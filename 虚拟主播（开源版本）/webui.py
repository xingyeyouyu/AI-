from __future__ import annotations



"""webui.py

简单的 Flask Web UI，用于查看/编辑配置。

运行：

    python webui.py  # 默认 http://127.0.0.1:5000/

依赖：Flask

"""



from pathlib import Path

from typing import Dict

import tkinter as tk

from tkinter import messagebox

import os

import json

import configparser



from flask import Flask, redirect, render_template, request, url_for, flash, jsonify, send_file, Response



from database import config_db



# ---------------------------------------------------------------------------

# 初始化

# ---------------------------------------------------------------------------



config_db.init_db()



BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, template_folder=str(BASE_DIR / "frontend"), static_folder=str(BASE_DIR / "static"))

app.secret_key = 'ai_vtuber_2025'  # 用于flash消息



# 默认要维护的字段及提示

_FIELDS: Dict[str, str] = {

    # 基础配置

    "DEFAULT.room_id": "直播间ID",

    "DEFAULT.self.username": "主播用户名",

    "DEFAULT.preset_file": "预设文件名(例如:猫猫.yml)",

    "DEFAULT.owner_uid": "主播UID(可选)",

    "DEFAULT.owner_name": "主播名称(可选)",

    "DEFAULT.set": "AI人设提示词",

    "DEFAULT.auto_send": "自动发送弹幕(yes/no)",

    

    # AI模型配置

    "DEFAULT.llm.order": "模型顺序 (逗号分隔, 例: gemini,openai,deepseek)",

    "DEFAULT.deepseek.api_key": "DeepSeek API密钥",

    "DEFAULT.deepseek.api_base": "DeepSeek API基础URL",

    "DEFAULT.deepseek.model": "DeepSeek模型名称",

    "DEFAULT.deepseek.enable": "启用DeepSeek(yes/no)",

    "DEFAULT.deepseek.proxy": "DeepSeek代理地址",

    

    "DEFAULT.gemini.api_key": "Gemini API密钥",

    "DEFAULT.gemini.api_base": "Gemini API基础URL",

    "DEFAULT.gemini.model": "Gemini模型名称",

    "DEFAULT.gemini.enable": "启用Gemini(yes/no)",

    "DEFAULT.gemini.proxy": "Gemini代理地址",

    

    "DEFAULT.openai.api_key": "OpenAI API密钥",

    "DEFAULT.openai.api_base": "OpenAI API基础URL",

    "DEFAULT.openai.model": "OpenAI模型名称",

    "DEFAULT.openai.enable": "启用OpenAI(yes/no)",

    "DEFAULT.openai.proxy": "OpenAI代理地址",

    

    "DEFAULT.claude.api_key": "Claude API密钥",

    "DEFAULT.claude.api_base": "Claude API基础URL",

    "DEFAULT.claude.model": "Claude模型名称",

    "DEFAULT.claude.enable": "启用Claude(yes/no)",

    "DEFAULT.claude.proxy": "Claude代理地址",

    

    "DEFAULT.local.endpoint": "本地模型API地址",

    "DEFAULT.local.model": "本地模型名称",

    "DEFAULT.local.enable": "启用本地模型(yes/no)",

    "DEFAULT.local.proxy": "本地模型代理地址",

    

    # 网络配置

    "NETWORK.proxy": "HTTP代理地址 (例如:http://127.0.0.1:7890)",

    

    # B站Cookie配置

    "COOKIES.SESSDATA": "B站Cookie: SESSDATA",

    "COOKIES.bili_jct": "B站Cookie: bili_jct",

    "COOKIES.DedeUserID": "B站Cookie: DedeUserID",

    "COOKIES.DedeUserID__ckMd5": "B站Cookie: DedeUserID__ckMd5(可选)",

    "COOKIES.buvid3": "B站Cookie: buvid3(可选)",

    "COOKIES.buvid4": "B站Cookie: buvid4(可选)",

    "COOKIES.sid": "B站Cookie: sid(可选)",

    

    # TTS配置

    "TTS.provider": "TTS提供商(edge/vits/bertvits/gpt-sovits)",

    "TTS.url": "TTS API地址(vits时使用)",

    "TTS.local_url": "本地Simple API地址",

    "TTS.bertvits_url": "Bert-VITS2 API地址",

    "TTS.gptsovits_url": "GPT-SoVITS API地址",

    "TTS.speaker_id": "说话人ID(vits/bertvits时使用)",

    "TTS.format": "音频格式(mp3/wav/ogg/silk/flac)",

    "TTS.lang": "语言(auto/zh/ja/en/mix)",

    "TTS.length": "语音长度(速度调节)",

    "TTS.noise": "噪声参数(vits时使用)",

    "TTS.noisew": "噪声宽度参数(vits时使用)",

    "TTS.max": "分段阈值(vits时使用)",

    "TTS.emotion": "情感参数(bertvits/gpt-sovits时使用)",

    "TTS.sdp_ratio": "SDP比率(gpt-sovits时使用)",

    "TTS.ref_audio": "参考音频路径(gpt-sovits时使用)",

    "TTS.emotion_ref_audio_joy": "喜悦情绪参考音频",

    "TTS.emotion_ref_audio_angry": "愤怒情绪参考音频",

    "TTS.emotion_ref_audio_sad": "悲伤情绪参考音频",

    "TTS.emotion_ref_audio_surprise": "惊讶情绪参考音频",

    "TTS.emotion_ref_audio_fear": "恐惧情绪参考音频",

    "TTS.emotion_ref_audio_neutral": "平静情绪参考音频",

    

    # 音乐配置

    "MUSIC.bgm_playlist_id": "背景音乐歌单ID",

    "MUSIC.bgm_volume": "背景音乐音量(0.0-1.0)",

}



