from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.adapters.fastapi.app import ApproveRepairCandidateRequest
from migration_factory.control_tower.application.v2_llm_read_only_candidate_persistence import (
    EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED,
    EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED,
    EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED,
    LlmReadOnlyCandidatePersistenceService,
    emit_llm_read_only_candidate_event,
)
from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application import v2_repair_apply_candidate as repair_apply_module
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    apply_approved_repair_candidate,
    approve_repair_apply_candidate,
)
from migration_factory.control_tower.application.v2_repair_remediation import (
    execute_remediation_attempt,
    repair_remediation_intent_from_text,
)
from migration_factory.control_tower.application.v2_llm_invocation_ledger import V2LLMInvocationLedger
from migration_factory.control_tower.application.v2_repair_projection import (
    build_reviewed_diff_proposal_from_record,
    reviewed_diff_proposal_to_safe_dict,
)
from migration_factory.control_tower.application.v2_repair_route_decision import RepairRouteDecision
from migration_factory.control_tower.application.v2_stage_progression import V2StageProgressionService
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, sha256_hex
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteControlTowerUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import SqliteV2CommandRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_event_repository import SqliteV2JobEventRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import SqliteV2JobRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import SqliteV2LLMInvocationRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_candidate_repository import (
    SqliteV2RepairCandidateRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_attempt_repository import (
    SqliteV2RepairAttemptRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import SqliteV2RepairRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import SqliteV2SetupRepository
from migration_factory.repair_loop.patch_gate import (
    PATCH_SOURCE_LLM_REVIEWED,
    POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
    REASON_ASSERTION_WEAKENING,
    REASON_DIRECT_TEST_FAILURE_MASKING,
    REASON_EXPECTED_EXCEPTION_MASKING,
)
from migration_factory.repair_loop.failure_evidence import FailureSource, build_failure_evidence
from migration_factory.repair_loop.repair_context import build_repair_context_pack


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _repos(conn: sqlite3.Connection) -> tuple[SqliteV2RepairRepository, SqliteV2RepairCandidateRepository]:
    return SqliteV2RepairRepository(conn), SqliteV2RepairCandidateRepository(conn)


def _evidence() -> Any:
    return build_failure_evidence(
        failure_source=FailureSource.BUILD,
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        failure_summary="Unknown build failure",
        changed_files=("src/main/java/App.java",),
    )


def _context(evidence: Any) -> Any:
    return build_repair_context_pack(
        failure_evidence=evidence,
        job_id=evidence.job_id,
        stage_index=evidence.stage_index,
        command_id=evidence.command_id,
        changed_files=evidence.changed_files,
        cycle_number=0,
        max_cycles=3,
    )


def _decision(evidence: Any, context: Any) -> RepairRouteDecision:
    return RepairRouteDecision(
        route="llm_reviewed_unknown",
        reason="llm_unknown_eligible",
        failure_type="unknown",
        classification_status="unknown",
        evidence_checksum=evidence.content_checksum,
        context_checksum=context.context_pack_checksum,
        base_repo_state_checksum=context.base_repo_state_checksum,
        deterministic_rule_id=None,
        llm_eligible=True,
        attempt_number=context.cycle_number,
    )


def _chain(
    output_dir: Path,
    context: Any,
    diff_text: str | None = None,
    diff_bytes: bytes | None = None,
    changed_files: list[str] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    diff_path = output_dir / "final_reviewed_repair.diff"
    diff_path.write_bytes(
        diff_bytes if diff_bytes is not None else (diff_text or (
            "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
            "--- a/src/main/java/App.java\n"
            "+++ b/src/main/java/App.java\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )).encode("utf-8")
    )
    checksum = "sha256:" + sha256_hex(diff_path.read_bytes())
    declared = changed_files if changed_files is not None else ["src/main/java/App.java"]
    primary_output = {"changed_files": declared}
    primary_path = output_dir / "primary_output.json"
    primary_path.write_text(json.dumps(primary_output, sort_keys=True), encoding="utf-8")
    primary_checksum = "sha256:" + sha256_canonical_json(primary_output)
    primary_output_artifact_checksum = "sha256:" + sha256_hex(primary_path.read_bytes())
    final_artifact_path = output_dir / "final_reviewed_repair_artifact.json"
    final_artifact = {"changed_files": declared}
    final_artifact_path.write_text(json.dumps(final_artifact, sort_keys=True), encoding="utf-8")
    final_artifact_checksum = "sha256:" + sha256_canonical_json(final_artifact)
    final_artifact_persisted_checksum = "sha256:" + sha256_hex(final_artifact_path.read_bytes())
    chain = {
        "reviewer_decision": "accept",
        "proposal_kind": "llm_repair_review",
        "context_pack_checksum": context.context_pack_checksum,
        "job_id": context.job_id,
        "stage_index": context.stage_index,
        "primary_output_checksum": primary_checksum,
        "primary_output_artifact_checksum": primary_output_artifact_checksum,
        "reviewer_output_checksum": "sha256:" + "2" * 64,
        "reviewer_invocation_id": "reviewer-invocation-1",
        "proposed_diff_checksum": checksum,
        "raw_diff_bytes_checksum": checksum,
        "final_reviewed_diff_checksum": checksum,
        "final_artifact_checksum": final_artifact_checksum,
        "final_artifact_persisted_checksum": final_artifact_persisted_checksum,
        "primary_deterministic_fallback_used": False,
        "reviewer_deterministic_fallback_used": False,
        "final_diff_ref": str(diff_path),
        "primary_output_ref": str(primary_path),
        "final_artifact_ref": str(final_artifact_path),
    }
    chain.update(overrides)
    return {"artifact_refs": {"final_reviewed_diff": str(diff_path)}, "review_chain": chain}


def _policy_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = run_dir / "workspaces" / "sandbox"
    legacy = tmp_path / "legacy"
    app = sandbox / "src" / "main" / "java" / "App.java"
    app.parent.mkdir(parents=True, exist_ok=True)
    app.write_text("old\n", encoding="utf-8")
    (sandbox / "pom.xml").write_text("<project><modelVersion>4.0.0</modelVersion></project>\n", encoding="utf-8")
    legacy.mkdir(parents=True, exist_ok=True)
    return sandbox, run_dir, legacy


def _policy_payloads(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        json.loads(event.payload_json)
        for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
        if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED
    ]


def _valid_primary_json() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "proposal_kind": "llm_repair_primary",
            "root_cause": "Opaque failure",
            "fix_strategy": "Minimal source update",
            "changed_files": ["src/main/java/App.java"],
            "proposed_diff": (
                "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
                "--- a/src/main/java/App.java\n"
                "+++ b/src/main/java/App.java\n"
                "@@ -1,2 +1,2 @@\n"
                "-old line\n"
                "+new line\n"
                " unchanged\n"
            ),
            "risk": "LOW",
            "confidence": 0.9,
            "rationale": "Bounded read-only candidate.",
            "deterministic_rule_id": "must-not-be-persisted",
        },
        sort_keys=True,
    )


def _reviewer_json(prompt: str, decision: str = "accept") -> str:
    checksums = {
        key: re.search(pattern, prompt).group(1)  # type: ignore[union-attr]
        for key, pattern in {
            "context": r"Context pack checksum: ([0-9a-f]+)",
            "primary": r"Primary output checksum: ([0-9a-f]+)",
            "diff": r"Proposed diff checksum: ([0-9a-f]+)",
        }.items()
    }
    return json.dumps(
        {
            "schema_version": "1.0",
            "proposal_kind": "llm_repair_review",
            "decision": decision,
            "notes": ["Looks correct"],
            "confidence": 0.95,
            "risks": [],
            "policy_concerns": [],
            "reviewed_context_checksum": checksums["context"],
            "reviewed_primary_output_checksum": checksums["primary"],
            "reviewed_diff_checksum": checksums["diff"],
        },
        sort_keys=True,
    )


class _TxAssertingRepairClient:
    def __init__(self, conn: sqlite3.Connection, reviewer_decision: str = "accept") -> None:
        self._conn = conn
        self._reviewer_decision = reviewer_decision
        self.calls: list[str] = []
        self.in_tx: list[bool] = []

    def answer_with_role(self, *, role: V2ModelRole, prompt: str, fallback: str, **_: Any) -> V2AssistantModelResult:
        self.calls.append(role.value)
        self.in_tx.append(self._conn.in_transaction)
        content = _valid_primary_json() if role == V2ModelRole.PROPOSER else _reviewer_json(prompt, self._reviewer_decision)
        return V2AssistantModelResult(
            content=content,
            source="fake",
            model_status="live_ok",
            provider="fake",
            role=role.value,
            success=True,
            redacted_summary="ok",
            failure_reason="",
        )


def _unknown_failure_result(run_dir: Path) -> dict[str, Any]:
    sandbox = run_dir / "workspaces" / "sandbox"
    legacy = run_dir.parent / "legacy"
    app = sandbox / "src" / "main" / "java" / "App.java"
    app.parent.mkdir(parents=True, exist_ok=True)
    app.write_text("old line\nunchanged\n", encoding="utf-8")
    legacy.mkdir(parents=True, exist_ok=True)
    return {
        "build_status": "BUILD_FAILED",
        "test_status": "",
        "run_dir": str(run_dir),
        "sandbox_path": str(sandbox),
        "legacy_path": str(legacy),
        "failure_summary": "Build failed with opaque status",
        "changed_files": ["src/main/java/App.java"],
        "artifact_refs": {
            "sandbox_path": str(sandbox),
            "legacy_path": str(legacy),
            "build_error_contract": "artifacts/build_error_contract.json",
            "test_agent_log": "artifacts/test_agent.log",
            "test_report": "artifacts/test_report.xml",
        },
    }


def _persist(conn: sqlite3.Connection, tmp_path: Path, **overrides: Any) -> tuple[Any, Any, Any, Any]:
    repair_repo, candidate_repo = _repos(conn)
    event_repo = SqliteV2JobEventRepository(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    service = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=event_repo,
        attempt_repo=SqliteV2RepairAttemptRepository(conn),
    )
    result = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, **overrides),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
        source_proposal_id="source-proposal-1",
        source_gate_id="source-gate-1",
    )
    return result, repair_repo, candidate_repo, context


def _seed_downstream_context(conn: sqlite3.Connection, tmp_path: Path) -> None:
    now = "2026-07-09T00:00:00.000000Z"
    output_parent = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    output_parent.mkdir(parents=True, exist_ok=True)
    ai_hub.mkdir(parents=True, exist_ok=True)
    conn.execute(
        """INSERT OR IGNORE INTO v2_migration_setups (
            setup_id, run_name, legacy_app_path, output_parent_path, ai_hub_path,
            java11_home, java17_home, java21_home, maven_cmd, proof_level,
            skip_endpoint_smoke, migration_flags_json, setup_checksum,
            checksum_algorithm, created_at, created_by, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "setup-wf04a",
            "WF04A",
            str(tmp_path / "legacy"),
            str(output_parent),
            str(ai_hub),
            str(tmp_path / "jdk11"),
            str(tmp_path / "jdk17"),
            str(tmp_path / "jdk21"),
            "mvn",
            "compile",
            1,
            "{}",
            "setup-checksum",
            "sha256_canonical_json_v1",
            now,
            "test",
            None,
        ),
    )
    conn.execute(
        """INSERT OR IGNORE INTO v2_migration_jobs (
            job_id, setup_id, setup_checksum, pipeline_id, stage_chain_json,
            status, created_at, updated_at, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "job-wf04a",
            "setup-wf04a",
            "setup-checksum",
            "springboot-216-to-400-java21-four-stage",
            "{}",
            "running",
            now,
            now,
            None,
        ),
    )


def _downstream_resume_callback(conn: sqlite3.Connection, tmp_path: Path) -> Any:
    _seed_downstream_context(conn, tmp_path)

    def _callback(candidate: dict[str, Any], post_repair: dict[str, Any]) -> dict[str, Any]:
        evidence_pack = post_repair.get("evidence_pack") if isinstance(post_repair.get("evidence_pack"), dict) else {}
        current_stage_result = dict(evidence_pack)
        current_stage_result["final_status"] = "TRANSFORM_APPLIED_IN_SANDBOX"
        current_stage_result["build_status"] = "BUILD_PASSED_IN_SANDBOX"
        current_stage_result["test_status"] = "TEST_PASSED"
        current_stage_result["sandbox_path"] = candidate["_sandbox_root"]
        current_stage_result["output_sandbox_ref"] = candidate["_sandbox_root"]
        job = SqliteV2JobRepository(conn).get("job-wf04a")
        assert job is not None
        result = V2StageProgressionService(
            SqliteV2SetupRepository(conn),
            SqliteV2CommandRepository(conn),
        ).queue_next_stage(
            job_id="job-wf04a",
            setup_id=job.setup_id,
            current_stage=int(candidate["stage_index"]),
            sandbox_path=candidate["_sandbox_root"],
            current_stage_result=current_stage_result,
        )
        if result.status == "queued":
            return {
                "downstream_resume_status": "queued",
                "downstream_command_id": result.command_id,
                "downstream_stage_index": result.to_stage,
            }
        if result.status == "completed":
            return {"downstream_resume_status": "route_complete", "downstream_stage_index": result.to_stage}
        return {"downstream_resume_status": "blocked", "reason": result.reason or result.status, "downstream_stage_index": result.to_stage}

    return _callback


def _backend_actor() -> dict[str, str]:
    return {"actor_type": "local_operator", "actor_id": "test-operator"}


def _rewrite_internal_candidate(conn: sqlite3.Connection, repair_candidate_id: str, mutator: Any) -> None:
    row = conn.execute(
        "SELECT internal_json FROM v2_repair_apply_candidates WHERE repair_candidate_id = ?",
        (repair_candidate_id,),
    ).fetchone()
    assert row is not None
    candidate = json.loads(str(row["internal_json"]))
    mutator(candidate)
    conn.execute(
        "UPDATE v2_repair_apply_candidates SET internal_json = ? WHERE repair_candidate_id = ?",
        (json.dumps(candidate, sort_keys=True, separators=(",", ":")), repair_candidate_id),
    )


def _post_repair_proof_path(candidate: dict[str, Any]) -> Path:
    return (
        Path(candidate["_sandbox_root"])
        / ".migration"
        / "post-repair-verification"
        / candidate["repair_candidate_id"]
        / "post-repair-verification.json"
    )


def _write_post_repair_proof(candidate: dict[str, Any], *, malformed: bool = False, forged: bool = False) -> dict[str, Any]:
    proof_path = _post_repair_proof_path(candidate)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    if malformed:
        proof_path.write_text("{not-json", encoding="utf-8")
    else:
        proof = {
            "job_id": candidate["job_id"],
            "stage_index": candidate["stage_index"],
            "repair_candidate_id": candidate["repair_candidate_id"],
            "approval_id": candidate.get("approval", {}).get("approval_id", ""),
            "post_repair_verification_status": "passed",
            "stage_recovery_status": "recovered",
            "commands": [],
            "evidence_pack_checksum": "",
            "classification": {},
            "proof_created_at": "2026-07-09T00:00:00.000000Z",
            "downstream_start_allowed": False,
        }
        proof["proof_checksum"] = "sha256:" + ("0" * 64) if forged else f"sha256:{sha256_canonical_json(proof)}"
        proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
    return {
        "post_repair_verification_status": "passed",
        "stage_recovery_status": "recovered",
        "commands": [],
        "evidence_pack": {},
        "classification": {},
        "proof_artifact": str(proof_path),
        "post_repair_proof_artifact": str(proof_path),
        "downstream_start_allowed": False,
    }


def test_accept_persists_one_proposal_one_candidate_and_replay_is_idempotent(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    second, _, _, _ = _persist(conn, tmp_path)
    record = repair_repo.get_proposal(first.llm_candidate_proposal_id)
    latest = candidate_repo.latest_public_for_job("job-wf04a")

    assert first.status == "persisted"
    assert second.status == "idempotent"
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1
    assert record is not None
    assert record.policy_validation_checksum
    assert latest["repair_candidate_id"] == first.llm_repair_candidate_id
    assert latest["patch_source"] == PATCH_SOURCE_LLM_REVIEWED
    assert latest["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert latest["policy_validation_checksum"] == record.policy_validation_checksum
    expected_diff = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    assert record.diff_ref
    assert Path(record.diff_ref).read_text(encoding="utf-8") == expected_diff
    assert latest["patch_checksum"] == "sha256:" + sha256_hex(expected_diff.encode("utf-8"))
    assert latest["approval_enabled"] is True
    assert latest["apply_enabled"] is False
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_proposals").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates").fetchone()[0] == 1
    policy_events = [
        json.loads(event.payload_json)
        for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
        if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED
    ]
    assert len(policy_events) == 1
    assert policy_events[0]["decision"] == "ALLOWED"
    assert policy_events[0]["policy_checksum"] == record.policy_validation_checksum
    replay_events: list[str] = []
    emit_llm_read_only_candidate_event(
        event_sink=lambda **kwargs: replay_events.append(kwargs["event_type"]),
        result=second,
    )
    assert replay_events == []


def test_source_correlation_not_candidate_identity_and_no_gate_created(tmp_path: Path) -> None:
    conn = _conn()
    result, repair_repo, _, _ = _persist(conn, tmp_path)
    record = repair_repo.get_proposal(result.llm_candidate_proposal_id)

    assert record is not None
    assert record.proposal_id.startswith("llm-candidate-proposal-")
    assert record.proposal_id != "source-proposal-1"
    assert record.source_proposal_id == "source-proposal-1"
    assert record.gate_id is None
    metadata = json.loads(record.patch_package_json)
    assert metadata["source_gate_id"] == "source-gate-1"


def test_same_id_different_checksum_fails_closed(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, _, _ = _persist(conn, tmp_path)
    conn.execute(
        "UPDATE v2_repair_proposals SET patch_package_json = ? WHERE proposal_id = ?",
        (json.dumps({"candidate_checksum": "sha256:" + "9" * 64}), first.llm_candidate_proposal_id),
    )
    second, _, _, _ = _persist(conn, tmp_path)

    assert second.status == "blocked"
    assert second.reason == "llm_candidate_checksum_collision"
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1


def test_candidate_insert_failure_rolls_back_proposal(tmp_path: Path) -> None:
    class FailingCandidateRepo(SqliteV2RepairCandidateRepository):
        def save_candidate(self, candidate: dict[str, Any]) -> None:
            raise RuntimeError("boom")

    conn = _conn()
    repair_repo = SqliteV2RepairRepository(conn)
    candidate_repo = FailingCandidateRepo(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )

    assert result.status == "blocked"
    assert result.reason == "llm_candidate_repository_write_failed"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()


def test_event_failure_rolls_back_proposal_and_candidate(tmp_path: Path) -> None:
    class FailingEventRepo(SqliteV2JobEventRepository):
        def save(self, **kwargs: Any) -> Any:
            raise RuntimeError("event write failed")

    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=FailingEventRepo(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )

    assert result.status == "blocked"
    assert result.reason == "llm_candidate_repository_write_failed"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_partial_state_collision_blocks_inside_transaction(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, _, _ = _persist(conn, tmp_path)
    conn.execute("DELETE FROM v2_repair_apply_candidates WHERE repair_candidate_id = ?", (first.llm_repair_candidate_id,))

    second, _, _, _ = _persist(conn, tmp_path)

    assert second.status == "blocked"
    assert second.reason == "llm_candidate_checksum_collision"
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1


def test_missing_repository_blocks_configuration(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, _ = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=None,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )

    assert result.status == "blocked"
    assert result.reason == "llm_candidate_persistence_configuration_incomplete"


def test_missing_event_repository_blocks_without_rows_or_events(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=None,
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )

    assert result.status == "blocked"
    assert result.reason == "llm_candidate_persistence_configuration_incomplete"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None
    assert SqliteV2JobEventRepository(conn).list_by_job("job-wf04a") == ()


def test_events_order_completed_then_candidate_and_failure_is_candidate_specific(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    conn.execute(
        "INSERT INTO v2_job_events (event_id, job_id, stage, type, status, message, payload_json, created_at, sequence) "
        "VALUES ('e-start', 'job-wf04a', 1, 'llm_review_chain_started', 'started', '', '{}', '2026-01-01T00:00:00Z', 1)"
    )
    conn.execute(
        "INSERT INTO v2_job_events (event_id, job_id, stage, type, status, message, payload_json, created_at, sequence) "
        "VALUES ('e-done', 'job-wf04a', 1, 'llm_review_chain_completed', 'completed', '', '{}', '2026-01-01T00:00:01Z', 2)"
    )
    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    blocked = type(result)(
        status="blocked",
        reason="reviewed_diff_ref_outside_output_dir",
        job_id=result.job_id,
        stage_index=result.stage_index,
        command_id=result.command_id,
    )
    events = [event.type for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")]
    emit_llm_read_only_candidate_event(
        event_sink=lambda **kwargs: events.append(kwargs["event_type"]),
        result=blocked,
    )

    assert events[:4] == [
        "llm_review_chain_started",
        "llm_review_chain_completed",
        EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED,
        EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED,
    ]
    assert events[-1] == EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED
    assert "llm_review_chain_blocked" not in events


def test_diff_outside_output_dir_and_checksum_mismatch_rejected(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    outside = tmp_path / "outside.diff"
    outside.write_text("diff --git a/x b/x\n", encoding="utf-8")
    chain = _chain(output_dir, context)
    chain["review_chain"]["final_diff_ref"] = str(outside)
    chain["artifact_refs"]["final_reviewed_diff"] = str(outside)

    service = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    )
    outside_result = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    mismatch = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, raw_diff_bytes_checksum="sha256:" + "8" * 64),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )

    assert outside_result.reason == "reviewed_llm_patch_policy_rejected"
    policy_events = [event for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a") if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED]
    outside_payload = json.loads(policy_events[0].payload_json)
    mismatch_payload = json.loads(policy_events[-1].payload_json)

    assert outside_payload["decision"] == "BLOCKED"
    assert outside_payload["reason_codes"] == ["reviewed_diff_ref_outside_output_dir"]
    assert mismatch.reason == "reviewed_llm_patch_policy_rejected"
    assert mismatch_payload["decision"] == "BLOCKED"
    assert mismatch_payload["reason_codes"] == ["reviewed_diff_checksum_mismatch"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()


def test_missing_diff_reference_is_audited_and_blocks_candidate(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    chain = _chain(output_dir, context)
    chain["review_chain"]["final_diff_ref"] = ""
    chain["artifact_refs"]["final_reviewed_diff"] = ""

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["decision"] == "BLOCKED"
    assert payload["reason_codes"] == ["reviewed_diff_ref_invalid"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_missing_referenced_diff_file_is_audited_and_blocks_candidate(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    missing = output_dir / "missing.diff"
    chain = _chain(output_dir, context)
    chain["review_chain"]["final_diff_ref"] = str(missing)
    chain["artifact_refs"]["final_reviewed_diff"] = str(missing)

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["decision"] == "BLOCKED"
    assert payload["reason_codes"] == ["reviewed_diff_file_missing"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


@pytest.mark.parametrize(
    ("ref_key", "checksum_key", "expected_reason"),
    [
        ("primary_output_ref", "primary_output_artifact_checksum", "primary_output_artifact_invalid"),
        ("final_artifact_ref", "final_artifact_persisted_checksum", "final_artifact_invalid"),
    ],
)
def test_tampered_referenced_json_artifact_is_blocked(
    tmp_path: Path,
    ref_key: str,
    checksum_key: str,
    expected_reason: str,
) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    chain = _chain(output_dir, context)
    Path(chain["review_chain"][ref_key]).write_text(json.dumps({"changed_files": ["src/main/java/Tampered.java"]}), encoding="utf-8")

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["reason_codes"] == [expected_reason]
    assert payload["details"][0]["detail"] == "json_artifact_checksum_mismatch"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


@pytest.mark.parametrize(
    ("checksum_key", "expected_reason"),
    [
        ("primary_output_artifact_checksum", "primary_output_artifact_invalid"),
        ("final_artifact_persisted_checksum", "final_artifact_invalid"),
    ],
)
def test_missing_persisted_json_artifact_checksum_field_is_blocked(
    tmp_path: Path,
    checksum_key: str,
    expected_reason: str,
) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    chain = _chain(output_dir, context)
    chain["review_chain"].pop(checksum_key)

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["reason_codes"] == [expected_reason]
    assert payload["details"][0]["detail"] == "json_artifact_checksum_missing"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


@pytest.mark.parametrize(
    ("ref_key", "checksum_key", "expected_reason"),
    [
        ("primary_output_ref", "primary_output_artifact_checksum", "primary_output_artifact_invalid"),
        ("final_artifact_ref", "final_artifact_persisted_checksum", "final_artifact_invalid"),
    ],
)
def test_json_artifact_reference_outside_output_dir_is_blocked(
    tmp_path: Path,
    ref_key: str,
    checksum_key: str,
    expected_reason: str,
) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    chain = _chain(output_dir, context)
    outside = tmp_path / f"{ref_key}.json"
    outside.write_text(json.dumps({"changed_files": ["src/main/java/App.java"]}), encoding="utf-8")
    chain["review_chain"][ref_key] = str(outside)
    chain["review_chain"][checksum_key] = "sha256:" + sha256_hex(outside.read_bytes())

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["reason_codes"] == [expected_reason]
    assert payload["details"][0]["detail"] == "reviewed_diff_ref_outside_output_dir"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_invalid_utf8_json_artifact_is_blocked(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    chain = _chain(output_dir, context)
    primary = Path(chain["review_chain"]["primary_output_ref"])
    primary.write_bytes(b'{"changed_files":["src/main/java/App.java"],"bad":"\xff"}')
    chain["review_chain"]["primary_output_artifact_checksum"] = "sha256:" + sha256_hex(primary.read_bytes())

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "blocked"
    assert payload["reason_codes"] == ["primary_output_artifact_invalid"]
    assert payload["details"][0]["detail"] == "invalid_json_encoding"
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_route_scope_is_not_derived_from_evidence_changed_files(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = build_failure_evidence(
        failure_source=FailureSource.BUILD,
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        failure_summary="Unknown build failure",
        changed_files=("evidence/diagnostic-only.txt",),
    )
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, changed_files=["src/main/java/App.java"]),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = _policy_payloads(conn)[-1]

    assert result.status == "persisted"
    assert payload["decision"] == "ALLOWED"
    assert payload["evidence_changed_files"] == ["evidence/diagnostic-only.txt"]
    assert payload["declared_changed_files"] == ["src/main/java/App.java"]
    assert payload["allowed_route_scope"] != payload["evidence_changed_files"]
    assert repair_repo.list_proposals_by_job("job-wf04a")
    assert candidate_repo.latest_public_for_job("job-wf04a")["apply_enabled"] is False


def test_replayed_blocked_policy_event_has_stable_checksum_and_bounded_duplicates(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    unsafe_diff = (
        "diff --git a/scripts/run.sh b/scripts/run.sh\n"
        "--- a/scripts/run.sh\n"
        "+++ b/scripts/run.sh\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
    )
    chain = _chain(output_dir, context, diff_text=unsafe_diff, changed_files=["scripts/run.sh"])
    service = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    )

    first = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    second = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=chain,
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payloads = _policy_payloads(conn)

    assert first.status == second.status == "blocked"
    assert len(payloads) == 2
    assert payloads[0]["policy_checksum"] == payloads[1]["policy_checksum"]
    assert payloads[0]["policy_id"] == payloads[1]["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_reviewed_llm_diff_policy_rejection_blocks_candidate_persistence(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    unsafe_diff = (
        "diff --git a/.env b/.env\n"
        "--- a/.env\n"
        "+++ b/.env\n"
        "@@ -1,1 +1,1 @@\n"
        "-OLD=1\n"
        "+NEW=2\n"
    )

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, diff_text=unsafe_diff),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    events = SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
    policy_event = [event for event in events if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED][-1]
    policy_payload = json.loads(policy_event.payload_json)

    assert result.status == "blocked"
    assert result.reason == "reviewed_llm_patch_policy_rejected"
    assert policy_payload["decision"] == "BLOCKED"
    assert "shared_path_validation_failed" in policy_payload["reason_codes"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_m1_unknown_runtime_sentinel_test_masking_is_policy_blocked(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = build_failure_evidence(
        failure_source=FailureSource.TEST,
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        failure_summary="M1_UNKNOWN_RUNTIME_SENTINEL: migrated runtime behavior requires governed review",
        changed_files=("src/test/java/com/example/UnknownRuntimeTest.java",),
    )
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    test_file = sandbox / "src" / "test" / "java" / "com" / "example" / "UnknownRuntimeTest.java"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "package com.example;\n"
        "class UnknownRuntimeTest {\n"
        "  void migratedRuntimeBehavior() {\n"
        "    org.junit.jupiter.api.Assertions.assertThrows(RuntimeException.class, () -> {\n"
        "      throw new RuntimeException(\"M1_UNKNOWN_RUNTIME_SENTINEL\");\n"
        "    });\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    output_dir = run_dir / "review-chain"
    masking_diff = (Path(__file__).parent / "fixtures" / "m1_unknown_runtime_sentinel_reviewed_repair.diff").read_text(encoding="utf-8")
    assert "M1_UNKNOWN_RUNTIME_SENTINEL" in masking_diff

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(
            output_dir,
            context,
            diff_text=masking_diff,
            changed_files=["src/test/java/com/example/UnknownRuntimeTest.java"],
        ),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    events = SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
    policy_payload = json.loads([event for event in events if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED][-1].payload_json)

    assert result.status == "blocked"
    assert result.reason == "reviewed_llm_patch_policy_rejected"
    assert policy_payload["decision"] == "BLOCKED"
    assert REASON_ASSERTION_WEAKENING in policy_payload["reason_codes"]
    assert REASON_DIRECT_TEST_FAILURE_MASKING in policy_payload["reason_codes"]
    assert REASON_EXPECTED_EXCEPTION_MASKING in policy_payload["reason_codes"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_phase_gates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_stage_commands WHERE job_id = ? AND stage_index > 1", ("job-wf04a",)).fetchone()[0] == 0
    assert not any("approval" in event.type or "apply" in event.type or "downstream" in event.type for event in events)


def test_reviewer_rejection_is_audited_and_persists_override_candidate(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, reviewer_decision="reject"),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = json.loads([event for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a") if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED][-1].payload_json)

    assert result.status == "persisted"
    assert payload["decision"] == "ALLOWED"
    assert payload["reason_codes"] == []
    candidate = candidate_repo.latest_public_for_job("job-wf04a")
    assert candidate["reviewer_outcome"] == "rejected"
    assert candidate["approval_mode_required"] == "reviewer_override_approval"
    assert candidate["apply_enabled"] is False


def test_invalid_diff_encoding_is_audited_and_blocks_candidate(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"
    invalid_bytes = (
        b"diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        b"--- a/src/main/java/App.java\n"
        b"+++ b/src/main/java/App.java\n"
        b"@@ -1,1 +1,1 @@\n"
        b"-old\n+\xff\n"
    )

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, diff_bytes=invalid_bytes),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = json.loads([event for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a") if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED][-1].payload_json)

    assert result.status == "blocked"
    assert payload["decision"] == "BLOCKED"
    assert payload["reason_codes"] == ["invalid_encoding"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_declared_changed_files_mismatch_is_audited_and_blocks_candidate(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    sandbox, run_dir, legacy = _policy_paths(tmp_path)
    output_dir = run_dir / "review-chain"

    result = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=SqliteV2JobEventRepository(conn),
    ).persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, changed_files=["src/main/java/Other.java"]),
        output_dir=output_dir,
        sandbox_path=sandbox,
        run_dir=run_dir,
        legacy_path=legacy,
    )
    payload = json.loads([event for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a") if event.type == EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED][-1].payload_json)

    assert result.status == "blocked"
    assert "declared_changed_files_mismatch" in payload["reason_codes"]
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()
    assert candidate_repo.latest_public_for_job("job-wf04a") is None


def test_exact_diff_bytes_projection_and_bindings_preserved(tmp_path: Path) -> None:
    conn = _conn()
    result, repair_repo, _, context = _persist(conn, tmp_path, diff_text=(
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\r\n"
        "--- a/src/main/java/App.java\r\n"
        "+++ b/src/main/java/App.java\r\n"
        "@@ -1,1 +1,1 @@\r\n"
        "-old\r\n"
        "+new\r\n"
    ))
    record = repair_repo.get_proposal(result.llm_candidate_proposal_id)
    metadata = json.loads(record.patch_package_json)
    projection = reviewed_diff_proposal_to_safe_dict(
        build_reviewed_diff_proposal_from_record(
            proposal_id=record.proposal_id,
            status=record.status,
            failure_summary=record.failure_summary,
            job_id=record.job_id,
            command_id=record.command_id,
            gate_id=record.gate_id,
            route_step_index=record.route_step_index,
            attempt_number=record.attempt_number,
            diff_ref=record.diff_ref,
            diff_checksum=record.diff_checksum,
            reviewer_output_checksum=record.reviewer_output_checksum,
            reviewer_decision=record.reviewer_decision,
        )
    )

    assert metadata["context_checksum"] == context.context_pack_checksum
    assert metadata["candidate_checksum"] == result.candidate_checksum
    assert metadata["patch_source"] == PATCH_SOURCE_LLM_REVIEWED
    assert metadata["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert metadata["policy_validation"]["patch_source"] == PATCH_SOURCE_LLM_REVIEWED
    assert metadata["policy_validation"]["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert metadata["policy_validation"]["decision"] == "ALLOWED"
    assert "deterministic_rule_id" not in metadata["policy_validation"]
    assert metadata["policy_validation_checksum"] == record.policy_validation_checksum
    assert "deterministic_rule_id" not in json.dumps(metadata)
    assert projection["safe_diff_preview"]["checksum_mismatch"] is False
    assert projection["safe_diff_preview"]["files"][0]["path"] == "src/main/java/App.java"


def _llm_approval_request(candidate: dict[str, Any]) -> dict[str, Any]:
    outcome = str(candidate.get("reviewer_outcome") or "accepted")
    mode = (
        "normal_approval"
        if outcome == "accepted"
        else "acknowledged_risk_approval"
        if outcome == "accepted_with_concerns"
        else "reviewer_override_approval"
    )
    return {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "candidate_checksum": candidate["candidate_checksum"],
        "reviewed_diff_checksum": candidate["patch_checksum"],
        "policy_validation_checksum": candidate["policy_validation_checksum"],
        "review_chain_identity_checksum": candidate["review_chain_identity_checksum"],
        "base_repository_state_checksum": candidate["base_repo_state_checksum"],
        "approval_mode": mode,
        "reviewer_outcome": outcome,
        "reviewer_output_checksum": candidate.get("reviewer_output_checksum", ""),
        "reviewer_invocation_id": candidate.get("reviewer_invocation_id", ""),
        "operator_justification": "Bounded sandbox repair with governed verification." if mode != "normal_approval" else "",
        "acknowledged_risk_codes": ["reviewer_advisory_risk"] if mode != "normal_approval" else [],
    }


def test_repository_persists_reviewed_llm_approval_and_execution_states(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())

    candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, approval)
    approved = candidate_repo.get_public("job-wf04a", 1, result.llm_repair_candidate_id)
    assert approved["status"] == "approved"
    assert approved["approval_enabled"] is False
    assert approved["apply_enabled"] is True

    execution = apply_approved_repair_candidate(
        candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id),
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=True),
        downstream_resume=lambda *_: {
            "downstream_resume_status": "route_complete",
            "downstream_stage_index": 1,
        },
    )
    candidate_repo.save_execution("job-wf04a", 1, result.llm_repair_candidate_id, execution)
    public = candidate_repo.get_public("job-wf04a", 1, result.llm_repair_candidate_id)
    latest = candidate_repo.latest_public_for_job("job-wf04a")

    for value in (public, latest):
        assert value["status"] == "verified"
        assert value["approval_enabled"] is False
        assert value["apply_enabled"] is False
        assert value["downstream_start_allowed"] is False
        assert value["downstream_resume_status"] == "route_complete"
        assert value["sandbox_only"] is True


def test_reviewed_llm_application_guard_requires_exact_approval_checksums(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)

    with pytest.raises(ValueError, match="browser_actor_identity_not_allowed"):
        approve_repair_apply_candidate(
            candidate,
            {**_llm_approval_request(candidate), "approved_by": "browser-user"},
            actor_identity=_backend_actor(),
        )

    request = _llm_approval_request(candidate)
    request["candidate_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="candidate_checksum_mismatch"):
        approve_repair_apply_candidate(candidate, request, actor_identity=_backend_actor())
    with pytest.raises(ValueError, match="approval_required"):
        apply_approved_repair_candidate(candidate, {})


@pytest.mark.parametrize(
    ("binding", "reason"),
    [
        ("proposal", "persisted_proposal_policy_checksum_missing"),
        ("policy_event", "persisted_policy_event_checksum_missing"),
        ("mismatch", "apply_time_policy_checksum_mismatch"),
    ],
)
def test_reviewed_llm_policy_bindings_are_mandatory_for_approval_and_apply(
    tmp_path: Path,
    binding: str,
    reason: str,
) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())

    app_candidate = dict(candidate)
    if binding == "proposal":
        app_candidate.pop("_persisted_proposal_policy_validation_checksum", None)
    elif binding == "policy_event":
        app_candidate.pop("_persisted_policy_event_checksum", None)
    else:
        app_candidate["_persisted_proposal_policy_validation_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match=reason):
        approve_repair_apply_candidate(app_candidate, _llm_approval_request(app_candidate), actor_identity=_backend_actor())

    if binding == "proposal":
        _rewrite_internal_candidate(
            conn,
            result.llm_repair_candidate_id,
            lambda stored: stored["_llm_candidate_metadata"].update({"llm_candidate_proposal_id": "missing-proposal"}),
        )
    elif binding == "policy_event":
        _rewrite_internal_candidate(conn, result.llm_repair_candidate_id, lambda stored: stored.update({"stage_index": 99}))
    else:
        conn.execute(
            "UPDATE v2_repair_proposals SET policy_validation_checksum = ? WHERE proposal_id = ?",
            ("sha256:" + "0" * 64, result.llm_candidate_proposal_id),
        )
    with pytest.raises(ValueError, match=reason):
        candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, approval)

    apply_candidate = dict(candidate)
    if binding == "proposal":
        apply_candidate.pop("_persisted_proposal_policy_validation_checksum", None)
    elif binding == "policy_event":
        apply_candidate.pop("_persisted_policy_event_checksum", None)
    else:
        apply_candidate["_persisted_policy_event_checksum"] = "sha256:" + "0" * 64
    apply_candidate["status"] = "approved"
    with pytest.raises(ValueError, match=reason):
        apply_approved_repair_candidate(apply_candidate, approval)


def test_reviewed_llm_policy_bindings_all_equal_pass(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())

    candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, approval)

    approved = candidate_repo.get_public("job-wf04a", 1, result.llm_repair_candidate_id)
    assert approved["status"] == "approved"
    assert candidate["_persisted_proposal_policy_validation_checksum"] == candidate["policy_validation_checksum"]
    assert candidate["_persisted_policy_event_checksum"] == candidate["policy_validation_checksum"]


def test_reviewed_llm_reviewer_rejection_requires_override_bindings(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    mutated = dict(candidate)
    mutated["_llm_candidate_metadata"] = dict(candidate["_llm_candidate_metadata"])
    mutated["reviewer_decision"] = "reject"
    mutated["reviewer_outcome"] = "rejected"
    request = _llm_approval_request(mutated)
    request.update({
        "approval_mode": "reviewer_override_approval",
        "reviewer_outcome": "rejected",
        "operator_justification": "Production change is bounded and will be verified.",
        "acknowledged_risk_codes": ["reviewer_rejected"],
    })
    approval = approve_repair_apply_candidate(mutated, request, actor_identity=_backend_actor())
    assert approval["approval_mode"] == "reviewer_override_approval"
    assert approval["reviewer_decision"] == "reject"


def test_reviewed_llm_reviewer_decision_is_approval_checksum_bound(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    changed = dict(approval)
    changed["reviewer_decision"] = "reject"

    assert repair_apply_module._reviewed_llm_approval_checksum(changed) != approval["approval_checksum"]
    with pytest.raises(ValueError, match="approval_checksum_mismatch"):
        apply_approved_repair_candidate({**candidate, "status": "approved"}, changed)


@pytest.mark.parametrize(
    "field",
    [
        "approved_by",
        "actor",
        "actor_id",
        "patch",
        "patch_text",
        "patch_bytes",
        "target_path",
        "sandbox",
        "sandbox_path",
        "legacy_path",
        "run_dir",
        "command",
        "environment",
    ],
)
def test_public_approval_request_rejects_browser_controlled_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        ApproveRepairCandidateRequest.model_validate(
            {
                "repair_candidate_id": "candidate",
                "candidate_checksum": "sha256:" + "1" * 64,
                "reviewed_diff_checksum": "sha256:" + "2" * 64,
                "policy_validation_checksum": "sha256:" + "3" * 64,
                "review_chain_identity_checksum": "sha256:" + "4" * 64,
                "base_repository_state_checksum": "sha256:" + "5" * 64,
                field: "browser-controlled",
            }
        )


class _ReviewedLlmPostRepairRunner:
    def __init__(self, *, pass_tests: bool = True) -> None:
        self.pass_tests = pass_tests
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str], cwd: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append(list(command))
        executable = Path(command[0]).name.lower() if command else ""
        if executable in {"java.exe", "java"}:
            executable = "java"
        if executable in {"mvn.cmd", "mvn.bat", "mvn.exe", "mvn"}:
            executable = "mvn"
        key = " ".join([executable, *command[1:]]) if command else ""
        if key == "java -version":
            return {"exit_code": 0, "stdout": "", "stderr": 'openjdk version "17.0.1"'}
        if key == "mvn -version":
            return {"exit_code": 0, "stdout": "Apache Maven 3.9.9", "stderr": ""}
        if key == "mvn -DskipTests clean compile":
            return {"exit_code": 0, "stdout": "[INFO] BUILD SUCCESS", "stderr": ""}
        if key == "mvn test":
            return {
                "exit_code": 0 if self.pass_tests else 1,
                "stdout": "Tests run: 1, Failures: 0, Errors: 0" if self.pass_tests else "Tests run: 1, Failures: 1",
                "stderr": "" if self.pass_tests else "reviewed repair verification failed",
            }
        if key == "mvn dependency:tree -DoutputType=text":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        return {"exit_code": 1, "stdout": "", "stderr": f"unexpected command {key}"}


def test_reviewed_llm_human_approval_apply_verification_and_downstream_resume_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    conn = _conn()
    result, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    sandbox_app = Path(candidate["_sandbox_root"]) / "src/main/java/App.java"
    legacy_app = tmp_path / "legacy" / "src/main/java/App.java"
    legacy_app.parent.mkdir(parents=True, exist_ok=True)
    legacy_app.write_text("old\n", encoding="utf-8")
    diff_bytes = Path(candidate["_reviewed_diff_ref"]).read_bytes()

    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    runner = _ReviewedLlmPostRepairRunner(pass_tests=True)
    execution = apply_approved_repair_candidate(
        approved,
        approval,
        post_repair_verification_runner=runner,
        downstream_resume=_downstream_resume_callback(conn, tmp_path),
    )
    candidate_repo.save_execution("job-wf04a", 1, candidate["repair_candidate_id"], execution)
    replay = apply_approved_repair_candidate(candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"]), approval)

    assert execution["execution_status"] == "verified"
    assert execution["verification_status"] == "passed"
    assert execution["rollback_status"] == "not_needed"
    assert execution["post_repair_verification_status"] == "passed"
    assert execution["downstream_resume_status"] == "queued"
    assert execution["downstream_start_allowed"] is True
    assert execution["downstream_command_id"]
    assert execution["downstream_stage_index"] == 2
    assert replay["execution_status"] == "verified"
    assert sandbox_app.read_text(encoding="utf-8") == "new\n"
    assert legacy_app.read_text(encoding="utf-8") == "old\n"
    assert (Path(candidate["_run_dir"]) / "repairs" / "patch_attempt_1.diff").read_bytes() == diff_bytes
    final_proof_path = Path(candidate["_sandbox_root"], ".migration", "repair-proofs", f"{candidate['repair_candidate_id']}.json")
    post_repair_proof_path = _post_repair_proof_path(candidate)
    final_proof = json.loads(final_proof_path.read_text(encoding="utf-8"))
    post_repair_proof = json.loads(post_repair_proof_path.read_text(encoding="utf-8"))
    assert execution["proof_artifact"] == f".migration/repair-proofs/{candidate['repair_candidate_id']}.json"
    assert execution["post_repair_proof_artifact"] == (
        f".migration/post-repair-verification/{candidate['repair_candidate_id']}/post-repair-verification.json"
    )
    assert execution["proof_artifact"] != execution["post_repair_proof_artifact"]
    assert execution["proof_checksum"] == final_proof["proof_checksum"]
    assert execution["post_repair_verification_proof_checksum"] == post_repair_proof["proof_checksum"]
    assert final_proof["status"] == "verified"
    assert final_proof["approval_id"] == approval["approval_id"]
    assert final_proof["post_repair_verification_proof_checksum"] == post_repair_proof["proof_checksum"]
    assert post_repair_proof["job_id"] == candidate["job_id"]
    assert post_repair_proof["stage_index"] == candidate["stage_index"]
    assert post_repair_proof["repair_candidate_id"] == candidate["repair_candidate_id"]
    assert post_repair_proof["approval_id"] == approval["approval_id"]
    assert post_repair_proof["post_repair_verification_status"] == "passed"
    assert post_repair_proof["stage_recovery_status"] == "recovered"
    assert final_proof_path.is_file()
    assert post_repair_proof_path.is_file()
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM v2_stage_commands WHERE job_id = ? AND stage_index = ? AND command_id = ?",
        ("job-wf04a", 2, execution["downstream_command_id"]),
    ).fetchone()[0] == 1
    assert len([row for row in conn.execute("SELECT * FROM v2_repair_apply_candidates WHERE job_id = ?", ("job-wf04a",)).fetchall()]) == 1


def test_reviewed_llm_apply_preserves_exact_diff_bytes_without_final_newline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    diff_bytes = (
        b"diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        b"--- a/src/main/java/App.java\n"
        b"+++ b/src/main/java/App.java\n"
        b"@@ -1,1 +1,1 @@\n"
        b"-old\n"
        b"+new\n"
        b"\\ No newline at end of file"
    )
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path, diff_bytes=diff_bytes)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])

    execution = apply_approved_repair_candidate(
        approved,
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=True),
        downstream_resume=_downstream_resume_callback(conn, tmp_path),
    )

    patch_bytes = (Path(candidate["_run_dir"]) / "repairs" / "patch_attempt_1.diff").read_bytes()
    assert execution["execution_status"] == "verified"
    assert Path(candidate["_reviewed_diff_ref"]).read_bytes() == diff_bytes
    assert patch_bytes == diff_bytes
    assert "sha256:" + sha256_hex(patch_bytes) == candidate["patch_checksum"]


def test_public_display_diff_redaction_does_not_change_internal_apply_diff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    diff_text = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new // diagnostic C:\\Users\\operator\\private\\repair.log\n"
    )
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path, diff_text=diff_text)
    attempts = SqliteV2RepairAttemptRepository(conn)
    public_attempt = attempts.get_public("job-wf04a", 1, result.attempt_id)
    internal_attempt = attempts.get_internal("job-wf04a", 1, result.attempt_id)

    assert public_attempt["display_diff_redacted"] is True
    assert public_attempt["display_diff_status"] == "redacted"
    assert "C:\\Users\\operator" not in public_attempt["display_proposed_diff"]
    assert "C:\\Users\\operator" not in public_attempt["exact_proposed_diff"]
    assert public_attempt["exact_diff_checksum"] == "sha256:" + sha256_hex(diff_text.encode("utf-8"))
    assert internal_attempt["internal"]["exact_proposed_diff"] == diff_text

    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    execution = apply_approved_repair_candidate(
        approved,
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=True),
        downstream_resume=_downstream_resume_callback(conn, tmp_path),
    )

    sandbox_app = Path(candidate["_sandbox_root"]) / "src/main/java/App.java"
    patch_bytes = (Path(candidate["_run_dir"]) / "repairs" / "patch_attempt_1.diff").read_bytes()
    assert execution["execution_status"] == "verified"
    assert "C:\\Users\\operator\\private\\repair.log" in sandbox_app.read_text(encoding="utf-8")
    assert patch_bytes == diff_text.encode("utf-8")


@pytest.mark.parametrize(
    ("proof_mode", "reason"),
    [
        ("missing", "post_repair_verification_proof_missing"),
        ("malformed", "post_repair_verification_proof_malformed"),
        ("forged", "post_repair_verification_proof_checksum_mismatch"),
    ],
)
def test_reviewed_llm_post_repair_proof_must_validate_before_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proof_mode: str,
    reason: str,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    sandbox_app = Path(approved["_sandbox_root"], "src/main/java/App.java")
    legacy_app = Path(approved["_legacy_path"], "src/main/java/App.java")
    legacy_app.parent.mkdir(parents=True, exist_ok=True)
    legacy_app.write_text("legacy-original\n", encoding="utf-8")
    sandbox_before = sandbox_app.read_bytes()
    legacy_before = legacy_app.read_bytes()
    downstream_calls: list[str] = []

    def _fake_post_repair(**_: Any) -> dict[str, Any]:
        if proof_mode == "malformed":
            return _write_post_repair_proof(approved, malformed=True)
        if proof_mode == "forged":
            return _write_post_repair_proof(approved, forged=True)
        proof_path = _post_repair_proof_path(approved)
        if proof_path.exists():
            proof_path.unlink()
        return {
            "post_repair_verification_status": "passed",
            "stage_recovery_status": "recovered",
            "commands": [],
            "evidence_pack": {},
            "classification": {},
            "downstream_start_allowed": False,
        }

    def _downstream(*_: Any) -> dict[str, Any]:
        downstream_calls.append("called")
        return {"downstream_resume_status": "queued", "downstream_command_id": "should-not-exist", "downstream_stage_index": 2}

    monkeypatch.setattr(repair_apply_module, "run_post_repair_verification", _fake_post_repair)
    execution = apply_approved_repair_candidate(approved, approval, downstream_resume=_downstream)
    candidate_repo.save_execution("job-wf04a", 1, candidate["repair_candidate_id"], execution)

    assert reason in execution["verification_log"]
    assert execution["execution_status"] == "rolled_back"
    assert execution["status"] == "rolled_back"
    assert execution["rollback_status"] == "succeeded"
    assert execution["downstream_resume_status"] == "blocked"
    assert execution["downstream_start_allowed"] is False
    assert execution["downstream_command_id"] == ""
    assert sandbox_app.read_bytes() == sandbox_before
    assert legacy_app.read_bytes() == legacy_before
    assert downstream_calls == []
    assert conn.execute("SELECT COUNT(*) FROM v2_stage_commands").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda candidate: candidate.update({"policy_validation_checksum": "sha256:" + "0" * 64}), "policy_validation_checksum_mismatch"),
        (lambda candidate: candidate["_llm_candidate_metadata"]["policy_validation"].update({"decision": "BLOCKED"}), "policy_not_allowed"),
        (lambda candidate: candidate.update({"reviewer_decision": "reject", "reviewer_outcome": "rejected"}), "approval_mode_mismatch"),
        (lambda candidate: candidate.update({"review_chain_identity_checksum": "sha256:" + "1" * 64}), "review_chain_identity_checksum_mismatch"),
        (lambda candidate: candidate.update({"base_repo_state_checksum": "sha256:" + "2" * 64}), "base_repository_state_checksum_mismatch"),
    ],
)
def test_reviewed_llm_approval_negative_revalidations(
    tmp_path: Path,
    mutator: Any,
    reason: str,
) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    request = _llm_approval_request(candidate)
    mutator(candidate)

    with pytest.raises(ValueError, match=reason):
        approve_repair_apply_candidate(candidate, request, actor_identity=_backend_actor())


def test_repository_rejects_forged_approval_checksum_and_fake_execution(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    forged = dict(approval)
    forged["approval_checksum"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="llm_approval_checksum_mismatch"):
        candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], forged)

    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    valid_execution = apply_approved_repair_candidate(
        candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"]),
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=True),
        downstream_resume=lambda *_: {
            "downstream_resume_status": "route_complete",
            "downstream_stage_index": 1,
        },
    )
    fake_execution = dict(valid_execution)
    fake_execution.update({
        "downstream_start_allowed": True,
        "downstream_resume_status": "queued",
        "downstream_command_id": "missing-command",
        "downstream_stage_index": 2,
    })
    with pytest.raises(ValueError, match="llm_execution_fake_downstream_command"):
        candidate_repo.save_execution("job-wf04a", 1, candidate["repair_candidate_id"], fake_execution)
    without_proof = dict(valid_execution)
    without_proof["proof_artifact"] = ""
    with pytest.raises(ValueError, match="llm_execution_verification_proof_required"):
        candidate_repo.save_execution("job-wf04a", 1, candidate["repair_candidate_id"], without_proof)
    fake_proof = dict(valid_execution)
    fake_proof["proof_artifact"] = "artifact:proof"
    with pytest.raises(ValueError, match="llm_execution_fake_proof_artifact"):
        candidate_repo.save_execution("job-wf04a", 1, candidate["repair_candidate_id"], fake_proof)


def test_reviewed_llm_apply_rejects_stale_sandbox_and_tampered_diff_after_approval(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    Path(approved["_sandbox_root"], "src/main/java/App.java").write_text("stale\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pre_apply_checksum_mismatch"):
        apply_approved_repair_candidate(approved, approval)

    Path(approved["_sandbox_root"], "src/main/java/App.java").write_text("old\n", encoding="utf-8")
    Path(approved["_reviewed_diff_ref"]).write_text(Path(approved["_reviewed_diff_ref"]).read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed_diff_checksum_mismatch"):
        apply_approved_repair_candidate(approved, approval)


def test_reviewed_llm_apply_rejects_apply_time_policy_checksum_mismatch(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    approved["_persisted_policy_event_checksum"] = "sha256:" + "0" * 64

    with pytest.raises(ValueError, match="apply_time_policy_checksum_mismatch"):
        apply_approved_repair_candidate(approved, approval)


def test_reviewed_llm_verification_failure_rolls_back_and_blocks_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    target = Path(candidate["_sandbox_root"], "src/main/java/App.java")
    before = target.read_bytes()
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])
    runner = _ReviewedLlmPostRepairRunner(pass_tests=False)

    execution = apply_approved_repair_candidate(approved, approval, post_repair_verification_runner=runner)

    assert execution["execution_status"] == "rolled_back"
    assert execution["verification_status"] == "failed"
    assert execution["rollback_status"] == "succeeded"
    assert execution["downstream_resume_status"] == "blocked"
    assert target.read_bytes() == before


def test_reviewed_llm_verification_failure_restores_multi_file_and_removes_created_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    diff_text = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1,1 +1,1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/src/main/java/New.java b/src/main/java/New.java\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/main/java/New.java\n"
        "@@ -0,0 +1 @@\n"
        "+created\n"
    )
    conn = _conn()
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        diff_text=diff_text,
        changed_files=["src/main/java/App.java", "src/main/java/New.java"],
    )
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    app_path = Path(candidate["_sandbox_root"], "src/main/java/App.java")
    new_path = Path(candidate["_sandbox_root"], "src/main/java/New.java")
    before = app_path.read_bytes()
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])

    execution = apply_approved_repair_candidate(
        approved,
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=False),
    )

    assert execution["execution_status"] == "rolled_back"
    assert execution["rollback_status"] == "succeeded"
    assert execution["downstream_resume_status"] == "blocked"
    assert app_path.read_bytes() == before
    assert not new_path.exists()
    proof = json.loads(Path(candidate["_sandbox_root"], ".migration", "repair-proofs", f"{candidate['repair_candidate_id']}.json").read_text(encoding="utf-8"))
    assert proof["rollback_status"] == "succeeded"
    assert proof["pre_apply_file_checksums"] == proof["post_apply_file_checksums"]


def test_reviewed_llm_rollback_failure_reports_failed_and_blocks_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAVEN_CMD", "mvn")
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, candidate["repair_candidate_id"], approval)
    approved = candidate_repo.get_internal("job-wf04a", 1, candidate["repair_candidate_id"])

    def _failed_rollback(**_: Any) -> tuple[bool, str]:
        return False, "simulated rollback failure"

    monkeypatch.setattr(repair_apply_module, "rollback_patch", _failed_rollback)
    execution = apply_approved_repair_candidate(
        approved,
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=False),
    )

    assert execution["execution_status"] == "failed"
    assert execution["status"] == "failed"
    assert execution["rollback_status"] == "failed"
    assert execution["downstream_resume_status"] == "blocked"
    assert execution["downstream_start_allowed"] is False
    proof = json.loads(Path(candidate["_sandbox_root"], ".migration", "repair-proofs", f"{candidate['repair_candidate_id']}.json").read_text(encoding="utf-8"))
    assert proof["status"] == "failed"
    assert proof["rollback_status"] == "failed"
    assert proof["downstream_resume_status"] == "blocked"


