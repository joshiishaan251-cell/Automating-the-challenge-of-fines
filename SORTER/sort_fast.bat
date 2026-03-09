@echo off
:: 1. Go to script folder (so it can see config.yaml)
cd /d "%~dp0"

echo.
echo ==================================================
echo   LAUNCHING UNIVERSAL SORTER (FAST MODE)
echo ==================================================
echo.

:: 2. Set dry_run to false in config (optional, better to use args if script supports)
:: For now, we just run the script. It will use settings from config.yaml.

:: 3. Run script
python universal_sorter.py

echo.
echo ==================================================
echo   PROCESS COMPLETED
echo ==================================================
echo.
pause