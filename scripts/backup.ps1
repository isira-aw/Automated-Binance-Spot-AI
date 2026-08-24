# Create a manual backup (database + models + artifacts + config).
param([string]$Name)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($Name) { python scripts/manage.py backup --name $Name }
else { python scripts/manage.py backup }
