from __future__ import annotations

import json
from unittest.mock import MagicMock

from migration_factory.control_tower.adapters.fastapi.app import (
    _overlay_repair_proof_acceptance,
    _repair_candidate_with_review_projection,
    _v2_stages_from_job,
    _v2_pipeline_projection,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_event_repository import V2JobEventRecord


def test_pipeline_projection_marks_r11_repair_proof_accepted() -> None:
    now = utc_now_text()
    events = (
        V2JobEventRecord("e1", "job-1", 1, "stage_started", "running", "started", "{}", now, 1),
        V2JobEventRecord(
            "e2",
            "job-1",
            1,
            "build_failed",
            "failed",
            "failed",
            json.dumps({"build_status": "BUILD_FAILED_IN_SANDBOX"}),
            now,
            2,
        ),
        V2JobEventRecord(
            "e3",
            "job-1",
            1,
            "repair_started",
            "running",
            "Repair loop status: REPAIR_REVIEW_REQUIRED",
            "{}",
            now,
            3,
        ),
    )

    projection = _v2_pipeline_projection("job-1", events, proof_accepted_stages={1})
    statuses = {row["key"]: row for row in projection["rows"]}

    assert statuses["failure_repair"]["status"] == "pass"
    assert statuses["result_contract"]["status"] == "pass"
    assert statuses["build_validation"]["status"] == "pass"
    assert "Repair proof accepted" in statuses["failure_repair"]["latest_message"]


def test_failure_summary_marks_verified_candidate_as_proof_accepted() -> None:
    summary = {
        "repair_loop_active": True,
        "failures": [
            {
                "stage": 1,
                "final_proof_level": "not_verified",
                "repair_loop_status": "REPAIR_REVIEW_REQUIRED",
                "next_operator_action": "Downstream remains blocked until backend proof is reviewed.",
            }
        ],
    }
    candidate = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
        "stage_recovery_status": "recovered",
    }
    uow = MagicMock()
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]

    _overlay_repair_proof_acceptance(summary, candidate, uow, "job-1")

    assert summary["repair_loop_active"] is False
    assert summary["repair_proof_status"] == "proof_accepted"
    assert summary["failures"][0]["final_proof_level"] == "proof_accepted"
    assert summary["failures"][0]["repair_loop_status"] == "PROOF_ACCEPTED"


def test_verified_candidate_with_open_gate_is_ready_not_accepted() -> None:
    candidate = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
    }
    uow = MagicMock()
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="open", gate_decision="pending")
    ]

    projected = _repair_candidate_with_review_projection(candidate, uow, "job-1")

    assert projected["proof_review_status"] == "ready_for_review"
    assert projected["proof_accepted"] is False


def test_contradictory_public_candidate_with_resolved_gate_is_proof_accepted() -> None:
    candidate = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "failed",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
    }
    uow = MagicMock()
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]

    projected = _repair_candidate_with_review_projection(candidate, uow, "job-1")

    assert projected["post_repair_verification_status"] == "passed"
    assert projected["proof_review_status"] == "accepted"
    assert projected["proof_accepted"] is True


def test_genuine_failed_post_repair_candidate_is_not_proof_accepted() -> None:
    candidate = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "failed",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
        "stage_recovery_status": "still_failed",
        "classification": {"failure_type": "JACKSON_VERSION_ALIGNMENT_DRIFT"},
        "next_repair_candidate": {"family": "JACKSON_VERSION_ALIGNMENT_DRIFT"},
    }
    uow = MagicMock()
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]

    projected = _repair_candidate_with_review_projection(candidate, uow, "job-1")

    assert projected["post_repair_verification_status"] == "failed"
    assert projected["proof_review_status"] == ""
    assert projected["proof_accepted"] is False


def test_stage_projection_marks_terminal_stage_proof_accepted() -> None:
    job = MagicMock(stage_chain_json=json.dumps([
        {
            "stage_index": 1,
            "stage_run_id": "",
            "pipeline_stage": "Stage 1",
            "input_source_kind": "legacy_source",
            "chain_status": "failed",
        }
    ]))

    stages = _v2_stages_from_job(job, (), (), proof_accepted_stages={1})

    assert stages[0]["chain_status"] == "proof_accepted"
