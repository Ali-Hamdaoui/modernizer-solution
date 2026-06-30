from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable


RunCallable = Callable[..., subprocess.CompletedProcess]
GIT_CMD_ENV = "AI_MIGRATION_GIT_CMD"
GIT_NOT_AVAILABLE = "PATCH_APPLY_GIT_NOT_AVAILABLE"
_COMMON_WINDOWS_GIT_PATHS = (
    Path(r"C:\Program Files\Git\cmd\git.exe"),
    Path(r"C:\Program Files\Git\bin\git.exe"),
)


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
    patch_text = unified_diff if unified_diff.endswith("\n") else unified_diff + "\n"
    patch_path.write_text(patch_text, encoding="utf-8")

    snapshot_dir = repairs_dir / "snapshots" / f"attempt_{attempt}"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    before_hashes, created_paths = _snapshot_files(sandbox, snapshot_dir, touched_paths)

    git_cmd, git_error = _resolve_git_executable(run=run)
    if git_cmd is None:
        return PatchApplyResult(
            status="REJECTED",
            reason=git_error,
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[git_error],
        )

    check = _git_apply([git_cmd, "apply", "--check", str(patch_path)], cwd=sandbox, run=run)
    if check.returncode != 0:
        return PatchApplyResult(
            status="REJECTED",
            reason=_stderr_reason(check, "git apply --check failed"),
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[_stderr_reason(check, "git apply --check failed")],
        )

    applied = _git_apply([git_cmd, "apply", str(patch_path)], cwd=sandbox, run=run)
    if applied.returncode != 0:
        return PatchApplyResult(
            status="FAILED",
            reason=_stderr_reason(applied, "git apply failed"),
            patch_path=patch_path,
            touched_paths=touched_paths,
            before_hashes=before_hashes,
            after_hashes={},
            snapshot_dir=snapshot_dir,
            created_paths=created_paths,
            errors=[_stderr_reason(applied, "git apply failed")],
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
    )


def validate_patch_artifact(
    *,
    patch_path: str | Path,
    cwd: str | Path,
    run: RunCallable = subprocess.run,
) -> tuple[bool, str]:
    patch_file = Path(patch_path)
    workdir = Path(cwd).resolve()
    git_cmd, git_error = _resolve_git_executable(run=run)
    if git_cmd is None:
        return False, git_error
    check = _git_apply([git_cmd, "apply", "--check", str(patch_file)], cwd=workdir, run=run)
    if check.returncode != 0:
        return False, _stderr_reason(check, "git apply --check failed")
    return True, ""


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


def _git_apply(command: list[str], *, cwd: Path, run: RunCallable) -> subprocess.CompletedProcess:
    try:
        return run(command, cwd=str(cwd), capture_output=True, text=True, check=False, timeout=60)
    except OSError as exc:
        return subprocess.CompletedProcess(command, 127, stdout="", stderr=f"{GIT_NOT_AVAILABLE}: {type(exc).__name__}")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(command, 124, stdout=exc.stdout or "", stderr=str(exc))


def _resolve_git_executable(*, run: RunCallable) -> tuple[str | None, str]:
    for candidate in _git_candidates():
        validation = _validate_git(candidate, run=run)
        if validation.returncode == 0:
            return candidate, ""
    return None, f"{GIT_NOT_AVAILABLE}: git executable not found or not runnable"


def _git_candidates() -> list[str]:
    candidates: list[str] = []
    configured = os.environ.get(GIT_CMD_ENV, "").strip()
    if configured:
        candidates.append(configured)
    path_git = shutil.which("git")
    if path_git:
        candidates.append(path_git)
    for path in _COMMON_WINDOWS_GIT_PATHS:
        if path.is_file():
            candidates.append(str(path))
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(candidate)
    return deduped


def _validate_git(candidate: str, *, run: RunCallable) -> subprocess.CompletedProcess:
    try:
        return run([candidate, "--version"], capture_output=True, text=True, check=False, timeout=10)
    except OSError:
        return subprocess.CompletedProcess([candidate, "--version"], 127, stdout="", stderr="")
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess([candidate, "--version"], 124, stdout=exc.stdout or "", stderr="")


def _stderr_reason(result: subprocess.CompletedProcess, fallback: str) -> str:
    text = (result.stderr or result.stdout or "").strip()
    return text[-1000:] if text else fallback
