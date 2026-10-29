# Builds Ypenthimiseis-Setup.exe on Windows (same steps as GitHub Actions).
# Needs: Python 3.12 and Inno Setup 6 (https://jrsoftware.org/isdl.php).
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1 [-Version 1.0.0]
param(
    [string]$Version = "1.0.0",
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

python installer\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "icon failed" }

python -m PyInstaller --noconfirm --clean --windowed `
    --name Ypenthimiseis `
    --icon installer\icon.ico `
    --add-data "installer\icon.ico;." `
    --add-data "installer\icon-png;icon-png" `
    --collect-data tzdata `
    --collect-all recurring_ical_events `
    --collect-all icalendar `
    --collect-all x_wr_timezone `
    --hidden-import pystray._win32 `
    --hidden-import PIL.ImageTk `
    --hidden-import PIL._tkinter_finder `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
if (-not (Test-Path "dist\Ypenthimiseis\Ypenthimiseis.exe")) { throw "exe missing" }

if ($SkipInstaller) { return }

$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) { throw "ISCC.exe (Inno Setup 6) not found" }
& $iscc "/DMyAppVersion=$Version" installer\Ypenthimiseis.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }
Get-Item installer\Output\Ypenthimiseis-Setup.exe
