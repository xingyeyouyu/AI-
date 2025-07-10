"""music_login.py (GitHub-safe subset)
提供网易云音乐扫码登录工具，**每次** 调用都要求重新扫码验证。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import pathlib
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://163api.qijieya.cn"

_client: Optional[httpx.AsyncClient] = None
# 本地持久化 Cookie 文件
_COOKIE_FILE = pathlib.Path.home() / ".netease_cookie.txt"


async def get_netease_client(force_login: bool | None = None) -> httpx.AsyncClient:
    """返回登录或匿名的 AsyncClient。

    - ``force_login=True``  强制扫码
    - ``force_login=False`` 匿名
    - ``None``             运行时询问用户 y/n（*每次启动都会询问*）
    """
    global _client  # noqa: PLW0603
    if _client is not None:
        return _client

    # ----------------------------
    # NEW: 统一在首次调用时询问用户是否重新登录
    # ----------------------------
    if force_login is None:
        try:
            ans = input("是否需要重新扫码登录网易云音乐？(y/N): ").strip().lower()
            force_login = ans in {"y", "yes", "1"}
        except EOFError:
            force_login = False

    headers: dict[str, str] = {"User-Agent": "Mozilla/5.0"}
    # 读取历史 Cookie
    if _COOKIE_FILE.exists():
        saved_cookie = _COOKIE_FILE.read_text(encoding="utf-8").strip()
        if saved_cookie:
            headers["Cookie"] = saved_cookie

    _client = httpx.AsyncClient(base_url=_API_BASE, timeout=10, headers=headers)

    # 检查 Cookie 是否仍然有效（若未要求强制登录）
    if not force_login and "Cookie" in _client.headers:
        try:
            if await _check_login(_client):
                logger.info("✅ 检测到有效网易云登录 Cookie，直接复用")
                return _client
            else:
                logger.info("ℹ️ 本地 Cookie 已失效，需要重新登录…")
        except Exception as exc:
            logger.debug("登录状态检查失败: %s", exc)

    if force_login is False:
        logger.info("ℹ️ 未登录状态，继续匿名访问（force_login=False）")
        return _client

    if force_login is None:
        try:
            ans = input("Cookie 已失效，需要扫码登录才能播放 VIP 歌曲，是否继续？(y/N): ").strip().lower()
            force_login = ans in {"y", "yes", "1"}
        except EOFError:
            force_login = False

    if not force_login:
        logger.info("ℹ️ 用户选择跳过登录，继续匿名模式")
        return _client

    await _login_qrcode(_client)

    try:
        _COOKIE_FILE.write_text(_client.headers.get("Cookie", ""), encoding="utf-8")
    except Exception as exc:
        logger.debug("写入 Cookie 文件失败: %s", exc)

    return _client


async def _login_qrcode(client: httpx.AsyncClient):
    r = await client.get("/login/qr/key", params={"timestamp": _ts()})
    key = r.json().get("data", {}).get("unikey")
    if not key:
        raise RuntimeError("无法获取扫码 key")

    r = await client.get("/login/qr/create", params={"key": key, "qrimg": True, "timestamp": _ts()})
    data = r.json().get("data", {})
    qr_base64 = data.get("qrimg", "")
    qr_url = data.get("qrurl") or data.get("url")
    if not qr_base64:
        raise RuntimeError("无法获取二维码图片")

    qr_path = pathlib.Path.cwd() / "netease_qr.png"
    qr_path.write_bytes(base64.b64decode(qr_base64.split("base64,")[-1]))
    logger.info("📱 请用网易云音乐 App 扫描二维码 (%s) 登录...", qr_path)

    _render_qr_terminal(qr_url)

    while True:
        await asyncio.sleep(2)
        r = await client.get("/login/qr/check", params={"key": key, "timestamp": _ts()})
        code = r.json().get("code")
        if code == 800:
            raise RuntimeError("二维码已失效，请重新运行登录")
        if code == 801:
            continue  # 等待扫码
        if code == 802:
            logger.info("✅ 已扫描，请在手机确认登录")
            continue
        if code == 803:
            logger.info("🎉 登录成功！")
            # 设置 Cookie 字符串
            json_cookie = r.json().get("cookie", "")
            if not json_cookie:
                cookie_pairs = [f"{k}={v}" for k, v in r.cookies.items()]
                json_cookie = "; ".join(cookie_pairs)
            client.headers["Cookie"] = json_cookie
            break


def _ts() -> int:
    import time
    return int(time.time() * 1000)


def _render_qr_terminal(url: str | None):
    if not url:
        return
    try:
        import qrcode  # noqa: WPS433
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("终端二维码渲染失败: %s", exc)
        logger.info("📎 请在浏览器打开以下链接完成扫码登录: %s", url) 