"""Shared migration profile model for Control Tower profile selection."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from .common import StrictModel


MigrationProfileId = Literal[
    "springboot-2.7-java11",
    "springboot-3.5-java17",
    "springboot-3.5-java21",
    "springboot-4.0-java21",
]


class MigrationProfile(StrictModel):
    profile_id: MigrationProfileId
    display_name: str
    order_index: int
    java_version: int
    spring_boot_line: str
    stage_index: int
    selectable_as_source: bool = True
    selectable_as_target: bool = True


_PROFILE_SEQUENCE: tuple[MigrationProfile, ...] = (
    MigrationProfile(
        profile_id="springboot-2.7-java11",
        display_name="Spring Boot 2.7 / Java 11",
        order_index=0,
        java_version=11,
        spring_boot_line="2.7",
        stage_index=1,
        selectable_as_source=True,
        selectable_as_target=False,
    ),
    MigrationProfile(
        profile_id="springboot-3.5-java17",
        display_name="Spring Boot 3.5 / Java 17",
        order_index=1,
        java_version=17,
        spring_boot_line="3.5",
        stage_index=2,
    ),
    MigrationProfile(
        profile_id="springboot-3.5-java21",
        display_name="Spring Boot 3.5 / Java 21",
        order_index=2,
        java_version=21,
        spring_boot_line="3.5",
        stage_index=3,
    ),
    MigrationProfile(
        profile_id="springboot-4.0-java21",
        display_name="Spring Boot 4.0 / Java 21",
        order_index=3,
        java_version=21,
        spring_boot_line="4.0",
        stage_index=4,
        selectable_as_source=False,
        selectable_as_target=True,
    ),
)


@lru_cache(maxsize=1)
def _profiles_by_id() -> dict[str, MigrationProfile]:
    return {profile.profile_id: profile for profile in _PROFILE_SEQUENCE}


def list_migration_profiles() -> tuple[MigrationProfile, ...]:
    return _PROFILE_SEQUENCE


def get_migration_profile(profile_id: str) -> MigrationProfile | None:
    return _profiles_by_id().get(profile_id)


def is_known_migration_profile(profile_id: str) -> bool:
    return get_migration_profile(profile_id) is not None


def is_selectable_source_profile(profile_id: str) -> bool:
    profile = get_migration_profile(profile_id)
    return bool(profile and profile.selectable_as_source)


def is_selectable_target_profile(profile_id: str) -> bool:
    profile = get_migration_profile(profile_id)
    return bool(profile and profile.selectable_as_target)


def default_source_profile_id() -> MigrationProfileId:
    return "springboot-2.7-java11"


def default_target_profile_id() -> MigrationProfileId:
    return "springboot-4.0-java21"
