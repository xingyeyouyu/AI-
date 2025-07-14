# B站AI虚拟主播弹幕回复系统 - 2025终极版

这是一个基于AI的B站虚拟主播系统，支持弹幕监听、AI回复生成、语音合成、表情控制等功能。

## 快速开始

1. 双击 `启动配置界面.bat` 打开配置界面，设置必要参数
2. 双击 `启动虚拟主播.bat` 启动虚拟主播系统

## 系统要求

- Python 3.8 或更高版本
- 安装了所需依赖库（见 requirements.txt）
- B站账号登录凭据（SESSDATA, bili_jct, DedeUserID）
- 至少一个AI模型的API密钥（支持Gemini, OpenAI, DeepSeek, Claude等）

## 配置系统

本系统支持两种配置方式：

### 1. Web界面配置（推荐）

通过Web界面可以方便地管理所有配置项，支持以下功能：

- 分类显示配置项
- 导入/导出配置
- 配置检查和验证
- 与config.txt文件同步

运行 `启动配置界面.bat` 或执行 `python webui.py` 打开配置界面。

### 2. 配置文件（config.txt）

系统也支持直接编辑 `config.txt` 文件进行配置，格式如下：

```ini
[DEFAULT]
room_id = 12345678
deepseek.api_key = sk-xxxxxxxx
preset_file = 猫猫.yml

[COOKIES]
SESSDATA = xxxxxxxx
bili_jct = xxxxxxxx
DedeUserID = xxxxxxxx

[NETWORK]
proxy = http://127.0.0.1:7890

[TTS]
provider = edge
```

首次启动时，系统会自动将config.txt中的配置同步到数据库。

## 表情控制

本系统支持通过AI回复中的特殊格式控制VTube Studio表情，**不需要在数据库中配置热键**，AI只需按照以下格式输出即可：

### 表情控制格式

```
<"表情名":on>  - 开启表情
<"表情名":off> - 关闭表情
<"表情名">     - 一次性触发表情
```

### 特殊表情

- **纸扇开合**: 每次触发会自动翻转状态（开→合→开→合...）
- **吐舌**: 开启后会在3秒后自动关闭
- **待机动作**: TTS播放完毕3.5秒后自动触发
- **打断待机**: 任何弹幕到达时自动触发

### 示例

```
我好开心啊！<"脸红":on><"笑">

今天天气真好呢~<"眨眼">

哎呀，好害羞...<"脸红":on>

我不害羞了！<"脸红":off>

让我想想...<"思考":on>我知道了！<"思考":off><"开心">
```

## 其他控制指令

除了表情控制外，AI还可以使用以下控制指令：

### 音乐控制

```
*[Music]:歌名*             - 点播歌曲
*[Music]:歌名.歌手*        - 指定歌手点播歌曲
*[Music]:none*             - 停止音乐

*[BGM]:"on"*              - 开启背景音乐
*[BGM]:"off"*             - 关闭背景音乐
*[BGM]:歌单ID*            - 切换背景音乐歌单
```

## 数据库与配置文件

系统使用SQLite数据库（database/config.db）存储配置，同时保持与config.txt的兼容性：

- 首次启动时，如果数据库为空但config.txt存在，会自动导入配置
- 可以通过Web界面在数据库和config.txt之间同步配置
- 程序启动时会优先从数据库读取配置，如果数据库为空则从config.txt读取

### 配置项说明

主要配置项包括：

1. **基础配置**（DEFAULT部分）
   - room_id: B站直播间ID
   - self.username: 主播用户名
   - preset_file: 预设文件名（如猫猫.yml）
   - deepseek.api_key, gemini.api_key等: AI模型API密钥

2. **Cookie配置**（COOKIES部分）
   - SESSDATA, bili_jct, DedeUserID等B站登录凭据

3. **网络配置**（NETWORK部分）
   - proxy: 代理服务器地址（如http://127.0.0.1:7890）

4. **音乐配置**（MUSIC部分）
   - bgm_playlist_id: 背景音乐歌单ID
   - bgm_volume: 背景音乐音量（0.0-1.0）

5. **TTS配置**（TTS部分）
   - provider: TTS提供商（edge/vits/bertvits）
   - 其他TTS相关参数

## 常见问题

1. **无法连接B站**: 检查网络连接和Cookie配置
2. **AI不回复**: 检查AI模型API密钥和网络代理设置
3. **表情不生效**: 确保VTube Studio已启动并允许API连接
4. **音乐无法播放**: 检查网易云登录和音乐配置
5. **配置不生效**: 检查是否保存了配置并重启了程序

## 开发者说明

- 系统使用blive和bilibili-live库监听弹幕
- AI回复通过LLMRouter支持多模型回退
- 表情控制通过WebSocket连接VTube Studio
- 配置界面基于Flask实现
- 配置存储使用SQLite数据库，位于database/config.db

### API接口

系统提供以下API接口用于外部程序集成：

- `GET /api/config` - 获取所有配置
- `GET /api/config/<key>` - 获取指定配置项
- `GET /api/check` - 检查配置完整性 
 
 
 
 
 