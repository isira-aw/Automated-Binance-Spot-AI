"""Model-registry artifact integrity (§77, §112 partial-restore scenario)."""

from __future__ import annotations

from pathlib import Path

from app.ml.registry import RegistryIntegrityReport, _resolve, _sha256
from tests.conftest import make_settings


def test_relative_artifact_paths_resolve_under_the_project_root(tmp_path: Path):
    settings = make_settings(paths={"root": tmp_path})
    assert _resolve(settings, "models/production/current/lgbm.txt") == (
        tmp_path / "models/production/current/lgbm.txt"
    )


def test_absolute_artifact_paths_are_preserved(tmp_path: Path):
    settings = make_settings(paths={"root": tmp_path})
    absolute = tmp_path / "elsewhere" / "lgbm.txt"
    assert _resolve(settings, str(absolute)) == absolute


def test_checksum_detects_a_corrupted_artifact(tmp_path: Path):
    artifact = tmp_path / "lgbm.txt"
    artifact.write_bytes(b"model-bytes")
    original = _sha256(artifact)
    artifact.write_bytes(b"model-bytez")
    assert _sha256(artifact) != original


def test_report_flags_a_broken_production_model():
    from app.ml.registry import ArtifactProblem

    report = RegistryIntegrityReport(
        checked=2,
        problems=[
            ArtifactProblem("lgbm", "v1", "PRODUCTION", "/models/lgbm.txt", "missing")
        ],
    )
    assert report.ok is False
    assert report.production_broken is True


def test_a_broken_candidate_does_not_break_production():
    from app.ml.registry import ArtifactProblem

    report = RegistryIntegrityReport(
        checked=2,
        problems=[
            ArtifactProblem("lgbm", "v2", "CANDIDATE", "/models/lgbm2.txt", "missing")
        ],
    )
    assert report.ok is False
    assert report.production_broken is False


def test_clean_report_is_ok():
    assert RegistryIntegrityReport(checked=3).ok is True
