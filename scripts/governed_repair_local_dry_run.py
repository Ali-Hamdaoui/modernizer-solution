"""Guarded local-project dry-run harness.

The legacy project path is supplied at runtime as:
<USER_LEGACY_PROJECT_PATH>
"""

from __future__ import annotations

import argparse
import json
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


def run_local_project_dry_run(
    *,
    legacy_project_path: str,
    sandbox_root: str | None = None,
    real_validation: bool = False,
    approve: bool = False,
    output: str | None = None,
    keep_sandbox: bool = False,
    validation_runner: ValidationRunner = run_validation_after_patch,
) -> dict[str, Any]:
    legacy = _resolve_legacy_project_path(legacy_project_path)
    sandbox, temp_created = _resolve_sandbox_root(legacy, sandbox_root)
    run_dir = sandbox / ".governed-dry-run"
    run_dir.mkdir(parents=True, exist_ok=True)

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

    if real_validation:
        run_id = f"governed-dry-run-{uuid.uuid4().hex[:12]}"
        try:
            validation = validation_runner(
                run_id=run_id,
                run_dir=run_dir,
                sandbox_path=sandbox,
                attempt=1,
                h2_required=False,
                h2_enabled=False,
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
        approve=args.approve,
        output=args.output,
        keep_sandbox=args.keep_sandbox,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
