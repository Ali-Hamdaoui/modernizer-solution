from __future__ import annotations

from migration_factory.control_tower.application.v2_repair_family_registry import (
    registered_repair_families,
    repair_family_policy,
)


def test_registry_returns_policies_for_known_families() -> None:
    families = set(registered_repair_families())
    assert {
        "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        "POWERMOCK_LEGACY_TEST_STRATEGY",
        "MOCKBEAN_TO_MOCKITOBEAN_CANDIDATE",
        "JAKARTA_NAMESPACE_MISMATCH",
        "JUNIT4_TO_JUNIT5_TEST_MIGRATION",
        "DEPENDENCY_VERSION_ALIGNMENT",
        "SPRING_SECURITY_API_DRIFT",
        "UNKNOWN_FAILURE",
    }.issubset(families)


def test_powermock_is_high_risk_strategy_only() -> None:
    policy = repair_family_policy("POWERMOCK_LEGACY_TEST_STRATEGY")
    assert policy.risk_level == "high"
    assert policy.backend_recipe_available is False
    assert policy.apply_candidate_allowed is False
    assert policy.human_gate_required is True
    assert policy.llm_proposer_enabled is True
    assert policy.llm_reviewer_required is True


def test_initmocks_remains_low_risk_apply_capable() -> None:
    policy = repair_family_policy("INITMOCKS_TO_OPENMOCKS_CANDIDATE")
    assert policy.risk_level == "low"
    assert policy.backend_recipe_available is True
    assert policy.apply_candidate_allowed is True
    assert policy.human_gate_required is True


def test_unknown_failure_returns_unknown_strategy_policy() -> None:
    policy = repair_family_policy("not-yet-classified")
    assert policy.family == "UNKNOWN_FAILURE"
    assert policy.risk_level == "unknown"
    assert policy.apply_candidate_allowed is False
