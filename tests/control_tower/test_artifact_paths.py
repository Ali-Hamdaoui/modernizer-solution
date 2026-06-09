from __future__ import annotations

from pathlib import Path
import sys

import pytest

from migration_factory.control_tower.domain.errors import (
    ArtifactEscapedRootError,
    UnknownRegisteredRootError,
    UnsafeArtifactPathError,
    UnsafeSymlinkOrReparsePointError,
    UnsupportedArtifactPathError,
)
from migration_factory.control_tower.infrastructure.artifact_paths import (
    ArtifactRootRegistry,
    validate_artifact_path,
)


def test_registered_root_id_resolves_correctly(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = validate_artifact_path(registry, "artifact-root", "logs/output.txt")

    assert result.registered_root_id == "artifact-root"
    assert result.normalized_relative_path == "logs/output.txt"


def test_unknown_root_id_is_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnknownRegisteredRootError, match="Unknown registered root"):
        validate_artifact_path(registry, "missing-root", "logs/output.txt")


def test_absolute_paths_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsupportedArtifactPathError, match="absolute paths"):
        validate_artifact_path(registry, "artifact-root", "/etc/passwd")


def test_unc_paths_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsupportedArtifactPathError, match="UNC paths"):
        validate_artifact_path(registry, "artifact-root", r"\\server\share\file.txt")


def test_windows_drive_qualified_paths_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsupportedArtifactPathError, match="drive-qualified"):
        validate_artifact_path(registry, "artifact-root", r"C:\logs\output.txt")


def test_cross_drive_like_paths_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsupportedArtifactPathError, match="cross-drive"):
        validate_artifact_path(registry, "artifact-root", r"logs/D:\output.txt")


def test_parent_traversal_is_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsafeArtifactPathError, match="parent traversal"):
        validate_artifact_path(registry, "artifact-root", "../outside.txt")


def test_mixed_separator_traversal_attempts_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsafeArtifactPathError, match="parent traversal"):
        validate_artifact_path(registry, "artifact-root", r"reports\..\final.txt")


def test_stable_normalized_uniqueness_key_uses_forward_slashes(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    result = validate_artifact_path(registry, "artifact-root", r"reports\final.md")

    assert result.normalized_relative_path == "reports/final.md"
    assert "/" in result.uniqueness_key
    assert "\\" not in result.uniqueness_key


def test_dot_segments_are_safely_normalized(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    result = validate_artifact_path(registry, "artifact-root", "./reports/./final.md")

    assert result.normalized_relative_path == "reports/final.md"


def test_empty_or_root_only_paths_are_rejected(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    with pytest.raises(UnsafeArtifactPathError):
        validate_artifact_path(registry, "artifact-root", "")

    with pytest.raises(UnsafeArtifactPathError):
        validate_artifact_path(registry, "artifact-root", "./")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows-only case alias check")
def test_windows_case_aliases_normalize_identically(tmp_path: Path) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    left = validate_artifact_path(registry, "artifact-root", "Reports/FINAL.md")
    right = validate_artifact_path(registry, "artifact-root", "reports/final.md")

    assert left.uniqueness_key == right.uniqueness_key


def test_safe_in_root_file_path_validates(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "final.md").write_text("ok\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    result = validate_artifact_path(
        registry,
        "artifact-root",
        "reports/final.md",
        require_exists=True,
        require_file=True,
    )

    assert result.original_relative_path == "reports/final.md"
    assert "absolute_path" not in result.__dict__


def test_path_escaping_root_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "artifacts"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "final.md").write_text("ok\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    import migration_factory.control_tower.infrastructure.artifact_paths as artifact_paths

    monkeypatch.setattr(artifact_paths, "_is_path_within_root", lambda *_args: False)

    with pytest.raises(ArtifactEscapedRootError, match="escaped registered root"):
        validate_artifact_path(
            registry,
            "artifact-root",
            "reports/final.md",
            require_exists=True,
            require_file=True,
        )


def test_unsafe_symlink_escaping_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    link = root / "escape.txt"
    try:
        link.symlink_to(outside / "secret.txt")
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable on this platform: {exc}")
    registry = ArtifactRootRegistry({"artifact-root": root})

    with pytest.raises(UnsafeSymlinkOrReparsePointError, match="Unsafe symlink"):
        validate_artifact_path(
            registry,
            "artifact-root",
            "escape.txt",
            require_exists=True,
            require_file=True,
        )


def test_junctions_or_reparse_points_are_rejected_when_detectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = root / "linked"
    target.write_text("ok\n", encoding="utf-8")
    registry = ArtifactRootRegistry({"artifact-root": root})

    import migration_factory.control_tower.infrastructure.artifact_paths as artifact_paths

    monkeypatch.setattr(artifact_paths, "_is_unsafe_reparse_point", lambda _path: True)

    with pytest.raises(UnsafeSymlinkOrReparsePointError, match="reparse point"):
        validate_artifact_path(
            registry,
            "artifact-root",
            "linked",
            require_exists=True,
            require_file=True,
        )


def test_public_validation_result_does_not_expose_absolute_canonical_paths(
    tmp_path: Path,
) -> None:
    registry = ArtifactRootRegistry({"artifact-root": tmp_path})

    result = validate_artifact_path(registry, "artifact-root", "reports/final.md")

    assert set(result.__dict__) == {
        "registered_root_id",
        "original_relative_path",
        "normalized_relative_path",
        "uniqueness_key",
    }
