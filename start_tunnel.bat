@echo off
chcp 65001 > nul
title Telegram Mini App HTTPS Tunnel
echo ======================================================================
echo    Telegram Mini App uchun bepul HTTPS Tunnel yaratilmoqda...
echo ======================================================================
echo.
echo Bu dastur sizga bepul HTTPS manzil beradi (masalan: https://xxxxx.lhrt.run)
echo O'sha manzilni .env faylidagi WEB_APP_URL ga qo'ysangiz,
echo Telegram ilovasining o'zida chiroyli ochiladi!
echo.
echo Bog'lanmoqda, kuting...
ssh -R 80:localhost:5000 localhost.run
pause
