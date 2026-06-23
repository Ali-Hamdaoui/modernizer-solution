"""Guarded local-project dry-run harness.

The legacy project path is supplied at runtime as:
<USER_LEGACY_PROJECT_PATH>
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable

from migration_factory.repair_loop.validation_runner import (
    ValidationResult,
    run_validation_after_patch,
)


ValidationRunner = Callable[..., ValidationResult]
WORKFLOW_STATUS_READY = "harness_ready_manual_backend_flow_required"
VALIDATION_MODE_STUB = "stub"
VALIDATION_MODE_REAL = "real"
DEFAULT_JAVA_ENV_NAME = "JAVA_HOME"


class GovernedRepairDryRunError(ValueError):
    """Raised when the local-project harness input is unsafe or invalid."""


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _checksum_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        snapshot[rel] = _sha256(path)
    return snapshot


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_legacy_project_path(raw: str) -> Path:
    if not str(raw or "").strip():
        raise GovernedRepairDryRunError("legacy project path is required")
    legacy = Path(raw).expanduser().resolve()
    if not legacy.exists():
        raise GovernedRepairDryRunError(f"legacy project path does not exist: {legacy}")
    if not legacy.is_dir():
        raise GovernedRepairDryRunError(f"legacy project path is not a directory: {legacy}")
    if not any(path.is_file() for path in legacy.rglob("*")):
        raise GovernedRepairDryRunError("legacy project path is empty")
    return legacy


def _resolve_sandbox_root(legacy: Path, sandbox_root: str | None) -> tuple[Path, bool]:
    if sandbox_root:
        sandbox = Path(sandbox_root).expanduser().resolve()
        if _is_within(sandbox, legacy):
            raise GovernedRepairDryRunError("sandbox root must be outside the legacy project")
        if sandbox.exists() and sandbox.is_file():
            raise GovernedRepairDryRunError(f"sandbox root is not a directory: {sandbox}")
        if sandbox.exists() and any(sandbox.iterdir()):
            raise GovernedRepairDryRunError(f"sandbox root must be empty: {sandbox}")
        sandbox.mkdir(parents=True, exist_ok=True)
        return sandbox, False

    sandbox = Path(tempfile.mkdtemp(prefix="modernizer-governed-dryrun-")).resolve()
    return sandbox, True


def _safe_display_path(path: Path) -> str:
    return path.name or "<redacted>"


def _resolve_java_home(java_home: str | None) -> Path | None:
    if java_home is None:
        return None
    if not str(java_home).strip():
        raise GovernedRepairDryRunError("java home is required when provided")
    resolved = Path(java_home).expanduser().resolve()
    if not resolved.exists():
        raise GovernedRepairDryRunError(f"java home does not exist: {resolved}")
    if not resolved.is_dir():
        raise GovernedRepairDryRunError(f"java home is not a directory: {resolved}")
    java_exe = resolved / "bin" / "java.exe"
    if not java_exe.is_file():
        raise GovernedRepairDryRunError(f"java home is missing bin/java.exe: {resolved}")
    return resolved


def _parse_project_java_version(legacy: Path) -> str | None:
    pom = legacy / "pom.xml"
    if not pom.is_file():
        return None
    text = pom.read_text(encoding="utf-8", errors="ignore")
    for pattern in (
        r"<java\.version>\s*([^<\s]+)\s*</java\.version>",
        r"<maven\.compiler\.source>\s*([^<\s]+)\s*</maven\.compiler\.source>",
        r"<maven\.compiler\.target>\s*([^<\s]+)\s*</maven\.compiler\.target>",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _parse_java_major(version_output: str) -> int | None:
    match = re.search(r'version "([^"]+)"', version_output)
    if not match:
        match = re.search(r"\b(?:openjdk|java)\s+(\d+(?:\.\d+)*)", version_output, re.IGNORECASE)
    if not match:
        return None
    version = match.group(1)
    if version.startswith("1."):
        parts = version.split(".")
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    major = version.split(".", 1)[0]
    return int(major) if major.isdigit() else None


def _probe_java_toolchain(java_home: Path | None) -> dict[str, Any]:
    java_executable = java_home / "bin" / "java.exe" if java_home else Path("java")
    env = None
    if java_home is not None:
        env = os.environ.copy()
        env[DEFAULT_JAVA_ENV_NAME] = str(java_home)
        env["PATH"] = str(java_home / "bin") + os.pathsep + env.get("PATH", "")
    try:
        completed = subprocess.run(
            [str(java_executable), "-version"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    except OSError as exc:
        return {
            "java_home_used": str(java_home) if java_home else "",
            "java_executable": str(java_executable),
            "java_version_output": str(exc),
            "java_major_version": None,
            "exit_code": 1,
        }
    version_output = "\n".join([*(completed.stdout or "").splitlines(), *(completed.stderr or "").splitlines()]).strip()
    return {
        "java_home_used": str(java_home) if java_home else "",
        "java_executable": str(java_executable),
        "java_version_output": version_output,
        "java_major_version": _parse_java_major(version_output),
        "exit_code": completed.returncode,
    }


@contextlib.contextmanager
def _temporary_java_home(java_home: Path | None):
    if java_home is None:
        yield
        return

    original = os.environ.get(DEFAULT_JAVA_ENV_NAME)
    os.environ[DEFAULT_JAVA_ENV_NAME] = str(java_home)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(DEFAULT_JAVA_ENV_NAME, None)
        else:
            os.environ[DEFAULT_JAVA_ENV_NAME] = original


def run_local_project_dry_run(
    *,
    legacy_project_path: str,
    sandbox_root: str | None = None,
    real_validation: bool = False,
    java_home: str | None = None,
    approve: bool = False,
    output: str | None = None,
    keep_sandbox: bool = False,
    validation_runner: ValidationRunner = run_validation_after_patch,
) -> dict[str, Any]:
    legacy = _resolve_legacy_project_path(legacy_project_path)
    sandbox, temp_created = _resolve_sandbox_root(legacy, sandbox_root)
    run_dir = sandbox / ".governed-dry-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    resolved_java_home = _resolve_java_home(java_home)

    legacy_before = _checksum_tree(legacy)
    shutil.copytree(legacy, sandbox, dirs_exist_ok=True)
    legacy_after = _checksum_tree(legacy)
    if legacy_before != legacy_after:
        raise GovernedRepairDryRunError("legacy project changed during dry run")

    report: dict[str, Any] = {
        "workflow_status": WORKFLOW_STATUS_READY,
        "legacy_project_path_display": _safe_display_path(legacy),
        "sandbox_path": str(sandbox),
        "legacy_checksum_before": legacy_before,
        "legacy_checksum_after": legacy_after,
        "legacy_unchanged": True,
        "approval_requested": bool(approve),
        "apply_attempted": False,
        "real_validation_requested": bool(real_validation),
        "validation_mode": VALIDATION_MODE_REAL if real_validation else VALIDATION_MODE_STUB,
        "java_home_requested": str(resolved_java_home) if resolved_java_home else "",
        "java_home_used": "",
        "java_executable": "",
        "java_version_output": "",
        "project_declared_java_version": _parse_project_java_version(legacy) or "",
        "toolchain_mismatch": False,
        "toolchain_warning": "",
        "proposal_status": "not_executed",
        "reviewer_status": "not_executed",
        "verification_status": "not_available",
        "verification_build_status": "",
        "verification_test_status": "",
        "verification_h2_status": "",
        "verification_artifact_refs": {},
        "verification_failure_classification_ref": "",
        "validation_error": "",
        "governance": {
            "auto_apply": False,
            "approval_bypass": False,
            "source_mutated": False,
            "sandbox_only": True,
            "external_llm_invoked": False,
            "llm_invoked_during_apply_or_verification": False,
        },
        "cleanup_performed": False,
        "sandbox_created": temp_created,
    }

    java_probe = _probe_java_toolchain(resolved_java_home)
    report["java_home_used"] = java_probe["java_home_used"]
    report["java_executable"] = java_probe["java_executable"]
    report["java_version_output"] = java_probe["java_version_output"]
    declared_java = report["project_declared_java_version"]
    detected_major = java_probe["java_major_version"]
    declared_major = None
    if declared_java:
        try:
            declared_major = int(str(declared_java).split(".", 1)[0])
        except ValueError:
            declared_major = None
    if declared_major is not None and detected_major is not None and declared_major != detected_major:
        report["toolchain_mismatch"] = True
        report["toolchain_warning"] = (
            f"Project declares Java {declared_java} but selected Java is {detected_major}."
        )

    if real_validation:
        run_id = f"governed-dry-run-{uuid.uuid4().hex[:12]}"
        with _temporary_java_home(resolved_java_home):
            try:
                validation = validation_runner(
                    run_id=run_id,
                    run_dir=run_dir,
                    sandbox_path=sandbox,
                    attempt=1,
                    h2_required=False,
                    h2_enabled=False,
                    java_home=str(resolved_java_home) if resolved_java_home else None,
                )
            except Exception as exc:  # pragma: no cover - guarded report path
                report["verification_status"] = "failed"
                report["validation_error"] = str(exc)
            else:
                report["verification_status"] = "passed" if validation.passed else "failed"
                report["verification_build_status"] = validation.build_status
                report["verification_test_status"] = validation.test_status
                report["verification_h2_status"] = validation.h2_status
                report["verification_artifact_refs"] = dict(validation.artifact_refs)

    if output:
        output_path = Path(output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not keep_sandbox:
        shutil.rmtree(sandbox, ignore_errors=True)
        report["cleanup_performed"] = True

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="governed_repair_local_dry_run",
        description="Prepare a guarded local-project sandbox dry run without mutating the original project.",
    )
    parser.add_argument(
        "--legacy-project-path",
        required=True,
        help="Path to the user-provided legacy project root.",
    )
    parser.add_argument(
        "--sandbox-root",
        help="Optional sandbox root directory. Defaults to a temporary directory outside the legacy tree.",
    )
    parser.add_argument(
        "--real-validation",
        action="store_true",
        help="Run the existing validation runner against the sandbox copy.",
    )
    parser.add_argument(
        "--java-home",
        help="Optional Java home to use for validation. Must contain bin/java.exe.",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Simulate explicit human approval in the dry-run report.",
    )
    parser.add_argument(
        "--output",
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--keep-sandbox",
        action="store_true",
        help="Keep the sandbox copy after the run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_local_project_dry_run(
        legacy_project_path=args.legacy_project_path,
        sandbox_root=args.sandbox_root,
        real_validation=args.real_validation,
        java_home=args.java_home,
        approve=args.approve,
        output=args.output,
        keep_sandbox=args.keep_sandbox,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
