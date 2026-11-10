import os
import sys
from dotenv import load_dotenv

# Принудительно настраиваем UTF-8 вывод для консоли Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Загружаем переменные из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

def validate_config():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("\n[ОШИБКА] Токен бота не указан!")
        print("Пожалуйста, откройте файл .env и укажите ваш токен в переменной BOT_TOKEN.")
        print("Пример: BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ\n")
        sys.exit(1)
