from dataclasses import dataclass
from typing import Any, Literal

from .assist_config import AssistPolicy, build_assist_policy


RequiredMode = Literal["yes", "auto"]
UnitId = str
ToolList = tuple[str, ...]

UNIT_ORDER: tuple[UnitId, ...] = (
    "baseline",
    "java-17",
    "spring-boot-3-5-14",
    "jakarta",
    "dependency-cleanup",
    "existing-test-migration",
)

ROUTE_UNIT_ORDERS: dict[str, tuple[UnitId, ...]] = {
    "boot-2.1-to-3.5-java17": (
        "baseline",
        "spring-boot-2-7-stabilization",
        "java-17",
        "spring-boot-3-5-14",
        "jakarta",
        "jaxb-jakarta",
        "dependency-cleanup",
        "contract-compatibility-review",
        "existing-test-migration",
    ),
    "boot-2.1-to-3.5-java21": (
        "baseline",
        "spring-boot-2-7-stabilization",
        "java-21",
        "spring-boot-3-5-14",
        "jakarta",
        "jaxb-jakarta",
        "dependency-cleanup",
        "contract-compatibility-review",
        "existing-test-migration",
    ),
}

ROUTE_UNIT_OPENREWRITE: dict[str, dict[UnitId, dict[str, Any]]] = {
    "boot-2.1-to-3.5-java17": {
        "spring-boot-2-7-stabilization": {
            "active_recipes": ("org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7",),
        },
        "spring-boot-3-5-14": {
            "active_recipes": ("org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5",),
        },
        "jakarta": {
            "active_recipes": ("org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta",),
        },
        "jaxb-jakarta": {
            "active_recipes": ("org.openrewrite.java.migrate.jakarta.JavaxXmlBindMigrationToJakartaXmlBind",),
        },
    },
    "boot-2.1-to-3.5-java21": {
        "spring-boot-2-7-stabilization": {
            "active_recipes": ("org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7",),
        },
        "java-21": {
            "active_recipes": ("org.openrewrite.java.migrate.UpgradeToJava21",),
        },
        "spring-boot-3-5-14": {
            "active_recipes": ("org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5",),
        },
        "jakarta": {
            "active_recipes": ("org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta",),
        },
        "jaxb-jakarta": {
            "active_recipes": ("org.openrewrite.java.migrate.jakarta.JavaxXmlBindMigrationToJakartaXmlBind",),
        },
    },
}

# Deterministic tool mapping owned centrally to avoid per-unit drift.
TOOLS_BY_UNIT: dict[UnitId, ToolList] = {
    "baseline": ("maven", "junit"),
    "java-17": ("maven",),
    "java-21": ("maven",),
    "java-21-runtime-validation": ("maven", "junit"),
    "spring-boot-2-7": ("maven",),
    "spring-boot-2-7-stabilization": ("maven",),
    "spring-boot-3-5-14": ("maven",),
    "spring-boot-4-0": ("maven",),
    "jakarta": ("maven", "jdeps"),
    "jaxb-jakarta": ("maven", "jdeps"),
    "dependency-cleanup": ("maven",),
    "contract-compatibility-review": ("maven",),
    "existing-test-migration": ("maven", "junit"),
}

_BANNED_TOOL_TOKENS: tuple[str, ...] = ("copilot", "llm")


@dataclass(frozen=True)
class MigrationUnit:
    id: str
    goal: str
    writes_source: bool
    tools: tuple[str, ...]
    validation: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    rollback_strategy: str
    blocking_gate: str
    required: RequiredMode
    assist_policy: AssistPolicy
    openrewrite: dict[str, Any] | None = None
    java_home_env: str | None = None
    hop_id: str | None = None


def _tools_for(unit_id: UnitId) -> ToolList:
    tools = TOOLS_BY_UNIT.get(unit_id, ("maven",))
    for tool in tools:
        lower_tool = tool.lower()
        if any(token in lower_tool for token in _BANNED_TOOL_TOKENS):
            raise ValueError(f"Disallowed tool token for {unit_id}: {tool}")
    return tools


