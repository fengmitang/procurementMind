[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeEnvFile = Join-Path $ProjectRoot ".env.docker"
$PidFile = Join-Path $ProjectRoot ".tmp\dev\processes.json"

function Stop-ManagedProcess {
    param([string]$Name, [object]$Entry)

    if ($null -eq $Entry) {
        Write-Host "$Name was not started by start_dev.ps1; no local process will be stopped."
        return
    }
    if ($Entry.managed -ne $true) {
        Write-Host "$Name was reused, not started by start_dev.ps1; PID $($Entry.pid) will not be stopped."
        return
    }
    try {
        $pidValue = [int]$Entry.pid
        $process = Get-Process -Id $pidValue -ErrorAction Stop
        $actualStart = $process.StartTime.ToUniversalTime().ToString("o")
        if ($actualStart -ne [string]$Entry.started_at_utc) {
            Write-Warning "$Name PID record is stale; PID $pidValue will not be stopped."
            return
        }

        Write-Host "Stopping managed $Name process tree (PID $pidValue)..." -ForegroundColor Cyan
        & taskkill.exe /PID $pidValue /T /F 2>$null | Out-Null
        if ($LASTEXITCODE -notin @(0, 128)) {
            throw "Could not stop $Name process tree (PID $pidValue)."
        }
        Write-Host "$Name stopped." -ForegroundColor Green
    }
    catch [Microsoft.PowerShell.Commands.ProcessCommandException] {
        Write-Host "$Name is no longer running."
    }
}

if (Test-Path -LiteralPath $PidFile) {
    try {
        $state = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Stop-ManagedProcess -Name "frontend" -Entry $state.frontend
        Stop-ManagedProcess -Name "agent" -Entry $state.agent
        Stop-ManagedProcess -Name "backend" -Entry $state.backend
        Remove-Item -LiteralPath $PidFile -Force
    }
    catch {
        Write-Error "Could not safely process $PidFile : $($_.Exception.Message)"
        exit 1
    }
}
else {
    Write-Host "No managed process file found; no Python or Node process will be stopped."
}

if (-not (Test-Path -LiteralPath $ComposeEnvFile)) {
    throw ".env.docker was not found: $ComposeEnvFile"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker was not found."
}

Push-Location $ProjectRoot
try {
    Write-Host "Stopping MySQL, Redis, and Qdrant containers..." -ForegroundColor Cyan
    & docker compose --env-file $ComposeEnvFile stop mysql redis qdrant
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose stop failed for mysql, redis, or qdrant."
    }
    Write-Host "Infrastructure stopped. Docker volumes were preserved." -ForegroundColor Green
}
finally {
    Pop-Location
}
