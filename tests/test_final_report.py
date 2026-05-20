from __future__ import annotations

import json
from pathlib import Path

import migration_factory.final_report.writer as final_report_writer
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state


def test_successful_full_sandbox_writes_final_report_and_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", raising=False)
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    final_report = Path(result["artifact_refs"]["final_migration_report"])
    final_summary = Path(result["artifact_refs"]["final_migration_summary"])
    assert final_report.is_file()
    assert final_summary.is_file()

    payload = json.loads(final_report.read_text(encoding="utf-8"))
    assert payload["test_status"] == "TEST_PASSED"
    assert payload["test_totals"]["tests"] == 3
    assert payload["approval"]["approval_ref"].endswith("approval_decision.json")
    assert payload["lock_status"]["lock_ref"].endswith("approved_plan_lock.json")
    assert payload["limitations"] == [
        "No production promotion performed.",
        "No pull request creation performed.",
    ]
    assert _as_posix(payload["timing"]["timing_report"]).endswith("performance/timing_report.json")
    assert _as_posix(payload["timing"]["timing_summary"]).endswith("performance/timing_summary.md")
    assert "copilot_migration_statement_json" not in result["artifact_refs"]
    assert "copilot_migration_statement_md" not in result["artifact_refs"]
    assert not (Path(state["run_dir"]) / "final" / "copilot_migration_statement.json").exists()
    assert "Copilot Advisory Statement" not in final_summary.read_text(encoding="utf-8")


def test_enabled_copilot_advisory_writes_artifacts_and_summary_reference(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", "true")
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    json_ref = Path(result["artifact_refs"]["copilot_migration_statement_json"])
    md_ref = Path(result["artifact_refs"]["copilot_migration_statement_md"])
    assert json_ref.is_file()
    assert md_ref.is_file()

    statement = json.loads(json_ref.read_text(encoding="utf-8"))
    assert statement["advisory_only"] is True
    assert statement["can_approve"] is False
    assert statement["can_transform"] is False
    assert statement["can_change_gates"] is False
    assert statement["can_mutate_source"] is False
    assert statement["can_override_status"] is False
    assert "sandbox migration candidate only" in statement["disclaimer"]
    assert "no production promotion, no PR, no deployment" in statement["disclaimer"]
    assert statement["facts"]["approval_decision"] == "approved"
    assert statement["facts"]["test_totals"]["tests"] == 3
    assert statement["facts"]["target_versions"] == {"java": "17"}

    advisory_md = md_ref.read_text(encoding="utf-8")
    assert "Copilot Advisory Statement" in advisory_md
    assert "sandbox migration candidate only" in advisory_md

    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")
    assert "## Copilot Advisory Statement" in final_summary
    assert "copilot_migration_statement.json" in final_summary
    assert "copilot_migration_statement.md" in final_summary

    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    assert final_report["artifact_refs"]["copilot_migration_statement_json"] == str(json_ref)
    assert final_report["artifact_refs"]["copilot_migration_statement_md"] == str(md_ref)


def test_copilot_advisory_failure_records_warning_without_failing_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_STATEMENT", "true")

    def fail_generation(payload, final_dir):
        raise RuntimeError("template unavailable")

    monkeypatch.setattr(final_report_writer, "_generate_copilot_advisory_statement", fail_generation)
    state = _successful_state(tmp_path)

    result = finalize_orchestration_state(state)

    assert result["orchestration_status"] == "PASS"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert result["orchestration_artifacts_valid"] is True
    assert Path(result["artifact_refs"]["final_migration_report"]).is_file()
    assert "copilot_migration_statement_json" not in result["artifact_refs"]
    assert "copilot_migration_statement_md" not in result["artifact_refs"]
    assert any("copilot advisory statement generation failed" in warning for warning in result["warnings"])


def test_missing_test_report_blocks_final_report_generation(tmp_path: Path) -> None:
    state = _successful_state(tmp_path)
    Path(state["artifact_refs"]["post_transform_test_report"]).unlink()

    result = finalize_orchestration_state(state)

    assert result["orchestration_artifacts_valid"] is False
    assert result["orchestration_status"] == "FAIL"
    assert result["final_status"] == "FAILED"
    assert "final_migration_report" not in result["artifact_refs"]
    assert any("post_transform_test_report" in blocker for blocker in result["blockers"])


def _successful_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    (ai_hub / "profiles").mkdir(parents=True)
    (ai_hub / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")

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

    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"source_stack": {"java": "11"}, "target_stack": {"java": "17"}}) + "\n",
        encoding="utf-8",
    )

    decision_path = approval_dir / "approval_decision.json"
    lock_path = approval_dir / "approved_plan_lock.json"
    exec_plan_path = transform_dir / "transformation_execution_plan.yaml"
    ledger_path = sandbox_dir / ".migration" / "ledger.json"
    phase2_log_path = logs_dir / "phase2_transform.log"
    test_report_path = test_dir / "test_report.json"
    test_summary_path = test_dir / "test_summary.md"
    test_log_path = test_dir / "test_agent.log"
    timing_report_path = run_dir / "performance" / "timing_report.json"
    timing_summary_path = run_dir / "performance" / "timing_summary.md"
    (sandbox_dir / ".migration").mkdir(parents=True, exist_ok=True)

    decision_path.write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    lock_path.write_text("{}\n", encoding="utf-8")
    exec_plan_path.write_text("recipes:\n  - org.openrewrite.java.migrate.UpgradeToJava17\n", encoding="utf-8")
    ledger_path.write_text("{}\n", encoding="utf-8")
    phase2_log_path.write_text("ok\n", encoding="utf-8")
    test_summary_path.write_text("# Test\n", encoding="utf-8")
    test_log_path.write_text("ok\n", encoding="utf-8")
    test_report_path.write_text(
        json.dumps(
            {
                "test_status": "TEST_PASSED",
                "totals": {"tests": 3, "passed": 3, "failures": 0, "errors": 0, "skipped": 0},
                "test_log_path": str(test_log_path),
                "source_log_path": str(phase2_log_path),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    timing_report_path.parent.mkdir(parents=True, exist_ok=True)
    timing_report_path.write_text("{}\n", encoding="utf-8")
    timing_summary_path.write_text("# timing\n", encoding="utf-8")

    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "approved_by": "reviewer",
            "orchestration_status": "PASS",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "test_totals": {"tests": 3, "passed": 3, "failures": 0, "errors": 0, "skipped": 0},
            "sandbox_path": str(sandbox_dir),
            "transform_log_path": str(phase2_log_path),
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "artifact_refs": {
                "approval_decision": str(decision_path),
                "approved_plan_lock": str(lock_path),
                "transformation_execution_plan": str(exec_plan_path),
                "migration_ledger": str(ledger_path),
                "phase2_log": str(phase2_log_path),
                "post_transform_test_report": str(test_report_path),
                "post_transform_test_summary": str(test_summary_path),
                "post_transform_test_log": str(test_log_path),
                "timing_report": str(timing_report_path),
                "timing_summary": str(timing_summary_path),
                "orchestration_summary": str(Path(state["orchestration_dir"]) / "orchestration_summary.json"),
            },
        }
    )
    return state


def _as_posix(path: str) -> str:
    return path.replace("\\", "/")