def build_migration_units(
    profile: dict[str, Any] | None = None,
    selected_route_id: str | None = None,
    selected_hops: tuple[dict[str, Any], ...] = (),
) -> tuple[MigrationUnit, ...]:
    """Return deterministic migration units in stable execution order."""
    assist_policy = build_assist_policy()
    strategy = str((profile or {}).get("strategy") or "")
    if strategy == "java21_runtime_validation_only":
        return (_baseline_unit(assist_policy), _java21_validation_unit(assist_policy))

    target = _target_from_profile(profile)
    if selected_route_id in ROUTE_UNIT_ORDERS:
        unit_order = _unit_order_for_route(profile, target, selected_route_id)
        runtime_metadata = _runtime_metadata_for_units(profile, selected_route_id, selected_hops)
        return tuple(
            _build_unit(
                unit_id,
                profile,
                target,
                assist_policy,
                selected_route_id,
                runtime_metadata.get(unit_id, {}),
            )
            for unit_id in unit_order
        )

    source = _source_from_profile(profile)
    java_unit = f"java-{target.java}"
    boot_unit = _spring_boot_unit_id(target.spring_boot)
    java_label = f"Java {target.java}"
    boot_label = _spring_boot_label(target.spring_boot)

    units: list[MigrationUnit] = [_baseline_unit(assist_policy)]
    if source.java != target.java:
        units.append(
            MigrationUnit(
                id=java_unit,
                goal=f"Upgrade project runtime and build configuration to {java_label}.",
                writes_source=True,
                tools=_tools_for(java_unit),
                validation=("mvn", "clean", "test"),
                expected_artifacts=("target/classes", "target/surefire-reports"),
                rollback_strategy=f"Revert {java_label} configuration and dependency changes.",
                blocking_gate=f"Proceed only if {java_label} build and tests pass.",
                required="yes",
                assist_policy=assist_policy,
            )
        )
    if source.spring_boot != target.spring_boot:
        units.append(
            MigrationUnit(
                id=boot_unit,
                goal=f"Upgrade Spring Boot dependencies and plugins to {boot_label}.",
                writes_source=True,
                tools=_tools_for(boot_unit),
                validation=("mvn", "clean", "test"),
                expected_artifacts=("target/classes", "target/surefire-reports"),
                rollback_strategy="Revert Spring Boot version and related plugin updates.",
                blocking_gate=f"Proceed only if Spring Boot {boot_label} build and tests pass.",
                required="yes",
                assist_policy=assist_policy,
            )
        )
    if _spring_boot_major(target.spring_boot) >= 3:
        units.append(
            MigrationUnit(
                id="jakarta",
                goal="Migrate javax usages to Jakarta namespace and APIs.",
                writes_source=True,
                tools=_tools_for("jakarta"),
                validation=("mvn", "clean", "test"),
                expected_artifacts=("target/classes", "target/surefire-reports"),
                rollback_strategy="Revert Jakarta namespace refactors and dependency adjustments.",
                blocking_gate="Proceed only if Jakarta migration compiles and tests pass.",
                required="yes",
                assist_policy=assist_policy,
            )
        )
    units.extend(
        (
            MigrationUnit(
                id="dependency-cleanup",
                goal="Resolve obsolete and incompatible dependencies after platform upgrades.",
                writes_source=True,
                tools=_tools_for("dependency-cleanup"),
                validation=("mvn", "clean", "test"),
                expected_artifacts=("target/dependency", "target/surefire-reports"),
                rollback_strategy="Revert dependency cleanup updates to previous locked set.",
                blocking_gate="Proceed only if dependency graph resolves and tests pass.",
                required="yes",
                assist_policy=assist_policy,
            ),
            MigrationUnit(
                id="existing-test-migration",
                goal="Adapt existing test suites and test infrastructure to upgraded stack.",
                writes_source=True,
                tools=_tools_for("existing-test-migration"),
                validation=("mvn", "clean", "test"),
                expected_artifacts=("target/test-classes", "target/surefire-reports"),
                rollback_strategy="Revert test framework and test source migration changes.",
                blocking_gate="Proceed only if migrated tests pass on upgraded stack.",
                required="auto",
                assist_policy=assist_policy,
            ),
        )
    )
    return tuple(units)


@dataclass(frozen=True)
class _TargetVersions:
    java: str = "17"
    spring_boot: str = "3.5.14"


def _baseline_unit(assist_policy: AssistPolicy) -> MigrationUnit:
    return MigrationUnit(
        id="baseline",
        goal="Establish baseline build and test posture before migration changes.",
        writes_source=False,
        tools=_tools_for("baseline"),
        validation=("mvn", "clean", "test"),
        expected_artifacts=("target/surefire-reports",),
        rollback_strategy="Revert baseline verification changes and restore prior working tree state.",
        blocking_gate="Proceed only if baseline mvn clean test passes.",
        required="yes",
        assist_policy=assist_policy,
    )


