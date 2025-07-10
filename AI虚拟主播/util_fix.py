#!/usr/bin/env python3
"""util_fix.py
通用工具：
1. safe_print -> 过滤非 ASCII 字符，避免 Windows 控制台编码错误
2. load_config -> 始终以脚本所在目录查找 config.txt
"""
from __future__ import annotations
from pathlib import Path
import builtins
import configparser
import sys


def safe_print(*args, **kwargs):
    filtered = []
    for arg in args:
        if isinstance(arg, str):
            filtered.append(arg.encode('ascii', 'ignore').decode('ascii'))
        else:
            filtered.append(arg)
    builtins.print(*filtered, **kwargs)


def load_config(script_path: str | Path) -> configparser.ConfigParser:
    script_dir = Path(script_path).resolve().parent
    cfg_path = script_dir / 'config.txt'
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(cfg_path, encoding='utf-8')
    return cfg

# monkey-patch stdout encoding if needed
try:
    if sys.stdout.encoding and 'utf' not in sys.stdout.encoding.lower():
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
except Exception:
    pass 