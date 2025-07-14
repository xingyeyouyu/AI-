"""TTS 适配器抽象层

使用方法：

    from tts_adapter import TTSAdapterFactory
    tts = TTSAdapterFactory.from_config(cfg_dict)
    audio_file = await tts.synthesize("你好")

EdgeTTSProvider: 默认使用 edge_tts 在线合成
VITSHTTPProvider: 兼容 vits-simple-api 接口
GPTSoVITSProvider: 支持 GPT-SoVITS 接口
"""
from __future__ import annotations

import abc
import asyncio
import tempfile
import uuid
import pathlib
import re
import os
from typing import Dict, Any, Optional

class BaseTTSProvider(abc.ABC):
    name: str = "base"

    def __init__(self, config: Dict[str, Any]):
        self.config = config

    @abc.abstractmethod
    async def synthesize(self, text: str) -> str:
        """合成并返回本地音频文件路径 (mp3/wav 等)"""

    async def cleanup(self, path: str):
        try:
            pathlib.Path(path).unlink(missing_ok=True)
        except Exception:
            pass
    
    def detect_emotion(self, text: str) -> tuple[str, Optional[str]]:
        """检测文本中的情感标记，返回(清理后的文本, 情感类型)"""
        # 匹配 *[emotion]:喜悦* 或 *[情感]:喜悦* 格式
        emotion_pattern = r'\*\[(emotion|情感)\]:(喜悦|愤怒|悲伤|惊讶|恐惧|平静)\*'
        match = re.search(emotion_pattern, text)
        
        if match:
            emotion_type = match.group(2)
            # 移除情感标记
            clean_text = re.sub(emotion_pattern, '', text).strip()
            return clean_text, emotion_type
        
        return text, None
    
    def get_emotion_ref_audio(self, emotion: Optional[str]) -> Optional[str]:
        """根据情感类型获取对应的参考音频路径"""
        if not emotion:
            return None
            
        # 情感类型到配置键的映射
        emotion_map = {
            "喜悦": "emotion_ref_audio_joy",
            "愤怒": "emotion_ref_audio_angry",
            "悲伤": "emotion_ref_audio_sad",
            "惊讶": "emotion_ref_audio_surprise",
            "恐惧": "emotion_ref_audio_fear",
            "平静": "emotion_ref_audio_neutral"
        }
        
        config_key = emotion_map.get(emotion)
        if not config_key:
            return None
            
        # 从配置中获取参考音频路径
        ref_audio = self.config.get(config_key)
        if ref_audio and os.path.exists(ref_audio):
            return ref_audio
            
        # 检查默认位置
        project_root = pathlib.Path(__file__).parent
        default_path = project_root / "reference_audio" / f"{emotion}.wav"
        if default_path.exists():
            return str(default_path)
            
        return None

class EdgeTTSProvider(BaseTTSProvider):
    name = "edge"

    async def synthesize(self, text: str) -> str:
        import edge_tts
        voice = self.config.get("voice", "zh-CN-XiaoyiNeural")
        # 简单清理，移除特殊动作括号 (如 "(动作)文本" )
        def _clean_tts_text(x: str) -> str:  # noqa: ANN001
            import re
            # 去掉形如 (动作) 的无声动作标记
            x = re.sub(r"\([^)]*\)", "", x)
            # 去掉多余空白
            return x.strip()

        # 检测情感标记
        clean_text, _ = self.detect_emotion(text)
        
        clean = _clean_tts_text
        tts_text = clean(clean_text)
        if not tts_text:
            raise ValueError("Empty text after clean")
        tmp = pathlib.Path(tempfile.gettempdir()) / f"tts_{uuid.uuid4().hex}.mp3"
        communicate = edge_tts.Communicate(tts_text, voice)
        await communicate.save(str(tmp))
        return str(tmp)

class VITSHTTPProvider(BaseTTSProvider):
    name = "vits"

    async def synthesize(self, text: str) -> str:
        import httpx, urllib.parse, os
        url = self.config.get("url")
        if not url:
            raise ValueError("vits provider requires 'url' in config")
            
        # 检测情感标记
        clean_text, emotion = self.detect_emotion(text)
        
        params = {
            "text": clean_text,
            "id": self.config.get("speaker_id", 0),
            "format": self.config.get("format", "mp3"),
        }
        # 可选参数如 emotion/noise
        for k in ("noise", "noisew", "lang", "length", "max"):
            if k in self.config:
                params[k] = self.config[k]
                
        # 如果检测到情感，覆盖配置中的情感参数
        if emotion and "emotion" in self.config:
            params["emotion"] = emotion
        elif "emotion" in self.config:
            params["emotion"] = self.config["emotion"]
            
        query = urllib.parse.urlencode(params, safe=",[]")
        full_url = f"{url}?{query}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(full_url)
            r.raise_for_status()
            ext = params["format"]
            tmp = pathlib.Path(tempfile.gettempdir()) / f"tts_{uuid.uuid4().hex}.{ext}"
            tmp.write_bytes(r.content)
            return str(tmp)

class GPTSoVITSProvider(BaseTTSProvider):
    name = "gpt-sovits"
    
    async def synthesize(self, text: str) -> str:
        import httpx, urllib.parse, os
        url = self.config.get("gptsovits_url")
        if not url:
            raise ValueError("gpt-sovits provider requires 'gptsovits_url' in config")
            
        # 检测情感标记
        clean_text, emotion = self.detect_emotion(text)
        
        # 获取参考音频
        ref_audio = None
        if emotion:
            ref_audio = self.get_emotion_ref_audio(emotion)
        
        # 如果没有找到情感对应的参考音频，使用默认参考音频
        if not ref_audio:
            ref_audio = self.config.get("ref_audio")
            
        if not ref_audio:
            raise ValueError("gpt-sovits requires reference audio")
            
        # 准备请求参数
        params = {
            "text": clean_text,
            "format": self.config.get("format", "mp3"),
        }
        
        # 可选参数
        for k in ("sdp_ratio", "lang"):
            if k in self.config:
                params[k] = self.config[k]
                
        # 构建 multipart/form-data 请求
        files = {"reference_audio": open(ref_audio, "rb")}
        
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(url, data=params, files=files)
            r.raise_for_status()
            ext = params.get("format", "mp3")
            tmp = pathlib.Path(tempfile.gettempdir()) / f"tts_{uuid.uuid4().hex}.{ext}"
            tmp.write_bytes(r.content)
            return str(tmp)

class TTSAdapterFactory:
    _providers = {
        EdgeTTSProvider.name: EdgeTTSProvider,
        VITSHTTPProvider.name: VITSHTTPProvider,
        "bertvits": VITSHTTPProvider,  # 复用同一 HTTP 调用方式，只需在 config.url 指向本地 bert-vits 服务
        "gpt-sovits": GPTSoVITSProvider,
    }

    @classmethod
    def from_config(cls, cfg: Dict[str, Any]):
        provider_key: str = cfg.get("provider", "edge").lower()
        provider_cls = cls._providers.get(provider_key)
        if not provider_cls:
            raise ValueError(f"Unknown TTS provider '{provider_key}'")
        return provider_cls(cfg) 