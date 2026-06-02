from migration_factory.agents.planning_agent.unit_builder import build_migration_units


def test_build_migration_units_has_deterministic_ids_in_exact_order() -> None:
    units = build_migration_units()
    assert [unit.id for unit in units] == [
        "baseline",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "dependency-cleanup",
        "existing-test-migration",
    ]


def test_build_migration_units_route_aware_boot21_sequence() -> None:
    units = build_migration_units(
        {"target": {"java": "17", "spring_boot": "3.5.14", "build": "maven"}},
        selected_route_id="boot-2.1-to-3.5-java17",
    )

    assert [unit.id for unit in units] == [
        "baseline",
        "spring-boot-2-7-stabilization",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "jaxb-jakarta",
        "dependency-cleanup",
        "contract-compatibility-review",
        "existing-test-migration",
    ]
    assert next(unit for unit in units if unit.id == "baseline").java_home_env is None
    assert next(unit for unit in units if unit.id == "spring-boot-2-7-stabilization").openrewrite is not None
    assert next(unit for unit in units if unit.id == "jakarta").openrewrite is not None
    assert next(unit for unit in units if unit.id == "contract-compatibility-review").openrewrite is None


def test_build_migration_units_for_boot4_java21_profile() -> None:
    units = build_migration_units(
        {"target": {"java": "21", "spring_boot": "4.0.0", "build": "maven"}}
    )

    assert [unit.id for unit in units] == [
        "baseline",
        "java-21",
        "spring-boot-4-0",
        "jakarta",
        "dependency-cleanup",
        "existing-test-migration",
    ]
    assert units[1].goal == "Upgrade project runtime and build configuration to Java 21."
    assert units[2].goal == "Upgrade Spring Boot dependencies and plugins to 4.0."


def test_each_unit_has_required_fields_and_assist_policy_separate_from_tools() -> None:
    units = build_migration_units()

    for unit in units:
        assert isinstance(unit.id, str) and unit.id
        assert isinstance(unit.goal, str) and unit.goal
        assert isinstance(unit.writes_source, bool)
        assert isinstance(unit.tools, tuple) and unit.tools
        assert all(isinstance(tool, str) and tool for tool in unit.tools)
        assert isinstance(unit.validation, tuple) and unit.validation
        assert isinstance(unit.expected_artifacts, tuple) and unit.expected_artifacts
        assert isinstance(unit.rollback_strategy, str) and unit.rollback_strategy
        assert isinstance(unit.blocking_gate, str) and unit.blocking_gate
        assert unit.required in {"yes", "auto"}

        # assist policy is a first-class field on the unit, not embedded in tools.
        assert unit.assist_policy is not None


def test_existing_test_migration_unit_is_auto_required() -> None:
    units = build_migration_units()
    existing_test_unit = next(unit for unit in units if unit.id == "existing-test-migration")
    assert existing_test_unit.required == "auto"


def test_contract_compatibility_review_is_review_only() -> None:
    units = build_migration_units(
        {"target": {"java": "17", "spring_boot": "3.5.14", "build": "maven"}},
        selected_route_id="boot-2.1-to-3.5-java17",
    )
    review_unit = next(unit for unit in units if unit.id == "contract-compatibility-review")
    assert review_unit.writes_source is False


def test_jaxb_jakarta_is_separate_source_writing_unit() -> None:
    units = build_migration_units(
        {"target": {"java": "17", "spring_boot": "3.5.14", "build": "maven"}},
        selected_route_id="boot-2.1-to-3.5-java17",
    )
    jaxb_unit = next(unit for unit in units if unit.id == "jaxb-jakarta")
    assert jaxb_unit.writes_source is True
    assert jaxb_unit.openrewrite is not None


def test_route_aware_units_assign_source_and_target_jdks_by_hop() -> None:
    units = build_migration_units(
        {
            "target": {"java": "17", "spring_boot": "3.5.14", "build": "maven"},
            "source_jdk_home_env": "JAVA_HOME_11",
            "target_jdk_home_env": "JAVA_HOME_17",
        },
        selected_route_id="boot-2.1-to-3.5-java17",
        selected_hops=(
            {"id": "boot-2.1-to-2.7-java11"},
            {"id": "boot-2.7-to-3.5-java17"},
        ),
    )

    baseline = next(unit for unit in units if unit.id == "baseline")
    stabilization = next(unit for unit in units if unit.id == "spring-boot-2-7-stabilization")
    java17 = next(unit for unit in units if unit.id == "java-17")
    dependency_cleanup = next(unit for unit in units if unit.id == "dependency-cleanup")

    assert baseline.java_home_env == "JAVA_HOME_11"
    assert baseline.hop_id == "boot-2.1-to-2.7-java11"
    assert stabilization.java_home_env == "JAVA_HOME_11"
    assert stabilization.hop_id == "boot-2.1-to-2.7-java11"
    assert java17.java_home_env == "JAVA_HOME_17"
    assert java17.hop_id == "boot-2.7-to-3.5-java17"
    assert dependency_cleanup.java_home_env == "JAVA_HOME_17"
    assert dependency_cleanup.hop_id == "boot-2.7-to-3.5-java17"


def test_unit_tools_exclude_copilot_llm_and_model_names() -> None:
    units = build_migration_units()
    banned_tokens = {
        "copilot",
        "llm",
        "model",
        "gpt",
        "claude",
        "gemini",
        "llama",
        "mistral",
    }

    for unit in units:
        for tool in unit.tools:
            lower_tool = tool.lower()
            assert not any(token in lower_tool for token in banned_tokens)


def test_unit_definitions_do_not_embed_project_specific_names() -> None:
    units = build_migration_units(
        {"target": {"java": "17", "spring_boot": "3.5.14", "build": "maven"}},
        selected_route_id="boot-2.1-to-3.5-java17",
    )
    parts: list[str] = []
    for unit in units:
        parts.extend([unit.id, unit.goal, unit.rollback_strategy, unit.blocking_gate])
        if unit.openrewrite:
            parts.extend(str(value) for value in unit.openrewrite.values())
    rendered = " ".join(parts)
    assert "msa-dto" not in rendered
    assert "common-utils" not in rendered
