# Backup, restore, and moving to another laptop

Backups are **manual only** — there is no scheduled automatic backup.

## What a backup contains

- The full PostgreSQL database (`pg_dump --format=custom`)
- `models/` — every model artifact plus the registry's on-disk state
- `artifacts/` — backtest results, reports, metrics
- `config/` — strategy and risk configuration files

A backup never relies on Docker layer state.

## Commands

```bash
make backup                     # or: scripts/backup.ps1
make list-backups
make restore NAME=backup-20260824T120000Z
make export  NAME=backup-20260824T120000Z     # single .tar.gz for transfer
make import  ARCHIVE=path/to/backup.tar.gz
```

Windows: `scripts/backup.ps1`, `scripts/restore.ps1 -Name <name>`.

## Moving to a new laptop

```
OLD LAPTOP
  make backup
  make export NAME=<name>
  copy the .tar.gz to external storage

NEW LAPTOP
  install Docker Desktop
  copy the project directory
  make import ARCHIVE=<name>.tar.gz
  make restore NAME=<name>
  cp .env.example .env   # re-enter your Binance keys; they are never backed up
  docker compose up -d
```

No retraining is required purely because the machine changed.

## Partial restore is detected, not ignored

If the database restores but `models/` does not, the model registry will
reference artifacts that are not on disk. At startup the platform:

1. Verifies every registered artifact exists and matches its recorded checksum.
2. Refuses to keep a `PRODUCTION` model whose artifact is unusable — it is
   demoted to `REJECTED`, with the reason recorded in its registry row.
3. Reports the problem through `GET /api/v1/system/health` (`model_registry`
   becomes `ERROR`) and on the System page.

It never crashes, and it never trades on a model it could not load.

## Verifying a migration

```bash
curl http://localhost:8000/api/v1/system/health
curl http://localhost:8000/api/v1/system/state     # model_registry_ok
curl http://localhost:8000/api/v1/system/version   # schema_revision
```
