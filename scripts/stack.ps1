[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $ProjectRoot
try {
    switch ($Action) {
        "start" {
            docker compose up -d --build --wait
        }
        "stop" {
            docker compose down
        }
        "restart" {
            docker compose restart
            if ($LASTEXITCODE -eq 0) {
                docker compose up -d --wait
            }
        }
        "status" {
            docker compose ps
        }
        "logs" {
            docker compose logs --follow
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "AX Sentinel stack command failed. Make sure Docker Desktop is running."
    }
}
finally {
    Pop-Location
}
