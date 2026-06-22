from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.governed_repair_local_dry_run import (
    GovernedRepairDryRunError,
    run_local_project_dry_run,
)


def _write_legacy_project(root: Path) -> Path:
    legacy = root / "legacy-project"
    (legacy / "src" / "main" / "java" / "com" / "example").mkdir(parents=True, exist_ok=True)
    (legacy / "pom.xml").write_text(
        "<project><modelVersion>4.0.0</modelVersion></project>\n",
        encoding="utf-8",
    )
    (legacy / "src" / "main" / "java" / "com" / "example" / "App.java").write_text(
        "package com.example;\n\npublic class App {}\n",
        encoding="utf-8",
    )
    return legacy


def test_missing_legacy_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(GovernedRepairDryRunError, match="does not exist"):
        run_local_project_dry_run(legacy_project_path=str(tmp_path / "missing"))


def test_non_directory_legacy_path_is_rejected(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.txt"
    legacy.write_text("nope", encoding="utf-8")
    with pytest.raises(GovernedRepairDryRunError, match="not a directory"):
        run_local_project_dry_run(legacy_project_path=str(legacy))


def test_sandbox_inside_legacy_is_rejected(tmp_path: Path) -> None:
    legacy = _write_legacy_project(tmp_path)
    sandbox = legacy / "sandbox"
    with pytest.raises(GovernedRepairDryRunError, match="outside the legacy project"):
        run_local_project_dry_run(
            legacy_project_path=str(legacy),
            sandbox_root=str(sandbox),
        )


def test_stub_mode_preserves_legacy_and_reports_governance(tmp_path: Path) -> None:
    legacy = _write_legacy_project(tmp_path)
    report_path = tmp_path / "report.json"

    report = run_local_project_dry_run(
        legacy_project_path=str(legacy),
        sandbox_root=str(tmp_path / "sandbox"),
        output=str(report_path),
        keep_sandbox=True,
    )

    assert report_path.exists()
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["workflow_status"] == "harness_ready_manual_backend_flow_required"
    assert saved["approval_requested"] is False
    assert saved["apply_attempted"] is False
    assert saved["real_validation_requested"] is False
    assert saved["validation_mode"] == "stub"
    assert saved["verification_status"] == "not_available"
    assert saved["legacy_unchanged"] is True
    assert report["legacy_checksum_before"] == report["legacy_checksum_after"]
    assert report["governance"] == {
        "auto_apply": False,
        "approval_bypass": False,
        "source_mutated": False,
        "sandbox_only": True,
        "external_llm_invoked": False,
        "llm_invoked_during_apply_or_verification": False,
    }
    sandbox = Path(report["sandbox_path"])
    assert sandbox.exists()
    assert legacy not in sandbox.parents

    shutil.rmtree(sandbox, ignore_errors=True)


def test_real_validation_is_opt_in(tmp_path: Path) -> None:
    legacy = _write_legacy_project(tmp_path)
    called: list[dict[str, object]] = []

    def fake_validation_runner(**kwargs):
        called.append(kwargs)
        from migration_factory.repair_loop.validation_runner import ValidationResult

        return ValidationResult(
            passed=True,
            build_status="BUILD_PASSED_IN_SANDBOX",
            test_status="TEST_PASSED",
            h2_status="H2_STARTUP_SKIPPED",
            validation_commands=[["mvn", "test"]],
            artifact_refs={"repair_test_summary": str(tmp_path / "summary.json")},
            warnings=[],
            errors=[],
        )

    report = run_local_project_dry_run(
        legacy_project_path=str(legacy),
        sandbox_root=str(tmp_path / "sandbox-real"),
        real_validation=True,
        approve=True,
        keep_sandbox=True,
        validation_runner=fake_validation_runner,
    )

    assert called
    assert report["approval_requested"] is True
    assert report["apply_attempted"] is False
    assert report["real_validation_requested"] is True
    assert report["validation_mode"] == "real"
    assert report["verification_status"] == "passed"
    assert report["verification_build_status"] == "BUILD_PASSED_IN_SANDBOX"
    assert report["verification_test_status"] == "TEST_PASSED"
    assert report["verification_artifact_refs"]["repair_test_summary"].endswith("summary.json")

    shutil.rmtree(Path(report["sandbox_path"]), ignore_errors=True)


def test_placeholder_only_in_docs_and_script() -> None:
    script_text = Path("scripts/governed_repair_local_dry_run.py").read_text(encoding="utf-8")
    runbook_text = Path("docs/user-local-project-governed-repair-dry-run.md").read_text(encoding="utf-8")
    assert "<USER_LEGACY_PROJECT_PATH>" in script_text
    assert "<USER_LEGACY_PROJECT_PATH>" in runbook_text
    assert "C:\\Users\\" not in script_text
    assert "C:\\Users\\" not in runbook_text
