# Apply database migrations.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/manage.py migrate
