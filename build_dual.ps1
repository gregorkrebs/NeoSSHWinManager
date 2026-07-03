# build_dual.ps1
# Terminate existing apps
Write-Host "[1/4] Terminating existing instances..." -ForegroundColor Cyan
Stop-Process -Name "NeoSSHWinManager" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "NeoSSHWinManager-cli" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Clean build folders (aggressive)
Write-Host "[2/4] Cleaning build artifacts..." -ForegroundColor Cyan
Remove-Item -Path build, dist, *.spec -Recurse -Force -ErrorAction SilentlyContinue

# Build second GUI EXE
Write-Host "[3/4] Building NeoSSHWinManager.exe (GUI)..." -ForegroundColor Cyan
& .venv/Scripts/pyinstaller.exe --noconfirm --onefile --windowed --name "NeoSSHWinManager" --icon "assets/app_icon.ico" --add-data "src;src" --add-data "assets;assets" --version-file "file_version_info.txt" --hidden-import "PyQt6.sip" --hidden-import "win32api" --hidden-import "win32con" --hidden-import "winreg" --hidden-import "keyring" --hidden-import "keyring.backends.Windows" --noupx main.py

# # Build CLI companion EXE (console subsystem, so stdin/stdout stay in the caller's terminal)
# Write-Host "[4/4] Building NeoSSHWinManager-cli.exe (console)..." -ForegroundColor Cyan
# & .venv/Scripts/pyinstaller.exe --noconfirm --onefile --console --name "NeoSSHWinManager-cli" --icon "assets/app_icon.ico" --add-data "src;src" --version-file "file_version_info.txt" cli_main.py

Write-Host "Done! EXEs are in the dist folder." -ForegroundColor Green
