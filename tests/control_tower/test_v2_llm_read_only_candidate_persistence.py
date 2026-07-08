from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_llm_read_only_candidate_persistence import (
    EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED,
    EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED,
    LlmReadOnlyCandidatePersistenceService,
    emit_llm_read_only_candidate_event,
)
from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    apply_approved_repair_candidate,
    approve_repair_apply_candidate,
)
from migration_factory.control_tower.application.v2_repair_projection import (
    build_reviewed_diff_proposal_from_record,
    reviewed_diff_proposal_to_safe_dict,
)
from migration_factory.control_tower.application.v2_repair_route_decision import RepairRouteDecision
from migration_factory.control_tower.domain.checksums import sha256_hex
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteControlTowerUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_event_repository import SqliteV2JobEventRepository
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_candidate_repository import (
    SqliteV2RepairCandidateRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import SqliteV2RepairRepository
from migration_factory.repair_loop.failure_evidence import FailureSource, build_failure_evidence
from migration_factory.repair_loop.repair_context import build_repair_context_pack


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
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


def _chain(output_dir: Path, context: Any, diff_text: str | None = None, **overrides: Any) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    diff_path = output_dir / "final_reviewed_repair.diff"
    diff_path.write_bytes(
        (diff_text or (
            "diff --git a/src/main/java/App.java b/src/main/java/App.java\n"
            "--- a/src/main/java/App.java\n"
            "+++ b/src/main/java/App.java\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "+new\n"
        )).encode("utf-8")
    )
    checksum = "sha256:" + sha256_hex(diff_path.read_bytes())
    chain = {
        "reviewer_decision": "accept",
        "proposal_kind": "llm_repair_review",
        "context_pack_checksum": context.context_pack_checksum,
        "job_id": context.job_id,
        "stage_index": context.stage_index,
        "primary_output_checksum": "sha256:" + "1" * 64,
        "reviewer_output_checksum": "sha256:" + "2" * 64,
        "proposed_diff_checksum": checksum,
        "raw_diff_bytes_checksum": checksum,
        "final_reviewed_diff_checksum": checksum,
        "final_artifact_checksum": "sha256:" + "4" * 64,
        "primary_deterministic_fallback_used": False,
        "reviewer_deterministic_fallback_used": False,
        "final_diff_ref": str(diff_path),
    }
    chain.update(overrides)
    return {"artifact_refs": {"final_reviewed_diff": str(diff_path)}, "review_chain": chain}


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
                "@@ -1,3 +1,3 @@\n"
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
    return {
        "build_status": "BUILD_FAILED",
        "test_status": "",
        "run_dir": str(run_dir),
        "failure_summary": "Build failed with opaque status",
        "artifact_refs": {
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
    output_dir = tmp_path / "review-chain"
    service = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        event_repo=event_repo,
    )
    result = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, **overrides),
        output_dir=output_dir,
        source_proposal_id="source-proposal-1",
        source_gate_id="source-gate-1",
    )
    return result, repair_repo, candidate_repo, context


def test_accept_persists_one_proposal_one_candidate_and_replay_is_idempotent(tmp_path: Path) -> None:
    conn = _conn()
    first, repair_repo, candidate_repo, _ = _persist(conn, tmp_path)
    second, _, _, _ = _persist(conn, tmp_path)

    assert first.status == "persisted"
    assert second.status == "idempotent"
    assert len(repair_repo.list_proposals_by_job("job-wf04a")) == 1
    assert candidate_repo.latest_public_for_job("job-wf04a")["repair_candidate_id"] == first.llm_repair_candidate_id
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
    output_dir = tmp_path / "review-chain"
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
    output_dir = tmp_path / "review-chain"

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
    output_dir = tmp_path / "review-chain"

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
    )

    assert result.status == "blocked"
    assert result.reason == "llm_candidate_persistence_configuration_incomplete"


