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
import subprocess
import signal  # for cross-platform kill

import httpx
import pygame
from music_login import get_netease_client

# 获取logger
logger = logging.getLogger(__name__)

# --- VTS expression controller integration ---
# ---- 动态定位项目根目录 -----------------------------------------------
from pathlib import Path
import sys

curr = Path(__file__).resolve()
project_root = curr.parent  # fallback
for p in curr.parents:
    if (p / "vts_expression_controller.py").exists():
        project_root = p
        break

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
from vts_expression_controller import VTSController  # noqa: E402

# Global VTS controller instance (lazy connect)
_vts_ctrl: VTSController | None = None

async def _ensure_vts_connected():
    global _vts_ctrl
    if _vts_ctrl is None:
        _vts_ctrl = VTSController()
        await _vts_ctrl.connect()

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

# Utility to build ffplay command list (no shell needed)
def _build_ffplay_cmd(path_or_url: str, volume: int) -> list[str]:
    return [
        "ffplay",
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "quiet",
        "-volume",
        str(volume),
        path_or_url,
    ]

async def _spawn_ffplay(url: str, volume: float = 0.25):
    """启动 ffplay 播放远程 URL，不使用 shell，以便后续准确终止进程"""
    vol = int(volume * 100)
    proc = await asyncio.create_subprocess_exec(*_build_ffplay_cmd(url, vol))
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
    """无限循环播放歌单内曲目（单首结束->play_next）"""
    while _bgm_enabled:
        # 随机遍历播放歌单内所有曲目
        random.shuffle(track_ids)
        for track_id in track_ids:
            # 中途已关闭则退出
            if not _bgm_enabled:
                break

            # 获取歌曲播放地址
            url = await _netease_get_song_url(track_id)
            if not url:
                logger.error("获取歌曲播放地址失败，跳过")
                continue

            # 播放当前曲目（阻塞等待播放结束）
            await _play_bgm(url)

async def _play_bgm(url: str):
    """播放单首 BGM，直到播放完毕、异常、或被暂停/关闭"""
    global _bgm_proc, _current_track_end
    if not _bgm_enabled:
        return

    logger.debug("播放 BGM: %s", url)
    # 启动独立播放进程（阻止 SIGINT 传递，避免主程序关闭）
    args = _build_ffplay_cmd(url, int(float(os.getenv("MUSIC_VOLUME", "0.25")) * 100))
    _bgm_proc = subprocess.Popen(
        args,
        # 重要：START_NEW_SESSION 避免 SIGINT 传递给子进程 (Windows 不支持 preexec_fn)
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        preexec_fn=None if os.name == "nt" else os.setpgrp,
    )
    # 设置预期结束时间（便于其他函数查询）
    _current_track_end = time.monotonic() + 300  # 假设曲目 5 分钟

    # 等待播放完毕或被暂停/关闭
    while _bgm_proc and _bgm_proc.poll() is None and _bgm_enabled:
        await asyncio.sleep(0.5)

    # 确保进程已终止（如果仍在运行且已暂停/关闭）
    if _bgm_proc and _bgm_proc.poll() is None:
        # Windows 下使用 CTRL_BREAK_EVENT 终止 ffplay
        if os.name == "nt":
            _bgm_proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            # Unix 系统下，优先 SIGTERM，避免立即杀死（给 IO 清理时间）
            _bgm_proc.send_signal(signal.SIGTERM)
        try:
            # 等待 2 秒，一般足够进程优雅退出
            _bgm_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            # 2 秒后仍未退出，强制结束
            _bgm_proc.kill()
    _bgm_proc = None
    _current_track_end = 0

async def start_background_music():
    """启动背景音乐（使用队列机制以支持点歌插队）"""
    global _bgm_enabled, _music_worker_task
    _bgm_enabled = True

    if _music_worker_task is None or _music_worker_task.done():
        _music_worker_task = asyncio.create_task(_music_worker())
        logger.info("✅ 已启动音乐播放工作线程")

def pause_background_music():
    """暂停背景音乐（关闭当前播放的进程）"""
    global _bgm_proc
    if _bgm_proc and _bgm_proc.poll() is None:
        if os.name == "nt":
            _bgm_proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            _bgm_proc.send_signal(signal.SIGTERM)

