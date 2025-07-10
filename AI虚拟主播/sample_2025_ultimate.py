#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B站AI虚拟主播弹幕回复系统 - 2025年版本
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
import tts_adapter_loader  # 加载根目录的 tts_adapter
from tts_adapter import TTSAdapterFactory

# AI相关
import openai as deepseek
import httpx
# 本地 LLM 适配器
from llm_adapter import LLMRouter
from ai_action import dispatch_actions, strip_control_sequences, start_background_music, configure_bgm, parse_playlist_id

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
            logger.info(f" 准备发送弹幕(len={len(clean_msg)} chars, bytes={len(clean_msg.encode('utf-8'))}): {clean_msg}")
            # Removed length truncation: always send full message
            if not clean_msg:
                logger.error(" 弹幕内容为空，已跳过发送")
                return False

            logger.debug(f" 准备发送弹幕: {clean_msg}")
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
                logger.info(f" 弹幕发送成功: {message}")
                return message  # 返回实际发送内容，供上层记录
            else:
                logger.error(f"弹幕发送失败: code={result.get('code')} msg={result.get('message')}")
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
                    except Exception as e2:
                        logger.error(f" fallback 弹幕发送仍然失败: {e2}")
                return False
                
        except Exception as e:
            logger.error(f" 发送弹幕时出错: {e}")
            return False

