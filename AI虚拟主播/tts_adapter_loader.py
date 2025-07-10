# 直接导入根目录的 tts_adapter 模块
import sys
import os

# 添加根目录到 Python 路径
current_file = os.path.abspath(__file__)
current_dir = os.path.dirname(current_file)
root_dir = os.path.dirname(os.path.dirname(current_dir))

if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# 直接导入
from tts_adapter import *  # noqa: F403, F401 