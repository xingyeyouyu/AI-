#!/usr/bin/env python3
"""blive_patcher.py
在导入 blive 之前调用，自动把完整 Cookie 与指纹 UA 写入所有 aiohttp 请求头，
以规避 B 站 412 / 风控。
"""
from __future__ import annotations
import aiohttp, inspect, functools
from pathlib import Path
from util_fix import load_config, safe_print as print

CFG_PATH = Path(__file__).resolve().parent / 'config.txt'
config = load_config(CFG_PATH)

pairs = []
for k, v in config['COOKIES'].items():
    if k.startswith('#'):
        continue
    try:
        v.encode('latin-1')
    except UnicodeEncodeError:
        continue
    pairs.append(f"{k}={v}")

cookie_str = '; '.join(pairs)

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

if cookie_str:
    print(' blive_patcher: 注入完整 Cookie 头，长度', len(cookie_str))
else:
    print(' blive_patcher: 未找到 Cookie 字符串，可能仍会 412')

_orig_init = aiohttp.ClientSession.__init__

@functools.wraps(_orig_init)
def _patched_init(self, *args, **kwargs):
    headers = kwargs.get('headers') or {}
    # 复制原 headers 避免修改外部引用
    headers = dict(headers)
    headers.setdefault('User-Agent', UA)
    headers.setdefault('Referer', 'https://live.bilibili.com/')
    if cookie_str:
        headers.setdefault('Cookie', cookie_str)
    kwargs['headers'] = headers
    return _orig_init(self, *args, **kwargs)

aiohttp.ClientSession.__init__ = _patched_init

print(' blive_patcher: aiohttp.ClientSession 已打补丁')