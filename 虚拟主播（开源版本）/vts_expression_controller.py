import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

import websockets

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VTS_WEBSOCKET_URL = os.getenv("VTS_URL", "ws://127.0.0.1:8001")
PLUGIN_NAME = "Cursor Expression Controller"
PLUGIN_AUTHOR = "AI Assistant"
TOKEN_FILE = Path(".vts_token")

# ---------------------------------------------------------------------------
# Regex helpers for command parsing  e.g. <"脸红":on> , <"挥手">
# ---------------------------------------------------------------------------

COMMAND_PATTERN = re.compile(r"<\s*\"(?P<expr>.+?)\"\s*(?::\s*(?P<action>on|off))?\s*>")


class VTSController:
    """Minimal VTS hotkey controller supporting toggle and one-shot expressions."""

    def __init__(self, url: str = VTS_WEBSOCKET_URL):
        self.url = url
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.logger = logging.getLogger("VTS")
        self.req_id = 0
        self.hotkey_name2id: Dict[str, str] = {}
        # Keeps current *toggle* state, e.g. {"脸红": True}
        self.expr_state: Dict[str, bool] = {}
        # Expressions that do *not* need toggle – they fire once and finish.
        self.one_shot_exprs = {"挥手"}
        # Expressions to ignore entirely (not stored nor exposed to AI)
        self.ignored_exprs = {"expression1", "空"}
        # Timed expressions that auto-off after N seconds when turned on
        self.timed_expr_config = {"吐舌": 3}
        self._timed_tasks: Dict[str, asyncio.Task] = {}
        # ─── 纸扇开合专用状态 ───────────────────────────────────────────
        self.fan_toggle_name = "纸扇开合"  # 快捷键名称
        self.fan_open: bool = True  # 默认开扇（True=开，False=合）

    # -----------------------  low-level helpers  ---------------------------
    def _next_id(self) -> str:
        self.req_id += 1
        return f"req_{self.req_id}"

    async def _send(self, payload: dict) -> dict:
        if not self.ws:
            raise RuntimeError("WebSocket not connected")
        await self.ws.send(json.dumps(payload))
        raw = await self.ws.recv()
        return json.loads(raw)

    # -----------------------  connection / auth ---------------------------
    async def connect(self):
        self.logger.info("Connecting to VTS at %s", self.url)
        self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20)
        await self._authenticate()
        await self._build_hotkey_table()
        self.logger.info("Connection ready. Hotkeys loaded: %s", list(self.hotkey_name2id.keys()))

    async def _authenticate(self):
        """Complete token exchange + authentication according to VTS API."""

        # 1) Ensure we *have* a token (may have to request one) -----------------
        token = TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else None

        if not token:
            # Ask VTS for new token (this will trigger Allow-/Deny-popup)
            tok_req = {
                "apiName": "VTubeStudioPublicAPI",
                "apiVersion": "1.0",
                "requestID": self._next_id(),
                "messageType": "AuthenticationTokenRequest",
                "data": {
                    "pluginName": PLUGIN_NAME,
                    "pluginDeveloper": PLUGIN_AUTHOR,
                },
            }
            rsp = await self._send(tok_req)

            token = rsp.get("data", {}).get("authenticationToken")
            if not token:
                raise RuntimeError(
                    "Token request denied in VTS. Please open '插件配置/权限' 并允许运行。"
                )
            # Persist token for next session
            TOKEN_FILE.write_text(token)
            self.logger.info("Received and stored new VTS token.")

        # 2) Authenticate using token -----------------------------------------
        auth_req = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": self._next_id(),
            "messageType": "AuthenticationRequest",
            "data": {
                "pluginName": PLUGIN_NAME,
                "pluginDeveloper": PLUGIN_AUTHOR,
                "authenticationToken": token,
            },
        }

        rsp = await self._send(auth_req)
        if not rsp.get("data", {}).get("authenticated"):
            raise RuntimeError("Authentication failed. token may be invalid, delete .vts_token and retry.")

        self.logger.info("Plugin authenticated with VTS")

    async def _build_hotkey_table(self):
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": self._next_id(),
            "messageType": "HotkeysInCurrentModelRequest",
            "data": {},
        }
        rsp = await self._send(payload)
        for hk in rsp.get("data", {}).get("availableHotkeys", []):
            if hk["name"] not in self.ignored_exprs:
                self.hotkey_name2id[hk["name"]] = hk["hotkeyID"]

        if not self.hotkey_name2id:
            self.logger.warning("No hotkeys returned. Ensure a model is loaded and has expressions configured.")

    # -----------------------  high-level helpers --------------------------
    async def trigger_hotkey(self, name: str):
        hotkey_id = self.hotkey_name2id.get(name)
        if not hotkey_id:
            self.logger.warning("Hotkey '%s' not found in current model", name)
            return
        payload = {
            "apiName": "VTubeStudioPublicAPI",
            "apiVersion": "1.0",
            "requestID": self._next_id(),
            "messageType": "HotkeyTriggerRequest",
            "data": {"hotkeyID": hotkey_id},
        }
        await self._send(payload)
        self.logger.info("Triggered hotkey: %s (%s)", name, hotkey_id)

    # -----------------------  command handling ----------------------------
    async def handle_input(self, text: str):
        """Parse and handle all expression commands inside *text*."""
        for match in COMMAND_PATTERN.finditer(text):
            expr = match.group("expr")
            action = match.group("action")  # may be None

            # Ignore certain expressions completely
            if expr in self.ignored_exprs:
                continue

            # ---- handle fan toggle ----------------------------------------
            if expr == self.fan_toggle_name:
                # 无论当前开/合，直接触发并翻转状态
                await self.trigger_hotkey(expr)
                self.fan_open = not self.fan_open
                continue

            # One-shot expressions are *never* stored
            if expr in self.one_shot_exprs or action is None:
                await self.trigger_hotkey(expr)
                continue

            # Toggleable expression flow
            current_state = self.expr_state.get(expr, False)
            desired_on = action.lower() == "on"

            # If the desired state matches current, ignore to avoid double trigger
            if desired_on == current_state:
                self.logger.debug("Expression '%s' already in state %s", expr, desired_on)
                continue

            # Otherwise trigger and update state
            await self.trigger_hotkey(expr)
            self.expr_state[expr] = desired_on

            # Handle auto-off scheduling
            if desired_on and expr in self.timed_expr_config:
                # cancel existing timer
                if expr in self._timed_tasks:
                    self._timed_tasks[expr].cancel()

                delay = self.timed_expr_config[expr]

                async def _auto_off(name=str(expr)):
                    await asyncio.sleep(delay)
                    # Only off if still on
                    if self.expr_state.get(name):
                        await self.trigger_hotkey(name)
                        self.expr_state[name] = False
                        import logging as _lg; _lg.getLogger(__name__).info(f"⏲️ Timed auto-off for {name}")

                self._timed_tasks[expr] = asyncio.create_task(_auto_off())
            elif not desired_on and expr in self._timed_tasks:
                # manually turned off, cancel timer
                self._timed_tasks[expr].cancel()
                self._timed_tasks.pop(expr, None)

    # -----------------------  public state helpers ------------------------

    def get_current_states(self) -> Dict[str, bool]:
        """Return merged dict of all expression/group states.

        Key: expression or group name (e.g. "脸红" / "手持纸扇")
        Value: True if currently active (on/open), False otherwise.
        """
        states: Dict[str, bool] = {**self.expr_state}
        # 加入纸扇开合状态（True=开）
        states[self.fan_toggle_name] = self.fan_open
        return states

    def format_state_for_ai(self) -> str:
        """Return a short human-readable summary that can be prepended to LLM prompts."""
        parts = []
        for name, st in self.get_current_states().items():
            if name == self.fan_toggle_name:
                parts.append(f"{name}:{'开' if st else '合'}")
            else:
                parts.append(f"{name}:{'on' if st else 'off'}")
        if not parts:
            return "[State] none"
        return "[State] " + "; ".join(parts)


async def cli_loop():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    ctrl = VTSController()
    await ctrl.connect()

    print("Enter commands like <\"脸红\":on>  |  quit to exit")
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if line.lower() in {"quit", "exit"}:
            break
        await ctrl.handle_input(line)

    await ctrl.ws.close()


if __name__ == "__main__":
    try:
        asyncio.run(cli_loop())
    except KeyboardInterrupt:
        pass 