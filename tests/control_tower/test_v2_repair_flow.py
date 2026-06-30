"""Tests for V2 repair/proposal flow."""

from __future__ import annotations

import json
import shutil
import subprocess
import sqlite3
from pathlib import Path

import pytest

import migration_factory.control_tower.application.v2_repair_flow as v2_repair_flow
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.repair_loop.patch_apply import PatchApplyResult
from migration_factory.repair_loop.rule_registry import evaluate_rule
from migration_factory.repair_loop.validation_runner import ValidationResult
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
    V2MigrationJobRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2MigrationSetupRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2SandboxActionRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
    SqliteV2ReviewerRepository,
)
from migration_factory.repair_loop.patch_apply import (
    GIT_NOT_AVAILABLE,
    apply_patch_to_sandbox,
    validate_patch_artifact,
)


def test_create_proposal() -> None:
    service = V2RepairFlowService()
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Compilation failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency to pom.xml",
        affected_paths=("pom.xml",),
    )
    assert proposal.status == "draft"
    assert proposal.command_id == "cmd-1"
    assert proposal.proposal_checksum


def test_create_patch_backed_proposal_writes_artifacts_without_applying(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "class App {\n"
        "  private static final int CONTROLLED_REPAIR_FAILURE = doesNotCompile;\n"
        "}\n"
    )
    target.write_text(original, encoding="utf-8")

    proposal = service.create_patch_backed_proposal(
        command_id="cmd-1",
        failure_summary="cannot find symbol variable doesNotCompile",
        hypothesis="Undefined controlled symbol",
        patch_summary="Remove controlled undefined symbol",
        affected_paths=(target_rel,),
    )
    body = service.proposal_to_dict(proposal)

    assert target.read_text(encoding="utf-8") == original
    assert body["target_files"][0]["relative_path"] == target_rel
    assert body["target_files"][0]["before_checksum"].startswith("sha256:")
    assert body["target_files"][0]["proposed_checksum"].startswith("sha256:")
    assert body["repair_artifact"]["unified_diff"].startswith("diff --git")
    assert "-  private static final int CONTROLLED_REPAIR_FAILURE = doesNotCompile;" in body["repair_artifact"]["unified_diff"]
    assert "+  private static final int CONTROLLED_REPAIR_FAILURE = 0;" in body["repair_artifact"]["unified_diff"]
    assert Path(body["repair_artifact"]["patch_path"]).is_file()
    assert body["failure_evidence"]["diagnostic_line"] == "cannot find symbol variable doesNotCompile"
    assert body["verification_plan"]["command"] == ["mvn", "-q", "-DskipTests", "compile"]
    assert body["verification_plan"]["cwd"] == str(sandbox)
    assert body["verification_plan"]["llm_during_verification"] is False
    assert body["containment"]["all_targets_under_sandbox"] is True
    assert body["containment"]["legacy_target_present"] is False


