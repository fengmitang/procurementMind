[CmdletBinding()]
param(
    [ValidateRange(30, 600)]
    [int]$InfrastructureWaitTimeoutSeconds = 180,

    [ValidateRange(30, 600)]
    [int]$ApplicationWaitTimeoutSeconds = 300
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ComposeEnvFile = Join-Path $ProjectRoot ".env.docker"
$PythonExecutable = "F:\Anaconda\envs\purchasing-agent\python.exe"
$FrontendDirectory = Join-Path $ProjectRoot "frontend"
$RuntimeDirectory = Join-Path $ProjectRoot ".tmp\dev"
$LogDirectory = Join-Path $RuntimeDirectory "logs"
$PidFile = Join-Path $RuntimeDirectory "processes.json"
$StartedThisRun = [System.Collections.Generic.List[object]]::new()

function Test-TcpPort {
    param([string]$HostName, [int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return $task.Wait(1000) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Test-HttpEndpoint {
    param(
        [string]$Uri,
        [string]$ExpectedDataStatus = ""
    )

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            return $false
        }
        if ($ExpectedDataStatus) {
            $payload = $response.Content | ConvertFrom-Json
            return [string]$payload.data.status -eq $ExpectedDataStatus
        }
        return $true
    }
    catch {
        return $false
    }
}

function Wait-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Uri,
        [int]$TimeoutSeconds,
        [System.Diagnostics.Process]$Process,
        [string]$ErrorLog,
        [string]$ExpectedDataStatus = ""
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-HttpEndpoint -Uri $Uri -ExpectedDataStatus $ExpectedDataStatus) {
            Write-Host "$Name is ready: $Uri" -ForegroundColor Green
            return
        }
        if ($null -ne $Process) {
            $Process.Refresh()
            if ($Process.HasExited) {
                throw "$Name exited before becoming ready. See $ErrorLog"
            }
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become ready within ${TimeoutSeconds}s. See $ErrorLog"
}

function Get-ContainerHealth {
    param([string]$ContainerName)

    $result = & docker inspect `
        --format "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" `
        $ContainerName 2>$null
    if ($LASTEXITCODE -ne 0) {
        return "missing"
    }
    return ([string]$result).Trim()
}

function Wait-Infrastructure {
    $containers = [ordered]@{
        mysql  = "procurement-mind-mysql"
        redis  = "procurement-mind-redis"
        qdrant = "procurement-mind-qdrant"
    }
    $deadline = [DateTime]::UtcNow.AddSeconds($InfrastructureWaitTimeoutSeconds)

    while ([DateTime]::UtcNow -lt $deadline) {
        $pending = @()
        $failed = @()
        foreach ($item in $containers.GetEnumerator()) {
            $health = Get-ContainerHealth -ContainerName $item.Value
            if ($health -eq "running|healthy") {
                continue
            }
            if ($health -match "^(exited|dead)\|" -or $health -match "\|unhealthy$") {
                $failed += "$($item.Key)=$health"
            }
            else {
                $pending += "$($item.Key)=$health"
            }
        }
        if ($failed.Count -gt 0) {
            throw "Infrastructure startup failed: $($failed -join ', ')"
        }
        if ($pending.Count -eq 0) {
            Write-Host "MySQL, Redis, and Qdrant are healthy." -ForegroundColor Green
            return
        }
        Write-Host "Waiting for infrastructure: $($pending -join ', ')"
        Start-Sleep -Seconds 3
    }
    throw "Infrastructure health check timed out after ${InfrastructureWaitTimeoutSeconds}s."
}

function Read-ProcessState {
    if (-not (Test-Path -LiteralPath $PidFile)) {
        return [ordered]@{ backend = $null; agent = $null; frontend = $null }
    }
    try {
        $saved = Get-Content -LiteralPath $PidFile -Raw -Encoding UTF8 | ConvertFrom-Json
        return [ordered]@{
            backend = $saved.backend
            agent = $saved.agent
            frontend = $saved.frontend
        }
    }
    catch {
        Write-Warning "Ignoring unreadable process state file: $PidFile"
        return [ordered]@{ backend = $null; agent = $null; frontend = $null }
    }
}

$ProcessState = Read-ProcessState

function Save-ProcessState {
    $ProcessState | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $PidFile -Encoding UTF8
}

function Get-VerifiedManagedProcess {
    param([string]$Name)

    $entry = $ProcessState[$Name]
    if ($null -eq $entry -or $entry.managed -ne $true) {
        return $null
    }
    try {
        $process = Get-Process -Id ([int]$entry.pid) -ErrorAction Stop
        $actualStart = $process.StartTime.ToUniversalTime().ToString("o")
        if ($actualStart -ne [string]$entry.started_at_utc) {
            return $null
        }
        return $process
    }
    catch {
        return $null
    }
}

function Start-ManagedService {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [int]$Port,
        [string]$HealthUri,
        [string]$ExpectedDataStatus = ""
    )

    $existing = Get-VerifiedManagedProcess -Name $Name
    if ($null -ne $existing) {
        Write-Host "$Name is already managed (PID $($existing.Id)); waiting for health."
        Wait-HttpEndpoint -Name $Name -Uri $HealthUri `
            -TimeoutSeconds $ApplicationWaitTimeoutSeconds -Process $existing `
            -ErrorLog ([string]$ProcessState[$Name].stderr_log) `
            -ExpectedDataStatus $ExpectedDataStatus
        return
    }

    if (Test-HttpEndpoint -Uri $HealthUri -ExpectedDataStatus $ExpectedDataStatus) {
        Write-Host "$Name is already available and will be reused (not managed by this script)."
        $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        $reusedPid = if ($null -ne $listener) { [int]$listener.OwningProcess } else { $null }
        $ProcessState[$Name] = [ordered]@{
            pid = $reusedPid
            managed = $false
            reused = $true
            health_uri = $HealthUri
        }
        Save-ProcessState
        return
    }
    if (Test-TcpPort -HostName "127.0.0.1" -Port $Port) {
        throw "$Name cannot start because port $Port is in use but $HealthUri is not healthy."
    }

    $stdoutLog = Join-Path $LogDirectory "$Name.out.log"
    $stderrLog = Join-Path $LogDirectory "$Name.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -WindowStyle Hidden `
        -PassThru

    $entry = [ordered]@{
        pid = $process.Id
        managed = $true
        reused = $false
        started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        stdout_log = $stdoutLog
        stderr_log = $stderrLog
        health_uri = $HealthUri
    }
    $ProcessState[$Name] = $entry
    Save-ProcessState
    $StartedThisRun.Add($entry) | Out-Null
    Write-Host "Starting $Name (PID $($process.Id)); logs: $stdoutLog, $stderrLog"
    Wait-HttpEndpoint -Name $Name -Uri $HealthUri `
        -TimeoutSeconds $ApplicationWaitTimeoutSeconds -Process $process `
        -ErrorLog $stderrLog -ExpectedDataStatus $ExpectedDataStatus
}

function Show-FailureLogs {
    foreach ($name in @("backend", "agent", "frontend")) {
        $entry = $ProcessState[$name]
        if ($null -eq $entry) {
            continue
        }
        $errorLog = [string]$entry.stderr_log
        if (Test-Path -LiteralPath $errorLog) {
            Write-Host "--- $name error log: $errorLog ---" -ForegroundColor Yellow
            Get-Content -LiteralPath $errorLog -Tail 30 -ErrorAction SilentlyContinue
        }
    }
}

function Stop-ProcessesStartedThisRun {
    foreach ($entry in $StartedThisRun) {
        try {
            $process = Get-Process -Id ([int]$entry.pid) -ErrorAction Stop
            if ($process.StartTime.ToUniversalTime().ToString("o") -eq [string]$entry.started_at_utc) {
                & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
            }
        }
        catch {
            # The process has already exited.
        }
    }
}

if (-not (Test-Path -LiteralPath $ComposeEnvFile)) {
    throw ".env.docker was not found: $ComposeEnvFile"
}
if (-not (Test-Path -LiteralPath $PythonExecutable)) {
    throw "Project Python was not found: $PythonExecutable"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker was not found. Start Docker Desktop first."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "npm.cmd was not found. Install Node.js first."
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendDirectory "node_modules\.bin\vite.cmd"))) {
    throw "Frontend dependencies are missing. Run npm.cmd install in frontend first."
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null

Push-Location $ProjectRoot
try {
    Write-Host "Starting MySQL, Redis, and Qdrant..." -ForegroundColor Cyan
    & docker compose --env-file $ComposeEnvFile up -d mysql redis qdrant
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose failed while starting mysql, redis, or qdrant."
    }
    Wait-Infrastructure

    Write-Host "Applying database migrations with the purchasing-agent Conda environment..." -ForegroundColor Cyan
    & $PythonExecutable -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic migration failed with exit code $LASTEXITCODE."
    }
    Write-Host "Database migration completed." -ForegroundColor Green

    Start-ManagedService -Name "backend" -FilePath $PythonExecutable `
        -Arguments @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload") `
        -WorkingDirectory $ProjectRoot -Port 8000 -HealthUri "http://127.0.0.1:8000/ready" `
        -ExpectedDataStatus "ready"

    Start-ManagedService -Name "agent" -FilePath $PythonExecutable `
        -Arguments @("-m", "uvicorn", "agent_app.main:app", "--host", "127.0.0.1", "--port", "8100", "--reload") `
        -WorkingDirectory $ProjectRoot -Port 8100 -HealthUri "http://127.0.0.1:8100/health" `
        -ExpectedDataStatus "ok"

    Start-ManagedService -Name "frontend" -FilePath "npm.cmd" `
        -Arguments @("run", "dev") -WorkingDirectory $FrontendDirectory `
        -Port 5173 -HealthUri "http://127.0.0.1:5173/demo/"

    Write-Host ""
    Write-Host "Frontend http://127.0.0.1:5173/demo/"
    Write-Host "Backend http://127.0.0.1:8000"
    Write-Host "Agent http://127.0.0.1:8100"
    Write-Host "Logs $LogDirectory"
}
catch {
    Write-Host "Development startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Show-FailureLogs
    Stop-ProcessesStartedThisRun
    exit 1
}
finally {
    Pop-Location
}
