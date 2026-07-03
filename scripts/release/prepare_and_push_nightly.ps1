param(
    [string]$Remote = 'origin',
    [string]$Branch = 'nightly'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host "[push-dev] $Message" -ForegroundColor Cyan
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repoRoot

if (-not (Test-Path '.git')) {
    throw 'This script must be run inside the git repository root.'
}

Write-Step 'Refreshing the local view of the remote branch.'
git fetch $Remote $Branch

$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Step ("Current branch: {0}" -f $currentBranch)

Write-Step 'Current repository status:'
git status --short

git diff --quiet
$workingTreeClean = ($LASTEXITCODE -eq 0)
git diff --cached --quiet
$indexClean = ($LASTEXITCODE -eq 0)

if (-not $workingTreeClean -or -not $indexClean) {
    throw 'The working tree is not clean. Review and finish your commits before pushing.'
}

$aheadBehind = (git rev-list --left-right --count ("{0}/{1}...HEAD" -f $Remote, $Branch)).Trim()
Write-Step ("Ahead/behind relative to {0}/{1}: {2}" -f $Remote, $Branch, $aheadBehind)

if ($currentBranch -ne $Branch) {
    Write-Warning ("You are not on '{0}'. This script is configured to push to '{0}'." -f $Branch)
}

$answer = Read-Host 'willst du jetzt alles nach github ins nightly pushen'
if ($answer -notmatch '^(?i)(j|ja|y|yes)$') {
    Write-Step 'Push aborted by user.'
    return
}

Write-Step ("Pushing HEAD to {0}/{1}." -f $Remote, $Branch)
git push $Remote HEAD:$Branch

Write-Step 'Push completed.'