def test_create_import_package_patch_backed_proposal_is_gate_compatible(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "package com.example;\n\n"
        "import javax.validation.Valid;\n\n"
        "class App {\n"
        "  @Valid Object value;\n"
        "}\n"
    )
    target.write_text(original, encoding="utf-8")

    proposal = service.create_patch_backed_proposal(
        command_id="cmd-1",
        failure_summary="[ERROR] package javax.validation does not exist",
        hypothesis="Controlled namespace mismatch",
        patch_summary="Repair import namespace",
        affected_paths=(target_rel,),
    )
    body = service.proposal_to_dict(proposal)
    diff = body["repair_artifact"]["unified_diff"]

    assert target.read_text(encoding="utf-8") == original
    assert body["repair_family"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
    assert body["deterministic_rule_id"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
    assert body["target_files"][0]["relative_path"] == target_rel
    assert body["target_files"][0]["before_checksum"].startswith("sha256:")
    assert body["target_files"][0]["repair_family"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
    assert diff.startswith("diff --git")
    assert "-import javax.validation.Valid;" in diff
    assert "+import jakarta.validation.Valid;" in diff
    assert "  @Valid Object value;" not in "".join(
        line for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )
    assert Path(body["repair_artifact"]["patch_path"]).is_file()
    assert body["failure_evidence"]["diagnostic_line"] == "[ERROR] package javax.validation does not exist"
    assert body["verification_plan"]["command"] == ["mvn", "-q", "-DskipTests", "compile"]
    assert body["verification_plan"]["llm_during_verification"] is False

    decision = evaluate_rule(
        rule_id="JAKARTA_IMPORT_MECHANICAL_SOURCE",
        sandbox_path=sandbox,
        touched_paths=[target_rel],
        unified_diff=diff,
    )
    assert decision.allowed is True


def test_generated_import_package_patch_passes_git_apply_check_and_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git = _git_binary()
    if git is None:
        pytest.skip("git unavailable")
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    original = (
        "package com.example;\n\n"
        "import javax.validation.Valid;\n\n"
        "class App {\n"
        "  @Valid Object value;\n"
        "}\n"
    )
    target.write_text(original, encoding="utf-8")
    _init_git_repo(sandbox)

    proposal = service.create_patch_backed_proposal(
        command_id="cmd-1",
        failure_summary="[ERROR] package javax.validation does not exist",
        hypothesis="Controlled namespace mismatch",
        patch_summary="Repair import namespace",
        affected_paths=(target_rel,),
    )
    body = service.proposal_to_dict(proposal)
    patch_text = body["repair_artifact"]["unified_diff"]
    patch_path = Path(body["repair_artifact"]["patch_path"])

    assert patch_text.startswith(f"diff --git a/{target_rel} b/{target_rel}\n")
    assert f"--- a/{target_rel}" in patch_text
    assert f"+++ b/{target_rel}" in patch_text
    assert "-import javax.validation.Valid;" in patch_text
    assert "+import jakarta.validation.Valid;" in patch_text
    assert "@@" in patch_text
    assert Path(body["repair_artifact"]["patch_path"]).is_file()
    assert patch_path.is_relative_to(sandbox.parent / "repairs" / "proposals")

    patch_valid, patch_error = validate_patch_artifact(patch_path=patch_path, cwd=sandbox)
    assert patch_valid is True, patch_error

    apply_result = apply_patch_to_sandbox(
        run_dir=sandbox.parent,
        sandbox_path=sandbox,
        attempt=1,
        unified_diff=patch_text,
        touched_paths=[target_rel],
    )

    assert apply_result.status == "APPLIED"
    assert apply_result.patch_path.read_text(encoding="utf-8") == patch_text
    assert target.read_text(encoding="utf-8") == original.replace("import javax.validation.Valid;", "import jakarta.validation.Valid;")
    diff_lines = body["repair_artifact"]["unified_diff"].splitlines()
    assert diff_lines[0] == f"diff --git a/{target_rel} b/{target_rel}"
    assert f"--- a/{target_rel}" in diff_lines
    assert f"+++ b/{target_rel}" in diff_lines
    assert "@@ -1,6 +1,6 @@" in diff_lines
    assert "-import javax.validation.Valid;" in diff_lines
    assert "+import jakarta.validation.Valid;" in diff_lines
    assert diff_lines.count("-import javax.validation.Valid;") == 1
    assert diff_lines.count("+import jakarta.validation.Valid;") == 1
    decision = evaluate_rule(
        rule_id="JAKARTA_IMPORT_MECHANICAL_SOURCE",
        sandbox_path=sandbox,
        touched_paths=[target_rel],
        unified_diff=patch_text,
    )
    assert decision.allowed is True


def test_apply_patch_to_sandbox_preserves_trailing_blank_context_line(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("class App {\nimport javax.validation.Valid;\n\n", encoding="utf-8")
    patch_text = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1,3 +1,3 @@\n"
        " class App {\n"
        "-import javax.validation.Valid;\n"
        "+import jakarta.validation.Valid;\n"
        " \n"
    )

    def fake_run(command, **kwargs):
        if command[1:] == ["--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="git version fake", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = apply_patch_to_sandbox(
        run_dir=tmp_path / "run",
        sandbox_path=sandbox,
        attempt=1,
        unified_diff=patch_text,
        touched_paths=[target_rel],
        run=fake_run,
    )

    assert result.status == "APPLIED"
    assert result.patch_path.read_text(encoding="utf-8") == patch_text


def test_invalid_patch_artifact_is_rejected_before_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "import javax.validation.Valid;\n"
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        v2_repair_flow,
        "validate_patch_artifact",
        lambda **kwargs: (False, "corrupt patch at line 12"),
    )

    with pytest.raises(ValueError, match="REPAIR_PATCH_INVALID: corrupt patch at line 12"):
        service.create_patch_backed_proposal(
            command_id="cmd-1",
            failure_summary="[ERROR] package javax.validation does not exist",
            hypothesis="Controlled namespace mismatch",
            patch_summary="Repair import namespace",
            affected_paths=(target_rel,),
        )
    assert target.read_text(encoding="utf-8") == original


def test_validate_patch_artifact_returns_git_not_available_when_git_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_path = tmp_path / "patch.diff"
    patch_path.write_text("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1 +1 @@\n-a\n+b\n", encoding="utf-8")
    monkeypatch.setenv("AI_MIGRATION_GIT_CMD", "")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setattr("migration_factory.repair_loop.patch_apply._COMMON_WINDOWS_GIT_PATHS", ())

    ok, reason = validate_patch_artifact(patch_path=patch_path, cwd=tmp_path)

    assert ok is False
    assert GIT_NOT_AVAILABLE in reason


def test_jakarta_import_mechanical_rule_rejects_body_edits(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    target_rel = "src/main/java/App.java"
    (sandbox / target_rel).parent.mkdir(parents=True, exist_ok=True)
    (sandbox / target_rel).write_text("class App {}\n", encoding="utf-8")
    diff = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@\n"
        "-class App { int value = doesNotCompile; }\n"
        "+class App { int value = 0; }\n"
    )

    decision = evaluate_rule(
        rule_id="JAKARTA_IMPORT_MECHANICAL_SOURCE",
        sandbox_path=sandbox,
        touched_paths=[target_rel],
        unified_diff=diff,
    )

    assert decision.allowed is False
    assert decision.reason == "source diff is not import/package-only"


def test_approve_proposal_requires_accepted_reviewer_critique() -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service)

    with pytest.raises(ValueError, match="blocked by reviewer gate"):
        service.approve_proposal(
            proposal_id=proposal.proposal_id,
            approval_checksum="abc123",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
        )

    approved = _approve(service, proposal.proposal_id)

    assert approved.status == "approved"
    assert approved.approval_checksum == "abc123"


def test_apply_patch_requires_approval(tmp_path: Path) -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service)

    with pytest.raises(ValueError, match="must be approved"):
        service.apply_patch(
            proposal_id=proposal.proposal_id,
            target_path="pom.xml",
            patch_content=_h2_patch(),
            run_id="run-1",
            run_dir=tmp_path / "run",
            sandbox_path=_sandbox(tmp_path),
            legacy_path=tmp_path / "legacy",
            deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
            h2_required=True,
            validation_runner=lambda **kwargs: _validation(True),
        )


def test_v2_approved_repair_routes_through_patch_gate_and_writes_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service)
    _approve(service, proposal.proposal_id)
    sandbox = _sandbox(tmp_path)
    run_dir = tmp_path / "run"
    calls: list[dict] = []
    events: list[tuple[str, dict]] = []

    def fake_apply(**kwargs) -> PatchApplyResult:
        calls.append(kwargs)
        return _apply_result(Path(kwargs["run_dir"]))

    monkeypatch.setattr(v2_repair_flow, "apply_patch_to_sandbox", fake_apply)

    action = service.apply_patch(
        proposal_id=proposal.proposal_id,
        target_path="pom.xml",
        patch_content=_h2_patch(),
        run_id="run-1",
        run_dir=run_dir,
        sandbox_path=sandbox,
        legacy_path=tmp_path / "legacy",
        deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        expected_validation=("mvn test",),
        h2_required=True,
        binding_checksum="binding-1",
        validation_runner=lambda **kwargs: _validation(True),
        event_recorder=lambda event_type, payload: events.append((event_type, payload)),
    )
    ledger = _ledger(run_dir)

    assert calls
    assert calls[0]["touched_paths"] == ["pom.xml"]
    assert action.status == "applied"
    assert ledger["final_status"] == "REPAIR_VALIDATED"
    assert ledger["attempts"][0]["patch_gate_status"] == "ALLOWED"
    assert ledger["attempts"][0]["repair_proposal_checksum"]
    assert ledger["artifact_refs"]["repair_patch_draft"].endswith("patch_draft_1.json")
    assert ledger["attempts"][0]["binding_checksum"] == "binding-1"
    assert ledger["attempts"][0]["status"] == "VALIDATED"
    assert action.verification_status == "passed"
    assert action.verification_build_status == "BUILD_PASSED_IN_SANDBOX"
    assert action.verification_test_status == "TEST_PASSED"
    assert action.verification_h2_status == "H2_STARTUP_PASSED"
    assert json.loads(action.verification_artifact_refs_json) == {}
    assert action.verification_failure_classification_ref == ""
    assert [event[0] for event in events] == [
        "repair_patch_gate_completed",
        "repair_patch_applied",
        "repair_validation_completed",
    ]
    assert events[0][1]["binding_checksum"] == "binding-1"
    assert events[0][1]["repair_proposal_checksum"]
    assert events[0][1]["repair_patch_draft_ref"].endswith("patch_draft_1.json")


