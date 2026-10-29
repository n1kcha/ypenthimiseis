@echo off
cd /d "%~dp0"
set TARGET=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ypenthimiseis-katastimaton.bat
> "%TARGET%" echo @echo off
>> "%TARGET%" echo cd /d "%~dp0"
>> "%TARGET%" echo start "" pythonw app.py
echo Προστεθηκε στην εκκινηση των Windows:
echo %TARGET%
pause
