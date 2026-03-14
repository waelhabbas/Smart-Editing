@echo off
title Smart Editing Server
cd /d "%~dp0"

echo Installing dependencies...
pip install -r backend/requirements.txt

echo.
echo Starting Smart Editing server on http://localhost:8000
echo.
python run.py

pause
