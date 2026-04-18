param(
    [string]$Action = "",
    [string]$Argument = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Script
    )

    Write-Host ""
    Write-Host ("== " + $Label + " ==") -ForegroundColor Cyan
    & $Script
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Show-Status {
    Invoke-Step -Label "Git Status" -Script {
        git -C $root status --short --branch
    }
    Invoke-Step -Label "Latest Job State" -Script {
        if (Test-Path (Join-Path $root "agent_job_state.json")) {
            python -c "import json, pathlib; p=pathlib.Path(r'$root')/'agent_job_state.json'; d=json.loads(p.read_text(encoding='utf-8')); print(json.dumps({k:d.get(k) for k in ['status','projectId','category','domainMode','updated_at']}, ensure_ascii=False, indent=2))"
        } else {
            Write-Host "agent_job_state.json not found" -ForegroundColor Yellow
        }
    }
}

function Run-Action {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [string]$Value = ""
    )

    switch ($Name.ToLowerInvariant()) {
        "start" {
            Invoke-Step -Label "Open Agent Chat" -Script {
                Start-Process -FilePath (Join-Path $root "OPEN_AGENT_CHAT.bat")
            }
        }
        "diagnostics" {
            Invoke-Step -Label "Generate Diagnostics" -Script {
                python (Join-Path $root "GENERATE_DIAGNOSTICS_REPORT.py")
            }
        }
        "regression" {
            Invoke-Step -Label "Run Regression Suite" -Script {
                python (Join-Path $root "RUN_REGRESSION_SUITE.py")
            }
        }
        "stress" {
            Invoke-Step -Label "Run Stress Check" -Script {
                python (Join-Path $root "RUN_STRESS_CHECK.py")
            }
        }
        "backup" {
            $label = if ([string]::IsNullOrWhiteSpace($Value)) { "manual" } else { $Value }
            Invoke-Step -Label "Create Backup Snapshot" -Script {
                powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "BACKUP_SNAPSHOT.ps1") $label
            }
        }
        "restore" {
            if ([string]::IsNullOrWhiteSpace($Value)) {
                throw "restore action requires a snapshot zip path"
            }
            Invoke-Step -Label "Restore Snapshot" -Script {
                powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "RESTORE_SNAPSHOT.ps1") $Value
            }
        }
        "git-sync" {
            $message = if ([string]::IsNullOrWhiteSpace($Value)) { "ops console sync" } else { $Value }
            Invoke-Step -Label "Git Sync" -Script {
                powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $root "AUTO_GIT_SYNC.ps1") $message
            }
        }
        "status" {
            Show-Status
        }
        default {
            throw "Unknown action: $Name"
        }
    }
}

function Show-Menu {
    Write-Host ""
    Write-Host "AI Agent Operations Console" -ForegroundColor Green
    Write-Host "1. Status"
    Write-Host "2. Start Chat Server"
    Write-Host "3. Diagnostics Report"
    Write-Host "4. Regression Suite"
    Write-Host "5. Stress Check"
    Write-Host "6. Backup Snapshot"
    Write-Host "7. Restore Snapshot"
    Write-Host "8. Git Sync"
    Write-Host "9. Exit"
    Write-Host ""
    $choice = Read-Host "Select"

    switch ($choice) {
        "1" { Run-Action -Name "status" }
        "2" { Run-Action -Name "start" }
        "3" { Run-Action -Name "diagnostics" }
        "4" { Run-Action -Name "regression" }
        "5" { Run-Action -Name "stress" }
        "6" {
            $label = Read-Host "Backup label"
            Run-Action -Name "backup" -Value $label
        }
        "7" {
            $path = Read-Host "Snapshot zip path"
            Run-Action -Name "restore" -Value $path
        }
        "8" {
            $message = Read-Host "Commit message"
            Run-Action -Name "git-sync" -Value $message
        }
        "9" { return }
        default { throw "Unknown menu selection: $choice" }
    }
}

if ([string]::IsNullOrWhiteSpace($Action)) {
    Show-Menu
} else {
    Run-Action -Name $Action -Value $Argument
}