def test_app_runner_dispatch_uses_authoritative_diagnosis_and_persists_once(tmp_path: Path) -> None:
    conn = _conn()
    client = _TxAssertingRepairClient(conn)
    app = create_app(lambda: SqliteControlTowerUnitOfWork(conn), v2_assistant_model_client=client)
    runner = app.state.v2_orchestrator_runner
    run_dir = tmp_path / "run"
    result_payload = _unknown_failure_result(run_dir)
    assert "classification" not in result_payload
    runner._handle_exit(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        exit_code=0,
        result=result_payload,
        stderr="compile failed",
    )

    repair_repo, candidate_repo = _repos(conn)
    record = repair_repo.list_proposals_by_job("job-wf04a")[0]
    metadata = json.loads(record.patch_package_json)
    projection = reviewed_diff_proposal_to_safe_dict(
        build_reviewed_diff_proposal_from_record(
            proposal_id=record.proposal_id,
            status=record.status,
            failure_summary=record.failure_summary,
            job_id=record.job_id,
            command_id=record.command_id,
            gate_id=record.gate_id,
            route_step_index=record.route_step_index,
            attempt_number=record.attempt_number,
            diff_ref=record.diff_ref,
            diff_checksum=record.diff_checksum,
            reviewer_output_checksum=record.reviewer_output_checksum,
            reviewer_decision=record.reviewer_decision,
        )
    )
    events = SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
    event_types = [event.type for event in events]
    route_payload = json.loads(events[event_types.index("repair_route_selected")].payload_json)
    invocation_rows = conn.execute(
        """SELECT role, responsibility, status, stage_index, attempt_number,
                  schema_name, context_checksum, input_checksum, output_checksum,
                  raw_response_checksum, normalized_output_checksum,
                  validated_output_checksum, diff_checksum
           FROM v2_llm_invocations
           WHERE job_id = ?
           ORDER BY created_at""",
        ("job-wf04a",),
    ).fetchall()
    latest_candidate = candidate_repo.latest_public_for_job("job-wf04a")

    assert client.calls == ["proposer", "reviewer"]
    assert client.in_tx == [False, False]
    assert [row["role"] for row in invocation_rows] == ["main", "reviewer"]
    assert [row["responsibility"] for row in invocation_rows] == ["repair_proposal", "repair_review"]
    assert [row["status"] for row in invocation_rows] == ["completed", "completed"]
    assert [row["schema_name"] for row in invocation_rows] == ["RepairPrimaryOutput", "RepairReviewerOutput"]
    assert all(row["stage_index"] == 1 for row in invocation_rows)
    assert all(row["attempt_number"] == 1 for row in invocation_rows)
    assert all(row["context_checksum"] for row in invocation_rows)
    assert all(row["input_checksum"] for row in invocation_rows)
    assert all(row["output_checksum"] for row in invocation_rows)
    assert all(row["raw_response_checksum"] for row in invocation_rows)
    assert all(row["normalized_output_checksum"] for row in invocation_rows)
    assert all(row["validated_output_checksum"] for row in invocation_rows)
    assert all(row["diff_checksum"] for row in invocation_rows)
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1
    assert latest_candidate["candidate_kind"] == "llm_unknown_family"
    assert latest_candidate["status"] == "read_only"
    assert latest_candidate["approval_enabled"] is True
    assert latest_candidate["apply_enabled"] is False
    assert conn.execute("SELECT COUNT(*) FROM v2_phase_gates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_stage_commands WHERE job_id = ? AND stage_index > 1", ("job-wf04a",)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates WHERE approval_json NOT IN ('', '{}') OR execution_json NOT IN ('', '{}')").fetchone()[0] == 0
    assert app.state.v2_failure_diagnosis_service.get_diagnosis("cmd-wf04a", "build_failed") is None
    assert route_payload["route"] == "llm_reviewed_unknown"
    assert route_payload["classification_status"] == "unknown"
    assert metadata["failure_evidence_checksum"] == route_payload["evidence_checksum"]
    assert metadata["context_checksum"] == route_payload["context_checksum"]
    assert metadata["policy_id"] == POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1
    assert record.policy_validation_checksum
    assert Path(record.diff_ref).is_file()
    assert projection["safe_diff_preview"]["checksum_mismatch"] is False
    assert projection["safe_diff_preview"]["files"]
    assert [
        event_type
        for event_type in event_types
        if event_type in {
            "repair_route_selected",
            "llm_review_chain_started",
            "llm_review_chain_completed",
            EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED,
            "llm_read_only_candidate_persisted",
            "llm_read_only_candidate_blocked",
        }
    ] == [
        "repair_route_selected",
        "llm_review_chain_started",
        "llm_review_chain_completed",
        EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED,
        "llm_read_only_candidate_persisted",
    ]
    assert "repair_review_required" not in event_types
    assert not any("approval" in event_type for event_type in event_types)
    assert not any("apply" in event_type for event_type in event_types)
    assert not any("downstream" in event_type or "queued" in event_type for event_type in event_types)
    assert not any(str(tmp_path) in event.payload_json for event in events if event.type in {"build_failed", "test_failed", "transform_failed"})


def test_app_unknown_route_unavailable_ledger_fails_closed_with_safe_kind(tmp_path: Path) -> None:
    class MissingLedgerUow(SqliteControlTowerUnitOfWork):
        def __init__(self, connection: sqlite3.Connection) -> None:
            super().__init__(connection)
            self.v2_llm_invocations = None

    conn = _conn()
    client = _TxAssertingRepairClient(conn)
    app = create_app(lambda: MissingLedgerUow(conn), v2_assistant_model_client=client)
    runner = app.state.v2_orchestrator_runner

    runner._handle_exit(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        exit_code=0,
        result=_unknown_failure_result(tmp_path / "missing-ledger-run"),
        stderr="compile failed",
    )

    events = SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
    event_types = [event.type for event in events]
    blocked = events[event_types.index("llm_review_chain_blocked")]
    payload = json.loads(blocked.payload_json)

    assert client.calls == []
    assert payload["reason"] == "review_chain_producer_failed"
    assert payload["failure_kind"] == "invocation_ledger_start_failed"
    assert conn.execute("SELECT COUNT(*) FROM v2_llm_invocations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_proposals").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_phase_gates").fetchone()[0] == 0
    assert "llm_review_chain_completed" not in event_types
    assert "llm_read_only_candidate_persisted" not in event_types


def test_app_notifier_runs_after_wf04_commit(tmp_path: Path) -> None:
    conn = _conn()
    persisted_notify_count = 0

    class Notifier:
        async def notify(self) -> None:
            nonlocal persisted_notify_count
            assert conn.in_transaction is False
            count = conn.execute(
                "SELECT COUNT(*) FROM v2_job_events WHERE type = 'llm_read_only_candidate_persisted'"
            ).fetchone()[0]
            if count:
                persisted_notify_count += 1

    app = create_app(lambda: SqliteControlTowerUnitOfWork(conn), v2_assistant_model_client=_TxAssertingRepairClient(conn))
    app.state.public_event_notifier = Notifier()
    runner = app.state.v2_orchestrator_runner
    run_dir = tmp_path / "app-run"
    runner._maybe_write_repair_failure_context(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        result=_unknown_failure_result(run_dir),
        stdout_tail="",
        stderr_tail="compile failed",
    )

    assert persisted_notify_count == 1


def test_app_blocked_route_invokes_no_model_candidate_or_gate(tmp_path: Path) -> None:
    conn = _conn()
    client = _TxAssertingRepairClient(conn)
    app = create_app(lambda: SqliteControlTowerUnitOfWork(conn), v2_assistant_model_client=client)
    runner = app.state.v2_orchestrator_runner

    runner._maybe_write_repair_failure_context(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        result={
            "build_status": "BUILD_FAILED",
            "run_dir": str(tmp_path / "blocked-run"),
            "failure_summary": "Build failed with unavailable evidence",
        },
        stdout_tail="",
        stderr_tail="compile failed",
    )

    event_types = [event.type for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")]
    assert event_types.count("repair_route_blocked") == 1
    assert "llm_review_chain_started" not in event_types
    assert client.calls == []
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_proposals").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_phase_gates").fetchone()[0] == 0
    assert app.state.v2_failure_diagnosis_service.get_diagnosis("cmd-wf04a", "build_failed") is None


def test_runtime_event_store_double_failure_does_not_escape_handle_exit(tmp_path: Path) -> None:
    class FailingRuntimeEventRepo(SqliteV2JobEventRepository):
        def save(self, **kwargs: Any) -> Any:
            if kwargs.get("event_type") in {"repair_route_selected", "repair_route_blocked"}:
                raise RuntimeError("raw sqlite failure must stay private")
            return super().save(**kwargs)

    class RuntimeEventFailingUow(SqliteControlTowerUnitOfWork):
        def __init__(self, connection: sqlite3.Connection) -> None:
            super().__init__(connection)
            self.v2_events = FailingRuntimeEventRepo(connection)

    conn = _conn()
    client = _TxAssertingRepairClient(conn)
    app = create_app(lambda: RuntimeEventFailingUow(conn), v2_assistant_model_client=client)
    runner = app.state.v2_orchestrator_runner

    runner._handle_exit(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        exit_code=0,
        result=_unknown_failure_result(tmp_path / "double-event-failure"),
        stderr="compile failed",
    )

    events = SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")
    event_types = [event.type for event in events]
    payloads = " ".join(event.payload_json for event in events)
    messages = " ".join(event.message for event in events)
    assert "stage_failed" in event_types
    assert "build_failed" in event_types
    assert "raw sqlite failure must stay private" not in payloads
    assert "raw sqlite failure must stay private" not in messages
    assert client.calls == []


def test_transform_only_failure_gets_governed_route_event(tmp_path: Path) -> None:
    conn = _conn()
    client = _TxAssertingRepairClient(conn)
    app = create_app(lambda: SqliteControlTowerUnitOfWork(conn), v2_assistant_model_client=client)
    runner = app.state.v2_orchestrator_runner

    runner._maybe_write_repair_failure_context(
        job_id="job-wf04a",
        stage_index=1,
        command_id="cmd-wf04a",
        result={
            "build_status": "",
            "test_status": "",
            "final_status": "TRANSFORM_FAILED",
            "transform_status": "TRANSFORM_FAILED",
            "run_dir": str(tmp_path / "transform-run"),
            "failure_summary": "Transform failed with unavailable evidence",
        },
        stdout_tail="",
        stderr_tail="transform failed",
    )

    event_types = [event.type for event in SqliteV2JobEventRepository(conn).list_by_job("job-wf04a")]
    assert "repair_route_blocked" in event_types
    assert client.calls == []


@pytest.mark.parametrize(
    ("reviewer_decision", "reviewer_outcome", "reviewer_checksum", "approval_mode"),
    [
        ("accept", "accepted", "sha256:" + "2" * 64, "normal_approval"),
        ("revise", "accepted_with_concerns", "sha256:" + "2" * 64, "acknowledged_risk_approval"),
        ("reject", "rejected", "sha256:" + "2" * 64, "reviewer_override_approval"),
        ("unavailable", "unavailable", "", "reviewer_override_approval"),
    ],
)
def test_operator_governed_attempt_persists_every_advisory_outcome(
    tmp_path: Path,
    reviewer_decision: str,
    reviewer_outcome: str,
    reviewer_checksum: str,
    approval_mode: str,
) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        reviewer_decision=reviewer_decision,
        reviewer_outcome=reviewer_outcome,
        reviewer_output_checksum=reviewer_checksum,
        reviewer_availability=reviewer_outcome != "unavailable",
    )

    assert result.status == "persisted"
    candidate = candidate_repo.get_public("job-wf04a", 1, result.llm_repair_candidate_id)
    attempt = SqliteV2RepairAttemptRepository(conn).get_public("job-wf04a", 1, result.attempt_id)
    assert candidate["reviewer_outcome"] == reviewer_outcome
    assert candidate["approval_mode_required"] == approval_mode
    assert candidate["apply_enabled"] is False
    assert attempt["reviewer_outcome"] == reviewer_outcome
    assert attempt["applicability_status"] == "applicable"
    assert attempt["exact_proposed_diff"].startswith("diff --git ")


