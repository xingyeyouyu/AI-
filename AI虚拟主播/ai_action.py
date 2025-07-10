"""ai_action.py
集中处理 AI 回复中的『功能控制指令』，例如点歌、切换模式等。
后续若要扩展更多指令，只需在 `dispatch_actions` 内添加相应逻辑。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional
import os
import random
import tempfile
import pathlib
import uuid
import time
import subprocess  # 用于启动独立播放器进程

import httpx
import pygame
from music_login import get_netease_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 🎵 网易云音乐播放
# ---------------------------------------------------------------------------

_API_BASE = "https://163api.qijieya.cn"

# 默认纯音乐歌单 ID（ACG 纯音乐）
_DEFAULT_BGM_PLAYLIST_ID = 2387965986

# ---- 背景音乐状态 ----
_bgm_enabled: bool = False
_bgm_proc: Optional[subprocess.Popen] = None  # 当前 BGM 播放进程句柄
_bgm_task: Optional[asyncio.Task] = None      # 背景循环任务句柄
_current_track_end: float = 0.0  # monotonic time when当前曲目结束

# ---------------------------------------------------------------------------
# ♫ 队列化播放：点歌优先，BGM 兜底
# ---------------------------------------------------------------------------

# 优先级 0：观众/AI 点播歌曲
_point_q: asyncio.Queue[str] = asyncio.Queue()

# 优先级 1：后台 BGM 随机循环
_bgm_q: asyncio.Queue[str] = asyncio.Queue(maxsize=50)

_music_worker_task: Optional[asyncio.Task] = None  # 全局播放协程

async def _spawn_ffplay(url: str, volume: float = 0.25):
    """包装 ffplay 调用，volume 0~1；若 ffplay 返回非 0 则记录日志"""
    vol = int(volume * 100)
    cmd = f'ffplay -nodisp -autoexit -loglevel quiet -volume {vol} "{url}"'
    proc = await asyncio.create_subprocess_shell(cmd)
    rc = await proc.wait()
    if rc != 0:
        logger.warning("ffplay 退出码 %s，可能无法直接流式播放: %s", rc, url)

async def _music_worker():
    """永驻协程：点歌队列优先，其次 BGM。确保不会并发播放。"""
    global _bgm_enabled
    while True:
        try:
            # 点歌优先：播放前暂停 BGM，播放完毕后（且队列已空）再恢复
            if not _point_q.empty():
                url = await _point_q.get()

                # 1) 暂停正在播放的 BGM（若有）
                pause_background_music()

                # 2) 播放点歌音频
                await _spawn_ffplay(url, volume=float(os.getenv("MUSIC_VOLUME", "0.25")))

                # 3) 若队列已空，则恢复 BGM
                if _point_q.empty():
                    resume_background_music()

                # 点歌处理完毕后立即进入下一轮循环
                continue

            # 若 BGM 关闭则休眠
            if not _bgm_enabled:
                await asyncio.sleep(1)
                continue

            # 取/补充 BGM 队列
            if _bgm_q.empty():
                # 重新洗牌歌单
                ids = await _fetch_playlist_track_ids(_DEFAULT_BGM_PLAYLIST_ID)
                random.shuffle(ids)
                for _id in ids:
                    url = await _netease_get_song_url(_id)
                    if url:
                        await _bgm_q.put(url)
                        # 立即跳出，优先开始播放首曲
                        break

            url = await _bgm_q.get()
            # 播放 BGM：阻塞等待曲目结束，点歌时通过 pause_background_music() 终止
            await _play_bgm(url)

            # 循环队列：将已播放歌曲重新放回队尾
            try:
                await _bgm_q.put(url)
            except asyncio.QueueFull:
                # 若队列满则丢弃最旧的一首，确保循环继续
                _ = await _bgm_q.get()
                await _bgm_q.put(url)
        except Exception as e:
            logger.error("music_worker error: %s", e)
            await asyncio.sleep(5)

async def _netease_search_song(keyword: str) -> Optional[int]:
    """搜索歌曲并返回第一条 ID。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{_API_BASE}/search", params={"keywords": keyword})
            data = r.json()
            # 登录受限判断
            if data.get("code") in {301, 401}:
                logger.info("🔒 接口需要登录，自动调用扫码登录…")
                login_cli = await get_netease_client()
                r = await login_cli.get("/search", params={"keywords": keyword})
                data = r.json()
            songs = data.get("result", {}).get("songs", [])
            if songs:
                return songs[0].get("id")
    except Exception as exc:  # noqa: BLE001
        logger.error("网易云搜索失败: %s", exc)
    return None

