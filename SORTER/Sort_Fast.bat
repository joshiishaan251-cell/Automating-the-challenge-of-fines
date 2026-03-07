@echo off
chcp 65001 > nul
title Universal Sorter - Fast Run

:: 1. Переходим в папку со скриптом (чтобы он видел config.yaml)
cd /d "C:\Users\Logik\Downloads\Antigravity\SORTER"

:: 2. Запускаем Python по твоему пути
echo --- ЗАПУСК БЫСТРОЙ СОРТИРОВКИ ---
"C:\Users\Logik\AppData\Local\Python\bin\python.exe" universal_sorter.py

:: 3. Не закрываем окно сразу, чтобы ты успел прочитать отчет
echo.
pause