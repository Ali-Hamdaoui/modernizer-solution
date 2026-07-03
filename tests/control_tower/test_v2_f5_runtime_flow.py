"""Service-level proof for the governed F5 repair runtime."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import migration_factory.control_tower.application.v2_repair_flow as v2_repair_flow
from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelResult,
)
from migration_factory.control_tower.application.v2_gate_action_service import (
    V2GateActionService,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_phase_gate_service import (
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_repair_flow import V2RepairFlowService
from migration_factory.control_tower.application.v2_repair_gate_service import (
    V2RepairGateService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_gate_decision_repository import (
    SqliteGateDecisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_phase_gate_repository import (
    SqlitePhaseGateRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
    SqliteV2ReviewerRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    SqliteV2LLMInvocationRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_event_repository import (
    SqliteV2JobEventRepository,
)
from migration_factory.orchestrator.repair_review_chain import produce_repair_review_chain
from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    build_failure_evidence,
)
from migration_factory.repair_loop.patch_apply import PatchApplyResult
from migration_factory.repair_loop.repair_context import build_repair_context_pack
from migration_factory.repair_loop.validation_runner import ValidationResult


REVIEWED_DIFF = """\
diff --git a/pom.xml b/pom.xml
--- a/pom.xml
+++ b/pom.xml
@@
+<dependency><groupId>com.h2database</groupId><artifactId>h2</artifactId><scope>runtime</scope></dependency>
"""


def _write_repair_inputs(
    tmp_path: Path,
    *,
    job_id: str = "job-f5",
    command_id: str = "cmd-f5",
) -> tuple[dict[str, str], FakeAzureRepairClient]:
    run_dir = tmp_path / "run"
    repair_dir = run_dir / "repairs"
    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy"
    repair_dir.mkdir(parents=True, exist_ok=True)
    sandbox.mkdir(exist_ok=True)
    legacy.mkdir(exist_ok=True)
    (sandbox / "pom.xml").write_text("<project/>\n", encoding="utf-8")
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        job_id=job_id,
        stage_index=3,
        command_id=command_id,
        failure_summary="Build failed: missing H2",
        source_profile="springboot-3.5-java21",
        target_profile="springboot-4.0-java21",
        changed_files=("pom.xml",),
    )
    context = build_repair_context_pack(
        failure_evidence=evidence,
        job_id=evidence.job_id,
        stage_index=evidence.stage_index,
        command_id=evidence.command_id,
        source_profile=evidence.source_profile,
        target_profile=evidence.target_profile,
        changed_files=evidence.changed_files,
    )
    evidence_path = repair_dir / "repair_failure_evidence.json"
    context_path = repair_dir / "repair_context_pack.json"
    from migration_factory.repair_loop.failure_evidence import failure_evidence_to_dict
    from migration_factory.repair_loop.repair_context import context_pack_to_dict

    evidence_path.write_text(json.dumps(failure_evidence_to_dict(evidence), indent=2), encoding="utf-8")
    context_path.write_text(json.dumps(context_pack_to_dict(context), indent=2), encoding="utf-8")
    return (
        {
            "_repair_failure_evidence_ref": str(evidence_path),
            "_repair_context_pack_ref": str(context_path),
            "_repair_run_dir": str(run_dir),
            "_repair_sandbox_path": str(sandbox),
            "_repair_failure_evidence_checksum": evidence.content_checksum,
            "_repair_context_pack_checksum": context.context_pack_checksum,
            "_repair_base_repo_state_checksum": context.base_repo_state_checksum,
            "_repair_h2_required": "true",
            "legacy_path": str(legacy),
        },
        FakeAzureRepairClient(),
    )


class FakeAzureRepairClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _extract_checksum(self, prompt: str, field: str) -> str:
        import re
        m = re.search(rf'"{field}":\s*"([^"]+)"', prompt)
        return m.group(1) if m else ""

    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **kwargs: Any
    ) -> V2AssistantModelResult:
        self.calls.append({"role": role, **kwargs})
        if role == V2ModelRole.PROPOSER:
            content = json.dumps(
                {
                    "root_cause": "Missing H2 runtime dependency",
                    "fix_strategy": "Add H2 runtime dependency to pom.xml",
                    "changed_files": ["pom.xml"],
                    "proposed_diff": REVIEWED_DIFF,
                    "risk": "LOW",
                    "confidence": 0.92,
                    "rationale": "Build failure requires the runtime dependency.",
                    "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                },
                sort_keys=True,
            )
        else:
            content = json.dumps(
                {
                    "decision": "accept",
                    "notes": ["Diff is scoped to pom.xml"],
                    "confidence": 0.95,
                    "risks": [],
                    "policy_concerns": [],
                    "changed_files_verified": True,
                    "diff_parseable": True,
                    "reviewed_context_checksum": self._extract_checksum(prompt, "reviewed_context_checksum"),
                    "reviewed_primary_output_checksum": self._extract_checksum(prompt, "reviewed_primary_output_checksum"),
                    "reviewed_diff_checksum": self._extract_checksum(prompt, "reviewed_diff_checksum"),
                },
                sort_keys=True,
            )
        return V2AssistantModelResult(
            content=content,
            source="azure_openai",
            model_status="live_ok",
            provider="azure_openai",
            role=role.value,
            success=True,
            redacted_summary="user-selected Azure model available",
            failure_reason="",
        )


class ReviewerUnavailableRepairClient(FakeAzureRepairClient):
    def answer_with_role(
        self, *, role: V2ModelRole, prompt: str, fallback: str, **kwargs: Any
    ) -> V2AssistantModelResult:
        if role == V2ModelRole.REVIEWER:
            self.calls.append({"role": role, **kwargs})
            return V2AssistantModelResult(
                content='{"decision":"revise","reasoning":"Reviewer model output unavailable","missing_evidence":["Reviewer model output unavailable"],"unsafe_assumptions":["No independent model critique was completed"]}',
                source="deterministic",
                model_status="fallback",
                provider="deterministic",
                role=role.value,
                success=False,
                redacted_summary='{"decision":"revise","missing_evidence":["Reviewer model output unavailable"],"reasoning":"Reviewer model unavailable; fail-closed review requires revision or manual evidence review.","unsafe_assumptions":["No independent model critique was completed"]}',
                failure_reason="reviewer_model_unavailable",
            )
        return super().answer_with_role(role=role, prompt=prompt, fallback=fallback, **kwargs)


def test_initial_build_failure_creates_reviewed_repair_gate_and_persistence(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        str(tmp_path / "initial-f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    repair_gate_service = V2RepairGateService(
        gate_service=V2PhaseGateService(gate_repo),
        repair_repo=SqliteV2RepairRepository(conn),
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=SqliteV2LLMInvocationRepository(conn),
    )
    payload, model_client = _write_repair_inputs(tmp_path)

    result = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-f5",
        stage_index=3,
        command_id="cmd-f5",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )

    assert result.status == "created"
    assert [call["role"] for call in model_client.calls] == [
        V2ModelRole.PROPOSER,
        V2ModelRole.REVIEWER,
    ]
    run_dir = Path(payload["_repair_run_dir"])
    assert (run_dir / "repair_chain" / "primary_repair_llm_output.json").is_file()
    assert (run_dir / "repair_chain" / "reviewer_repair_llm_output.json").is_file()
    assert (run_dir / "repair_chain" / "final_reviewed_repair.diff").is_file()
    assert (run_dir / "repair_chain" / "review_chain.json").is_file()

    repair_repo = SqliteV2RepairRepository(conn)
    proposal = repair_repo.get_current_proposal_for_job("job-f5")
    assert proposal is not None
    assert proposal.gate_id == result.gate_id
    assert proposal.diff_ref and proposal.diff_ref.endswith("final_reviewed_repair.diff")
    assert proposal.diff_checksum
    assert proposal.reviewer_verdict_id
    assert proposal.reviewer_output_checksum
    assert Path(proposal.failure_evidence_ref).name == Path(str(payload["_repair_failure_evidence_ref"])).name
    assert Path(proposal.repair_context_ref).name == Path(str(payload["_repair_context_pack_ref"])).name

    critiques = SqliteV2ReviewerRepository(conn).list_critiques_by_proposal(proposal.proposal_id)
    assert len(critiques) == 1
    assert critiques[0].decision == "accept"

    invocations = SqliteV2LLMInvocationRepository(conn).list_by_job("job-f5")
    assert {item.role for item in invocations} == {"main", "reviewer"}
    assert {item.responsibility for item in invocations} == {"repair_proposal", "repair_review"}
    assert len({item.invocation_id for item in invocations}) == 2
    assert all(item.proposal_id == proposal.proposal_id for item in invocations)
    assert all(item.gate_id == result.gate_id for item in invocations)


def test_reviewer_fallback_emits_unavailable_event_and_no_proposal(tmp_path: Path) -> None:
    conn = sqlite3.connect(
        str(tmp_path / "reviewer-unavailable.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    service = V2RepairGateService(
        gate_service=V2PhaseGateService(SqlitePhaseGateRepository(conn)),
        repair_repo=SqliteV2RepairRepository(conn),
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=SqliteV2LLMInvocationRepository(conn),
        event_repo=SqliteV2JobEventRepository(conn),
    )
    payload, _ = _write_repair_inputs(tmp_path, job_id="job-fallback", command_id="cmd-fallback")

    result = service.create_reviewed_repair_gate_on_failure(
        job_id="job-fallback",
        stage_index=3,
        command_id="cmd-fallback",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=ReviewerUnavailableRepairClient(),
    )

    assert result.status == "skipped"
    assert SqliteV2RepairRepository(conn).get_current_proposal_for_job("job-fallback") is None
    invocations = SqliteV2LLMInvocationRepository(conn).list_by_job("job-fallback")
    assert {item.responsibility for item in invocations} == {"repair_proposal", "repair_review"}
    reviewer = next(item for item in invocations if item.responsibility == "repair_review")
    assert reviewer.status == "fallback"
    assert reviewer.redacted_error == "reviewer_model_unavailable"

    events = SqliteV2JobEventRepository(conn).list_by_job("job-fallback")
    unavailable = [event for event in events if event.type == "reviewed_repair_unavailable"]
    assert len(unavailable) == 1
    payload_json = unavailable[0].payload_json
    assert "reviewer_model_unavailable" in payload_json
    for forbidden in ("endpoint", "api_key", "deployment", "prompt", "completion", "sandbox_path", "_repair_sandbox_path"):
        assert forbidden not in payload_json


def test_f5_failure_to_reviewed_diff_apply_and_proof(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conn = sqlite3.connect(
        str(tmp_path / "f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    decision_repo = SqliteGateDecisionRepository(conn)
    gate_service = V2PhaseGateService(gate_repo)
    reviewer_service = V2ReviewerService()
    repair_service = V2RepairFlowService(reviewer_service=reviewer_service)
    action_service = V2GateActionService(
        gate_repo,
        decision_repo,
        gate_service,
        repair_service=repair_service,
    )
    repair_gate_service = V2RepairGateService(
        gate_service=gate_service,
        gate_action_service=action_service,
        repair_flow=repair_service,
    )
    run_dir = tmp_path / "run"
    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy"
    sandbox.mkdir()
    legacy.mkdir()
    (sandbox / "pom.xml").write_text("<project/>\n", encoding="utf-8")

    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        job_id="job-f5",
        stage_index=3,
        command_id="cmd-f5",
        failure_summary="Build failed: missing H2",
        source_profile="springboot-3.5-java21",
        target_profile="springboot-4.0-java21",
        changed_files=("pom.xml",),
    )
    context = build_repair_context_pack(
        failure_evidence=evidence,
        job_id=evidence.job_id,
        stage_index=evidence.stage_index,
        command_id=evidence.command_id,
        source_profile=evidence.source_profile,
        target_profile=evidence.target_profile,
        changed_files=evidence.changed_files,
    )
    model_client = FakeAzureRepairClient()
    chain_result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=run_dir / "repair_chain",
        source_profile=evidence.source_profile,
        target_profile=evidence.target_profile,
        model_client=model_client,
    )
    assert [call["role"] for call in model_client.calls] == [
        V2ModelRole.PROPOSER,
        V2ModelRole.REVIEWER,
    ]
    assert all(call["require_schema"] is True for call in model_client.calls)
    chain = chain_result["review_chain"]

    gate_result = repair_gate_service.create_repair_gate_from_reviewed_chain(
        job_id="job-f5",
        stage_index=3,
        command_id="cmd-f5",
        review_chain_result=chain_result,
        failure_evidence_checksum=evidence.artifact_checksum,
        context_pack_checksum=context.context_pack_checksum,
        base_repo_state_checksum="repo-state-1",
        sandbox_path=str(sandbox),
        run_dir=str(run_dir),
        legacy_path=str(legacy),
        deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        h2_required=True,
    )
    assert gate_result.status == "created"
    assert gate_result.policy_validation_checksum

    proposal = repair_service.create_proposal(
        command_id="cmd-f5",
        failure_summary=evidence.failure_summary,
        hypothesis=chain.get("root_cause", "missing dependency"),
        patch_summary=chain.get("fix_strategy", "add dependency"),
        affected_paths=("pom.xml",),
    )
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_type="repair",
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=context.context_pack_checksum,
        decision="accept",
        reasoning="Reviewed repair chain accepted.",
    )
    approval = action_service.approve_repair(
        gate_id=gate_result.gate_id,
        job_id="job-f5",
        decided_by="human-1",
        proposal_id=proposal.proposal_id,
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum=context.context_pack_checksum,
        reviewer_output_checksum=chain["reviewer_output_checksum"],
        final_reviewed_diff_checksum=chain["proposed_diff_checksum"],
        policy_validation_checksum=gate_result.policy_validation_checksum,
        base_repo_state_checksum="repo-state-1",
        final_reviewed_artifact_checksum=chain["final_artifact_checksum"],
        expected_gate_checksum=gate_result.gate_checksum,
    )
    assert approval.status == "executed"

    monkeypatch.setattr(
        v2_repair_flow,
        "apply_patch_to_sandbox",
        lambda **kwargs: PatchApplyResult(
            status="APPLIED",
            reason="applied",
            patch_path=Path(kwargs["run_dir"]) / "repairs" / "applied.patch",
            snapshot_dir=Path(kwargs["run_dir"]) / "snapshots" / "attempt-1",
            touched_paths=tuple(kwargs["touched_paths"]),
            created_paths=(),
            before_hashes={"pom.xml": "before"},
            after_hashes={"pom.xml": "after"},
            errors=(),
        ),
    )
    action = repair_service.apply_reviewed_repair_diff(
        proposal_id=proposal.proposal_id,
        final_diff_ref=chain["final_diff_ref"],
        final_diff_checksum=chain["proposed_diff_checksum"],
        reviewer_output_checksum=chain["reviewer_output_checksum"],
        expected_reviewer_output_checksum=chain["reviewer_output_checksum"],
        policy_validation_checksum=gate_result.policy_validation_checksum,
        expected_policy_validation_checksum=gate_result.policy_validation_checksum,
        policy_status="allowed",
        expected_base_repo_state_checksum="repo-state-1",
        current_base_repo_state_checksum="repo-state-1",
        target_path="pom.xml",
        run_id="cmd-f5",
        run_dir=run_dir,
        sandbox_path=sandbox,
        legacy_path=legacy,
        deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        h2_required=True,
        validation_runner=lambda **kwargs: ValidationResult(
            passed=True,
            build_status="passed",
            test_status="passed",
            h2_status="passed",
            validation_commands=("mvn test",),
            warnings=(),
            errors=(),
            artifact_refs={"validation_log": "validation.log"},
        ),
    )

    assert action.status == "applied"
    proof_path = run_dir / "repairs" / "repair_proof.json"
    assert proof_path.is_file()
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    assert proof["status"] == "REPAIR_VALIDATED"
    assert proof["repair_rerun_result_checksum"]
    assert sha256_canonical_json({"unified_diff": REVIEWED_DIFF}) == chain["proposed_diff_checksum"]


# ── F5 TASK 4: End-to-end proof and red-team tests ────────────────────


def test_f5_reviewer_bypass_fails(tmp_path: Path, monkeypatch) -> None:
    """Applying a diff that was never reviewed is rejected."""
    import sqlite3
    from migration_factory.control_tower.application.v2_repair_flow import V2RepairFlowService
    from migration_factory.control_tower.application.v2_reviewer_service import V2ReviewerService
    from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations

    conn = sqlite3.connect(str(tmp_path / "bypass.sqlite3"), check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    reviewer_service = V2ReviewerService()
    repair_service = V2RepairFlowService(reviewer_service=reviewer_service)

    proposal = repair_service.create_proposal(
        command_id="cmd-bypass",
        failure_summary="build failed",
        hypothesis="fix",
        patch_summary="add dep",
        affected_paths=("pom.xml",),
    )

    with pytest.raises(ValueError, match="blocked by reviewer gate"):
        repair_service.approve_proposal(
            proposal_id=proposal.proposal_id,
            approval_checksum="sha256:fake",
            proposal_checksum=proposal.proposal_checksum,
            context_pack_checksum="sha256:cp",
        )


def test_f5_stale_repo_state_fails(tmp_path: Path) -> None:
    """Applying a reviewed diff to a stale repo is rejected."""
    from migration_factory.control_tower.application.v2_repair_flow import V2RepairFlowService
    from migration_factory.control_tower.application.v2_reviewer_service import V2ReviewerService
    from migration_factory.control_tower.domain.checksums import sha256_canonical_json

    reviewer_service = V2ReviewerService()
    repair_service = V2RepairFlowService(reviewer_service=reviewer_service)

    proposal = repair_service.create_proposal(
        command_id="cmd-stale",
        failure_summary="build failed",
        hypothesis="fix",
        patch_summary="add dep",
        affected_paths=("pom.xml",),
    )
    reviewer_service.record_critique(
        proposal_id=proposal.proposal_id,
        proposal_type="repair",
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum="sha256:cp",
        decision="accept",
        reasoning="ok",
    )
    repair_service.approve_proposal(
        proposal_id=proposal.proposal_id,
        approval_checksum="sha256:gc",
        proposal_checksum=proposal.proposal_checksum,
        context_pack_checksum="sha256:cp",
    )

    diff_file = tmp_path / "diff.patch"
    diff_file.parent.mkdir(exist_ok=True)
    diff_content = "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@\n+<dep/>\n"
    diff_file.write_text(diff_content, encoding="utf-8")
    diff_checksum = sha256_canonical_json({"unified_diff": diff_content})

    (tmp_path / "sandbox").mkdir(exist_ok=True)
    (tmp_path / "legacy").mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="stale"):
        repair_service.apply_reviewed_repair_diff(
            proposal_id=proposal.proposal_id,
            final_diff_ref=str(diff_file),
            final_diff_checksum=diff_checksum,
            reviewer_output_checksum="sha256:ro",
            expected_reviewer_output_checksum="sha256:ro",
            policy_validation_checksum="sha256:pv",
            expected_policy_validation_checksum="sha256:pv",
            policy_status="allowed",
            expected_base_repo_state_checksum="sha256:old",
            current_base_repo_state_checksum="sha256:new",
            target_path="pom.xml",
            run_dir=tmp_path,
            sandbox_path=tmp_path / "sandbox",
            legacy_path=tmp_path / "legacy",
            deterministic_rule_id="DEPENDENCY_ADD_H2_RUNTIME",
        )


def test_f5_missing_proposer_model_fails_closed(tmp_path: Path) -> None:
    """If the proposer model is unavailable, the review chain fails closed."""
    from migration_factory.orchestrator.repair_review_chain import (
        produce_repair_review_chain,
        RepairReviewChainProductionError,
    )
    from migration_factory.repair_loop.failure_evidence import (
        FailureSource,
        build_failure_evidence,
    )
    from migration_factory.repair_loop.repair_context import build_repair_context_pack
    from pathlib import Path
    import json

    from migration_factory.control_tower.application.v2_assistant_model_client import (
        V2AssistantModelResult,
    )

    class _DeadProposerClient:
        def answer_with_role(self, *, role, prompt, fallback, output_schema_name=None, require_schema=True):
            success = role.value != "proposer"
            return V2AssistantModelResult(
                content=json.dumps({"decision": "accept", "notes": [], "confidence": 0.8}),
                source="azure_openai",
                model_status="blocked" if not success else "live_ok",
                provider="azure_openai",
                role=role.value,
                success=success,
                redacted_summary="model unavailable",
                failure_reason="Proposer model offline" if not success else "",
            )

    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-fail",
        failure_summary="Build failure",
    )
    context = build_repair_context_pack(failure_evidence=evidence)

    with pytest.raises(RepairReviewChainProductionError, match="primary repair model failed"):
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context,
            output_dir=tmp_path / "dummy_chain",
            model_client=_DeadProposerClient(),
        )


def test_f5_missing_reviewer_model_fails_closed(tmp_path: Path) -> None:
    """If the reviewer model is unavailable, the review chain fails closed."""
    from migration_factory.orchestrator.repair_review_chain import (
        produce_repair_review_chain,
        RepairReviewChainProductionError,
    )
    from migration_factory.repair_loop.failure_evidence import (
        FailureSource,
        build_failure_evidence,
    )
    from migration_factory.repair_loop.repair_context import build_repair_context_pack
    from pathlib import Path
    import json

    from migration_factory.control_tower.application.v2_assistant_model_client import (
        V2AssistantModelResult,
    )

    class _DeadReviewerClient:
        def answer_with_role(self, *, role, prompt, fallback, output_schema_name=None, require_schema=True):
            if role.value == "proposer":
                return V2AssistantModelResult(
                    content=json.dumps({
                        "root_cause": "fix", "fix_strategy": "patch",
                        "changed_files": ["pom.xml"],
                        "proposed_diff": "diff --git a/pom.xml b/pom.xml\n--- a/pom.xml\n+++ b/pom.xml\n@@\n+<dep/>\n",
                        "risk": "LOW", "confidence": 0.9, "rationale": "fix",
                        "deterministic_rule_id": "DEPENDENCY_ADD_H2_RUNTIME",
                    }),
                    source="azure_openai", model_status="live_ok",
                    provider="azure_openai", role="proposer",
                    success=True, redacted_summary="ok", failure_reason="",
                )
            return V2AssistantModelResult(
                content="{}",
                source="azure_openai",
                model_status="blocked",
                provider="azure_openai",
                role="reviewer",
                success=False,
                redacted_summary="reviewer unavailable",
                failure_reason="Reviewer model offline",
            )

    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        command_id="cmd-fail",
        failure_summary="Build failure",
    )
    context = build_repair_context_pack(failure_evidence=evidence)

    with pytest.raises(RepairReviewChainProductionError, match="review"):
        produce_repair_review_chain(
            failure_evidence=evidence,
            context_pack=context,
            output_dir=tmp_path / "dummy_chain2",
            model_client=_DeadReviewerClient(),
        )


def test_f5_copilot_repair_loop_quarantined() -> None:
    """Legacy Copilot repair loop is quarantined and not authoritative."""
    from migration_factory.repair_loop.orchestrator import run_post_failure_repair_loop

    state = {
        "copilot_failure_agent_enabled": True,
        "repair_loop_enabled": True,
        "run_id": "test-run",
        "run_dir": "/tmp",
        "max_repair_attempts": 5,
        "copilot_first_attempt_timeout_seconds": 120,
        "copilot_subsequent_timeout_seconds": 120,
        "copilot_model": "gpt-4o",
        "copilot_enabled": True,
        "copilot_cli_path": "/usr/local/bin/copilot",
        "artifact_refs": {},
    }
    result = run_post_failure_repair_loop(state, copilot_invoker=lambda **kw: {})
    assert result["repair_loop_status"] == "BLOCKED"
    assert result["repair_loop_quarantined"] is True
    assert "copilot_removed" in result["repair_blocker"]


def test_earlier_chain_failure_does_not_block_later_success(tmp_path: Path) -> None:
    """Earlier proposer_schema_invalid + later successful chain still creates proposal."""
    conn = sqlite3.connect(
        str(tmp_path / "idempotent-f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    event_repo = SqliteV2JobEventRepository(conn)
    llm_repo = SqliteV2LLMInvocationRepository(conn)
    repair_gate_service = V2RepairGateService(
        gate_service=V2PhaseGateService(gate_repo),
        repair_repo=SqliteV2RepairRepository(conn),
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=llm_repo,
        event_repo=event_repo,
    )

    # ── Inject an earlier failure event (simulates first failed chain) ──
    event_repo.save(
        job_id="job-idempotent",
        stage=3,
        event_type="repair_primary_schema_invalid",
        status="blocked",
        message="Earlier failure event",
        payload={"reason_code": "proposer_schema_invalid", "job_id": "job-idempotent"},
    )
    assert len(event_repo.list_by_job("job-idempotent")) == 1

    # ── Run a successful chain with persistence ──
    payload, model_client = _write_repair_inputs(tmp_path, job_id="job-idempotent", command_id="cmd-idempotent")
    result = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-idempotent",
        stage_index=3,
        command_id="cmd-idempotent",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )

    assert result.status == "created"
    repair_repo = SqliteV2RepairRepository(conn)
    proposal = repair_repo.get_current_proposal_for_job("job-idempotent")
    assert proposal is not None, "Later successful chain must create proposal despite earlier failure event"
    assert proposal.status == "user_review_required"

    invocations = llm_repo.list_by_job("job-idempotent")
    assert all(item.proposal_id == proposal.proposal_id for item in invocations)
    assert all(item.gate_id == result.gate_id for item in invocations)


def test_successful_chain_does_not_emit_materialization_failed(tmp_path: Path) -> None:
    """A successful chain+persistence must NOT emit a materialization_failed event."""
    conn = sqlite3.connect(
        str(tmp_path / "matfail-f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    event_repo = SqliteV2JobEventRepository(conn)
    repair_repo = SqliteV2RepairRepository(conn)

    repair_gate_service = V2RepairGateService(
        gate_service=V2PhaseGateService(gate_repo),
        repair_repo=repair_repo,
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=SqliteV2LLMInvocationRepository(conn),
        event_repo=event_repo,
    )

    payload, model_client = _write_repair_inputs(tmp_path, job_id="job-matfail", command_id="cmd-matfail")
    result = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-matfail",
        stage_index=3,
        command_id="cmd-matfail",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )

    assert result.status == "created"
    proposal = repair_repo.get_current_proposal_for_job("job-matfail")
    assert proposal is not None

    events = event_repo.list_by_job("job-matfail")
    matfail_events = [e for e in events if e.type == "reviewed_repair_materialization_failed"]
    assert len(matfail_events) == 0


def test_duplicate_failure_callback_does_not_start_second_reviewed_chain(tmp_path: Path) -> None:
    """A second failure callback for the same (job_id, command_id) must NOT start
    a second repair chain or create a second proposal."""
    conn = sqlite3.connect(
        str(tmp_path / "duplicate-f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    repair_repo = SqliteV2RepairRepository(conn)
    llm_repo = SqliteV2LLMInvocationRepository(conn)

    repair_gate_service = V2RepairGateService(
        gate_service=V2PhaseGateService(gate_repo),
        repair_repo=repair_repo,
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=llm_repo,
    )

    payload, model_client = _write_repair_inputs(tmp_path, job_id="job-dup", command_id="cmd-dup")

    # First call — should succeed
    r1 = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-dup",
        stage_index=3,
        command_id="cmd-dup",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )
    assert r1.status == "created"

    # Second call (simulates duplicate failure event) — must NOT create a
    # second proposal or run the chain again.
    r2 = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-dup",
        stage_index=3,
        command_id="cmd-dup",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )
    assert r2.status == "skipped"
    assert "proposal already exists" in r2.reason or "duplicate repair chain" in r2.reason

    # Verify only one proposal and two invocations (proposer + reviewer) exist
    proposals = repair_repo.list_proposals_by_job("job-dup")
    assert len(proposals) == 1

    invocations = llm_repo.list_by_job("job-dup")
    # Only the first chain's invocations (no extra unbound fallback)
    bound = [i for i in invocations if i.proposal_id == proposals[0].proposal_id]
    assert len(bound) >= 2
    # All invocations should be bound to the proposal
    unbound = [i for i in invocations if i.proposal_id is None]
    assert len(unbound) == 0, f"Found unbound invocations: {[i.invocation_id for i in unbound]}"


def test_previous_unavailable_event_does_not_block_proposal(tmp_path: Path) -> None:
    """An old repair_primary_schema_invalid event does not prevent a later successful proposal."""
    conn = sqlite3.connect(
        str(tmp_path / "prev-unavail-f5.sqlite3"),
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)

    gate_repo = SqlitePhaseGateRepository(conn)
    event_repo = SqliteV2JobEventRepository(conn)
    repair_repo = SqliteV2RepairRepository(conn)
    llm_repo = SqliteV2LLMInvocationRepository(conn)

    repair_gate_service = V2RepairGateService(
        gate_service=V2PhaseGateService(gate_repo),
        repair_repo=repair_repo,
        reviewer_repo=SqliteV2ReviewerRepository(conn),
        llm_invocation_repo=llm_repo,
        event_repo=event_repo,
    )

    # Simulate old unavailable event
    event_repo.save(
        job_id="job-prev-unavail",
        stage=3,
        event_type="reviewed_repair_unavailable",
        status="blocked",
        message="No independent reviewer completed",
        payload={"reason_code": "proposer_schema_invalid", "job_id": "job-prev-unavail"},
    )

    # Now run a successful chain
    payload, model_client = _write_repair_inputs(tmp_path, job_id="job-prev-unavail", command_id="cmd-prev-unavail")
    result = repair_gate_service.create_reviewed_repair_gate_on_failure(
        job_id="job-prev-unavail",
        stage_index=3,
        command_id="cmd-prev-unavail",
        event_type="build_failed",
        payload=payload,
        legacy_path=payload["legacy_path"],
        model_client=model_client,
    )

    assert result.status == "created"
    proposal = repair_repo.get_current_proposal_for_job("job-prev-unavail")
    assert proposal is not None, "Proposal must be created despite previous unavailable event"
    assert proposal.status == "user_review_required"
