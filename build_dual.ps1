# build_dual.ps1
# Terminate existing apps
Write-Host "[1/3] Terminating existing instances..." -ForegroundColor Cyan
Stop-Process -Name "NeoSSHWinManager" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Clean build folders (keep NeoSSHWinManager.spec - it's the tracked build config)
Write-Host "[2/3] Cleaning build artifacts..." -ForegroundColor Cyan
Remove-Item -Path build, dist -Recurse -Force -ErrorAction SilentlyContinue

# Build GUI EXE from the tracked spec (controls hiddenimports/excludes/datas trimming)
Write-Host "[3/3] Building NeoSSHWinManager.exe (GUI)..." -ForegroundColor Cyan
$pyinstaller = if (Test-Path ".venv/Scripts/pyinstaller.exe") { ".venv/Scripts/pyinstaller.exe" } else { "pyinstaller" }
& $pyinstaller --noconfirm NeoSSHWinManager.spec

Write-Host "Done! EXE is in the dist folder." -ForegroundColor Green