def test_v2_repair_bridge_rejects_legacy_path(tmp_path: Path) -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service, affected_paths=("src/main/java/App.java",))
    _approve(service, proposal.proposal_id)
    legacy_source = _sandbox(tmp_path)

    action = service.apply_patch(
        proposal_id=proposal.proposal_id,
        target_path="src/main/java/App.java",
        patch_content=_java_import_patch(),
        run_id="run-1",
        run_dir=tmp_path / "run",
        sandbox_path=legacy_source,
        legacy_path=legacy_source,
        deterministic_rule_id="JAKARTA_IMPORT_MECHANICAL_SOURCE",
        validation_runner=lambda **kwargs: _validation(True),
    )
    ledger = _ledger(tmp_path / "run")

    assert action.status == "failed"
    assert ledger["final_status"] == "REPAIR_BLOCKED"
    assert ledger["attempts"][0]["patch_gate_status"] == "INVALID_PATCH"
    assert any("legacy source" in warning for warning in ledger["warnings"])


def test_v2_repair_bridge_rolls_back_on_validation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service)
    _approve(service, proposal.proposal_id)
    sandbox = _sandbox(tmp_path)
    run_dir = tmp_path / "run"
    rollbacks: list[dict] = []
    events: list[tuple[str, dict]] = []
    build_error_contract = run_dir / "repair_build_error_contract.json"
    failure_classification = run_dir / "post_transform_failure_classification.json"
    build_error_contract.parent.mkdir(parents=True, exist_ok=True)
    build_error_contract.write_text("{}", encoding="utf-8")
    failure_classification.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        v2_repair_flow,
        "apply_patch_to_sandbox",
        lambda **kwargs: _apply_result(Path(kwargs["run_dir"])),
    )

    def fake_rollback(**kwargs):
        rollbacks.append(kwargs)
        return True, "rolled back"

    monkeypatch.setattr(v2_repair_flow, "rollback_patch", fake_rollback)

    action = service.apply_patch(
        proposal_id=proposal.proposal_id,
        target_path="pom.xml",
        patch_content=_h2_patch(),
        run_id="run-1",
        run_dir=run_dir,
        sandbox_path=sandbox,
        legacy_path=tmp_path / "legacy",
        deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        h2_required=True,
        validation_runner=lambda **kwargs: _validation(
            False,
            artifact_refs={"repair_build_error_contract": str(build_error_contract)},
        ),
        event_recorder=lambda event_type, payload: events.append((event_type, payload)),
    )
    ledger = _ledger(run_dir)

    assert rollbacks
    assert action.status == "rolled_back"
    assert action.verification_status == "failed"
    assert action.verification_build_status == "BUILD_FAILED_IN_SANDBOX"
    assert action.verification_test_status == "TEST_FAILED"
    assert action.verification_h2_status == "H2_STARTUP_FAILED"
    assert action.verification_failure_classification_ref == str(build_error_contract)
    assert json.loads(action.verification_artifact_refs_json)[
        "post_transform_failure_classification"
    ] == str(failure_classification)
    assert ledger["final_status"] == "REPAIR_FAILED"
    assert ledger["attempts"][0]["rollback"]["status"] == "ROLLED_BACK"
    assert ledger["attempts"][0]["status"] == "ROLLED_BACK"
    assert [event[0] for event in events] == [
        "repair_patch_gate_completed",
        "repair_patch_applied",
        "repair_validation_completed",
        "repair_rollback_completed",
    ]


def test_apply_approved_proposal_uses_persisted_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(str(tmp_path / "bridge.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)

    repair_repo = None
    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    repair_repo = None
    service = V2RepairFlowService(
        repair_repo=repair_repo,
        job_repo=job_repo,
        setup_repo=setup_repo,
        command_repo=command_repo,
    )

    setup = V2MigrationSetupRecord(
        setup_id="setup-1",
        run_name="bridge",
        legacy_app_path=str(tmp_path / "legacy"),
        output_parent_path=str(tmp_path / "out"),
        ai_hub_path=str(tmp_path / "ai"),
        java11_home="C:/java11",
        java17_home="C:/java17",
        java21_home="C:/java21",
        maven_cmd="mvn",
        proof_level="build_test_verified",
        skip_endpoint_smoke=False,
        migration_flags_json="{}",
        setup_checksum="setup-chk",
        checksum_algorithm="sha256",
        created_at="2026-06-18T00:00:00Z",
        created_by="test",
        correlation_id=None,
    )
    setup_repo.save(setup)
    job_repo.save(
        V2MigrationJobRecord(
            job_id="job-1",
            setup_id="setup-1",
            setup_checksum="setup-chk",
            pipeline_id="pipe-1",
            stage_chain_json="[]",
            status="created",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            correlation_id=None,
        )
    )

    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="Test failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency",
        affected_paths=("pom.xml",),
    )
    service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    approved = service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="abc123",
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
    )
    assert approved.status == "approved"

    run_id = "run-bridge-1"
    run_dir = Path(tmp_path / "out" / ".migration" / "runs" / run_id)
    draft_path = run_dir / "repairs" / "patch_draft_1.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "proposal_id": proposal.proposal_id,
                "repair_proposal_checksum": proposal.proposal_checksum,
                "target_path": "pom.xml",
                "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                "risk": "LOW",
                "requires_human_review": False,
                "binding_checksum": "binding-1",
                "h2_required": True,
                "unified_diff": _h2_patch(),
                "expected_validation": ["mvn test"],
                "limitations": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    command_repo.save(
        V2StageCommandRecord(
            command_id="cmd-1",
            job_id="job-1",
            stage_index=3,
            manifest_checksum="manifest-chk",
            argv_json="[]",
            env_json="{}",
            status="failed",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            result_json=json.dumps(
                {
                    "run_id": run_id,
                    "sandbox_path": str(run_dir / "sandbox"),
                    "modernized_app_path": str(tmp_path / "out"),
                }
            ),
            gate_id=None,
            decision_id=None,
        )
    )
    (tmp_path / "legacy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / ".migration" / "runs" / run_id / "sandbox").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / ".migration" / "runs" / run_id / "sandbox" / "pom.xml").write_text(
        "<project/>",
        encoding="utf-8",
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        v2_repair_flow,
        "apply_patch_to_sandbox",
        lambda **kwargs: calls.append(kwargs) or _apply_result(Path(kwargs["run_dir"])),
    )
    result = service.apply_approved_proposal(
        proposal_id=proposal.proposal_id,
        command_id="cmd-1",
        validation_runner=lambda **kwargs: _validation(True),
    )

    assert result.status == "applied"
    assert calls
    assert calls[0]["run_dir"] == run_dir
    assert calls[0]["sandbox_path"] == str(run_dir / "sandbox")


