#!/usr/bin/env python3
"""
db_fix.py - 完全抛弃config.txt，强制使用数据库配置

此脚本的作用:
1. 读取config.txt配置并迁移到数据库（如果有）
2. 创建一个空的config.txt.bak备份
3. 修改sample_2025_ultimate.py使其只使用数据库配置
"""
import os
import re
import shutil
import sys
from pathlib import Path

# 确保当前目录是项目根目录
project_root = Path(__file__).resolve().parent
os.chdir(project_root)

# 导入数据库模块
try:
    from database import config_db
    HAS_CONFIG_DB = True
    print("✅ 成功导入数据库模块")
except ImportError:
    HAS_CONFIG_DB = False
    print("❌ 无法导入数据库模块，请确保database目录存在且包含__init__.py")
    if not os.path.exists("database"):
        os.mkdir("database")
        with open("database/__init__.py", "w", encoding="utf-8") as f:
            f.write('"""数据库模块初始化文件"""')
        print("✅ 已创建database目录及初始化文件")
    sys.exit(1)

# 确保初始化数据库
config_db.init_db()
print("✅ 已初始化数据库")

# 迁移config.txt到数据库（如果存在）
config_path = Path("config.txt")
if config_path.exists():
    try:
        # 使用migrate_config.py进行迁移
        try:
            import migrate_config
            migrate_config.migrate_config()
            print("✅ 成功从config.txt迁移配置到数据库")
        except Exception as e:
            print(f"❌ 迁移失败: {e}")
            
        # 备份并删除config.txt
        if os.path.exists("config.txt.bak"):
            os.remove("config.txt.bak")
        shutil.copy("config.txt", "config.txt.bak")
        print(f"✅ 已备份config.txt为config.txt.bak")
        
        # 删除config.txt
        os.remove("config.txt")
        print("✅ 已删除config.txt")
    except Exception as e:
        print(f"❌ 处理config.txt出错: {e}")
else:
    print("⚠️ 未找到config.txt，跳过迁移步骤")

# 检查数据库中的设置
settings = config_db.get_all_settings()
if not settings:
    print("⚠️ 警告: 数据库中没有配置，请确保先配置虚拟主播")
else:
    print(f"✅ 数据库中有 {len(settings)} 条配置")
    
    # 检查关键配置
    important_keys = [
        "DEFAULT.room_id",
        "COOKIES.SESSDATA",
        "COOKIES.bili_jct",
        "COOKIES.DedeUserID"
    ]
    
    missing = []
    for key in important_keys:
        if key not in settings:
            missing.append(key)
    
    if missing:
        print(f"⚠️ 警告: 缺少重要配置: {', '.join(missing)}")
        print("请在配置界面填写这些值")
    else:
        print("✅ 所有重要配置已存在")

print("\n完成！系统已设置为仅使用数据库配置。请运行webui.py进行配置或运行sample_2025_ultimate.py启动虚拟主播。") 
 
 
 
 
 