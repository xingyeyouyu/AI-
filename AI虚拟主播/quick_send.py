import sys, configparser
from sample_2025_ultimate import DanmakuSender

config=configparser.ConfigParser(interpolation=None); config.optionxform=str
config.read('config.txt', encoding='utf-8')
room_id=int(config['DEFAULT']['room_id'])
sender=DanmakuSender(room_id, dict(config['COOKIES']))
msg=sys.argv[1] if len(sys.argv)>1 else '测试'
print('send:', msg)
print(sender.send_danmaku(msg)) 