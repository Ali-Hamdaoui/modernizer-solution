from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Sequence


RunCallable = Callable[..., subprocess.CompletedProcess]

REASON_CODE_PATCH_ENGINE_UNAVAILABLE = "PATCH_ENGINE_UNAVAILABLE"
REASON_CODE_PATCH_ENGINE_OS_ERROR = "PATCH_ENGINE_OS_ERROR"
REASON_CODE_MALFORMED_DIFF = "MALFORMED_DIFF"
REASON_CODE_PATCH_CHECK_FAILED = "PATCH_CHECK_FAILED"
REASON_CODE_PATCH_APPLY_FAILED = "PATCH_APPLY_FAILED"
REASON_CODE_PATCH_APPLY_TIMEOUT = "PATCH_APPLY_TIMEOUT"
REASON_CODE_PATCH_APPLY_UNSAFE_PATH = "PATCH_APPLY_UNSAFE_PATH"
REASON_CODE_PATCH_APPLY_SANDBOX_MISSING = "PATCH_APPLY_SANDBOX_MISSING"
REASON_CODE_PATCH_APPLY_TARGET_MISSING = "PATCH_APPLY_TARGET_MISSING"
REASON_CODE_PATCH_ALREADY_APPLIED = "PATCH_ALREADY_APPLIED"


@dataclass(frozen=True)
class PatchApplyResult:
    status: str
    reason: str
    patch_path: Path
    touched_paths: list[str]
    before_hashes: dict[str, str]
    after_hashes: dict[str, str]
    snapshot_dir: Path
    created_paths: list[str]
    errors: list[str]
    reason_code: str = ""
    stdout: str = ""
    stderr: str = ""


def _resolve_git_executable() -> str | None:
    exe = shutil.which("git")
    if exe is not None:
        try:
            exe = os.path.realpath(exe)
        except OSError:
            pass
    return exe


_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$"
)

_VALID_HUNK_BODY_LINE = re.compile(r"^[ +\-\\]")
_NEWLINE_AT_EOF = re.compile(r"^\\ No newline at end of file$")


def validate_unified_diff_structure(diff_text: str) -> str | None:
    lines = diff_text.splitlines(keepends=False)
    i = 0
    n = len(lines)
    has_file_header = False
    has_hunk = False

    while i < n:
        line = lines[i]
        if line.startswith("diff --git "):
            i += 1
            continue
        if line.startswith("--- "):
            has_file_header = True
            old_path = line[4:].strip()
            path_issue = _check_path_safety(old_path)
            if path_issue:
                return path_issue
            if i + 1 >= n or not lines[i + 1].startswith("+++ "):
                return "missing_new_file_header"
            new_path = lines[i + 1][4:].strip()
            path_issue = _check_path_safety(new_path)
            if path_issue:
                return path_issue
            i += 2
            continue
        if line.startswith("+++ "):
            # orphaned +++ without ---
            return "orphan_new_file_header"
        if line.startswith("@@"):
            has_hunk = True
            m = _HUNK_HEADER_RE.match(line)
            if not m:
                return "invalid_hunk_header_format"
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1
            i += 1
            context_lines = 0
            deletion_lines = 0
            addition_lines = 0
            while i < n and not lines[i].startswith("diff --git ") and not lines[i].startswith("--- ") and not lines[i].startswith("+++ ") and not lines[i].startswith("@@"):
                body_line = lines[i]
                if not _VALID_HUNK_BODY_LINE.match(body_line) and not _NEWLINE_AT_EOF.match(body_line):
                    return "invalid_hunk_body_line"
                if body_line.startswith(" "):
                    context_lines += 1
                elif body_line.startswith("-"):
                    deletion_lines += 1
                elif body_line.startswith("+"):
                    addition_lines += 1
                elif body_line.startswith("\\"):
                    pass
                i += 1
            # old-side: context + deletion lines
            if old_count != context_lines + deletion_lines:
                return "hunk_old_count_mismatch"
            # new-side: context + addition lines
            if new_count != context_lines + addition_lines:
                return "hunk_new_count_mismatch"
            if context_lines == 0:
                return "hunk_missing_context"
            continue
        if not line.strip():
            i += 1
            continue
        # Skip lines that are valid in diffs but outside hunks
        # (e.g. index lines, new file mode, etc.)
        if line.startswith("index ") or line.startswith("new file mode ") or line.startswith("deleted file mode ") or line.startswith("old mode ") or line.startswith("new mode ") or line.startswith("copy "):
            i += 1
            continue
        # rename from/to
        if line.startswith("rename from ") or line.startswith("rename to "):
            i += 1
            continue
        i += 1

    if not has_file_header:
        return "missing_file_headers"
    if not has_hunk:
        return "missing_hunk"
    return None


