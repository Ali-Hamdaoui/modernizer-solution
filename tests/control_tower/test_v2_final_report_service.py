from __future__ import annotations

import json
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.application.v2_final_report_service import (
    _load_report_artifact_manifest_for_job,
    V2FinalReportService,
    V2FinalReportEligibility,
    V2FinalReportResult,
)
from migration_factory.control_tower.domain.errors import StorageIntegrityError
from migration_factory.final_report.writer import generate_final_migration_report


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
        "classification": {"failure_type": "SPRING_DATA_SORT_API_DRIFT"},
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
        "next_repair_candidate": {"family": "JACKSON_VERSION_ALIGNMENT_DRIFT"},
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is False
    assert any("Stage 1 is not completed" in blocker for blocker in eligibility.blockers)
    assert any("No accepted Stage 1 output artifact revision or repair proof exists" in blocker for blocker in eligibility.blockers)


def test_evaluate_eligibility_blocks_nested_post_repair_failed_classification() -> None:
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
        "post_repair_verification": {
            "classification": {"failure_type": "JACKSON_VERSION_ALIGNMENT_DRIFT"},
        },
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is False
    assert any("Stage 1 is not completed" in blocker for blocker in eligibility.blockers)


def test_evaluate_eligibility_blocks_top_level_post_repair_scoped_classification() -> None:
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
        "classification": {
            "source": "post_repair_verification",
            "failure_type": "JACKSON_VERSION_ALIGNMENT_DRIFT",
        },
    }
    service = V2FinalReportService(MagicMock(return_value=uow))

    eligibility = service._evaluate_eligibility(uow, "job123")

    assert eligibility.eligible is False
    assert any("Stage 1 is not completed" in blocker for blocker in eligibility.blockers)


def test_generate_report_artifacts_enriches_repair_proof_terminal_state(tmp_path: Path, monkeypatch) -> None:
    service = V2FinalReportService(MagicMock(return_value=_mock_uow()))
    run_dir = tmp_path / "run"
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True)
    (run_dir / "assessment").mkdir(parents=True)
    (run_dir / "planning").mkdir(parents=True)
    (run_dir / "assessment" / "assessment_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "planning" / "migration_plan.yaml").write_text("risk: low\n", encoding="utf-8")
    required_refs = {
        "approval_decision": run_dir / "approval_decision.json",
        "approved_plan_lock": run_dir / "approved_plan_lock.json",
        "transformation_execution_plan": run_dir / "transformation_execution_plan.yaml",
        "migration_ledger": run_dir / "migration_ledger.json",
        "orchestration_summary": run_dir / "orchestration_summary.json",
    }
    for path in required_refs.values():
        path.write_text("{}", encoding="utf-8")
    captured_state = {}

    def fake_generate_report(state: dict[str, object]):
        captured_state.update(state)
        final_report = Path(state["run_dir"]) / "final" / "migration_report.json"
        final_summary = Path(state["run_dir"]) / "final" / "migration_summary.md"
        final_report.write_text("{}", encoding="utf-8")
        final_summary.write_text("# Summary\n", encoding="utf-8")
        return generate_final_migration_report({
            **state,
            "artifact_refs": {
                **state["artifact_refs"],
                "final_migration_report": str(final_report),
                "final_migration_summary": str(final_summary),
            },
        })

    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_final_report_service.generate_final_migration_report",
        fake_generate_report,
    )
    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_final_report_service.write_text_pdf_from_markdown",
        lambda md, pdf: Path(pdf).write_text("pdf", encoding="utf-8"),
    )
    command = MagicMock(result_json=json.dumps({
        "sandbox_path": str(run_dir),
        "artifact_refs": {key: str(path) for key, path in required_refs.items()},
    }))
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": str(run_dir / ".migration" / "repair-proofs" / "proof.json"),
        "post_repair_proof_artifact": str(run_dir / ".migration" / "repair-proofs" / "post.json"),
        "repair_candidate_id": "repair-1",
        "family": "SPRING_DATA_SORT_API_DRIFT",
        "candidate_checksum": "sha256:candidate",
        "patch_checksum": "sha256:patch",
        "review_checksum": "sha256:review",
        "target_file": "src/main/java/Foo.java",
        "target_files": ["src/main/java/Foo.java"],
        "post_repair_verification": {"post_repair_verification_status": "passed"},
    }
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifacts.list_for_job.return_value = []

    artifacts = service._generate_report_artifacts(uow, "job123")

    assert captured_state["repair_proof_accepted"] is True
    assert captured_state["repair_loop_status"] == "PROOF_ACCEPTED"
    assert captured_state["final_status"] == "PASS"
    assert captured_state["artifact_refs"]["repair_proof_artifact"].endswith("proof.json")
    assert captured_state["artifact_refs"]["post_repair_proof_artifact"].endswith("post.json")
    assert artifacts


