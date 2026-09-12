@echo off
chcp 65001 >nul
cd /d %~dp0
python -m pip install -r requirements.txt
start "" http://127.0.0.1:7860
python -m uvicorn server:app --host 127.0.0.1 --port 7860
pause
