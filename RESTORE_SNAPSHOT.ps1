param(
    [Parameter(Mandatory = $true)]
    [string]$ArchivePath
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$resolvedArchive = Resolve-Path -LiteralPath $ArchivePath
$restoreRoot = Join-Path $root "agent_restore_tmp"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$restoreDir = Join-Path $restoreRoot ("restore_" + $timestamp)

if (Test-Path $restoreDir) {
    Remove-Item -LiteralPath $restoreDir -Recurse -Force
}
New-Item -ItemType Directory -Path $restoreDir -Force | Out-Null

Expand-Archive -LiteralPath $resolvedArchive -DestinationPath $restoreDir -Force

$topLevelItems = Get-ChildItem -LiteralPath $restoreDir
foreach ($item in $topLevelItems) {
    $destination = Join-Path $root $item.Name
    if ($item.PSIsContainer) {
        if (Test-Path $destination) {
            Remove-Item -LiteralPath $destination -Recurse -Force
        }
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Recurse -Force
    } else {
        Copy-Item -LiteralPath $item.FullName -Destination $destination -Force
    }
}

[pscustomobject]@{
    restored_from = $resolvedArchive.Path
    restored_to = $root
    restored_at = $timestamp
} | ConvertTo-Json -Depth 4
