from dataclasses import dataclass
from typing import Literal


RequiredMode = Literal["yes", "auto"]


@dataclass(frozen=True)
class MigrationUnit:
    id: str
    goal: str
    writes_source: bool
    tools: tuple[str, ...]
    validation: tuple[str, ...]
    required: RequiredMode


def build_migration_units() -> tuple[MigrationUnit, ...]:
    """Return deterministic MVP migration units in stable execution order."""

    return (
        MigrationUnit(
            id="baseline",
            goal="Establish baseline build and test posture before migration changes.",
            writes_source=False,
            tools=("maven", "junit"),
            validation=("mvn", "clean", "test"),
            required="yes",
        ),
        MigrationUnit(
            id="java-17",
            goal="Upgrade project runtime and build configuration to Java 17.",
            writes_source=True,
            tools=("maven",),
            validation=("mvn", "clean", "test"),
            required="yes",
        ),
        MigrationUnit(
            id="spring-boot-3-5-14",
            goal="Upgrade Spring Boot dependencies and plugins to 3.5.14.",
            writes_source=True,
            tools=("maven",),
            validation=("mvn", "clean", "test"),
            required="yes",
        ),
        MigrationUnit(
            id="jakarta",
            goal="Migrate javax usages to Jakarta namespace and APIs.",
            writes_source=True,
            tools=("maven", "jdeps"),
            validation=("mvn", "clean", "test"),
            required="yes",
        ),
        MigrationUnit(
            id="dependency-cleanup",
            goal="Resolve obsolete and incompatible dependencies after platform upgrades.",
            writes_source=True,
            tools=("maven",),
            validation=("mvn", "clean", "test"),
            required="yes",
        ),
        MigrationUnit(
            id="existing-test-migration",
            goal="Adapt existing test suites and test infrastructure to upgraded stack.",
            writes_source=True,
            tools=("maven", "junit"),
            validation=("mvn", "clean", "test"),
            required="auto",
        ),
    )
