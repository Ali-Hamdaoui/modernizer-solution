from __future__ import annotations

import hashlib
from pathlib import Path
import sys

import pytest

from migration_factory.control_tower.domain.errors import (
    ArtifactChangedDuringHashingError,
    ArtifactIsNotAFileError,
    ArtifactNotFoundError,
)
from migration_factory.control_tower.infrastructure.artifact_hashing import (
    ArtifactFileIdentity,
    hash_artifact_sha256,
)
from migration_factory.control_tower.infrastructure.artifact_paths import ArtifactRootRegistry


def test_sha256_is_correct_for_known_small_file(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    content = b"hello artifact\n"
    (root / "report.txt").write_bytes(content)
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = hash_artifact_sha256(registry, "artifact-root", "report.txt")

    assert result.checksum_algorithm == "sha256"
    assert result.checksum_hex_digest == hashlib.sha256(content).hexdigest()


def test_large_files_are_hashed_in_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    payload = b"a" * (1024 * 1024 * 2 + 17)
    path = root / "large.bin"
    path.write_bytes(payload)
    registry = ArtifactRootRegistry({"artifact-root": root})
    read_sizes: list[int] = []

    import migration_factory.control_tower.infrastructure.artifact_hashing as artifact_hashing

    real_open = Path.open

    class RecordingHandle:
        def __init__(self, handle) -> None:
            self._handle = handle

        def read(self, size: int = -1) -> bytes:
            read_sizes.append(size)
            return self._handle.read(size)

        def __getattr__(self, name: str):
            return getattr(self._handle, name)

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._handle.__exit__(exc_type, exc, tb)

    def recording_open(self: Path, *args, **kwargs):
        return RecordingHandle(real_open(self, *args, **kwargs))

    monkeypatch.setattr(Path, "open", recording_open)

    result = artifact_hashing.hash_artifact_sha256(
        registry,
        "artifact-root",
        "large.bin",
        chunk_size=1024 * 1024,
    )

    assert result.size_bytes == len(payload)
    assert read_sizes.count(1024 * 1024) >= 2


def test_hash_result_includes_expected_public_metadata(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "report.txt"
    path.write_text("hello\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = hash_artifact_sha256(registry, "artifact-root", "report.txt")

    assert result.registered_root_id == "artifact-root"
    assert result.normalized_relative_path == "report.txt"
    assert result.size_bytes == path.stat().st_size
    assert result.modified_time_ns == path.stat().st_mtime_ns
    assert isinstance(result.file_identity, ArtifactFileIdentity)


def test_hash_result_does_not_expose_absolute_canonical_path(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "report.txt").write_text("hello\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = hash_artifact_sha256(registry, "artifact-root", "report.txt")

    assert "resolved_path" not in result.__dict__
    assert "absolute_path" not in result.__dict__


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    registry = ArtifactRootRegistry({"artifact-root": root})

    with pytest.raises(ArtifactNotFoundError, match="Artifact not found"):
        hash_artifact_sha256(registry, "artifact-root", "missing.txt")


def test_directory_path_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    folder = root / "reports"
    folder.mkdir(parents=True)
    registry = ArtifactRootRegistry({"artifact-root": root})

    with pytest.raises(ArtifactIsNotAFileError, match="Artifact is not a file"):
        hash_artifact_sha256(registry, "artifact-root", "reports")


def test_file_modified_during_hashing_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "report.txt"
    path.write_bytes(b"x" * (1024 * 1024 + 8))
    registry = ArtifactRootRegistry({"artifact-root": root})

    real_open = Path.open

    class MutatingHandle:
        def __init__(self, handle) -> None:
            self._handle = handle
            self._mutated = False

        def read(self, size: int = -1) -> bytes:
            chunk = self._handle.read(size)
            if chunk and not self._mutated:
                self._mutated = True
                path.write_bytes(b"y" * (1024 * 1024 + 8))
            return chunk

        def __getattr__(self, name: str):
            return getattr(self._handle, name)

        def __enter__(self):
            self._handle.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self._handle.__exit__(exc_type, exc, tb)

    monkeypatch.setattr(Path, "open", lambda self, *a, **k: MutatingHandle(real_open(self, *a, **k)))

    with pytest.raises(ArtifactChangedDuringHashingError, match="changed during hashing"):
        hash_artifact_sha256(
            registry,
            "artifact-root",
            "report.txt",
            chunk_size=1024 * 512,
        )


def test_file_replaced_during_hashing_is_rejected_where_deterministically_testable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "report.txt"
    path.write_text("before\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    import migration_factory.control_tower.infrastructure.artifact_hashing as artifact_hashing

    real_capture = artifact_hashing._capture_file_snapshot
    call_count = {"count": 0}

    def capturing_with_replacement(target: Path):
        call_count["count"] += 1
        if call_count["count"] == 2:
            replacement = root / "replacement.txt"
            replacement.write_text("after\n", encoding="utf-8")
            replacement.replace(path)
        return real_capture(target)

    monkeypatch.setattr(artifact_hashing, "_capture_file_snapshot", capturing_with_replacement)

    with pytest.raises(ArtifactChangedDuringHashingError, match="identity changed|resolved path changed|modification time changed|size changed"):
        hash_artifact_sha256(registry, "artifact-root", "report.txt")


def test_file_identity_size_mtime_and_resolved_path_are_checked_before_and_after_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    path = root / "report.txt"
    path.write_text("hello\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    import migration_factory.control_tower.infrastructure.artifact_hashing as artifact_hashing

    real_capture = artifact_hashing._capture_file_snapshot
    captured_snapshots: list[object] = []

    def recording_capture(target: Path):
        snapshot = real_capture(target)
        captured_snapshots.append(snapshot)
        return snapshot

    monkeypatch.setattr(artifact_hashing, "_capture_file_snapshot", recording_capture)

    result = hash_artifact_sha256(registry, "artifact-root", "report.txt")

    assert result.normalized_relative_path == "report.txt"
    assert len(captured_snapshots) == 2
    assert captured_snapshots[0].resolved_path == captured_snapshots[1].resolved_path
    assert captured_snapshots[0].identity == captured_snapshots[1].identity
    assert captured_snapshots[0].size_bytes == captured_snapshots[1].size_bytes
    assert captured_snapshots[0].modified_time_ns == captured_snapshots[1].modified_time_ns


@pytest.mark.skipif(sys.platform.startswith("win"), reason="symlink target replacement differs on Windows")
def test_hash_result_uses_same_public_shape_after_safe_read(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "report.txt").write_text("hello\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = hash_artifact_sha256(registry, "artifact-root", "report.txt")

    assert set(result.__dict__) == {
        "registered_root_id",
        "original_relative_path",
        "normalized_relative_path",
        "uniqueness_key",
        "checksum_algorithm",
        "checksum_hex_digest",
        "size_bytes",
        "modified_time_ns",
        "file_identity",
    }
