from __future__ import annotations

from copy import deepcopy

import pytest

from migration_factory.copilot_assist.providers import DeterministicCopilotProvider, ProviderResult


PROTECTED_STATE = {
    "status": "PASS",
    "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
    "approval_status": "COMPLETED",
    "approval_decision": "approved",
    "blockers": ["manual follow-up"],
    "warnings": ["deterministic warning"],
    "errors": ["deterministic error"],
    "verdict": "ready_for_review",
    "artifact_refs": {"migration_report": "final/migration_report.json"},
}


def test_deterministic_provider_phase_assist_returns_data_only_and_keeps_state_unchanged() -> None:
    provider = DeterministicCopilotProvider()
    state = deepcopy(PROTECTED_STATE)
    before = deepcopy(state)

    result = provider.phase_assist_fallback(
        run_id="run-001",
        phase="build",
        agent="build_agent",
        context=state,
    )
    payload = result.to_dict()

    assert isinstance(result, ProviderResult)
    assert state == before
    assert payload["schema_version"] == "1.0.0"
    assert payload["run_id"] == "run-001"
    assert payload["phase"] == "build"
    assert payload["agent"] == "build_agent"
    assert payload["status"] == "fallback"
    assert payload["provider"] == "deterministic"
    assert payload["advisory_only"] is True
    assert payload["fallback_used"] is True
    assert payload["confidence"] == "medium"
    assert "official migration statuses" in payload["blocked_actions"][0]


def test_deterministic_provider_rejects_unsupported_phase_without_mutating_state() -> None:
    provider = DeterministicCopilotProvider()
    state = deepcopy(PROTECTED_STATE)
    before = deepcopy(state)

    with pytest.raises(ValueError, match="unsupported Copilot assist phase"):
        provider.phase_assist_fallback(
            run_id="run-001",
            phase="deployment",
            agent="deploy_agent",
            context=state,
        )

    assert state == before


def test_deterministic_provider_final_report_keeps_official_state_fields_unchanged() -> None:
    provider = DeterministicCopilotProvider()
    state = deepcopy(PROTECTED_STATE)
    before = deepcopy(state)

    result = provider.final_report_fallback(run_id="run-001", context=state)
    payload = result.to_dict()

    assert state == before
    assert payload["status"] == "generated_with_fallback"
    assert payload["provider"] == "deterministic"
    assert payload["advisory_only"] is True
    assert payload["fallback_used"] is True
    assert payload["validation"]["uses_provided_context_only"] is True
