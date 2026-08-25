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

### When the stack is down: `--direct`

The commands above reach PostgreSQL through `docker compose exec`, which
needs the `postgres` container to be running. The moment you most need a
restore is often the moment it is not. Both `backup` and `restore` accept
`--direct`, which uses your local `pg_dump`/`pg_restore` against
`POSTGRES_HOST`/`POSTGRES_PORT` instead:

```bash
python scripts/manage.py backup  --name pre-incident --direct
python scripts/manage.py restore --name pre-incident --yes --direct
```

`MANAGE_DB_MODE=direct` sets the same thing for a whole shell session.

Your local client must be at least the server's major version — a PG 15
`pg_dump` cannot dump a PG 16 server. It says so plainly if that is the
case, and the error is passed straight through rather than swallowed.
Prefer the default docker mode when the stack is up, since the container's
client always matches its own server.

## Safety rules the tooling enforces

These are guards, not conventions — they hold even if you are in a hurry:

- **A failed backup leaves nothing behind.** If `pg_dump` fails partway, the
  partial directory is deleted. A half-written backup that `list-backups`
  shows as real is worse than no backup, because you find out during an
  incident.
- **`MANIFEST.txt` is written last, and its absence blocks a restore.** It is
  the completeness marker: a backup missing it never finished, and restoring
  a truncated dump over a working database is refused rather than attempted.
- **A restore never runs without `--yes`.** It overwrites the database and the
  `models/`, `artifacts/` and `config/` directories.

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

## Incident runbook: restoring after data loss

**Before you restore anything, back up the current broken state.** A restore
is destructive, and the damaged database is often the only copy of whatever
happened between the last good backup and now.

```bash
python scripts/manage.py backup --name incident-$(date -u +%Y%m%dT%H%M%SZ) --direct
```

Then:

1. **Stop the stack** so nothing writes during the restore, and so the
   scheduler cannot act on half-restored state:
   `docker compose down` (or stop the backend process).
2. **Pick a backup**: `python scripts/manage.py list-backups`. Prefer the
   most recent one whose `created_at` predates the problem. A backup with no
   `MANIFEST.txt` will be refused — that is intentional, it never finished.
3. **Restore**: `python scripts/manage.py restore --name <name> --yes`
   (add `--direct` if the stack is down, which after step 1 it is).
4. **Bring the stack up** and check health before trusting anything:
   ```bash
   docker compose up -d
   curl http://localhost:8000/api/v1/system/health
   ```
   `model_registry` must be `ONLINE`. If it is `ERROR`, the database came
   back but the model artifacts did not — see "Partial restore" above.
5. **Reconcile paper-trading state.** Positions open at backup time are open
   again after the restore, but the market has moved. Check
   `GET /api/v1/positions` and close anything whose stop or target the
   market passed while you were down — the scheduler evaluates against the
   *current* price, so it will not retroactively fire an exit that should
   have happened during the outage.

### What is deliberately not backed up

`.env` — it holds your Binance API keys. Backups are transferred and copied;
secrets are not (§60). After any restore on a new machine, re-create `.env`
from `.env.example` and re-enter the keys by hand.
