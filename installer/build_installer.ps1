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

# Drop setups of older versions, so dist_installer\ only ever holds the current
# one (the release workflow picks the first *.exe it finds there).
$outDir = Join-Path $repoRoot 'dist_installer'
if (Test-Path $outDir) {
    Get-ChildItem (Join-Path $outDir 'NeoSSHWinManager-Setup-*.exe') -ErrorAction SilentlyContinue |
        ForEach-Object {
            Write-Host ("      removing stale installer {0}" -f $_.Name) -ForegroundColor DarkGray
            Remove-Item $_.FullName -Force
        }
}

& $iscc "$PSScriptRoot\NeoSSHWinManager.iss"

# The version in the installer name comes from src\version.txt (see the .iss).
$version = (Get-Content (Join-Path $repoRoot 'src\version.txt') -Raw -Encoding UTF8).Trim()
$setup = Join-Path $repoRoot "dist_installer\NeoSSHWinManager-Setup-$version.exe"
if (-not (Test-Path $setup)) {
    throw "Expected installer '$setup' was not produced."
}

Write-Host "Done! $setup" -ForegroundColor Green