async def _netease_get_song_url(song_id: int) -> Optional[str]:
    """获取歌曲播放 URL（优先带 Cookie 请求 /song/url/v1 获取完整音质）。"""
    try:
        login_cli = await get_netease_client()  # 确保已登录
        # 尝试无损 / 极高音质，按需回退
        for level in ("lossless", "exhigh", "standard"):
            try:
                r = await login_cli.get(
                    "/song/url/v1",
                    params={
                        "id": song_id,
                        "level": level,
                        # 根据 NeteaseCloudMusicApi 文档，附带 cookie 可拿到 VIP 资源
                        "cookie": login_cli.headers.get("Cookie", ""),
                    },
                )
                data = r.json()
                urls = data.get("data", [])
                for _item in urls:
                    if _item.get("url") and not _item.get("freeTrialInfo"):
                        return _item["url"]
                # 若全为试听，暂不返回，继续降级
            except Exception:
                continue
        # 若仍失败，改用匿名接口（可能返回试听片段）
        async with httpx.AsyncClient(timeout=10) as anon:
            r = await anon.get(f"{_API_BASE}/song/url", params={"id": song_id})
            data = r.json()
            urls = data.get("data", [])
            # 过滤试听 URL
            for _item in urls:
                if _item.get("url") and not _item.get("freeTrialInfo"):
                    return _item["url"]
            # 仍未找到完整曲 → 返回首个试听 URL 兜底播放
            if urls and urls[0].get("url"):
                return urls[0]["url"]
    except Exception as exc:  # noqa: BLE001
        logger.error("获取歌曲 URL 失败: %s", exc)
    return None

async def _fetch_playlist_track_ids(playlist_id: int) -> list[int]:
    """返回歌单所有歌曲 ID。"""
    ids: list[int] = []
    try:
        login_cli = await get_netease_client(force_login=False)
        offset = 0
        while True:
            r = await login_cli.get(
                "/playlist/track/all",
                params={"id": playlist_id, "limit": 200, "offset": offset},
            )
            data = r.json()
            songs = data.get("songs", [])
            ids.extend([s.get("id") for s in songs if s.get("id")])
            if len(songs) < 200:
                break
            offset += 200
    except Exception as exc:
        logger.error("获取歌单失败: %s", exc)
    random.shuffle(ids)
    return ids

async def _bgm_loop(track_ids: list[int]):
    global _bgm_enabled
    idx = 0
    while _bgm_enabled:
        try:
            # 若当前曲目尚未播放完，等待
            if time.monotonic() < _current_track_end:
                await asyncio.sleep(1)
                continue

            alive = _bgm_proc and (_bgm_proc.returncode is None)
            if not alive:
                if idx >= len(track_ids):
                    random.shuffle(track_ids)
                    idx = 0
                song_id = track_ids[idx]
                idx += 1
                url = await _netease_get_song_url(song_id)
                if not url:
                    continue
                await _play_bgm(url)
            await asyncio.sleep(1)
        except Exception as exc:
            logger.error("BGM 循环异常: %s", exc)
            await asyncio.sleep(5)

