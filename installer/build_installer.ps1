# build_installer.ps1
# Builds the GUI + CLI executables (build_dual.ps1) and then compiles the
# Windows installer (NeoSSHWinManager.iss) from them with Inno Setup 6.
#
# Requires Inno Setup 6 (ISCC.exe) installed, default path assumed below.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "[1/2] Building GUI + CLI executables..." -ForegroundColor Cyan
Push-Location $repoRoot
try {
    & .\build_dual.ps1
} finally {
    Pop-Location
}

$iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $iscc = "C:\Program Files\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $iscc)) {
    throw "Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isinfo.php"
}

Write-Host "[2/2] Compiling installer..." -ForegroundColor Cyan
& $iscc "$PSScriptRoot\NeoSSHWinManager.iss"

Write-Host "Done! Setup.exe is in dist_installer\." -ForegroundColor Green