@pytest.mark.parametrize(
    ("missing_field", "reason"),
    [
        ("operator_justification", "operator_justification_required"),
        ("acknowledged_risk_codes", "acknowledged_risk_codes_required"),
    ],
)
@pytest.mark.parametrize(
    ("reviewer_decision", "reviewer_outcome"),
    [
        ("revise", "accepted_with_concerns"),
        ("reject", "rejected"),
    ],
)
def test_risk_or_override_approval_requires_justification_and_acknowledged_risks(
    tmp_path: Path,
    missing_field: str,
    reason: str,
    reviewer_decision: str,
    reviewer_outcome: str,
) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        reviewer_decision=reviewer_decision,
        reviewer_outcome=reviewer_outcome,
    )
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    request = _llm_approval_request(candidate)
    request[missing_field] = "" if missing_field == "operator_justification" else []

    with pytest.raises(ValueError, match=reason):
        approve_repair_apply_candidate(candidate, request, actor_identity=_backend_actor())


@pytest.mark.parametrize(
    ("reviewer_decision", "reviewer_outcome", "reviewer_checksum"),
    [
        ("reject", "rejected", "sha256:" + "2" * 64),
        ("unavailable", "unavailable", ""),
    ],
)
def test_valid_reviewer_override_is_append_only_and_keeps_advisory_visible(
    tmp_path: Path,
    reviewer_decision: str,
    reviewer_outcome: str,
    reviewer_checksum: str,
) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        reviewer_decision=reviewer_decision,
        reviewer_outcome=reviewer_outcome,
        reviewer_output_checksum=reviewer_checksum,
    )
    attempts = SqliteV2RepairAttemptRepository(conn)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, approval)
    attempts.save_decision({
        "decision_id": "repair-decision-override-1",
        "attempt_id": result.attempt_id,
        "repair_candidate_id": result.llm_repair_candidate_id,
        "job_id": "job-wf04a",
        "stage_index": 1,
        "approval_mode": approval["approval_mode"],
        "decision_status": "approved",
        "operator_justification": approval["operator_justification"],
        "acknowledged_risk_codes": approval["acknowledged_risk_codes"],
        "reviewer_outcome": approval["reviewer_outcome"],
        "reviewer_output_checksum": approval["reviewer_output_checksum"],
        "reviewer_invocation_id": approval["reviewer_invocation_id"],
        "candidate_checksum": approval["candidate_checksum"],
        "actor_type": approval["backend_actor_type"],
        "actor_id": approval["backend_actor_id"],
    })

    projected = attempts.get_public("job-wf04a", 1, result.attempt_id)
    assert projected["reviewer_outcome"] == reviewer_outcome
    assert projected["repair_workflow_state"] == "repair_reviewer_override_approved"
    assert projected["apply_enabled"] is True
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_operator_decisions").fetchone()[0] == 1


