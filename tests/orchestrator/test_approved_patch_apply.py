from __future__ import annotations

import json
from pathlib import Path

from migration_factory.contracts.migration import initialize_ledger, load_ledger
from migration_factory.remediation.approved_patch_apply import apply_approved_behavioral_patch


def test_approved_patch_applies_to_sandbox_test_file(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, target = _workspace_with_patch(
        tmp_path,
        relative_target="src/test/java/com/example/DemoTest.java",
        original_text="package com.example;\nclass DemoTest {}\n",
        updated_text="package com.example;\nimport org.springframework.test.context.bean.override.mockito.MockitoBean;\nclass DemoTest {\n    @MockitoBean\n    Helper helper;\n}\n",
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved for sandbox-only remediation",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "applied"
    assert "@MockitoBean" in target.read_text(encoding="utf-8")


def test_patch_outside_sandbox_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "DemoTest.java"
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target="../outside/DemoTest.java",
        original_text="class DemoTest {}\n",
        updated_text="class DemoTest { int x; }\n",
        absolute_target=outside,
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert result.payload["status"] == "rejected_patch_outside_sandbox"


def test_patch_touching_legacy_path_is_rejected(tmp_path: Path) -> None:
    legacy_file = tmp_path / "legacy" / "src/test/java/com/example/DemoTest.java"
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target=str(legacy_file),
        original_text="class DemoTest {}\n",
        updated_text="class DemoTest { int x; }\n",
        absolute_target=legacy_file,
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert result.payload["status"] == "rejected_patch_outside_sandbox"


def test_patch_touching_production_source_is_rejected_by_default(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target="src/main/java/com/example/Demo.java",
        original_text="package com.example;\nclass Demo {}\n",
        updated_text="package com.example;\nclass Demo { int x; }\n",
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert result.payload["status"] == "rejected_production_source"


def test_patch_touching_pom_is_rejected_by_default(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target="pom.xml",
        original_text="<project></project>\n",
        updated_text="<project><name>x</name></project>\n",
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert result.payload["status"] == "rejected_pom_xml"


def test_missing_approval_rejects(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target="src/test/java/com/example/DemoTest.java",
        original_text="class DemoTest {}\n",
        updated_text="class DemoTest { int x; }\n",
    )

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="",
        approval_comment="",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert result.payload["status"] == "rejected_missing_approval"


def test_already_applied_patch_handled_safely(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, target = _workspace_with_patch(
        tmp_path,
        relative_target="src/test/java/com/example/DemoTest.java",
        original_text="class DemoTest {}\n",
        updated_text="class DemoTest { int x; }\n",
    )

    first = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )
    second = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved again",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
    )

    assert first.payload["status"] == "applied"
    assert second.payload["status"] == "already_applied"
    assert target.read_text(encoding="utf-8") == "class DemoTest { int x; }\n"


def test_ledger_records_approved_behavioral_patch_and_rerun(tmp_path: Path) -> None:
    run_dir, sandbox, patch_path, _ = _workspace_with_patch(
        tmp_path,
        relative_target="src/test/java/com/example/DemoTest.java",
        original_text="class DemoTest {}\n",
        updated_text="class DemoTest { int x; }\n",
    )

    class Completed:
        returncode = 0
        stdout = "ok\nline2\n"
        stderr = ""

    result = apply_approved_behavioral_patch(
        run_dir=run_dir,
        patch_proposal_path=patch_path,
        approved_by="tester",
        approval_comment="approved",
        failed_unit_id="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
        validation_command=["python", "-c", "print('ok')"],
        subprocess_runner=lambda *args, **kwargs: Completed(),
    )

    ledger = load_ledger(sandbox / ".migration" / "ledger.json")
    assert result.payload["rerun"]["attempted"] is True
    assert ledger["last_approved_behavioral_patch"]["approved_by"] == "tester"
    assert ledger["last_approved_behavioral_patch"]["rerun"]["exit_code"] == 0


def test_approved_patch_apply_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/approved_patch_apply.py").read_text(encoding="utf-8").lower()

    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _workspace_with_patch(
    tmp_path: Path,
    *,
    relative_target: str,
    original_text: str,
    updated_text: str,
    absolute_target: Path | None = None,
) -> tuple[Path, Path, Path, Path]:
    run_dir = tmp_path / "run"
    remediation = run_dir / "remediation"
    sandbox = run_dir / "workspaces" / "sandbox"
    orchestration = run_dir / "orchestration"
    final = run_dir / "final"
    legacy = tmp_path / "legacy"
    for directory in (remediation, sandbox / ".migration", orchestration, final, legacy):
        directory.mkdir(parents=True, exist_ok=True)
    target = absolute_target or (sandbox / relative_target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(original_text, encoding="utf-8")
    patch_path = remediation / "proposal.patch"
    patch_path.write_text(_make_patch(target, original_text, updated_text), encoding="utf-8")
    (orchestration / "orchestration_summary.json").write_text(json.dumps({"artifact_refs": {}, "run_id": "run-001"}) + "\n", encoding="utf-8")
    (final / "migration_report.json").write_text(json.dumps({"artifact_refs": {}, "run_id": "run-001"}) + "\n", encoding="utf-8")
    (final / "migration_summary.md").write_text("# Migration Summary\n", encoding="utf-8")
    initialize_ledger(
        sandbox / ".migration" / "ledger.json",
        migration_id="run-001",
        migration_name="profile",
        total_units=1,
        target_path=sandbox,
    )
    ledger = load_ledger(sandbox / ".migration" / "ledger.json")
    ledger["current_unit"] = "spring-boot-3-5-14"
    ledger["blocked_unit"] = "spring-boot-3-5-14"
    ledger["status"] = "blocked"
    ledger["units"]["spring-boot-3-5-14"] = {"id": "spring-boot-3-5-14"}
    (sandbox / ".migration" / "ledger.json").write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    return run_dir, sandbox, patch_path, target


def _make_patch(target: Path, original: str, updated: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile=f"a/{target.as_posix()}",
        tofile=f"b/{target.as_posix()}",
        lineterm="",
    )
    return "\n".join(diff) + "\n"
