"""Tests for V2 repair/proposal flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import migration_factory.control_tower.application.v2_repair_flow as v2_repair_flow
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.repair_loop.patch_apply import PatchApplyResult
from migration_factory.repair_loop.validation_runner import ValidationResult


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
        validation_runner=lambda **kwargs: _validation(False),
        event_recorder=lambda event_type, payload: events.append((event_type, payload)),
    )
    ledger = _ledger(run_dir)

    assert rollbacks
    assert action.status == "rolled_back"
    assert ledger["final_status"] == "REPAIR_FAILED"
    assert ledger["attempts"][0]["rollback"]["status"] == "ROLLED_BACK"
    assert ledger["attempts"][0]["status"] == "ROLLED_BACK"
    assert [event[0] for event in events] == [
        "repair_patch_gate_completed",
        "repair_patch_applied",
        "repair_validation_completed",
        "repair_rollback_completed",
    ]


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


def _validation(passed: bool) -> ValidationResult:
    return ValidationResult(
        passed=passed,
        build_status="BUILD_PASSED_IN_SANDBOX" if passed else "BUILD_FAILED_IN_SANDBOX",
        test_status="TEST_PASSED" if passed else "TEST_FAILED",
        h2_status="H2_STARTUP_PASSED" if passed else "H2_STARTUP_FAILED",
        validation_commands=[["mvn", "test"]],
        artifact_refs={},
        warnings=[],
        errors=[] if passed else ["validation failed"],
    )


def _ledger(run_dir: Path) -> dict:
    return json.loads((run_dir / "repairs" / "repair_ledger.json").read_text(encoding="utf-8"))
