"""Hygiene tests that enforce git hygiene for runtime artifacts.

These tests fail when runtime DB files, caches, logs, or other generated
junk are tracked in the git index. They protect against accidental commits
of local development artifacts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

TRACKED_ARTIFACT_PATTERNS = (
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".db",
)


def _tracked_files() -> list[str]:
    """Return all files currently tracked in the git index."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.fail(f"git ls-files failed: {result.stderr}")
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def _is_runtime_artifact(path: str) -> bool:
    """Check if a tracked path looks like a runtime artifact."""
    lower = path.lower()
    if path.startswith(".control-tower-dev/"):
        return True
    for pat in TRACKED_ARTIFACT_PATTERNS:
        if lower.endswith(pat):
            return True
    return False


@pytest.mark.hygiene
class TestRuntimeArtifactsNotTracked:
    """Guard: no SQLite DBs, runtime folders, or generated junk in git index."""

    def test_no_sqlite_db_tracked(self) -> None:
        """Fail if any .sqlite3, .sqlite3-shm, .sqlite3-wal, or .db file is tracked."""
        offenders = [f for f in _tracked_files() if _is_runtime_artifact(f)]
        assert not offenders, (
            f"Runtime artifacts found in git index ({len(offenders)}):\n"
            + "\n".join(f"  {f}" for f in offenders)
        )

    def test_no_control_tower_dev_tracked(self) -> None:
        """Fail if anything under .control-tower-dev/ is tracked."""
        offenders = [f for f in _tracked_files() if f.startswith(".control-tower-dev/")]
        assert not offenders, (
            f"Tracked files under .control-tower-dev/:\n"
            + "\n".join(f"  {f}" for f in offenders)
        )

    @pytest.mark.usefixtures("tmp_path")
    def test_hypothetical_sqlite_would_fail(self, tmp_path: Path) -> None:
        """Verify the detection logic itself would catch a hypothetical tracked .sqlite3."""
        assert _is_runtime_artifact(".control-tower-dev/control_tower.sqlite3")
        assert _is_runtime_artifact("data/cache.sqlite3")
        assert _is_runtime_artifact("data/db.sqlite3-shm")
        assert _is_runtime_artifact("data/db.sqlite3-wal")
        assert _is_runtime_artifact("data/app.db")
        assert not _is_runtime_artifact("src/main.py")
        assert not _is_runtime_artifact("tests/test_app.py")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
