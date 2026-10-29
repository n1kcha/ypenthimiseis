@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo Αν λείπει η Python: https://www.python.org/downloads/
  echo Μετα την εγκατασταση τρεξε: python -m pip install -r requirements.txt
  pause
)
