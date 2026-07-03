"""ModelRoleConfig abstraction — maps model roles to provider/model config loaded from env.

Provides `ModelRoleConfig` dataclass and `ModelRoleConfigLoader` that reads
AI_MIGRATION_* environment variables to configure model roles (main, reviewer,
fallback) independently of deployment specifics.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any


class ModelRoleConfigMissingError(Exception):
    """Raised when required config is missing for a role that is invoked."""


@dataclass(frozen=True)
class ModelRoleConfig:
    role: str
    provider_alias: str
    model_display_name: str
    deployment_or_model_id: str
    endpoint_type: str
    response_format: str
    max_input_tokens: int
    max_output_tokens: int
    reasoning_effort: str | None
    schema_name: str | None
    supports_json_schema: bool
    supports_json_object: bool
    supports_reasoning_effort: bool
    supports_temperature: bool
    timeout_seconds: int
    display_name_source: str

    def deployment_alias_hash(self) -> str:
        if not self.deployment_or_model_id:
            return ""
        return hashlib.sha256(
            self.deployment_or_model_id.encode("utf-8")
        ).hexdigest()[:16]


def _get_env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if val in ("1", "true", "yes"):
        return True
    if val in ("0", "false", "no"):
        return False
    return default


class ModelRoleConfigLoader:
    _PREFIX = "AI_MIGRATION"

    @classmethod
    def _read_role_env(cls, role: str) -> dict[str, Any]:
        upper = role.upper()
        prefix = f"{cls._PREFIX}_{upper}"

        deployment_or_model_id = os.environ.get(f"{prefix}_MODEL", "").strip()
        if not deployment_or_model_id:
            return {}

        raw_display = os.environ.get(f"{prefix}_MODEL_DISPLAY_NAME", "").strip()
        model_display_name = raw_display or f"{role.capitalize()} Model"

        raw_reasoning = os.environ.get(f"{prefix}_REASONING_EFFORT", "").strip()

        return {
            "role": role,
            "provider_alias": (
                os.environ.get(f"{prefix}_PROVIDER", "").strip()
                or "azure_openai"
            ),
            "model_display_name": model_display_name,
            "deployment_or_model_id": deployment_or_model_id,
            "endpoint_type": (
                os.environ.get(f"{prefix}_ENDPOINT_TYPE", "").strip()
                or "chat_completions"
            ),
            "response_format": (
                os.environ.get(f"{prefix}_RESPONSE_FORMAT", "").strip()
                or "text"
            ),
            "max_input_tokens": int(
                os.environ.get(f"{prefix}_MAX_INPUT_TOKENS", "50000").strip()
            ),
            "max_output_tokens": int(
                os.environ.get(f"{prefix}_MAX_OUTPUT_TOKENS", "20000").strip()
            ),
            "reasoning_effort": raw_reasoning or None,
            "schema_name": None,
            "supports_json_schema": _get_env_bool(
                f"{prefix}_SUPPORTS_JSON_SCHEMA", True
            ),
            "supports_json_object": _get_env_bool(
                f"{prefix}_SUPPORTS_JSON_OBJECT", True
            ),
            "supports_reasoning_effort": bool(raw_reasoning),
            "supports_temperature": _get_env_bool(
                f"{prefix}_SUPPORTS_TEMPERATURE", True
            ),
            "timeout_seconds": int(
                os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "30").strip()
            ),
            "display_name_source": "env",
        }

    @classmethod
    def load_role(cls, role: str) -> ModelRoleConfig:
        data = cls._read_role_env(role)
        if not data.get("deployment_or_model_id"):
            upper = role.upper()
            raise ModelRoleConfigMissingError(
                f"Model role '{role}' is not configured: "
                f"env var {cls._PREFIX}_{upper}_MODEL is not set or empty"
            )
        return ModelRoleConfig(**data)

    @classmethod
    def load_main(cls) -> ModelRoleConfig:
        return cls.load_role("main")

    @classmethod
    def load_reviewer(cls) -> ModelRoleConfig:
        return cls.load_role("reviewer")

    @classmethod
    def load_fallback(cls) -> ModelRoleConfig:
        return cls.load_role("fallback")

    @classmethod
    def try_load_role(cls, role: str) -> ModelRoleConfig | None:
        try:
            return cls.load_role(role)
        except ModelRoleConfigMissingError:
            return None
