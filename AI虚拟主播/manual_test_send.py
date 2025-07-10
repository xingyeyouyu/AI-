import configparser, requests, time, os

config=configparser.ConfigParser(interpolation=None)
config.optionxform=str
config.read('config.txt', encoding='utf-8')
room_id=int(config['DEFAULT']['room_id'])
cookies=dict(config['COOKIES'])

safe_pairs=[]
for k,v in cookies.items():
    try:
        v.encode('latin-1')
    except UnicodeEncodeError:
        continue
    safe_pairs.append(f"{k}={v}")

headers={
    'User-Agent':'Mozilla/5.0',
    'Referer':f'https://live.bilibili.com/{room_id}',
    'Origin':'https://live.bilibili.com',
    'Content-Type':'application/x-www-form-urlencoded',
    'Cookie':'; '.join(safe_pairs)
}

csrf=cookies.get('bili_jct','')

payload={
    'bubble':'0',
    'msg':'测试XYZ',
    'color':'16777215',
    'mode':'1',
    'fontsize':'25',
    'rnd':str(int(time.time())),
    'roomid':room_id,
    'csrf':csrf,
    'csrf_token':csrf
}

resp=requests.post('https://api.live.bilibili.com/xlive/web-room/v1/dM/send', data=payload, headers=headers)
print('status', resp.status_code)
print('text', resp.text) 