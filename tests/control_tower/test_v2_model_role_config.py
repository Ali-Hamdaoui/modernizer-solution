"""Tests for ModelRoleConfig dataclass and ModelRoleConfigLoader.

Covers environment-based loading, defaults, missing config fail-closed,
deployment hash privacy, and multi-role loading.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from migration_factory.control_tower.application.v2_model_role_config import (
    ModelRoleConfig,
    ModelRoleConfigLoader,
    ModelRoleConfigMissingError,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _unset_ai_migration_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("AI_MIGRATION_MAIN_") or key.startswith("AI_MIGRATION_REVIEWER_") or key.startswith("AI_MIGRATION_FALLBACK_"):
            monkeypatch.delenv(key, raising=False)


# ── 1. test_main_role_loads_gpt5_mini_from_env ───────────────────────


class TestMainRole:
    def test_main_role_loads_gpt5_mini_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_PROVIDER", "azure_openai")
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL_DISPLAY_NAME", "GPT-5 mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_ENDPOINT_TYPE", "chat_completions")
        monkeypatch.setenv("AI_MIGRATION_MAIN_RESPONSE_FORMAT", "json_object")

        config = ModelRoleConfigLoader.load_main()

        assert config.role == "main"
        assert config.provider_alias == "azure_openai"
        assert config.deployment_or_model_id == "gpt-5-mini"
        assert config.model_display_name == "GPT-5 mini"
        assert config.endpoint_type == "chat_completions"
        assert config.response_format == "json_object"
        assert config.display_name_source == "env"

    def test_main_role_reasoning_effort_medium(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_REASONING_EFFORT", "medium")

        config = ModelRoleConfigLoader.load_main()

        assert config.reasoning_effort == "medium"
        assert config.supports_reasoning_effort is True

    def test_role_defaults_use_50k_input_20k_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-3")
        monkeypatch.setenv("AI_MIGRATION_FALLBACK_MODEL", "gpt-4o")

        main_config = ModelRoleConfigLoader.load_main()
        reviewer_config = ModelRoleConfigLoader.load_reviewer()
        fallback_config = ModelRoleConfigLoader.load_fallback()

        assert main_config.max_input_tokens == 50000
        assert main_config.max_output_tokens == 20000
        assert reviewer_config.max_input_tokens == 50000
        assert reviewer_config.max_output_tokens == 20000
        assert fallback_config.max_input_tokens == 50000
        assert fallback_config.max_output_tokens == 20000

    def test_display_name_not_hardcoded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-3")
        monkeypatch.setenv("AI_MIGRATION_FALLBACK_MODEL", "gpt-4o")

        main_config = ModelRoleConfigLoader.load_main()
        reviewer_config = ModelRoleConfigLoader.load_reviewer()
        fallback_config = ModelRoleConfigLoader.load_fallback()

        assert main_config.model_display_name == "Main Model"
        assert reviewer_config.model_display_name == "Reviewer Model"
        assert fallback_config.model_display_name == "Fallback Model"

    def test_missing_invoked_role_config_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _unset_ai_migration_env(monkeypatch)
        monkeypatch.delenv("AI_MIGRATION_MAIN_MODEL", raising=False)
        monkeypatch.delenv("AI_MIGRATION_REVIEWER_MODEL", raising=False)
        monkeypatch.delenv("AI_MIGRATION_FALLBACK_MODEL", raising=False)

        with pytest.raises(ModelRoleConfigMissingError) as exc_info:
            ModelRoleConfigLoader.load_main()
        assert "main" in str(exc_info.value)

        with pytest.raises(ModelRoleConfigMissingError) as exc_info:
            ModelRoleConfigLoader.load_reviewer()
        assert "reviewer" in str(exc_info.value)

        with pytest.raises(ModelRoleConfigMissingError) as exc_info:
            ModelRoleConfigLoader.load_fallback()
        assert "fallback" in str(exc_info.value)

    def test_try_load_role_returns_none_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _unset_ai_migration_env(monkeypatch)
        monkeypatch.delenv("AI_MIGRATION_MAIN_MODEL", raising=False)

        config = ModelRoleConfigLoader.try_load_role("main")
        assert config is None

    def test_deployment_or_model_id_is_hashed_for_public_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini-private")

        config = ModelRoleConfigLoader.load_main()

        expected_hash = hashlib.sha256("gpt-5-mini-private".encode("utf-8")).hexdigest()[:16]
        assert config.deployment_alias_hash() == expected_hash
        assert config.deployment_alias_hash() != "gpt-5-mini-private"

    def test_reviewer_role_loads_mistral_large_3_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_PROVIDER", "mistral")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "mistral-large-3")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL_DISPLAY_NAME", "Mistral Large 3")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_ENDPOINT_TYPE", "chat_completions")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_RESPONSE_FORMAT", "text")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_INPUT_TOKENS", "32000")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MAX_OUTPUT_TOKENS", "8000")

        config = ModelRoleConfigLoader.load_reviewer()

        assert config.role == "reviewer"
        assert config.provider_alias == "mistral"
        assert config.deployment_or_model_id == "mistral-large-3"
        assert config.model_display_name == "Mistral Large 3"
        assert config.endpoint_type == "chat_completions"
        assert config.response_format == "text"
        assert config.max_input_tokens == 32000
        assert config.max_output_tokens == 8000
        assert config.schema_name is None
        assert config.display_name_source == "env"

    def test_timeout_seconds_defaults_to_30(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")

        config = ModelRoleConfigLoader.load_main()
        assert config.timeout_seconds == 30

    def test_timeout_seconds_custom(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        monkeypatch.setenv("AI_MIGRATION_MAIN_TIMEOUT_SECONDS", "60")

        config = ModelRoleConfigLoader.load_main()
        assert config.timeout_seconds == 60

    def test_load_role_dispatches_correctly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "main-model")
        monkeypatch.setenv("AI_MIGRATION_REVIEWER_MODEL", "reviewer-model")
        monkeypatch.setenv("AI_MIGRATION_FALLBACK_MODEL", "fallback-model")

        main_config = ModelRoleConfigLoader.load_role("main")
        reviewer_config = ModelRoleConfigLoader.load_role("reviewer")
        fallback_config = ModelRoleConfigLoader.load_role("fallback")

        assert main_config.deployment_or_model_id == "main-model"
        assert reviewer_config.deployment_or_model_id == "reviewer-model"
        assert fallback_config.deployment_or_model_id == "fallback-model"

    def test_model_role_config_immutable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AI_MIGRATION_MAIN_MODEL", "gpt-5-mini")
        config = ModelRoleConfigLoader.load_main()

        with pytest.raises(AttributeError):
            config.role = "reviewer"  # type: ignore[misc]

    def test_empty_deployment_hash_is_empty_string(self) -> None:
        config = ModelRoleConfig(
            role="main",
            provider_alias="azure_openai",
            model_display_name="Test Model",
            deployment_or_model_id="",
            endpoint_type="chat_completions",
            response_format="text",
            max_input_tokens=50000,
            max_output_tokens=20000,
            reasoning_effort=None,
            schema_name=None,
            supports_json_schema=True,
            supports_json_object=True,
            supports_reasoning_effort=False,
            supports_temperature=True,
            timeout_seconds=30,
            display_name_source="test",
        )
        assert config.deployment_alias_hash() == ""
