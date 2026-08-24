#!/usr/bin/env python3
"""Operational tooling: migrations, backup, restore, export, import (§49, §50).

Cross-platform by design — Windows is the primary development machine (§67), so
everything here is plain Python driving `docker compose`, with thin Makefile and
PowerShell wrappers.

Backups never rely on Docker layer state: the database is dumped with `pg_dump`
and the persistent directories are archived from the host filesystem.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = ROOT / "backups"

# Directories captured in a backup, alongside the database dump.
BACKED_UP_TREES = ("models", "artifacts", "config")
DB_DUMP_NAME = "database.dump"
MANIFEST_NAME = "MANIFEST.txt"


def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
    print(f"$ {' '.join(command)}", flush=True)
    return subprocess.run(command, check=True, cwd=ROOT, **kwargs)  # type: ignore[arg-type]


def compose(*args: str) -> list[str]:
    return ["docker", "compose", *args]


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_migrate(_: argparse.Namespace) -> int:
    """Apply Alembic migrations. The schema is never created implicitly (§3)."""
    run(compose("run", "--rm", "migrate"))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = args.name or f"backup-{stamp}"
    staging = BACKUP_DIR / name
    if staging.exists():
        print(f"Backup '{name}' already exists.", file=sys.stderr)
        return 1
    staging.mkdir(parents=True)

    print("Dumping PostgreSQL...")
    dump_path = staging / DB_DUMP_NAME
    with dump_path.open("wb") as handle:
        run(
            compose(
                "exec", "-T", "postgres",
                "pg_dump", "-U", env("POSTGRES_USER", "trader"),
                "-d", env("POSTGRES_DB", "binance_spot_ai"),
                "--format=custom", "--no-owner",
            ),
            stdout=handle,
        )

    for tree in BACKED_UP_TREES:
        source = ROOT / tree
        if not source.exists():
            continue
        print(f"Archiving {tree}/ ...")
        with tarfile.open(staging / f"{tree}.tar.gz", "w:gz") as archive:
            archive.add(source, arcname=tree)

    (staging / MANIFEST_NAME).write_text(
        "\n".join(
            [
                f"created_at: {datetime.now(tz=timezone.utc).isoformat()}",
                f"database: {env('POSTGRES_DB', 'binance_spot_ai')}",
                f"trees: {', '.join(BACKED_UP_TREES)}",
                "note: restore with `python scripts/manage.py restore --name "
                f"{name}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"\nBackup complete: {staging}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    staging = BACKUP_DIR / args.name
    if not staging.is_dir():
        print(f"No such backup: {staging}", file=sys.stderr)
        return 1

    dump_path = staging / DB_DUMP_NAME
    if not dump_path.is_file():
        print(f"Backup is missing {DB_DUMP_NAME}.", file=sys.stderr)
        return 1

    if not args.yes:
        print(
            "This overwrites the current database and the models/, artifacts/ and\n"
            "config/ directories. Re-run with --yes to proceed."
        )
        return 1

    print("Restoring PostgreSQL...")
    with dump_path.open("rb") as handle:
        run(
            compose(
                "exec", "-T", "postgres",
                "pg_restore", "-U", env("POSTGRES_USER", "trader"),
                "-d", env("POSTGRES_DB", "binance_spot_ai"),
                "--clean", "--if-exists", "--no-owner",
            ),
            stdin=handle,
        )

    for tree in BACKED_UP_TREES:
        archive_path = staging / f"{tree}.tar.gz"
        if not archive_path.is_file():
            print(f"! {tree}.tar.gz is absent from this backup; leaving {tree}/ as-is.")
            continue
        print(f"Restoring {tree}/ ...")
        target = ROOT / tree
        if target.exists():
            shutil.rmtree(target)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(ROOT, filter="data")

    print(
        "\nRestore complete. Restart the stack and check "
        "GET /api/v1/system/health — a restore that brought back the database "
        "but not the model artifacts is reported there as a model registry "
        "integrity problem."
    )
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    if not BACKUP_DIR.is_dir():
        print("No backups yet.")
        return 0
    entries = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir())
    if not entries:
        print("No backups yet.")
        return 0
    for entry in entries:
        manifest = entry / MANIFEST_NAME
        created = "unknown"
        if manifest.is_file():
            for line in manifest.read_text(encoding="utf-8").splitlines():
                if line.startswith("created_at:"):
                    created = line.split(":", 1)[1].strip()
        size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
        print(f"{entry.name}\t{created}\t{size / 1_048_576:.1f} MiB")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Bundle one backup into a single archive for transfer to another laptop."""
    staging = BACKUP_DIR / args.name
    if not staging.is_dir():
        print(f"No such backup: {staging}", file=sys.stderr)
        return 1
    destination = Path(args.output or (BACKUP_DIR / f"{args.name}.tar.gz")).resolve()
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(staging, arcname=args.name)
    print(f"Exported to {destination}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    source = Path(args.archive).resolve()
    if not source.is_file():
        print(f"No such archive: {source}", file=sys.stderr)
        return 1
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as archive:
        archive.extractall(BACKUP_DIR, filter="data")
    print(f"Imported into {BACKUP_DIR}. Restore it with `manage.py restore --name <name>`.")
    return 0


def cmd_verify(_: argparse.Namespace) -> int:
    """Check that the persistent directory skeleton exists."""
    missing = [
        str(path)
        for path in (
            ROOT / "data",
            ROOT / "models" / "production",
            ROOT / "artifacts",
            ROOT / "logs",
            ROOT / "backups",
        )
        if not path.exists()
    ]
    if missing:
        print("Missing persistent directories:\n  " + "\n  ".join(missing))
        return 1
    print("Persistent directory layout is intact.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="apply Alembic migrations").set_defaults(func=cmd_migrate)

    backup = subparsers.add_parser("backup", help="create a manual backup")
    backup.add_argument("--name", help="backup name (default: timestamped)")
    backup.set_defaults(func=cmd_backup)

    restore = subparsers.add_parser("restore", help="restore a backup")
    restore.add_argument("--name", required=True)
    restore.add_argument("--yes", action="store_true", help="confirm the overwrite")
    restore.set_defaults(func=cmd_restore)

    subparsers.add_parser("list-backups", help="list backups").set_defaults(func=cmd_list)

    export = subparsers.add_parser("export", help="bundle a backup for transfer")
    export.add_argument("--name", required=True)
    export.add_argument("--output")
    export.set_defaults(func=cmd_export)

    imp = subparsers.add_parser("import", help="import a bundled backup")
    imp.add_argument("archive")
    imp.set_defaults(func=cmd_import)

    subparsers.add_parser("verify", help="check persistent directories").set_defaults(func=cmd_verify)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
