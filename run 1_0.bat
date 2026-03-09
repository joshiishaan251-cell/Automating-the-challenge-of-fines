@echo off
chcp 65001 >nul
echo.
echo ==================================================
echo   ЗАПУСК МОДУЛЯ ОБРАБОТКИ ПОСТАНОВЛЕНИЙ (1_0)
echo ==================================================
echo.

:: Check for required python libraries
python -c "import fitz, PIL, pytesseract, pdf2image" 2>nul
if %errorlevel% neq 0 (
    echo [ИНФО] Установка необходимых библиотек...
    pip install pymupdf pillow pytesseract pdf2image pyyaml
)

echo Поиск активной папки и обработка 4-х сканов...
echo.

:: Run the script
python "1_0\process_resolutions.py"

echo.
echo ==================================================
echo   РАБОТА ЗАВЕРШЕНА
echo ==================================================
echo.
pause
