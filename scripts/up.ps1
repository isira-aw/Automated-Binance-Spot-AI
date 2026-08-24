# Start the full stack (Windows equivalent of `make up`).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose up -d
