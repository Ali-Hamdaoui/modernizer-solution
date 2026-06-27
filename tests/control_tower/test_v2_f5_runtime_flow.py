"""Service-level proof for the governed F5 repair runtime."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

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


class FakeAzureRepairClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

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
                    "reviewed_context_checksum": "",
                    "reviewed_primary_output_checksum": "",
                    "reviewed_diff_checksum": "",
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