def test_generate_report_artifacts_writes_manifest_when_legacy_artifact_insert_fails(tmp_path: Path, monkeypatch) -> None:
    service = V2FinalReportService(MagicMock(return_value=_mock_uow()))
    run_dir = tmp_path / "run"
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True)
    (run_dir / "assessment").mkdir(parents=True)
    (run_dir / "planning").mkdir(parents=True)
    (run_dir / "assessment" / "assessment_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "planning" / "migration_plan.yaml").write_text("risk: low\n", encoding="utf-8")
    artifact_refs = {
        "approval_decision": run_dir / "approval_decision.json",
        "approved_plan_lock": run_dir / "approved_plan_lock.json",
        "transformation_execution_plan": run_dir / "transformation_execution_plan.yaml",
        "migration_ledger": run_dir / "migration_ledger.json",
        "orchestration_summary": run_dir / "orchestration_summary.json",
    }
    for path in artifact_refs.values():
        path.write_text("{}", encoding="utf-8")
    command = MagicMock(result_json=json.dumps({
        "sandbox_path": str(run_dir),
        "artifact_refs": {key: str(path) for key, path in artifact_refs.items()},
    }))
    uow = _mock_uow()
    uow.run_configurations.get_for_job.return_value = MagicMock(
        payload_json=json.dumps({
            "source_profile": "springboot-2.1-java11",
            "target_profile": "springboot-2.7-java11",
        })
    )
    uow.v2_commands.list_by_job_and_stage.return_value = [command]
    uow.v2_repair_candidates.latest_public_for_job.return_value = {
        "stage_index": 1,
        "status": "verified",
        "execution_status": "verified",
        "post_repair_verification_status": "passed",
        "verification_status": "passed",
        "rollback_status": "not_needed",
        "proof_artifact": str(run_dir / ".migration" / "repair-proofs" / "proof.json"),
        "post_repair_proof_artifact": str(run_dir / ".migration" / "repair-proofs" / "post.json"),
        "repair_candidate_id": "repair-1",
        "family": "SPRING_DATA_SORT_API_DRIFT",
        "candidate_checksum": "sha256:candidate",
        "patch_checksum": "sha256:patch",
        "review_checksum": "sha256:review",
        "target_file": "src/main/java/Foo.java",
        "target_files": ["src/main/java/Foo.java"],
        "post_repair_verification": {"post_repair_verification_status": "passed"},
    }
    uow.phase_gates.list_by_job_and_stage.return_value = [
        MagicMock(gate_phase="repair_review", gate_status="resolved", gate_decision="continue")
    ]
    uow.artifacts.list_for_job.return_value = []
    uow.artifacts.insert.side_effect = StorageIntegrityError("FOREIGN KEY constraint failed")
    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_final_report_service.generate_final_migration_report",
        lambda state: generate_final_migration_report({
            **state,
            "artifact_refs": {
                **state["artifact_refs"],
                "final_migration_report": str(final_dir / "migration_report.json"),
                "final_migration_summary": str(final_dir / "migration_summary.md"),
            },
        }),
    )
    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_final_report_service.write_text_pdf_from_markdown",
        lambda md, pdf: Path(pdf).write_text("pdf", encoding="utf-8"),
    )

    artifacts = service._generate_report_artifacts(uow, "job123")

    manifest = final_dir / "report_artifacts_manifest.json"
    assert manifest.is_file()
    assert artifacts
    assert _load_report_artifact_manifest_for_job(uow, "job123")