def _normalize_patch_bytes(diff: str) -> bytes:
    text = str(diff).replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text.encode("utf-8")


def _normalize_patch_text(diff: str) -> str:
    return _normalize_patch_bytes(diff).decode("utf-8")


def _extract_touched_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            for raw in parts[2:4]:
                path = _strip_diff_path_prefix(raw)
                if path != "/dev/null" and path not in paths:
                    paths.append(path)
        elif line.startswith("--- ") or line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0].strip()
            path = _strip_diff_path_prefix(raw)
            if path != "/dev/null" and path not in paths:
                paths.append(path)
    return paths


def _strip_diff_path_prefix(raw: str) -> str:
    path = raw.strip().strip('"')
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _check_path_safety(path: str) -> str | None:
    if not path:
        return "empty_path"
    if path.startswith("/"):
        return "absolute_path"
    if ".." in path.split("/"):
        return "path_traversal"
    try:
        p = PureWindowsPath(path)
        if p.drive:
            return "windows_drive_path"
    except (ValueError, TypeError):
        pass
    try:
        p = PurePosixPath(path)
        if p.is_absolute():
            return "absolute_path"
    except (ValueError, TypeError):
        pass
    return None


def _check_sandbox_preflight(
    sandbox: Path,
    patch_path: Path,
    touched_paths: list[str],
    diff_text: str,
) -> str | None:
    if not sandbox.is_dir():
        return REASON_CODE_PATCH_APPLY_SANDBOX_MISSING
    if not patch_path.is_file():
        return REASON_CODE_PATCH_APPLY_TARGET_MISSING
    for rel in touched_paths:
        target = (sandbox / PurePosixPath(rel)).resolve()
        try:
            target.relative_to(sandbox.resolve())
        except ValueError:
            return REASON_CODE_PATCH_APPLY_UNSAFE_PATH
        if not target.exists():
            # New file diff is ok, but we need to verify it's actually
            # a new file diff, not a modification of a missing file.
            # We check parents exist.
            if not target.parent.exists():
                return REASON_CODE_PATCH_APPLY_TARGET_MISSING
    return None


