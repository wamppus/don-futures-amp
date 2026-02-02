@echo off
echo DON Futures TopStep - Shadow Mode
echo ==================================
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

echo Activating environment...
call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -r requirements.txt -q

echo.
echo Enter your TopStep credentials:
set /p PROJECTX_USERNAME="Username: "
set /p PROJECTX_API_KEY="API Key: "

echo.
echo Starting shadow trading...
python run_topstep.py --mode shadow

pause