def test_apply_approved_proposal_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(str(tmp_path / "bridge-idempotent.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)

    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    service = V2RepairFlowService(
        repair_repo=None,
        job_repo=job_repo,
        setup_repo=setup_repo,
        command_repo=command_repo,
    )

    setup = V2MigrationSetupRecord(
        setup_id="setup-idem",
        run_name="bridge",
        legacy_app_path=str(tmp_path / "legacy"),
        output_parent_path=str(tmp_path / "out"),
        ai_hub_path=str(tmp_path / "ai"),
        java11_home="C:/java11",
        java17_home="C:/java17",
        java21_home="C:/java21",
        maven_cmd="mvn",
        proof_level="build_test_verified",
        skip_endpoint_smoke=False,
        migration_flags_json="{}",
        setup_checksum="setup-chk",
        checksum_algorithm="sha256",
        created_at="2026-06-18T00:00:00Z",
        created_by="test",
        correlation_id=None,
    )
    setup_repo.save(setup)
    job_repo.save(
        V2MigrationJobRecord(
            job_id="job-idem",
            setup_id="setup-idem",
            setup_checksum="setup-chk",
            pipeline_id="pipe-idem",
            stage_chain_json="[]",
            status="created",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            correlation_id=None,
        )
    )

    proposal = service.create_proposal(
        command_id="cmd-idem",
        failure_summary="Test failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency",
        affected_paths=("pom.xml",),
    )
    service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    approved = service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="abc123",
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
    )
    assert approved.status == "approved"

    run_id = "run-idem-1"
    run_dir = Path(tmp_path / "out" / ".migration" / "runs" / run_id)
    draft_path = run_dir / "repairs" / "patch_draft_1.json"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "proposal_id": proposal.proposal_id,
                "repair_proposal_checksum": proposal.proposal_checksum,
                "target_path": "pom.xml",
                "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                "risk": "LOW",
                "requires_human_review": False,
                "binding_checksum": "binding-1",
                "h2_required": True,
                "unified_diff": _h2_patch(),
                "expected_validation": ["mvn test"],
                "limitations": [],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    command_repo.save(
        V2StageCommandRecord(
            command_id="cmd-idem",
            job_id="job-idem",
            stage_index=3,
            manifest_checksum="manifest-chk",
            argv_json="[]",
            env_json="{}",
            status="failed",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            result_json=json.dumps(
                {
                    "run_id": run_id,
                    "sandbox_path": str(run_dir / "sandbox"),
                    "modernized_app_path": str(tmp_path / "out"),
                }
            ),
            gate_id=None,
            decision_id=None,
        )
    )
    (tmp_path / "legacy").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / ".migration" / "runs" / run_id / "sandbox").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / ".migration" / "runs" / run_id / "sandbox" / "pom.xml").write_text(
        "<project/>",
        encoding="utf-8",
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        v2_repair_flow,
        "apply_patch_to_sandbox",
        lambda **kwargs: calls.append(kwargs) or _apply_result(Path(kwargs["run_dir"])),
    )
    monkeypatch.setattr(v2_repair_flow, "run_validation_after_patch", lambda **kwargs: _validation(True))
    first = service.apply_approved_proposal(
        proposal_id=proposal.proposal_id,
        command_id="cmd-idem",
    )
    second = service.apply_approved_proposal(
        proposal_id=proposal.proposal_id,
        command_id="cmd-idem",
    )

    assert first.status == "applied"
    assert second.status == "idempotent"
    assert second.action_id == first.action_id
    assert first.verification_status == "passed"
    assert second.verification_status == "passed"
    assert second.verification_build_status == first.verification_build_status
    assert second.verification_test_status == first.verification_test_status
    assert second.verification_h2_status == first.verification_h2_status
    assert len(calls) == 1


def test_prepare_apply_context_persists_repair_review_context(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
        model_invocation_id="reviewer-invoke-1",
    )

    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )

    assert context.approval_eligible is True
    assert context.approval_scope == "sandbox_only"
    assert context.reviewer_decision == "accept"
    loaded = service.get_apply_context(context.context_id)
    assert loaded is not None
    assert loaded.context_id == context.context_id
    assert loaded.sandbox_reference == "sandbox://run-1"
    assert loaded.legacy_checksum == "legacy-chk"
    assert json.loads(loaded.evidence_refs_json) == {"build_error": "artifact://build-error.json"}


def test_prepare_apply_context_fails_closed_when_command_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        str(tmp_path / "missing-command.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)
    service = V2RepairFlowService(
        repair_repo=SqliteV2RepairRepository(conn),
        reviewer_service=v2_repair_flow.V2ReviewerService(
            reviewer_repo=SqliteV2ReviewerRepository(conn)
        ),
        job_repo=SqliteV2JobRepository(conn),
        setup_repo=SqliteV2SetupRepository(conn),
        command_repo=SqliteV2CommandRepository(conn),
    )
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )

    with pytest.raises(v2_repair_flow.RepairContextBindingError, match="Command 'cmd-1' not found"):
        service.prepare_apply_context(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            reviewer_critique_id=critique.critique_id,
            proposer_invocation_id="proposer-invoke-1",
            reviewer_invocation_id="reviewer-invoke-1",
            patch_preview=_h2_patch(),
            target_path="pom.xml",
            sandbox_reference=str(tmp_path / "sandbox"),
            sandbox_checksum="sandbox-chk",
            legacy_checksum="legacy-chk",
            evidence_refs={"build_error": "artifact://build-error.json"},
        )


def test_prepare_apply_context_requires_durable_command_sandbox_binding(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )

    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference=str(sandbox),
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )

    assert context.sandbox_reference == str(sandbox)
    assert context.approval_eligible is True


def test_prepare_apply_context_binds_when_modernized_path_is_redacted(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )

    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference=str(sandbox),
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )

    assert context.sandbox_reference == str(sandbox)


