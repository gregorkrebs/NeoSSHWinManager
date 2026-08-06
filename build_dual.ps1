# build_dual.ps1
# Sync the version resource with src\version.txt (the single source of truth)
Write-Host "[1/5] Syncing version from src\version.txt..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "scripts\sync_version.ps1")

# Terminate existing apps
Write-Host "[2/5] Terminating existing instances..." -ForegroundColor Cyan
Stop-Process -Name "NeoSSHWinManager" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "NeoSSHWinManager-cli" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Clean build folders (keep the .spec files - they're the tracked build config)
Write-Host "[3/5] Cleaning build artifacts..." -ForegroundColor Cyan
Remove-Item -Path build, dist -Recurse -Force -ErrorAction SilentlyContinue

$pyinstaller = if (Test-Path ".venv/Scripts/pyinstaller.exe") { ".venv/Scripts/pyinstaller.exe" } else { "pyinstaller" }

# Build the standalone GUI EXE from the tracked spec (controls hiddenimports/excludes/datas trimming)
Write-Host "[4/5] Building NeoSSHWinManager.exe (GUI, standalone onefile)..." -ForegroundColor Cyan
& $pyinstaller --noconfirm NeoSSHWinManager.spec

# Build the CLI companion EXE (console subsystem, so stdin/stdout stay in the
# caller's terminal) — talks to the running, logged-in GUI instance over the
# local IPC pipe to resolve --connect-cli access keys; see cli_main.py.
Write-Host "[5/5] Building NeoSSHWinManager-cli.exe (console)..." -ForegroundColor Cyan
& $pyinstaller --noconfirm NeoSSHWinManager-cli.spec

Write-Host "Done! Both EXEs are in the dist folder." -ForegroundColor Green
