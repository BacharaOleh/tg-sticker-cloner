@echo off
chcp 65001 > nul
echo ====================================================
echo Запуск Telegram Sticker Cloner бота...
echo ====================================================

IF NOT EXIST ".venv\Scripts\python.exe" (
    echo Виртуальное окружение не найдено. Создаем .venv...
    python -m venv .venv
    echo Установка зависимостей...
    .venv\Scripts\python.exe -m pip install -r requirements.txt
)

.venv\Scripts\python.exe bot.py
pause
