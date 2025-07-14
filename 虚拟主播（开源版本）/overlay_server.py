import asyncio
from aiohttp import web, WSMsgType
from typing import Set
import pathlib

_clients: Set[web.WebSocketResponse] = set()
_app: web.Application | None = None
_BASE_DIR = pathlib.Path(__file__).resolve().parent / "overlay"

async def _ws_handler(request: web.Request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    _clients.add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                pass
    finally:
        _clients.discard(ws)
    return ws

async def ensure_server(host: str = "127.0.0.1", port: int = 8765):
    global _app
    if _app is not None:
        return
    _app = web.Application()
    _app.router.add_get("/ws", _ws_handler)

    async def _index(request):
        return web.FileResponse(_BASE_DIR / "overlay.html")

    _app.router.add_get("/", _index)
    _app.router.add_static("/", str(_BASE_DIR), show_index=False)

    runner = web.AppRunner(_app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

async def push_subtitle(text: str):
    dead = []
    for ws in list(_clients):
        try:
            await ws.send_str(text)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws) 