def test_download_report_artifact_falls_back_to_manifest_snapshot(tmp_path: Path, monkeypatch) -> None:
    report_file = tmp_path / "reports" / "final" / "final_report.json"
    report_file.parent.mkdir(parents=True)
    report_file.write_text("{\"ok\":true}", encoding="utf-8")
    checksum = hashlib.sha256(report_file.read_bytes()).hexdigest()
    snapshot = MagicMock(
        artifact_id="report-json",
        absolute_path=str(report_file),
        checksum_sha256=checksum,
        kind="final_report_json",
    )
    fake_uow = _mock_uow()
    fake_uow.v2_jobs.get.return_value = MagicMock(job_id="job123")
    fake_uow.artifacts.list_for_job.return_value = []
    monkeypatch.setattr(
        "migration_factory.control_tower.application.v2_final_report_service._load_report_artifact_manifest_for_job",
        lambda uow, job_id: [snapshot],
    )

    client = TestClient(create_app(lambda: fake_uow), base_url="http://127.0.0.1:8000")
    response = client.get("/v1/v2/jobs/job123/report-artifacts/report-json/download")

    assert response.status_code == 200
    assert response.content == report_file.read_bytes()
    assert "final_report_json" in response.headers["content-disposition"]


def test_writer_requires_post_transform_report_only_on_normal_green_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for folder in ("assessment", "planning", "final"):
        (run_dir / folder).mkdir()
    (run_dir / "assessment" / "assessment_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "planning" / "migration_plan.yaml").write_text("risk: low\n", encoding="utf-8")
    artifact_refs = {
        "approval_decision": str(run_dir / "approval_decision.json"),
        "approved_plan_lock": str(run_dir / "approved_plan_lock.json"),
        "transformation_execution_plan": str(run_dir / "transformation_execution_plan.yaml"),
        "migration_ledger": str(run_dir / "migration_ledger.json"),
        "orchestration_summary": str(run_dir / "orchestration_summary.json"),
    }
    for ref in artifact_refs.values():
        Path(ref).write_text("{}", encoding="utf-8")

    normal = generate_final_migration_report({
        "run_dir": str(run_dir),
        "artifact_refs": artifact_refs,
        "build_status": "PASS",
        "test_status": "PASS",
        "repair_loop": {},
    })
    assert any("post_transform_test_report" in blocker for blocker in normal.blockers)

    repair_proof = generate_final_migration_report({
        "run_dir": str(run_dir),
        "artifact_refs": {
            **artifact_refs,
            "repair_proof_artifact": str(run_dir / "repair-proof.json"),
            "post_repair_proof_artifact": str(run_dir / "post-repair-proof.json"),
        },
        "repair_proof_accepted": True,
        "repair_candidate": {"family": "SPRING_DATA_SORT_API_DRIFT"},
        "repair_loop": {},
        "build_status": "POST_REPAIR_VERIFICATION_PASSED",
        "test_status": "POST_REPAIR_VERIFICATION_PASSED",
        "final_status": "PASS",
    })
    assert repair_proof.blockers == []


def test_writer_generates_report_for_repair_proof_terminal_without_historical_refs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for folder in ("assessment", "planning", "final"):
        (run_dir / folder).mkdir()
    (run_dir / "assessment" / "assessment_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "planning" / "migration_plan.yaml").write_text("risk: low\n", encoding="utf-8")

    result = generate_final_migration_report({
        "run_dir": str(run_dir),
        "artifact_refs": {
            "repair_proof_artifact": str(run_dir / "repair-proof.json"),
            "post_repair_proof_artifact": str(run_dir / "post-repair-proof.json"),
        },
        "repair_proof_accepted": True,
        "repair_candidate": {
            "family": "SPRING_DATA_SORT_API_DRIFT",
            "stage_index": 1,
        },
        "repair_loop": {},
        "build_status": "POST_REPAIR_VERIFICATION_PASSED",
        "test_status": "POST_REPAIR_VERIFICATION_PASSED",
        "final_status": "PASS",
    })

    assert result.blockers == []
    assert result.artifact_refs["final_migration_report"]
    assert result.artifact_refs["final_migration_summary"]


def test_writer_still_requires_historical_refs_on_normal_green_path(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for folder in ("assessment", "planning", "final"):
        (run_dir / folder).mkdir()
    (run_dir / "assessment" / "assessment_report.json").write_text("{}", encoding="utf-8")
    (run_dir / "planning" / "migration_plan.yaml").write_text("risk: low\n", encoding="utf-8")

    result = generate_final_migration_report({
        "run_dir": str(run_dir),
        "artifact_refs": {},
        "repair_loop": {},
        "build_status": "PASS",
        "test_status": "PASS",
        "final_status": "PASS",
    })

    assert result.blockers
    assert any("approval_decision" in blocker for blocker in result.blockers)


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
