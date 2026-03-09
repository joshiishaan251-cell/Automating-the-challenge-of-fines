@echo off
chcp 65001 >nul
echo.
echo ==================================================
echo   LAUNCHING RESOLUTION PROCESSING MODULE (1_0)
echo ==================================================
echo.

:: Check for required python libraries
python -c "import fitz, PIL, pytesseract, pdf2image" 2>nul
if %errorlevel% neq 0 (
    echo [INFO] Installing required libraries...
    pip install pymupdf pillow pytesseract pdf2image pyyaml
)

echo Searching for active folder and processing 4 scans...
echo.

:: Run the script
python "1_0\process_resolutions.py"

echo.
echo ==================================================
echo   WORK COMPLETED
echo ==================================================
echo.
pause