def test_hard_gate_blocked_attempt_is_preserved_and_never_applicable(tmp_path: Path) -> None:
    conn = _conn()
    unsafe_diff = (
        "diff --git a/.env b/.env\n"
        "--- a/.env\n"
        "+++ b/.env\n"
        "@@ -1 +1 @@\n"
        "-SECRET=old\n"
        "+SECRET=new\n"
    )
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        diff_text=unsafe_diff,
        changed_files=[".env"],
    )
    attempt = SqliteV2RepairAttemptRepository(conn).get_public("job-wf04a", 1, result.attempt_id)

    assert result.status == "blocked"
    assert candidate_repo.latest_public_for_job("job-wf04a") is None
    assert attempt["applicability_status"] == "blocked"
    assert attempt["apply_enabled"] is False
    assert attempt["display_diff_redacted"] is True
    assert "SECRET=new" not in attempt["exact_proposed_diff"]
    internal = SqliteV2RepairAttemptRepository(conn).get_internal("job-wf04a", 1, result.attempt_id)
    assert internal["internal"]["exact_proposed_diff"] == unsafe_diff
    assert attempt["exact_diff_checksum"] == "sha256:" + sha256_hex(unsafe_diff.encode("utf-8"))
    assert "request_corrected_proposal" in attempt["operator_actions_available"]
    assert attempt["hard_gate_reason_codes"]


