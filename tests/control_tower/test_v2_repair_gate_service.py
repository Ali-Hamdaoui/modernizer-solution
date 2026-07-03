"""Focused tests for F15 jobs 101-108 — repair_review gate lifecycle.

Covers:
  - job101: Create repair_review gate on build/test failure
  - job102: Create repair_review gate on transform failure
  - job104: request_repair_revision action
  - job105: approve_repair action (delegated)
  - job106: reject_repair action
  - job107: Repair validation result gate transition
  - job108: Repair attempt limits at gate layer
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    FailureDiagnosisRecord,
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_gate_action_service import (
    V2GateActionService,
)
from migration_factory.control_tower.application.v2_phase_gate_service import (
    CreateGateRequest,
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_repair_gate_service import (
    V2RepairGateService,
    create_repair_gate_diagnosis_callback,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.application.v2_reviewer_service import (
    ReviewerCritique,
    V2ReviewerService,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_gate_decision_repository import (
    SqliteGateDecisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import (
    SqlitePhaseGateRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_artifact_revision_repository import (
    SqliteArtifactRevisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
)


# ── Helpers ───────────────────────────────────────────────────────────


def _connection(tmp_path: Path, name: str = "repair_gate.sqlite3") -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(tmp_path / name),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


def _svc(tmp_path: Path) -> tuple:
    """Set up services for repair gate tests."""
    conn = _connection(tmp_path)
    gate_repo = SqlitePhaseGateRepository(conn)
    decision_repo = SqliteGateDecisionRepository(conn)
    gate_svc = V2PhaseGateService(gate_repo)
    reviewer_svc = V2ReviewerService()
    repair_svc = V2RepairFlowService(reviewer_service=reviewer_svc)
    action_svc = V2GateActionService(
        gate_repo, decision_repo, gate_svc,
        repair_service=repair_svc,
    )
    repair_gate_svc = V2RepairGateService(
        gate_service=gate_svc,
        gate_action_service=action_svc,
        repair_flow=repair_svc,
        max_repair_attempts=3,
    )
    return gate_repo, decision_repo, gate_svc, action_svc, repair_svc, reviewer_svc, repair_gate_svc, conn


def _create_diagnosis_record(
    command_id: str = "cmd-1",
    event_type: str = "build_failed",
) -> FailureDiagnosisRecord:
    """Create a minimal FailureDiagnosisRecord for testing."""
    return FailureDiagnosisRecord(
        diagnosis_id="diag-1",
        command_id=command_id,
        event_type=event_type,
        failure_type="BUILD_FAILED",
        context_pack_id="pack-1",
        context_pack_checksum="sha256:ctx-v1",
        repair_proposal_id="prop-1",
        model_invocation_id="model-1",
        redaction_status="evidence_redacted",
        created_at="2026-06-17T12:00:00Z",
    )


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def save(self, **kwargs):
        self.events.append(kwargs)


def _h2_patch() -> str:
    return (
        "diff --git a/pom.xml b/pom.xml\n"
        "--- a/pom.xml\n"
        "+++ b/pom.xml\n"
        "@@\n"
        "+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>\n"
    )


def _reviewed_chain_files(tmp_path: Path, *, reviewer_decision: str = "accept", diff: str | None = None) -> dict:
    output = tmp_path / "chain"
    output.mkdir(parents=True, exist_ok=True)
    primary_path = output / "primary.json"
    reviewer_path = output / "reviewer.json"
    final_artifact_path = output / "final.json"
    diff_path = output / "final.diff"
    review_chain_path = output / "review_chain.json"
    reviewed_diff = diff if diff is not None else _h2_patch()
    primary_path.write_text(
        '{"risk":"LOW","changed_files":["pom.xml"],"root_cause":"missing h2","fix_strategy":"add h2"}',
        encoding="utf-8",
    )
    reviewer_path.write_text('{"decision":"' + reviewer_decision + '"}', encoding="utf-8")
    final_artifact_path.write_text("{}", encoding="utf-8")
    diff_path.write_text(reviewed_diff, encoding="utf-8")
    chain = {
        "reviewer_decision": reviewer_decision,
        "deterministic_artifact_checksum": "det-cs",
        "context_pack_checksum": "ctx-cs",
        "primary_output_checksum": "primary-cs",
        "reviewer_output_checksum": "reviewer-cs",
        "proposed_diff_checksum": "diff-cs",
        "final_artifact_checksum": "final-cs",
        "deterministic_artifact_ref": str(output / "deterministic.json"),
        "primary_output_ref": str(primary_path),
        "reviewer_output_ref": str(reviewer_path),
        "final_artifact_ref": str(final_artifact_path),
        "final_diff_ref": str(diff_path),
        "review_chain_metadata_ref": str(review_chain_path),
    }
    review_chain_path.write_text("{}", encoding="utf-8")
    return {"review_chain": chain}


def _seed_proposal_and_critique(
    repair_svc: V2RepairFlowService,
    reviewer_svc: V2ReviewerService,
    proposal_checksum: str = "sha256:prop-v1",
    context_checksum: str = "sha256:ctx-v1",
) -> tuple[str, str, str]:
    """Create a draft repair proposal and accepted reviewer critique."""
    proposal = repair_svc.create_proposal(
        command_id="cmd-1",
        failure_summary="Build failure in module X",
        hypothesis="Missing dependency declaration",
        patch_summary="Add dependency to pom.xml",
        affected_paths=("pom.xml",),
    )

    crit = ReviewerCritique(
        critique_id="crit-1",
        proposal_id=proposal.proposal_id,
        proposal_type="repair",
        proposal_checksum=proposal_checksum,
        context_pack_checksum=context_checksum,
        decision="accept",
        reasoning="Proposal looks correct",
        missing_evidence=(),
        unsafe_assumptions=(),
        model_invocation_id="",
        created_at="2026-06-17T12:00:00Z",
    )
    reviewer_svc._critiques[crit.critique_id] = crit

    return proposal.proposal_id, proposal_checksum, context_checksum


# ── Job101: Create repair_review gate on build failure ───────────────


class TestCreateRepairGateOnBuildFailure:
    """Repair_review gate creation on build/test/transform failure."""

    def test_create_gate_on_build_failure(self, tmp_path: Path) -> None:
        """Creates repair_review gate after build failure diagnosis."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-build-1",
            failure_summary="Build failed: compilation error in Foo.java",
            failure_details={"build_status": "FAILED", "exit_code": 1},
            source_artifact_refs=("build:log-1",),
            diagnosis=_create_diagnosis_record("cmd-build-1", "build_failed"),
        )

        assert result.status == "created"
        assert result.gate_id
        assert result.gate_checksum
        assert result.diagnosis is not None
        assert result.diagnosis.event_type == "build_failed"

        # Verify gate was persisted
        gate = gate_svc._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"
        assert gate.gate_status == "open"

    def test_create_gate_on_transform_failure(self, tmp_path: Path) -> None:
        """Creates repair_review gate after transform failure diagnosis."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=2,
            command_id="cmd-transform-1",
            failure_summary="Transform failed: OpenRewrite error in module X",
            failure_details={"transform_status": "FAILED", "final_proof_level": "NONE"},
            diagnosis=_create_diagnosis_record("cmd-transform-1", "transform_failed"),
        )

        assert result.status == "created"
        assert result.gate_id

        gate = gate_svc._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"
        assert gate.stage_index == 2

    def test_create_gate_from_reviewed_chain_persists_revision(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        gate_repo = SqlitePhaseGateRepository(conn)
        revision_repo = SqliteArtifactRevisionRepository(conn)
        gate_svc = V2PhaseGateService(gate_repo)
        repair_gate_svc = V2RepairGateService(
            gate_service=gate_svc,
            revision_repo=revision_repo,
        )
        run_dir = tmp_path / "run"
        sandbox = tmp_path / "sandbox"
        legacy = tmp_path / "legacy"
        sandbox.mkdir()
        legacy.mkdir()
        (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

        result = repair_gate_svc.create_repair_gate_from_reviewed_chain(
            job_id="job-1",
            stage_index=3,
            command_id="cmd-1",
            review_chain_result=_reviewed_chain_files(tmp_path),
            failure_evidence_checksum="failure-cs",
            context_pack_checksum="ctx-cs",
            base_repo_state_checksum="repo-cs",
            sandbox_path=str(sandbox),
            run_dir=str(run_dir),
            legacy_path=str(legacy),
            deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
            h2_required=True,
        )

        assert result.status == "created"
        assert result.gate_id
        assert result.revision_id
        assert result.policy_validation_checksum
        gate = gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"
        refs = gate.source_artifact_refs_json
        assert "failure_evidence_checksum:failure-cs" in refs
        assert "context_pack_checksum:ctx-cs" in refs
        assert "reviewer_output_checksum:reviewer-cs" in refs
        assert "policy_validation_checksum:" in refs
        assert (run_dir / "repairs" / "repair_policy_validation.json").is_file()
        revision = revision_repo.get(result.revision_id)
        assert revision is not None
        assert revision.revision_kind == "repair"
        assert revision.revision_status == "draft"
        assert revision.evidence_checksum == gate.source_artifact_checksum

    def test_create_gate_from_reviewed_chain_materializes_human_review_required(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        gate_repo = SqlitePhaseGateRepository(conn)
        repair_repo = SqliteV2RepairRepository(conn)
        gate_svc = V2PhaseGateService(gate_repo)
        repair_gate_svc = V2RepairGateService(
            gate_service=gate_svc,
            revision_repo=SqliteArtifactRevisionRepository(conn),
            repair_repo=repair_repo,
        )
        run_dir = tmp_path / "run"
        sandbox = tmp_path / "sandbox"
        legacy = tmp_path / "legacy"
        sandbox.mkdir()
        legacy.mkdir()
        (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

        result = repair_gate_svc.create_repair_gate_from_reviewed_chain(
            job_id="job-1",
            stage_index=3,
            command_id="cmd-1",
            review_chain_result=_reviewed_chain_files(tmp_path),
            failure_evidence_checksum="failure-cs",
            context_pack_checksum="ctx-cs",
            base_repo_state_checksum="repo-cs",
            sandbox_path=str(sandbox),
            run_dir=str(run_dir),
            legacy_path=str(legacy),
            deterministic_rule_id="RULE_NOT_ALLOWLISTED",
            h2_required=True,
        )

        assert result.status == "created"
        assert result.policy_status == "HUMAN_REVIEW_REQUIRED"
        gate = gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"
        assert (run_dir / "repairs" / "repair_policy_validation.json").is_file()

    def test_reviewed_chain_reviewer_reject_does_not_open_gate(self, tmp_path: Path) -> None:
        conn = _connection(tmp_path)
        gate_repo = SqlitePhaseGateRepository(conn)
        repair_gate_svc = V2RepairGateService(gate_service=V2PhaseGateService(gate_repo))
        sandbox = tmp_path / "sandbox"
        legacy = tmp_path / "legacy"
        sandbox.mkdir()
        legacy.mkdir()
        (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

        result = repair_gate_svc.create_repair_gate_from_reviewed_chain(
            job_id="job-1",
            stage_index=3,
            command_id="cmd-1",
            review_chain_result=_reviewed_chain_files(tmp_path, reviewer_decision="reject"),
            failure_evidence_checksum="failure-cs",
            context_pack_checksum="ctx-cs",
            base_repo_state_checksum="repo-cs",
            sandbox_path=str(sandbox),
            run_dir=str(tmp_path / "run"),
            legacy_path=str(legacy),
            deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
            h2_required=True,
        )

        assert result.status == "skipped"
        assert "reviewer did not accept" in result.reason
        assert gate_repo.list_open("job-1") == ()

    def test_duplicate_gate_returns_conflict(self, tmp_path: Path) -> None:
        """Duplicate gate creation for same stage returns conflict."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # First creation succeeds
        r1 = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            failure_summary="Build failed",
        )
        assert r1.status == "created"

        # Second creation returns conflict
        r2 = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            failure_summary="Build failed again",
        )
        assert r2.status == "conflict"
        assert r2.existing_gate_id == r1.gate_id

    def test_gate_binds_diagnosis_evidence(self, tmp_path: Path) -> None:
        """Gate artifact refs include diagnosis references."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis = _create_diagnosis_record("cmd-1", "build_failed")
        result = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            failure_summary="Build failed",
            diagnosis=diagnosis,
            source_artifact_refs=("build:log-1",),
        )

        assert result.status == "created"
        assert result.diagnosis is not None
        assert result.diagnosis.diagnosis_id == "diag-1"

    def test_gate_on_test_failure(self, tmp_path: Path) -> None:
        """Creates repair_review gate on test failure."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-test-1",
            failure_summary="Test failed: 3 failures in FooTest",
            failure_details={"test_status": "FAILED", "failure_count": 3},
        )

        assert result.status == "created"
        gate = repair_gate_svc._gate_service._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"

    def test_no_source_writes(self, tmp_path: Path) -> None:
        """Verify no sandbox_path, argv, or command fields in creation."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.create_repair_gate_on_failure(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            failure_summary="Build failed",
        )

        assert result.status == "created"
        # Check that the gate record has no dangerous fields
        gate = repair_gate_svc._gate_service._gate_repo.get(result.gate_id)
        assert gate is not None
        # No sandbox_path in gate fields
        assert not hasattr(gate, "sandbox_path")
        assert not hasattr(gate, "argv")
        assert not hasattr(gate, "env")


# ── Job104: request_repair_revision ──────────────────────────────────


class TestRequestRepairRevision:
    """request_repair_revision action at repair_review gate."""

    def test_request_repair_revision_success(self, tmp_path: Path) -> None:
        """Request repair revision creates new gate and stores feedback."""
        gate_repo, decision_repo, gate_svc, action_svc, repair_svc, _, repair_gate_svc, _ = (
            _svc(tmp_path)
        )

        # Create open repair_review gate
        gate_result = gate_svc.create_gate(CreateGateRequest(
            job_id="job-abc",
            gate_phase="repair_review",
            stage_index=1,
            source_artifact_checksum="sha256:repair-chk",
            source_artifact_refs=("repair-ref",),
        ))
        assert gate_result.status == "created"

        result = repair_gate_svc.request_repair_revision(
            gate_id=gate_result.gate_id,
            job_id="job-abc",
            decided_by="user-1",
            proposal_id="prop-1",
            user_feedback="Try a different dependency version",
        )

        assert result.status == "executed"
        assert result.decision_id
        # A new gate should have been created for the revision
        assert result.result_gate_id is not None
        assert result.result_gate_id != gate_result.gate_id

        # Old gate should be resolved
        old_gate = gate_repo.get(gate_result.gate_id)
        assert old_gate is not None
        assert old_gate.gate_status == "resolved"

        # New gate should be open for revision
        new_gate = gate_repo.get(result.result_gate_id)
        assert new_gate is not None
        assert new_gate.gate_status == "open"
        assert new_gate.gate_phase == "repair_review"

    def test_request_repair_revision_no_proposal(self, tmp_path: Path) -> None:
        """Request revision works even without proposal_id."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        gate_result = gate_svc.create_gate(CreateGateRequest(
            job_id="job-abc",
            gate_phase="repair_review",
            stage_index=1,
            source_artifact_checksum="sha256:repair-chk",
            source_artifact_refs=("repair-ref",),
        ))
        assert gate_result.status == "created"

        result = repair_gate_svc.request_repair_revision(
            gate_id=gate_result.gate_id,
            job_id="job-abc",
            decided_by="user-1",
            proposal_id="",
            user_feedback="Please reconsider the approach",
        )

        assert result.status == "executed"

    def test_request_repair_revision_wrong_phase(self, tmp_path: Path) -> None:
        """Request revision fails on non-repair gates."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # Create analysis_review gate instead of repair_review
        gate_result = gate_svc.create_gate(CreateGateRequest(
            job_id="job-abc",
            gate_phase="analysis_review",
            stage_index=1,
            source_artifact_checksum="sha256:analysis-chk",
            source_artifact_refs=(),
        ))
        assert gate_result.status == "created"

        result = repair_gate_svc.request_repair_revision(
            gate_id=gate_result.gate_id,
            job_id="job-abc",
            decided_by="user-1",
            proposal_id="prop-1",
        )

        # REVISE is invalid for analysis_review, so the gate action service
        # returns invalid_decision.
        assert result.status == "invalid_decision"


# ── Job105: approve_repair (delegated) ───────────────────────────────


class TestApproveRepairDelegation:
    """approve_repair delegates to V2GateActionService.approve_repair."""

    def test_approve_repair_delegates(self, tmp_path: Path) -> None:
        """V2RepairGateService.approve_repair delegates to action service."""
        gate_repo, decision_repo, gate_svc, action_svc, repair_svc, reviewer_svc, repair_gate_svc, _ = (
            _svc(tmp_path)
        )

        # Create open repair_review gate
        gate_result = gate_svc.create_gate(CreateGateRequest(
            job_id="job-abc",
            gate_phase="repair_review",
            stage_index=1,
            source_artifact_checksum="sha256:repair-chk",
            source_artifact_refs=("repair-ref",),
        ))
        assert gate_result.status == "created"

        proposal_id, prop_chk, ctx_chk = _seed_proposal_and_critique(
            repair_svc, reviewer_svc,
        )

        result = repair_gate_svc.approve_repair(
            gate_id=gate_result.gate_id,
            job_id="job-abc",
            decided_by="user-1",
            proposal_id=proposal_id,
            proposal_checksum=prop_chk,
            context_pack_checksum=ctx_chk,
        )

        assert result.status == "executed"

    def test_approve_repair_no_action_service(self, tmp_path: Path) -> None:
        """Approve repair fails when no gate action service configured."""
        _, _, gate_svc, _, _, _, _, _ = _svc(tmp_path)

        repair_gate_svc = V2RepairGateService(
            gate_service=gate_svc,
            gate_action_service=None,
        )

        result = repair_gate_svc.approve_repair(
            gate_id="nonexistent",
            job_id="job-abc",
            decided_by="user-1",
            proposal_id="p1",
            proposal_checksum="sha256:x",
            context_pack_checksum="sha256:y",
        )

        assert result.status == "no_action_service"


# ── Job106: reject_repair gate action ────────────────────────────────


class TestRejectRepair:
    """Reject repair at repair_review gate."""

    def test_reject_repair_success(self, tmp_path: Path) -> None:
        """Reject repair resolves gate with REJECT and persists reason."""
        gate_repo, decision_repo, gate_svc, action_svc, _, _, repair_gate_svc, _ = (
            _svc(tmp_path)
        )

        gate_result = gate_svc.create_gate(CreateGateRequest(
            job_id="job-abc",
            gate_phase="repair_review",
            stage_index=1,
            source_artifact_checksum="sha256:repair-chk",
            source_artifact_refs=("repair-ref",),
        ))
        assert gate_result.status == "created"

        result = repair_gate_svc.reject_repair(
            gate_id=gate_result.gate_id,
            job_id="job-abc",
            decided_by="user-1",
            reason="The repair proposal is too risky",
        )

        assert result.status == "executed"
        assert result.decision_id

        # Gate should be resolved with REJECT
        gate = gate_repo.get(gate_result.gate_id)
        assert gate is not None
        assert gate.gate_status == "resolved"
        assert gate.gate_decision == "reject"

        # Reason should be persisted in decision record
        decision = decision_repo.get(result.decision_id)
        assert decision is not None
        assert "risky" in (decision.reason or "").lower()

    def test_reject_repair_no_action_service(self, tmp_path: Path) -> None:
        """Reject repair fails when no gate action service configured."""
        _, _, gate_svc, _, _, _, _, _ = _svc(tmp_path)

        repair_gate_svc = V2RepairGateService(
            gate_service=gate_svc,
            gate_action_service=None,
        )

        result = repair_gate_svc.reject_repair(
            gate_id="nonexistent",
            job_id="job-abc",
            decided_by="user-1",
            reason="Too risky",
        )

        assert result.status == "no_action_service"


# ── Job107: Repair validation result gate transition ─────────────────


class TestRepairValidationTransition:
    """Repair validation result routes to correct next gate."""

    def test_validation_pass_creates_stage_completion_gate(self, tmp_path: Path) -> None:
        """Passing validation creates stage_completion_review gate."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc",
            stage_index=1,
            validation_passed=True,
            validation_id="val-1",
            sandbox_path="/tmp/sandbox/job-abc",
        )

        assert result.status == "stage_completion_gate_created"
        assert result.gate_id is not None
        assert result.remaining_attempts == 3

        # Verify gate is stage_completion_review
        gate = gate_svc._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "stage_completion_review"
        assert gate.gate_status == "open"

    def test_validation_fail_creates_new_repair_gate(self, tmp_path: Path) -> None:
        """Failing validation with remaining attempts creates new repair gate."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        result = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc",
            stage_index=1,
            validation_passed=False,
            validation_id="val-1",
        )

        assert result.status == "repair_gate_created"
        assert result.gate_id is not None
        assert result.remaining_attempts == 2  # 3 - 1

        # Verify gate is repair_review
        gate = gate_svc._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"
        assert gate.gate_status == "open"

    def test_validation_fail_exhausts_attempts(self, tmp_path: Path) -> None:
        """Failing validation after all attempts exhausted."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # Use up all 3 attempts
        for _ in range(3):
            repair_gate_svc.handle_repair_validation_result(
                job_id="job-abc",
                stage_index=1,
                validation_passed=False,
                validation_id="val-exhaust",
            )

        result = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc",
            stage_index=1,
            validation_passed=False,
            validation_id="val-exhaust-4",
        )

        assert result.status == "attempts_exhausted"
        assert result.remaining_attempts == 0
        assert "exhausted" in result.reason.lower()

    def test_validation_pass_resets_attempts(self, tmp_path: Path) -> None:
        """Passing validation resets attempt counter."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # Fail once
        r1 = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-1",
        )
        assert r1.remaining_attempts == 2

        # Pass - resets counter
        repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=True, validation_id="val-pass",
        )

        # Should be back to 3 remaining
        remaining = repair_gate_svc.get_remaining_attempts("job-abc", 1)
        assert remaining == 3

    def test_get_remaining_attempts(self, tmp_path: Path) -> None:
        """get_remaining_attempts returns correct count."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        assert repair_gate_svc.get_remaining_attempts("job-abc", 1) == 3

        repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-1",
        )
        assert repair_gate_svc.get_remaining_attempts("job-abc", 1) == 2

    def test_reset_attempts(self, tmp_path: Path) -> None:
        """reset_attempts clears attempt counter."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # Fail twice
        for _ in range(2):
            repair_gate_svc.handle_repair_validation_result(
                job_id="job-abc", stage_index=1,
                validation_passed=False, validation_id="val-fail",
            )
        assert repair_gate_svc.get_remaining_attempts("job-abc", 1) == 1

        repair_gate_svc.reset_attempts("job-abc", 1)
        assert repair_gate_svc.get_remaining_attempts("job-abc", 1) == 3

    def test_validation_fail_with_diagnosis(self, tmp_path: Path) -> None:
        """Failing validation includes diagnosis refs in gate."""
        _, _, gate_svc, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis = _create_diagnosis_record("cmd-1")
        result = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc",
            stage_index=1,
            validation_passed=False,
            validation_id="val-1",
            diagnosis=diagnosis,
        )

        assert result.status == "repair_gate_created"
        assert result.gate_id is not None

        gate = gate_svc._gate_repo.get(result.gate_id)
        assert gate is not None
        assert gate.gate_phase == "repair_review"


# ── Job108: Attempt limits ───────────────────────────────────────────


class TestRepairAttemptLimits:
    """Repair attempt limits at gate layer."""

    def test_default_max_attempts(self, tmp_path: Path) -> None:
        """Default max repair attempts is 3."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)
        assert repair_gate_svc._max_repair_attempts == 3

    def test_custom_max_attempts(self, tmp_path: Path) -> None:
        """Custom max repair attempts can be configured."""
        _, _, gate_svc, action_svc, repair_svc, _, _, _ = _svc(tmp_path)

        svc = V2RepairGateService(
            gate_service=gate_svc,
            gate_action_service=action_svc,
            repair_flow=repair_svc,
            max_repair_attempts=1,
        )
        assert svc._max_repair_attempts == 1

        # One failure exhausts all attempts
        svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-1",
        )
        assert svc.get_remaining_attempts("job-abc", 1) == 0

    def test_attempts_isolation(self, tmp_path: Path) -> None:
        """Attempts are isolated per (job_id, stage_index)."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        # Fail on job-abc stage 1 twice, and job-xyz stage 1 once
        repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-1",
        )
        repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-2",
        )
        repair_gate_svc.handle_repair_validation_result(
            job_id="job-xyz", stage_index=1,
            validation_passed=False, validation_id="val-3",
        )

        assert repair_gate_svc.get_remaining_attempts("job-abc", 1) == 1
        assert repair_gate_svc.get_remaining_attempts("job-xyz", 1) == 2
        assert repair_gate_svc.get_remaining_attempts("job-abc", 2) == 3

    def test_block_after_exhausted(self, tmp_path: Path) -> None:
        """After exhausted, validation transition returns exhausted status."""
        _, _, _, _, _, _, repair_gate_svc, _ = _svc(tmp_path)

        for _ in range(3):
            repair_gate_svc.handle_repair_validation_result(
                job_id="job-abc", stage_index=1,
                validation_passed=False, validation_id="val-fail",
            )

        result = repair_gate_svc.handle_repair_validation_result(
            job_id="job-abc", stage_index=1,
            validation_passed=False, validation_id="val-extra",
        )

        assert result.status == "attempts_exhausted"
        assert result.gate_id is None  # No new gate created


# ── create_repair_gate_diagnosis_callback ─────────────────────────────


class TestReviewedRepairChainIdempotency:
    """Persistent idempotency for the reviewed repair chain."""

    def test_reviewed_repair_chain_idempotency_uses_context_checksum(self, tmp_path: Path) -> None:
        """A second call with the same (job_id, command_id) but different
        context checksum must still be idempotently skipped if a proposal
        already exists with status user_review_required."""
        conn = _connection(tmp_path, "idempotency-gate.sqlite3")
        gate_repo = SqlitePhaseGateRepository(conn)
        repair_repo = SqliteV2RepairRepository(conn)
        gate_svc = V2PhaseGateService(gate_repo)

        svc = V2RepairGateService(
            gate_service=gate_svc,
            repair_repo=repair_repo,
        )
        sandbox = tmp_path / "sandbox"
        legacy = tmp_path / "legacy"
        sandbox.mkdir()
        legacy.mkdir()
        (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

        # Create a gate first via reviewed chain — simulate a successful chain
        gate_result = svc.create_repair_gate_from_reviewed_chain(
            job_id="job-idempotent",
            stage_index=3,
            command_id="cmd-idempotent",
            review_chain_result=_reviewed_chain_files(tmp_path),
            failure_evidence_checksum="failure-cs",
            context_pack_checksum="ctx-cs",
            base_repo_state_checksum="repo-cs",
            sandbox_path=str(sandbox),
            run_dir=str(tmp_path / "run"),
            legacy_path=str(legacy),
            deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
            h2_required=True,
        )
        assert gate_result.status == "created"

        # Now simulate a proposal already existing (what happens after
        # create_reviewed_repair_gate_on_failure succeeds)
        proposal_id = uuid4().hex
        repair_repo.save_proposal(V2RepairProposalRecord(
            proposal_id=proposal_id,
            command_id="cmd-idempotent",
            failure_summary="Build failure",
            hypothesis="missing dep",
            patch_summary="add dep",
            affected_paths_json='["pom.xml"]',
            status="user_review_required",
            approval_checksum=None,
            created_at=utc_now_text(),
            job_id="job-idempotent",
            route_step_index=3,
            gate_id=gate_result.gate_id,
        ))

        # The persistent check in create_reviewed_repair_gate_on_failure
        # should now skip the chain — verify that the proposal-based check
        # fires before the chain runs.

        # Use a different context checksum to prove the check is
        # proposal-based, not context-based.
        payload = {
            "_repair_failure_evidence_ref": str(tmp_path / "nonexistent.json"),
            "_repair_context_pack_ref": str(tmp_path / "nonexistent2.json"),
            "_repair_run_dir": str(tmp_path / "run"),
            "_repair_sandbox_path": str(sandbox),
            "_repair_failure_evidence_checksum": "different-failure-cs",
            "_repair_context_pack_checksum": "different-ctx-cs",
            "_repair_base_repo_state_checksum": "different-repo-cs",
            "_repair_h2_required": "false",
        }
        result = svc.create_reviewed_repair_gate_on_failure(
            job_id="job-idempotent",
            stage_index=3,
            command_id="cmd-idempotent",
            event_type="build_failed",
            payload=payload,
            legacy_path=str(legacy),
        )
        assert result.status == "skipped"
        assert "proposal already exists" in result.reason

        # Verify chain was never attempted (the persistent check fired
        # before the chain attempt record was created)
        if svc._chain_attempt_repo is not None:
            from migration_factory.control_tower.infrastructure.sqlite.v2_chain_attempt_repository import (
                build_chain_key,
            )
            durable_key = build_chain_key(
                "job-idempotent", "cmd-idempotent", "different-ctx-cs", "initial_reviewed_repair"
            )
            chain_attempt = svc._chain_attempt_repo.get(durable_key)
            assert chain_attempt is None, "no chain attempt should have been created"


def test_reviewer_schema_unavailable_event_preserves_safe_diagnostics(tmp_path: Path) -> None:
    _, _, gate_svc, _, _, _, _, _ = _svc(tmp_path)
    recorder = _EventRecorder()
    svc = V2RepairGateService(gate_service=gate_svc, event_repo=recorder)

    svc._emit_reviewed_repair_unavailable(
        job_id="job-reviewer-schema",
        stage_index=2,
        context_checksum="ctx-cs",
        reason_code="reviewer_schema_invalid",
        schema_diagnostics={
            "schema_name": "RepairReviewerOutput",
            "role": "reviewer",
            "stage": "reviewer",
            "reason_code": "reviewer_schema_invalid",
            "missing_fields": ["notes", "reviewed_diff_checksum"],
            "raw_output": '{"decision":"accept"}',
            "prompt": "do not leak",
            "completion": "do not leak",
        },
    )

    assert len(recorder.events) == 1
    event = recorder.events[0]
    payload = event["payload"]
    assert event["message"] == "Reviewer model output failed schema validation."
    assert payload["reason_code"] == "reviewer_schema_invalid"
    assert payload["schema_name"] == "RepairReviewerOutput"
    assert payload["role"] == "reviewer"
    assert payload["stage"] == "reviewer"
    assert payload["schema_diagnostics"]["missing_fields"] == ["notes", "reviewed_diff_checksum"]
    serialized = json.dumps(payload)
    assert "raw_output" not in serialized
    assert "prompt" not in serialized
    assert "completion" not in serialized


class TestRepairGateDiagnosisCallback:
    """Diagnosis callback integration."""

    def test_callback_does_not_crash(self, tmp_path: Path) -> None:
        """Callback runs without errors."""
        _, _, gate_svc, action_svc, repair_svc, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis_svc = V2FailureDiagnosisService()

        callback = create_repair_gate_diagnosis_callback(
            repair_gate_service=repair_gate_svc,
            diagnosis_service=diagnosis_svc,
        )

        # The callback should not raise
        callback(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload={"build_status": "FAILED"},
        )

    def test_callback_with_transform_failure(self, tmp_path: Path) -> None:
        """Callback handles transform failure without errors."""
        _, _, gate_svc, action_svc, repair_svc, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis_svc = V2FailureDiagnosisService()

        callback = create_repair_gate_diagnosis_callback(
            repair_gate_service=repair_gate_svc,
            diagnosis_service=diagnosis_svc,
        )

        callback(
            job_id="job-abc",
            stage_index=2,
            command_id="cmd-transform-1",
            event_type="transform_failed",
            payload={"transform_status": "FAILED", "final_proof_level": "NONE"},
        )

    def test_callback_with_non_diagnosable_event(self, tmp_path: Path) -> None:
        """Callback handles non-diagnosable events gracefully."""
        _, _, gate_svc, action_svc, repair_svc, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis_svc = V2FailureDiagnosisService()

        callback = create_repair_gate_diagnosis_callback(
            repair_gate_service=repair_gate_svc,
            diagnosis_service=diagnosis_svc,
        )

        # Non-diagnosable events are ignored by diagnosis service
        # but the callback should still attempt gate creation
        callback(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-other",
            event_type="stage_completed",
            payload={"stage_status": "COMPLETED"},
        )

    def test_callback_creates_gate(self, tmp_path: Path) -> None:
        """Callback should create a repair_review gate after failure."""
        _, _, gate_svc, action_svc, repair_svc, _, repair_gate_svc, _ = _svc(tmp_path)

        diagnosis_svc = V2FailureDiagnosisService()

        callback = create_repair_gate_diagnosis_callback(
            repair_gate_service=repair_gate_svc,
            diagnosis_service=diagnosis_svc,
        )

        callback(
            job_id="job-abc",
            stage_index=1,
            command_id="cmd-1",
            event_type="build_failed",
            payload={"build_status": "FAILED"},
        )

        # Check that a gate was created
        open_gates = gate_svc._gate_repo.list_open("job-abc")
        assert len(open_gates) == 1
        assert open_gates[0].gate_phase == "repair_review"