def apply_patch_to_sandbox(
    *,
    run_dir: str | Path,
    sandbox_path: str | Path,
    attempt: int,
    unified_diff: str,
    touched_paths: list[str],
    run: RunCallable = subprocess.run,
) -> PatchApplyResult:
    run_path = Path(run_dir)
    sandbox = Path(sandbox_path).resolve()
    repairs_dir = run_path / "repairs"
    repairs_dir.mkdir(parents=True, exist_ok=True)
    patch_path = repairs_dir / f"patch_attempt_{attempt}.diff"

    patch_bytes = _normalize_patch_bytes(unified_diff)
    patch_text = patch_bytes.decode("utf-8")
    patch_path.write_bytes(patch_bytes)

    snapshot_dir = repairs_dir / "snapshots" / f"attempt_{attempt}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    before_hashes, created_paths = _snapshot_files(sandbox, snapshot_dir, touched_paths)

    # 1. Structural diff validation
    struct_issue = validate_unified_diff_structure(patch_text)
    if struct_issue is not None:
        return PatchApplyResult(
            status="REJECTED",
            reason=f"Diff structure validation failed: {struct_issue}",
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[f"Diff structure validation failed: {struct_issue}"],
            reason_code=REASON_CODE_MALFORMED_DIFF,
        )

    # 2. Resolve git executable
    git_exe = _resolve_git_executable()
    if git_exe is None:
        return PatchApplyResult(
            status="REJECTED",
            reason="Git executable not found on this system",
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=["Git not found: PATCH_ENGINE_UNAVAILABLE"],
            reason_code=REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
        )

    # 3. Sandbox/target preflight
    preflight_issue = _check_sandbox_preflight(sandbox, patch_path, touched_paths, patch_text)
    if preflight_issue is not None:
        return PatchApplyResult(
            status="REJECTED",
            reason=f"Sandbox preflight check failed: {preflight_issue}",
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[f"Sandbox preflight: {preflight_issue}"],
            reason_code=preflight_issue,
        )

    # 4. git apply --check
    check = _git_apply([git_exe, "apply", "--check", str(patch_path)], cwd=sandbox, run=run)
    if check.returncode != 0:
        if check.returncode == 127:
            reason_code = REASON_CODE_PATCH_ENGINE_UNAVAILABLE
            reason = "Git executable not found at runtime"
        elif check.returncode == 126:
            reason_code = REASON_CODE_PATCH_ENGINE_OS_ERROR
            reason = _stderr_reason(check, "Git executable could not be invoked")
        elif check.returncode == 124:
            reason_code = REASON_CODE_PATCH_APPLY_TIMEOUT
            reason = _stderr_reason(check, "git apply --check timed out")
        else:
            reason_code = REASON_CODE_PATCH_CHECK_FAILED
            reason = _stderr_reason(check, "git apply --check failed")
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[reason],
            reason_code=reason_code,
            stdout=str(check.stdout or ""),
            stderr=str(check.stderr or ""),
        )

    # 5. git apply
    applied = _git_apply([git_exe, "apply", str(patch_path)], cwd=sandbox, run=run)
    if applied.returncode != 0:
        if applied.returncode == 127:
            reason_code = REASON_CODE_PATCH_ENGINE_UNAVAILABLE
            reason = "Git executable not found at runtime"
        elif applied.returncode == 126:
            reason_code = REASON_CODE_PATCH_ENGINE_OS_ERROR
            reason = _stderr_reason(applied, "Git executable could not be invoked")
        elif applied.returncode == 124:
            reason_code = REASON_CODE_PATCH_APPLY_TIMEOUT
            reason = _stderr_reason(applied, "git apply timed out")
        else:
            reason_code = REASON_CODE_PATCH_APPLY_FAILED
            reason = _stderr_reason(applied, "git apply failed")
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[reason],
            reason_code=reason_code,
            stdout=str(applied.stdout or ""),
            stderr=str(applied.stderr or ""),
        )

    return PatchApplyResult(
        status="APPLIED",
        reason="patch applied inside sandbox",
        patch_path=patch_path,
        touched_paths=touched_paths,
        before_hashes=before_hashes,
        after_hashes=_hash_files(sandbox, touched_paths),
        snapshot_dir=snapshot_dir,
        created_paths=created_paths,
        errors=[],
        reason_code="",
        stdout=str(applied.stdout or ""),
        stderr=str(applied.stderr or ""),
    )


