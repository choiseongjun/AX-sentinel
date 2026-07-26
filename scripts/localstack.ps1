[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "reset")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $ProjectRoot
try {
    switch ($Action) {
        "start" {
            docker compose up -d --wait localstack
            if ($LASTEXITCODE -ne 0) {
                throw "LocalStack failed to start. Make sure Docker Desktop is running."
            }
            $Port = if ($env:LOCALSTACK_PORT) { $env:LOCALSTACK_PORT } else { "4566" }
            Write-Host "LocalStack is ready at http://localhost:$Port"
        }
        "stop" {
            docker compose down
        }
        "restart" {
            docker compose restart localstack
            if ($LASTEXITCODE -eq 0) {
                docker compose up -d --wait localstack
            }
        }
        "status" {
            docker compose ps
        }
        "logs" {
            docker compose logs --follow localstack
        }
        "reset" {
            Write-Warning "This removes all persisted LocalStack data."
            docker compose down --volumes
        }
    }

    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