def resume_background_music():
    """恢复背景音乐（重新播放新曲目）"""
    global _bgm_enabled
    _bgm_enabled = True

def stop_background_music():
    """停止背景音乐（关闭进程并禁用标记）"""
    global _bgm_enabled, _bgm_proc, _music_worker_task
    # 1) 停用标记，防止再启动新任务
    _bgm_enabled = False

    # 2) 终止当前播放进程
    if _bgm_proc and _bgm_proc.poll() is None:
        if os.name == "nt":
            _bgm_proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            _bgm_proc.send_signal(signal.SIGTERM)
        try:
            _bgm_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _bgm_proc.kill()
        _bgm_proc = None

    # 3) 清空队列
    while not _point_q.empty():
        try:
            _point_q.get_nowait()
        except:
            pass

    while not _bgm_q.empty():
        try:
            _bgm_q.get_nowait()
        except:
            pass

def configure_bgm(playlist_id: Optional[int] = None, volume: Optional[float] = None):
    """配置背景音乐的播放列表和音量"""
    global _DEFAULT_BGM_PLAYLIST_ID
    # 设置播放列表 ID
    if playlist_id:
        _DEFAULT_BGM_PLAYLIST_ID = playlist_id
        logger.info("已设置BGM歌单ID: %s", playlist_id)
    
    # 设置音量
    if volume is not None:
        # 限制在 0.0 ~ 1.0 之间
        vol = max(0.0, min(1.0, volume))
        os.environ["MUSIC_VOLUME"] = str(vol)
        logger.info("已设置音乐音量: %.2f", vol)
    
    # 返回当前配置
    return {
        "playlist_id": _DEFAULT_BGM_PLAYLIST_ID,
        "volume": float(os.getenv("MUSIC_VOLUME", "0.25"))
    }

# ---------------------------------------------------------------------------
# 🤖 AI 控制指令分发
# ---------------------------------------------------------------------------

# 正则模式: 提取控制语句
_ACTION_PATTERN = re.compile(r'#\[(.+?):(.*?)\]')

async def dispatch_actions(ai_reply: str):
    """
    派发 AI 回复中的控制指令
    指令格式: #[action:param]
    """
    actions = _ACTION_PATTERN.findall(ai_reply)
    for action, param in actions:
        action = action.strip().lower()
        param = param.strip()
        logger.debug(f"检测到控制指令: {action}:{param}")
        
        try:
            if action == "play" or action == "music":
                # 音乐控制: #[play:歌曲名] 或 #[music:歌曲名]
                await handle_music_command(param)
            
            elif action == "bgm":
                # 背景音乐控制: #[bgm:on/off]
                if param.lower() in ("on", "start", "true", "1"):
                    await start_background_music()
                    logger.info("✅ 已开启背景音乐")
                elif param.lower() in ("off", "stop", "false", "0"):
                    stop_background_music()
                    logger.info("🛑 已关闭背景音乐")
            
            elif action == "expression" or action == "emoji":
                # 表情控制: #[expression:smile] 或 #[emoji:smile]
                await _ensure_vts_connected()
                if _vts_ctrl:
                    await _vts_ctrl.trigger_expression(param.lower())
                    logger.info(f"👾 已触发表情: {param}")
            
            elif action == "idle":
                # 空闲动画: #[idle:start/stop]
                if param.lower() in ("start", "on", "true", "1"):
                    await schedule_idle_animation()
                    logger.info("🎭 已启动空闲动画")
                elif param.lower() in ("stop", "off", "false", "0"):
                    await cancel_idle_animation()
                    logger.info("🎭 已停止空闲动画")

        except Exception as e:
            logger.error(f"执行控制指令 {action}:{param} 出错: {e}")
    
    # 返回去除控制指令后的文本
    return _ACTION_PATTERN.sub(_replace_action, ai_reply)

def _replace_action(match: re.Match[str]) -> str:
    """将控制指令替换为空字符串（从文本中移除）"""
    action = match.group(1).strip().lower()
    param = match.group(2).strip()
    # 设计决策：从最终文本中完全删除控制指令
    return ""

