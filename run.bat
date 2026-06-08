@echo off
start http://localhost:5000
python app.py
if errorlevel 1 (
    echo.
    echo Make sure html2mcq is installed: pip install html2mcq
    pause
)
