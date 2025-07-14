from __future__ import annotations



"""config_db.py

SQLite 持久化配置存取工具。

首次运行时：

1. 自动在项目根目录创建 database/config.db。

2. 若表为空且同目录存在 config.txt，则读取其中内容并迁移到数据库。



接口：

- init_db()              初始化数据库（自动迁移）。

- get_setting(key)       获取单个配置值，若不存在返回 None。

- set_setting(key,value) 设置/更新配置。

- get_all_settings()     获取所有配置为 dict。

- sync_to_config_txt()   将数据库配置同步到config.txt文件

- sync_from_config_txt() 从config.txt文件同步配置到数据库

- check_required_settings() 检查必要配置是否存在



存储模型：单表 ``settings (key TEXT PRIMARY KEY, value TEXT)``。

"""



import configparser

import sqlite3

from pathlib import Path

import os

from typing import Any, Dict, Optional, List, Tuple



# ---------------------------------------------------------------------------

# 路径 / 连接工具

# ---------------------------------------------------------------------------



_THIS_DIR = Path(__file__).resolve().parent

_DB_PATH = _THIS_DIR / "config.db"

_CONFIG_TXT_PATH = _THIS_DIR.parent / "config.txt"  # 在项目根



# 确保目录存在

_THIS_DIR.mkdir(parents=True, exist_ok=True)





def _get_conn() -> sqlite3.Connection:  # noqa: D401

    """Return SQLite connection (row_factory dict for convenience)."""

    conn = sqlite3.connect(_DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn





# ---------------------------------------------------------------------------

# 初始化 & 迁移

# ---------------------------------------------------------------------------



def _migrate_from_config_txt(conn: sqlite3.Connection):

    """If config.txt exists, migrate key-values into DB (flat: SECTION.key)."""

    # 已废弃 config.txt 功能

    pass





def init_db():

    """Ensure DB & table exist; perform one-time migration if empty."""

    conn = _get_conn()

    with conn:

        conn.execute(

            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"

        )

    # The following check and migration logic is deprecated and causes issues.

    # It should be removed to prevent unexpected behavior with ghost config.txt files.

    # # 检查是否为空

    # cur = conn.execute("SELECT COUNT(*) AS cnt FROM settings")

    # if cur.fetchone()["cnt"] == 0:

    #     _migrate_from_config_txt(conn)

    conn.close()





# ---------------------------------------------------------------------------

# CRUD helpers

# ---------------------------------------------------------------------------



def get_setting(key: str) -> Optional[str]:

    conn = _get_conn()

    cur = conn.execute("SELECT value FROM settings WHERE key=?", (key,))

    row = cur.fetchone()

    conn.close()

    return row["value"] if row else None





def set_setting(key: str, value: Any):

    """设置配置项，即使是空值也会保存"""

    conn = _get_conn()

    # 将None值转换为空字符串

    str_value = "" if value is None else str(value)

    with conn:

        conn.execute(

            "INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str_value)

        )

    conn.close()





def delete_setting(key: str) -> bool:

    """从数据库中删除指定的配置项

    参数:

        key: 要删除的配置项键名



    返回:

        bool: 如果成功删除或键不存在则返回True，否则返回False

    """

    try:

        conn = _get_conn()

        with conn:

            # 先检查键是否存在

            cur = conn.execute("SELECT 1 FROM settings WHERE key=?", (key,))

            exists = cur.fetchone() is not None



            # 如果存在则删除

            if exists:

                conn.execute("DELETE FROM settings WHERE key=?", (key,))

                print(f"成功删除配置项: {key}")

            else:

                print(f"配置项不存在，无需删除: {key}")



        conn.close()

        return True

    except Exception as e:

        print(f"删除配置项失败: {key}, 错误: {e}")

        return False





def get_all_settings() -> Dict[str, str]:

    conn = _get_conn()

    cur = conn.execute("SELECT key,value FROM settings")

    result = {row["key"]: row["value"] for row in cur.fetchall()}

    conn.close()

    return result





# ---------------------------------------------------------------------------

# 同步功能

# ---------------------------------------------------------------------------



def sync_to_config_txt():

    """将数据库配置同步到config.txt文件"""

    # 已废弃 config.txt 功能

    return False, "config.txt 功能已废弃，请使用数据库配置"





def sync_from_config_txt() -> Tuple[bool, str]:

    """从config.txt文件同步配置到数据库"""

    # 已废弃 config.txt 功能

    return False, "config.txt 功能已废弃，请使用数据库配置"





# ---------------------------------------------------------------------------

# 配置检查功能

# ---------------------------------------------------------------------------



def check_required_settings() -> List[str]:

    """检查必要配置是否存在，返回缺失项列表"""

    settings = get_all_settings()

    missing = []

    

    # 必要配置项

    required_keys = [

        "DEFAULT.room_id",  # 直播间ID

        "COOKIES.SESSDATA",  # B站登录Cookie

        "COOKIES.bili_jct",  # B站CSRF Token

        "COOKIES.DedeUserID"  # B站用户ID

    ]

    

    # AI模型密钥(至少需要一个)

    ai_keys = [

        "DEFAULT.deepseek.api_key",

        "DEFAULT.gemini.api_key",

        "DEFAULT.openai.api_key",

        "DEFAULT.claude.api_key"

    ]

    

    # 检查必要配置

    for key in required_keys:

        if key not in settings or not settings[key].strip():

            missing.append(key)

    

    # 检查AI模型密钥

    has_ai_key = any(key in settings and settings[key].strip() for key in ai_keys)

    if not has_ai_key:

        missing.append("AI模型API密钥(至少需要一个)")

    

    return missing





def get_config_sections() -> Dict[str, Dict[str, str]]:

    """获取按部分分组的配置"""

    settings = get_all_settings()

    sections = {}

    

    for full_key, value in settings.items():

        if "." in full_key:

            section, key = full_key.split(".", 1)

            if section not in sections:

                sections[section] = {}

            sections[section][key] = value

        else:

            # 处理没有部分前缀的键

            if "DEFAULT" not in sections:

                sections["DEFAULT"] = {}

            sections["DEFAULT"][full_key] = value

    

    return sections 
 
 
 
 
 