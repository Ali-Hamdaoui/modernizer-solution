from __future__ import annotations

import json
from unittest.mock import MagicMock, create_autospec

from migration_factory.control_tower.application.v2_final_report_service import (
    V2FinalReportService,
    V2FinalReportEligibility,
    V2FinalReportResult,
)


def _mock_uow(v2_jobs: MagicMock | None = None, v2_commands: MagicMock | None = None) -> MagicMock:
    uow = MagicMock()
    uow.v2_jobs = v2_jobs or MagicMock()
    uow.v2_commands = v2_commands or MagicMock()
    uow.__enter__ = MagicMock(return_value=uow)
    uow.__exit__ = MagicMock(return_value=None)
    return uow


def test_get_report_status_returns_not_generated_for_new_job() -> None:
    uow = _mock_uow()
    uow.v2_jobs.get.return_value = MagicMock(job_id="job123")
    uow.v2_commands.list_by_job_and_stage.return_value = []
    factory = MagicMock(return_value=uow)
    service = V2FinalReportService(factory)

    result = service.get_report_status("job123")

    assert result.job_id == "job123"
    assert result.status == "not_generated"
    assert result.eligible is False
    assert len(result.blockers) > 0


def test_generate_report_returns_blocked_when_ineligible() -> None:
    uow = _mock_uow()
    uow.v2_jobs.get.return_value = MagicMock(job_id="job123")
    uow.v2_commands.list_by_job_and_stage.return_value = []
    factory = MagicMock(return_value=uow)
    service = V2FinalReportService(factory)

    result = service.generate_report("job123")

    assert result.status == "blocked"
    assert result.eligible is False


def test_evaluate_eligibility_fails_without_stage4() -> None:
    uow = _mock_uow()
    uow.v2_commands.list_by_job_and_stage.return_value = []
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is False
    assert any("Stage 4" in b for b in eligibility.blockers)


def test_evaluate_eligibility_accepts_stage1_repair_proof_for_boot27_route() -> None:
    command = MagicMock(
        status="failed",
        result_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
            "route_metadata": {
                "source_profile": "springboot-2.1-java11",
                "target_profile": "springboot-2.7-java11",
                "included_stages": [1],
                "route_steps": [{"stage_index": 1}],
            },
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
        }),
    )
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job.return_value = [command]
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.phase_gates.list_open.return_value = []
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifact_revisions.find_accepted.return_value = None
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is True
    uow.v2_commands.list_by_job_and_stage.assert_called_with("job123", 1)


def test_evaluate_eligibility_uses_run_configuration_route_when_command_lacks_route_metadata() -> None:
    command = MagicMock(
        status="failed",
        result_json=json.dumps({
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
        }),
    )
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job.return_value = [command]
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.phase_gates.list_open.return_value = []
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifact_revisions.find_accepted.return_value = None
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is True
    uow.v2_commands.list_by_job_and_stage.assert_called_with("job123", 1)


def test_evaluate_eligibility_accepts_contradictory_stale_post_repair_status() -> None:
    command = MagicMock(
        status="blocked",
        result_json=json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}),
    )
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job.return_value = [command]
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.phase_gates.list_open.return_value = []
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifact_revisions.find_accepted.return_value = None
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "failed",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": "proof.json",
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is True
    assert eligibility.blockers == []
    uow.v2_commands.list_by_job_and_stage.assert_called_with("job123", 1)


def test_evaluate_eligibility_blocks_genuine_failed_post_repair_status() -> None:
    command = MagicMock(
        status="blocked",
        result_json=json.dumps({"final_status": "BUILD_FAILED_IN_SANDBOX"}),
    )
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job.return_value = [command]
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.phase_gates.list_open.return_value = []
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifact_revisions.find_accepted.return_value = None
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
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
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is False
    assert any("Stage 1 is not completed" in blocker for blocker in eligibility.blockers)
    assert any("No accepted Stage 1 output artifact revision or repair proof exists" in blocker for blocker in eligibility.blockers)


def test_report_result_contains_no_path_fields() -> None:
    result = V2FinalReportResult(
        job_id="job123",
        status="not_generated",
        eligible=False,
        blockers=[],
        generated_at=None,
        input_checksum=None,
        redacted_summary="",
        artifacts=(),
    )
    d = {
        "job_id": result.job_id,
        "status": result.status,
        "eligible": result.eligible,
        "blockers": list(result.blockers),
        "generated_at": result.generated_at,
        "input_checksum": result.input_checksum,
        "redacted_summary": result.redacted_summary,
        "artifacts": [
            {
                "artifact_id": a.artifact_id,
                "kind": a.kind,
                "checksum_sha256": a.checksum_sha256,
                "size_bytes": a.size_bytes,
                "content_type": a.content_type,
                "download_url": a.download_url,
            }
            for a in result.artifacts
        ],
    }
    assert "run_dir" not in d
    assert "sandbox_path" not in d
    assert "run_report_json" not in d
    assert "run_report_markdown" not in d
    assert "run_report_pdf" not in d
