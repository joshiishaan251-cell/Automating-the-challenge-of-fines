@echo off
:: 1. Go to folder
cd /d "%~dp0"

:: 2. Delete cache file (if it exists)
if exist archive_cache.json (
    echo Deleting old cache for full rescan...
    del archive_cache.json
)

:: 3. Run script (it will create a new cache)
echo --- STARTING FULL INDEXING ---
python universal_sorter.py

echo Indexing completed!
pause