# Restore a backup.  Overwrites the database and models/, artifacts/, config/.
param([Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
python scripts/manage.py restore --name $Name --yes
