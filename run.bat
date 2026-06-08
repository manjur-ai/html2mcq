@echo off
python html2mcq_web.py
if errorlevel 1 (
    echo.
    echo Failed to start. Make sure html2mcq is installed:
    echo pip install html2mcq
    pause
)
