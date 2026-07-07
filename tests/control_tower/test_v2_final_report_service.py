from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, create_autospec

import migration_factory.control_tower.application.v2_final_report_service as report_service_module
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


def test_generate_report_aggregates_full_stage_history(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "stage4-run"
    command1 = SimpleNamespace(
        command_id="cmd-1",
        stage_index=1,
        status="completed",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:01:00Z",
        result_json=json.dumps({
            "final_status": "PASS",
            "source_stack": {"java": "11", "spring_boot": "2.1.6"},
            "target_stack": {"java": "11", "spring_boot": "2.7.x"},
            "duration_seconds": 10,
            "artifact_refs": {"stage_report": "stage1/report.json"},
        }),
    )
    command2 = SimpleNamespace(
        command_id="cmd-2",
        stage_index=2,
        status="completed",
        created_at="2026-01-01T00:02:00Z",
        updated_at="2026-01-01T00:03:00Z",
        result_json=json.dumps({
            "final_status": "PASS",
            "source_stack": {"java": "11", "spring_boot": "2.7.x"},
            "target_stack": {"java": "17", "spring_boot": "3.5.x"},
            "duration_seconds": 20,
        }),
    )
    command4 = SimpleNamespace(
        command_id="cmd-4",
        stage_index=4,
        status="completed",
        created_at="2026-01-01T00:04:00Z",
        updated_at="2026-01-01T00:05:00Z",
        result_json=json.dumps({
            "final_status": "PASS",
            "status": "completed",
            "sandbox_path": str(run_dir),
            "source_stack": {"java": "21", "spring_boot": "3.5.x"},
            "target_stack": {"java": "21", "spring_boot": "4.0.0"},
            "duration_seconds": 40,
        }),
    )

    uow = _mock_uow()
    uow.v2_jobs.get.return_value = SimpleNamespace(job_id="job123")
    uow.v2_commands.list_by_job.return_value = (command1, command2, command4)
    uow.v2_commands.list_by_job_and_stage.return_value = (command4,)
    uow.v2_events.list_by_job.return_value = (
        SimpleNamespace(stage=1, type="stage_completed", status="completed", message="stage 1 done", created_at="2026-01-01T00:01:00Z"),
        SimpleNamespace(stage=4, type="final_report_started", status="running", message="report started", created_at="2026-01-01T00:05:00Z"),
    )
    uow.phase_gates.list_open.return_value = []
    uow.artifact_revisions.find_accepted.return_value = SimpleNamespace(revision_id="rev-4")
    uow.artifacts.list_for_job.return_value = []
    inserted = []
    uow.artifacts.insert.side_effect = inserted.append

    captured_state: dict[str, object] = {}

    def fake_generate(state: dict[str, object]):
        captured_state.update(state)
        final_dir = Path(str(state["run_dir"])) / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        json_path = final_dir / "migration_report.json"
        md_path = final_dir / "migration_summary.md"
        json_path.write_text(json.dumps({"ok": True}) + "\n", encoding="utf-8")
        md_path.write_text("# Report\n", encoding="utf-8")
        return SimpleNamespace(
            artifact_refs={
                "final_migration_report": str(json_path),
                "final_migration_summary": str(md_path),
            },
            blockers=[],
            warnings=[],
        )

    monkeypatch.setattr(report_service_module, "generate_final_migration_report", fake_generate)

    result = V2FinalReportService(MagicMock(return_value=uow)).generate_report("job123")

    assert result.status == "generated"
    assert len(inserted) == 3
    assert [stage["stage_index"] for stage in captured_state["pipeline_history"]] == [1, 2, 4]
    assert captured_state["full_migration_source_stack"] == {"java": "11", "spring_boot": "2.1.6"}
    assert captured_state["full_migration_target_stack"] == {"java": "21", "spring_boot": "4.0.0"}
    assert captured_state["pipeline_history"][0]["events"][0]["message"] == "stage 1 done"
    assert {artifact.kind for artifact in result.artifacts} == {
        "final_report_json",
        "final_report_markdown",
        "final_report_pdf",
    }
