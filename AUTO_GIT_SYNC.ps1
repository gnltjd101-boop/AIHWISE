param(
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Set-Location $repoRoot

Write-Host "[1/5] Checking git status..." -ForegroundColor Cyan
git status --short --branch

if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = Read-Host "Enter commit message"
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    Write-Host "Commit message is empty. Stop." -ForegroundColor Yellow
    exit 1
}

Write-Host "[2/5] Staging changes..." -ForegroundColor Cyan
git add .

git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "No staged changes." -ForegroundColor Yellow
    exit 0
}

Write-Host "[3/5] Creating commit..." -ForegroundColor Cyan
git commit -m $Message

Write-Host "[4/5] Pushing to origin..." -ForegroundColor Cyan
git push

Write-Host "[5/5] Done" -ForegroundColor Green
git status --short --branch
