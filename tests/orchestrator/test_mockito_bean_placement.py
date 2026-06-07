from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.mockito_bean_placement import (
    generate_mockito_bean_placement_report,
)


def test_detects_legacy_mockbean_and_sandbox_mockitobean(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, package_name="com.example.web")
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(run_dir, sandbox, support_class="TestSupportConfig", package_name="com.example.web")
    _write_guided(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_java(
        sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/TestSupportConfig.java",
        """
package com.example.web;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        legacy_guided_patch_proposal_path=run_dir / "remediation" / "legacy_guided_patch_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["legacy_mock_locations"][0]["matched_markers"] == ["MOCKBEAN"]
    assert proposal["sandbox_mock_locations"][0]["matched_markers"] == ["MOCKITOBEAN"]
    assert proposal["placement_classification"] == "MOCK_IN_SUPPORT_CLASS_ONLY"


def test_classifies_mockitobean_in_failing_test_class(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, package_name="com.example.web")
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(run_dir, sandbox, support_class="TestSupportConfig", package_name="com.example.web")
    _write_guided(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_java(
        sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        legacy_guided_patch_proposal_path=run_dir / "remediation" / "legacy_guided_patch_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["proposals"][0]["placement_classification"] == "MOCK_IN_FAILING_TEST_CLASS"


def test_classifies_mockitobean_in_superclass_and_generates_patch(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(
        run_dir,
        sandbox,
        package_name="com.example.web",
        extra_failures=[
            {
                "test_class": "com.example.web.AnotherExceptionTranslatorTest",
                "test_method": "missingBean2",
                "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.AnotherExceptionTranslatorTest, classes = [com.example.web.App]]",
                "file": str(sandbox / "src/test/java/com/example/web/AnotherExceptionTranslatorTest.java"),
            }
        ],
    )
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(
        run_dir,
        sandbox,
        support_class="TestSupportConfig",
        package_name="com.example.web",
        extra_tests=[
            {
                "test_class": "com.example.web.AnotherExceptionTranslatorTest",
                "test_method": "missingBean2",
                "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                "file": str(sandbox / "src/test/java/com/example/web/AnotherExceptionTranslatorTest.java"),
                "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.AnotherExceptionTranslatorTest, classes = [com.example.web.App]]",
            }
        ],
    )
    _write_guided(
        run_dir,
        support_class="TestSupportConfig",
        package_name="com.example.web",
        extra_tests=[
            {
                "test_class": "com.example.web.AnotherExceptionTranslatorTest",
                "test_method": "missingBean2",
                "file": str(sandbox / "src/test/java/com/example/web/AnotherExceptionTranslatorTest.java"),
                "symptom": "Failed to load ApplicationContext",
            }
        ],
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/AbstractTranslatorTest.java",
        """
package com.example.web;
abstract class AbstractTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
import com.example.web.CustomExceptionTranslator;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest extends AbstractTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/AnotherExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
import com.example.web.CustomExceptionTranslator;
@SpringBootTest(classes = App.class)
class AnotherExceptionTranslatorTest extends AbstractTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/TestSupportConfig.java",
        """
package com.example.web;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        legacy_guided_patch_proposal_path=run_dir / "remediation" / "legacy_guided_patch_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["placement_classification"] == "MOCK_IN_SUPPORT_CLASS_ONLY"
    assert proposal["patch_proposal_available"] is True
    assert proposal["patch_strategy"] == "duplicate_mockito_bean_into_shared_abstract_superclass"
    assert result.patch_path is not None
    assert "@MockitoBean" in result.patch_path.read_text(encoding="utf-8")


def test_generates_patch_for_single_failing_test_class(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, reference = _workspace(tmp_path)
    _write_behavioral_context(run_dir, sandbox, package_name="com.example.web")
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(run_dir, sandbox, support_class="TestSupportConfig", package_name="com.example.web")
    _write_guided(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    original = """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
"""
    target = sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java"
    _write_java(target, original)
    _write_java(
        sandbox / "src/test/java/com/example/web/TestSupportConfig.java",
        """
package com.example.web;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )
    _write_java(
        reference / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        legacy_guided_patch_proposal_path=run_dir / "remediation" / "legacy_guided_patch_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
        migrated_reference_path=reference,
    )
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is True
    assert proposal["patch_strategy"] == "duplicate_mockito_bean_into_failing_test_class"
    assert proposal["reference_evidence"]["classification"] == "supports_patch"
    assert result.patch_path is not None
    assert target.read_text(encoding="utf-8").strip() == original.strip()


def test_ambiguous_multiple_test_case_produces_no_patch_and_llm_candidate(tmp_path: Path) -> None:
    run_dir, legacy, sandbox, _ = _workspace(tmp_path)
    _write_behavioral_context(
        run_dir,
        sandbox,
        package_name="com.example.web",
        extra_failures=[
            {
                "test_class": "com.example.web.OtherTranslatorTest",
                "test_method": "missingBean2",
                "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.OtherTranslatorTest, classes = [com.example.web.App]]",
                "file": str(sandbox / "src/test/java/com/example/web/OtherTranslatorTest.java"),
            }
        ],
    )
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(
        run_dir,
        sandbox,
        support_class="TestSupportConfig",
        package_name="com.example.web",
            extra_tests=[
                {
                    "test_class": "com.example.web.OtherTranslatorTest",
                    "test_method": "missingBean2",
                    "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                    "file": str(sandbox / "src/test/java/com/example/web/OtherTranslatorTest.java"),
                    "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.OtherTranslatorTest, classes = [com.example.web.App]]",
                }
            ],
        )
    _write_guided(
        run_dir,
        support_class="TestSupportConfig",
        package_name="com.example.web",
            extra_tests=[
                {
                    "test_class": "com.example.web.OtherTranslatorTest",
                    "test_method": "missingBean2",
                    "file": str(sandbox / "src/test/java/com/example/web/OtherTranslatorTest.java"),
                    "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.OtherTranslatorTest, classes = [com.example.web.App]]",
                }
            ],
        )
    _write_java(
        sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import com.example.web.CustomExceptionTranslator;
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/OtherTranslatorTest.java",
        """
package com.example.web;
import com.example.web.CustomExceptionTranslator;
class OtherTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/TestSupportConfig.java",
        """
package com.example.web;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
@TestConfiguration
class TestSupportConfig {
  @MockitoBean FunctionalMessageHelper helper;
}
""",
    )

    result = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox,
        legacy_project_path=legacy,
        legacy_behavior_equivalence_report_path=run_dir / "remediation" / "legacy_behavior_equivalence_report.json",
        test_context_repair_proposal_path=run_dir / "remediation" / "test_context_repair_proposal.json",
        legacy_guided_patch_proposal_path=run_dir / "remediation" / "legacy_guided_patch_proposal.json",
        behavioral_failure_context_pack_path=run_dir / "remediation" / "behavioral_failure_context_pack.json",
    )
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    proposal = payload["proposals"][0]
    assert proposal["patch_proposal_available"] is False
    assert proposal["llm_candidate"] is True
    assert proposal["placement_classification"] == "MOCK_PLACEMENT_AMBIGUOUS"


def test_finalize_failed_sandbox_adds_mockito_placement_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["mockito_bean_placement_report"].endswith("mockito_bean_placement_report.json")
    assert summary["artifact_refs"]["mockito_bean_placement_report"].endswith("mockito_bean_placement_report.json")
    assert final_report["artifact_refs"]["mockito_bean_placement_report"].endswith("mockito_bean_placement_report.json")
    assert "MockitoBean Placement Report:" in final_summary


def test_mockito_bean_placement_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/mockito_bean_placement.py").read_text(encoding="utf-8").lower()

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


def _write_behavioral_context(
    run_dir: Path,
    sandbox: Path,
    *,
    package_name: str,
    extra_failures: list[dict[str, str]] | None = None,
) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    failures = [
        {
            "test_class": f"{package_name}.CustomExceptionTranslatorTest",
            "test_method": "missingBean",
            "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
            "symptom": f"Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = {package_name}.CustomExceptionTranslatorTest, classes = [{package_name}.App]]",
            "file": str(sandbox / ("src/test/java/" + package_name.replace(".", "/") + "/CustomExceptionTranslatorTest.java")),
        }
    ]
    failures.extend(extra_failures or [])
    affected = [
        {
            "class_name": "CustomExceptionTranslatorTest",
            "file": failures[0]["file"],
            "matched_markers": ["SPRING_BOOT_TEST"],
        }
    ]
    for item in extra_failures or []:
        affected.append(
            {
                "class_name": str(item["test_class"]).rsplit(".", 1)[-1],
                "file": item["file"],
                "matched_markers": ["SPRING_BOOT_TEST"],
            }
        )
    (remediation / "behavioral_failure_context_pack.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "failing_tests": [
                    {k: v for k, v in item.items() if k != "file"}
                    for item in failures
                ],
                "affected_test_files": affected,
                "missing_bean_type_errors": [{"bean_type": f"{package_name}.FunctionalMessageHelper"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_equivalence(run_dir: Path, *, support_class: str, package_name: str) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    (remediation / "legacy_behavior_equivalence_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "beans": [
                    {
                        "missing_bean_type": f"{package_name}.FunctionalMessageHelper",
                        "legacy_occurrences": [
                            {
                                "class_name": support_class,
                                "file": f"src/test/java/{package_name.replace('.', '/')}/{support_class}.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": ["MOCKBEAN"],
                            }
                        ],
                        "sandbox_occurrences": [
                            {
                                "class_name": support_class,
                                "file": f"src/test/java/{package_name.replace('.', '/')}/{support_class}.java",
                                "scope": "test",
                                "occurrence_role": "provider",
                                "matched_markers": ["MOCKITOBEAN"],
                            },
                            {
                                "class_name": "CustomExceptionTranslator",
                                "file": f"src/main/java/{package_name.replace('.', '/')}/CustomExceptionTranslator.java",
                                "scope": "main",
                                "occurrence_role": "consumer",
                                "matched_markers": ["FIELD_INJECTION"],
                            },
                        ],
                        "provider_status": "not_loaded",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_repair(
    run_dir: Path,
    sandbox: Path,
    *,
    support_class: str,
    package_name: str,
    extra_tests: list[dict[str, str]] | None = None,
) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    tests = [
        {
            "test_class": f"{package_name}.CustomExceptionTranslatorTest",
            "test_method": "missingBean",
            "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
            "file": str(sandbox / ("src/test/java/" + package_name.replace(".", "/") + "/CustomExceptionTranslatorTest.java")),
            "symptom": f"Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = {package_name}.CustomExceptionTranslatorTest, classes = [{package_name}.App]]",
        }
    ]
    tests.extend(extra_tests or [])
    payload = {
        "run_id": "run-001",
        "failed_unit": "spring-boot-3-5-14",
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "TEST_FAILED_IN_SANDBOX",
        "proposals": [
            {
                "missing_bean_type": f"{package_name}.FunctionalMessageHelper",
                "failing_tests": tests,
                "existing_mock_or_provider_classes": [
                    {
                        "class_name": support_class,
                        "file": f"src/test/java/{package_name.replace('.', '/')}/{support_class}.java",
                        "matched_markers": ["MOCKITOBEAN", "TEST_CONFIGURATION"],
                    }
                ],
                "provider_exists_but_not_loaded": True,
                "proposal_strategies": [{"strategy_id": "ensure_mockito_bean_in_loaded_test_context"}],
            }
        ],
    }
    (remediation / "test_context_repair_proposal.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _write_guided(
    run_dir: Path,
    *,
    support_class: str,
    package_name: str,
    extra_tests: list[dict[str, str]] | None = None,
) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    tests = [
        {
            "test_class": f"{package_name}.CustomExceptionTranslatorTest",
            "test_method": "missingBean",
            "file": f"C:/tmp/{support_class}.java",
            "symptom": f"Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = {package_name}.CustomExceptionTranslatorTest, classes = [{package_name}.App]]",
        }
    ]
    tests.extend(extra_tests or [])
    payload = {
        "run_id": "run-001",
        "failed_unit": "spring-boot-3-5-14",
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "TEST_FAILED_IN_SANDBOX",
        "proposals": [
            {
                "missing_bean_type": f"{package_name}.FunctionalMessageHelper",
                "failing_tests": tests,
                "test_support_classes": [
                    {
                        "class_name": support_class,
                        "file": f"src/test/java/{package_name.replace('.', '/')}/{support_class}.java",
                        "matched_markers": ["MOCKITOBEAN", "TEST_CONFIGURATION"],
                    }
                ],
                "provider_exists_but_not_loaded": True,
            }
        ],
    }
    (remediation / "legacy_guided_patch_proposal.json").write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _failed_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy-source"
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
    for directory in (sandbox, analysis_dir, planning_dir, assessment_dir, approval_dir, transform_dir, test_dir, logs_dir, build_dir):
        directory.mkdir(parents=True, exist_ok=True)
    _write_behavioral_context(run_dir, sandbox, package_name="com.example.web")
    _write_equivalence(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_repair(run_dir, sandbox, support_class="TestSupportConfig", package_name="com.example.web")
    _write_guided(run_dir, support_class="TestSupportConfig", package_name="com.example.web")
    _write_java(
        sandbox / "src/test/java/com/example/web/CustomExceptionTranslatorTest.java",
        """
package com.example.web;
import org.springframework.boot.test.context.SpringBootTest;
@SpringBootTest(classes = App.class)
class CustomExceptionTranslatorTest {}
""",
    )
    _write_java(
        sandbox / "src/test/java/com/example/web/TestSupportConfig.java",
        """
package com.example.web;
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
                "message": "No qualifying bean of type 'com.example.web.FunctionalMessageHelper' available",
                "matched_line": "No qualifying bean of type 'com.example.web.FunctionalMessageHelper' available",
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
                        "test_class": "com.example.web.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                        "symptom": "Failed to load ApplicationContext for [WebMergedContextConfiguration testClass = com.example.web.CustomExceptionTranslatorTest, classes = [com.example.web.App]]",
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
