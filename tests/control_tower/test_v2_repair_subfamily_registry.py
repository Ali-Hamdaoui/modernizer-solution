from __future__ import annotations

from migration_factory.control_tower.application.v2_repair_subfamily_registry import (
    registered_repair_subfamilies,
    repair_subfamily_policy,
)


def test_subfamily_registry_returns_known_policies() -> None:
    names = set(registered_repair_subfamilies())
    assert {
        "INITMOCKS_DIRECT_REPLACEMENT",
        "MOCKBEAN_DIRECT_REPLACEMENT",
        "POWERMOCK_STATIC_MOCK_SIMPLE",
        "POWERMOCK_CONSTRUCTOR_MOCKING",
        "POWERMOCK_PRIVATE_OR_FINAL_MOCKING",
        "JUNIT4_RUNNER_SIMPLE",
        "JUNIT4_RULE_COMPLEX",
        "JAKARTA_IMPORT_ONLY",
        "JAKARTA_DEPENDENCY_ALIGNMENT",
        "DEPENDENCY_VERSION_BUMP_ONLY",
        "SPRING_SECURITY_BEHAVIORAL_CHANGE",
        "UNKNOWN_SUBFAMILY",
    }.issubset(names)


def test_initmocks_direct_replacement_is_safe_recipe_candidate() -> None:
    policy = repair_subfamily_policy("INITMOCKS_DIRECT_REPLACEMENT")
    assert policy.promotion_status == "safe_recipe_candidate"
    assert policy.backend_recipe_available is True
    assert policy.apply_candidate_allowed is True
    assert policy.human_gate_required is True


def test_powermock_static_simple_is_not_globally_auto_applied() -> None:
    policy = repair_subfamily_policy("POWERMOCK_STATIC_MOCK_SIMPLE")
    assert policy.promotion_status == "medium_risk_recipe_candidate"
    assert policy.backend_recipe_available is False
    assert policy.apply_candidate_allowed is False


def test_powermock_constructor_and_private_final_are_human_refactor_required() -> None:
    constructor = repair_subfamily_policy("POWERMOCK_CONSTRUCTOR_MOCKING")
    private_final = repair_subfamily_policy("POWERMOCK_PRIVATE_OR_FINAL_MOCKING")
    assert constructor.promotion_status == "human_refactor_required"
    assert constructor.apply_candidate_allowed is False
    assert private_final.promotion_status == "human_refactor_required"
    assert private_final.apply_candidate_allowed is False


def test_unknown_subfamily_is_unsupported() -> None:
    policy = repair_subfamily_policy("not-real")
    assert policy.subfamily == "UNKNOWN_SUBFAMILY"
    assert policy.promotion_status == "unsupported"
    assert policy.apply_candidate_allowed is False
