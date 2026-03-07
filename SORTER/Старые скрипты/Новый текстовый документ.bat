@echo off
chcp 65001 > nul
echo --- СБРОС ПРОКСИ И УСТАНОВКА ---

:: 1. Очищаем переменные окружения, которые могут мешать
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set http_proxy=
set https_proxy=

:: 2. Пробуем установить библиотеку напрямую
echo Устанавливаю openpyxl...
"C:\Users\Logik\AppData\Local\Python\bin\python.exe" -m pip install openpyxl

echo.
echo Если сверху написано "Successfully installed" или "Requirement already satisfied", значит все ОК.
pause