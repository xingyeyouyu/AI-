#!/usr/bin/env python3
"""blive_patcher.py
在导入 blive 之前调用，自动把完整 Cookie 与指纹 UA 写入所有 aiohttp 请求头，
以规避 B 站 412 / 风控。

此版本完全使用数据库配置，不再依赖config.txt文件。
"""
from __future__ import annotations
import aiohttp, inspect, functools
import os
import logging

# 初始化日志
logger = logging.getLogger(__name__)

# 尝试从数据库获取配置
try:
    from database import config_db
    config_db.init_db()
    HAS_CONFIG_DB = True
    logger.info("成功从数据库模块导入配置")
except ImportError:
    HAS_CONFIG_DB = False
    logger.warning("未能导入数据库模块，Cookie功能可能受限")

# 获取Cookie
cookie_str = ""
pairs = []

if HAS_CONFIG_DB:
    # 从数据库获取Cookie配置
    settings = config_db.get_all_settings()
    if settings:
        for key, value in settings.items():
            if key.startswith('COOKIES.'):
                cookie_name = key.split('.', 1)[1]
                # 跳过注释
                if cookie_name.startswith('#'):
                    continue
                # 检查是否可以编码为latin-1
                try:
                    value.encode('latin-1')
                    pairs.append(f"{cookie_name}={value}")
                except UnicodeEncodeError:
                    logger.warning(f"跳过包含非 latin-1 字符的 Cookie: {cookie_name}")
                    continue
    else:
        logger.warning("数据库中无配置或配置为空")
else:
    logger.warning("未使用数据库配置，Cookie功能将不可用")

cookie_str = '; '.join(pairs)

# 默认UA
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'

if cookie_str:
    print('👾 blive_patcher: 注入完整 Cookie 头，长度', len(cookie_str))
else:
    print('⚠️ blive_patcher: 未找到 Cookie 字符串，可能仍会 412')

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

print('✅ blive_patcher: aiohttp.ClientSession 已打补丁') 