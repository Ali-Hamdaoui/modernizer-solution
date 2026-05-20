from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state


def test_successful_full_sandbox_writes_final_report_and_summary(tmp_path: Path) -> None:
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
                "orchestration_summary": str(Path(state["orchestration_dir"]) / "orchestration_summary.json"),
            },
        }
    )
    return state