def check_patch_applicability(
    *,
    sandbox_path: str | Path,
    unified_diff: str,
    touched_paths: Sequence[str] | None = None,
    run_dir: str | Path | None = None,
    attempt: int | str | None = None,
    timeout_seconds: int = 60,
    run: RunCallable = subprocess.run,
) -> PatchApplyResult:
    sandbox = Path(sandbox_path).resolve()
    if run_dir is not None:
        checks_dir = Path(run_dir) / "repairs"
    else:
        checks_dir = Path(tempfile.gettempdir()) / "modernizer_patch_checks"
    checks_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(attempt or "preproposal").replace("/", "_").replace("\\", "_")
    patch_path = checks_dir / f"patch_apply_check_{suffix}.diff"

    patch_bytes = _normalize_patch_bytes(unified_diff)
    patch_text = patch_bytes.decode("utf-8")
    patch_path.write_bytes(patch_bytes)

    resolved_touched_paths = list(touched_paths or _extract_touched_paths_from_diff(patch_text))
    snapshot_dir = checks_dir
    before_hashes = _hash_files(sandbox, resolved_touched_paths) if sandbox.is_dir() else {}

    struct_issue = validate_unified_diff_structure(patch_text)
    if struct_issue is not None:
        reason = f"Diff structure validation failed: {struct_issue}"
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=[reason],
            reason_code=REASON_CODE_MALFORMED_DIFF,
        )

    git_exe = _resolve_git_executable()
    if git_exe is None:
        return PatchApplyResult(
            status="REJECTED",
            reason="Git executable not found on this system",
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=["Git not found: PATCH_ENGINE_UNAVAILABLE"],
            reason_code=REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
        )

    preflight_issue = _check_sandbox_preflight(sandbox, patch_path, resolved_touched_paths, patch_text)
    if preflight_issue is not None:
        reason = f"Sandbox preflight check failed: {preflight_issue}"
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=[reason],
            reason_code=preflight_issue,
        )

    check = _git_apply(
        [git_exe, "apply", "--check", str(patch_path)],
        cwd=sandbox,
        run=run,
        timeout_seconds=timeout_seconds,
    )
    if check.returncode != 0:
        if check.returncode == 127:
            reason_code = REASON_CODE_PATCH_ENGINE_UNAVAILABLE
            reason = "Git executable not found at runtime"
        elif check.returncode == 126:
            reason_code = REASON_CODE_PATCH_ENGINE_OS_ERROR
            reason = _stderr_reason(check, "Git executable could not be invoked")
        elif check.returncode == 124:
            reason_code = REASON_CODE_PATCH_APPLY_TIMEOUT
            reason = _stderr_reason(check, "git apply --check timed out")
        else:
            reason_code = REASON_CODE_PATCH_CHECK_FAILED
            reason = _stderr_reason(check, "git apply --check failed")
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=[],
            errors=[reason],
            reason_code=reason_code,
            stdout=str(check.stdout or ""),
            stderr=str(check.stderr or ""),
        )

    return PatchApplyResult(
        status="CHECKED",
        reason="patch applies cleanly inside sandbox",
        patch_path=patch_path,
        touched_paths=resolved_touched_paths,
        before_hashes=before_hashes,
        after_hashes={},
        snapshot_dir=snapshot_dir,
        created_paths=[],
        errors=[],
        reason_code="",
        stdout=str(check.stdout or ""),
        stderr=str(check.stderr or ""),
    )


