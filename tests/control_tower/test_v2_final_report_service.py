from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from migration_factory.control_tower.application.v2_final_report_service import V2FinalReportService


@dataclass(frozen=True)
class _FakeJob:
    job_id: str
    stage_chain_json: str


@dataclass(frozen=True)
class _FakeCommand:
    stage_index: int
    argv_json: str


class _FakeJobRepo:
    def get(self, job_id: str) -> _FakeJob | None:
        return _FakeJob(
            job_id=job_id,
            stage_chain_json=json.dumps(
                [
                    {"stage_index": 1, "pipeline_stage": "baseline", "input_source_kind": "legacy"},
                    {"stage_index": 2, "pipeline_stage": "boot-3-5", "input_source_kind": "stage-output"},
                    {"stage_index": 3, "pipeline_stage": "java-21", "input_source_kind": "stage-output"},
                    {"stage_index": 4, "pipeline_stage": "boot-4", "input_source_kind": "stage-output"},
                ]
            ),
        )


class _FakeCommandRepo:
    def __init__(self, commands: tuple[_FakeCommand, ...]) -> None:
        self._commands = commands

    def list_by_job(self, job_id: str) -> tuple[_FakeCommand, ...]:
        assert job_id == "job-123"
        return self._commands


def test_generate_report_writes_docs_copy_and_includes_full_pipeline_history(tmp_path: Path) -> None:
    modernized_root = tmp_path / "modernized"
    stage_run_ids = {
        1: "v2-job-123-s1",
        2: "v2-job-123-s2",
        3: "v2-job-123-s3",
        4: "v2-job-123-s4",
    }
    _seed_successful_run(
        modernized_root / ".migration" / "runs" / stage_run_ids[1],
        source_java="11",
        source_boot="2.1.6",
        target_java="11",
        target_boot="2.7.18",
        recipe="org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7",
        duration_seconds=18.5,
    )
    _seed_successful_run(
        modernized_root / ".migration" / "runs" / stage_run_ids[2],
        source_java="11",
        source_boot="2.7.18",
        target_java="17",
        target_boot="3.5.6",
        recipe="org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5",
        duration_seconds=31.75,
    )
    _seed_successful_run(
        modernized_root / ".migration" / "runs" / stage_run_ids[3],
        source_java="17",
        source_boot="3.5.6",
        target_java="21",
        target_boot="3.5.6",
        recipe="org.openrewrite.java.migrate.UpgradeToJava21",
        duration_seconds=42.25,
    )
    _seed_successful_run(
        modernized_root / ".migration" / "runs" / stage_run_ids[4],
        source_java="21",
        source_boot="3.5.6",
        target_java="21",
        target_boot="4.0.7",
        recipe="org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0",
        duration_seconds=27.0,
    )
    service = V2FinalReportService(
        job_repo=_FakeJobRepo(),
        command_repo=_FakeCommandRepo(
            tuple(
                _FakeCommand(
                    stage_index=stage_index,
                    argv_json=json.dumps(
                        [
                            "python",
                            "-m",
                            "migration_factory.orchestrator.runner",
                            "--run-id",
                            run_id,
                            "--modernized",
                            str(modernized_root),
                        ]
                    ),
                )
                for stage_index, run_id in stage_run_ids.items()
            )
        ),
    )
    service._repo_root = tmp_path
    stale_markdown = tmp_path / "docs" / "migration-reports" / "job-123" / "stale_report.md"
    stale_markdown.parent.mkdir(parents=True, exist_ok=True)
    stale_markdown.write_text("# old\n", encoding="utf-8")

    report = service.generate_report("job-123")

    assert report.docs_report_json == "docs/migration-reports/job-123/migration_report.json"
    assert report.docs_report_markdown == "docs/migration-reports/job-123/full_migration_report.md"
    assert report.docs_report_pdf == "docs/migration-reports/job-123/full_migration_report.pdf"
    assert report.total_duration_seconds == 119.5
    assert report.full_migration_source_stack == {"spring_boot": "2.1.6", "java": "11"}
    assert report.full_migration_target_stack == {"spring_boot": "4.0.7", "java": "21"}
    assert len(report.pipeline_history) == 4
    assert "Spring Boot 2.1.6 / Java 11 -> Spring Boot 4.0.7 / Java 21" in report.summary
    assert any("Stage 1 (springboot-2.1.6-to-2.7-java11)" in item for item in report.change_summary)
    assert any("Stage 4 (springboot-3.5-java21-to-4.0-java21)" in item for item in report.change_summary)
    assert any("Spring Boot changed from 3.5.6 to 4.0.7." == item for item in report.change_summary)
    assert any("Executed OpenRewrite recipes:" in item for item in report.change_summary)
    assert (tmp_path / report.docs_report_json).is_file()
    assert (tmp_path / report.docs_report_markdown).is_file()
    assert (tmp_path / report.docs_report_pdf).is_file()
    pdf_bytes = (tmp_path / report.docs_report_pdf).read_bytes()
    assert pdf_bytes.startswith(b"%PDF-1.4")
    assert len(pdf_bytes) > 1500
    assert not stale_markdown.exists()
    markdown = (tmp_path / report.docs_report_markdown).read_text(encoding="utf-8")
    assert "# Final Migration Report" in markdown
    assert "## 1. Executive Summary" in markdown
    assert "## 5. Stage-By-Stage Journey" in markdown
    assert "## 12. Timing" in markdown
    assert "119.500s" in markdown
    assert "## 6. What Changed" in markdown
    assert "## 13. Related Artifacts" in markdown
    assert "| **Legacy Baseline** | **Spring Boot 2.1.6 / Java 11** |" in markdown
    assert "| **Current Application State** | **Spring Boot 4.0.7 / Java 21** |" in markdown
    assert "Legacy application baseline: Spring Boot 2.1.6 / Java 11" in markdown
    assert "Latest completed stage: Stage 4: springboot-3.5-java21-to-4.0-java21" in markdown
    assert "Completed stage transition: Spring Boot 3.5.6 / Java 21 -> Spring Boot 4.0.7 / Java 21" in markdown
    assert "Current application state: Spring Boot 4.0.7 / Java 21" in markdown
    assert "Final executed target: Spring Boot 4.0.7 / Java 21" in markdown
    assert "| **Stage 1** | `springboot-2.1.6-to-2.7-java11` |" in markdown
    assert "| **Stage 4** | `springboot-3.5-java21-to-4.0-java21` |" in markdown
    assert "Narrative highlights:" in markdown

    regenerated = service.generate_report("job-123")
    assert regenerated.docs_report_markdown == report.docs_report_markdown


def _seed_successful_run(
    run_dir: Path,
    *,
    source_java: str,
    source_boot: str,
    target_java: str,
    target_boot: str,
    recipe: str,
    duration_seconds: float,
) -> None:
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
                f'  java: "{target_java}"',
                f'  spring_boot: "{target_boot}"',
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
                "source_stack": {"java": source_java, "spring_boot": source_boot},
                "target_stack": {"java": target_java, "spring_boot": target_boot},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (approval_dir / "approval_decision.json").write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    (approval_dir / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (transform_dir / "transformation_execution_plan.yaml").write_text(
        f"recipes:\n  - {recipe}\n",
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
        json.dumps({"phase_durations_seconds": {"total_run": duration_seconds}}) + "\n",
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
