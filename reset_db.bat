@echo off
:: Database reset script for UIN Indexer

echo.
echo      UIN INDEXER DATABASE RESET
echo.
echo This will delete the database file:
echo uin_index.db
echo.
echo Re-indexing will be required after reset.
echo.
set /p CONFIRM=Are you sure? Type YES to confirm: 

if /i "%CONFIRM%" NEQ "YES" (
    echo Cancelled. Database remains untouched.
    goto :end
)

if exist uin_index.db (
    echo Deleting database...
    del uin_index.db
    if %errorlevel% equ 0 (
        echo [OK] Database deleted successfully.
        echo      Run run_index_uin.bat to create a new index.
    ) else (
        echo [ERROR] Failed to delete database file.
        echo          The file may be in use. Close any programs using it and try again.
    )
) else (
    echo Database file not found. Nothing to delete.
)

:end
echo.
pause
