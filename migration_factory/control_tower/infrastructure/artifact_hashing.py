"""Streaming SHA-256 hashing for Control Tower artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from migration_factory.control_tower.domain.errors import (
    ArtifactChangedDuringHashingError,
    ArtifactNotFoundError,
)
from migration_factory.control_tower.infrastructure.artifact_paths import (
    ArtifactPathValidationResult,
    ArtifactRootRegistry,
    _resolve_artifact_path,
)


DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class ArtifactFileIdentity:
    device_id: int | None
    inode: int | None
    file_attributes: int | None


@dataclass(frozen=True)
class ArtifactHashResult:
    registered_root_id: str
    original_relative_path: str
    normalized_relative_path: str
    uniqueness_key: str
    checksum_algorithm: str
    checksum_hex_digest: str
    size_bytes: int
    modified_time_ns: int
    file_identity: ArtifactFileIdentity


@dataclass(frozen=True)
class _FileSnapshot:
    resolved_path: Path
    identity: ArtifactFileIdentity
    size_bytes: int
    modified_time_ns: int


def hash_artifact_sha256(
    registry: ArtifactRootRegistry,
    registered_root_id: str,
    relative_artifact_path: str | Path,
    *,
    chunk_size: int = DEFAULT_HASH_CHUNK_SIZE,
) -> ArtifactHashResult:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    resolved = _resolve_artifact_path(
        registry,
        registered_root_id,
        relative_artifact_path,
        require_exists=True,
        require_file=True,
    )
    before = _capture_file_snapshot(resolved.absolute_path)
    checksum_hex_digest = _stream_sha256(resolved.absolute_path, chunk_size=chunk_size)
    try:
        after = _capture_file_snapshot(resolved.absolute_path)
    except ArtifactNotFoundError as exc:
        raise ArtifactChangedDuringHashingError(
            resolved.normalized_relative_path,
            "artifact disappeared during hashing",
        ) from exc

    _ensure_snapshot_unchanged(
        resolved.to_public_result(),
        before=before,
        after=after,
    )

    return ArtifactHashResult(
        registered_root_id=resolved.registered_root_id,
        original_relative_path=resolved.original_relative_path,
        normalized_relative_path=resolved.normalized_relative_path,
        uniqueness_key=resolved.uniqueness_key,
        checksum_algorithm="sha256",
        checksum_hex_digest=checksum_hex_digest,
        size_bytes=before.size_bytes,
        modified_time_ns=before.modified_time_ns,
        file_identity=before.identity,
    )


def _stream_sha256(path: Path, *, chunk_size: int) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _capture_file_snapshot(path: Path) -> _FileSnapshot:
    if not path.exists():
        raise ArtifactNotFoundError(path.name)
    stat_result = path.stat()
    return _FileSnapshot(
        resolved_path=path.resolve(strict=True),
        identity=ArtifactFileIdentity(
            device_id=getattr(stat_result, "st_dev", None),
            inode=getattr(stat_result, "st_ino", None),
            file_attributes=getattr(stat_result, "st_file_attributes", None),
        ),
        size_bytes=stat_result.st_size,
        modified_time_ns=stat_result.st_mtime_ns,
    )


def _ensure_snapshot_unchanged(
    artifact: ArtifactPathValidationResult,
    *,
    before: _FileSnapshot,
    after: _FileSnapshot,
) -> None:
    if before.resolved_path != after.resolved_path:
        raise ArtifactChangedDuringHashingError(
            artifact.normalized_relative_path,
            "resolved path changed during hashing",
        )
    if before.identity != after.identity:
        raise ArtifactChangedDuringHashingError(
            artifact.normalized_relative_path,
            "file identity changed during hashing",
        )
    if before.size_bytes != after.size_bytes:
        raise ArtifactChangedDuringHashingError(
            artifact.normalized_relative_path,
            "file size changed during hashing",
        )
    if before.modified_time_ns != after.modified_time_ns:
        raise ArtifactChangedDuringHashingError(
            artifact.normalized_relative_path,
            "file modification time changed during hashing",
        )
