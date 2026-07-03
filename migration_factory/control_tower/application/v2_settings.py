"""V2 Control Tower Settings — env ref projection and redacted settings display.

This module defines the Pydantic-backed settings class for the V2 local
migration cockpit. All Azure secrets, endpoints, and deployment IDs are
loaded from environment variables at process start and are never exposed
in API responses. The UI receives only env ref names (strings like
"AZURE_OPENAI_ENDPOINT"), booleans, role labels, and health status.

Design:
- ControlTowerSettings loads from env at startup via pydantic-settings.
- Env ref projection produces a safe dict for /v1/settings/ai without
  exposing endpoint URLs, API keys, deployment IDs, or raw prompts.
- Redaction helpers display paths in local-only mode but never show
  forbidden paths, secrets, or Azure credentials.
- is_configured() checks whether an env var is set without revealing its value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

from migration_factory.control_tower.application.redaction import (
    FORBIDDEN_PATH_PREFIXES,
    SENSITIVE_ENV_VARS,
    contains_forbidden_path,
    redact_absolute_paths,
)


# ── V2 Settings class ────────────────────────────────────────────────


class ControlTowerSettings(BaseSettings):
    """V2 Control Tower settings loaded from environment variables.

    All Azure Foundry values are stored as env refs — the setting stores
    the *name* of the env variable, not its value. The corresponding env
    var is read by the backend process only and is never returned in API
    responses.

    Local operator mode paths are accepted as typed frontend inputs and
    validated by the backend before queuing commands.
    """

    model_config = {"env_prefix": "CONTROL_TOWER_"}

    # ── Bind settings ──────────────────────────────────────────────
    bind_host: str = "127.0.0.1"
    bind_port: int = 8000

    # ── Local mode ─────────────────────────────────────────────────
    local_mode: bool = True
    allowed_source_roots: str = ""
    allowed_output_roots: str = ""
    default_ai_hub_path: str = ""

    # ── Azure Foundry settings (env refs) ──────────────────────────
    azure_foundry_provider: str = "azure_openai"
    azure_foundry_endpoint_env: str = "AZURE_OPENAI_ENDPOINT"
    azure_foundry_auth_mode: str = "api_key_or_entra"
    azure_foundry_api_key_env: str = "AZURE_OPENAI_API_KEY"
    azure_foundry_api_version: str = ""

    azure_foundry_proposer_deployment_env: str = "AZURE_OPENAI_PROPOSER_DEPLOYMENT"
    azure_foundry_reviewer_deployment_env: str = "AZURE_OPENAI_REVIEWER_DEPLOYMENT"
    azure_foundry_assistant_deployment_env: str = "AZURE_OPENAI_ASSISTANT_DEPLOYMENT"
    azure_foundry_fallback_deployment_env: str = "AZURE_OPENAI_FALLBACK_DEPLOYMENT"
    azure_foundry_fallback_enabled: bool = False

    # ── Model role display names and token budgets (env refs) ──────
    azure_foundry_main_model_display_name_env: str = "AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME"
    azure_foundry_reviewer_model_display_name_env: str = "AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME"
    azure_foundry_main_reasoning_effort_env: str = "AI_MIGRATION_MAIN_REASONING_EFFORT"
    azure_foundry_main_max_input_tokens_env: str = "AI_MIGRATION_MAIN_MAX_INPUT_TOKENS"
    azure_foundry_main_max_output_tokens_env: str = "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS"
    azure_foundry_reviewer_max_input_tokens_env: str = "AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS"
    azure_foundry_reviewer_max_output_tokens_env: str = "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS"
    azure_foundry_reviewer_response_format_env: str = "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT"

    # ── Mistral provider settings (env refs) ───────────────────────
    mistral_provider: str = "mistral"
    mistral_endpoint_env: str = "MISTRAL_ENDPOINT"
    mistral_api_key_env: str = "MISTRAL_API_KEY"
    mistral_reviewer_model_id_env: str = "AI_MIGRATION_REVIEWER_MODEL"

    # ── AI Migration main role config (env refs) ────────────────────
    ai_migration_main_provider_env: str = "AI_MIGRATION_MAIN_PROVIDER"
    ai_migration_main_model_env: str = "AI_MIGRATION_MAIN_MODEL"
    ai_migration_main_model_display_name_env: str = "AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME"
    ai_migration_main_endpoint_type_env: str = "AI_MIGRATION_MAIN_ENDPOINT_TYPE"
    ai_migration_main_response_format_env: str = "AI_MIGRATION_MAIN_RESPONSE_FORMAT"
    ai_migration_main_max_input_tokens_env: str = "AI_MIGRATION_MAIN_MAX_INPUT_TOKENS"
    ai_migration_main_max_output_tokens_env: str = "AI_MIGRATION_MAIN_MAX_OUTPUT_TOKENS"
    ai_migration_main_reasoning_effort_env: str = "AI_MIGRATION_MAIN_REASONING_EFFORT"
    ai_migration_main_timeout_seconds_env: str = "AI_MIGRATION_MAIN_TIMEOUT_SECONDS"

    # ── AI Migration reviewer role config (env refs) ────────────────
    ai_migration_reviewer_provider_env: str = "AI_MIGRATION_REVIEWER_PROVIDER"
    ai_migration_reviewer_model_env: str = "AI_MIGRATION_REVIEWER_MODEL"
    ai_migration_reviewer_model_display_name_env: str = "AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME"
    ai_migration_reviewer_endpoint_type_env: str = "AI_MIGRATION_REVIEWER_ENDPOINT_TYPE"
    ai_migration_reviewer_response_format_env: str = "AI_MIGRATION_REVIEWER_RESPONSE_FORMAT"
    ai_migration_reviewer_max_input_tokens_env: str = "AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS"
    ai_migration_reviewer_max_output_tokens_env: str = "AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS"
    ai_migration_reviewer_reasoning_effort_env: str = "AI_MIGRATION_REVIEWER_REASONING_EFFORT"
    ai_migration_reviewer_timeout_seconds_env: str = "AI_MIGRATION_REVIEWER_TIMEOUT_SECONDS"

    # ── AI Migration fallback role config (env refs) ────────────────
    ai_migration_fallback_provider_env: str = "AI_MIGRATION_FALLBACK_PROVIDER"
    ai_migration_fallback_model_env: str = "AI_MIGRATION_FALLBACK_MODEL"
    ai_migration_fallback_model_display_name_env: str = "AI_MIGRATION_FALLBACK_MODEL_DISPLAY_NAME"
    ai_migration_fallback_endpoint_type_env: str = "AI_MIGRATION_FALLBACK_ENDPOINT_TYPE"
    ai_migration_fallback_response_format_env: str = "AI_MIGRATION_FALLBACK_RESPONSE_FORMAT"
    ai_migration_fallback_max_input_tokens_env: str = "AI_MIGRATION_FALLBACK_MAX_INPUT_TOKENS"
    ai_migration_fallback_max_output_tokens_env: str = "AI_MIGRATION_FALLBACK_MAX_OUTPUT_TOKENS"
    ai_migration_fallback_reasoning_effort_env: str = "AI_MIGRATION_FALLBACK_REASONING_EFFORT"
    ai_migration_fallback_timeout_seconds_env: str = "AI_MIGRATION_FALLBACK_TIMEOUT_SECONDS"


# ── Env ref helpers ──────────────────────────────────────────────────


def is_env_var_configured(env_var_name: str | None) -> bool:
    """Check whether an env var is set, without revealing its value."""
    if not env_var_name:
        return False
    value = os.environ.get(env_var_name)
    return bool(value and value.strip())


def env_ref_display_name(env_var_name: str) -> str:
    """Return a display-safe env ref string for the UI.

    Returns the env var name itself (not the value). The UI sees
    e.g. "AZURE_OPENAI_ENDPOINT" and the backend resolves it.
    """
    return env_var_name


# ── Redacted settings projection ─────────────────────────────────────


@dataclass(frozen=True)
class EnvRefStatus:
    """Safe status of a single env-ref-backed setting."""
    env_ref: str
    configured: bool


@dataclass(frozen=True)
class DeploymentRoleStatus:
    """Safe status of a model deployment role."""
    env_ref: str
    configured: bool
    deployment_label: str
    enabled: bool = True


@dataclass(frozen=True)
class AzureFoundryProjection:
    """Redacted Azure Foundry settings projection for /v1/settings/ai."""
    profile_id: str
    provider: str
    endpoint: EnvRefStatus
    auth_mode: str
    api_version_configured: bool
    roles: dict[str, DeploymentRoleStatus]


@dataclass(frozen=True)
class LocalModeProjection:
    """Redacted local mode settings projection."""
    enabled: bool
    allowed_source_roots: tuple[str, ...] = ()
    allowed_output_roots: tuple[str, ...] = ()
    default_ai_hub_path: str = ""


@dataclass(frozen=True)
class MistralProjection:
    """Redacted Mistral settings projection."""
    provider: str
    endpoint: EnvRefStatus
    reviewer_model_configured: bool
    reviewer_model_env_ref: str


@dataclass(frozen=True)
class SettingsProjection:
    """Complete redacted settings projection for public API."""
    azure: AzureFoundryProjection
    local_mode: LocalModeProjection
    mistral: MistralProjection | None = None
    mistral: MistralProjection | None = None


def build_settings_projection(settings: ControlTowerSettings) -> SettingsProjection:
    """Build a redacted settings projection with env refs only.

    No secret values (endpoints, keys, deployment IDs) are included
    in the returned projection. Only env ref names and booleans are
    exposed.
    """
    azure = AzureFoundryProjection(
        profile_id="azure-foundry-v2",
        provider=settings.azure_foundry_provider,
        endpoint=EnvRefStatus(
            env_ref=settings.azure_foundry_endpoint_env,
            configured=is_env_var_configured(settings.azure_foundry_endpoint_env),
        ),
        auth_mode=settings.azure_foundry_auth_mode,
        api_version_configured=bool(settings.azure_foundry_api_version),
        roles={
            "proposer": DeploymentRoleStatus(
                env_ref=settings.azure_foundry_proposer_deployment_env,
                configured=is_env_var_configured(settings.azure_foundry_proposer_deployment_env),
                deployment_label="proposer",
            ),
            "reviewer": DeploymentRoleStatus(
                env_ref=settings.azure_foundry_reviewer_deployment_env,
                configured=is_env_var_configured(settings.azure_foundry_reviewer_deployment_env),
                deployment_label="reviewer",
            ),
            "assistant": DeploymentRoleStatus(
                env_ref=settings.azure_foundry_assistant_deployment_env,
                configured=is_env_var_configured(settings.azure_foundry_assistant_deployment_env),
                deployment_label="assistant",
            ),
            "fallback": DeploymentRoleStatus(
                env_ref=settings.azure_foundry_fallback_deployment_env or "",
                configured=is_env_var_configured(settings.azure_foundry_fallback_deployment_env),
                deployment_label="fallback",
                enabled=settings.azure_foundry_fallback_enabled,
            ),
        },
    )

    allowed_source = _parse_allowed_paths(settings.allowed_source_roots)
    allowed_output = _parse_allowed_paths(settings.allowed_output_roots)
    default_hub = settings.default_ai_hub_path

    mistral = MistralProjection(
        provider=settings.mistral_provider,
        endpoint=EnvRefStatus(
            env_ref=settings.mistral_endpoint_env,
            configured=is_env_var_configured(settings.mistral_endpoint_env),
        ),
        reviewer_model_configured=is_env_var_configured(settings.mistral_reviewer_model_id_env),
        reviewer_model_env_ref=settings.mistral_reviewer_model_id_env,
    )

    local_mode = LocalModeProjection(
        enabled=settings.local_mode,
        allowed_source_roots=allowed_source,
        allowed_output_roots=allowed_output,
        default_ai_hub_path=redact_absolute_paths(default_hub) if default_hub else "",
    )

    return SettingsProjection(azure=azure, mistral=mistral, local_mode=local_mode)


def settings_projection_to_dict(projection: SettingsProjection) -> dict[str, Any]:
    """Convert a SettingsProjection to a safe dict for JSON responses."""
    result: dict[str, Any] = {
        "azure": {
            "profile_id": projection.azure.profile_id,
            "status": "configured" if projection.azure.endpoint.configured else "not_configured",
            "connection_configured": projection.azure.endpoint.configured,
            "api_version_configured": projection.azure.api_version_configured,
            "roles": {
                role_name: {
                    "configured": role.configured,
                    "enabled": role.enabled,
                }
                for role_name, role in projection.azure.roles.items()
            },
        },
        "local_mode": {
            "enabled": projection.local_mode.enabled,
            "allowed_source_roots": list(projection.local_mode.allowed_source_roots),
            "allowed_output_roots": list(projection.local_mode.allowed_output_roots),
            "default_ai_hub_path": projection.local_mode.default_ai_hub_path,
        },
    }
    if projection.mistral is not None:
        result["mistral"] = {
            "api_configured": projection.mistral.endpoint.configured,
            "reviewer_model_configured": projection.mistral.reviewer_model_configured,
        }
    return result


# ── Path display helpers for local mode ────────────────────────────


def redact_for_public_display(path: str) -> str:
    """Redact a path for public display in local operator mode.

    In local mode, absolute paths are shown with a redacted placeholder
    for the user prefix but the rest is visible (e.g., "[user-home]/apps").
    Paths that match forbidden patterns are fully redacted.
    """
    if contains_forbidden_path(path):
        return "[redacted-path]"
    return redact_absolute_paths(path)


def is_path_allowed(path: str, allowed_roots: tuple[str, ...]) -> bool:
    """Check if a local path is within the allowed roots."""
    resolved = Path(path).resolve()
    for root in allowed_roots:
        try:
            resolved.relative_to(Path(root).resolve())
        except ValueError:
            continue
        return True
    return False


# ── Internal helpers ────────────────────────────────────────────────


def _parse_allowed_paths(raw: str) -> tuple[str, ...]:
    """Parse a semicolon-or-comma-separated list of allowed paths."""
    if not raw:
        return ()
    parts = raw.replace(";", ",").split(",")
    return tuple(p.strip() for p in parts if p.strip())
