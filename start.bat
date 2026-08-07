@echo off
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
echo.
echo Portrait Lab starting (stopping old process on port 8765)...
echo Browser: http://127.0.0.1:8765
echo Export:  %cd%\pic
echo.
rem User start: open browser if no Lab was already on 8765
set PORTRAIT_LAB_OPEN_BROWSER=1
python server.py
pause
