from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from migration_factory.control_tower.application.v2_final_report_service import V2FinalReportService


@dataclass(frozen=True)
class _FakeJob:
    job_id: str


@dataclass(frozen=True)
class _FakeCommand:
    argv_json: str


class _FakeJobRepo:
    def get(self, job_id: str) -> _FakeJob | None:
        return _FakeJob(job_id=job_id)


class _FakeCommandRepo:
    def __init__(self, argv_json: str) -> None:
        self._command = _FakeCommand(argv_json=argv_json)

    def list_by_job_and_stage(self, job_id: str, stage_index: int) -> tuple[_FakeCommand, ...]:
        assert job_id == "job-123"
        assert stage_index == 3
        return (self._command,)


def test_generate_report_writes_docs_copy_and_includes_duration_and_changes(tmp_path: Path) -> None:
    modernized_root = tmp_path / "modernized"
    run_id = "v2-job-123-s3"
    run_dir = modernized_root / ".migration" / "runs" / run_id
    _seed_successful_run(run_dir)
    service = V2FinalReportService(
        job_repo=_FakeJobRepo(),
        command_repo=_FakeCommandRepo(
            json.dumps(
                [
                    "python",
                    "-m",
                    "migration_factory.orchestrator.runner",
                    "--run-id",
                    run_id,
                    "--modernized",
                    str(modernized_root),
                ]
            )
        ),
    )
    service._repo_root = tmp_path

    report = service.generate_report("job-123")

    assert report.docs_report_json == "docs/migration-reports/job-123/migration_report.json"
    assert report.docs_report_markdown == "docs/migration-reports/job-123/migration_summary.md"
    assert report.total_duration_seconds == 42.25
    assert any("Java changed from 17 to 21." == item for item in report.change_summary)
    assert any("Executed OpenRewrite recipes:" in item for item in report.change_summary)
    assert (tmp_path / report.docs_report_json).is_file()
    assert (tmp_path / report.docs_report_markdown).is_file()
    markdown = (tmp_path / report.docs_report_markdown).read_text(encoding="utf-8")
    assert "## Migration Process" in markdown
    assert "## Timing" in markdown
    assert "42.250s" in markdown
    assert "## What Changed" in markdown
    assert "## Related Artifacts" in markdown
    assert "Source Java: 17" in markdown
    assert "Target Java: 21" in markdown


def _seed_successful_run(run_dir: Path) -> None:
    analysis_dir = run_dir / "analysis"
    planning_dir = run_dir / "planning"
    assessment_dir = run_dir / "assessment"
    approval_dir = run_dir / "approval"
    transform_dir = run_dir / "transformation"
    logs_dir = run_dir / "logs"
    test_dir = run_dir / "test" / "post_transform"
    perf_dir = run_dir / "performance"
    sandbox_dir = run_dir / "workspaces" / "sandbox" / ".migration"
    for directory in (
        analysis_dir,
        planning_dir,
        assessment_dir,
        approval_dir,
        transform_dir,
        logs_dir,
        test_dir,
        perf_dir,
        sandbox_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text(
        "\n".join(
            [
                "risk: MEDIUM",
                "requires_human_approval: true",
                "target_stack:",
                '  java: "21"',
                '  spring_boot: "3.5.6"',
                "profile_governance:",
                "  strategy: staged_openrewrite",
                "  fallback_profile: none",
                "  production_allowed: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps(
            {
                "source_stack": {"java": "17", "spring_boot": "3.5.6"},
                "target_stack": {"java": "21", "spring_boot": "3.5.6"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (approval_dir / "approval_decision.json").write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    (approval_dir / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (transform_dir / "transformation_execution_plan.yaml").write_text(
        "recipes:\n  - org.openrewrite.java.migrate.UpgradeToJava21\n",
        encoding="utf-8",
    )
    (sandbox_dir / "ledger.json").write_text("{}\n", encoding="utf-8")
    (logs_dir / "phase2_transform.log").write_text("ok\n", encoding="utf-8")
    (test_dir / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_PASSED",
                "totals": {"tests": 12, "passed": 12, "failures": 0, "errors": 0, "skipped": 0},
                "test_log_path": str(test_dir / "test_agent.log"),
                "source_log_path": str(logs_dir / "phase2_transform.log"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (test_dir / "test_summary.md").write_text("# Test Summary\n", encoding="utf-8")
    (test_dir / "test_agent.log").write_text("tests passed\n", encoding="utf-8")
    (perf_dir / "timing_report.json").write_text(
        json.dumps({"phase_durations_seconds": {"total_run": 42.25}}) + "\n",
        encoding="utf-8",
    )
    (perf_dir / "timing_summary.md").write_text("# Timing Summary\n", encoding="utf-8")
    orchestration_summary = {
        "run_id": "run-123",
        "approval_status": "COMPLETED",
        "approval_decision": "approved",
        "approved_by": "operator",
        "orchestration_status": "PASS",
        "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "build_status": "BUILD_PASSED_IN_SANDBOX",
        "test_status": "TEST_PASSED",
        "test_totals": {"tests": 12, "passed": 12, "failures": 0, "errors": 0, "skipped": 0},
        "sandbox_path": str(run_dir / "workspaces" / "sandbox"),
        "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "artifact_refs": {
            "approval_decision": str(approval_dir / "approval_decision.json"),
            "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
            "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
            "migration_ledger": str(sandbox_dir / "ledger.json"),
            "phase2_log": str(logs_dir / "phase2_transform.log"),
            "post_transform_test_report": str(test_dir / "test_report.json"),
            "orchestration_summary": str(run_dir / "orchestration" / "orchestration_summary.json"),
            "timing_report": str(perf_dir / "timing_report.json"),
            "timing_summary": str(perf_dir / "timing_summary.md"),
        },
    }
    orchestration_dir = run_dir / "orchestration"
    orchestration_dir.mkdir(parents=True, exist_ok=True)
    (orchestration_dir / "orchestration_summary.json").write_text(
        json.dumps(orchestration_summary) + "\n",
        encoding="utf-8",
    )
