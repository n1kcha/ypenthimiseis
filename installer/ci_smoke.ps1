# CI smoke tests on a real Windows runner (ASCII only on purpose).
#   pwsh installer\ci_smoke.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$exe = Join-Path $root "dist\Ypenthimiseis\Ypenthimiseis.exe"
$setup = Join-Path $root "installer\Output\Ypenthimiseis-Setup.exe"
$realLocal = $env:LOCALAPPDATA

function Stop-App { Get-Process Ypenthimiseis -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep 1 }
function Fail($m) { Write-Host "::error::$m"; Stop-App; exit 1 }
function Show-Windows {
    Get-Process Ypenthimiseis -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  pid $($_.Id) title='$($_.MainWindowTitle)'" }
}
function Check-NoCrashDialog {
    $bad = Get-Process Ypenthimiseis -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -match "exception|Error|error" }
    if ($bad) { Fail "exe shows an error dialog: $($bad.MainWindowTitle)" }
}

# ---- artwork bundled in the exe (tray icon PNGs + ico)
foreach ($f in "icon.ico", "icon-png\icon_16.png", "icon-png\icon_32.png", "icon-png\icon_64.png") {
    if (-not (Test-Path (Join-Path $root "dist\Ypenthimiseis\_internal\$f"))) { Fail "missing bundled $f" }
}
Write-Host "OK: icon files bundled"

# ---- local ICS server with an event happening now
$tmp = Join-Path $env:RUNNER_TEMP "smoke"
New-Item -ItemType Directory -Force $tmp | Out-Null
$now = (Get-Date).ToUniversalTime()
$fmt = "yyyyMMdd'T'HHmmss'Z'"
$ics = @(
  "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//smoke//EN",
  "BEGIN:VEVENT", "UID:smoke-1@test",
  "DTSTAMP:$($now.ToString($fmt))",
  "DTSTART:$($now.AddMinutes(-1).ToString($fmt))",
  "DTEND:$($now.AddMinutes(30).ToString($fmt))",
  "SUMMARY:[ola] Smoke test", "END:VEVENT", "END:VCALENDAR"
) -join "`r`n"
Set-Content -Path (Join-Path $tmp "test.ics") -Value $ics -Encoding ascii -NoNewline
$server = Start-Process python -ArgumentList "-m", "http.server", "8765", "--bind", "127.0.0.1", "--directory", $tmp -PassThru -WindowStyle Hidden
Start-Sleep 2
$cfgJson = '{"store_name":"Smoke","store_id":"smoke","ics_url":"http://127.0.0.1:8765/test.ics","ics_urls":[],"poll_seconds":30,"minutes_before":0,"show_missed_max_minutes":15,"sound":true,"sound_seconds":5}'

