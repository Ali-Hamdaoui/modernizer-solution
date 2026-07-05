from __future__ import annotations

from migration_factory.control_tower.application.v2_repair_recipe_registry import (
    registered_repair_recipes,
    repair_recipe_policy,
)


def test_recipe_registry_returns_known_policies() -> None:
    names = set(registered_repair_recipes())
    assert {
        "INITMOCKS_DIRECT_REPLACEMENT",
        "JAKARTA_IMPORT_ONLY",
        "MOCKBEAN_DIRECT_REPLACEMENT",
        "DEPENDENCY_VERSION_BUMP_ONLY",
        "JACKSON_PROPERTY_BOM_ALIGNMENT",
        "POWERMOCK_STATIC_MOCK_SIMPLE",
        "POWERMOCK_CONSTRUCTOR_MOCKING",
        "POWERMOCK_PRIVATE_OR_FINAL_MOCKING",
        "SPRING_SECURITY_BEHAVIORAL_CHANGE",
        "JUNIT4_RULE_COMPLEX",
        "UNKNOWN_SUBFAMILY",
    }.issubset(names)


def test_initmocks_recipe_is_apply_enabled() -> None:
    policy = repair_recipe_policy("INITMOCKS_DIRECT_REPLACEMENT")
    assert policy.recipe_status == "apply_enabled"
    assert policy.backend_recipe_available is True
    assert policy.apply_candidate_allowed is True
    assert policy.dry_run_available is True
    assert policy.rollback_required is True
    assert policy.proof_required is True
    assert policy.rag_reuse_enabled is True


def test_jakarta_import_only_is_dry_run_only_in_r11a() -> None:
    policy = repair_recipe_policy("JAKARTA_IMPORT_ONLY")
    assert policy.recipe_status == "dry_run_only"
    assert policy.backend_recipe_available is False
    assert policy.apply_candidate_allowed is False
    assert policy.dry_run_available is True
    assert "business logic change" in policy.forbidden_patterns
    assert "dependency version change" in policy.forbidden_patterns


def test_mockbean_dependency_and_powermock_static_are_dry_run_only() -> None:
    for subfamily in (
        "MOCKBEAN_DIRECT_REPLACEMENT",
        "DEPENDENCY_VERSION_BUMP_ONLY",
        "POWERMOCK_STATIC_MOCK_SIMPLE",
    ):
        policy = repair_recipe_policy(subfamily)
        assert policy.recipe_status == "dry_run_only"
        assert policy.backend_recipe_available is False
        assert policy.apply_candidate_allowed is False
        assert policy.dry_run_available is True


def test_jackson_alignment_recipe_is_apply_enabled_with_human_gate() -> None:
    policy = repair_recipe_policy("JACKSON_PROPERTY_BOM_ALIGNMENT")
    assert policy.family == "JACKSON_VERSION_ALIGNMENT_DRIFT"
    assert policy.recipe_status == "apply_enabled"
    assert policy.risk_level == "medium"
    assert policy.backend_recipe_available is True
    assert policy.apply_candidate_allowed is True
    assert policy.dry_run_available is True
    assert policy.rollback_required is True
    assert policy.proof_required is True
    assert "pom_xml" in policy.required_evidence
    assert "dependency_graph" in policy.required_evidence


def test_high_risk_families_are_not_apply_capable() -> None:
    expectations = {
        "POWERMOCK_CONSTRUCTOR_MOCKING": "human_refactor_required",
        "POWERMOCK_PRIVATE_OR_FINAL_MOCKING": "human_refactor_required",
        "SPRING_SECURITY_BEHAVIORAL_CHANGE": "strategy_only",
        "JUNIT4_RULE_COMPLEX": "human_refactor_required",
    }
    for subfamily, expected_status in expectations.items():
        policy = repair_recipe_policy(subfamily)
        assert policy.recipe_status == expected_status
        assert policy.backend_recipe_available is False
        assert policy.apply_candidate_allowed is False


def test_unknown_recipe_is_unsupported() -> None:
    policy = repair_recipe_policy("not-real")
    assert policy.subfamily == "UNKNOWN_SUBFAMILY"
    assert policy.recipe_status == "unsupported"
    assert policy.backend_recipe_available is False
    assert policy.apply_candidate_allowed is False
    assert policy.dry_run_available is False
