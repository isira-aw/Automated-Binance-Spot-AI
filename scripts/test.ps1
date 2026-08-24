# Run backend and frontend test suites.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Push-Location (Join-Path $root "backend"); python -m pytest; Pop-Location
Push-Location (Join-Path $root "frontend"); npm run test; Pop-Location
