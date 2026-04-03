# settings.py  放在项目根目录
from pathlib import Path
from dotenv import load_dotenv
import os

# 自动找根目录 .env（智能版）
def find_env_file():
    current = Path(__file__).resolve()
    for _ in range(10):
        env = current / ".env"
        if env.exists():
            return env
        current = current.parent
    raise Exception("请在项目根目录创建 .env 文件")

load_dotenv(find_env_file(), override=True)

# 导出环境变量方法
def env(key, default=None):
    return os.getenv(key, default)