def test_prepare_apply_context_consumes_patch_backed_proposal_artifacts(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "package com.example;\n\n"
        "import javax.validation.Valid;\n\n"
        "class App {\n"
        "  @Valid Object value;\n"
        "}\n",
        encoding="utf-8",
    )
    proposal = service.create_patch_backed_proposal(
        command_id="cmd-1",
        failure_summary="[ERROR] package javax.validation does not exist",
        hypothesis="Controlled namespace mismatch",
        patch_summary="Repair import namespace",
        affected_paths=(target_rel,),
    )
    package = service.proposal_to_dict(proposal)["patch_package"]
    service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=package["package_checksum"],
        decision="accept",
        reasoning="Patch-backed package is sandbox-only.",
        missing_evidence=(),
        unsafe_assumptions=(),
    )
    critique = service._reviewer.check_reviewer_gate(
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=package["package_checksum"],
    )

    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id="cmd-1",
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=package["package_checksum"],
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-1",
        reviewer_invocation_id="reviewer-1",
        patch_preview=package["repair_artifact"]["unified_diff"],
        target_path=target_rel,
        sandbox_reference=str(sandbox),
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={
            "patch_path": package["repair_artifact"]["patch_path"],
            "evidence_artifact": package["evidence_artifact_path"],
            "deterministic_rule_id": package["deterministic_rule_id"],
        },
    )

    assert context.approval_eligible is True
    assert context.target_path == target_rel
    assert json.loads(context.evidence_refs_json)["patch_path"] == package["repair_artifact"]["patch_path"]
    assert json.loads(context.evidence_refs_json)["deterministic_rule_id"] == "JAKARTA_IMPORT_MECHANICAL_SOURCE"
    assert context.approval_eligible is True


def test_prepare_apply_context_rejects_target_escape(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )

    with pytest.raises(v2_repair_flow.RepairContextBindingError, match="target is not sandbox-bound"):
        service.prepare_apply_context(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            reviewer_critique_id=critique.critique_id,
            proposer_invocation_id="proposer-invoke-1",
            reviewer_invocation_id="reviewer-invoke-1",
            patch_preview=_h2_patch(),
            target_path="../legacy/pom.xml",
            sandbox_reference=str(sandbox),
            sandbox_checksum="sandbox-chk",
            legacy_checksum="legacy-chk",
            evidence_refs={"build_error": "artifact://build-error.json"},
        )


def test_prepare_apply_context_rejects_sandbox_reference_mismatch(tmp_path: Path) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    other_sandbox = tmp_path / "other-sandbox"
    other_sandbox.mkdir()

    with pytest.raises(v2_repair_flow.RepairContextBindingError, match="does not match command sandbox"):
        service.prepare_apply_context(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            reviewer_critique_id=critique.critique_id,
            proposer_invocation_id="proposer-invoke-1",
            reviewer_invocation_id="reviewer-invoke-1",
            patch_preview=_h2_patch(),
            target_path="pom.xml",
            sandbox_reference=str(other_sandbox),
            sandbox_checksum="sandbox-chk",
            legacy_checksum="legacy-chk",
            evidence_refs={"build_error": "artifact://build-error.json"},
        )


def test_prepare_apply_context_fails_closed_without_accept(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="revise",
        reasoning="Need more evidence",
    )

    with pytest.raises(ValueError, match="reviewer decision is accept"):
        service.prepare_apply_context(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            reviewer_critique_id=critique.critique_id,
            proposer_invocation_id="proposer-invoke-1",
            reviewer_invocation_id="reviewer-invoke-1",
            patch_preview=_h2_patch(),
            target_path="pom.xml",
            sandbox_reference="sandbox://run-1",
            sandbox_checksum="sandbox-chk",
            legacy_checksum="legacy-chk",
            evidence_refs={"build_error": "artifact://build-error.json"},
        )


@pytest.mark.parametrize(
    ("field_name", "kwargs", "message"),
    [
        ("sandbox_reference", {"sandbox_reference": ""}, "sandbox reference"),
        ("patch_preview", {"patch_preview": ""}, "patch preview"),
        ("legacy_checksum", {"legacy_checksum": ""}, "legacy checksum"),
    ],
)
def test_prepare_apply_context_requires_complete_binding(
    tmp_path: Path,
    field_name: str,
    kwargs: dict[str, str],
    message: str,
) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    payload = {
        "proposal_id": proposal.proposal_id,
        "command_id": proposal.command_id,
        "proposal_checksum": "pc-test",
        "context_pack_checksum": "cp-test",
        "reviewer_critique_id": critique.critique_id,
        "proposer_invocation_id": "proposer-invoke-1",
        "reviewer_invocation_id": "reviewer-invoke-1",
        "patch_preview": _h2_patch(),
        "target_path": "pom.xml",
        "sandbox_reference": "sandbox://run-1",
        "sandbox_checksum": "sandbox-chk",
        "legacy_checksum": "legacy-chk",
        "evidence_refs": {"build_error": "artifact://build-error.json"},
    }
    payload.update(kwargs)

    with pytest.raises(ValueError, match=message):
        service.prepare_apply_context(**payload)


def test_record_approval_only_persists_without_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
        model_invocation_id="reviewer-invoke-1",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    apply_called = False

    def _no_apply(**kwargs):
        nonlocal apply_called
        apply_called = True
        raise AssertionError("apply should not run")

    monkeypatch.setattr(v2_repair_flow, "apply_patch_to_sandbox", _no_apply)

    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )

    assert approval.approval_status == "recorded"
    assert approval.approval_scope == "sandbox_only"
    assert apply_called is False
    loaded = service.get_latest_approval(context.context_id)
    assert loaded is not None
    assert loaded.approval_id == approval.approval_id


def test_record_approval_only_requires_sandbox_only_scope(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )

    with pytest.raises(ValueError, match="sandbox_only"):
        service.record_approval_only(
            context_id=context.context_id,
            approval_checksum="approval-chk",
            approval_note="Human approves everything.",
            approval_scope="legacy_source",
        )


def test_get_approval_requires_context_binding(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )

    assert service.get_approval(context.context_id, approval.approval_id) is not None
    assert service.get_approval("other-context", approval.approval_id) is None


def test_validate_apply_guard_passes_then_reports_not_wired_ready(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )

    guard = service.validate_apply_guard(
        context_id=context.context_id,
        approval_id=approval.approval_id,
        expected_approval_checksum="approval-chk",
        expected_sandbox_checksum="sandbox-chk",
        expected_legacy_checksum="legacy-chk",
    )

    assert guard.apply_ready is True
    assert guard.blockers == ()
    assert guard.patch_preview_checksum == context.patch_preview_checksum


