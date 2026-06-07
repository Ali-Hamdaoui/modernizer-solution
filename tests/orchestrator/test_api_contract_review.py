from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.api_contract_review import build_api_contract_review
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state


def test_api_contract_review_detects_http_status_drift_from_classification(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_controller_advice(sandbox)
    _write_test_hint_file(sandbox)
    result = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=sandbox,
        failure_classification={
            "category_counts": {"HTTP_STATUS_CONTRACT_DRIFT": 1},
            "failures": [
                {
                    "test_class": "com.example.CustomExceptionTranslatorTest",
                    "test_method": "requestMethodNotSupported",
                    "category": "HTTP_STATUS_CONTRACT_DRIFT",
                    "symptom": "expected:<404> but was:<405>",
                    "suggested_next_action": "Review expected HTTP status codes and exception-to-response mappings under Spring Boot 3.",
                }
            ],
        },
        orchestration_summary={"run_id": "run-001"},
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["detected"] is True
    assert payload["gate_id"] == "API_CONTRACT_REVIEW_GATE"
    assert payload["human_review_required"] is True
    assert payload["safe_to_auto_apply"] is False
    assert payload["detected_failure_categories"] == ["HTTP_STATUS_CONTRACT_DRIFT"]
    assert payload["affected_source_files"][0]["file"].endswith("CustomExceptionTranslator.java")
    assert payload["affected_tests"][0]["test_class"] == "com.example.CustomExceptionTranslatorTest"
    assert payload["affected_tests"][0]["test_hint_files"][0].endswith("CustomExceptionTranslatorTest.java")


def test_api_contract_review_detects_spring_mvc_behavior_drift_from_classification(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    result = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=sandbox,
        failure_classification={
            "category_counts": {"SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1},
            "failures": [
                {
                    "test_class": "com.example.CustomExceptionTranslatorTest",
                    "test_method": "missingToken",
                    "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                    "symptom": "Request processing failed",
                    "suggested_next_action": "Review controller advice / exception handler behavior under Spring Framework 6.",
                }
            ],
        },
        orchestration_summary={"run_id": "run-001"},
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT" in payload["detected_failure_categories"]
    assert "controller_advice_behavior" in payload["suspected_contract_areas"]


def test_api_contract_review_detects_jakarta_validation_handler_mismatch(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    result = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=sandbox,
        failure_classification={
            "category_counts": {"JAKARTA_VALIDATION_HANDLER_MISMATCH": 1},
            "failures": [
                {
                    "test_class": "com.example.CustomExceptionTranslatorTest",
                    "test_method": "constraintViolations",
                    "category": "JAKARTA_VALIDATION_HANDLER_MISMATCH",
                    "symptom": "jakarta.validation.ConstraintViolationException",
                    "suggested_next_action": "Review jakarta.validation runtime behavior against legacy handler contract.",
                }
            ],
        },
        orchestration_summary={"run_id": "run-001"},
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert "JAKARTA_VALIDATION_HANDLER_MISMATCH" in payload["detected_failure_categories"]
    assert "validation_exception_mapping" in payload["suspected_contract_areas"]


def test_api_contract_review_detects_http_status_drift_from_surefire_report(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "TEST-com.example.CustomExceptionTranslatorTest.xml").write_text(
        """
<testsuite name="com.example.CustomExceptionTranslatorTest">
  <testcase classname="com.example.CustomExceptionTranslatorTest" name="requestMethodNotSupported">
    <failure type="org.junit.ComparisonFailure" message="expected:&lt;404&gt; but was:&lt;405&gt;">expected:&lt;404&gt; but was:&lt;405&gt;</failure>
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    result = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=sandbox,
        orchestration_summary={"run_id": "run-001"},
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["detected"] is True
    assert "HTTP_STATUS_CONTRACT_DRIFT" in payload["detected_failure_categories"]
    assert payload["affected_tests"][0]["symptom"] == "expected:<404> but was:<405>"


def test_api_contract_review_no_api_failures_returns_detected_false(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    result = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=sandbox,
        failure_classification={
            "category_counts": {"MOCKITO_FINAL_CLASS_MOCKING_LIMITATION": 1},
            "failures": [],
        },
        orchestration_summary={"run_id": "run-001"},
    )

    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["detected"] is False
    assert payload["human_review_required"] is False
    assert payload["detected_failure_categories"] == []


def test_finalize_failed_sandbox_propagates_api_contract_review_artifact_and_warning(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)
    sandbox = Path(state["sandbox_path"])
    _write_controller_advice(sandbox)
    _write_test_hint_file(sandbox)
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "TEST-com.example.CustomExceptionTranslatorTest.xml").write_text(
        """
<testsuite name="com.example.CustomExceptionTranslatorTest">
  <testcase classname="com.example.CustomExceptionTranslatorTest" name="requestMethodNotSupported">
    <failure type="org.junit.ComparisonFailure" message="expected:&lt;404&gt; but was:&lt;405&gt;">expected:&lt;404&gt; but was:&lt;405&gt;</failure>
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    payload = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))

    assert "api_contract_review" in result["artifact_refs"]
    assert summary["artifact_refs"]["api_contract_review"].endswith("review\\api_contract_review.json") or summary["artifact_refs"]["api_contract_review"].endswith("review/api_contract_review.json")
    assert any("API contract drift detected" in warning for warning in result["warnings"])
    assert payload["artifact_refs"]["api_contract_review"].endswith("api_contract_review.json")


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = run_dir / "workspaces" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return run_dir, sandbox


def _write_controller_advice(sandbox: Path) -> None:
    path = sandbox / "src" / "main" / "java" / "com" / "example" / "CustomExceptionTranslator.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;
import org.zalando.problem.spring.web.advice.AdviceTrait;

@ControllerAdvice
class CustomExceptionTranslator extends ResponseEntityExceptionHandler implements AdviceTrait {}
""".strip(),
        encoding="utf-8",
    )


def _write_test_hint_file(sandbox: Path) -> None:
    path = sandbox / "src" / "test" / "java" / "com" / "example" / "CustomExceptionTranslatorTest.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
class CustomExceptionTranslatorTest {
  void requestMethodNotSupported() {
    mvc.perform(get("/demo"))
      .andExpect(status().isNotFound())
      .andExpect(jsonPath("$.status").value(404))
      .andExpect(content().string("problem"));
  }
}
""".strip(),
        encoding="utf-8",
    )


def _failed_state(tmp_path: Path) -> dict:
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
    sandbox = run_dir / "workspaces" / "sandbox"
    analysis_dir = Path(state["analysis_dir"])
    planning_dir = Path(state["planning_dir"])
    assessment_dir = Path(state["assessment_dir"])
    approval_dir = run_dir / "approval"
    transform_dir = run_dir / "transformation"
    test_dir = run_dir / "test" / "post_transform"
    logs_dir = run_dir / "logs"
    build_dir = run_dir / "build"
    for directory in (
        sandbox,
        analysis_dir,
        planning_dir,
        assessment_dir,
        approval_dir,
        transform_dir,
        test_dir,
        logs_dir,
        build_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\nrequires_human_approval: true\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"source_stack": {}, "target_stack": {}}) + "\n",
        encoding="utf-8",
    )
    (approval_dir / "approval_decision.json").write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    (approval_dir / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (transform_dir / "transformation_execution_plan.yaml").write_text("recipes: []\n", encoding="utf-8")
    (sandbox / ".migration").mkdir(parents=True, exist_ok=True)
    (sandbox / ".migration" / "ledger.json").write_text("{}\n", encoding="utf-8")
    (logs_dir / "phase2_transform.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_agent.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_summary.md").write_text("# failed\n", encoding="utf-8")
    (test_dir / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "severity": "ERROR",
                "message": "Surefire reported post-transform test failures.",
                "totals": {"tests": 1, "passed": 0, "failures": 1, "errors": 0, "skipped": 0},
                "test_log_path": str(test_dir / "test_agent.log"),
                "source_log_path": str(logs_dir / "phase2_transform.log"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    classification_path = build_dir / "post_transform_failure_classification.json"
    classification_path.write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "failure_count": 1,
                "category_counts": {"HTTP_STATUS_CONTRACT_DRIFT": 1},
                "failures": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "requestMethodNotSupported",
                        "category": "HTTP_STATUS_CONTRACT_DRIFT",
                        "symptom": "expected:<404> but was:<405>",
                        "suggested_next_action": "Review expected HTTP status codes and exception-to-response mappings under Spring Boot 3.",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_error = build_dir / "build-error-20260603-120000-test_failure.json"
    build_error.write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "failure_classification_path": str(classification_path),
                "failure_categories": {"HTTP_STATUS_CONTRACT_DRIFT": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "orchestration_status": "FAIL",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "final_status": "TEST_FAILED_IN_SANDBOX",
            "stop_reason": "Sandbox migration failed after tests.",
            "current_unit": "spring-boot-3-5-14",
            "sandbox_path": str(sandbox),
            "warnings": [],
            "errors": ["post-transform test failures"],
            "blockers": ["post-transform test failures"],
            "artifact_refs": {
                "analysis_report": str(analysis_dir / "analysis_report.json"),
                "migration_plan": str(planning_dir / "migration_plan.yaml"),
                "assessment_report": str(assessment_dir / "assessment_report.json"),
                "approval_decision": str(approval_dir / "approval_decision.json"),
                "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
                "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
                "migration_ledger": str(sandbox / ".migration" / "ledger.json"),
                "phase2_log": str(logs_dir / "phase2_transform.log"),
                "post_transform_test_report": str(test_dir / "test_report.json"),
                "post_transform_test_summary": str(test_dir / "test_summary.md"),
                "post_transform_test_log": str(test_dir / "test_agent.log"),
                "build_error_contract": str(build_error),
            },
        }
    )
    return state
