#!/usr/bin/env python3
"""
check_api_keys.py - 用于检查数据库中API密钥的值

这个脚本会列出所有API密钥相关的数据库条目，帮助诊断清除API密钥后仍回填的问题
"""
from database import config_db
import sqlite3

def main():
    # 初始化数据库
    config_db.init_db()
    
    # 获取数据库连接
    conn = sqlite3.connect(config_db._DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # 查询所有带有api_key的设置
    print("=== 检查数据库中的API密钥 ===")
    cursor = conn.execute("SELECT key, value FROM settings WHERE key LIKE '%api_key%'")
    rows = cursor.fetchall()
    
    if not rows:
        print("数据库中没有找到API密钥相关条目")
    else:
        print(f"找到 {len(rows)} 个API密钥相关条目:")
        for row in rows:
            key = row["key"]
            value = row["value"]
            # 掩盖显示密钥值，只显示前3个和后3个字符
            if value:
                masked_value = value[:3] + "..." + value[-3:] if len(value) > 6 else value
            else:
                masked_value = "[空]"
            print(f"  {key}: {masked_value} (长度: {len(value)})")
    
    # 检查可能影响Gemini API的特定字段
    print("\n=== 特定检查Gemini相关字段 ===")
    gemini_fields = [
        "DEFAULT.gemini.api_key",
        "DEFAULT.gemini.enable",
        "DEFAULT.gemini.model",
        "DEFAULT.gemini.api_base",
        "DEFAULT.gemini.proxy",
        "DEFAULT.self.username"  # 检查用户名字段
    ]
    
    for field in gemini_fields:
        cursor = conn.execute("SELECT value FROM settings WHERE key=?", (field,))
        row = cursor.fetchone()
        value = row["value"] if row else None
        
        if value is not None:
            if "api_key" in field and value:
                masked_value = value[:3] + "..." + value[-3:] if len(value) > 6 else value
            else:
                masked_value = value
            print(f"  {field}: {masked_value}")
        else:
            print(f"  {field}: [不存在]")
    
    # 提供删除特定键的选项
    print("\n=== 修复选项 ===")
    print("如果需要删除特定的API密钥，可以输入相应的选项:")
    print("1. 删除Gemini API密钥")
    print("2. 删除所有API密钥")
    print("3. 退出")
    
    choice = input("请选择操作 (1-3): ").strip()
    
    if choice == "1":
        config_db.delete_setting("DEFAULT.gemini.api_key")
        print("已删除 DEFAULT.gemini.api_key")
    elif choice == "2":
        for row in rows:
            config_db.delete_setting(row["key"])
        print(f"已删除所有 {len(rows)} 个API密钥")
    elif choice == "3":
        print("未进行任何操作")
    else:
        print("无效选择")
    
    conn.close()
    print("\n操作完成。请检查webui页面是否仍回填API密钥。")
    input("按Enter键继续...")

if __name__ == "__main__":
    main() 
 
 
 
 
 