def _java21_validation_unit(assist_policy: AssistPolicy) -> MigrationUnit:
    return MigrationUnit(
        id="java-21-runtime-validation",
        goal="Validate the already-migrated Spring Boot 3.5 application on a Java 21 runtime.",
        writes_source=True,
        tools=_tools_for("java-21-runtime-validation"),
        validation=("mvn", "clean", "test"),
        expected_artifacts=("target/classes", "target/surefire-reports"),
        rollback_strategy="Revert Java 21 recipe application and restore prior Java 17-compatible sources.",
        blocking_gate="Proceed only if Java 21 recipe application and runtime validation pass.",
        required="yes",
        assist_policy=assist_policy,
    )


def _target_from_profile(profile: dict[str, Any] | None) -> _TargetVersions:
    target = profile.get("target") if isinstance(profile, dict) else None
    if not isinstance(target, dict):
        return _TargetVersions()
    java = _major_text(target.get("java")) or "17"
    spring_boot = _version_text(target.get("spring_boot")) or "3.5.14"
    return _TargetVersions(java=java, spring_boot=spring_boot)


def _source_from_profile(profile: dict[str, Any] | None) -> _TargetVersions:
    source = profile.get("source") if isinstance(profile, dict) else None
    if not isinstance(source, dict):
        return _TargetVersions(java="", spring_boot="")
    java = _first_allowed(source.get("java")) or ""
    spring_boot = _first_allowed(source.get("spring_boot")) or ""
    return _TargetVersions(java=java, spring_boot=spring_boot)


def _spring_boot_unit_id(version: str) -> str:
    parts = version.split(".")
    if version == "3.5.14":
        return "spring-boot-3-5-14"
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"spring-boot-{parts[0]}-{parts[1]}"
    return "spring-boot-" + version.replace(".", "-")


def _spring_boot_label(version: str) -> str:
    if version == "3.5.14":
        return "3.5.14"
    parts = version.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1]}"
    return version


def _major_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text.split(".", 1)[0]


def _version_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _first_allowed(value: Any) -> str | None:
    if not isinstance(value, dict):
        return _version_text(value)
    values = value.get("allowed_versions") or value.get("allowed_version_prefixes")
    if isinstance(values, list) and values:
        return _version_text(values[0])
    return None


def _spring_boot_major(value: str) -> int:
    try:
        return int(str(value).split(".", 1)[0])
    except (TypeError, ValueError):
        return 0


def _unit_order_for_route(
    profile: dict[str, Any] | None,
    target: _TargetVersions,
    selected_route_id: str | None,
) -> tuple[UnitId, ...]:
    route_metadata = _route_migration_units_metadata(profile, selected_route_id)
    route_order = route_metadata.get("order")
    if isinstance(route_order, tuple) and route_order:
        return route_order
    if selected_route_id and selected_route_id in ROUTE_UNIT_ORDERS:
        return ROUTE_UNIT_ORDERS[selected_route_id]
    return (
        "baseline",
        f"java-{target.java}",
        _spring_boot_unit_id(target.spring_boot),
        "jakarta",
        "dependency-cleanup",
        "existing-test-migration",
    )


