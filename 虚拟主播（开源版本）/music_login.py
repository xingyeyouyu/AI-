"""music_login.py
网易云音乐登录工具。
默认走『扫码登录』，也提供手机、邮箱登录接口，成功后返回 httpx.AsyncClient，已携带 Cookie，可给 ai_action 使用。
用法示例：
    from music_login import get_netease_client
    client = await get_netease_client()  # 首次会自动完成扫码
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import pathlib
import sys
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_API_BASE = "https://163api.qijieya.cn"

# -- 全局单例 ---------------------------------------------------------------

_client: Optional[httpx.AsyncClient] = None

# 本地持久化的 Cookie 文件
_COOKIE_FILE = pathlib.Path.home() / ".netease_cookie.txt"

async def get_netease_client(force_login: bool | None = None) -> httpx.AsyncClient:
    """获取带登录 Cookie 的 AsyncClient。

    参数说明
    ----------
    force_login : bool | None, optional
        - ``True``  : 强制扫码登录（忽略本地 Cookie）。
        - ``False`` : 不登录，直接匿名访问。
        - ``None``  : 运行时询问用户 y/n（*每次启动都会询问*）。
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

    # 构造初始 headers
    headers: dict[str, str] = {"User-Agent": "Mozilla/5.0"}

    # 尝试读取历史 Cookie
    if _COOKIE_FILE.exists():
        saved_cookie = _COOKIE_FILE.read_text(encoding="utf-8").strip()
        if saved_cookie:
            headers["Cookie"] = saved_cookie

    _client = httpx.AsyncClient(base_url=_API_BASE, timeout=10, headers=headers)

    # 如果已携带 Cookie 且本次不要求强制登录，则先检测是否仍然有效
    if not force_login and "Cookie" in _client.headers:
        try:
            if await _check_login(_client):
                logger.info("✅ 检测到有效网易云登录 Cookie，直接复用")
                return _client
            else:
                logger.info("ℹ️ 本地 Cookie 已失效，需要重新登录…")
        except Exception as exc:  # noqa: BLE001
            logger.debug("登录状态检查失败: %s", exc)

    # 此时未登录 / Cookie 失效，根据 force_login 参数决定后续流程
    if force_login is False:
        logger.info("ℹ️ 未登录状态，继续匿名访问（force_login=False）")
        return _client

    if force_login is None:
        # 仅在需要登录时才询问用户
        try:
            ans = input("Cookie 已失效，需要扫码登录才能播放 VIP 歌曲，是否继续？(y/N): ").strip().lower()
            force_login = ans in {"y", "yes", "1"}
        except EOFError:
            force_login = False

    if not force_login:
        logger.info("ℹ️ 用户选择跳过登录，继续匿名模式")
        return _client

    # 执行扫码登录
    await _login_qrcode(_client)

    # 将新的 Cookie 写入本地文件，供下次启动直接复用
    try:
        _COOKIE_FILE.write_text(_client.headers.get("Cookie", ""), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("写入 Cookie 文件失败: %s", exc)

    return _client

# -- 登录方式 ---------------------------------------------------------------

async def _check_login(client: httpx.AsyncClient) -> bool:
    try:
        r = await client.post("/login/status")
        data = r.json()
        return data.get("data", {}).get("account", {}) != {}
    except Exception:  # noqa: BLE001
        return False

async def _login_qrcode(client: httpx.AsyncClient):
    """命令行扫码登录（在终端直接渲染二维码）。"""
    # 1. 获取 key
    r = await client.get("/login/qr/key", params={"timestamp": _ts()})
    key = r.json().get("data", {}).get("unikey")
    if not key:
        raise RuntimeError("无法获取扫码 key")

    # 2. 获取二维码 base64 + URL
    r = await client.get("/login/qr/create", params={"key": key, "qrimg": True, "timestamp": _ts()})
    data = r.json().get("data", {})
    qr_base64 = data.get("qrimg", "")
    qr_url = data.get("qrurl") or data.get("url")
    if not qr_base64:
        raise RuntimeError("无法获取二维码图片")

    qr_path = pathlib.Path.cwd() / "netease_qr.png"
    qr_path.write_bytes(base64.b64decode(qr_base64.split("base64,")[-1]))
    logger.info("📱 请用网易云音乐 App 扫描二维码 (%s) 登录...", qr_path)

    # 在终端渲染 ASCII 二维码
    _render_qr_terminal(qr_url)

    # 不再自动弹出本地图片，简化交互
    # 3. 轮询扫码状态
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
            # 设置 Cookie：优先 JSON 返回的 cookie 字段，其次响应 cookies
            json_cookie = r.json().get("cookie", "")
            if not json_cookie:
                # 组合所有 Set-Cookie 为标准 Cookie 头
                cookie_pairs = [f"{k}={v}" for k, v in r.cookies.items()]
                json_cookie = "; ".join(cookie_pairs)
            client.headers["Cookie"] = json_cookie
            break
    # 清理二维码文件
    try:
        qr_path.unlink(missing_ok=True)
    except Exception:
        pass

async def login_phone(phone: str, password: str, country_code: int = 86, md5: bool = False):
    client = await get_netease_client()
    r = await client.post(
        "/login/cellphone",
        data={
            "phone": phone,
            "password": password,
            "countrycode": country_code,
            "md5_password": password if md5 else "",
        },
    )
    if r.json().get("code") != 200:
        raise RuntimeError("手机登录失败")

async def login_email(email: str, password: str):
    client = await get_netease_client()
    r = await client.post("/login", data={"email": email, "password": password})
    if r.json().get("code") != 200:
        raise RuntimeError("邮箱登录失败")

# -- 工具 -------------------------------------------------------------------

def _ts() -> int:
    import time
    return int(time.time() * 1000)

# -- 终端二维码渲染 ----------------------------------------------------------

def _render_qr_terminal(url: str | None):
    """在终端输出二维码（ASCII 形式）。若渲染失败则打印链接。"""
    if not url:
        return
    try:
        import qrcode  # noqa: WPS433 (third-party optional dependency)
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("终端二维码渲染失败: %s", exc)
        logger.info("📎 请在浏览器打开以下链接完成扫码登录: %s", url) 