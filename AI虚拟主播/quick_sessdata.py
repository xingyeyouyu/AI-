#!/usr/bin/env python3
# -*- coding: utf-8 -*-

print("🔍 快速获取SESSDATA指导")
print("=" * 40)
print()
print("📋 步骤：")
print("1. 确保你已经登录B站")
print("2. 在B站页面按 F12")
print("3. 点击 'Application'(应用程序) 标签")
print("4. 左侧展开 'Cookies' → 'https://www.bilibili.com'")
print("5. 在列表中找到 'SESSDATA' 行")
print("6. 复制 'Value' 列的值")
print()
print("💡 SESSDATA 大概长这样:")
print("   abc123def456ghi789...")
print()
print("📝 复制到剪贴板后，修改 config.txt:")
print("   将 SESSDATA = ")
print("   改为 SESSDATA = 你复制的值")
print()
print("🧪 然后运行测试:")
print("   python test_full_auth.py")
print()

sessdata = input("请粘贴SESSDATA值 (直接Enter跳过): ").strip()

if sessdata:
    try:
        # 读取配置
        import configparser
        config = configparser.ConfigParser(interpolation=None)
        config.read('config.txt', encoding='utf-8')
        
        # 更新SESSDATA
        config.set('COOKIES', 'SESSDATA', sessdata)
        
        # 保存
        with open('config.txt', 'w', encoding='utf-8') as f:
            config.write(f)
        
        print("✅ SESSDATA 已更新到 config.txt!")
        print("🧪 现在运行测试: python test_full_auth.py")
        
    except Exception as e:
        print(f"❌ 更新失败: {e}")
        print("请手动编辑 config.txt 文件")
else:
    print("⏭️ 已跳过，请手动更新 config.txt")

input("\n按Enter键退出...") 