def test_apply_prepared_context_applies_only_sandbox_and_records_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = sqlite3.connect(
        str(tmp_path / "prepared-apply.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)
    repair_repo = SqliteV2RepairRepository(conn)
    reviewer_repo = SqliteV2ReviewerRepository(conn)
    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    service = V2RepairFlowService(
        repair_repo=repair_repo,
        reviewer_service=v2_repair_flow.V2ReviewerService(reviewer_repo=reviewer_repo),
        job_repo=job_repo,
        setup_repo=setup_repo,
        command_repo=command_repo,
    )
    legacy = tmp_path / "legacy"
    sandbox = tmp_path / "out" / ".migration" / "runs" / "run-prepared" / "sandbox"
    legacy.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    (legacy / "pom.xml").write_text("<project/>", encoding="utf-8")
    (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")
    legacy_before = (legacy / "pom.xml").read_text(encoding="utf-8")
    sandbox_before = (sandbox / "pom.xml").read_text(encoding="utf-8")
    setup_repo.save(
        V2MigrationSetupRecord(
            setup_id="setup-prepared",
            run_name="prepared",
            legacy_app_path=str(legacy),
            output_parent_path=str(tmp_path / "out"),
            ai_hub_path=str(tmp_path / "ai"),
            java11_home="C:/java11",
            java17_home="C:/java17",
            java21_home="C:/java21",
            maven_cmd="mvn",
            proof_level="build_test_verified",
            skip_endpoint_smoke=False,
            migration_flags_json="{}",
            setup_checksum="setup-chk",
            checksum_algorithm="sha256",
            created_at="2026-06-18T00:00:00Z",
            created_by="test",
            correlation_id=None,
        )
    )
    job_repo.save(
        V2MigrationJobRecord(
            job_id="job-prepared",
            setup_id="setup-prepared",
            setup_checksum="setup-chk",
            pipeline_id="pipe-prepared",
            stage_chain_json="[]",
            status="created",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            correlation_id=None,
        )
    )
    command_repo.save(
        V2StageCommandRecord(
            command_id="cmd-prepared",
            job_id="job-prepared",
            stage_index=3,
            manifest_checksum="manifest-chk",
            argv_json="[]",
            env_json="{}",
            status="failed",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            result_json=json.dumps(
                {
                    "run_id": "run-prepared",
                    "sandbox_path": str(sandbox),
                    "modernized_app_path": str(tmp_path / "out"),
                }
            ),
            gate_id=None,
            decision_id=None,
        )
    )
    proposal = service.create_proposal(
        command_id="cmd-prepared",
        failure_summary="Missing H2",
        hypothesis="H2 dependency absent",
        patch_summary="Add H2 dependency",
        affected_paths=("pom.xml",),
    )
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference=str(sandbox),
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={
            "build_error": "artifact://build-error.json",
            "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
            "h2_required": "true",
            "expected_validation": "mvn test",
        },
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )
    calls: list[dict] = []

    def fake_apply(**kwargs) -> PatchApplyResult:
        calls.append(kwargs)
        (Path(kwargs["sandbox_path"]) / "pom.xml").write_text(
            "<project><dependency>h2</dependency></project>",
            encoding="utf-8",
        )
        return _apply_result(Path(kwargs["run_dir"]))

    monkeypatch.setattr(v2_repair_flow, "apply_patch_to_sandbox", fake_apply)
    events: list[tuple[str, dict]] = []
    action = service.apply_prepared_context(
        context_id=context.context_id,
        approval_id=approval.approval_id,
        expected_approval_checksum="approval-chk",
        expected_sandbox_checksum="sandbox-chk",
        expected_legacy_checksum="legacy-chk",
        validation_runner=lambda **kwargs: _validation(True),
        event_recorder=lambda event_type, payload: events.append((event_type, payload)),
    )

    assert action.status == "applied"
    assert action.verification_status == "passed"
    assert action.verification_build_status == "BUILD_PASSED_IN_SANDBOX"
    assert action.verification_test_status == "TEST_PASSED"
    assert calls and calls[0]["sandbox_path"] == sandbox
    assert (legacy / "pom.xml").read_text(encoding="utf-8") == legacy_before
    assert (sandbox / "pom.xml").read_text(encoding="utf-8") != sandbox_before
    assert [event[0] for event in events] == [
        "repair_patch_gate_completed",
        "repair_patch_applied",
        "repair_validation_completed",
    ]


def test_apply_prepared_context_audits_missing_git_without_mutating_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn, service, sandbox = _bound_repair_repo_service(tmp_path, redacted_modernized_path=True)
    legacy = tmp_path / "legacy"
    target_rel = "src/main/java/App.java"
    target = sandbox / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import jakarta.servlet.http.HttpServletRequest;\nclass App {}\n", encoding="utf-8")
    sandbox_before = target.read_text(encoding="utf-8")
    proposal = service.create_proposal(
        command_id="cmd-1",
        failure_summary="package jakarta.servlet.http does not exist",
        hypothesis="Import namespace mismatch",
        patch_summary="Switch import back to javax",
        affected_paths=(target_rel,),
    )
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    patch = (
        f"diff --git a/{target_rel} b/{target_rel}\n"
        f"--- a/{target_rel}\n"
        f"+++ b/{target_rel}\n"
        "@@\n"
        "-import jakarta.servlet.http.HttpServletRequest;\n"
        "+import javax.servlet.http.HttpServletRequest;\n"
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=patch,
        target_path=target_rel,
        sandbox_reference=str(sandbox),
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"deterministic_rule_id": "JAKARTA_IMPORT_MECHANICAL_SOURCE"},
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )

    def missing_git(**kwargs) -> PatchApplyResult:
        return PatchApplyResult(
            status="REJECTED",
            reason="PATCH_APPLY_GIT_NOT_AVAILABLE: git executable not found or not runnable",
            patch_path=Path(kwargs["run_dir"]) / "repairs" / "patch_attempt_1.diff",
            touched_paths=[target_rel],
            before_hashes={target_rel: "before"},
            after_hashes={},
            snapshot_dir=Path(kwargs["run_dir"]) / "repairs" / "snapshots" / "attempt_1",
            created_paths=[],
            errors=["PATCH_APPLY_GIT_NOT_AVAILABLE: git executable not found or not runnable"],
        )

    monkeypatch.setattr(v2_repair_flow, "apply_patch_to_sandbox", missing_git)
    action = service.apply_prepared_context(
        context_id=context.context_id,
        approval_id=approval.approval_id,
        expected_approval_checksum="approval-chk",
        expected_sandbox_checksum="sandbox-chk",
        expected_legacy_checksum="legacy-chk",
        validation_runner=lambda **kwargs: _validation(True),
    )

    assert action.status == "failed"
    assert "PATCH_APPLY_GIT_NOT_AVAILABLE" in action.result_summary
    assert target.read_text(encoding="utf-8") == sandbox_before
    assert not (legacy / target_rel).exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("expected_approval_checksum", "wrong", "approval checksum mismatch"),
        ("expected_sandbox_checksum", "wrong", "sandbox checksum mismatch"),
        ("expected_legacy_checksum", "wrong", "legacy checksum mismatch"),
    ],
)
def test_validate_apply_guard_fails_closed_on_checksum_mismatch(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )
    payload = {
        "context_id": context.context_id,
        "approval_id": approval.approval_id,
        "expected_approval_checksum": "approval-chk",
        "expected_sandbox_checksum": "sandbox-chk",
        "expected_legacy_checksum": "legacy-chk",
    }
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        service.validate_apply_guard(**payload)


