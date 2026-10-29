@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.

where python >nul 2>&1
if %errorlevel%==0 (
  python install.py
  goto end
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 install.py
  goto end
)

echo Den brethike Python sto PATH.
echo Egkatastase Python me "Add python.exe to PATH".
pause
goto :eof

:end
echo.
pause
