#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ai_voice.py
通用 AI 文本回复 → Edge TTS 语音播放 模块。
用法：
    from ai_voice import AIVoice
    ai = AIVoice(cfg)
    await ai.reply(username, message)

依赖：openai, edge_tts, pygame
"""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
import re

import openai as deepseek
import edge_tts
import pygame


class AIVoice:
    """封装 DeepSeek + EdgeTTS + pygame"""

    def __init__(
        self,
        *,
        deepseek_api_key: str,
        prompt: str,
        voice: str = "zh-CN-XiaoyiNeural",
        executor: Optional[ThreadPoolExecutor] = None,
        tmp_dir: Optional[Path] = None,
    ):
        self.prompt = prompt
        deepseek.api_key = deepseek_api_key
        self.voice = voice
        self.executor = executor or ThreadPoolExecutor(max_workers=2)
        self.tmp_dir = Path(tmp_dir) if tmp_dir else Path.cwd()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        # pygame mixer 全局只能 init 一次
        if not pygame.mixer.get_init():
            pygame.mixer.init()

    async def reply(self, username: str, message: str) -> str:
        """生成 AI 回复并播放语音，返回文本"""
        text = await self._generate_deepseek_reply(username, message)
        ok = await self._tts_and_play(text)
        if not ok:
            raise RuntimeError("TTS 播放失败")
        return text

    async def _generate_deepseek_reply(self, username: str, message: str) -> str:
        loop = asyncio.get_event_loop()
        resp = await loop.run_in_executor(
            self.executor,
            lambda: deepseek.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": self.prompt},
                    {"role": "user", "content": f"{username}: {message}"},
                ],
                max_tokens=150,
                temperature=0.8,
            ),
        )
        return resp.choices[0].message.content.strip()

    async def _tts_and_play(self, text: str) -> bool:
        """edge-tts 合成并播放 mp3"""
        filename = self.tmp_dir / f"ai_reply_{int(time.time()*1000)}.mp3"
        try:
            tts_text = self._clean_tts_text(text)
            if not tts_text:
                print('[ai_voice] 清理括号后文本为空，跳过 TTS')
                return True
            communicate = edge_tts.Communicate(tts_text, self.voice)
            await communicate.save(str(filename))
            await asyncio.get_event_loop().run_in_executor(self.executor, self._play_audio, filename)
            return True
        except Exception as e:
            print(f"[ai_voice] TTS 失败: {e}")
            return False
        finally:
            if filename.exists():
                try:
                    filename.unlink()
                except Exception:
                    pass

    def _clean_tts_text(self, text: str) -> str:
        """去掉括号指令 + emoji/符号"""
        cleaned = re.sub(r"[\(（][^\)\）]{0,30}[\)\）]", "", text)
        cleaned = re.sub(r"[\U0001F300-\U0001F64F\U0001F680-\U0001FAFF]", "", cleaned)
        cleaned = re.sub(r"[\u2600-\u27BF]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # 去掉 *包裹* 的星号
        cleaned = re.sub(r"[\*＊]([^\*＊]{1,30})[\*＊]", r"\\1", cleaned)
        return cleaned

    @staticmethod
    def _play_audio(path: Path):
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        except Exception as e:
            print(f"[ai_voice] 播放失败: {e}") 