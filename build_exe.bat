@echo off
setlocal enabledelayedexpansion
python -m PyInstaller --onefile --windowed --name MyntraTrackerPro --add-data "data\products.json;data" app.py
if %ERRORLEVEL% neq 0 (
    echo Build failed.
    exit /b %ERRORLEVEL%
)
echo Build complete. Executable available in dist\MyntraTrackerPro.exe
endlocal
