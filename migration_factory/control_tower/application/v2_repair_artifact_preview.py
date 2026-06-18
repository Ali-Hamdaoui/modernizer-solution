from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary


_ARTIFACT_KIND_BY_NAME: dict[str, str] = {
    "repair_proposal.json": "json",
    "repair_verification.json": "json",
    "repair_proposal.md": "markdown",
    "approval_state.json": "json",
    "repair_execution_plan.json": "json",
    "repair_patch_candidate.json": "json",
    "sandbox_apply_result.json": "json",
    "sandbox_validation_result.json": "json",
    "backups/pom.xml.before-repair": "backup",
}
_PREVIEW_LIMIT = 4000


@dataclass(frozen=True, slots=True)
class RepairArtifactMetadata:
    proposal_id: str
    artifact_name: str
    relative_path: str
    kind: str
    exists: bool
    size_bytes: int
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "artifact_name": self.artifact_name,
            "relative_path": self.relative_path,
            "kind": self.kind,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class RepairArtifactPreview:
    proposal_id: str
    artifact_name: str
    kind: str
    content: str
    truncated: bool
    size_bytes: int
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "artifact_name": self.artifact_name,
            "kind": self.kind,
            "content": self.content,
            "truncated": self.truncated,
            "size_bytes": self.size_bytes,
            "read_only": self.read_only,
        }


class V2RepairArtifactPreviewService:
    def list_artifacts(self, *, trace_root: Path, proposal_id: str) -> list[RepairArtifactMetadata]:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        return [
            self._metadata_for_artifact(proposal_dir=proposal_dir, proposal_id=proposal_id, artifact_name=name)
            for name in _ARTIFACT_KIND_BY_NAME
        ]

    def preview_artifact(
        self,
        *,
        trace_root: Path,
        proposal_id: str,
        artifact_name: str,
    ) -> RepairArtifactPreview:
        proposal_dir = self._proposal_dir(trace_root=trace_root, proposal_id=proposal_id)
        normalized_name = self._normalize_artifact_name(artifact_name)
        artifact_path = self._artifact_path(proposal_dir=proposal_dir, artifact_name=normalized_name)
        if not artifact_path.is_file():
            raise FileNotFoundError(normalized_name)
        raw = artifact_path.read_text(encoding="utf-8", errors="replace")
        redacted = redact_model_summary(raw).strip()
        truncated = len(redacted) > _PREVIEW_LIMIT
        content = redacted[:_PREVIEW_LIMIT] + ("...[truncated]" if truncated else "")
        return RepairArtifactPreview(
            proposal_id=proposal_id,
            artifact_name=normalized_name,
            kind=_ARTIFACT_KIND_BY_NAME[normalized_name],
            content=content,
            truncated=truncated,
            size_bytes=artifact_path.stat().st_size,
        )

    def _metadata_for_artifact(
        self,
        *,
        proposal_dir: Path,
        proposal_id: str,
        artifact_name: str,
    ) -> RepairArtifactMetadata:
        artifact_path = self._artifact_path(proposal_dir=proposal_dir, artifact_name=artifact_name)
        exists = artifact_path.is_file()
        return RepairArtifactMetadata(
            proposal_id=proposal_id,
            artifact_name=artifact_name,
            relative_path=str(Path("ai_supervision") / "repair_proposals" / proposal_id / Path(artifact_name)).replace("\\", "/"),
            kind=_ARTIFACT_KIND_BY_NAME[artifact_name],
            exists=exists,
            size_bytes=artifact_path.stat().st_size if exists else 0,
        )

    @staticmethod
    def _proposal_dir(*, trace_root: Path, proposal_id: str) -> Path:
        if not str(proposal_id or "").strip():
            raise ValueError("Repair proposal id is required.")
        proposal_root = (trace_root / "ai_supervision" / "repair_proposals").resolve()
        proposal_dir = (proposal_root / proposal_id).resolve()
        try:
            proposal_dir.relative_to(proposal_root)
        except ValueError as exc:
            raise ValueError("Repair proposal path must stay within governed repair proposal root.") from exc
        if not proposal_dir.is_dir():
            raise FileNotFoundError(proposal_id)
        return proposal_dir

    def _artifact_path(self, *, proposal_dir: Path, artifact_name: str) -> Path:
        artifact_path = (proposal_dir / Path(artifact_name)).resolve()
        try:
            artifact_path.relative_to(proposal_dir.resolve())
        except ValueError as exc:
            raise ValueError("Artifact path traversal is not allowed.") from exc
        return artifact_path

    @staticmethod
    def _normalize_artifact_name(name: str) -> str:
        raw = str(name or "").strip().replace("\\", "/")
        if not raw:
            raise ValueError("Artifact name is required.")
        if raw.startswith("/") or PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
            raise ValueError("Absolute artifact paths are not allowed.")
        normalized = str(PurePosixPath(raw))
        if ".." in PurePosixPath(normalized).parts:
            raise ValueError("Artifact path traversal is not allowed.")
        if normalized not in _ARTIFACT_KIND_BY_NAME:
            raise ValueError(f"Unsupported repair artifact {normalized!r}.")
        return normalized
