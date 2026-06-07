from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.behavioral_context import generate_behavioral_failure_context_pack
from migration_factory.remediation.policy import LlmPolicy


def test_behavioral_context_pack_detects_missing_bean_error(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_source_hints(sandbox)
    _write_test_hints(sandbox)
    build_error = {
        "message": "Application configuration is missing or invalid",
        "matched_line": (
            "Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException: "
            "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"
        ),
    }
    classification = {
        "category_counts": {"UNKNOWN_TEST_FAILURE": 1},
        "failures": [
            {
                "test_class": "com.example.CustomExceptionTranslatorTest",
                "test_method": "missingBean",
                "category": "UNKNOWN_TEST_FAILURE",
                "symptom": "Failed to load ApplicationContext",
            }
        ],
    }

    result = generate_behavioral_failure_context_pack(
        run_dir=run_dir,
        failed_unit="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
        build_error_contract=build_error,
        failure_classification=classification,
        llm_policy=LlmPolicy(),
        orchestration_summary={"run_id": "run-001", "final_status": "BUILD_FAILED_IN_SANDBOX"},
    )

    payload = json.loads(result.context_pack_path.read_text(encoding="utf-8"))
    gate = json.loads(result.llm_gate_path.read_text(encoding="utf-8"))
    assert payload["human_review_required"] is True
    assert payload["safe_to_auto_apply"] is False
    assert payload["llm_candidate"] is True
    assert payload["missing_bean_type_errors"][0]["bean_type"] == "com.example.FunctionalMessageHelper"
    assert "ApplicationContext" in payload["suspected_framework_areas"]
    assert gate["decision"] == "LLM_DISABLED_CONTEXT_ONLY"


def test_behavioral_context_pack_detects_surefire_application_context_failure(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_source_hints(sandbox)
    _write_test_hints(sandbox)
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "TEST-com.example.CustomExceptionTranslatorTest.xml").write_text(
        """
<testsuite name="com.example.CustomExceptionTranslatorTest">
  <testcase classname="com.example.CustomExceptionTranslatorTest" name="missingBean">
    <error type="java.lang.IllegalStateException" message="Failed to load ApplicationContext">Failed to load ApplicationContext</error>
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    result = generate_behavioral_failure_context_pack(
        run_dir=run_dir,
        failed_unit="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
        llm_policy=LlmPolicy(),
        orchestration_summary={"run_id": "run-001", "build_status": "BUILD_FAILED_IN_SANDBOX"},
    )

    payload = json.loads(result.context_pack_path.read_text(encoding="utf-8"))
    assert payload["failing_tests"][0]["test_method"] == "missingBean"
    assert payload["failure_categories"]["UNKNOWN_TEST_FAILURE"] == 1
    assert payload["affected_source_files"][0]["class_name"] == "CustomExceptionTranslator"
    assert payload["affected_test_files"][0]["class_name"] == "CustomExceptionTranslatorTest"


def test_behavioral_context_pack_includes_ledger_fixes(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    review_dir = sandbox / ".migration"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "ledger.json").write_text(
        json.dumps(
            {
                "transformations": [
                    {"type": "align_jjwt_version", "status": "updated", "unit": "spring-boot-3-5-14"},
                    {"type": "jjwt_api_compatibility_migration", "status": "applied", "unit": "spring-boot-3-5-14"},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = generate_behavioral_failure_context_pack(
        run_dir=run_dir,
        failed_unit="spring-boot-3-5-14",
        sandbox_project_path=sandbox,
        build_error_contract={"matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"},
        failure_classification={"category_counts": {"UNKNOWN_TEST_FAILURE": 1}},
        llm_policy=LlmPolicy(),
    )

    payload = json.loads(result.context_pack_path.read_text(encoding="utf-8"))
    assert payload["deterministic_fixes_already_applied"][0]["type"] == "align_jjwt_version"
    assert payload["deterministic_fixes_already_applied"][1]["type"] == "jjwt_api_compatibility_migration"


def test_finalize_failed_sandbox_adds_behavioral_context_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["behavioral_failure_context_pack"].endswith("behavioral_failure_context_pack.json")
    assert result["artifact_refs"]["llm_proposal_gate"].endswith("llm_proposal_gate.json")
    assert summary["artifact_refs"]["behavioral_failure_context_pack"].endswith("behavioral_failure_context_pack.json")
    assert final_report["artifact_refs"]["behavioral_failure_context_pack"].endswith("behavioral_failure_context_pack.json")
    assert "Behavioral Failure Context Pack:" in final_summary
    assert "LLM Proposal Gate:" in final_summary


def test_behavioral_context_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/behavioral_context.py").read_text(encoding="utf-8").lower()

    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = run_dir / "workspaces" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return run_dir, sandbox


def _write_source_hints(sandbox: Path) -> None:
    path = sandbox / "src" / "main" / "java" / "com" / "example" / "CustomExceptionTranslator.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

@ControllerAdvice
class CustomExceptionTranslator extends ResponseEntityExceptionHandler {
  @Autowired
  FunctionalMessageHelper helper;
}
""".strip(),
        encoding="utf-8",
    )


def _write_test_hints(sandbox: Path) -> None:
    path = sandbox / "src" / "test" / "java" / "com" / "example" / "CustomExceptionTranslatorTest.java"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class CustomExceptionTranslatorTest {
  void missingBean() {
    mvc.perform(get("/demo")).andExpect(status().isNotFound()).andExpect(jsonPath("$.status").value(404));
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
    (ai_hub / "profiles").mkdir(parents=True, exist_ok=True)
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
    _write_source_hints(sandbox)
    _write_test_hints(sandbox)
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "TEST-com.example.CustomExceptionTranslatorTest.xml").write_text(
        """
<testsuite name="com.example.CustomExceptionTranslatorTest">
  <testcase classname="com.example.CustomExceptionTranslatorTest" name="missingBean">
    <error type="java.lang.IllegalStateException" message="Failed to load ApplicationContext">Failed to load ApplicationContext</error>
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )
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
    (sandbox / ".migration" / "ledger.json").write_text(
        json.dumps({"transformations": [{"type": "align_jjwt_version", "status": "updated", "unit": "spring-boot-3-5-14"}]})
        + "\n",
        encoding="utf-8",
    )
    (logs_dir / "phase2_transform.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_agent.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_summary.md").write_text("# failed\n", encoding="utf-8")
    (test_dir / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "severity": "ERROR",
                "message": "Failed to load ApplicationContext",
                "totals": {"tests": 1, "passed": 0, "failures": 0, "errors": 1, "skipped": 0},
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
                "failure_count": 2,
                "category_counts": {
                    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1,
                    "UNKNOWN_TEST_FAILURE": 1,
                },
                "failures": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "UNKNOWN_TEST_FAILURE",
                        "symptom": "Failed to load ApplicationContext",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_error = build_dir / "build-error-20260603-120000-missing_config.json"
    build_error.write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "status": "failed",
                "result_kind": "missing_config",
                "message": "Application configuration is missing or invalid",
                "matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available",
                "failure_classification_path": str(classification_path),
                "failure_categories": {
                    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1,
                    "UNKNOWN_TEST_FAILURE": 1,
                },
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
            "transform_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "stop_reason": "Sandbox migration failed after tests.",
            "current_unit": "spring-boot-3-5-14",
            "sandbox_path": str(sandbox),
            "warnings": [],
            "errors": ["behavioral test failures"],
            "blockers": ["behavioral test failures"],
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
