from dataclasses import dataclass
from typing import Literal
from .assist_config import AssistPolicy, build_assist_policy


RequiredMode = Literal["yes", "auto"]
UnitId = Literal[
    "baseline",
    "java-17",
    "spring-boot-3-5-14",
    "jakarta",
    "dependency-cleanup",
    "existing-test-migration",
]
ToolList = tuple[str, ...]

UNIT_ORDER: tuple[UnitId, ...] = (
    "baseline",
    "java-17",
    "spring-boot-3-5-14",
    "jakarta",
    "dependency-cleanup",
    "existing-test-migration",
)

# Deterministic tool mapping owned centrally to avoid per-unit drift.
TOOLS_BY_UNIT: dict[UnitId, ToolList] = {
    "baseline": ("maven", "junit"),
    "java-17": ("maven",),
    "spring-boot-3-5-14": ("maven",),
    "jakarta": ("maven", "jdeps"),
    "dependency-cleanup": ("maven",),
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


def _tools_for(unit_id: UnitId) -> ToolList:
    tools = TOOLS_BY_UNIT[unit_id]
    for tool in tools:
        lower_tool = tool.lower()
        if any(token in lower_tool for token in _BANNED_TOOL_TOKENS):
            raise ValueError(f"Disallowed tool token for {unit_id}: {tool}")
    return tools


def build_migration_units() -> tuple[MigrationUnit, ...]:
    """Return deterministic MVP migration units in stable execution order."""
    assist_policy = build_assist_policy()

    return (
        MigrationUnit(
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
        ),
        MigrationUnit(
            id="java-17",
            goal="Upgrade project runtime and build configuration to Java 17.",
            writes_source=True,
            tools=_tools_for("java-17"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy="Revert Java 17 configuration and dependency changes.",
            blocking_gate="Proceed only if Java 17 build and tests pass.",
            required="yes",
            assist_policy=assist_policy,
        ),
        MigrationUnit(
            id="spring-boot-3-5-14",
            goal="Upgrade Spring Boot dependencies and plugins to 3.5.14.",
            writes_source=True,
            tools=_tools_for("spring-boot-3-5-14"),
            validation=("mvn", "clean", "test"),
            expected_artifacts=("target/classes", "target/surefire-reports"),
            rollback_strategy="Revert Spring Boot version and related plugin updates.",
            blocking_gate="Proceed only if Spring Boot 3.5.14 build and tests pass.",
            required="yes",
            assist_policy=assist_policy,
        ),
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
        ),
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