def test_manual_diff_creates_append_only_second_attempt_through_same_pipeline(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    prior = attempts.get_internal("job-wf04a", 1, first.attempt_id)
    manual_diff = (
        "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
        "--- a/src/main/java/App.java\n"
        "+++ b/src/main/java/App.java\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+manual\n"
    )

    result = execute_remediation_attempt(
        prior_attempt=prior,
        action="submit_manual_diff",
        model_client=_TxAssertingRepairClient(conn, reviewer_decision="reject"),
        invocation_ledger=V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        attempt_repo=attempts,
        event_repo=SqliteV2JobEventRepository(conn),
        manual_diff=manual_diff,
        operator_justification="Operator-investigated production-only correction.",
    )

    assert result["status"] == "persisted"
    assert result["attempt"]["attempt_number"] == 2
    assert result["attempt"]["attempt_source"] == "manual"
    assert result["attempt"]["previous_attempt_id"] == first.attempt_id
    assert result["attempt"]["reviewer_outcome"] == "rejected"
    assert result["attempt"]["approval_mode_required"] == "reviewer_override_approval"
    assert [item["attempt_number"] for item in attempts.list_public("job-wf04a", 1)] == [1, 2]


def test_invalid_manual_diff_is_preserved_as_actionable_invalid_attempt(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    prior = attempts.get_internal("job-wf04a", 1, first.attempt_id)

    result = execute_remediation_attempt(
        prior_attempt=prior,
        action="submit_manual_diff",
        model_client=_TxAssertingRepairClient(conn),
        invocation_ledger=V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        attempt_repo=attempts,
        event_repo=SqliteV2JobEventRepository(conn),
        manual_diff="this is not a canonical Git diff",
        operator_justification="Preserve this rejected operator submission for audit.",
    )

    assert result["status"] == "blocked"
    assert result["attempt"]["attempt_number"] == 2
    assert result["attempt"]["attempt_source"] == "manual"
    assert result["attempt"]["applicability_status"] == "invalid"
    assert result["attempt"]["exact_proposed_diff"] == "this is not a canonical Git diff"
    assert result["attempt"]["apply_enabled"] is False
    assert "request_corrected_proposal" in result["attempt"]["operator_actions_available"]
    assert len(attempts.list_public("job-wf04a", 1)) == 2


def test_corrected_proposal_preserves_guidance_and_prior_attempt(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    prior = attempts.get_internal("job-wf04a", 1, first.attempt_id)
    sandbox_app = Path(prior["internal"]["sandbox_path"]) / "src" / "main" / "java" / "App.java"
    sandbox_app.write_text("old line\nunchanged\n", encoding="utf-8")
    guidance = "Do not modify tests. Inspect production code and propose a smaller repair."

    result = execute_remediation_attempt(
        prior_attempt=prior,
        action="request_corrected_proposal",
        model_client=_TxAssertingRepairClient(conn),
        invocation_ledger=V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        attempt_repo=attempts,
        event_repo=SqliteV2JobEventRepository(conn),
        operator_guidance=guidance,
    )
    internal = attempts.get_internal("job-wf04a", 1, result["attempt"]["attempt_id"])

    assert result["attempt"]["attempt_number"] == 2
    assert result["attempt"]["previous_attempt_id"] == first.attempt_id
    assert internal["internal"]["review_chain"]["operator_guidance"] == guidance
    assert len(attempts.list_public("job-wf04a", 1)) == 2
    superseded = candidate_repo.get_public("job-wf04a", 1, first.llm_repair_candidate_id)
    assert superseded["status"] == "superseded"
    assert superseded["approval_enabled"] is False
    assert superseded["apply_enabled"] is False
    with pytest.raises(ValueError, match="repair_attempt_superseded"):
        execute_remediation_attempt(
            prior_attempt=prior,
            action="request_corrected_proposal",
            model_client=_TxAssertingRepairClient(conn),
            invocation_ledger=V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
            repair_repo=repair_repo,
            candidate_repo=candidate_repo,
            attempt_repo=attempts,
            event_repo=SqliteV2JobEventRepository(conn),
            operator_guidance="stale branch",
        )


def test_additional_context_is_contained_checksummed_and_creates_attempt(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    prior = attempts.get_internal("job-wf04a", 1, first.attempt_id)
    sandbox = Path(prior["internal"]["sandbox_path"])
    sandbox_app = sandbox / "src" / "main" / "java" / "App.java"
    sandbox_app.write_text("old line\nunchanged\n", encoding="utf-8")
    added = sandbox / "src" / "main" / "java" / "com" / "example" / "PaymentService.java"
    added.parent.mkdir(parents=True, exist_ok=True)
    added.write_text("package com.example; class PaymentService { void pay() {} }\n", encoding="utf-8")

    result = execute_remediation_attempt(
        prior_attempt=prior,
        action="request_additional_context",
        model_client=_TxAssertingRepairClient(conn),
        invocation_ledger=V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        attempt_repo=attempts,
        event_repo=SqliteV2JobEventRepository(conn),
        requested_context=("com.example.PaymentService",),
    )
    internal = attempts.get_internal("job-wf04a", 1, result["attempt"]["attempt_id"])
    evidence = internal["internal"]["context_pack"]["source_evidence"]

    assert result["attempt"]["attempt_number"] == 2
    assert any(item["path"] == "src/main/java/com/example/PaymentService.java" for item in evidence)
    assert all(str(item["checksum"]).startswith("sha256:") for item in evidence)
    assert internal["context_checksum"] != prior["context_checksum"]


def test_unsafe_additional_context_and_attempt_overflow_create_no_attempt(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    prior = attempts.get_internal("job-wf04a", 1, first.attempt_id)
    common = {
        "prior_attempt": prior,
        "action": "request_additional_context",
        "model_client": _TxAssertingRepairClient(conn),
        "invocation_ledger": V2LLMInvocationLedger(SqliteV2LLMInvocationRepository(conn)),
        "repair_repo": repair_repo,
        "candidate_repo": candidate_repo,
        "attempt_repo": attempts,
        "event_repo": SqliteV2JobEventRepository(conn),
    }

    with pytest.raises(ValueError, match="additional_context_not_found"):
        execute_remediation_attempt(**common, requested_context=("../outside.txt",))
    assert len(attempts.list_public("job-wf04a", 1)) == 1

    exhausted = {**prior, "internal": {**prior["internal"], "context_pack": {**prior["internal"]["context_pack"], "max_cycles": 1}}}
    with pytest.raises(ValueError, match="maximum_repair_attempts_reached"):
        execute_remediation_attempt(**{**common, "prior_attempt": exhausted}, requested_context=())
    assert "mark_manual_remediation_required" in prior["operator_actions_available"]
    assert len(attempts.list_public("job-wf04a", 1)) == 1


def test_chatbot_translation_only_previews_bounded_backend_action() -> None:
    command = repair_remediation_intent_from_text(
        "Do not modify tests. Inspect production code and propose another solution.",
        job_id="job-wf04a",
        stage_index=1,
        attempt_id="repair-attempt-1",
    )

    assert command == {
        "action": "request_corrected_proposal",
        "job_id": "job-wf04a",
        "stage_index": 1,
        "previous_attempt_id": "repair-attempt-1",
        "operator_guidance": "Do not modify tests. Inspect production code and propose another solution.",
        "confirmation_required": True,
        "authority": "backend_governed",
    }
    assert "actor_id" not in command
    assert "expected_attempt_checksum" not in command


def test_repair_attempt_routes_reject_stale_state_and_project_recorded_action(tmp_path: Path) -> None:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    conn = _conn()
    _seed_downstream_context(conn, tmp_path)
    result, _, _, _ = _persist(conn, tmp_path)
    attempts = SqliteV2RepairAttemptRepository(conn)
    current = attempts.get_public("job-wf04a", 1, result.attempt_id)
    client = TestClient(
        create_app(lambda: SqliteControlTowerUnitOfWork(conn)),
        base_url="http://127.0.0.1:8000",
    )
    headers = {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }
    url = f"/v1/v2/jobs/job-wf04a/stages/1/repair-attempts/{result.attempt_id}/actions"

    listing = client.get("/v1/v2/jobs/job-wf04a/stages/1/repair-attempts")
    assert listing.status_code == 200
    assert listing.json()["attempts"][0]["attempt_checksum"] == current["attempt_checksum"]

    stale = client.post(url, headers=headers, json={
        "action": "reject_current_attempt",
        "expected_attempt_checksum": "sha256:stale",
    })
    assert stale.status_code == 409
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_operator_actions").fetchone()[0] == 0

    recorded = client.post(url, headers=headers, json={
        "action": "reject_current_attempt",
        "expected_attempt_checksum": current["attempt_checksum"],
    })
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["attempt"]["repair_workflow_state"] == "repair_rejected"
    rejected_candidate = SqliteV2RepairCandidateRepository(conn).get_public(
        "job-wf04a",
        1,
        result.llm_repair_candidate_id,
    )
    assert rejected_candidate["status"] == "rejected"
    assert rejected_candidate["approval_enabled"] is False
    assert rejected_candidate["apply_enabled"] is False
    row = conn.execute("SELECT actor_type, actor_id, action_type FROM v2_repair_operator_actions").fetchone()
    assert row["action_type"] == "reject_current_attempt"
    assert row["actor_type"]
    assert row["actor_id"]


def test_resume_action_retries_blocked_route_continuation_from_verified_checkpoint(tmp_path: Path) -> None:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    conn = _conn()
    _seed_downstream_context(conn, tmp_path)
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    approval = approve_repair_apply_candidate(candidate, _llm_approval_request(candidate), actor_identity=_backend_actor())
    candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, approval)
    execution = apply_approved_repair_candidate(
        candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id),
        approval,
        post_repair_verification_runner=_ReviewedLlmPostRepairRunner(pass_tests=True),
        downstream_resume=lambda *_: {"downstream_resume_status": "blocked", "reason": "transient_queue_failure"},
    )
    candidate_repo.save_execution("job-wf04a", 1, result.llm_repair_candidate_id, execution)
    attempts = SqliteV2RepairAttemptRepository(conn)
    current = attempts.get_public("job-wf04a", 1, result.attempt_id)
    assert current["resume_enabled"] is True

    client = TestClient(
        create_app(lambda: SqliteControlTowerUnitOfWork(conn)),
        base_url="http://127.0.0.1:8000",
    )
    response = client.post(
        f"/v1/v2/jobs/job-wf04a/stages/1/repair-attempts/{result.attempt_id}/actions",
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:3000",
            "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
        },
        json={
            "action": "resume_from_repair_checkpoint",
            "expected_attempt_checksum": current["attempt_checksum"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] in {"queued", "route_complete"}
    assert response.json()["attempt"]["resume_enabled"] is False
    assert response.json()["route_continuation"]["downstream_resume_status"] in {"queued", "route_complete"}
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_operator_actions WHERE action_type = 'resume_from_repair_checkpoint'").fetchone()[0] == 1


def test_fastapi_reviewer_override_requires_risks_and_records_decision(tmp_path: Path) -> None:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    conn = _conn()
    _seed_downstream_context(conn, tmp_path)
    result, _, candidate_repo, _ = _persist(
        conn,
        tmp_path,
        reviewer_decision="reject",
        reviewer_outcome="rejected",
    )
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)
    request = _llm_approval_request(candidate)
    client = TestClient(
        create_app(lambda: SqliteControlTowerUnitOfWork(conn)),
        base_url="http://127.0.0.1:8000",
    )
    headers = {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }
    url = f"/v1/v2/jobs/job-wf04a/stages/1/repair-candidates/{result.llm_repair_candidate_id}/approve"

    missing = client.post(url, headers=headers, json={**request, "operator_justification": ""})
    assert missing.status_code == 409
    approved = client.post(url, headers=headers, json=request)
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval"]["approval_mode"] == "reviewer_override_approval"
    assert approved.json()["candidate"]["reviewer_outcome"] == "rejected"
    assert approved.json()["candidate"]["apply_enabled"] is True
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_operator_decisions").fetchone()[0] == 1