def test_validate_apply_guard_fails_closed_when_target_escapes_sandbox(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="../pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    approval = service.record_approval_only(
        context_id=context.context_id,
        approval_checksum="approval-chk",
        approval_note="Human approves sandbox-only apply later.",
        approval_scope="sandbox_only",
    )

    with pytest.raises(ValueError, match="not sandbox-bound"):
        service.validate_apply_guard(
            context_id=context.context_id,
            approval_id=approval.approval_id,
            expected_approval_checksum="approval-chk",
            expected_sandbox_checksum="sandbox-chk",
            expected_legacy_checksum="legacy-chk",
        )


def test_validate_apply_guard_fails_closed_without_reviewer_accept(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    assert service._repo is not None
    proposal = _proposal(service)
    context_payload = {
        "kind": "repair_apply_context_v1",
        "context_id": "ctx-revise",
        "command_id": proposal.command_id,
        "reviewer_critique_id": "critique-1",
        "proposer_invocation_id": "proposer-invoke-1",
        "reviewer_invocation_id": "reviewer-invoke-1",
        "reviewer_decision": "revise",
        "proposal_summary": proposal.patch_summary,
        "patch_preview_checksum": "patch-chk",
        "sandbox_reference": "sandbox://run-1",
        "sandbox_checksum": "sandbox-chk",
        "legacy_checksum": "legacy-chk",
        "context_pack_checksum": "cp-test",
        "proposal_checksum": "pc-test",
        "evidence_refs": {},
        "approval_eligible": True,
        "blockers": [],
        "approval_scope": "sandbox_only",
    }
    service._repo.save_action(
        V2SandboxActionRecord(
            action_id="ctx-revise",
            proposal_id=proposal.proposal_id,
            target_path="pom.xml",
            patch_content=_h2_patch(),
            status="prepared_apply_context",
            result_summary=json.dumps(context_payload),
            created_at="2026-06-26T00:00:00Z",
        )
    )
    service._repo.save_action(
        V2SandboxActionRecord(
            action_id="approval-1",
            proposal_id=proposal.proposal_id,
            target_path="pom.xml",
            patch_content="",
            status="approval_recorded",
            result_summary=json.dumps(
                {
                    "kind": "repair_approval_record_v1",
                    "approval_id": "approval-1",
                    "context_id": "ctx-revise",
                    "approval_status": "recorded",
                    "approval_scope": "sandbox_only",
                    "approval_note": "Human approval.",
                    "approval_checksum": "approval-chk",
                    "sandbox_checksum": "sandbox-chk",
                    "legacy_checksum": "legacy-chk",
                }
            ),
            created_at="2026-06-26T00:00:01Z",
        )
    )

    with pytest.raises(ValueError, match="reviewer decision accept"):
        service.validate_apply_guard(
            context_id="ctx-revise",
            approval_id="approval-1",
            expected_approval_checksum="approval-chk",
            expected_sandbox_checksum="sandbox-chk",
            expected_legacy_checksum="legacy-chk",
        )


def test_validate_apply_guard_fails_closed_without_sandbox_only_approval(tmp_path: Path) -> None:
    conn, service = _repair_repo_service(tmp_path)
    assert service._repo is not None
    proposal = _proposal(service)
    critique = service._reviewer.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Looks good",
    )
    context = service.prepare_apply_context(
        proposal_id=proposal.proposal_id,
        command_id=proposal.command_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        reviewer_critique_id=critique.critique_id,
        proposer_invocation_id="proposer-invoke-1",
        reviewer_invocation_id="reviewer-invoke-1",
        patch_preview=_h2_patch(),
        target_path="pom.xml",
        sandbox_reference="sandbox://run-1",
        sandbox_checksum="sandbox-chk",
        legacy_checksum="legacy-chk",
        evidence_refs={"build_error": "artifact://build-error.json"},
    )
    service._repo.save_action(
        V2SandboxActionRecord(
            action_id="approval-legacy",
            proposal_id=proposal.proposal_id,
            target_path="pom.xml",
            patch_content="",
            status="approval_recorded",
            result_summary=json.dumps(
                {
                    "kind": "repair_approval_record_v1",
                    "approval_id": "approval-legacy",
                    "context_id": context.context_id,
                    "approval_status": "recorded",
                    "approval_scope": "legacy_source",
                    "approval_note": "Bad scope.",
                    "approval_checksum": "approval-chk",
                    "sandbox_checksum": "sandbox-chk",
                    "legacy_checksum": "legacy-chk",
                }
            ),
            created_at="2026-06-26T00:00:01Z",
        )
    )

    with pytest.raises(ValueError, match="scope must be sandbox_only"):
        service.validate_apply_guard(
            context_id=context.context_id,
            approval_id="approval-legacy",
            expected_approval_checksum="approval-chk",
            expected_sandbox_checksum="sandbox-chk",
            expected_legacy_checksum="legacy-chk",
        )


def test_cannot_approve_twice() -> None:
    service = V2RepairFlowService()
    proposal = _proposal(service)
    _approve(service, proposal.proposal_id)

    with pytest.raises(ValueError, match="already approved"):
        service.approve_proposal(
            proposal_id=proposal.proposal_id,
            approval_checksum="abc123",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
        )


def test_unknown_proposal() -> None:
    service = V2RepairFlowService()

    with pytest.raises(ValueError, match="not found"):
        service.approve_proposal(
            proposal_id="nonexistent",
            approval_checksum="abc",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
        )


def _proposal(
    service: V2RepairFlowService,
    *,
    affected_paths: tuple[str, ...] = ("pom.xml",),
):
    return service.create_proposal(
        command_id="cmd-1",
        failure_summary="Test failed",
        hypothesis="Missing dependency",
        patch_summary="Add dependency",
        affected_paths=affected_paths,
    )


