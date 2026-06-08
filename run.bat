@echo off
python html2mcq_web.py
if errorlevel 1 (
    echo.
    echo Failed to start. Make sure Flask is installed:
    echo pip install flask
    pause
)
