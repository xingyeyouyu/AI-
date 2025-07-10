#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复后的弹幕发送程序 - 正确处理cookies
只包含真正的B站cookies，排除其他配置项
"""

import requests
import time
import configparser
import json

def load_config():
    """加载配置文件，正确区分cookies和其他配置"""
    config = configparser.ConfigParser(interpolation=None)
    config.read('config.txt', encoding='utf-8')
    
    room_id = int(config.get('DEFAULT', 'room_id'))
    
    # 只获取真正的B站cookies
    valid_cookie_keys = {
        'sessdata', 'bili_jct', 'dedeuserid', 'dedeuserid__ckmd5', 
        'buvid3', 'buvid4'
    }
    
    cookies = {}
    cookies_section = config['COOKIES']
    for key, value in cookies_section.items():
        # 只处理有效的cookie键
        if key.lower() in valid_cookie_keys:
            # 处理百分号替换
            if '%%' in value:
                value = value.replace('%%', '%')
            cookies[key] = value
    
    return room_id, cookies

def send_danmaku_fixed(room_id, cookies, message):
    """发送弹幕 - 修复版本"""
    try:
        # 构建cookie字符串 - 只包含有效cookies
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        
        print(f"🔍 房间号: {room_id}")
        print(f"🔍 消息: {message}")
        print(f"🔍 有效Cookies: {list(cookies.keys())}")
        print(f"🔍 Cookie字符串长度: {len(cookie_str)}")
        
        # 准备请求
        url = 'https://api.live.bilibili.com/msg/send'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'https://live.bilibili.com/{room_id}',
            'Cookie': cookie_str,
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Origin': 'https://live.bilibili.com',
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        # 验证cookie字符串编码
        try:
            cookie_str.encode('latin-1')
            print("✅ Cookie字符串编码验证通过")
        except UnicodeEncodeError as e:
            print(f"❌ Cookie字符串编码失败: {e}")
            return False
        
        data = {
            'bubble': '0',
            'msg': message,
            'color': '16777215',
            'mode': '1',
            'fontsize': '25',
            'rnd': str(int(time.time())),
            'roomid': str(room_id),
            'csrf': cookies.get('bili_jct', ''),
            'csrf_token': cookies.get('bili_jct', '')
        }
        
        print(f"🔍 CSRF token: {cookies.get('bili_jct', '')[:10]}...")
        
        # 发送请求
        response = requests.post(url, headers=headers, data=data)
        
        print(f"🔍 响应状态: {response.status_code}")
        print(f"🔍 响应内容: {response.text}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                if result.get('code') == 0:
                    print(f"✅ 弹幕发送成功: {message}")
                    return True
                else:
                    error_msg = result.get('message', '未知错误')
                    print(f"❌ 弹幕发送失败: {error_msg}")
                    return False
            except:
                print(f"❌ 响应解析失败: {response.text}")
                return False
        else:
            print(f"❌ HTTP错误: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ 发送异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_login_status(cookies):
    """测试登录状态"""
    try:
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        
        url = 'https://api.bilibili.com/x/web-interface/nav'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': cookie_str
        }
        
        response = requests.get(url, headers=headers)
        result = response.json()
        
        if result.get('code') == 0:
            data = result.get('data', {})
            if data.get('isLogin'):
                username = data.get('uname', '未知用户')
                uid = data.get('mid', '未知UID')
                print(f"✅ 登录状态正常 - 用户: {username}, UID: {uid}")
                return True
            else:
                print("❌ 用户未登录")
                return False
        else:
            print(f"❌ 登录检查失败: {result.get('message')}")
            return False
            
    except Exception as e:
        print(f"❌ 登录检查异常: {e}")
        return False

def main():
    """主函数"""
    print("🎌 修复版弹幕发送测试")
    print("=" * 40)
    
    try:
        # 加载配置
        room_id, cookies = load_config()
        
        print(f"✅ 配置加载成功")
        print(f"   房间号: {room_id}")
        print(f"   有效Cookies数量: {len(cookies)}")
        
        # 测试登录状态
        print("\n🔐 检查登录状态...")
        if not test_login_status(cookies):
            print("❌ 登录状态检查失败，可能cookies已过期")
            return
        
        # 发送测试弹幕
        test_messages = [
            "🤖 AI助手测试弹幕",
            "✨ 2025年新系统上线",
            "🎵 弹幕发送功能正常"
        ]
        
        success_count = 0
        for i, message in enumerate(test_messages, 1):
            print(f"\n📤 发送第{i}条测试弹幕: {message}")
            
            if send_danmaku_fixed(room_id, cookies, message):
                success_count += 1
            
            # 发送间隔
            if i < len(test_messages):
                print("⏱️ 等待3秒...")
                time.sleep(3)
        
        print(f"\n📊 测试结果:")
        print(f"   成功发送: {success_count}/{len(test_messages)} 条弹幕")
        
        if success_count > 0:
            print("\n✅ 弹幕发送功能正常！")
            print("💡 请查看你的直播间是否出现了测试弹幕")
            print(f"🔗 直播间链接: https://live.bilibili.com/{room_id}")
            print("\n🎯 现在你可以用我的身份发送弹幕来测试监听功能！")
        else:
            print("\n❌ 弹幕发送失败！")
        
    except Exception as e:
        print(f"❌ 程序错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 