def _repair_repo_service(tmp_path: Path) -> tuple[sqlite3.Connection, V2RepairFlowService]:
    conn = sqlite3.connect(
        str(tmp_path / "repair-context.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)
    repair_repo = SqliteV2RepairRepository(conn)
    reviewer_repo = SqliteV2ReviewerRepository(conn)
    service = V2RepairFlowService(
        repair_repo=repair_repo,
        reviewer_service=v2_repair_flow.V2ReviewerService(reviewer_repo=reviewer_repo),
    )
    return conn, service


def _bound_repair_repo_service(
    tmp_path: Path,
    *,
    redacted_modernized_path: bool = False,
) -> tuple[sqlite3.Connection, V2RepairFlowService, Path]:
    conn = sqlite3.connect(
        str(tmp_path / "bound-repair-context.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    apply_pending_migrations(conn)
    repair_repo = SqliteV2RepairRepository(conn)
    reviewer_repo = SqliteV2ReviewerRepository(conn)
    setup_repo = SqliteV2SetupRepository(conn)
    job_repo = SqliteV2JobRepository(conn)
    command_repo = SqliteV2CommandRepository(conn)
    service = V2RepairFlowService(
        repair_repo=repair_repo,
        reviewer_service=v2_repair_flow.V2ReviewerService(reviewer_repo=reviewer_repo),
        job_repo=job_repo,
        setup_repo=setup_repo,
        command_repo=command_repo,
    )
    legacy = tmp_path / "legacy"
    output_root = tmp_path / "out"
    run_id = "run-bound"
    sandbox = output_root / ".migration" / "runs" / run_id / "sandbox"
    legacy.mkdir(parents=True)
    sandbox.mkdir(parents=True)
    _init_git_repo(sandbox)
    setup_repo.save(
        V2MigrationSetupRecord(
            setup_id="setup-bound",
            run_name="bound",
            legacy_app_path=str(legacy),
            output_parent_path=str(output_root),
            ai_hub_path=str(tmp_path / "ai"),
            java11_home="C:/java11",
            java17_home="C:/java17",
            java21_home="C:/java21",
            maven_cmd="mvn",
            proof_level="build_test_verified",
            skip_endpoint_smoke=False,
            migration_flags_json="{}",
            setup_checksum="setup-chk",
            checksum_algorithm="sha256",
            created_at="2026-06-18T00:00:00Z",
            created_by="test",
            correlation_id=None,
        )
    )
    job_repo.save(
        V2MigrationJobRecord(
            job_id="job-bound",
            setup_id="setup-bound",
            setup_checksum="setup-chk",
            pipeline_id="pipe-bound",
            stage_chain_json="[]",
            status="created",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            correlation_id=None,
        )
    )
    command_repo.save(
        V2StageCommandRecord(
            command_id="cmd-1",
            job_id="job-bound",
            stage_index=3,
            manifest_checksum="manifest-chk",
            argv_json="[]",
            env_json="{}",
            status="failed",
            created_at="2026-06-18T00:00:00Z",
            updated_at="2026-06-18T00:00:00Z",
            result_json=json.dumps(
                {
                    "run_id": run_id,
                    "sandbox_path": str(sandbox),
                    "modernized_app_path": "[redacted-windows-path]"
                    if redacted_modernized_path
                    else str(output_root),
                }
            ),
            gate_id=None,
            decision_id=None,
        )
    )
    return conn, service, sandbox


def _approve(service: V2RepairFlowService, proposal_id: str):
    service._reviewer.record_critique(
        proposal_id=proposal_id,
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
        decision="accept",
        reasoning="Proposal is bounded.",
    )
    return service.approve_proposal(
        proposal_id=proposal_id,
        approval_checksum="abc123",
        proposal_checksum="pc-test",
        context_pack_checksum="cp-test",
    )


def _sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir(exist_ok=True)
    (sandbox / "pom.xml").write_text(_pom(), encoding="utf-8")
    java_dir = sandbox / "src" / "main" / "java"
    java_dir.mkdir(parents=True, exist_ok=True)
    (java_dir / "App.java").write_text("import javax.validation.Valid;\n", encoding="utf-8")
    _init_git_repo(sandbox)
    return sandbox


def _pom() -> str:
    return (
        "<project><modelVersion>4.0.0</modelVersion><parent>"
        "<groupId>org.springframework.boot</groupId><artifactId>spring-boot-starter-parent</artifactId>"
        "<version>3.2.0</version></parent><dependencies></dependencies></project>\n"
    )


def _h2_patch() -> str:
    return (
        "diff --git a/pom.xml b/pom.xml\n"
        "--- a/pom.xml\n"
        "+++ b/pom.xml\n"
        "@@\n"
        " <dependencies>\n"
        "+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>\n"
    )


def _java_import_patch() -> str:
    return (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@\n"
        "-import javax.validation.Valid;\n"
        "+import jakarta.validation.Valid;\n"
    )


def _apply_result(run_dir: Path) -> PatchApplyResult:
    patch_path = run_dir / "repairs" / "patch_attempt_1.diff"
    snapshot_dir = run_dir / "repairs" / "snapshots" / "attempt_1"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    patch_path.write_text(_h2_patch(), encoding="utf-8")
    return PatchApplyResult(
        status="APPLIED",
        reason="ok",
        patch_path=patch_path,
        touched_paths=["pom.xml"],
        before_hashes={"pom.xml": "before"},
        after_hashes={"pom.xml": "after"},
        snapshot_dir=snapshot_dir,
        created_paths=[],
        errors=[],
    )


def _validation(passed: bool, *, artifact_refs: dict[str, str] | None = None) -> ValidationResult:
    return ValidationResult(
        passed=passed,
        build_status="BUILD_PASSED_IN_SANDBOX" if passed else "BUILD_FAILED_IN_SANDBOX",
        test_status="TEST_PASSED" if passed else "TEST_FAILED",
        h2_status="H2_STARTUP_PASSED" if passed else "H2_STARTUP_FAILED",
        validation_commands=[["mvn", "test"]],
        artifact_refs=artifact_refs or {},
        warnings=[],
        errors=[] if passed else ["validation failed"],
    )


def _ledger(run_dir: Path) -> dict:
    return json.loads((run_dir / "repairs" / "repair_ledger.json").read_text(encoding="utf-8"))


def _git_binary() -> str | None:
    configured = shutil.which("git")
    return configured


def _init_git_repo(root: Path) -> None:
    git = _git_binary()
    if git is None:
        return
    subprocess.run([git, "init"], cwd=str(root), capture_output=True, text=True, check=False)
    subprocess.run([git, "config", "user.email", "test@example.com"], cwd=str(root), capture_output=True, text=True, check=False)
    subprocess.run([git, "config", "user.name", "Test User"], cwd=str(root), capture_output=True, text=True, check=False)
