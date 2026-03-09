@echo off
chcp 65001 >nul
echo ============================================
echo      СБРОС БАЗЫ ДАННЫХ УИН-ИНДЕКСАТОРА
echo ============================================
echo.
echo Это удалит файл базы данных:
echo   INDEX_UIN\uin_index.db
echo.
echo После сброса потребуется повторное индексирование.
echo.
set /p CONFIRM=Вы уверены? Введите ДА для подтверждения: 

if /i "%CONFIRM%" NEQ "ДА" (
    echo.
    echo Отменено. База данных не тронута.
    pause
    exit /b 0
)

echo.
echo Удаляю базу данных...

del /f /q "INDEX_UIN\uin_index.db"     2>nul
del /f /q "INDEX_UIN\uin_index.db-wal" 2>nul
del /f /q "INDEX_UIN\uin_index.db-shm" 2>nul

if not exist "INDEX_UIN\uin_index.db" (
    echo.
    echo [OK] База данных успешно удалена.
    echo      Запустите run_index_uin.bat для создания нового индекса.
) else (
    echo.
    echo [ОШИБКА] Не удалось удалить файл базы данных.
    echo          Возможно, программа ещё запущена. Закройте её и повторите.
)

echo.
pause
