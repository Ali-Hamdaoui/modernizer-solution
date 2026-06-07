from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.legacy_equivalence import generate_legacy_behavior_equivalence_report


def test_equivalence_detects_missing_bean_and_legacy_component_provider(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, reference = _workspace(tmp_path)
    _write_java(
        legacy / "src/main/java/com/example/FunctionalMessageHelper.java",
        """
package com.example;
import org.springframework.stereotype.Component;
@Component
class FunctionalMessageHelper {}
""",
    )
    _write_java(
        sandbox / "src/main/java/com/example/CustomExceptionTranslator.java",
        """
package com.example;
import org.springframework.beans.factory.annotation.Autowired;
class CustomExceptionTranslator {
  @Autowired
  FunctionalMessageHelper helper;
}
""",
    )
    result = generate_legacy_behavior_equivalence_report(
        run_dir=run_dir,
        legacy_project_path=legacy,
        sandbox_project_path=sandbox,
        build_error_contract={"matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"},
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    bean = payload["beans"][0]
    assert bean["missing_bean_type"] == "com.example.FunctionalMessageHelper"
    assert bean["likely_legacy_provider_type"] == "COMPONENT"
    assert bean["provider_status"] == "disappeared"
    assert payload["safe_to_auto_apply"] is False
    assert payload["human_review_required"] is True
    assert payload["llm_candidate"] is True
    assert result.summary_path.is_file()
    assert reference.is_dir()


def test_equivalence_detects_bean_and_test_configuration_providers(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_java(
        legacy / "src/main/java/com/example/WebConfig.java",
        """
package com.example;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
@Configuration
class WebConfig {
  @Bean
  FunctionalMessageHelper functionalMessageHelper() { return new FunctionalMessageHelper(); }
}
""",
    )
    _write_java(
        legacy / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.boot.test.mock.mockito.MockBean;
@TestConfiguration
class CustomExceptionTranslatorTest {
  @MockBean FunctionalMessageHelper helper;
  @Bean FunctionalMessageHelper localHelper() { return new FunctionalMessageHelper(); }
}
""",
    )
    _write_java(
        sandbox / "src/main/java/com/example/CustomExceptionTranslator.java",
        """
package com.example;
class CustomExceptionTranslator {
  FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_behavior_equivalence_report(
        run_dir=run_dir,
        legacy_project_path=legacy,
        sandbox_project_path=sandbox,
        build_error_contract={"matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"},
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    bean = payload["beans"][0]
    legacy_occurrences = bean["legacy_occurrences"]
    assert any("BEAN_METHOD" in row["matched_markers"] for row in legacy_occurrences)
    assert any("TEST_CONFIGURATION" in row["matched_markers"] for row in legacy_occurrences)
    assert any("MOCKBEAN" in row["matched_markers"] for row in legacy_occurrences)


def test_equivalence_uses_reference_to_classify_test_context_candidate(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, reference = _workspace(tmp_path)
    _write_java(
        legacy / "src/main/java/com/example/FunctionalMessageHelper.java",
        """
package com.example;
import org.springframework.stereotype.Component;
@Component
class FunctionalMessageHelper {}
""",
    )
    _write_java(
        sandbox / "src/main/java/com/example/CustomExceptionTranslator.java",
        """
package com.example;
import org.springframework.beans.factory.annotation.Autowired;
class CustomExceptionTranslator {
  @Autowired FunctionalMessageHelper helper;
}
""",
    )
    _write_java(
        reference / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
class CustomExceptionTranslatorTest {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_behavior_equivalence_report(
        run_dir=run_dir,
        legacy_project_path=legacy,
        sandbox_project_path=sandbox,
        migrated_reference_path=reference,
        build_error_contract={"matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"},
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    bean = payload["beans"][0]
    assert bean["reference_resolution_classification"] == "test_context_candidate"
    assert any("MOCKITOBEAN" in row["matched_markers"] for row in bean["migrated_reference_occurrences"])
    assert "test-context" in bean["recommended_equivalent_fix_strategy"]


def test_finalize_failed_sandbox_adds_legacy_equivalence_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["legacy_behavior_equivalence_report"].endswith("legacy_behavior_equivalence_report.json")
    assert summary["artifact_refs"]["legacy_behavior_equivalence_report"].endswith("legacy_behavior_equivalence_report.json")
    assert final_report["artifact_refs"]["legacy_behavior_equivalence_report"].endswith("legacy_behavior_equivalence_report.json")
    assert "Legacy Behavior Equivalence:" in final_summary


def test_standalone_equivalence_backfills_orchestration_and_final_refs(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    orchestration_dir = run_dir / "orchestration"
    final_dir = run_dir / "final"
    orchestration_dir.mkdir(parents=True, exist_ok=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    (orchestration_dir / "orchestration_summary.json").write_text(
        json.dumps({"artifact_refs": {}, "run_id": "run-001"}) + "\n",
        encoding="utf-8",
    )
    (final_dir / "migration_report.json").write_text(
        json.dumps({"artifact_refs": {}, "run_id": "run-001"}) + "\n",
        encoding="utf-8",
    )
    _write_java(
        legacy / "src/main/java/com/example/FunctionalMessageHelper.java",
        """
package com.example;
import org.springframework.stereotype.Component;
@Component
class FunctionalMessageHelper {}
""",
    )
    _write_java(
        sandbox / "src/main/java/com/example/CustomExceptionTranslator.java",
        """
package com.example;
import org.springframework.beans.factory.annotation.Autowired;
class CustomExceptionTranslator {
  @Autowired FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_behavior_equivalence_report(
        run_dir=run_dir,
        legacy_project_path=legacy,
        sandbox_project_path=sandbox,
        build_error_contract={"matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"},
    )

    orchestration = json.loads((orchestration_dir / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads((final_dir / "migration_report.json").read_text(encoding="utf-8"))
    assert orchestration["artifact_refs"]["legacy_behavior_equivalence_report"] == str(result.report_path)
    assert final_report["artifact_refs"]["legacy_behavior_equivalence_summary"] == str(result.summary_path)


def test_legacy_equivalence_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/legacy_equivalence.py").read_text(encoding="utf-8").lower()

    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _workspace(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    run_dir = tmp_path / "run"
    legacy = tmp_path / "legacy"
    sandbox = run_dir / "workspaces" / "sandbox"
    reference = tmp_path / "reference"
    for path in (run_dir, legacy, sandbox, reference):
        path.mkdir(parents=True, exist_ok=True)
    return run_dir, legacy, sandbox, reference


def _write_java(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip(), encoding="utf-8")


def _failed_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy-source"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    (ai_hub / "profiles").mkdir(parents=True, exist_ok=True)
    (ai_hub / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")
    _write_java(
        legacy / "src/main/java/com/example/FunctionalMessageHelper.java",
        """
package com.example;
import org.springframework.stereotype.Component;
@Component
class FunctionalMessageHelper {}
""",
    )
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
    _write_java(
        sandbox / "src/main/java/com/example/CustomExceptionTranslator.java",
        """
package com.example;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.ControllerAdvice;
@ControllerAdvice
class CustomExceptionTranslator {
  @Autowired
  FunctionalMessageHelper helper;
}
""",
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
    classification = build_dir / "post_transform_failure_classification.json"
    classification.write_text(
        json.dumps(
            {
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
        )
        + "\n",
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
                "failure_classification_path": str(classification),
                "failure_categories": {"UNKNOWN_TEST_FAILURE": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
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