def strip_control_sequences(ai_reply: str) -> str:
    """仅清除控制序列，不执行"""
    return _ACTION_PATTERN.sub(_replace_action, ai_reply)

# ---------------------------------------------------------------------------
# 🎵 点歌处理
# ---------------------------------------------------------------------------

async def handle_music_command(song: str, artist: Optional[str] = None):
    """处理点歌指令"""
    # 构建搜索关键词
    keyword = song
    if artist:
        keyword = f"{song} {artist}"
    
    logger.info(f"🎵 正在搜索歌曲: {keyword}")
    song_id = await _netease_search_song(keyword)
    
    if song_id:
        url = await _netease_get_song_url(song_id)
        if url:
            await _play_music(url)
            return True
    
    logger.error(f"❌ 未找到歌曲: {keyword}")
    return False

async def _play_music(url: str):
    """将歌曲URL加入播放队列"""
    await _point_q.put(url)
    logger.info("🎵 已加入播放队列")

# ---------------------------------------------------------------------------
# 🎯 辅助函数
# ---------------------------------------------------------------------------

def parse_playlist_id(raw: str | int | None) -> Optional[int]:
    """从各种格式解析歌单ID"""
    if raw is None:
        return None
    
    try:
        # 如果是数字，直接返回
        if isinstance(raw, int):
            return raw
        
        # 如果是空字符串，返回None
        if not raw.strip():
            return None
        
        # 尝试作为纯数字解析
        try:
            return int(raw.strip())
        except ValueError:
            pass
        
        # 尝试从URL中提取
        id_patterns = [
            r'playlist[/=](\d+)',  # playlist/123456 或 playlist=123456
            r'[?&]id=(\d+)',       # ?id=123456 或 &id=123456
            r'[/=](\d{5,})',       # 末尾是5位以上数字
        ]
        
        for pattern in id_patterns:
            match = re.search(pattern, raw)
            if match:
                return int(match.group(1))
        
    except Exception as e:
        logger.error(f"解析歌单ID失败: {e}")
    
    return None

# ---------------------------------------------------------------------------
# 🎭 VTS 空闲动画控制
# ---------------------------------------------------------------------------

_idle_task = None
_idle_cancelled = asyncio.Event()

async def schedule_idle_animation():
    """调度VTS空闲动画（每30秒随机触发一个动画）"""
    global _idle_task, _idle_cancelled
    
    # 确保没有正在运行的空闲任务
    await cancel_idle_animation(trigger_break=False)
    _idle_cancelled.clear()
    
    async def _timer():
        # 空闲动画列表
        idle_expressions = ["blink", "smile", "thinking", "lookaway", "surprised"]
        
        while not _idle_cancelled.is_set():
            # 随机等待20-60秒
            try:
                await asyncio.wait_for(
                    _idle_cancelled.wait(), 
                    timeout=random.randint(20, 60)
                )
            except asyncio.TimeoutError:
                # 超时，触发随机动画
                if not _idle_cancelled.is_set():
                    try:
                        await _ensure_vts_connected()
                        if _vts_ctrl:
                            expr = random.choice(idle_expressions)
                            await _vts_ctrl.trigger_expression(expr)
                            logger.debug(f"触发空闲动画: {expr}")
                    except Exception as e:
                        logger.error(f"触发空闲动画失败: {e}")
    
    _idle_task = asyncio.create_task(_timer())
    logger.debug("空闲动画调度已启动")

async def cancel_idle_animation(trigger_break: bool = True):
    """取消VTS空闲动画调度"""
    global _idle_task, _idle_cancelled
    
    # 设置取消信号
    _idle_cancelled.set()
    
    # 如果有任务，等待它完成
    if _idle_task:
        try:
            await asyncio.wait_for(_idle_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _idle_task.cancel()
        _idle_task = None
    
    if trigger_break and _vts_ctrl:
        # 可选：触发一个打断当前表情的动作
        try:
            await _vts_ctrl.reset_all_expressions()
            logger.debug("已重置所有表情")
        except:
            pass
    
    logger.debug("空闲动画调度已取消") 
 
 
 
 
 