# 配置项分类

_CATEGORIES = {

    "基础配置": ["DEFAULT.room_id", "DEFAULT.self.username", "DEFAULT.preset_file", "DEFAULT.owner_uid", "DEFAULT.owner_name", "DEFAULT.set", "DEFAULT.auto_send"],

    "AI模型配置": ["DEFAULT.llm.order", 

                "DEFAULT.deepseek.api_key", "DEFAULT.deepseek.api_base", "DEFAULT.deepseek.model", "DEFAULT.deepseek.enable", "DEFAULT.deepseek.proxy",

                "DEFAULT.gemini.api_key", "DEFAULT.gemini.api_base", "DEFAULT.gemini.model", "DEFAULT.gemini.enable", "DEFAULT.gemini.proxy",

                "DEFAULT.openai.api_key", "DEFAULT.openai.api_base", "DEFAULT.openai.model", "DEFAULT.openai.enable", "DEFAULT.openai.proxy",

                "DEFAULT.claude.api_key", "DEFAULT.claude.api_base", "DEFAULT.claude.model", "DEFAULT.claude.enable", "DEFAULT.claude.proxy",

                "DEFAULT.local.endpoint", "DEFAULT.local.model", "DEFAULT.local.enable", "DEFAULT.local.proxy"],

    "网络配置": ["NETWORK.proxy"],

    "B站Cookie配置": ["COOKIES.SESSDATA", "COOKIES.bili_jct", "COOKIES.DedeUserID", "COOKIES.DedeUserID__ckMd5", 

                  "COOKIES.buvid3", "COOKIES.buvid4", "COOKIES.sid"],

    "TTS配置": ["TTS.provider", "TTS.url", "TTS.local_url", "TTS.bertvits_url", "TTS.gptsovits_url", "TTS.speaker_id", "TTS.format", 

             "TTS.lang", "TTS.length", "TTS.noise", "TTS.noisew", "TTS.max", "TTS.emotion", "TTS.sdp_ratio", "TTS.ref_audio",

             "TTS.emotion_ref_audio_joy", "TTS.emotion_ref_audio_angry", "TTS.emotion_ref_audio_sad", 

             "TTS.emotion_ref_audio_surprise", "TTS.emotion_ref_audio_fear", "TTS.emotion_ref_audio_neutral"],

    "音乐配置": ["MUSIC.bgm_playlist_id", "MUSIC.bgm_volume"],

}



# ---------------------------------------------------------------------------

# 路由

# ---------------------------------------------------------------------------



@app.route("/", methods=["GET"])

def index():

    settings = config_db.get_all_settings()

    missing = config_db.check_required_settings()

    

    # 检查配置完整性并显示提示

    if missing:

        flash(f"⚠️ 警告: 以下关键配置缺失: {', '.join(missing)}", "warning")

    

    # 构造表单初始值

    return render_template("index.html", 

                          fields=_FIELDS, 

                          settings=settings, 

                          categories=_CATEGORIES,

                          missing=missing)





@app.route("/save", methods=["POST"])

def save():

    # 保存提交的配置

    for key, label in _FIELDS.items():

        # 优先检查这个字段是否被标记为清除

        if f"{key}_clear" in request.form:

            config_db.delete_setting(key)

            continue  # 处理完清除操作后，跳过后续逻辑



        # 特殊处理启用开关类型的字段

        if key.endswith('.enable'):

            # 如果表单中有这个字段，说明复选框被勾选了

            if key in request.form:

                config_db.set_setting(key, 'yes')

            else:

                # 复选框未勾选，使用'no'表示禁用

                config_db.set_setting(key, 'no')

        # 只处理表单中存在的其他字段

        elif key in request.form:

            val = request.form.get(key, "").strip()

            # 只有当值不为空时才保存，空值不保存也不删除（除非被标记为_clear）

            if val:

                config_db.set_setting(key, val)

    

    flash("✅ 配置已保存到数据库", "success")

    return redirect(url_for("index"))