def _build_unit(
    unit_id: UnitId,
    profile: dict[str, Any] | None,
    target: _TargetVersions,
    assist_policy: AssistPolicy,
    selected_route_id: str | None,
    runtime_metadata: dict[str, str | None],
) -> MigrationUnit:
    java_label = f"Java {target.java}"
    boot_label = _spring_boot_label(target.spring_boot)
    openrewrite = _openrewrite_for_unit(profile, selected_route_id, unit_id)
    java_home_env = _text_or_none(runtime_metadata.get("java_home_env"))
    hop_id = _text_or_none(runtime_metadata.get("hop_id"))

    if unit_id == "baseline":
        return MigrationUnit(
            id="baseline",
            goal="Establish baseline build and test posture before migration changes.",
            writes_source=False,
            tools=_tools_for("baseline"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/surefire-reports",),
            rollback_strategy="Revert baseline verification changes and restore prior working tree state.",
            blocking_gate="Proceed only if baseline mvn clean test passes.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id.startswith("java-") and unit_id != "java-21-runtime-validation":
        return MigrationUnit(
            id=unit_id,
            goal=f"Upgrade project runtime and build configuration to {java_label}.",
            writes_source=True,
            tools=_tools_for(unit_id),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy=f"Revert {java_label} configuration and dependency changes.",
            blocking_gate=f"Proceed only if {java_label} build and tests pass.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "java-21-runtime-validation":
        return _java21_validation_unit(assist_policy)
    if unit_id == "spring-boot-2-7-stabilization":
        return MigrationUnit(
            id=unit_id,
            goal="Stabilize project on Spring Boot 2.7.x before Boot 3.5 migration step.",
            writes_source=True,
            tools=_tools_for(unit_id),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy="Revert Spring Boot 2.7 stabilization updates and restored aligned plugin configuration.",
            blocking_gate="Proceed only if Spring Boot 2.7 stabilization build and tests pass.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id.startswith("spring-boot-"):
        return MigrationUnit(
            id=unit_id,
            goal=f"Upgrade Spring Boot dependencies and plugins to {boot_label}.",
            writes_source=True,
            tools=_tools_for(unit_id),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy="Revert Spring Boot version and related plugin updates.",
            blocking_gate=f"Proceed only if Spring Boot {boot_label} build and tests pass.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "jakarta":
        return MigrationUnit(
            id="jakarta",
            goal="Migrate javax usages to Jakarta namespace and APIs.",
            writes_source=True,
            tools=_tools_for("jakarta"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy="Revert Jakarta namespace refactors and dependency adjustments.",
            blocking_gate="Proceed only if Jakarta migration compiles and tests pass.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "jaxb-jakarta":
        return MigrationUnit(
            id="jaxb-jakarta",
            goal="Migrate JAXB and XML binding usage to Jakarta-compatible APIs with contract review checkpoints.",
            writes_source=True,
            tools=_tools_for("jaxb-jakarta"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/generated-sources", "target/surefire-reports"),
            rollback_strategy="Revert JAXB and XML binding migration changes to prior API set.",
            blocking_gate="Proceed only if JAXB/Jakarta migration preserves compilation and contract-sensitive tests.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "dependency-cleanup":
        return MigrationUnit(
            id="dependency-cleanup",
            goal="Resolve obsolete and incompatible dependencies after platform upgrades.",
            writes_source=True,
            tools=_tools_for("dependency-cleanup"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/dependency", "target/surefire-reports"),
            rollback_strategy="Revert dependency cleanup updates to previous locked set.",
            blocking_gate="Proceed only if dependency graph resolves and tests pass.",
            required="yes",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "contract-compatibility-review":
        return MigrationUnit(
            id="contract-compatibility-review",
            goal="Review external and internal contract compatibility risks after framework and JAXB changes.",
            writes_source=False,
            tools=_tools_for("contract-compatibility-review"),
            validation=("mvn", "test"),
            expected_artifacts=("target/surefire-reports",),
            rollback_strategy="Discard review notes or follow-up planning deltas produced from contract compatibility assessment.",
            blocking_gate="Proceed only after contract compatibility review is completed and recorded.",
            required="auto",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    if unit_id == "existing-test-migration":
        return MigrationUnit(
            id="existing-test-migration",
            goal="Adapt existing test suites and test infrastructure to upgraded stack.",
            writes_source=True,
            tools=_tools_for("existing-test-migration"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/test-classes", "target/surefire-reports"),
            rollback_strategy="Revert test framework and test source migration changes.",
            blocking_gate="Proceed only if migrated tests pass on upgraded stack.",
            required="auto",
            assist_policy=assist_policy,
            openrewrite=openrewrite,
            java_home_env=java_home_env,
            hop_id=hop_id,
        )
    raise ValueError(f"Unsupported migration unit id: {unit_id}")


def _runtime_metadata_for_units(
    profile: dict[str, Any] | None,
    selected_route_id: str | None,
    selected_hops: tuple[dict[str, Any], ...],
) -> dict[str, dict[str, str | None]]:
    if not isinstance(profile, dict):
        return {}
    source_env = _text_or_none(profile.get("source_jdk_home_env"))
    target_env = _text_or_none(profile.get("target_jdk_home_env"))
    hop_ids = [str(hop.get("id") or "") for hop in selected_hops if isinstance(hop, dict)]
    first_hop = hop_ids[0] if hop_ids else None
    second_hop = hop_ids[1] if len(hop_ids) > 1 else first_hop

    if selected_route_id == "boot-2.1-to-3.5-java17":
        return {
            "baseline": {"java_home_env": source_env, "hop_id": first_hop},
            "spring-boot-2-7-stabilization": {"java_home_env": source_env, "hop_id": first_hop},
            "java-17": {"java_home_env": target_env, "hop_id": second_hop},
            "spring-boot-3-5-14": {"java_home_env": target_env, "hop_id": second_hop},
            "jakarta": {"java_home_env": target_env, "hop_id": second_hop},
            "jaxb-jakarta": {"java_home_env": target_env, "hop_id": second_hop},
            "dependency-cleanup": {"java_home_env": target_env, "hop_id": second_hop},
            "contract-compatibility-review": {"java_home_env": target_env, "hop_id": second_hop},
            "existing-test-migration": {"java_home_env": target_env, "hop_id": second_hop},
        }
    if selected_route_id == "boot-2.1-to-3.5-java21":
        return {
            "baseline": {"java_home_env": source_env, "hop_id": first_hop},
            "spring-boot-2-7-stabilization": {"java_home_env": source_env, "hop_id": first_hop},
            "java-21": {"java_home_env": target_env, "hop_id": second_hop},
            "spring-boot-3-5-14": {"java_home_env": target_env, "hop_id": second_hop},
            "jakarta": {"java_home_env": target_env, "hop_id": second_hop},
            "jaxb-jakarta": {"java_home_env": target_env, "hop_id": second_hop},
            "dependency-cleanup": {"java_home_env": target_env, "hop_id": second_hop},
            "contract-compatibility-review": {"java_home_env": target_env, "hop_id": second_hop},
            "existing-test-migration": {"java_home_env": target_env, "hop_id": second_hop},
        }
    return {}


def _text_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _openrewrite_for_unit(
    profile: dict[str, Any] | None,
    selected_route_id: str | None,
    unit_id: UnitId,
) -> dict[str, Any] | None:
    route_metadata = _route_migration_units_metadata(profile, selected_route_id)
    route_units = route_metadata.get("openrewrite")
    if isinstance(route_units, dict):
        config = route_units.get(unit_id)
        if isinstance(config, dict):
            return _normalize_openrewrite_config(config)

    if not selected_route_id:
        return None
    legacy_route_units = ROUTE_UNIT_OPENREWRITE.get(selected_route_id)
    if not isinstance(legacy_route_units, dict):
        return None
    config = legacy_route_units.get(unit_id)
    if not isinstance(config, dict):
        return None
    return _normalize_openrewrite_config(config)


def _route_migration_units_metadata(
    profile: dict[str, Any] | None,
    selected_route_id: str | None,
) -> dict[str, Any]:
    if not selected_route_id or not isinstance(profile, dict):
        return {}
    selected_route = _selected_route(profile, selected_route_id)
    if not isinstance(selected_route, dict):
        return {}
    migration_units = selected_route.get("migration_units")
    if not isinstance(migration_units, dict):
        return {}

    normalized: dict[str, Any] = {}
    order = migration_units.get("order")
    if isinstance(order, list) and order:
        normalized_order = tuple(str(item).strip() for item in order if str(item).strip())
        if normalized_order:
            normalized["order"] = normalized_order
    openrewrite = migration_units.get("openrewrite")
    if isinstance(openrewrite, dict):
        normalized_openrewrite: dict[str, dict[str, Any]] = {}
        for unit_id, config in openrewrite.items():
            if not isinstance(config, dict):
                continue
            unit_key = str(unit_id).strip()
            if not unit_key:
                continue
            normalized_openrewrite[unit_key] = _normalize_openrewrite_config(config)
        if normalized_openrewrite:
            normalized["openrewrite"] = normalized_openrewrite
    return normalized


def _selected_route(profile: dict[str, Any], selected_route_id: str) -> dict[str, Any] | None:
    routes = profile.get("routes")
    if not isinstance(routes, list):
        return None
    for route in routes:
        if isinstance(route, dict) and str(route.get("id") or "").strip() == selected_route_id:
            return route
    return None


def _normalize_openrewrite_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: tuple(str(item) for item in value) if isinstance(value, (list, tuple)) else value
        for key, value in config.items()
    }