def apply_patch_to_sandbox_direct(
    *,
    run_dir: str | Path,
    sandbox_path: str | Path,
    attempt: int,
    unified_diff: str,
    touched_paths: list[str] | None = None,
    run: RunCallable = subprocess.run,
) -> PatchApplyResult:
    """Apply patch to sandbox without structural validation or git apply --check.

    AMF-252: Direct apply for reviewer-accepted diffs. Skips
    validate_unified_diff_structure and git apply --check.
    The patch is persisted from the reviewer's reviewed_diff as-is.
    Uses shell=False and argument list style for all command execution.
    """
    run_path = Path(run_dir)
    sandbox = Path(sandbox_path).resolve()
    repairs_dir = run_path / "repairs"
    repairs_dir.mkdir(parents=True, exist_ok=True)
    patch_path = repairs_dir / f"patch_attempt_{attempt}_direct.diff"

    patch_bytes = _normalize_patch_bytes(unified_diff)
    patch_text = patch_bytes.decode("utf-8")
    patch_path.write_bytes(patch_bytes)

    extract_paths = _extract_touched_paths_from_diff(patch_text)
    resolved_touched_paths = touched_paths or extract_paths

    snapshot_dir = repairs_dir / "snapshots" / f"attempt_{attempt}_direct"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    before_hashes, created_paths = _snapshot_files(sandbox, snapshot_dir, resolved_touched_paths)

    git_exe = _resolve_git_executable()
    if git_exe is None:
        return PatchApplyResult(
            status="REJECTED",
            reason="Git executable not found on this system",
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=["Git not found: PATCH_ENGINE_UNAVAILABLE"],
            reason_code=REASON_CODE_PATCH_ENGINE_UNAVAILABLE,
        )

    preflight_issue = _check_sandbox_preflight(sandbox, patch_path, resolved_touched_paths, patch_text)
    if preflight_issue is not None:
        return PatchApplyResult(
            status="REJECTED",
            reason=f"Sandbox preflight check failed: {preflight_issue}",
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[f"Sandbox preflight: {preflight_issue}"],
            reason_code=preflight_issue,
        )

    applied = _git_apply([git_exe, "apply", str(patch_path)], cwd=sandbox, run=run)
    if applied.returncode != 0:
        if applied.returncode == 127:
            reason_code = REASON_CODE_PATCH_ENGINE_UNAVAILABLE
            reason = "Git executable not found at runtime"
        elif applied.returncode == 126:
            reason_code = REASON_CODE_PATCH_ENGINE_OS_ERROR
            reason = _stderr_reason(applied, "Git executable could not be invoked")
        elif applied.returncode == 124:
            reason_code = REASON_CODE_PATCH_APPLY_TIMEOUT
            reason = _stderr_reason(applied, "git apply timed out")
        else:
            # Normal git apply failure — run post-failure reverse classifier.
            # git apply --reverse --check is read-only (--check flag) and
            # detects whether the patch changes are already present.
            reverse_check = _git_apply(
                [git_exe, "apply", "--reverse", "--check", str(patch_path)],
                cwd=sandbox, run=run,
            )
            if reverse_check.returncode == 0:
                return PatchApplyResult(
                    status="ALREADY_APPLIED",
                    reason="Patch changes are already present in sandbox; validation will run.",
                    patch_path=patch_path,
                    touched_paths=resolved_touched_paths,
                    before_hashes=before_hashes,
                    after_hashes=_hash_files(sandbox, resolved_touched_paths),
                    snapshot_dir=snapshot_dir,
                    created_paths=created_paths,
                    errors=[],
                    reason_code=REASON_CODE_PATCH_ALREADY_APPLIED,
                    stdout=str(applied.stdout or ""),
                    stderr=str(applied.stderr or ""),
                )
            reason_code = REASON_CODE_PATCH_APPLY_FAILED
            reason = _stderr_reason(applied, "git apply failed")
        return PatchApplyResult(
            status="REJECTED",
            reason=reason,
            patch_path=patch_path,
            touched_paths=resolved_touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[reason],
            reason_code=reason_code,
            stdout=str(applied.stdout or ""),
            stderr=str(applied.stderr or ""),
        )

    return PatchApplyResult(
        status="APPLIED",
        reason="patch applied inside sandbox (direct)",
        patch_path=patch_path,
        touched_paths=resolved_touched_paths,
        before_hashes=before_hashes,
        after_hashes=_hash_files(sandbox, resolved_touched_paths),
        snapshot_dir=snapshot_dir,
        created_paths=created_paths,
        errors=[],
        reason_code="",
        stdout=str(applied.stdout or ""),
        stderr=str(applied.stderr or ""),
    )


def rollback_patch(
    *,
    sandbox_path: str | Path,
    snapshot_dir: str | Path,
    touched_paths: list[str],
    created_paths: list[str],
) -> tuple[bool, str]:
    sandbox = Path(sandbox_path).resolve()
    snapshot = Path(snapshot_dir)
    try:
        for rel in touched_paths:
            destination = sandbox / PurePosixPath(rel)
            backup = snapshot / rel
            if rel in created_paths:
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                continue
            if backup.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, destination)
            elif destination.exists():
                destination.unlink()
    except OSError as exc:
        return False, str(exc)
    return True, "rollback restored sandbox snapshot"


def _snapshot_files(sandbox: Path, snapshot_dir: Path, paths: list[str]) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    created: list[str] = []
    for rel in paths:
        source = sandbox / PurePosixPath(rel)
        if source.is_file():
            target = snapshot_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            hashes[rel] = _sha256(source)
        else:
            hashes[rel] = ""
            created.append(rel)
    return hashes, created


def _hash_files(sandbox: Path, paths: list[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in paths:
        path = sandbox / PurePosixPath(rel)
        hashes[rel] = _sha256(path) if path.is_file() else ""
    return hashes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_apply(
    command: list[str],
    *,
    cwd: Path,
    run: RunCallable,
    timeout_seconds: int = 60,
) -> subprocess.CompletedProcess:
    try:
        return run(command, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=timeout_seconds)
    except FileNotFoundError:
        return subprocess.CompletedProcess(command, 127, stdout="", stderr="Git executable not found")
    except OSError as exc:
        return subprocess.CompletedProcess(command, 126, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=str(exc))


def _stderr_reason(result: subprocess.CompletedProcess, fallback: str) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text[-1000:] if text else fallback
