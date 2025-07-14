#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站AI虚拟主播弹幕回复系统 - 2025年终极版本
使用最新的blive库和bilibili-live库
支持弹幕监听、AI回复生成、语音合成、弹幕发送
"""

import asyncio
import random
import time
import configparser
from concurrent.futures import ThreadPoolExecutor
import threading
import queue
import traceback
import json
import sys  # ensure available for patch
import blive_patcher  # 注入Cookie+UA以绕过412
import six, types, urllib3
# 在导入 requests 之前补丁，确保 urllib3.packages.six 存在（urllib3>=2 移除后向兼容）
if not hasattr(urllib3, 'packages') or not getattr(urllib3, 'packages').__dict__.get('six', None):
    pkg_mod = types.ModuleType('urllib3.packages')
    pkg_mod.six = six
    sys.modules['urllib3.packages'] = pkg_mod
    sys.modules['urllib3.packages.six'] = six

# 同步映射 six.moves 及其子模块，避免 requests -> urllib3 导入
import importlib
moves_mod = importlib.import_module('six.moves')
sys.modules['urllib3.packages.six.moves'] = moves_mod
# 提前加载 http_client 子模块（在 six 内部是懒加载）
try:
    http_client_mod = importlib.import_module('six.moves.http_client')
    sys.modules['urllib3.packages.six.moves.http_client'] = http_client_mod
except Exception:
    pass

# 现在安全导入 requests
import requests
from typing import Optional, Dict, Any
import logging
import os
import yaml
from preset_loader import load_preset

# 游戏和语音相关
import pygame
# Edge TTS 移至适配器内部按需导入
import tts_adapter_loader  # 加载根目录的 tts_adapter
from tts_adapter import TTSAdapterFactory

# AI相关
import openai as deepseek
import httpx  # 用于自定义代理
# 网易云登录 (提前显示扫码二维码)
from music_login import get_netease_client
# 本地 LLM 适配器
from llm_adapter import LLMRouter
# AI 控制指令处理
from ai_action import dispatch_actions, strip_control_sequences, start_background_music, configure_bgm, parse_playlist_id

# 数据库配置
try:
    from database import config_db
    HAS_CONFIG_DB = True
except ImportError:
    HAS_CONFIG_DB = False

# B站弹幕相关 - 使用最新的bliver库
try:
    from blive import BLiver, Events, BLiverCtx
    from blive.msg import DanMuMsg
    BLIVE_AVAILABLE = True
except ImportError:
    BLIVE_AVAILABLE = False
    
# B站API相关 - 使用bilibili-live库发送弹幕
try:
    from bilibili_live.events import BilibiliLiveEventHandler, Danmu, Event
    from bilibili_live import BilibiliLive
    BILIBILI_LIVE_AVAILABLE = True
except ImportError:
    BILIBILI_LIVE_AVAILABLE = False
    # 定义空的基类以避免导入错误
    class BilibiliLiveEventHandler:
        pass
    class Danmu:
        pass
    class Event:
        pass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ai_vtuber_2025.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from util_fix import safe_print as print

print("🎌 B站AI虚拟主播弹幕回复系统 - 2025年终极版本")
print("🚀 启动中...")
logger.info("🔍 检查依赖库...")
logger.info(f"blive库: {'✅ 可用' if BLIVE_AVAILABLE else '❌ 不可用'}")
logger.info(f"bilibili-live库: {'✅ 可用' if BILIBILI_LIVE_AVAILABLE else '❌ 不可用'}")

from overlay_server import ensure_server, push_subtitle

# 旧的 `check_config` 和 `build_config_from_db` 函数已不再需要，
# 因为我们将直接从数据库读取配置。

class DanmakuSender:
    """现代化B站弹幕发送器"""
    
    def __init__(self, room_id: int, cookies: Dict[str, str]):
        self.room_id = room_id
        self.cookies = cookies
        self.session = requests.Session()

        # 重新构造仅包含 latin-1 值的 Cookie 头
        safe_cookie_pairs = []
        for k, v in cookies.items():
            try:
                v.encode('latin-1')
            except UnicodeEncodeError:
                logger.debug(f"Cookie 值非 latin-1, 已忽略: {k}")
                continue
            safe_cookie_pairs.append(f"{k}={v}")
            self.session.cookies.set(k, v)

        cookie_header_str = '; '.join(safe_cookie_pairs)

        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'https://live.bilibili.com/{room_id}',
            'Origin': 'https://live.bilibili.com',
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cookie': cookie_header_str
        })
        
    def send_danmaku(self, message: str) -> bool:
        """发送弹幕到直播间（UTF-8 编码，避免 latin-1 报错）"""
        try:
            import re
            clean_msg = re.sub(r"\s+", " ", message).strip()  # 保留 emoji 只清理多余空白
            logger.info(f"📤 准备发送弹幕(len={len(clean_msg)} chars, bytes={len(clean_msg.encode('utf-8'))}): {clean_msg}")
            # Removed length truncation: always send full message
            if not clean_msg:
                logger.error(" 弹幕内容为空，已跳过发送")
                return False

            logger.debug(f"📤 准备发送弹幕: {clean_msg}")
            message = clean_msg

            csrf_token = self.cookies.get('bili_jct', '')
            
            url = 'https://api.live.bilibili.com/msg/send'
            payload = {
                'bubble': '0',
                'msg': message,
                'color': '16777215',
                'mode': '1',
                'fontsize': '25',
                'rnd': str(int(time.time())),
                'roomid': str(self.room_id),
                'csrf': csrf_token,
                'csrf_token': csrf_token
            }
            
            import urllib.parse
            encoded: bytes = urllib.parse.urlencode(payload, encoding='utf-8').encode('utf-8')

            resp = self.session.post(
                url,
                data=encoded,
                headers={
                    **self.session.headers,
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'Content-Length': str(len(encoded)),
                    'X-CSRF-Token': csrf_token,
                    'X-Requested-With': 'XMLHttpRequest'
                }
            )
            result = resp.json()
            
            if result.get('code') == 0:
                logger.info(f"✅ 弹幕发送成功: {message}")
                return message  # 返回实际发送内容，供上层记录
            else:
                logger.error(f" 弹幕发送失败: code={result.get('code')} msg={result.get('message')}")
                logger.debug(f"Response raw: {resp.text}")
                print('Danmaku API raw response:', resp.text)

                # 尝试使用 bilibili_live SDK 作为后备方案
                if BILIBILI_LIVE_AVAILABLE:
                    try:
                        from bilibili_live import BilibiliLive
                        cookie_str = '; '.join([f"{k}={v}" for k, v in self.cookies.items()])
                        live_client = BilibiliLive(cookie_str, room_id=self.room_id)
                        live_client.send_danmaku(message)
                        logger.info(" fallback:bilibili_live 弹幕发送成功")
                        return message
                    except Exception as e:
                        logger.error(f" 后备方案也失败: {e}")
                return False
        except Exception as e:
            logger.error(f" 弹幕发送异常: {e}")
            return False

class AIVTuber2025:
    """2025年AI虚拟主播主程序"""
    
    busy: bool = False  # 是否正在处理观众互动
    
    def __init__(self):
        """初始化AI虚拟主播"""
        # 配置
        self.room_id: int = 0
        self.cookies: Dict[str, str] = {}
        self.proxy: Optional[str] = None
        self.ai_prompt: str = ""
        self.model_name: str = "deepseek-chat"
        self.deepseek_client = None
        self.llm_router = None
        
        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # 弹幕发送器
        self.danmaku_sender = None
        
        # 自我标识
        self.self_uid: int = 0
        self.self_username: str = ""
        self.self_username_mask: str = ""
        
        # 自动发送弹幕
        self.auto_send: bool = False
        
        # TTS提供器
        self.tts_provider = None
        
        # 用户昵称缓存
        self._uname_cache: Dict[int, str] = {}
        
        # 空闲聊天计时器
        self._last_activity_ts: float = time.time()
        self._idle_interval: float = 300  # 默认5分钟，后续会根据观众数动态调整
        self._idle_chat_task: Optional[asyncio.Task] = None
        self._idle_timer_lock = threading.Lock()
        
        # 观众统计
        self._viewers_set = set()  # 精确统计小房间观众
        self._current_popularity: int = 0  # bliVE 心跳里的人气值（近似在线人数）
        
        # 统一清理函数
    @staticmethod
    def _norm_msg(msg: str) -> str:
        import re
        return re.sub(r"\s+", " ", msg).strip()
        
    def load_config(self):
        """从数据库加载所有配置，并初始化相关组件"""
        logger.info("⚙️ 正在从数据库加载配置...")
        try:
            # 基础配置
            self.room_id = int(config_db.get_setting('DEFAULT.room_id') or 0)
            if not self.room_id:
                raise ValueError("关键配置项 room_id 未在数据库中设置或无效。")

            # AI 人设 (优先YAML, 回退到 set 字段)
            self.ai_prompt = ""
            preset_file_raw = config_db.get_setting('DEFAULT.preset_file')
            preset_file = preset_file_raw.strip().strip('"\'') if preset_file_raw else ""
            if preset_file:
                logger.debug(f"🔍 尝试加载预设文件: {preset_file}")
                try:
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    # 修正路径拼接，防止绝对路径问题
                    if not os.path.isabs(preset_file):
                        preset_path = os.path.join(base_dir, preset_file)
                    else:
                        preset_path = preset_file

                    if os.path.exists(preset_path):
                        self.ai_prompt = load_preset(preset_path)
                        logger.info(f"✅ 已加载预设文件: {preset_file}")
                    else:
                        logger.warning(f"⚠️ 预设文件不存在: {preset_path}")
                except Exception as e:
                    logger.error(f"❌ 预设文件加载失败: {e}")
            
            if not self.ai_prompt:
                legacy_set = config_db.get_setting('DEFAULT.set') or ''
                if legacy_set:
                    self.ai_prompt = legacy_set
                    logger.info("✅ 已使用 DEFAULT.set 作为 AI 人设 (YAML 预设未找到或加载失败)")
                else:
                    logger.warning("⚠️ 未找到 YAML 预设且未配置 set 字段，AI人设将为空。")

            # ---- LLM 配置 ----
            # 注意: deepseek_client 在旧逻辑中是单独创建的，新逻辑下我们让 LLMRouter 自己处理
            # 为了兼容，我们仍然可以创建它，但 LLMRouter 会优先使用自己的逻辑
            self.deepseek_client = None # 设为None，让LLMRouter处理
            all_llm_configs = config_db.get_all_settings()
            
            self.llm_router = LLMRouter(all_llm_configs, deepseek_client_legacy=self.deepseek_client)
            
            enabled_models = self.llm_router.get_enabled_models()
            if not enabled_models:
                 raise ValueError("数据库中没有任何模型被启用或成功加载，程序无法运行。")
            logger.info(f"✅ LLM 路由器初始化成功，已启用模型: {enabled_models}")
            
            # self.model_name 不再需要，由 router 内部管理
            self.model_name = enabled_models[0] # 可以设置一个默认值，但实际调用由router决定

            # 加载 Cookies & TTS 配置
            all_settings = config_db.get_all_settings()
            
            self.cookies = {
                k.replace("COOKIES.", ""): v
                for k, v in all_settings.items()
                if k.startswith("COOKIES.")
            }
            
            if not self.cookies.get('SESSDATA'):
                logger.warning("⚠️ 数据库中未找到 [COOKIES] 或 SESSDATA，将以游客模式运行")
            else:
                logger.info(f"✅ Cookies 加载成功 (发现 {len(self.cookies)} 个条目)")
            # 记录登录 UID 供自检
            self.self_uid = int(self.cookies.get('DedeUserID', 0))

            # 读取并设置代理 (这个现在由 LLMRouter 在内部为每个 provider 设置)
            self.proxy = config_db.get_setting('NETWORK.proxy')
            if self.proxy:
                 logger.info(f"🌐 检测到全局代理配置: {self.proxy} (将传递给各模型提供商)")
            
            # 初始化弹幕发送器
            self.danmaku_sender = DanmakuSender(self.room_id, self.cookies)
            
            # 读取主播昵称
            self.self_username = config_db.get_setting('DEFAULT.self.username') or ''
            if not self.self_username and self.self_uid:
                try:
                    api_url = f'https://api.bilibili.com/x/space/acc/info?mid={self.self_uid}&jsonp=jsonp'
                    resp = requests.get(api_url, timeout=5)
                    data = resp.json()
                    if data.get('code') == 0:
                        self.self_username = data['data'].get('name', '')
                        logger.info(f"🔍 已从 API 获取主播昵称: {self.self_username}")
                except Exception as e:
                    logger.debug(f"通过 API 获取主播昵称失败: {e}")
            
            def _mask_name(name: str) -> str:
                if not name: return ""
                if len(name) == 1: return name
                if len(name) == 2: return name[0] + "*"
                return name[0] + ("*" * (len(name) - 2)) + name[-1]

            self.self_username_mask = _mask_name(self.self_username)
            if self.self_username:
                logger.info(f"✅ 已配置登录昵称: {self.self_username} (脱敏: {self.self_username_mask})")

            # 强制禁用弹幕发送，使用字幕
            self.auto_send = False
            logger.info("✅ 字幕模式已启用，AI回复弹幕将不会自动发送。")

            # ---- 背景音乐配置 ----
            playlist_raw = config_db.get_setting('MUSIC.bgm_playlist_id') or ''
            volume_raw = config_db.get_setting('MUSIC.bgm_volume') or ''
            playlist_id = parse_playlist_id(playlist_raw) if playlist_raw else None
            volume_val = float(volume_raw) if volume_raw else None
            configure_bgm(playlist_id, volume_val)
            logger.info(f"🎶 已配置 BGM 歌单ID={playlist_id or '默认'} 音量={volume_val or '默认'}")

            # ---- TTS 配置 ----
            tts_cfg = {
                k.replace("TTS.", ""): v
                for k, v in all_settings.items()
                if k.startswith("TTS.")
            }
            self.tts_provider = TTSAdapterFactory.from_config(tts_cfg)
            
            logger.info(f"✅ 配置加载成功 - 直播间: {self.room_id}")

        except Exception as e:
            logger.error(f"❌ 配置加载失败: {e}")
            traceback.print_exc()
            # 在抛出异常前确保关键组件是 None
            self.llm_router = None
            self.danmaku_sender = None
            raise

    async def generate_ai_response(self, username: str, message: str) -> str:
        """调用大模型生成回复"""
        try:
            self.busy = True
            import datetime, time as _t
            # 1) 预设
            messages = [{"role": "system", "content": self.ai_prompt}]

            # 1.1) 加入模型表情状态提示（若 VTS 控制器已连接）
            try:
                import ai_action as _ai_mod
                if getattr(_ai_mod, "_vts_ctrl", None):
                    state_hint = _ai_mod._vts_ctrl.format_state_for_ai()
                    logger.info(f"[VTS-State->AI] {state_hint}")
                    messages.append({"role": "system", "content": state_hint})
            except Exception as _e_state:
                logger.debug(f"State hint unavailable: {_e_state}")

            # 2) 场景信息
            idle_sec = int(_t.time() - self._last_activity_ts)
            ctx_info = (
                f"[当前场景] 现在是 {datetime.datetime.now().strftime('%H:%M')}，"
                f"直播间人气值 ≈ {self._current_popularity}，"
                f"已 {idle_sec//60} 分 {idle_sec%60} 秒无人互动。"
            )
            messages.append({"role": "system", "content": ctx_info})

            for uname, umsg, areply in self._history:
                messages.append({"role": "user", "content": f"{uname}: {umsg}"})
                messages.append({"role": "assistant", "content": areply})

            # 当前弹幕（待回复）
            messages.append({"role": "user", "content": f"{username}: {message}"})
            
            def _chat():
                # 优先通过适配器调用，支持多模型回退
                if getattr(self, 'llm_router', None):
                    return self.llm_router.chat(
                        messages=messages,
                        # model 参数由 router 内部决定，不再需要外部传入
                        max_tokens=150,
                        temperature=0.8
                    )
                # 这个分支现在理论上不应该被执行
                raise RuntimeError("LLMRouter 未初始化，无法生成 AI 回复。")

            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                _chat
            )
            
            # 兼容适配器直接返回字符串或 OpenAI 客户端响应对象
            if isinstance(response, str):
                ai_reply = response.strip()
            else:
                ai_reply = response.choices[0].message.content.strip()

            # 将回复推送到字幕
            # 先清洗文本，去掉 <think>/<message> 标签等再用于显示/朗读
            cleaned_reply = self._clean_tts_text(ai_reply)

            # 推送到字幕使用已清理版本
            await push_subtitle(cleaned_reply)

            # 保留原始内容以便解析功能指令，再用清理版本朗读/记录
            await dispatch_actions(ai_reply)
            cleaned_reply = strip_control_sequences(cleaned_reply)

            logger.info(f"🤖 AI回复生成: {cleaned_reply}")

            # 将本轮对话加入历史（存已清理版本，防止污染）
            self._history.append((username, message, cleaned_reply))

            # 更新 ai_reply 为清理后的内容，后续 TTS/返回使用
            ai_reply = cleaned_reply

            # 活动计时刷新
            self._reset_idle_timer()

            return ai_reply
            
        except Exception as e:
            logger.error(f"❌ AI回复生成失败: {e}")
            return f"@{username} 抱歉，我现在有点累了～"
        finally:
            self.busy = False
    
    async def text_to_speech(self, text: str) -> bool:
        """使用Edge TTS将文本转换为语音并播放 (一次只播放一段)"""
        try:
            async with self.audio_lock:

                # 字幕已由 generate_ai_response 推送，此处不再重复

                # 对朗读文本进行正则清洗，去除括号指令等
                speak_text = self._clean_tts_text(text)

                # 调用适配器合成
                audio_file = await self.tts_provider.synthesize(speak_text)

                # 播放
                await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self._play_audio,
                    str(audio_file)
                )

                # 清理临时文件
                await self.tts_provider.cleanup(audio_file)
            
            logger.info(f"🔊 语音播放完成: {text[:30]}...")
            # 启动待机计时
            try:
                from ai_action import schedule_idle_animation as _sched_idle
                await _sched_idle()
            except Exception as _e_idle:
                logger.debug(f"Idle schedule skipped: {_e_idle}")
            return True
            
        except Exception as e:
            logger.error(f"❌ 语音合成/播放失败: {e}")
            return False
    
    def _play_audio(self, audio_file: str):
        """在线程池中播放音频"""
        try:
            # 若仍有残余播放，强制停止，确保一次只播一段
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.load(audio_file)
            pygame.mixer.music.play()
            
            # 等待播放完成
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"❌ 音频播放失败: {e}")
    
    async def send_test_danmaku(self):
        """发送测试弹幕"""
        test_messages = [
            "[AI] 虚拟主播系统启动成功!",
            "欢迎来到辉夜酱的直播间~",
            "2025 最新技术栈运行中...",
            "请大家多多关照!"
        ]
        
        message = random.choice(test_messages)
        
        success = await asyncio.get_event_loop().run_in_executor(
            self.executor,
            self.danmaku_sender.send_danmaku,
            message
        )
        
        if success:
            logger.info(f"✅ 测试弹幕发送成功: {message}")
        else:
            logger.error(f"❌ 测试弹幕发送失败")
        
        return success

    # Blive弹幕监听处理器
    async def handle_blive_danmaku(self, ctx):
        """处理blive库接收到的弹幕"""
        try:
            danmu = DanMuMsg(ctx.body)
            sender_uid = getattr(danmu.sender, 'uid', 0)
            # 跳过自己发送的弹幕（统一判断）
            if self._is_self_sender(sender_uid, danmu.sender.name):
                return
            username = danmu.sender.name
            message = danmu.content
            
            # 取消待机并触发打断动作
            try:
                from ai_action import cancel_idle_animation as _cancel_idle
                await _cancel_idle()
            except Exception as _e_idle:
                logger.debug(f"Cancel idle skip: {_e_idle}")

            logger.info(f"📨 [blive] 收到弹幕 - uid={sender_uid} name={username}: {message}")
            
            norm_msg = self._norm_msg(message)
            # 跳过已回复或自身弹幕
            if (
                norm_msg in self._recent_self_msgs
                or norm_msg in self._all_self_msgs
            ):
                return
            
            # 获取完整观众昵称（若可能）
            username_full = await self._resolve_username(sender_uid, username)
            
            # 生成AI回复
            ai_response = await self.generate_ai_response(username_full, message)
            
            # 语音播放
            await self.text_to_speech(ai_response)
            
            # 发送回复弹幕（仅发送 Emoji）
            emojis = self._extract_emojis(ai_response)
            if emojis and self.auto_send:
                # 先记录，避免推流事件先于 HTTP 回调到来导致漏判
                norm_e = self._norm_msg(emojis)
                self._recent_self_msgs.append(norm_e)
                self._recent_self_emojis.append(emojis)
                self._all_self_msgs.add(norm_e)
                self._all_self_emojis.add(emojis)

                sent = await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self.danmaku_sender.send_danmaku,
                    emojis
                )
                # 如发送内容有变化（理论上不会），再追加一次
                if sent and sent != emojis:
                    self._recent_self_msgs.append(self._norm_msg(sent))
                    self._recent_self_emojis.append(sent)
                    self._all_self_msgs.add(self._norm_msg(sent))
                    self._all_self_emojis.add(sent)
            
            logger.debug(f"[self-check] Comparing incoming message='{norm_msg}' with cache={list(self._recent_self_msgs)}")
            
            # 刷新计时器
            self._reset_idle_timer()
            
        except Exception as e:
            logger.error(f"❌ blive弹幕处理失败: {e}")
            traceback.print_exc()

    # -------------------------------------------------
    # 🎁 礼物事件（blive）
    # -------------------------------------------------
    async def handle_blive_gift(self, ctx):
        """处理 blive 库收到的送礼事件"""
        try:
            gift_data = ctx.body.get('data', {}) if isinstance(ctx.body, dict) else {}

            sender_uid = int(gift_data.get('uid', 0))
            username = gift_data.get('uname', 'unknown')

            # 跳过自己送出的礼物（极少见，但保持一致）
            if self._is_self_sender(sender_uid, username):
                return

            gift_name = gift_data.get('giftName', gift_data.get('gift_name', '礼物'))
            gift_num = int(gift_data.get('num', 1))

            logger.info(f"🎁 [blive] 收到礼物 - uid={sender_uid} name={username}: {gift_name} x{gift_num}")

            # 将送礼简化为一条"系统弹幕"交给大模型，让 AI 生成感谢语
            pseudo_msg = f"送出了 {gift_name} x{gift_num}"

            # 获取完整昵称（若可能）
            username_full = await self._resolve_username(sender_uid, username)

            ai_response = await self.generate_ai_response(username_full, pseudo_msg)

            # 语音播放
            await self.text_to_speech(ai_response)

            # 发送表情/感谢弹幕
            emojis = self._extract_emojis(ai_response)
            if emojis and self.auto_send:
                norm_e = self._norm_msg(emojis)
                self._recent_self_msgs.append(norm_e)
                self._recent_self_emojis.append(emojis)
                self._all_self_msgs.add(norm_e)
                self._all_self_emojis.add(emojis)

                await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self.danmaku_sender.send_danmaku,
                    emojis
                )

            # 刷新计时器
            self._reset_idle_timer()

        except Exception as e:
            logger.error(f"❌ blive礼物处理失败: {e}")
            traceback.print_exc()

    # Bilibili-live库的事件处理器
    class BilibiliLiveHandler(BilibiliLiveEventHandler):
        def __init__(self, ai_vtuber):
            self.ai_vtuber = ai_vtuber
            
        def onDanmu(self, event):
            """处理bilibili-live库接收到的弹幕"""
            try:
                danmu = event.data
                # 跳过自己发送的弹幕（统一判断）
                if self.ai_vtuber._is_self_sender(getattr(danmu, 'uid', 0), danmu.username):
                    return
                username = danmu.username
                message = danmu.content
                
                logger.info(f"📨 [bilibili-live] 收到弹幕 - uid={getattr(danmu, 'uid', 0)} name={username}: {message}")
                
                # 内容匹配（防护双保险）
                if (
                    self.ai_vtuber._norm_msg(message) in self.ai_vtuber._all_self_msgs
                ):
                    logger.debug("⚠️ 忽略可能回显的自己弹幕")
                    return
                
                # 将处理任务放入异步队列
                asyncio.create_task(self._handle_danmu_async(getattr(danmu, 'uid', 0), username, message))
                
            except Exception as e:
                logger.error(f"❌ 处理弹幕事件失败: {e}")
                traceback.print_exc()
        
        async def _handle_danmu_async(self, uid: int, username: str, message: str):
            """异步处理弹幕"""
            try:
                # 解析完整昵称（若可）
                username_full = await self.ai_vtuber._resolve_username(uid, username)

                ai_response = await self.ai_vtuber.generate_ai_response(username_full, message)
                
                # 语音播放
                await self.ai_vtuber.text_to_speech(ai_response)
                
                # 发送回复弹幕（仅发送 Emoji）
                emojis = self.ai_vtuber._extract_emojis(ai_response)
                if emojis and self.ai_vtuber.auto_send:
                    # 先记录，避免 race
                    norm_e = self.ai_vtuber._norm_msg(emojis)
                    self.ai_vtuber._recent_self_msgs.append(norm_e)
                    self.ai_vtuber._recent_self_emojis.append(emojis)
                    self.ai_vtuber._all_self_msgs.add(norm_e)
                    self.ai_vtuber._all_self_emojis.add(emojis)

                    sent = await asyncio.get_event_loop().run_in_executor(
                        self.ai_vtuber.executor,
                        self.ai_vtuber.danmaku_sender.send_danmaku,
                        emojis
                    )
                    if sent and sent != emojis:
                        self.ai_vtuber._recent_self_msgs.append(self.ai_vtuber._norm_msg(sent))
                        self.ai_vtuber._recent_self_emojis.append(sent)
                        self.ai_vtuber._all_self_msgs.add(self.ai_vtuber._norm_msg(sent))
                        self.ai_vtuber._all_self_emojis.add(sent)
                
                logger.debug(f"[self-check BL] incoming='{self.ai_vtuber._norm_msg(message)}' cache={list(self.ai_vtuber._recent_self_msgs)}")
                logger.debug(f"[self-check BL] incoming emoji='{self.ai_vtuber._extract_emojis(message)}' cache emoji={list(self.ai_vtuber._recent_self_emojis)}")
            
            except Exception as e:
                logger.error(f"❌ 异步弹幕处理失败: {e}")

        # -------- 礼物事件 --------
        def onGift(self, event):
            """处理 bilibili-live Gift 事件"""
            try:
                gift = event.data

                sender_uid = getattr(gift, 'uid', 0)
                username = getattr(gift, 'uname', getattr(gift, 'username', 'unknown'))

                # 跳过自己送的
                if self.ai_vtuber._is_self_sender(sender_uid, username):
                    return

                gift_name = getattr(gift, 'gift_name', getattr(gift, 'giftName', '礼物'))
                gift_num = getattr(gift, 'num', 1)

                logger.info(f"🎁 [bilibili-live] 收到礼物 - uid={sender_uid} name={username}: {gift_name} x{gift_num}")

                asyncio.create_task(self._handle_gift_async(sender_uid, username, gift_name, gift_num))

            except Exception as e:
                logger.error(f"❌ 处理礼物事件失败: {e}")
                traceback.print_exc()

        async def _handle_gift_async(self, uid: int, username: str, gift_name: str, gift_num: int):
            try:
                username_full = await self.ai_vtuber._resolve_username(uid, username)
                pseudo_msg = f"送出了 {gift_name} x{gift_num}"

                ai_response = await self.ai_vtuber.generate_ai_response(username_full, pseudo_msg)

                await self.ai_vtuber.text_to_speech(ai_response)

                emojis = self.ai_vtuber._extract_emojis(ai_response)
                if emojis and self.ai_vtuber.auto_send:
                    norm_e = self.ai_vtuber._norm_msg(emojis)
                    self.ai_vtuber._recent_self_msgs.append(norm_e)
                    self.ai_vtuber._recent_self_emojis.append(emojis)
                    self.ai_vtuber._all_self_msgs.add(norm_e)
                    self.ai_vtuber._all_self_emojis.add(emojis)

                    await asyncio.get_event_loop().run_in_executor(
                        self.ai_vtuber.executor,
                        self.ai_vtuber.danmaku_sender.send_danmaku,
                        emojis
                    )

            except Exception as e:
                logger.error(f"❌ 异步礼物处理失败: {e}")

    async def start_blive_listener(self):
        """启动blive弹幕监听器"""
        try:
            logger.info("🚀 启动blive弹幕监听器...")
            
            # 创建blive应用实例
            app = BLiver(self.room_id)
            
            # 注册弹幕处理器
            @app.on(Events.DANMU_MSG)
            async def on_danmaku(ctx: BLiverCtx):
                await self.handle_blive_danmaku(ctx)
            
            # 注册礼物事件
            @app.on(Events.SEND_GIFT)
            async def on_gift(ctx: BLiverCtx):
                await self.handle_blive_gift(ctx)
            
            # 欢迎新人进入
            @app.on(Events.INTERACT_WORD)
            async def on_interact(ctx: BLiverCtx):
                try:
                    data = ctx.body.get('data', {})
                    # msg_type 1: 进入直播间 2: 关注 3: 分享
                    if data.get('msg_type') == 1:
                        uname = data.get('uname', '路人')
                        uid = int(data.get('uid', 0))
                        if uid:
                            self._live_viewer_uids.add(uid)
                        logger.info(f"👋 [blive] 新观众进入: {uname}")
                        pseudo_msg = "进入了直播间"
                        ai_resp = await self.generate_ai_response(uname, pseudo_msg)
                        await self.text_to_speech(ai_resp)
                        emojis = self._extract_emojis(ai_resp)
                        if emojis and self.auto_send:
                            await asyncio.get_event_loop().run_in_executor(
                                self.executor,
                                self.danmaku_sender.send_danmaku,
                                emojis
                            )
                except Exception as e:
                    logger.error(f"❌ 处理进入房间事件失败: {e}")
                finally:
                    # 重置闲聊计时器
                    self._reset_idle_timer()
            
            # 欢迎 (系统通知)
            @app.on(Events.WELCOME)
            async def on_welcome(ctx: BLiverCtx):
                try:
                    data = ctx.body.get('data', {})
                    uname = data.get('uname', '') or data.get('username', '路人')
                    uid = int(data.get('uid', 0))
                    if uid:
                        self._live_viewer_uids.add(uid)
                    logger.info(f"👋 [welcome] {uname} 进入直播间")
                    pseudo_msg = "进入了直播间"
                    ai_resp = await self.generate_ai_response(uname, pseudo_msg)
                    await self.text_to_speech(ai_resp)
                    emojis = self._extract_emojis(ai_resp)
                    if emojis and self.auto_send:
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor,
                            self.danmaku_sender.send_danmaku,
                            emojis
                        )
                except Exception as e:
                    logger.error(f"❌ 处理 WELCOME 事件失败: {e}")
                finally:
                    self._reset_idle_timer()
            
            # 注册心跳事件
            # blive >=0.4.0 修改了心跳事件名称为 HEARTBEAT_REPLY
            try:
                HEARTBEAT_EVT = Events.HEARTBEAT  # 老版本
            except AttributeError:
                HEARTBEAT_EVT = getattr(Events, 'HEARTBEAT_REPLY', None)  # 新版本

            if HEARTBEAT_EVT is not None:
                @app.on(HEARTBEAT_EVT)
                async def on_heartbeat(ctx: BLiverCtx):
                    try:
                        self._current_popularity = ctx.body.get('popularity', 0)
                    except Exception:
                        pass
            else:
                logger.debug("⚠️ 未在 Events 中找到 HEARTBEAT/HEARTBEAT_REPLY 事件，已跳过心跳监听")
            
            # 启动监听
            await app.run_as_task()
            
        except Exception as e:
            logger.error(f"❌ blive监听器启动失败: {str(e)}")
            # 尝试使用备用方案
            self.start_bilibili_live_listener()
    
    def start_bilibili_live_listener(self):
        """启动bilibili-live弹幕监听器"""
        if not BILIBILI_LIVE_AVAILABLE:
            logger.error("❌ bilibili-live库不可用")
            return False
            
        try:
            logger.info("🚀 启动bilibili-live弹幕监听器...")
            
            # 使用事件处理器类（让 bilibili_live 内部实例化）
            handler_cls = self.BilibiliLiveHandler
            
            bilibili_live = BilibiliLive()
            bilibili_live.schedule(handler_cls, self.room_id)
            bilibili_live.start()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ bilibili-live监听器启动失败: {e}")
            traceback.print_exc()
            return False
    
    async def run(self):
        """运行主程序"""
        try:
            logger.info("🎬 AI虚拟主播系统启动中...")
            logger.info(f"📱 房间号: {self.room_id}")
            
            # 启动字幕 WebSocket 服务
            await ensure_server()

            # 先启动闲聊守护协程，避免被后续阻塞
            # asyncio.create_task(self._idle_chat_loop())  # 已禁用自动闲聊
            
            # 不再主动发送测试弹幕，只监听
            
            # 优先尝试blive库
            if BLIVE_AVAILABLE:
                logger.info(" 使用blive库监听弹幕...")
                await self.start_blive_listener()
            elif BILIBILI_LIVE_AVAILABLE:
                logger.info("🎯 使用bilibili-live库监听弹幕...")
                self.start_bilibili_live_listener()
                
                # 保持主循环运行
                while True:
                    await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info(" 用户中断，程序退出")
        except Exception as e:
            logger.error(f" 主程序运行失败: {e}")
            traceback.print_exc()
        finally:
            self.cleanup()
    
    def cleanup(self):
        """清理资源"""
        logger.info("🧹 清理系统资源...")
        pygame.mixer.quit()
        self.executor.shutdown(wait=True)

    async def _idle_chat_loop(self):
        """若直播间长时间无互动，主动找话题聊天"""
        import time
        first_run = True
        while True:
            await asyncio.sleep(10)
            try:
                if self.busy:
                    continue  # 正在处理弹幕/礼物，跳过闲聊
                if first_run or (time.time() - self._last_activity_ts >= self._next_idle_interval):
                    if first_run:
                        logger.debug("[idle] 首次启动，立即进行自我介绍")
                        first_run = False
                    else:
                        logger.debug(f"[idle] 触发闲聊: 距离上次互动已 {(time.time() - self._last_activity_ts):.0f}s ≥ {self._next_idle_interval}s")
                    # 仅保留「观众弹幕 + 本人回复」的配对记录
                    _audience_pairs = [item for item in self._history if not self._is_self_sender(0, item[0])]
                    if _audience_pairs:
                        # 取最近 5 轮互动
                        recent_pairs = _audience_pairs[-5:]
                        summary = " | ".join(f"{u}:{m} -> 我:{a}" for u, m, a in recent_pairs)
                        prompt_msg = f"最近和观众的互动: {summary}。系统提示：你可以根据历史聊天吐槽或回应，最后一条是最新消息，越往前越旧"
                        logger.debug(f"[idle] 基于历史聊天内容进行吐槽: {summary}")
                        ai_resp = await self.generate_ai_response("观众们", prompt_msg)
                    else:
                        candidates = [
                            "好像没有人在呢…要不我先唱首歌？",
                            "直播间空空如也，好无聊呀~",
                            "嗨~ 有没有路过的小伙伴？陪我聊聊天吧！",
                            "欸——都去哪里了？可怜的主播只能对空气说话啦。"
                        ]
                        import random as _r
                        pseudo_msg = _r.choice(candidates)
                        ai_resp = await self.generate_ai_response(self.self_username or "主播", pseudo_msg)
                    await self.text_to_speech(ai_resp)
                    emojis = self._extract_emojis(ai_resp)
                    if emojis and self.auto_send:
                        await asyncio.get_event_loop().run_in_executor(
                            self.executor,
                            self.danmaku_sender.send_danmaku,
                            emojis
                        )
                    # 重置计时器
                    self._reset_idle_timer()
            except Exception as e:
                logger.debug(f"idle chat loop error: {e}")

    def _extract_emojis(self, text: str) -> str:
        """提取一个表情（优先级：最后一句中的最后一个  颜文字 > Emoji > 特符）。
        从回复结尾开始逐行向上查找，找到即返回。"""
        import re
        # 拆分行，去掉空白
        segments = [seg.strip() for seg in text.strip().splitlines() if seg.strip()]

        # 正则定义
        kaomoji_pat = re.compile(r'[\(（][^\n]{1,30}?[\)）]')  # 颜文字
        emoji_pat = re.compile(r'[\U0001F300-\U0001F64F]|[\U0001F680-\U0001FAFF]')
        symbol_pat = re.compile(r'[\u2600-\u27BF]')  # ★☆✧♥✨ 等

        def last_token(pattern: re.Pattern, s: str):
            token = ''
            for m in pattern.finditer(s):
                token = m.group(0)
            return token

        # 从结尾行开始向上查找
        for seg in reversed(segments):
            for pattern in (kaomoji_pat, emoji_pat, symbol_pat):
                tok = last_token(pattern, seg)
                if tok:
                    logger.info(f"🎯 选定表情: {tok} (segment='{seg}')")
                    return tok
        # 整体兜底搜索（极端情况如整段无换行）
        for pattern in (kaomoji_pat, emoji_pat, symbol_pat):
            tok = last_token(pattern, text)
            if tok:
                logger.info(f"🎯 选定表情(全局兜底): {tok}")
                return tok
        logger.warning("⚠️ 未找到可用表情，将不发送弹幕")
        return ''

    def _is_self_sender(self, sender_uid: int, username: str) -> bool:
        """判断一条弹幕是否来自本账号

        1) UID 精准匹配
        2) 若 UID 为 0 或获取失败，则用脱敏昵称匹配：
           - 与配置中的 `self_username_mask` 完全相等，或
           - 首字符相同且长度一致（应对不同星号数量的脱敏实现）
           - 兼容全角星号、★☆、… 等特殊填充字符
        """
        import unicodedata, re
        norm_username = unicodedata.normalize('NFKC', username).strip()
        norm_self_full = unicodedata.normalize('NFKC', self.self_username).strip() if self.self_username else ''
        mask = self.self_username_mask

        # DEBUG: 打印检测过程，便于后续排查
        logger.debug(
            f"[self_det] uid={sender_uid} raw_name={repr(username)} norm_name={repr(norm_username)} "
            f"mask={mask} full={norm_self_full}"
        )

        # UID 最可靠
        if self.self_uid and sender_uid == self.self_uid:
            logger.debug("[self_det] ✅ 命中 UID")
            return True

        # 完整昵称匹配（使用NFKC归一化）
        if norm_self_full and norm_username == norm_self_full:
            logger.debug("[self_det] ✅ 命中完整昵称")
            return True

        if not mask:
            return False

        # 完全相同脱敏名
        if norm_username == mask:
            logger.debug("[self_det] ✅ 脱敏名完全相同")
            return True

        # 星号宽松匹配 - 支持半角 * 、全角 ＊ 及部分装饰星
        star_chars = "*＊★☆"
        additional_fillers = "．。.。！!?,，·。、… "  # 允许的中文/英文标点、空格及省略号
        star_pattern = rf"^{re.escape(mask[0])}[{re.escape(star_chars)}]+[{re.escape(additional_fillers)}]*$"
        if re.match(star_pattern, norm_username):
            logger.debug("[self_det] ✅ 星号宽松匹配命中")
            return True

        # 一般宽松匹配：首字符一致且其余全部由星号/标点组成
        if (
            norm_username and norm_username[0] == mask[0] and
            set(norm_username[1:]).issubset(set(star_chars + additional_fillers))
        ):
            logger.debug("[self_det] ✅ 首字符+填充字符匹配命中")
            return True

        logger.debug("[self_det] ❌ 判断为非自身弹幕")
        return False

    async def _resolve_username(self, uid: int, masked_name: str) -> str:
        """若 uid >0，则尝试通过公开API获取完整昵称（带缓存）；失败返回 masked_name"""
        if uid <= 0:
            return masked_name
        if uid in self._uname_cache:
            return self._uname_cache[uid]
        try:
            import requests, asyncio
            loop = asyncio.get_event_loop()
            def _fetch():
                url = f'https://api.bilibili.com/x/space/acc/info?mid={uid}&jsonp=jsonp'
                resp = requests.get(url, timeout=5)
                return resp.json()
            data = await loop.run_in_executor(self.executor, _fetch)
            if data.get('code') == 0:
                name = data['data'].get('name', '') or masked_name
                self._uname_cache[uid] = name
                return name
        except Exception:
            pass
        return masked_name

    def _clean_tts_text(self, text: str) -> str:
        """清理不应朗读的内容：
        0. 删除 <think>…</think> 段，保留 <message> 内部文字、去掉标签
        1. 去掉 (动作) / （动作） 等括号指令
        2. 去掉 Emoji、表情符号、特殊符号、颜文字（括号包围的已被 1 去除）
        3. 去掉 *包裹* 的星号但保留内容
        """
        import re, unicodedata

        # 0) 移除 <think> 段 & <message> 标签
        text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"</?message>", "", text, flags=re.IGNORECASE)

        # 1) 去掉括号动作
        cleaned = re.sub(r"[\(（][^\)\）]{0,30}[\)）]", "", text)

        # 2) 去掉显式 Emoji / 符号
        emoji_pattern = re.compile(r"[\U0001F300-\U0001F64F\U0001F680-\U0001FAFF]", flags=re.UNICODE)
        symbol_pattern = re.compile(r"[\u2600-\u27BF]")  # ★☆✧♥✨ 等
        cleaned = emoji_pattern.sub("", cleaned)
        cleaned = symbol_pattern.sub("", cleaned)

        # 3) 去掉半角/全角星号包裹的内容的外壳，保留内部文字
        cleaned = re.sub(r"[\*＊]([^\*＊]{1,30})[\*＊]", r"\\1", cleaned)

        # 合并空白、归一化
        cleaned = unicodedata.normalize('NFKC', cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        return cleaned

async def main():
    """主函数"""
    try:
        # 检查依赖库
        logger.info("检查依赖库...")
        logger.info(f"blive库: {'可用' if BLIVE_AVAILABLE else ' 不可用'}")
        logger.info(f"bilibili-live库: {' 可用' if BILIBILI_LIVE_AVAILABLE else ' 不可用'}")
        
        if not BLIVE_AVAILABLE and not BILIBILI_LIVE_AVAILABLE:
            logger.error(" 没有可用的B站弹幕库，请检查安装！")
            print("❌ 错误: 没有可用的B站弹幕库，请先安装blive或bilibili-live")
            print("   运行命令: pip install blive bilibili-live")
            return
        
        # 检查数据库配置完整性
        if HAS_CONFIG_DB:
            missing = config_db.check_required_settings()
            if missing:
                logger.error(f"数据库配置不完整，缺少: {', '.join(missing)}")
                print("❌ 数据库配置不完整，缺少以下必要参数:")
                for item in missing:
                    print(f"   - {item}")
                print("请在配置界面填写这些参数后重试")
        else:
            logger.error("数据库模块不可用，无法读取配置")
            print("❌ 错误: 数据库模块不可用，无法读取配置")
            return
        
        # 提前初始化网易云客户端（若未登录将生成二维码）
        try:
            await get_netease_client()
        except Exception as e:
            logger.error(f"网易云登录初始化失败: {e}")
            print(f"⚠️ 警告: 网易云登录初始化失败: {e}")
            print("   背景音乐和点歌功能可能不可用")

        # 启动背景纯音乐播放（低音量循环）
        try:
            await start_background_music()
        except Exception as e:
            logger.warning(f"背景音乐启动失败: {e}")
            print(f"⚠️ 警告: 背景音乐启动失败: {e}")
        
        # 创建并运行AI虚拟主播
        ai_vtuber = AIVTuber2025()
        ai_vtuber.load_config()  # <--- 在此调用配置加载！
        await ai_vtuber.run()
        
    except Exception as e:
        logger.error(f" 程序启动失败: {e}")
        traceback.print_exc()
        print(f"\n❌ 程序启动失败: {e}")
        print("请检查日志文件 ai_vtuber_2025.log 获取详细错误信息")

if __name__ == "__main__":
    print("🎌 B站AI虚拟主播弹幕回复系统 - 2025年终极版本")
    print("=" * 60)
    print(" 启动中...")
    
    # 运行异步主程序
    asyncio.run(main()) 