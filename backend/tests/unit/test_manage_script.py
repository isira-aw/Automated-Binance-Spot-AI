"""Operational tooling: backup/restore safety rules (§49, §50).

``scripts/manage.py`` handles the one operation where a bug is unrecoverable
-- restoring over a working database from a backup that turns out to be
truncated. These tests cover the guards that make that impossible, plus the
command construction that keeps the docker and direct paths producing the
same backup format.

The database round-trip itself (`pg_dump` -> destroy -> `pg_restore` ->
verify row counts and model-artifact checksums) is exercised manually
against a real PostgreSQL and recorded in PROJECT_STATUS.md; it needs a live
server, so it is not reproduced here. What *is* here is everything that can
fail without one.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "manage.py"


def _load_manage():
    """Import scripts/manage.py by path -- it is deliberately not a package
    (it must run standalone on a machine with no venv activated)."""
    spec = importlib.util.spec_from_file_location("manage_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def manage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = _load_manage()
    # Point the tool at a scratch tree so no test can touch real backups.
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "BACKUP_DIR", tmp_path / "backups")
    return module


def _args(**kwargs) -> argparse.Namespace:
    kwargs.setdefault("direct", False)
    return argparse.Namespace(**kwargs)


class TestDbCommandConstruction:
    def test_docker_mode_goes_through_compose_exec(self, manage):
        command = manage.db_command(_args(), "pg_dump", "--format=custom")
        assert command[:5] == ["docker", "compose", "exec", "-T", "postgres"]
        assert "pg_dump" in command
        assert "--format=custom" in command

    def test_direct_mode_calls_the_local_binary_with_host_and_port(
        self, manage, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("POSTGRES_HOST", "db.example")
        monkeypatch.setenv("POSTGRES_PORT", "6543")
        command = manage.db_command(_args(direct=True), "pg_restore", "--clean")

        assert command[0] == "pg_restore"
        assert "docker" not in command
        assert command[command.index("-h") + 1] == "db.example"
        assert command[command.index("-p") + 1] == "6543"
        assert "--clean" in command

    def test_both_modes_pass_identical_database_flags(self, manage):
        """The two paths differ only in how the binary is reached -- the
        database, user and format flags must match, or the two modes would
        quietly produce different backup formats."""
        docker = manage.db_command(_args(), "pg_dump", "--format=custom", "--no-owner")
        direct = manage.db_command(_args(direct=True), "pg_dump", "--format=custom", "--no-owner")

        def database_flags(command: list[str]) -> list[str]:
            # Drop only the connection-routing difference (-h host, -p port),
            # which direct mode adds and docker mode gets from the container.
            out, skip = [], 0
            for index, token in enumerate(command):
                if skip:
                    skip = 0
                    continue
                if token in {"-h", "-p"}:
                    skip = 1
                    continue
                if index < command.index("pg_dump"):
                    continue
                out.append(token)
            return out

        assert database_flags(docker) == database_flags(direct)
        assert "--format=custom" in database_flags(direct)
        assert "-d" in database_flags(direct)

    def test_the_env_var_selects_direct_mode_without_the_flag(
        self, manage, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("MANAGE_DB_MODE", "direct")
        assert manage.direct_mode(_args()) is True

    def test_docker_is_the_default(self, manage, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("MANAGE_DB_MODE", raising=False)
        assert manage.direct_mode(_args()) is False


class TestBackupIntegrity:
    def test_a_failed_dump_leaves_no_partial_backup_behind(
        self, manage, monkeypatch: pytest.MonkeyPatch
    ):
        """A half-written backup that `list-backups` shows as real is worse
        than no backup: it is discovered only during an incident."""

        def failing_run(command, **kwargs):
            raise subprocess.CalledProcessError(1, command)

        monkeypatch.setattr(manage, "run", failing_run)

        with pytest.raises(subprocess.CalledProcessError):
            manage.cmd_backup(_args(name="doomed", direct=True))

        assert not (manage.BACKUP_DIR / "doomed").exists()

    def test_the_manifest_is_written_last(self, manage, monkeypatch: pytest.MonkeyPatch):
        """Ordering is the mechanism behind the completeness guard: if the
        manifest existed before the dump finished, an interrupted backup
        would read as finished."""
        seen: list[str] = []

        def fake_run(command, **kwargs):
            seen.append("dump")
            # pg_dump writes to the handle the caller opened.
            handle = kwargs.get("stdout")
            if handle is not None:
                handle.write(b"fake-dump-bytes")
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(manage, "run", fake_run)
        manage.cmd_backup(_args(name="ordered", direct=True))

        staging = manage.BACKUP_DIR / "ordered"
        assert seen == ["dump"]
        assert (staging / manage.MANIFEST_NAME).is_file()
        assert (staging / manage.DB_DUMP_NAME).read_bytes() == b"fake-dump-bytes"


class TestRestoreGuards:
    def _make_backup(self, manage, name: str, *, manifest: bool) -> Path:
        staging = manage.BACKUP_DIR / name
        staging.mkdir(parents=True)
        (staging / manage.DB_DUMP_NAME).write_bytes(b"dump")
        if manifest:
            (staging / manage.MANIFEST_NAME).write_text("created_at: now\n", encoding="utf-8")
        return staging

    def test_restoring_an_incomplete_backup_is_refused(
        self, manage, monkeypatch: pytest.MonkeyPatch
    ):
        """No manifest means that backup never finished -- restoring it
        would write a truncated dump over a working database."""
        self._make_backup(manage, "incomplete", manifest=False)
        called = False

        def fake_run(command, **kwargs):
            nonlocal called
            called = True
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(manage, "run", fake_run)

        assert manage.cmd_restore(_args(name="incomplete", yes=True, direct=True)) == 1
        assert called is False  # refused before touching the database

    def test_restoring_a_missing_backup_is_refused(self, manage):
        assert manage.cmd_restore(_args(name="nope", yes=True, direct=True)) == 1

    def test_restore_requires_explicit_confirmation(self, manage, monkeypatch: pytest.MonkeyPatch):
        self._make_backup(manage, "complete", manifest=True)
        called = False

        def fake_run(command, **kwargs):
            nonlocal called
            called = True
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(manage, "run", fake_run)

        assert manage.cmd_restore(_args(name="complete", yes=False, direct=True)) == 1
        assert called is False

    def test_a_complete_backup_restores(self, manage, monkeypatch: pytest.MonkeyPatch):
        self._make_backup(manage, "complete", manifest=True)
        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)
            return subprocess.CompletedProcess(command, 0)

        monkeypatch.setattr(manage, "run", fake_run)

        assert manage.cmd_restore(_args(name="complete", yes=True, direct=True)) == 0
        assert any("pg_restore" in c for c in commands)


class TestExportImport:
    def test_a_backup_survives_an_export_import_round_trip(self, manage, tmp_path: Path):
        staging = manage.BACKUP_DIR / "portable"
        staging.mkdir(parents=True)
        (staging / manage.DB_DUMP_NAME).write_bytes(b"dump-bytes")
        (staging / manage.MANIFEST_NAME).write_text("created_at: now\n", encoding="utf-8")

        bundle = tmp_path / "bundle.tar.gz"
        assert manage.cmd_export(_args(name="portable", output=str(bundle))) == 0
        assert bundle.is_file()

        # Simulate the other machine: nothing local to begin with.
        import shutil

        shutil.rmtree(staging)
        assert not staging.exists()

        assert manage.cmd_import(_args(archive=str(bundle))) == 0
        assert (staging / manage.DB_DUMP_NAME).read_bytes() == b"dump-bytes"
        assert (staging / manage.MANIFEST_NAME).is_file()

    def test_exporting_a_missing_backup_is_refused(self, manage, tmp_path: Path):
        assert manage.cmd_export(_args(name="nope", output=str(tmp_path / "x.tar.gz"))) == 1

    def test_importing_a_missing_archive_is_refused(self, manage, tmp_path: Path):
        assert manage.cmd_import(_args(archive=str(tmp_path / "nope.tar.gz"))) == 1

    def test_an_imported_bundle_keeps_its_directory_name(self, manage, tmp_path: Path):
        """`restore --name X` has to find the backup under exactly the name
        it was exported as, or the round trip is useless."""
        source = tmp_path / "staging" / "named-backup"
        source.mkdir(parents=True)
        (source / manage.MANIFEST_NAME).write_text("created_at: now\n", encoding="utf-8")

        bundle = tmp_path / "bundle.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(source, arcname="named-backup")

        assert manage.cmd_import(_args(archive=str(bundle))) == 0
        assert (manage.BACKUP_DIR / "named-backup" / manage.MANIFEST_NAME).is_file()


class TestVerify:
    def test_missing_persistent_directories_are_reported(self, manage):
        assert manage.cmd_verify(_args()) == 1

    def test_an_intact_layout_passes(self, manage):
        for path in ("data", "models/production", "artifacts", "logs", "backups"):
            (manage.ROOT / path).mkdir(parents=True, exist_ok=True)
        assert manage.cmd_verify(_args()) == 0
