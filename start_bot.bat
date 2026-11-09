@echo off
chcp 65001 > nul
title Telegram Ombor AI Boti
echo ======================================================
echo    Telegram Ombor va Qoldiqlar AI Boti ishga tushmoqda...
echo ======================================================
echo.

REM Tekshirish: .env fayl mavjudmi?
if not exist .env (
    echo [OGOHLANTIRISH] .env fayli topilmadi! .env.example dan nusxa olinmoqda...
    copy .env.example .env
    echo Iltimos, .env faylini ochib BOT_TOKEN ni kiriting va qayta ishga tushiring!
    pause
    exit /b
)

echo 1. Kutubxonalar tekshirilmoqda...
python -m pip install -r requirements.txt

echo.
echo 2. Bot ishga tushirilmoqda...
python main.py

pause
