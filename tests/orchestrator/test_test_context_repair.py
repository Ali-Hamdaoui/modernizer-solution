from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.test_context_repair import generate_test_context_repair_proposal


def test_generates_repair_proposal_from_missing_bean_and_mock_provider(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_behavioral_context(run_dir)
    _write_equivalence_report(run_dir)
    _write_test_file(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_test_file(
        sandbox / "src/test/java/com/example/App.java",
        """
package com.example;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@SpringBootConfiguration
class App {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_test_context_repair_proposal(
        run_dir=run_dir,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        sandbox_project_path=sandbox,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["provider_exists_but_not_loaded"] is True
    assert proposal["migrated_reference_shows_equivalent_test_setup"] is True
    assert any(item["strategy_id"] == "ensure_mockito_bean_in_loaded_test_context" for item in proposal["proposal_strategies"])
    assert payload["safe_to_auto_apply"] is False
    assert payload["human_review_required"] is True


def test_detects_context_configuration_and_import_strategies(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_behavioral_context(run_dir)
    _write_equivalence_report(run_dir, provider_type="TEST_CONFIGURATION")
    _write_test_file(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.test.context.ContextConfiguration;
@ContextConfiguration(classes = {App.class})
class CustomExceptionTranslatorTest {}
""",
    )
    _write_test_file(
        sandbox / "src/test/java/com/example/App.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Import;
@TestConfiguration
@Import(FunctionalMessageHelper.class)
class App {}
""",
    )

    result = generate_test_context_repair_proposal(
        run_dir=run_dir,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        sandbox_project_path=sandbox,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    strategy_ids = [row["strategy_id"] for row in payload["proposals"][0]["proposal_strategies"]]
    assert "adjust_context_configuration_classes" in strategy_ids
    assert "add_import_for_test_support_configuration" in strategy_ids


def test_ambiguous_case_produces_no_patch(tmp_path: Path) -> None:
    run_dir, sandbox = _workspace(tmp_path)
    _write_behavioral_context(run_dir)
    _write_equivalence_report(run_dir, reference_support=False)
    _write_test_file(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
class CustomExceptionTranslatorTest {}
""",
    )

    result = generate_test_context_repair_proposal(
        run_dir=run_dir,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        sandbox_project_path=sandbox,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["patch_proposal_path"] == ""
    assert result.patch_path is None
    assert payload["proposals"][0]["unsafe_to_auto_apply"] is True


def test_finalize_failed_sandbox_adds_test_context_repair_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["test_context_repair_proposal"].endswith("test_context_repair_proposal.json")
    assert summary["artifact_refs"]["test_context_repair_proposal"].endswith("test_context_repair_proposal.json")
    assert final_report["artifact_refs"]["test_context_repair_proposal"].endswith("test_context_repair_proposal.json")
    assert "Test Context Repair Proposal:" in final_summary


def test_test_context_repair_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/test_context_repair.py").read_text(encoding="utf-8").lower()

    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _workspace(tmp_path: Path) -> tuple[Path, Path]:
    run_dir = tmp_path / "run"
    sandbox = run_dir / "workspaces" / "sandbox"
    sandbox.mkdir(parents=True, exist_ok=True)
    return run_dir, sandbox


def _write_test_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip(), encoding="utf-8")


def _write_behavioral_context(run_dir: Path) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    (remediation / "behavioral_failure_context_pack.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "failing_tests": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "UNKNOWN_TEST_FAILURE",
                        "symptom": "Failed to load ApplicationContext",
                    }
                ],
                "affected_test_files": [
                    {
                        "class_name": "CustomExceptionTranslatorTest",
                        "file": str(run_dir / "workspaces" / "sandbox" / "src/test/java/com/example/CustomExceptionTranslatorTest.java"),
                        "matched_markers": ["SPRING_BOOT_TEST"],
                    }
                ],
                "missing_bean_type_errors": [{"bean_type": "com.example.FunctionalMessageHelper"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_equivalence_report(run_dir: Path, *, provider_type: str = "MOCKBEAN", reference_support: bool = True) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    reference_occurrences = []
    if reference_support:
        reference_occurrences.append(
            {
                "class_name": "App",
                "file": "src/test/java/com/example/App.java",
                "scope": "test",
                "occurrence_role": "provider",
                "matched_markers": ["MOCKITOBEAN"] if provider_type == "MOCKBEAN" else ["IMPORT", "TEST_CONFIGURATION"],
            }
        )
    (remediation / "legacy_behavior_equivalence_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "beans": [
                    {
                        "missing_bean_type": "com.example.FunctionalMessageHelper",
                        "legacy_occurrences": [
                            {
                                "class_name": "App",
                                "file": "src/test/java/com/example/App.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": [provider_type],
                            }
                        ],
                        "sandbox_occurrences": [
                            {
                                "class_name": "App",
                                "file": "src/test/java/com/example/App.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": ["MOCKITOBEAN"] if provider_type == "MOCKBEAN" else ["IMPORT", "TEST_CONFIGURATION"],
                            }
                        ],
                        "migrated_reference_occurrences": reference_occurrences,
                        "provider_status": "not_loaded",
                        "likely_legacy_provider_type": provider_type,
                        "reference_resolution_classification": "test_context_candidate" if reference_support else "",
                        "llm_candidate": True,
                    }
                ],
            }
        )
        + "\n",
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
    _write_test_file(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_test_file(
        sandbox / "src/test/java/com/example/App.java",
        """
package com.example;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@SpringBootConfiguration
class App {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )
    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\nrequires_human_approval: true\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(json.dumps({"source_stack": {}, "target_stack": {}}) + "\n", encoding="utf-8")
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
                "totals": {"tests": 1, "passed": 0, "failures": 0, "errors": 1, "skipped": 0},
                "warnings": [],
                "test_log_path": str(test_dir / "test_agent.log"),
                "source_log_path": str(logs_dir / "phase2_transform.log"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "TEST-com.example.CustomExceptionTranslatorTest.xml").write_text(
        """
<testsuite name="com.example.CustomExceptionTranslatorTest">
  <testcase classname="com.example.CustomExceptionTranslatorTest" name="missingBean">
    <error type="java.lang.IllegalStateException" message="Failed to load ApplicationContext">Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException: No qualifying bean of type 'com.example.FunctionalMessageHelper' available</error>
  </testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )
    build_error_path = build_dir / "build-error-20260604-000000-missing_config.json"
    build_error_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "project_path": str(sandbox),
                "status": "failed",
                "result_kind": "missing_config",
                "message": "Failed to load ApplicationContext",
                "matched_line": (
                    "Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException: "
                    "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"
                ),
                "unit_id": "spring-boot-3-5-14",
                "failure_categories": {"UNKNOWN_TEST_FAILURE": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_behavioral_context(run_dir)
    _write_equivalence_report(run_dir)
    state["artifact_refs"] = {
        "analysis_report": str(analysis_dir / "analysis_report.json"),
        "approval_decision": str(approval_dir / "approval_decision.json"),
        "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
        "assessment_report": str(assessment_dir / "assessment_report.json"),
        "migration_plan": str(planning_dir / "migration_plan.yaml"),
        "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
        "migration_ledger": str(sandbox / ".migration" / "ledger.json"),
        "phase2_log": str(logs_dir / "phase2_transform.log"),
        "post_transform_test_report": str(test_dir / "test_report.json"),
        "post_transform_test_summary": str(test_dir / "test_summary.md"),
        "post_transform_test_log": str(test_dir / "test_agent.log"),
        "build_error_contract": str(build_error_path),
        "behavioral_failure_context_pack": str(run_dir / "remediation" / "behavioral_failure_context_pack.json"),
        "legacy_behavior_equivalence_report": str(run_dir / "remediation" / "legacy_behavior_equivalence_report.json"),
    }
    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "orchestration_status": "FAIL",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "sandbox_path": str(sandbox),
            "current_unit": "spring-boot-3-5-14",
        }
    )
    return state
