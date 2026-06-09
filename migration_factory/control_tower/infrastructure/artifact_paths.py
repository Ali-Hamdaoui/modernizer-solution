"""Filesystem-only artifact path validation for Control Tower."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Iterable, Mapping

from migration_factory.control_tower.domain.errors import (
    ArtifactEscapedRootError,
    ArtifactIsNotAFileError,
    ArtifactNotFoundError,
    UnknownRegisteredRootError,
    UnsafeArtifactPathError,
    UnsafeSymlinkOrReparsePointError,
    UnsupportedArtifactPathError,
)
from migration_factory.control_tower.infrastructure.windows_paths import (
    has_cross_drive_segment,
    has_drive_qualified_prefix,
    is_unc_path,
    is_unsafe_windows_reparse_point,
    normalize_key_case,
)
from migration_factory.control_tower.schemas import RegisteredFilesystemRoot


_SEPARATOR_RE = re.compile(r"[\\/]+")


@dataclass(frozen=True)
class ArtifactPathValidationResult:
    registered_root_id: str
    original_relative_path: str
    normalized_relative_path: str
    uniqueness_key: str


@dataclass(frozen=True)
class _ResolvedArtifactPath:
    registered_root_id: str
    original_relative_path: str
    normalized_relative_path: str
    uniqueness_key: str
    absolute_path: Path

    def to_public_result(self) -> ArtifactPathValidationResult:
        return ArtifactPathValidationResult(
            registered_root_id=self.registered_root_id,
            original_relative_path=self.original_relative_path,
            normalized_relative_path=self.normalized_relative_path,
            uniqueness_key=self.uniqueness_key,
        )


class ArtifactRootRegistry:
    """Trusted registry that maps registered root IDs to local filesystem roots."""

    def __init__(self, roots_by_id: Mapping[str, Path | str]) -> None:
        normalized_roots: dict[str, Path] = {}
        for root_id, root_path in roots_by_id.items():
            if root_id in normalized_roots:
                raise ValueError(f"registered root IDs must be unique: {root_id}")
            normalized_roots[root_id] = Path(root_path).expanduser().resolve(strict=False)
        self._roots_by_id = normalized_roots

    @classmethod
    def from_registered_roots(
        cls,
        roots: Iterable[RegisteredFilesystemRoot],
    ) -> "ArtifactRootRegistry":
        return cls({root.root_id: root.path for root in roots})

    def require_root_path(self, registered_root_id: str) -> Path:
        try:
            return self._roots_by_id[registered_root_id]
        except KeyError as exc:
            raise UnknownRegisteredRootError(registered_root_id) from exc


def validate_artifact_path(
    registry: ArtifactRootRegistry,
    registered_root_id: str,
    relative_artifact_path: str | Path,
    *,
    require_exists: bool = False,
    require_file: bool = False,
) -> ArtifactPathValidationResult:
    return _resolve_artifact_path(
        registry,
        registered_root_id,
        relative_artifact_path,
        require_exists=require_exists,
        require_file=require_file,
    ).to_public_result()


def _resolve_artifact_path(
    registry: ArtifactRootRegistry,
    registered_root_id: str,
    relative_artifact_path: str | Path,
    *,
    require_exists: bool,
    require_file: bool,
) -> _ResolvedArtifactPath:
    root_path = registry.require_root_path(registered_root_id)
    original_path = _coerce_artifact_path(relative_artifact_path)
    normalized_path = _normalize_relative_artifact_path(original_path)
    uniqueness_key = f"{registered_root_id}:{normalize_key_case(normalized_path)}"

    root_resolved = root_path.resolve(strict=False)
    candidate_path = root_resolved

    for component in normalized_path.split("/"):
        candidate_path = candidate_path / component
        if candidate_path.exists() or candidate_path.is_symlink():
            if _is_unsafe_reparse_point(candidate_path):
                raise UnsafeSymlinkOrReparsePointError(original_path, component)
            if candidate_path.is_symlink():
                resolved_component = candidate_path.resolve(strict=True)
                if not _is_path_within_root(root_resolved, resolved_component):
                    raise UnsafeSymlinkOrReparsePointError(original_path, component)
                candidate_path = resolved_component

    if require_exists and not candidate_path.exists():
        raise ArtifactNotFoundError(normalized_path)
    if require_file and candidate_path.exists() and not candidate_path.is_file():
        raise ArtifactIsNotAFileError(normalized_path)
    if candidate_path.exists():
        resolved_candidate = candidate_path.resolve(strict=True)
        if not _is_path_within_root(root_resolved, resolved_candidate):
            raise ArtifactEscapedRootError(normalized_path, registered_root_id)

    return _ResolvedArtifactPath(
        registered_root_id=registered_root_id,
        original_relative_path=original_path,
        normalized_relative_path=normalized_path,
        uniqueness_key=uniqueness_key,
        absolute_path=candidate_path,
    )


def _coerce_artifact_path(relative_artifact_path: str | Path) -> str:
    if isinstance(relative_artifact_path, Path):
        return relative_artifact_path.as_posix()
    return str(relative_artifact_path)


def _normalize_relative_artifact_path(raw_path: str) -> str:
    if raw_path == "":
        raise UnsafeArtifactPathError(raw_path, "artifact path must not be empty")
    if is_unc_path(raw_path):
        raise UnsupportedArtifactPathError(raw_path, "UNC paths are not allowed")
    if raw_path.startswith(("/", "\\")):
        raise UnsupportedArtifactPathError(raw_path, "absolute paths are not allowed")
    if has_drive_qualified_prefix(raw_path):
        raise UnsupportedArtifactPathError(
            raw_path,
            "drive-qualified paths are not allowed",
        )
    if has_cross_drive_segment(raw_path):
        raise UnsupportedArtifactPathError(
            raw_path,
            "cross-drive path segments are not allowed",
        )

    parts: list[str] = []
    for component in _SEPARATOR_RE.split(raw_path):
        if component in ("", "."):
            continue
        if component == "..":
            raise UnsafeArtifactPathError(raw_path, "parent traversal is not allowed")
        if ":" in component:
            raise UnsupportedArtifactPathError(
                raw_path,
                "drive-qualified or alternate-stream path segments are not allowed",
            )
        parts.append(component)

    if not parts:
        raise UnsafeArtifactPathError(raw_path, "artifact path must not be root-only")
    return "/".join(parts)


def _is_path_within_root(root_path: Path, candidate_path: Path) -> bool:
    normalized_root = os.path.normcase(str(root_path))
    normalized_candidate = os.path.normcase(str(candidate_path))
    try:
        return os.path.commonpath([normalized_root, normalized_candidate]) == normalized_root
    except ValueError:
        return False


def _is_unsafe_reparse_point(path: Path) -> bool:
    return is_unsafe_windows_reparse_point(path)
