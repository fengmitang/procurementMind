param(
    [ValidateSet("up", "down", "status", "logs", "config")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    switch ($Action) {
        "up" { docker compose --env-file .env.docker up -d }
        "down" { docker compose --env-file .env.docker down }
        "status" { docker compose --env-file .env.docker ps }
        "logs" { docker compose --env-file .env.docker logs --tail 100 }
        "config" { docker compose --env-file .env.docker config }
    }
}
finally {
    Pop-Location
}