try {
    # ---- 1) frozen exe: fetch + popup; data must go to %LOCALAPPDATA%\Ypenthimiseis
    Write-Host "== 1) frozen exe with config"
    $la1 = Join-Path $tmp "la1"; $d1 = Join-Path $la1 "Ypenthimiseis"
    New-Item -ItemType Directory -Force $d1 | Out-Null
    Set-Content -Path (Join-Path $d1 "config.json") -Value $cfgJson -Encoding utf8
    $env:LOCALAPPDATA = $la1
    Start-Process $exe | Out-Null
    $ok = $false
    for ($i = 0; $i -lt 45; $i++) { if (Test-Path (Join-Path $d1 "chime.wav")) { $ok = $true; break }; Start-Sleep 1 }
    Show-Windows; Check-NoCrashDialog
    if (Test-Path (Join-Path $d1 "app.log")) { Get-Content (Join-Path $d1 "app.log") }
    if (-not $ok) { Fail "popup/sound did not start (no chime.wav in data dir)" }
    Start-Sleep 3
    $log1 = Join-Path $d1 "app.log"
    if ((Test-Path $log1) -and (Select-String -Path $log1 -Pattern "loop:" -Quiet)) { Get-Content $log1; Fail "popup raised an error (see app.log)" }
    if (-not ((Test-Path $log1) -and (Select-String -Path $log1 -Pattern "start \(pid" -Quiet))) { Fail "app.log missing or without start line" }
    if (Select-String -Path $log1 -Pattern "fatal exception|unhandled|tk callback" -Quiet) { Get-Content $log1; Fail "crash/unhandled error logged in app.log" }
    if (-not (Get-Process Ypenthimiseis -ErrorAction SilentlyContinue)) { Fail "exe exited" }
    Write-Host "OK: event fetched, popup + chime started, data in LOCALAPPDATA"
    Stop-App

    # ---- 2) first run without config: settings window instead of crash
    Write-Host "== 2) first run without config"
    $la2 = Join-Path $tmp "la2"
    New-Item -ItemType Directory -Force $la2 | Out-Null
    $env:LOCALAPPDATA = $la2
    Start-Process $exe | Out-Null
    Start-Sleep 10
    Show-Windows; Check-NoCrashDialog
    if (-not (Get-Process Ypenthimiseis -ErrorAction SilentlyContinue)) { Fail "exe exited on first run (settings window expected)" }
    if (Test-Path (Join-Path $la2 "Ypenthimiseis\config.json")) { Fail "config.json should not exist yet" }
    Write-Host "OK: first run stays open (settings window)"
    Stop-App

    # ---- 3) installer: silent install, upgrade, uninstall (real LOCALAPPDATA)
    $env:LOCALAPPDATA = $realLocal
    $inst = Join-Path $realLocal "Ypenthimiseis"
    New-Item -ItemType Directory -Force $inst | Out-Null
    Set-Content -Path (Join-Path $inst "config.json") -Value $cfgJson -Encoding utf8
    $hash = (Get-FileHash (Join-Path $inst "config.json")).Hash
    $run = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $unKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8C3B6F1E-5D0A-4C7B-9E2F-3A1D4B6C7E90}_is1"

    foreach ($round in 1, 2) {
        Write-Host "== 3.$round) silent install"
        # not -Wait: it would also wait for the app that setup launches (child process)
        $p = Start-Process $setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=$tmp\setup$round.log" -PassThru
        if (-not $p.WaitForExit(180000)) { Fail "setup timed out" }
        if ($p.ExitCode -ne 0) { Get-Content "$tmp\setup$round.log" -Tail 40; Fail "setup exit code $($p.ExitCode)" }
        if (-not (Test-Path (Join-Path $inst "Ypenthimiseis.exe"))) { Fail "exe not installed" }
        if (-not (Test-Path (Join-Path $inst "unins000.exe"))) { Fail "uninstaller missing" }
        $v = (Get-ItemProperty $run -Name Ypenthimiseis -ErrorAction SilentlyContinue).Ypenthimiseis
        if (-not $v) { Fail "Run key missing" }
        Write-Host "Run key: $v"
        if (-not (Test-Path $unKey)) { Fail "Uninstall entry missing in HKCU" }
        if ((Get-FileHash (Join-Path $inst "config.json")).Hash -ne $hash) { Fail "config.json was overwritten" }
        Start-Sleep 5
        $procs = @(Get-Process Ypenthimiseis -ErrorAction SilentlyContinue)
        Show-Windows; Check-NoCrashDialog
        if ($procs.Count -lt 1) { Fail "app not started after install" }
        Write-Host "OK: install round $round, processes: $($procs.Count)"
    }

    Write-Host "== 3.3) silent uninstall"
    # the uninstaller re-launches itself from %TEMP%, so poll until the exe is gone
    $u = Start-Process (Join-Path $inst "unins000.exe") -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -PassThru
    [void]$u.WaitForExit(120000)
    for ($i = 0; $i -lt 60; $i++) { if (-not (Test-Path (Join-Path $inst "unins000.exe"))) { break }; Start-Sleep 1 }
    Start-Sleep 3
    if (Get-Process Ypenthimiseis -ErrorAction SilentlyContinue) { Fail "app still running after uninstall" }
    if ((Get-ItemProperty $run -ErrorAction SilentlyContinue).Ypenthimiseis) { Fail "Run key not removed" }
    if (Test-Path (Join-Path $inst "Ypenthimiseis.exe")) { Fail "exe not removed" }
    if (Test-Path $unKey) { Fail "Uninstall entry not removed" }
    if (-not (Test-Path (Join-Path $inst "config.json"))) { Fail "silent uninstall should keep config.json" }
    Write-Host "OK: uninstall removed app, startup entry and Apps entry; kept config.json"
}
finally {
    $env:LOCALAPPDATA = $realLocal
    Stop-App
    if ($server) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
}
Write-Host "ALL SMOKE TESTS PASSED"
