@echo off
chcp 65001 > nul
title Universal Sorter - Fast Run

:: 1. Кладем пп Армель в эту папку со скриптом. Переходим в папку со скриптом (чтобы он видел config.yaml) его нет пока
cd /d "C:\Users\Logik\Downloads\Antigravity\SORTER_PP"

:: 2. Запускаем Python по твоему пути
echo --- ЗАПУСК БЫСТРОЙ СОРТИРОВКИ ---
"C:\Users\Logik\AppData\Local\Python\bin\python.exe" sort_payments.py

:: 3. Не закрываем окно сразу, чтобы ты успел прочитать отчет
echo.
pause