@app.route("/clear_section/<section>", methods=["POST"])

def clear_section(section):

    """清除特定分类下的所有配置"""

    if section in _CATEGORIES:

        keys = _CATEGORIES[section]

        deleted_count = 0

        

        for key in keys:

            try:

                # 检查是否是开关类型字段

                if key.endswith('.enable'):

                    # 将开关设置为关闭状态

                    config_db.set_setting(key, 'no')

                else:

                    # 删除其他类型的配置

                    config_db.delete_setting(key)

                deleted_count += 1

            except Exception as e:

                print(f"删除配置项 {key} 失败: {e}")

        

        flash(f"✅ 已清除 {section} 中的 {deleted_count} 个配置项", "success")

    else:

        flash(f"❌ 未知的配置分类: {section}", "danger")

    

    return redirect(url_for("index"))





@app.route("/check", methods=["GET"])

def check():

    missing = config_db.check_required_settings()

    

    if not missing:

        flash("✅ 所有关键配置已设置", "success")

    else:

        flash(f"⚠️ 以下配置缺失: {', '.join(missing)}", "warning")

    

    return redirect(url_for("index"))





@app.route("/export", methods=["GET"])

def export_config():

    """导出配置为JSON文件"""

    settings = config_db.get_all_settings()

    if not settings:

        flash("❌ 没有可导出的配置", "danger")

        return redirect(url_for("index"))

    

    # 创建JSON响应

    response = Response(

        json.dumps(settings, indent=2, ensure_ascii=False),

        mimetype="application/json",

        headers={"Content-Disposition": "attachment;filename=vtuber_config.json"}

    )

    return response





@app.route("/import", methods=["POST"])

def import_config():

    """从JSON文件导入配置"""

    if "config_file" not in request.files:

        flash("❌ 未选择文件", "danger")

        return redirect(url_for("index"))

    

    file = request.files["config_file"]

    if file.filename == "":

        flash("❌ 未选择文件", "danger")

        return redirect(url_for("index"))

    

    try:

        # 读取JSON文件

        config_data = json.loads(file.read().decode("utf-8"))

        count = 0

        

        # 导入配置

        for key, value in config_data.items():

            config_db.set_setting(key, value)

            count += 1

        

        flash(f"✅ 成功导入{count}个配置项", "success")

    except Exception as e:

        flash(f"❌ 导入失败: {e}", "danger")

    

    return redirect(url_for("index"))





@app.route("/reset", methods=["POST"])

def reset_config():

    """重置配置(清空数据库)"""

    try:

        conn = config_db._get_conn()

        with conn:

            conn.execute("DELETE FROM settings")

        conn.close()

        flash("✅ 配置已重置", "success")

    except Exception as e:

        flash(f"❌ 重置失败: {e}", "danger")

    

    return redirect(url_for("index"))





@app.route("/api/config", methods=["GET"])

def api_get_config():

    """API接口: 获取所有配置"""

    settings = config_db.get_all_settings()

    return jsonify(settings)





@app.route("/api/config/<key>", methods=["GET"])

def api_get_setting(key):

    """API接口: 获取单个配置"""

    value = config_db.get_setting(key)

    if value is None:

        return jsonify({"error": "配置不存在"}), 404

    return jsonify({key: value})





@app.route("/api/check", methods=["GET"])

def api_check_config():

    """API接口: 检查配置完整性"""

    missing = config_db.check_required_settings()

    return jsonify({

        "success": len(missing) == 0,

        "missing": missing

    })





if __name__ == "__main__":

    import webbrowser

    

    # 显示配置状态窗口

    root = tk.Tk()

    root.withdraw()  # 隐藏主窗口

    

    # 检查配置完整性

    missing = config_db.check_required_settings()

    

    # 检查config.txt是否存在

    config_txt_path = BASE_DIR / "config.txt"

    config_txt_exists = config_txt_path.exists()

    

    if missing:

        missing_str = "\n".join([f"- {k}" for k in missing])

        message = f"以下关键配置缺失:\n{missing_str}\n\n请在Web界面中完成配置。"

        

        # 如果config.txt存在但数据库没有配置，提示导入

        if config_txt_exists and len(config_db.get_all_settings()) == 0:

            message += "\n\n检测到config.txt文件存在，可以在Web界面中点击'从配置文件导入'按钮导入配置。"

        

        messagebox.showwarning("配置检查", message)

    else:

        messagebox.showinfo("配置检查", "所有关键配置已设置，系统可以正常运行。")



    url = "http://127.0.0.1:5000/"

    print(f"🌐 Web UI running at {url}")

    try:

        webbrowser.open(url)

    except Exception:

        pass

    app.run(debug=False) 
 
 
 
 
 