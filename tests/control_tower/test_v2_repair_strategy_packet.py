from __future__ import annotations

import json
from typing import Any

from migration_factory.control_tower.application.v2_repair_strategy_packet import (
    create_repair_strategy_packet,
)


class _FakeStrategyClient:
    def answer_with_role(self, *, role: Any, prompt: str, fallback: str, **_: Any) -> Any:
        role_value = getattr(role, "value", str(role))
        if role_value == "proposer":
            content = {
                "status": "available",
                "role": "repair_strategy_proposer",
                "family": "POWERMOCK_LEGACY_TEST_STRATEGY",
                "root_cause": "PowerMock static and constructor mocking block safe migration.",
                "affected_files": ["src/test/java/ExampleTest.java"],
                "detected_patterns": ["static mocking", "constructor mocking"],
                "migration_options": ["replace simple static mocking with Mockito inline"],
                "recommended_strategy": "Split simple static mocks from constructor mocks and refactor high-risk tests.",
                "risk_notes": ["Constructor mocking changes behavior risk."],
                "missing_evidence": [],
                "engineer_checklist": ["Review PrepareForTest scope."],
                "confidence": "high",
            }
        else:
            content = {
                "status": "available",
                "role": "repair_strategy_reviewer",
                "verdict": "advisory_accept",
                "critique": "Human gate remains required.",
                "risks": ["No auto-apply recipe."],
                "missing_evidence": [],
                "unsafe_assumptions": [],
                "recommended_next_action": "engineer_review_powermock_strategy",
                "confidence": "medium",
            }
        return type("FakeResult", (), {"content": json.dumps(content)})()


class _InvalidStrategyClient:
    def answer_with_role(self, **_: Any) -> Any:
        return type("FakeResult", (), {"content": "not json"})()


def _powermock_classification() -> dict[str, Any]:
    return {
        "stage_index": 2,
        "classification_status": "unsupported_known_failure",
        "failure_type": "POWERMOCK_LEGACY_TEST_STRATEGY",
        "repair_family_candidate": "",
        "confidence_reason": "PowerMock legacy test strategy signal found.",
        "matched_signals": ["review_gate:powermock_legacy_test_strategy"],
        "missing_required_evidence": [],
    }


def _powermock_evidence() -> dict[str, Any]:
    return {
        "job_id": "job-r9",
        "stage_index": 2,
        "usable_artifacts": [
            {
                "kind": "pom_xml",
                "ref": "pom.xml",
                "checksum": "sha256:pom",
                "excerpt": "org.powermock:powermock-api-mockito2",
            },
            {
                "kind": "test_source",
                "ref": "src/test/java/ExampleTest.java",
                "checksum": "sha256:test",
                "excerpt": "@RunWith(PowerMockRunner.class) @PrepareForTest(Foo.class) PowerMockito.mockStatic(Foo.class); PowerMockito.whenNew(Foo.class);",
            },
            {"kind": "build_error_contract", "ref": "build.json", "checksum": "sha256:build"},
            {"kind": "test_report", "ref": "TEST.xml", "checksum": "sha256:test-report"},
        ],
        "missing_artifacts": [],
    }


def test_strategy_packet_created_for_powermock_with_llm_outputs() -> None:
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=2,
        classification=_powermock_classification(),
        stage_evidence=_powermock_evidence(),
        migration_memory={},
        llm_client=_FakeStrategyClient(),
        llm_enabled=True,
    )
    assert packet["family"] == "POWERMOCK_LEGACY_TEST_STRATEGY"
    assert packet["risk_level"] == "high"
    assert packet["apply_candidate_allowed"] is False
    assert packet["backend_recipe_available"] is False
    assert packet["human_gate_required"] is True
    assert packet["llm_proposer"]["output"]["root_cause"].startswith("PowerMock")
    assert packet["llm_reviewer"]["output"]["verdict"] == "advisory_accept"
    assert "Review PrepareForTest scope." in packet["engineer_checklist"]
    assert packet["backend_gate"]["backend_authority"] is True
    assert packet["backend_gate"]["llm_can_apply"] is False


def test_powermock_strategy_fallback_invalid_output_remains_advisory() -> None:
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=2,
        classification=_powermock_classification(),
        stage_evidence=_powermock_evidence(),
        migration_memory={},
        llm_client=_InvalidStrategyClient(),
        llm_enabled=True,
    )
    assert packet["llm_proposer"]["fallback_used"] is True
    assert packet["llm_reviewer"]["fallback_used"] is True
    assert packet["llm_fallback"]["fallback_used"] is True
    assert packet["apply_candidate_allowed"] is False
    assert packet["backend_gate"]["llm_can_approve"] is False
    assert packet["backend_gate"]["downstream_start_allowed"] is False


def test_browser_like_input_cannot_influence_strategy_risk_or_apply_flags() -> None:
    classification = {
        **_powermock_classification(),
        "risk_level": "low",
        "apply_candidate_allowed": True,
        "backend_recipe_available": True,
    }
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=2,
        classification=classification,
        stage_evidence=_powermock_evidence(),
    )
    assert packet["risk_level"] == "high"
    assert packet["apply_candidate_allowed"] is False
    assert packet["backend_recipe_available"] is False


def test_unknown_strategy_policy_is_safe() -> None:
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=1,
        classification={"failure_type": "mystery"},
        stage_evidence={"usable_artifacts": [], "missing_artifacts": []},
    )
    assert packet["family"] == "UNKNOWN_FAILURE"
    assert packet["risk_level"] == "unknown"
    assert packet["strategy_status"] == "unknown"
    assert packet["apply_candidate_allowed"] is False
