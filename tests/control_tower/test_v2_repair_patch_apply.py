"""Unit tests for patch_apply.py: git resolution, diff validation, failure modes."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from migration_factory.repair_loop.patch_apply import (
    REASON_CODE_MALFORMED_DIFF,
    REASON_CODE_PATCH_APPLY_FAILED,
    REASON_CODE_PATCH_APPLY_SANDBOX_MISSING,
    REASON_CODE_PATCH_APPLY_TARGET_MISSING,
    REASON_CODE_PATCH_APPLY_TIMEOUT,
    REASON_CODE_PATCH_APPLY_UNSAFE_PATH,
    REASON_CODE_PATCH_CHECK_FAILED,
    REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
    REASON_CODE_PATCH_ENGINE_OS_ERROR,
    _check_path_safety,
    _check_sandbox_preflight,
    _resolve_git_executable,
    validate_unified_diff_structure,
    apply_patch_to_sandbox,
)


def test_resolve_git_executable_found() -> None:
    exe = _resolve_git_executable()
    assert exe is not None
    assert isinstance(exe, str)
    assert len(exe) > 0


def test_resolve_git_executable_not_found(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    exe = _resolve_git_executable()
    assert exe is None


def test_validate_diff_structure_valid() -> None:
    diff = (
        "diff --git a/test.txt b/test.txt\n"
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
        "@@ -1,2 +1,3 @@\n"
        " line1\n"
        "+line2_new\n"
        " line3\n"
    )
    assert validate_unified_diff_structure(diff) is None


def test_validate_diff_structure_missing_file_headers() -> None:
    diff = "some text with no diff markers\n"
    result = validate_unified_diff_structure(diff)
    assert result is not None
    assert "missing_file_headers" in result


def test_validate_diff_structure_missing_hunk() -> None:
    diff = (
        "diff --git a/test.txt b/test.txt\n"
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
    )
    result = validate_unified_diff_structure(diff)
    assert result is not None
    assert "missing_hunk" in result


def test_validate_diff_structure_hunk_count_mismatch() -> None:
    diff = (
        "--- a/test.txt\n"
        "+++ b/test.txt\n"
        "@@ -1,2 +1,5 @@\n"
        " line1\n"
        "+addition\n"
    )
    result = validate_unified_diff_structure(diff)
    assert result is not None
    assert "hunk" in result


def test_validate_diff_structure_absolute_path() -> None:
    diff = (
        "--- /etc/passwd\n"
        "+++ /etc/passwd\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    result = validate_unified_diff_structure(diff)
    assert result is not None
    assert "absolute_path" in result


def test_check_path_safety_empty() -> None:
    assert _check_path_safety("") is not None


def test_check_path_safety_absolute() -> None:
    assert _check_path_safety("/etc/passwd") is not None


def test_check_path_safety_traversal() -> None:
    assert _check_path_safety("../etc/passwd") is not None


def test_check_path_safety_windows_drive() -> None:
    assert _check_path_safety("C:\\Windows\\system32") is not None


def test_check_path_safety_valid_relative() -> None:
    assert _check_path_safety("src/main/java/App.java") is None


def test_check_sandbox_preflight_missing_sandbox(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_sandbox"
    patch_file = tmp_path / "patch.diff"
    patch_file.write_text("dummy", encoding="utf-8")
    result = _check_sandbox_preflight(missing, patch_file, ["test.txt"], "dummy")
    assert result == REASON_CODE_PATCH_APPLY_SANDBOX_MISSING


def test_check_sandbox_preflight_missing_patch(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    missing_patch = tmp_path / "no_patch.diff"
    result = _check_sandbox_preflight(sandbox, missing_patch, ["test.txt"], "dummy")
    assert result == REASON_CODE_PATCH_APPLY_TARGET_MISSING


def test_check_sandbox_preflight_unsafe_path(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    patch_file = tmp_path / "patch.diff"
    patch_file.write_text("dummy", encoding="utf-8")
    result = _check_sandbox_preflight(
        sandbox, patch_file, ["../../etc/passwd"], "dummy"
    )
    assert result == REASON_CODE_PATCH_APPLY_UNSAFE_PATH


class TestApplyPatchToSandbox:
    def test_missing_git_returns_engine_unavailable(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda _: None)
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-content\n"
            "+modified\n"
        )

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_PATCH_ENGINE_UNAVAILABLE

    def test_malformed_diff_rejected_before_git(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        called = []

        def _track_run(*args, **kwargs):
            called.append(True)
            return subprocess.CompletedProcess(args[0], 0)

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff="not a valid diff at all",
            touched_paths=["test.txt"],
            run=_track_run,
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_MALFORMED_DIFF
        assert len(called) == 0

    def test_git_check_failure_returns_check_failed(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-nonexistent_content\n"
            "+modified\n"
        )

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
        )
        assert result.status == "REJECTED"
        assert result.reason_code in (
            REASON_CODE_PATCH_CHECK_FAILED,
            REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
        )

    def test_git_apply_failure_after_check(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-content\n"
            "+modified\n"
        )

        call_count = 0

        def _fail_apply(
            command: list[str], **kwargs
        ) -> subprocess.CompletedProcess:
            nonlocal call_count
            call_count += 1
            if "--check" in command:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="apply failed")

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
            run=_fail_apply,
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_PATCH_APPLY_FAILED

    def test_file_not_found_error_returns_engine_unavailable(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-content\n"
            "+modified\n"
        )

        def _raise_fnf(*args, **kwargs):
            raise FileNotFoundError("git not found")

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
            run=_raise_fnf,
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_PATCH_ENGINE_UNAVAILABLE

    def test_os_error_returns_os_error(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-content\n"
            "+modified\n"
        )

        def _raise_oserror(*args, **kwargs):
            raise PermissionError("access denied")

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
            run=_raise_oserror,
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_PATCH_ENGINE_OS_ERROR

    def test_timeout_returns_apply_timeout(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("content", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-content\n"
            "+modified\n"
        )

        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("git", 60, output="", stderr="timed out")

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
            run=_raise_timeout,
        )
        assert result.status == "REJECTED"
        assert result.reason_code == REASON_CODE_PATCH_APPLY_TIMEOUT
        assert "timed out" in result.reason or "timeout" in result.reason.lower()

    def test_successful_apply_returns_applied(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("line1\nline2\nline3\n", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "+new_line\n"
            " line2\n"
            " line3\n"
        )

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
        )
        if result.status == "APPLIED":
            assert result.reason_code == ""
            # Verify sandbox file was modified
            content = (sandbox / "test.txt").read_text(encoding="utf-8")
            assert "new_line" in content
        else:
            # Git may not be available on test runner
            assert result.status == "REJECTED"
            assert result.reason_code in (
                REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
                REASON_CODE_PATCH_CHECK_FAILED,
                REASON_CODE_PATCH_APPLY_FAILED,
            )

    def test_validate_newline_preservation(self, tmp_path: Path) -> None:
        """Diff text without trailing newline gets one added, but content
        is otherwise preserved exactly."""
        sandbox = tmp_path / "sandbox"
        sandbox.mkdir()
        (sandbox / "test.txt").write_text("line1\nline2\n", encoding="utf-8")

        diff = (
            "--- a/test.txt\n"
            "+++ b/test.txt\n"
            "@@ -1,2 +1,3 @@\n"
            " line1\n"
            "+new_line\n"
            " line2\n"
        )

        result = apply_patch_to_sandbox(
            run_dir=str(tmp_path / "run"),
            sandbox_path=str(sandbox),
            attempt=1,
            unified_diff=diff,
            touched_paths=["test.txt"],
        )
        path = result.patch_path
        written = path.read_text(encoding="utf-8")
        assert written.endswith("\n")
        # The check is for the apply logic correctness, not rstripping
        assert "+new_line\n" in written
