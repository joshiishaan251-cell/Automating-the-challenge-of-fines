@echo off
chcp 65001 > nul
title Universal Sorter - FORCE UPDATE

:: 1. Переходим в папку
cd /d "C:\Users\Logik\Downloads\Antigravity\SORTER"

:: 2. Удаляем файл кэша (если он есть)
if exist archive_cache.json (
    echo Удаляю старый кэш для полного пересканирования...
    del archive_cache.json
)

:: 3. Запускаем скрипт (он сам создаст новый кэш)
echo --- ЗАПУСК ПОЛНОЙ ИНДЕКСАЦИИ ---
"C:\Users\Logik\AppData\Local\Python\bin\python.exe" universal_sorter.py

echo.
echo Индексация завершена!
pause