def test_missing_event_repository_blocks_without_rows_or_events(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    output_dir = tmp_path / "review-chain"

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
    output_dir = tmp_path / "review-chain"
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

    assert events[:3] == [
        "llm_review_chain_started",
        "llm_review_chain_completed",
        EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED,
    ]
    assert events[-1] == EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED
    assert "llm_review_chain_blocked" not in events


def test_diff_outside_output_dir_and_checksum_mismatch_rejected(tmp_path: Path) -> None:
    conn = _conn()
    repair_repo, candidate_repo = _repos(conn)
    evidence = _evidence()
    context = _context(evidence)
    output_dir = tmp_path / "review-chain"
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
    )
    mismatch = service.persist(
        decision=_decision(evidence, context),
        failure_evidence=evidence,
        context_pack=context,
        chain_result=_chain(output_dir, context, raw_diff_bytes_checksum="sha256:" + "8" * 64),
        output_dir=output_dir,
    )

    assert outside_result.reason == "reviewed_diff_ref_outside_output_dir"
    assert mismatch.reason in {"llm_candidate_invalid_review_chain", "reviewed_diff_checksum_mismatch"}
    assert repair_repo.list_proposals_by_job("job-wf04a") == ()


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
    assert "deterministic_rule_id" not in json.dumps(metadata)
    assert projection["safe_diff_preview"]["checksum_mismatch"] is False
    assert projection["safe_diff_preview"]["files"][0]["path"] == "src/main/java/App.java"


def test_repository_rejects_approval_execution_and_public_reads_stay_false(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)

    with pytest.raises(ValueError, match="llm_candidate_not_actionable"):
        candidate_repo.save_approval("job-wf04a", 1, result.llm_repair_candidate_id, {"approval_status": "approved"})
    with pytest.raises(ValueError, match="llm_candidate_not_actionable"):
        candidate_repo.save_execution("job-wf04a", 1, result.llm_repair_candidate_id, {"status": "applied"})

    conn.execute(
        """UPDATE v2_repair_apply_candidates
           SET status = 'approved', approval_json = ?, execution_json = ?
           WHERE repair_candidate_id = ?""",
        (json.dumps({"approval_status": "approved"}), json.dumps({"status": "applied"}), result.llm_repair_candidate_id),
    )
    public = candidate_repo.get_public("job-wf04a", 1, result.llm_repair_candidate_id)
    latest = candidate_repo.latest_public_for_job("job-wf04a")

    for value in (public, latest):
        assert value["status"] == "read_only"
        assert value["approval_enabled"] is False
        assert value["apply_enabled"] is False
        assert value["sandbox_only"] is True


def test_application_guards_still_reject_llm_candidate(tmp_path: Path) -> None:
    conn = _conn()
    result, _, candidate_repo, _ = _persist(conn, tmp_path)
    candidate = candidate_repo.get_internal("job-wf04a", 1, result.llm_repair_candidate_id)

    with pytest.raises(ValueError, match="llm_candidate_not_actionable"):
        approve_repair_apply_candidate(candidate, {})
    with pytest.raises(ValueError, match="llm_candidate_not_actionable"):
        apply_approved_repair_candidate(candidate, {"approval_status": "approved"})


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
    assert all(row["attempt_number"] == 0 for row in invocation_rows)
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
    assert latest_candidate["approval_enabled"] is False
    assert latest_candidate["apply_enabled"] is False
    assert conn.execute("SELECT COUNT(*) FROM v2_phase_gates").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_stage_commands WHERE job_id = ? AND stage_index > 1", ("job-wf04a",)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v2_repair_apply_candidates WHERE approval_json NOT IN ('', '{}') OR execution_json NOT IN ('', '{}')").fetchone()[0] == 0
    assert app.state.v2_failure_diagnosis_service.get_diagnosis("cmd-wf04a", "build_failed") is None
    assert route_payload["route"] == "llm_reviewed_unknown"
    assert route_payload["classification_status"] == "unknown"
    assert metadata["failure_evidence_checksum"] == route_payload["evidence_checksum"]
    assert metadata["context_checksum"] == route_payload["context_checksum"]
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
            "llm_read_only_candidate_persisted",
            "llm_read_only_candidate_blocked",
        }
    ] == [
        "repair_route_selected",
        "llm_review_chain_started",
        "llm_review_chain_completed",
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
