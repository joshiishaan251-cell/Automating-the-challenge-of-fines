@echo off
chcp 65001 > nul
title MSP Bank Statement Processor

:: 1. Переходим в папку со скриптом
cd /d "c:\Users\Logik\Downloads\Antigravity\MSP"

:: 2. Запускаем Python
echo --- ЗАПУСК ОБРАБОТКИ ВЫПИСКИ МСП ---
"C:\Users\Logik\AppData\Local\Python\bin\python.exe" process_statement.py

:: 3. Не закрываем окно сразу
echo.
echo Обработка завершена.
pause
