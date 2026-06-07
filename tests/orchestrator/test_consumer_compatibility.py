from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.consumer_compatibility import (
    CommandRunResult,
    run_consumer_compatibility_validation,
)
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state


def test_consumer_validation_not_configured_returns_not_configured(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={},
        project_kind="spring_boot_application",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_CONFIGURED"
    assert payload["consumers_configured"] == 0
    assert payload["human_review_required"] is False


def test_library_without_consumers_adds_recommendation_warning(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={},
        project_kind="contract_library",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "NOT_CONFIGURED"
    assert any("consumer compatibility validation is required" in warning.lower() for warning in payload["warnings"])


def test_consumer_validation_passed_when_consumer_command_succeeds(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")
    consumer = _write_maven_project(tmp_path / "consumer-a")

    def runner(command: str, cwd: Path) -> CommandRunResult:
        return CommandRunResult(exit_code=0, stdout=f"ok:{cwd.name}:{command}", stderr="")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={"consumers": [str(consumer)]},
        project_kind="shared_library",
        command_runner=runner,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "PASSED"
    assert payload["consumer_results"][0]["status"] == "PASSED"
    assert payload["human_review_required"] is False


def test_consumer_validation_failed_when_consumer_command_fails(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")
    consumer = _write_maven_project(tmp_path / "consumer-a")

    def runner(command: str, cwd: Path) -> CommandRunResult:
        if cwd == consumer:
            return CommandRunResult(exit_code=1, stdout="", stderr="boom")
        return CommandRunResult(exit_code=0, stdout="ok", stderr="")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={"consumers": [str(consumer)]},
        project_kind="shared_library",
        command_runner=runner,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "FAILED"
    assert payload["human_review_required"] is True
    assert payload["production_allowed"] is False


def test_consumer_validation_aggregates_multiple_consumers(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")
    consumer_a = _write_maven_project(tmp_path / "consumer-a")
    consumer_b = _write_maven_project(tmp_path / "consumer-b")

    def runner(command: str, cwd: Path) -> CommandRunResult:
        if cwd == consumer_b:
            return CommandRunResult(exit_code=1, stdout="", stderr="fail")
        return CommandRunResult(exit_code=0, stdout="ok", stderr="")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={"consumers": [str(consumer_a), {"path": str(consumer_b), "command": "mvn test"}]},
        project_kind="shared_library",
        command_runner=runner,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "FAILED"
    assert len(payload["consumer_results"]) == 2
    assert [row["status"] for row in payload["consumer_results"]] == ["PASSED", "FAILED"]


def test_consumer_validation_does_not_modify_consumer_sources(tmp_path: Path) -> None:
    migrated = _write_maven_project(tmp_path / "sandbox")
    consumer = _write_maven_project(tmp_path / "consumer-a")
    source_file = consumer / "src" / "main" / "java" / "demo" / "Demo.java"
    before = source_file.read_text(encoding="utf-8")

    def runner(command: str, cwd: Path) -> CommandRunResult:
        (cwd / "target").mkdir(exist_ok=True)
        (cwd / "target" / "build.log").write_text("generated\n", encoding="utf-8")
        return CommandRunResult(exit_code=0, stdout="ok", stderr="")

    result = run_consumer_compatibility_validation(
        run_id="run-001",
        migrated_project_path=migrated,
        output_dir=tmp_path / "validation",
        config={"consumers": [str(consumer)]},
        project_kind="shared_library",
        command_runner=runner,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["consumer_results"][0]["source_files_modified"] is False
    assert source_file.read_text(encoding="utf-8") == before


def test_finalize_successful_sandbox_propagates_consumer_validation_artifacts(tmp_path: Path, monkeypatch) -> None:
    state = _successful_state(tmp_path)

    def fake_validation(**kwargs):
        output_dir = Path(kwargs["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        report = output_dir / "consumer_compatibility_report.json"
        summary = output_dir / "consumer_compatibility_summary.md"
        report.write_text(
            json.dumps(
                {
                    "gate_id": "CONSUMER_COMPATIBILITY_VALIDATION",
                    "status": "FAILED",
                    "production_allowed": False,
                    "human_review_required": True,
                    "consumer_results": [{"consumer_project_path": "c:/tmp/consumer", "status": "FAILED"}],
                    "warnings": ["consumer failed"],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        summary.write_text("# Consumer Compatibility Summary\n", encoding="utf-8")
        from migration_factory.orchestrator.consumer_compatibility import ConsumerCompatibilityResult

        return ConsumerCompatibilityResult(
            report_path=report,
            summary_path=summary,
            status="FAILED",
            warnings=["consumer failed"],
            human_review_required=True,
            production_allowed=False,
        )

    monkeypatch.setattr("migration_factory.orchestrator.summary.run_consumer_compatibility_validation", fake_validation)

    result = finalize_orchestration_state(state)
    payload = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))

    assert result["artifact_refs"]["consumer_compatibility_report"].endswith("consumer_compatibility_report.json")
    assert payload["artifact_refs"]["consumer_compatibility_report"].endswith("consumer_compatibility_report.json")
    assert payload["consumer_compatibility_status"] == "FAILED"
    assert payload["production_allowed"] is False


def _write_maven_project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pom.xml").write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
</project>
""".strip(),
        encoding="utf-8",
    )
    source = root / "src" / "main" / "java" / "demo"
    source.mkdir(parents=True, exist_ok=True)
    (source / "Demo.java").write_text("class Demo {}\n", encoding="utf-8")
    return root


def _successful_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    ai_hub.mkdir()
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(legacy),
        modernized_app_path=str(modernized),
        ai_hub_path=str(ai_hub),
        profile_id="java17",
        mode=FULL_SANDBOX_MIGRATION_MODE,
    )
    run_dir = Path(state["run_dir"])
    analysis_dir = Path(state["analysis_dir"])
    planning_dir = Path(state["planning_dir"])
    assessment_dir = Path(state["assessment_dir"])
    sandbox_dir = run_dir / "workspaces" / "sandbox"
    approval_dir = run_dir / "approval"
    transform_dir = run_dir / "transformation"
    logs_dir = run_dir / "logs"
    test_dir = run_dir / "test" / "post_transform"
    for directory in (analysis_dir, planning_dir, assessment_dir, sandbox_dir, approval_dir, transform_dir, logs_dir, test_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text(json.dumps({"project_kind": "contract_library"}) + "\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"source_stack": {"java": "11"}, "target_stack": {"java": "17"}, "project_kind": "contract_library"}) + "\n",
        encoding="utf-8",
    )
    (sandbox_dir / "pom.xml").write_text(
        """
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>1.0.0</version>
</project>
""".strip(),
        encoding="utf-8",
    )
    (sandbox_dir / ".migration").mkdir(parents=True, exist_ok=True)
    (sandbox_dir / ".migration" / "ledger.json").write_text("{}\n", encoding="utf-8")
    (approval_dir / "approval_decision.json").write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    (approval_dir / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (transform_dir / "transformation_execution_plan.yaml").write_text("recipes: []\n", encoding="utf-8")
    (logs_dir / "phase2_transform.log").write_text("ok\n", encoding="utf-8")
    (test_dir / "test_agent.log").write_text("ok\n", encoding="utf-8")
    (test_dir / "test_summary.md").write_text("# test\n", encoding="utf-8")
    (test_dir / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_PASSED",
                "totals": {"tests": 1, "passed": 1, "failures": 0, "errors": 0, "skipped": 0},
                "test_log_path": str(test_dir / "test_agent.log"),
                "source_log_path": str(logs_dir / "phase2_transform.log"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "orchestration_status": "PASS",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "sandbox_path": str(sandbox_dir),
            "final_status": "SANDBOX_MIGRATION_COMPLETED",
            "artifact_refs": {
                "analysis_report": str(analysis_dir / "analysis_report.json"),
                "migration_plan": str(planning_dir / "migration_plan.yaml"),
                "assessment_report": str(assessment_dir / "assessment_report.json"),
                "approval_decision": str(approval_dir / "approval_decision.json"),
                "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
                "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
                "migration_ledger": str(sandbox_dir / ".migration" / "ledger.json"),
                "phase2_log": str(logs_dir / "phase2_transform.log"),
                "post_transform_test_report": str(test_dir / "test_report.json"),
                "post_transform_test_summary": str(test_dir / "test_summary.md"),
                "post_transform_test_log": str(test_dir / "test_agent.log"),
            },
        }
    )
    return state
