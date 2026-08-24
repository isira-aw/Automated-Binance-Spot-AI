"""Model registry integrity checks (§39, §77, §112).

A restore that brings back the database but not the ``models/`` directory must
be *detected*, not silently ignored: a registry row whose artifact is missing
can never be treated as PRODUCTION, and the condition is surfaced through
System/health.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.logging_config import get_logger
from app.models.enums import ModelStatus
from app.models.ml import ModelVersion

logger = get_logger("ml.registry")


@dataclass
class ArtifactProblem:
    model_id: str
    version: str
    status: str
    artifact_path: str
    reason: str


@dataclass
class RegistryIntegrityReport:
    checked: int = 0
    problems: list[ArtifactProblem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def production_broken(self) -> bool:
        return any(p.status == ModelStatus.PRODUCTION.value for p in self.problems)


def _resolve(settings: Settings, artifact_path: str) -> Path:
    path = Path(artifact_path)
    return path if path.is_absolute() else settings.paths.root / path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def verify_registry_artifacts(
    session: AsyncSession, settings: Settings
) -> RegistryIntegrityReport:
    """Verify that every non-archived registry row has its artifact on disk."""
    result = await session.execute(
        select(ModelVersion).where(
            ModelVersion.status.in_(
                [
                    ModelStatus.PRODUCTION.value,
                    ModelStatus.VALIDATED.value,
                    ModelStatus.CANDIDATE.value,
                ]
            )
        )
    )
    report = RegistryIntegrityReport()
    for row in result.scalars():
        report.checked += 1
        path = _resolve(settings, row.artifact_path)
        if not path.is_file():
            report.problems.append(
                ArtifactProblem(
                    model_id=row.model_id,
                    version=row.version,
                    status=row.status,
                    artifact_path=str(path),
                    reason="Artifact file is missing on disk.",
                )
            )
            continue
        if row.artifact_sha256 and _sha256(path) != row.artifact_sha256:
            report.problems.append(
                ArtifactProblem(
                    model_id=row.model_id,
                    version=row.version,
                    status=row.status,
                    artifact_path=str(path),
                    reason="Artifact checksum does not match the registry record.",
                )
            )
    return report


async def demote_broken_production_models(
    session: AsyncSession, report: RegistryIntegrityReport
) -> list[str]:
    """Move PRODUCTION rows with unusable artifacts out of PRODUCTION.

    The system refuses to trade on a model it cannot load; demoting to REJECTED
    keeps the row (and its metadata) rather than deleting history (§39).
    """
    demoted: list[str] = []
    for problem in report.problems:
        if problem.status != ModelStatus.PRODUCTION.value:
            continue
        result = await session.execute(
            select(ModelVersion).where(
                ModelVersion.model_id == problem.model_id,
                ModelVersion.version == problem.version,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:  # pragma: no cover - row vanished between queries
            continue
        row.status = ModelStatus.REJECTED.value
        row.notes = (row.notes or "") + f"\n[integrity] {problem.reason}"
        demoted.append(f"{problem.model_id}:{problem.version}")
        logger.error(
            "Demoted PRODUCTION model with unusable artifact",
            extra={
                "event_type": "model_artifact_missing",
                "model_version": problem.version,
                "artifact": problem.artifact_path,
            },
        )
    return demoted
