from __future__ import annotations

from typing import Any

from migration_factory.control_tower.application.v2_repair_family_registry import repair_family_policy
from migration_factory.control_tower.application.v2_repair_subfamily_classifier import (
    classify_repair_subfamily,
)


def _evidence(text: str) -> dict[str, Any]:
    return {
        "job_id": "job-r10",
        "stage_index": 2,
        "usable_artifacts": [
            {"kind": "test_source", "ref": "src/test/java/ExampleTest.java", "excerpt": text},
            {"kind": "test_report", "ref": "TEST.xml", "excerpt": "failed"},
            {"kind": "pom_xml", "ref": "pom.xml", "excerpt": "org.powermock"},
            {"kind": "build_error_contract", "ref": "build.json", "excerpt": text},
            {"kind": "sandbox", "ref": "sandbox"},
        ],
    }


def _assessment(family: str, text: str, classification: dict[str, Any] | None = None) -> dict[str, Any]:
    return classify_repair_subfamily(
        family_policy=repair_family_policy(family),
        repair_strategy_packet={"job_id": "job-r10", "stage_index": 2, "family": family},
        stage_evidence=_evidence(text),
        classification=classification or {"failure_type": family},
        migration_memory={},
    )


def test_classifier_detects_initmocks() -> None:
    assessment = _assessment("INITMOCKS_TO_OPENMOCKS_CANDIDATE", "MockitoAnnotations.initMocks(this);")
    assert assessment["subfamily"] == "INITMOCKS_DIRECT_REPLACEMENT"
    assert assessment["promotion_status"] == "safe_recipe_candidate"
    assert assessment["apply_candidate_allowed"] is True


def test_classifier_detects_mockbean() -> None:
    assessment = _assessment("MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE", "@MockBean Service service;")
    assert assessment["subfamily"] == "MOCKBEAN_DIRECT_REPLACEMENT"
    assert assessment["apply_candidate_allowed"] is False


def test_classifier_detects_powermock_static_simple_without_global_apply() -> None:
    assessment = _assessment("POWERMOCK_LEGACY_TEST_STRATEGY", "PowerMockito.mockStatic(Foo.class);")
    assert assessment["subfamily"] == "POWERMOCK_STATIC_MOCK_SIMPLE"
    assert assessment["promotion_status"] == "medium_risk_recipe_candidate"
    assert assessment["backend_recipe_available"] is False
    assert assessment["apply_candidate_allowed"] is False


def test_classifier_detects_whennew_as_constructor_mocking() -> None:
    assessment = _assessment("POWERMOCK_LEGACY_TEST_STRATEGY", "PowerMockito.whenNew(Foo.class).thenReturn(foo);")
    assert assessment["subfamily"] == "POWERMOCK_CONSTRUCTOR_MOCKING"
    assert assessment["promotion_status"] == "human_refactor_required"
    assert "constructor mocking" in assessment["forbidden_patterns_matched"]


def test_classifier_detects_private_or_final_mocking() -> None:
    assessment = _assessment("POWERMOCK_LEGACY_TEST_STRATEGY", "Whitebox.invokeMethod(target, \"privateMethod\"); final class Foo {}")
    assert assessment["subfamily"] == "POWERMOCK_PRIVATE_OR_FINAL_MOCKING"
    assert assessment["promotion_status"] == "human_refactor_required"
    assert assessment["apply_candidate_allowed"] is False


def test_classifier_unknown_is_unsupported_and_browser_cannot_override_flags() -> None:
    assessment = _assessment(
        "UNKNOWN_FAILURE",
        "mystery failure",
        {
            "failure_type": "UNKNOWN_FAILURE",
            "repair_subfamily_assessment": {
                "subfamily": "INITMOCKS_DIRECT_REPLACEMENT",
                "risk_level": "low",
                "apply_candidate_allowed": True,
            },
        },
    )
    assert assessment["subfamily"] == "UNKNOWN_SUBFAMILY"
    assert assessment["promotion_status"] == "unsupported"
    assert assessment["apply_candidate_allowed"] is False
    assert assessment["backend_gate"]["llm_can_apply"] is False
