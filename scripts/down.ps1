# Stop the stack.  Persistent data under data/, models/, artifacts/, logs/ and
# backups/ is never removed by this.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose down
