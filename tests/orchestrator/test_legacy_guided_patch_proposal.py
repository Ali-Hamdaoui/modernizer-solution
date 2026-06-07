from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.legacy_guided_patch_proposal import (
    generate_legacy_guided_patch_proposal,
)


def test_generate_patch_proposal_for_missing_spring_boot_support_class(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, reference = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="App")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=False)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=False)
    target_test = sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java"
    original = """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
"""
    _write_java(target_test, original)
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is True
    assert proposal["patch_strategy"] == "add_support_class_to_spring_boot_test_classes"
    assert result.patch_path is not None
    patch_text = result.patch_path.read_text(encoding="utf-8")
    assert "@SpringBootTest(classes = {App.class, TestSupportConfig.class})" in patch_text
    assert target_test.read_text(encoding="utf-8").strip() == original.strip()
    assert payload["safe_to_auto_apply"] is False
    assert payload["human_review_required"] is True
    assert reference.is_dir()


def test_generate_patch_proposal_for_context_configuration_missing_support_class(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="App")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=False)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=False)
    _write_java(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.test.context.ContextConfiguration;
@ContextConfiguration(classes = {App.class})
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is True
    assert proposal["patch_strategy"] == "add_support_class_to_context_configuration_classes"
    assert result.patch_path is not None
    assert "@ContextConfiguration(classes = {App.class, TestSupportConfig.class})" in result.patch_path.read_text(
        encoding="utf-8"
    )


def test_generate_patch_proposal_for_missing_import_support_class(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="App")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=False)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=False)
    _write_java(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.context.annotation.Import;
@Import(App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is True
    assert proposal["patch_strategy"] == "add_import_for_test_support_configuration"
    assert result.patch_path is not None
    assert "@Import({App.class, TestSupportConfig.class})" in result.patch_path.read_text(encoding="utf-8")


def test_legacy_and_sandbox_mode_works_without_reference(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="App")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=False)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=False)
    _write_java(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["proposal_mode"] == "legacy_sandbox_only"
    assert payload["patch_proposal_available"] is True


def test_optional_reference_can_strengthen_patch_and_broad_diff_blocks_it(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, reference = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="App")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=True)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=True)
    _write_java(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )
    _write_java(
        reference / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = {App.class, TestSupportConfig.class})
class CustomExceptionTranslatorTest {}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        migrated_reference_path=reference,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["proposals"][0]["reference_evidence"]["classification"] == "supports_patch"
    assert payload["patch_proposal_available"] is True

    broad_report = json.loads((run_dir / "remediation" / "legacy_behavior_equivalence_report.json").read_text(encoding="utf-8"))
    broad_rows = [
        {
            "class_name": f"Reference{i}",
            "file": f"src/test/java/com/example/Reference{i}.java",
            "scope": "test",
            "occurrence_role": "provider",
            "matched_markers": ["MOCKITOBEAN"],
        }
        for i in range(5)
    ]
    broad_report["beans"][0]["migrated_reference_occurrences"] = broad_rows
    (run_dir / "remediation" / "legacy_behavior_equivalence_report.json").write_text(
        json.dumps(broad_report) + "\n",
        encoding="utf-8",
    )

    broad_result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        migrated_reference_path=reference,
    )
    broad_payload = json.loads(broad_result.report_path.read_text(encoding="utf-8"))
    assert broad_payload["proposals"][0]["reference_evidence"]["classification"] == "broad_change_not_safe"
    assert broad_payload["patch_proposal_available"] is False


def test_ambiguous_case_produces_no_patch_and_llm_candidate(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, symptom_context="")
    _write_equivalence_report(run_dir, support_class="TestSupportConfig", include_reference=False)
    _write_repair_report(run_dir, sandbox, support_class="TestSupportConfig", include_reference=False)
    _write_java(
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is False
    assert proposal["llm_candidate"] is True
    assert payload["safe_to_auto_apply"] is False
    assert payload["human_review_required"] is True


def test_finalize_failed_sandbox_adds_legacy_guided_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["legacy_guided_patch_proposal"].endswith("legacy_guided_patch_proposal.json")
    assert summary["artifact_refs"]["legacy_guided_patch_proposal"].endswith("legacy_guided_patch_proposal.json")
    assert final_report["artifact_refs"]["legacy_guided_patch_proposal"].endswith("legacy_guided_patch_proposal.json")
    assert "Legacy Guided Patch Proposal:" in final_summary


def test_legacy_guided_patch_proposal_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/legacy_guided_patch_proposal.py").read_text(
        encoding="utf-8"
    ).lower()

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


