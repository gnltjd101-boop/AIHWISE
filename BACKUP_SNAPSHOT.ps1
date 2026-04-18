param(
    [string]$Label = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$safeLabel = ($Label -replace '[^0-9A-Za-z_-]', '-').Trim('-')
if ([string]::IsNullOrWhiteSpace($safeLabel)) {
    $safeLabel = "manual"
}

$backupDir = Join-Path $root "agent_backups"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

$staging = Join-Path $backupDir "snapshot_$timestamp"
New-Item -ItemType Directory -Path $staging -Force | Out-Null

$includePaths = @(
    "agent_chat_server.py",
    "OPEN_AGENT_CHAT.bat",
    "OPEN_ME_COMMAND.txt",
    "README.md",
    "RUN_REGRESSION_SUITE.py",
    "RUN_REGRESSION_SUITE.bat",
    "AUTO_GIT_SYNC.ps1",
    "AUTO_GIT_SYNC.bat",
    "BACKUP_SNAPSHOT.ps1",
    "BACKUP_SNAPSHOT.bat",
    "agent_chat_history.jsonl",
    "agent_chat_meta.json",
    "agent_jobs.jsonl",
    "agent_job_state.json",
    "agent_active_project.json",
    "agent_projects",
    "agent_system"
)

foreach ($relative in $includePaths) {
    $source = Join-Path $root $relative
    if (-not (Test-Path $source)) {
        continue
    }
    $destination = Join-Path $staging $relative
    $parent = Split-Path -Parent $destination
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    if ((Get-Item $source) -is [System.IO.DirectoryInfo]) {
        Copy-Item -LiteralPath $source -Destination $destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

$archiveName = "AI_AGENT_SNAPSHOT_${timestamp}_${safeLabel}.zip"
$archivePath = Join-Path $backupDir $archiveName
if (Test-Path $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $archivePath -CompressionLevel Optimal
Remove-Item -LiteralPath $staging -Recurse -Force

[pscustomobject]@{
    backup_path = $archivePath
    label = $safeLabel
    created_at = $timestamp
} | ConvertTo-Json -Depth 4
