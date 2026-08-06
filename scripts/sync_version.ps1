# sync_version.ps1
# Single source of truth for the app version is src\version.txt.
# This script rewrites file_version_info.txt (the PyInstaller version resource
# used by both .spec files) so the built EXEs always carry that version.
#
# Called automatically by build_dual.ps1; can also be run standalone after
# bumping src\version.txt.

param(
    [switch]$Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$versionFile = Join-Path $repoRoot 'src\version.txt'
$infoFile = Join-Path $repoRoot 'file_version_info.txt'

if (-not (Test-Path $versionFile)) {
    throw "src\version.txt not found at $versionFile"
}

$version = (Get-Content $versionFile -Raw -Encoding UTF8).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "src\version.txt must contain a version like 1.5.4, but contains '$version'."
}

$parts = $version.Split('.')
$tuple = "({0}, {1}, {2}, 0)" -f $parts[0], $parts[1], $parts[2]

$content = Get-Content $infoFile -Raw -Encoding UTF8
$updated = $content
$updated = [regex]::Replace($updated, 'filevers=\([^)]*\)', "filevers=$tuple")
$updated = [regex]::Replace($updated, 'prodvers=\([^)]*\)', "prodvers=$tuple")
$updated = [regex]::Replace($updated, "(StringStruct\(u'FileVersion', u')[^']*(')", "`${1}$version`${2}")
$updated = [regex]::Replace($updated, "(StringStruct\(u'ProductVersion', u')[^']*(')", "`${1}$version`${2}")

if ($updated -eq $content) {
    Write-Host "[version] file_version_info.txt already matches src\version.txt ($version)." -ForegroundColor DarkGray
    return
}

if ($Check) {
    throw "file_version_info.txt is out of sync with src\version.txt ($version). Run scripts\sync_version.ps1."
}

# UTF-8 without BOM - PyInstaller eval()s this file and chokes on a BOM.
[System.IO.File]::WriteAllText($infoFile, $updated, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[version] file_version_info.txt updated to $version." -ForegroundColor Green