def _write_behavioral_context(run_dir: Path, sandbox: Path, *, symptom_context: str) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    symptom = "Failed to load ApplicationContext"
    if symptom_context:
        symptom += f" for [WebMergedContextConfiguration testClass = com.example.CustomExceptionTranslatorTest, classes = [com.example.{symptom_context}]]"
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
                        "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                        "symptom": symptom,
                    }
                ],
                "affected_test_files": [
                    {
                        "class_name": "CustomExceptionTranslatorTest",
                        "file": str(sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java"),
                        "matched_markers": ["SPRING_BOOT_TEST"],
                    }
                ],
                "missing_bean_type_errors": [{"bean_type": "com.example.FunctionalMessageHelper"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_equivalence_report(run_dir: Path, *, support_class: str, include_reference: bool) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    reference_rows = []
    if include_reference:
        reference_rows.append(
            {
                "class_name": support_class,
                "file": f"src/test/java/com/example/{support_class}.java",
                "scope": "test",
                "occurrence_role": "provider",
                "matched_markers": ["TEST_CONFIGURATION", "MOCKITOBEAN"],
            }
        )
    (remediation / "legacy_behavior_equivalence_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "beans": [
                    {
                        "missing_bean_type": "com.example.FunctionalMessageHelper",
                        "legacy_occurrences": [
                            {
                                "class_name": support_class,
                                "file": f"src/test/java/com/example/{support_class}.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": ["MOCKBEAN", "TEST_CONFIGURATION"],
                            }
                        ],
                        "sandbox_occurrences": [
                            {
                                "class_name": support_class,
                                "file": f"src/test/java/com/example/{support_class}.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": ["MOCKITOBEAN", "TEST_CONFIGURATION"],
                            }
                        ],
                        "migrated_reference_occurrences": reference_rows,
                        "provider_status": "not_loaded",
                        "likely_legacy_provider_type": "MOCKBEAN",
                        "reference_resolution_classification": "test_context_candidate" if include_reference else "",
                        "llm_candidate": True,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_repair_report(run_dir: Path, sandbox: Path, *, support_class: str, include_reference: bool) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "run-001",
        "failed_unit": "spring-boot-3-5-14",
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "TEST_FAILED_IN_SANDBOX",
        "proposals": [
            {
                "missing_bean_type": "com.example.FunctionalMessageHelper",
                "failing_tests": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                        "file": str(sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java"),
                        "symptom": "Failed to load ApplicationContext",
                    }
                ],
                "existing_mock_or_provider_classes": [
                    {
                        "class_name": support_class,
                        "file": f"src/test/java/com/example/{support_class}.java",
                        "matched_markers": ["MOCKITOBEAN", "TEST_CONFIGURATION"],
                    }
                ],
                "provider_exists_but_not_loaded": True,
                "migrated_reference_shows_equivalent_test_setup": include_reference,
                "proposal_strategies": [
                    {"strategy_id": "ensure_mockito_bean_in_loaded_test_context"},
                    {"strategy_id": "add_import_for_test_support_configuration"},
                ],
            }
        ],
    }
    (remediation / "test_context_repair_proposal.json").write_text(
        json.dumps(payload) + "\n",
        encoding="utf-8",
    )


def _failed_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy-source"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    (ai_hub / "profiles").mkdir(parents=True, exist_ok=True)
    (ai_hub / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")
    _write_java(
        legacy / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.mock.mockito.MockBean;
class TestSupportConfig {
  @MockBean FunctionalMessageHelper helper;
}
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
        sandbox / "src/test/java/com/example/CustomExceptionTranslatorTest.java",
        """
package com.example;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/TestSupportConfig.java",
        """
package com.example;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
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
    (build_dir / "build-error-001-missing_config.json").write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "message": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available",
                "matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available",
                "error_type": "missing_config",
                "test_report_path": str(test_dir / "test_report.json"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (build_dir / "post_transform_failure_classification.json").write_text(
        json.dumps(
            {
                "failure_category_counts": {"SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1},
                "top_failed_tests": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                        "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.CustomExceptionTranslatorTest, classes = [com.example.App]]",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state["analysis_status"] = "PASS"
    state["planning_status"] = "PASS"
    state["assessment_status"] = "PASS"
    state["approval_status"] = "COMPLETED"
    state["approval_decision"] = "approved"
    state["transform_status"] = "BUILD_FAILED_IN_SANDBOX"
    state["build_status"] = "BUILD_FAILED_IN_SANDBOX"
    state["test_status"] = "TEST_FAILED_IN_SANDBOX"
    state["orchestration_status"] = "FAIL"
    state["final_status"] = "BUILD_FAILED_IN_SANDBOX"
    state["sandbox_path"] = str(sandbox)
    state["artifact_refs"] = {
        "approval_decision": str(approval_dir / "approval_decision.json"),
        "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
        "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
        "migration_ledger": str(sandbox / ".migration" / "ledger.json"),
        "analysis_report": str(analysis_dir / "analysis_report.json"),
        "assessment_report": str(assessment_dir / "assessment_report.json"),
        "post_transform_test_report": str(test_dir / "test_report.json"),
        "build_error_contract": str(build_dir / "build-error-001-missing_config.json"),
        "post_transform_failure_classification": str(build_dir / "post_transform_failure_classification.json"),
    }
    return state