async def _play_bgm(url: str):
    try:
        proxy_url = os.getenv("MUSIC_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        async with httpx.AsyncClient(timeout=20, proxies=proxy_url or None) as client:
            r = await client.get(url)
            r.raise_for_status()
            audio_bytes = r.content

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.set_num_channels(4)

        tmp = pathlib.Path(tempfile.gettempdir()) / f"bgm_{uuid.uuid4().hex}.mp3"
        tmp.write_bytes(audio_bytes)

        vol = int(float(os.getenv("BGM_VOLUME", "0.30")) * 100)  # ffplay 音量 0~100
        cmd = f'ffplay -nodisp -autoexit -loglevel quiet -volume {vol} "{tmp}"'
        global _bgm_proc, _current_track_end  # noqa: PLW0603
        _bgm_proc = await asyncio.create_subprocess_shell(cmd)
        logger.info("🎧 [ffplay] 播放背景音乐: %s", url)

        # 估算长度：简单等待 180s 作为兜底；可替换为实际长度
        _current_track_end = time.monotonic() + 180

        await _bgm_proc.wait()
        _bgm_proc = None
        _current_track_end = 0.0
        logger.debug("🎧 BGM 曲目结束")
    except Exception as exc:
        logger.error("播放背景音乐失败: %s", exc)

async def start_background_music():
    """启动后台纯音乐播放任务（若未启动）。"""
    global _bgm_enabled
    if _bgm_enabled:
        return
    _bgm_enabled = True

    # 若已在跑 worker，不重复启动
    global _music_worker_task
    if _music_worker_task is None or _music_worker_task.done():
        _music_worker_task = asyncio.create_task(_music_worker())

def pause_background_music():
    global _bgm_proc
    if _bgm_proc and _bgm_proc.returncode is None:
        _bgm_proc.terminate()
        _bgm_proc = None

def resume_background_music():
    if _bgm_enabled and not (_bgm_proc and _bgm_proc.returncode is None):
        # 重新启动循环任务
        asyncio.create_task(start_background_music())

def stop_background_music():
    global _bgm_enabled
    _bgm_enabled = False
    global _bgm_proc, _bgm_task, _music_worker_task
    if _bgm_proc and _bgm_proc.returncode is None:
        _bgm_proc.terminate()
    _bgm_proc = None
    if _bgm_task:
        _bgm_task.cancel()
    if _music_worker_task:
        _music_worker_task.cancel()

def configure_bgm(playlist_id: Optional[int] = None, volume: Optional[float] = None):
    """由外部配置调用，动态调整 BGM 歌单和音量。"""
    global _DEFAULT_BGM_PLAYLIST_ID
    if playlist_id:
        _DEFAULT_BGM_PLAYLIST_ID = playlist_id
    if volume is not None:
        # 更新环境变量便于后续 Channel 创建
        os.environ["BGM_VOLUME"] = str(volume)

    # 若后台音乐未开启，则自动启动
    if not _bgm_enabled:
        asyncio.create_task(start_background_music())

# ---------------------------------------------------------------------------
# 🎛️ 总调度
# ---------------------------------------------------------------------------

_MUSIC_PATTERN = re.compile(r"\*\[Music\]:(?P<song>[^*.]+?)(?:\.(?P<artist>[^*]+))?\*", flags=re.IGNORECASE)
_VOICE_PATTERN = re.compile(r"\*\[voice\]:(?P<content>[^*]+?)\*", flags=re.IGNORECASE)  # 保留向后兼容

# 通用指令格式 *[Action]:Content*
_ACTION_PATTERN = re.compile(r"\*\[(?P<action>[A-Za-z]+)\]:(?P<content>[^*]+?)\*", flags=re.IGNORECASE)

_STAR_WRAP_PATTERN = re.compile(r"\*(?!\[)([^*]+?)\*")  # 匹配非指令的 *文本*

async def dispatch_actions(ai_reply: str):
    """扫描 AI 回复，触发对应动作 (Music / Voice / 未来其它)。"""
    try:
        for m in _ACTION_PATTERN.finditer(ai_reply):
            action = m.group("action").lower()
            content = m.group("content").strip()

            if action == "music":
                # None 表示停止背景音乐
                if content.lower() in {"none", "off", "stop"}:
                    stop_background_music()
                    continue
                # content 格式: 歌名 或 歌名.歌手
                if "." in content:
                    song, artist = content.split(".", 1)
                    await handle_music_command(song.strip(), artist.strip())
                else:
                    await handle_music_command(content, None)
            elif action == "bgm":
                raw = content.strip()
                # 控制指令必须写成 *[BGM]:"open"* / *[BGM]:"close"*
                if (raw.startswith("\"") and raw.endswith("\"")) or (raw.startswith("'") and raw.endswith("'")):
                    keyword = raw.strip("'\"").lower()
                    if keyword in {"open", "on", "start"}:
                        await start_background_music()
                    elif keyword in {"close", "off", "stop"}:
                        stop_background_music()
                    continue  # 不向下传递
                # 非引号包裹则视为切换歌单名称/ID，可在此扩展
                try:
                    playlist_id = parse_playlist_id(raw)
                    if playlist_id:
                        configure_bgm(playlist_id=playlist_id)
                        logger.info("🎶 已切换 BGM 歌单 ID=%s", playlist_id)
                except Exception:
                    pass
                continue
            elif action == "voice":
                # 语音指令无需特殊处理（下游 TTS 会朗读内容）
                continue
            else:
                # 未识别动作 -> 当普通文本处理
                logger.debug("未知动作指令 [%s]，按普通文本处理", action)
    except Exception as exc:  # noqa: BLE001
        logger.error("动作调度失败: %s", exc)

def _replace_action(match: re.Match[str]) -> str:
    """strip_control_sequences 的替换回调"""
    action = match.group("action").lower()
    content = match.group("content").strip()
    # Music 指令已被 dispatch 消耗，这里清除文本；其它动作保留内容
    return "" if action in {"music", "bgm"} else content

def strip_control_sequences(ai_reply: str) -> str:
    """去掉控制指令后返回纯文本，供后续 TTS / 弹幕。"""
    # 1) 处理所有 *[Action]:Content*
    text = _ACTION_PATTERN.sub(_replace_action, ai_reply)
    # 2) 再处理残余兼容 pattern（如旧版 _VOICE_PATTERN）
    text = _VOICE_PATTERN.sub(lambda m: m.group("content").strip(), text)
    # 3) 将 *普通文本* -> 普通文本
    text = _STAR_WRAP_PATTERN.sub(r"\1", text)
    return text.strip()

async def handle_music_command(song: str, artist: Optional[str] = None):
    """处理点歌指令。"""
    keyword = f"{song} {artist}".strip() if artist else song
    song_id = await _netease_search_song(keyword)
    if not song_id:
        logger.warning("⚠️ 未找到歌曲: %s", keyword)
        return
    url = await _netease_get_song_url(song_id)
    if not url:
        logger.warning("⚠️ 未获取到歌曲播放 URL (id=%s)", song_id)
        return
    await _play_music(url)

# ---------------------------------------------------------------------------
# 修改 _play_music 以暂停/恢复 BGM
# ---------------------------------------------------------------------------

async def _play_music(url: str):
    """异步播放远程歌曲 (下载到内存后播放)。"""
    # 点歌改为入队，由 _music_worker 统一调度
    await _point_q.put(url)
    logger.info("🎵 已加入点歌队列: %s (len=%d)", url, _point_q.qsize())
    return

def parse_playlist_id(raw: str | int | None) -> Optional[int]:
    """从数字或网易云歌单 URL 中提取歌单 ID。

    支持以下形式::

        123456789                     # 纯数字
        https://music.163.com/#/playlist?id=123456789
        @https://music.163.com/playlist?id=123456789   # 前缀 @ 来源于聊天引用
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw

    raw = str(raw).strip()
    # 去掉前缀符号（如 @）
    if raw.startswith("@"):
        raw = raw[1:]

    if raw.isdigit():
        return int(raw)
    m = re.search(r"id=(\d+)", raw)
    return int(m.group(1)) if m else None 