class AIVTuber2025:
    """2025年AI虚拟主播主程序"""
    
    def __init__(self):
        self.room_id = None
        self.deepseek_client = None
        self.ai_prompt = None
        self.cookies = {}
        self.proxy = None
        self.danmaku_sender = None
        
        # 异步队列用于线程间通信
        self.message_queue = queue.Queue()
        self.response_queue = queue.Queue()
        
        # 初始化pygame mixer
        pygame.mixer.init()
        
        # 新增：用于串行化音频播放，保证一次只播放一段
        import asyncio  # 这里确保 asyncio 可用
        self.audio_lock = asyncio.Lock()
        
        # 线程池
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # 控制变量
        self.running = False
        # 是否自动发送弹幕（从 config 读取，默认为 True）
        self.auto_send = False
        
        # 加载配置
        self.load_config()
        
        # 记录最近自己发送的弹幕/表情，用于过滤
        from collections import deque
        self._recent_self_msgs = deque(maxlen=10)
        # 新增：记录最近自己发送的表情（Emoji / 颜文字），用于更精准地忽略自身弹幕
        self._recent_self_emojis = deque(maxlen=10)
        # 会话级去重：保存本次会话中所有由主播账号主动发送的弹幕/表情，防止历史过长时 deque 被挤掉导致自问自答
        # 总量通常很小（不会超过几百条），使用 set 即可。
        self._all_self_msgs: set[str] = set()
        self._all_self_emojis: set[str] = set()
        self._current_popularity: int = 0
        
        # --- 记忆功能 ---
        from collections import deque as _dq
        # 最近 20 轮 (user, msg, ai_reply) 供上下文
        self._history: _dq[tuple[str, str, str]] = _dq(maxlen=10)
        
        # 登录用户名相关属性已在 load_config 中初始化，不要在此处覆盖
        
        # 用户名缓存：uid -> 完整昵称
        self._uname_cache: dict[int, str] = {}
        
        # ---- 主动聊天相关 ----
        self._last_activity_ts = time.time()

        # 在线人数缓存
        self._viewer_cnt: int = 0
        self._viewer_cnt_ts: float = 0.0
        self._live_viewer_uids: set[int] = set()

        def _get_online_viewers() -> int:
            import time, requests
            if time.time() - self._viewer_cnt_ts < 60:
                return self._viewer_cnt
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"https://live.bilibili.com/{self.room_id}"
                }
                urls = [
                    f"https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom?room_id={self.room_id}",
                    f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={self.room_id}",
                ]
                for api_url in urls:
                    try:
                        r = requests.get(api_url, headers=headers, timeout=3)
                        data = r.json()
                    except Exception:
                        continue
                    if data.get('code') == 0:
                        online = None
                        if 'room_info' in data.get('data', {}):
                            online = data['data']['room_info'].get('online')
                        elif 'online' in data.get('data', {}):
                            online = data['data'].get('online')
                        if online is not None:
                            self._viewer_cnt = int(online)
                            self._viewer_cnt_ts = time.time()
                            break
            except Exception as e:
                logger.debug(f"[idle] 获取在线人数失败: {e}")
            return self._viewer_cnt

        def _estimate_viewers(raw: int) -> int:
            real_small = len(self._live_viewer_uids)
            if real_small and real_small <= 12:
                return real_small
            if raw <= 0:
                return real_small
            if raw < 180:
                return max(real_small, raw // 15)
            return max(real_small, raw // 20)

        def _calc_idle_interval():
            interval = random.randint(20, 90)
            logger.debug(f"[idle] 随机闲聊间隔: {interval}s")
            return interval

        self._calc_idle_interval = _calc_idle_interval
        self._get_online_viewers = _get_online_viewers
        self._next_idle_interval = self._calc_idle_interval()
        logger.debug(f"[idle] 初始化定时器: 下一次闲聊将在 ~{self._next_idle_interval}s 后触发")

        def _reset_idle_timer():
            self._last_activity_ts = time.time()
            self._next_idle_interval = self._calc_idle_interval()
            logger.debug(f"[idle] 计时器已重置: 下一次闲聊将在 ~{self._next_idle_interval}s 后触发")
        self._reset_idle_timer = _reset_idle_timer
        
        # 统一清理函数
    @staticmethod
    def _norm_msg(msg: str) -> str:
        import re
        return re.sub(r"\s+", " ", msg).strip()
        
    def load_config(self):
        """加载配置文件"""
        try:
            config = configparser.ConfigParser(interpolation=None)
            # 保留键名大小写，避免 Cookie 名被强制小写导致服务器不识别
            config.optionxform = str
            # 保持 interpolation=None，不要再覆盖，否则 % 字符会触发插值错误
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.txt')
            logger.info(f" 正在读取配置文件: {config_path}")
            
            if not os.path.exists(config_path):
                raise FileNotFoundError(f"配置文件不存在: {config_path}")
                
            with open(config_path, 'r', encoding='utf-8') as f:
                config.read_file(f)
            
            # 基础配置
            self.room_id = int(config.get('DEFAULT', 'room_id'))
            deepseek_api_key = config.get('DEFAULT', 'deepseek.api_key')
            # 先尝试加载 YAML 预设文件；若不存在或加载失败，再回退到旧的 set 字段
            self.ai_prompt = None  # 占位，稍后确定实际值

            # 读取预设文件（优先级最高）
            preset_file = config.get('DEFAULT', 'preset_file', fallback='').strip()
            if preset_file:
                try:
                    preset_path = os.path.join(os.path.dirname(config_path), preset_file)
                    if os.path.exists(preset_path):
                        self.ai_prompt = load_preset(preset_path)
                        logger.info(f"✅ 已加载预设文件: {preset_file}")
                    else:
                        logger.warning(f"⚠️ 预设文件不存在: {preset_file}")
                except Exception as e:
                    logger.error(f"❌ 预设文件加载失败: {e}")

            # 若 YAML 未找到，则尝试回退到旧的 set 字段
            if not self.ai_prompt:
                legacy_set = config.get('DEFAULT', 'set', fallback='').strip()
                if legacy_set:
                    self.ai_prompt = legacy_set
                    logger.info("✅ 已使用 DEFAULT.set 作为 AI 人设 (YAML 预设未找到)")
                else:
                    self.ai_prompt = ""
                    logger.info("⚠️ 未找到 YAML 预设且未配置 set 字段，已使用空系统提示")
            
            # 设置DeepSeek客户端
            api_base_url = config.get('DEFAULT', 'api.base_url', fallback='https://api.deepseek.com/v1').strip()
            deepseek_proxy = config.get('DEFAULT', 'deepseek.proxy', fallback=config.get('NETWORK', 'proxy', fallback='')).strip() or None
            if deepseek_proxy:
                http_client = httpx.Client(proxies=deepseek_proxy, timeout=60.0)
                self.deepseek_client = deepseek.OpenAI(api_key=deepseek_api_key, base_url=api_base_url, http_client=http_client)
            else:
                self.deepseek_client = deepseek.OpenAI(api_key=deepseek_api_key, base_url=api_base_url)
            
            # 初始化多模型 LLM 适配器（带回退逻辑）
            try:
                self.llm_router = LLMRouter(config, deepseek_client=self.deepseek_client)
            except Exception as e:
                logger.error(f"❌ 初始化LLMRouter失败: {e}")
                self.llm_router = None
            
            # 解析 cookies
            if config.has_section('COOKIES'):
                cookies_section = config['COOKIES']
                defaults_keys = config.defaults().keys()
                for key, value in cookies_section.items():
                    # 跳过来自 DEFAULT 的条目，确保只处理本节真正的 cookie
                    if key in defaults_keys:
                        continue

                    # 配置文件里把 % 写成 %% 以避免被解析器吞掉，这里换回来
                    value = value.replace('%%', '%')

                    if key.isascii() and '.' not in key:
                        # 只保留 latin-1 可编码的 Cookie 值，避免 requests header 编码失败
                        try:
                            value.encode('latin-1')
                        except UnicodeEncodeError:
                            logger.debug(f"跳过包含非 latin-1 字符的 Cookie 值: {key}")
                            continue
                        # 记录到 cookie 字典
                        self.cookies[key] = value
                    else:
                        # 跳过注释行
                        if key.startswith('#'):
                            continue
                        # 其余字段如果需要可在此处添加 else 分支逻辑
                        logger.debug(f"跳过配置字段 {key}")
            else:
                logger.warning(" 配置文件中未找到 [COOKIES] 段，将以游客模式运行")
            
            # 读取代理
            proxy_raw = config.get('NETWORK', 'proxy', fallback='').strip()
            self.proxy = proxy_raw or None
            if self.proxy:
                # 通过环境变量让 httpx / aiohttp 自动使用代理
                os.environ['HTTP_PROXY'] = self.proxy
                os.environ['HTTPS_PROXY'] = self.proxy
                logger.info(f" 已配置网络代理: {self.proxy}")
            
            # 初始化弹幕发送器
            self.danmaku_sender = DanmakuSender(self.room_id, self.cookies)
            
            # 加载模型名称
            self.model_name = config.get('DEFAULT', 'model.name', fallback='deepseek-chat').strip()
            
            # 记录登录 UID 供自检
            self.self_uid = int(self.cookies.get('DedeUserID', '0') or 0)
            
            # 读取登录昵称（可选）
            self.self_username = config.get('DEFAULT', 'self.username', fallback='').strip()

            # 若未配置用户名但已知UID，尝试通过公开API获取一次
            if not self.self_username and self.self_uid:
                try:
                    api_url = f'https://api.bilibili.com/x/space/acc/info?mid={self.self_uid}&jsonp=jsonp'
                    resp = requests.get(api_url, timeout=5)
                    data = resp.json()
                    if data.get('code') == 0:
                        self.self_username = data['data'].get('name', '') or ''
                        logger.info(f" 已从 API 获取主播昵称: {self.self_username}")
                except Exception as e:
                    logger.debug(f"获取主播昵称失败: {e}")

            def _mask_name(name: str) -> str:
                if not name:
                    return ""
                if len(name) == 1:
                    return name
                if len(name) == 2:
                    return name[0] + "*"
                return name[0] + ("*" * (len(name) - 2)) + name[-1]

            self.self_username_mask = _mask_name(self.self_username)

            if self.self_username:
                logger.info(f" 已配置登录昵称: {self.self_username} (masked -> {self.self_username_mask})")
            
            # 读取是否自动发送弹幕
            self.auto_send = False
            logger.info("✅ 已切换字幕模式，弹幕发送已禁用")
            
            # 背景音乐配置
            if config.has_section('MUSIC'):
                playlist_raw = config.get('MUSIC', 'bgm_playlist_id', fallback='').strip()
                volume_raw = config.get('MUSIC', 'bgm_volume', fallback='').strip()
                playlist_id = parse_playlist_id(playlist_raw) if playlist_raw else None
                volume_val = float(volume_raw) if volume_raw else None
                configure_bgm(playlist_id, volume_val)
                logger.info(f"🎶 已配置 BGM 歌单ID={playlist_id or '默认'} 音量={volume_val or '默认'}")
            
            # ---- TTS 配置 ----
            if config.has_section('TTS'):
                tts_cfg = {k: v for k, v in config.items('TTS')}
            else:
                tts_cfg = {}
            self.tts_provider = TTSAdapterFactory.from_config(tts_cfg)
            
            logger.info(f"配置加载成功 - 房间号: {self.room_id}")
            logger.info(f" DeepSeek API已配置")
            logger.info(f"Cookies已配置: {list(self.cookies.keys())}")
            
        except Exception as e:
            logger.error(f" 配置加载失败: {e}")
            raise
    
    async def generate_ai_response(self, username: str, message: str) -> str:
        """使用DeepSeek生成AI回复"""
        try:
            import datetime, time as _t
            messages = [{"role": "system", "content": self.ai_prompt}]

            idle_sec = int(_t.time() - self._last_activity_ts)
            ctx_info = (
                f"[当前场景] 现在是 {datetime.datetime.now().strftime('%H:%M')}，"
                f"直播间人气值 ≈ {self._current_popularity}，"
                f"已 {idle_sec//60} 分 {idle_sec%60} 秒无人互动。"
            )
            messages.append({"role": "system", "content": ctx_info})

            # 2. 历史对话
            for uname, umsg, areply in self._history:
                messages.append({"role": "user", "content": f"{uname}: {umsg}"})
                messages.append({"role": "assistant", "content": areply})

            # 3. 当前弹幕
            messages.append({"role": "user", "content": f"{username}: {message}"})
            
            def _chat():
                # 优先通过适配器调用，支持多模型回退
                if getattr(self, 'llm_router', None):
                    return self.llm_router.chat(
                        messages=messages,
                        model=self.model_name,
                        max_tokens=150,
                        temperature=0.8
                    )
                # 回退到旧的 DeepSeek 调用
                return self.deepseek_client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    max_tokens=150,
                    temperature=0.8
                )

            response = await asyncio.get_event_loop().run_in_executor(
                self.executor,
                _chat
            )
            
            # 兼容适配器直接返回字符串或 OpenAI 客户端响应对象
            if isinstance(response, str):
                ai_reply = response.strip()
            else:
                ai_reply = response.choices[0].message.content.strip()

            await dispatch_actions(ai_reply)
            ai_reply = strip_control_sequences(ai_reply)

            logger.info(f" AI回复生成: {ai_reply}")

            # 更新历史
            self._history.append((username, message, ai_reply))

            # 活动计时刷新
            self._reset_idle_timer()

            await push_subtitle(ai_reply)
            # 触发可能的功能指令（如点歌），并去除控制序列

            return ai_reply
            
        except Exception as e:
            logger.error(f" AI回复生成失败: {e}")
            return f"@{username} 抱歉，我现在有点累了～"
    
    async def text_to_speech(self, text: str) -> bool:
        """使用Edge TTS将文本转换为语音并播放 (一次只播放一段)"""
        try:
            async with self.audio_lock:
                voice = "zh-CN-XiaoyiNeural"  # 中文女声

                # 为避免并发写入/占用，使用唯一临时文件
                import uuid, tempfile, pathlib
                audio_file = pathlib.Path(tempfile.gettempdir()) / f"ai_reply_{uuid.uuid4().hex}.mp3"

                tts_text = self._clean_tts_text(text)
                if not tts_text:
                    logger.warning("⚠️ 清理括号后文本为空，跳过 TTS")
                    return True
                # 字幕已在生成回复阶段推送，此处不重复
                # 适配器合成
                audio_file = await self.tts_provider.synthesize(tts_text)

                # 播放语音（在线程池中执行，使锁在整个播放期间保持）
                await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self._play_audio,
                    str(audio_file)
                )

                await self.tts_provider.cleanup(audio_file)
            
            logger.info(f" 语音播放完成: {text[:30]}...")
            return True
            
        except Exception as e:
            logger.error(f" 语音合成/播放失败: {e}")
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
            logger.error(f" 音频播放失败: {e}")
    
    async def send_test_danmaku(self):
        """发送测试弹幕"""
        test_messages = [
            "[AI] 虚拟主播系统启动成功!",
            "欢迎来到直播间~",
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
            logger.error(f" 测试弹幕发送失败")
        
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
            
            logger.info(f"📨 [blive] 收到弹幕 - uid={sender_uid} name={username}: {message}")
            
            norm_msg = self._norm_msg(message)
            # 内容匹配 & 去重
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
            
            # 活动计时刷新
            self._reset_idle_timer()
            
        except Exception as e:
            logger.error(f" blive弹幕处理失败: {e}")
            traceback.print_exc()

    # ------------------ 🎁 礼物事件（blive） ------------------
    async def handle_blive_gift(self, ctx):
        try:
            gift_data = ctx.body.get('data', {}) if isinstance(ctx.body, dict) else {}

            sender_uid = int(gift_data.get('uid', 0))
            username = gift_data.get('uname', 'unknown')

            if self._is_self_sender(sender_uid, username):
                return

            gift_name = gift_data.get('giftName', gift_data.get('gift_name', '礼物'))
            gift_num = int(gift_data.get('num', 1))

            logger.info(f"🎁 [blive] 收到礼物 - uid={sender_uid} name={username}: {gift_name} x{gift_num}")

            pseudo_msg = f"送出了 {gift_name} x{gift_num}"
            username_full = await self._resolve_username(sender_uid, username)

            ai_response = await self.generate_ai_response(username_full, pseudo_msg)

            await self.text_to_speech(ai_response)

            emojis = self._extract_emojis(ai_response)
            if emojis and self.auto_send:
                norm_e = self._norm_msg(emojis)
                self._recent_self_msgs.append(norm_e)
                self._recent_self_emojis.append(emojis)
                self.ai_vtuber._all_self_msgs.add(norm_e)
                self.ai_vtuber._all_self_emojis.add(emojis)

                await asyncio.get_event_loop().run_in_executor(
                    self.executor,
                    self.danmaku_sender.send_danmaku,
                    emojis
                )

        except Exception as e:
            logger.error(f" blive礼物处理失败: {e}")
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
                
                logger.info(f" [bilibili-live] 收到弹幕 - uid={getattr(danmu, 'uid', 0)} name={username}: {message}")
                
                # 内容匹配（防护双保险）
                norm_msg = self.ai_vtuber._norm_msg(message)
                if (
                    norm_msg in self.ai_vtuber._all_self_msgs
                ):
                    logger.debug(" 忽略可能回显的自己弹幕")
                    return
                
                # 将处理任务放入异步队列
                asyncio.create_task(self._handle_danmu_async(getattr(danmu, 'uid', 0), username, message))
                
            except Exception as e:
                logger.error(f" 处理弹幕事件失败: {e}")
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
                logger.error(f" 异步弹幕处理失败: {e}")

        # -------- 礼物事件 --------
        def onGift(self, event):
            try:
                gift = event.data

                sender_uid = getattr(gift, 'uid', 0)
                username = getattr(gift, 'uname', getattr(gift, 'username', 'unknown'))

                if self.ai_vtuber._is_self_sender(sender_uid, username):
                    return

                gift_name = getattr(gift, 'gift_name', getattr(gift, 'giftName', '礼物'))
                gift_num = getattr(gift, 'num', 1)

                logger.info(f"🎁 [bilibili-live] 收到礼物 - uid={sender_uid} name={username}: {gift_name} x{gift_num}")

                asyncio.create_task(self._handle_gift_async(sender_uid, username, gift_name, gift_num))

            except Exception as e:
                logger.error(f" 处理礼物事件失败: {e}")
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
                logger.error(f" 异步礼物处理失败: {e}")

    async def start_blive_listener(self):
        """启动blive弹幕监听器"""
        try:
            logger.info(" 启动blive弹幕监听器...")
            
            # 创建blive应用实例
            app = BLiver(self.room_id)
            
            # 注册弹幕处理器
            @app.on(Events.DANMU_MSG)
            async def on_danmaku(ctx: BLiverCtx):
                await self.handle_blive_danmaku(ctx)

            @app.on(Events.SEND_GIFT)
            async def on_gift(ctx: BLiverCtx):
                await self.handle_blive_gift(ctx)

            @app.on(Events.INTERACT_WORD)
            async def on_interact(ctx: BLiverCtx):
                try:
                    data = ctx.body.get('data', {})
                    if data.get('msg_type') == 1:
                        uname = data.get('uname', 'unknown')
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
                    logger.error(f" 处理进入房间事件失败: {e}")
                finally:
                    self._reset_idle_timer()

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
                            emojis)
                except Exception as e:
                    logger.error(f" 处理 WELCOME 事件失败: {e}")
                finally:
                    self._reset_idle_timer()

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
            logger.error(f" blive监听器启动失败: {str(e)}")
            # 尝试使用备用方案
            self.start_bilibili_live_listener()
    
    def start_bilibili_live_listener(self):
        """启动bilibili-live弹幕监听器"""
        if not BILIBILI_LIVE_AVAILABLE:
            logger.error(" bilibili-live库不可用")
            return False
            
        try:
            logger.info(" 启动bilibili-live弹幕监听器...")
            
            # 使用事件处理器类（让 bilibili_live 内部实例化）
            handler_cls = self.BilibiliLiveHandler
            
            bilibili_live = BilibiliLive()
            bilibili_live.schedule(handler_cls, self.room_id)
            bilibili_live.start()
            
            return True
            
        except Exception as e:
            logger.error(f" bilibili-live监听器启动失败: {e}")
            traceback.print_exc()
            return False
    
    async def run(self):
        """运行主程序"""
        try:
            logger.info("🎬 AI虚拟主播系统启动中...")
            logger.info("📱 房间号: {self.room_id}")
            await ensure_server()
            
            # 先启动闲聊守护协程，避免被阻塞
            asyncio.create_task(self._idle_chat_loop())
            
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
        logger.info(" 清理系统资源...")
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
                    continue
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
                        prompt_msg = f"最近和观众的互动: {summary}。你有什么想吐槽或回应的吗？"
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
                    logger.info(f" 选定表情: {tok} (segment='{seg}')")
                    return tok
        # 整体兜底搜索（极端情况如整段无换行）
        for pattern in (kaomoji_pat, emoji_pat, symbol_pat):
            tok = last_token(pattern, text)
            if tok:
                logger.info(f" 选定表情(全局兜底): {tok}")
                return tok
        logger.warning(" 未找到可用表情，将不发送弹幕")
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
            logger.debug("[self_det]  命中 UID")
            return True

        # 完整昵称匹配（使用NFKC归一化）
        if norm_self_full and norm_username == norm_self_full:
            logger.debug("[self_det]  命中完整昵称")
            return True

        if not mask:
            return False

        # 完全相同脱敏名
        if norm_username == mask:
            logger.debug("[self_det]  脱敏名完全相同")
            return True

        # 星号宽松匹配 - 支持半角 * 、全角 ＊ 及部分装饰星
        star_chars = "*＊★☆"
        additional_fillers = "．。.。！!?,，·。、… "  # 允许的中文/英文标点、空格及省略号
        star_pattern = rf"^{re.escape(mask[0])}[{re.escape(star_chars)}]+[{re.escape(additional_fillers)}]*$"
        if re.match(star_pattern, norm_username):
            logger.debug("[self_det]  星号宽松匹配命中")
            return True

        # 一般宽松匹配：首字符一致且其余全部由星号/标点组成
        if (
            norm_username and norm_username[0] == mask[0] and
            set(norm_username[1:]).issubset(set(star_chars + additional_fillers))
        ):
            logger.debug("[self_det]  首字符+填充字符匹配命中")
            return True

        logger.debug("[self_det]  判断为非自身弹幕")
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
        """清理不应朗读内容：括号动作 + emoji/符号"""
        import re, unicodedata
        cleaned = re.sub(r"[\(（][^\)\）]{0,30}[\)）]", "", text)
        cleaned = re.sub(r"[\U0001F300-\U0001F64F\U0001F680-\U0001FAFF]", "", cleaned)
        cleaned = re.sub(r"[\u2600-\u27BF]", "", cleaned)
        cleaned = unicodedata.normalize('NFKC', cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # 去掉 *／＊ 包裹的星号但保留内容
        cleaned = re.sub(r"[\*＊]([^\*＊]{1,30})[\*＊]", r"\\1", cleaned)
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
            return
        
        # 提前登录网易云，显示二维码
        try:
            await get_netease_client()
        except Exception as e:
            logger.error(f"网易云登录初始化失败: {e}")
        
        # 启动背景音乐
        try:
            await start_background_music()
        except Exception as e:
            logger.warning(f"背景音乐启动失败: {e}")
        
        # 创建并运行AI虚拟主播
        ai_vtuber = AIVTuber2025()
        await ai_vtuber.run()
        
    except Exception as e:
        logger.error(f" 程序启动失败: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    print(" B站AI虚拟主播弹幕回复系统 - 2025年版本")
    print("=" * 60)
    print(" 启动中...")
    
    # 运行异步主程序
    asyncio.run(main()) 