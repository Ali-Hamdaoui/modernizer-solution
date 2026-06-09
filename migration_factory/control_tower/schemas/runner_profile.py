"""Runner profile schemas for Control Tower configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import field_validator, model_validator

from .common import NonEmptyString, StrictModel, ensure_unique_ids, reject_secret_like_value, require_non_empty_string


FilesystemRootKind = Literal["source", "output", "artifact", "cache"]


class RegisteredFilesystemRoot(StrictModel):
    root_id: NonEmptyString
    kind: FilesystemRootKind
    path: NonEmptyString
    description: str | None = None

    @field_validator("root_id", "path", mode="after")
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @field_validator("description", mode="after")
    @classmethod
    def _validate_optional_description(cls, value: str | None, info):
        if value is None:
            return value
        return require_non_empty_string(value, info.field_name)


class MavenConfiguration(StrictModel):
    maven_id: NonEmptyString
    maven_home: str | None = None
    settings_ref: str | None = None
    local_repository_ref: str | None = None
    version: str | None = None

    @field_validator("maven_id", mode="after")
    @classmethod
    def _validate_maven_id(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @field_validator(
        "maven_home",
        "settings_ref",
        "local_repository_ref",
        "version",
        mode="after",
    )
    @classmethod
    def _validate_optional_strings(cls, value: str | None, info):
        if value is None:
            return value
        return require_non_empty_string(value, info.field_name)


class JdkInstallation(StrictModel):
    jdk_id: NonEmptyString
    java_home: NonEmptyString
    major_version: int
    display_name: str | None = None

    @field_validator("jdk_id", "java_home", mode="after")
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @field_validator("display_name", mode="after")
    @classmethod
    def _validate_display_name(cls, value: str | None, info):
        if value is None:
            return value
        return require_non_empty_string(value, info.field_name)


class NetworkPolicy(StrictModel):
    allow_outbound: bool
    allowed_hosts: tuple[str, ...] = ()
    allowed_maven_repositories: tuple[str, ...] = ()
    allowed_model_endpoints: tuple[str, ...] = ()
    allowed_documentation_hosts: tuple[str, ...] = ()

    @field_validator(
        "allowed_hosts",
        "allowed_maven_repositories",
        "allowed_model_endpoints",
        "allowed_documentation_hosts",
        mode="after",
    )
    @classmethod
    def _validate_collections(cls, value: tuple[str, ...], info):
        return tuple(require_non_empty_string(item, info.field_name) for item in value)


class AiProfileReference(StrictModel):
    profile_id: NonEmptyString
    profile_version: NonEmptyString
    provider: NonEmptyString
    deployment_ref: NonEmptyString
    purpose: str | None = None

    @field_validator(
        "profile_id",
        "profile_version",
        "provider",
        "deployment_ref",
        "purpose",
        mode="after",
    )
    @classmethod
    def _reject_secret_like_strings(cls, value: str | None, info):
        if value is None:
            return value
        value = require_non_empty_string(value, info.field_name)
        return reject_secret_like_value(value, info.field_name)


class RunnerProfile(StrictModel):
    schema_version: NonEmptyString
    runner_profile_id: NonEmptyString
    runner_profile_version: NonEmptyString
    display_name: NonEmptyString
    filesystem_roots: tuple[RegisteredFilesystemRoot, ...]
    maven: MavenConfiguration
    jdk_inventory: tuple[JdkInstallation, ...]
    network_policy: NetworkPolicy
    ai_profiles: tuple[AiProfileReference, ...]

    @field_validator(
        "schema_version",
        "runner_profile_id",
        "runner_profile_version",
        "display_name",
        mode="after",
    )
    @classmethod
    def _validate_required_strings(cls, value: str, info):
        return require_non_empty_string(value, info.field_name)

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> "RunnerProfile":
        ensure_unique_ids(self.filesystem_roots, "root_id", "filesystem root_id")
        ensure_unique_ids(self.jdk_inventory, "jdk_id", "jdk_id")
        return self
