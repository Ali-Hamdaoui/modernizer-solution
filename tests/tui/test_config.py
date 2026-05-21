from pathlib import Path

import pytest

from migration_factory.tui import config as config_module
from migration_factory.tui.config import (
    ConfigError,
    TuiConfig,
    fill_config_from_environment,
    load_config,
    save_config,
)


def test_load_missing_config_returns_defaults(tmp_path: Path) -> None:
    assert load_config(tmp_path / "missing.json") == TuiConfig()


def test_save_and_load_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config = TuiConfig(
        legacy_app_path="/legacy",
        modernized_app_path="/modernized",
        ai_hub_path="/ai-hub",
        profile_id="java17",
        run_id="run-001",
        approved_by="ada",
    )

    save_config(config, config_path)

    assert load_config(config_path) == config


def test_load_corrupt_config_raises_config_error(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(config_path)


def test_save_config_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.json"
    calls: list[tuple[str, Path]] = []
    real_replace = config_module.os.replace

    def spy_replace(source: str, target: Path) -> None:
        calls.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(config_module.os, "replace", spy_replace)

    save_config(TuiConfig(run_id="run-001"), config_path)

    assert calls
    temp_path, target_path = calls[0]
    assert Path(temp_path).parent == tmp_path
    assert target_path == config_path
    assert load_config(config_path).run_id == "run-001"


def test_fill_config_from_environment_populates_empty_startup_fields() -> None:
    config, imported = fill_config_from_environment(
        TuiConfig(),
        environ={
            "LEGACY_APP": "/legacy",
            "MODERNIZED_APP": "/modernized",
            "AI_HUB": "/ai-hub",
            "PROFILE": "java17",
            "APPROVED_BY": "ada",
            "RUN_ID": "run-001",
            "MODE": "full_sandbox_migration",
            "JAVA8_HOME": "/java8",
            "JAVA21_HOME": "/java21",
            "JAVA_HOME": "/java21",
        },
        saved_config_exists=False,
    )

    assert config == TuiConfig(
        legacy_app_path="/legacy",
        modernized_app_path="/modernized",
        ai_hub_path="/ai-hub",
        profile_id="java17",
        approved_by="ada",
        run_id="run-001",
        mode="full_sandbox_migration",
        source_jdk_home="/java8",
        target_jdk_home="/java21",
        active_java_home="/java21",
    )
    assert set(imported) == {
        "legacy_app_path",
        "modernized_app_path",
        "ai_hub_path",
        "profile_id",
        "approved_by",
        "run_id",
        "mode",
        "source_jdk_home",
        "target_jdk_home",
        "active_java_home",
    }


def test_fill_config_from_environment_does_not_overwrite_saved_values() -> None:
    config, imported = fill_config_from_environment(
        TuiConfig(
            legacy_app_path="/saved-legacy",
            modernized_app_path="/saved-modernized",
            mode="read_only_assessment",
        ),
        environ={
            "LEGACY_APP": "/env-legacy",
            "MODERNIZED_APP": "/env-modernized",
            "AI_HUB": "/env-ai-hub",
            "MODE": "full_sandbox_migration",
        },
        saved_config_exists=True,
    )

    assert config.legacy_app_path == "/saved-legacy"
    assert config.modernized_app_path == "/saved-modernized"
    assert config.mode == "read_only_assessment"
    assert config.ai_hub_path == "/env-ai-hub"
    assert imported == ("ai_hub_path",)
