# Start the stack with backend hot reload and the Vite dev server.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
