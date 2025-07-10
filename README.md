# Bilibili AI VTuber System (Open-Source Edition)

> Realtime bilibili live-room assistant powered by LLM + TTS. Listens to danmaku, generates AI replies, speaks with Edge-TTS, and can play background music or on-demand songs.

---

## ✨ Key Features

| 功能 | 说明 |
| ---- | ---- |
| 弹幕监听 | 支持 `blive` 与 `bilibili-live` 两套 SDK，按可用性自动切换 |
| AI 回复 | 集成 DeepSeek / OpenAI API，可通过 `llm_adapter.py` 接入本地 LLM |
| 语音合成 | Edge-TTS（或自定义 TTS 适配器）+ `pygame` 播放，支持中英文 |
| 字幕 Overlay | 内置 WebSocket 服务器，串流至 OBS / 浏览器展示字幕 |
| BGM 循环 | 自动循环播放网易云歌单，可在 `config.txt` 指定歌单 & 音量 |
| 点歌优先 | 通过 `*[Music]:歌名.歌手*` 指令点歌，自动暂停 BGM 并播放完毕后恢复 |
| YAML 预设 | `catgirl.yml / girl.yml / Nacho猫.yml` 等角色人设，支持自定义 |

---

## 🌱 Quick Start

```bash
# 1. 克隆仓库
$ git clone https://github.com/yourname/ai-vtuber-2025.git


# 2. 安装依赖 (Python 3.9+)
$ python -m pip install -r requirements.txt

# 3. 配置
$ cp config.txt.example config.txt  # 若仓库未附带，请手动创建
# 打开 config.txt，至少填写：
# [DEFAULT]
# room_id = 你的直播间ID
# deepseek.api_key = sk-xxx 或 OPENAI_API_KEY
# [COOKIES]
# SESSDATA = ...
# bili_jct = ...
# DedeUserID = ...

# 4. 运行
$ python sample_2025_ultimate.py
```

如需扫码登录网易云以播放付费歌曲，首次运行会在终端输出二维码 —— 用手机网易云 App 扫码即可。

---

## 🛠️ 目录结构（`tts3/`）

```
ai_action.py          # 音乐、指令调度
ai_voice.py           # 轻量级 DeepSeek + Edge-TTS 演示模块
sample_2025_ultimate.py  # 主程序（建议直接运行此文件）
config.txt            # 配置文件（请自行填写）
requirements.txt      # Python 依赖
preset_loader.py      # YAML 角色加载器
catgirl.yml           # 角色预设
music_login.py        # 网易云扫码登录
overlay_server.py     # 字幕 WebSocket 服务器
blive_patcher.py      # UA+Cookie 修补，绕过 412
util_fix.py           # 终端安全打印等小工具
...
```

---

## 🎵 控制指令示例

| 指令 | 效果 |
| --- | --- |
| `*[Music]:告白气球*` | 点播歌曲《告白气球》 |
| `*[Music]:none*` | 立即停止当前歌曲/BGM |
| `*[BGM]:"off"*` | 关闭背景音乐循环 |
| `*[BGM]:"on"*`  | 开启背景音乐循环 |

> AI 回复中若包含以上格式的指令，会被 `ai_action.py` 自动解析并执行。

---

## 📝 License

MIT License.  请随意 fork / star / 二创，但请保留原作者署名。

---

### Thanks

项目参考 & 致谢：

* DeepSeek / OpenAI
* blive – Bilibili Live Python SDK
* bilibili-live
* Edge-TTS
* 网易云音乐开放接口

祝使用愉快！ 
开发者：B站up主，星野の梦
