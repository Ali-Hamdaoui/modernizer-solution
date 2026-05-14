from migration_factory.agents.planning_agent.assist_config import load_planning_assist_config


def test_load_planning_assist_config_defaults_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("MF_PLANNING_ASSIST_ENABLED", raising=False)
    monkeypatch.delenv("MF_PLANNING_ASSIST_PROVIDER", raising=False)
    monkeypatch.delenv("MF_PLANNING_ASSIST_MODE", raising=False)
    monkeypatch.delenv("MF_PLANNING_ASSIST_MODEL", raising=False)

    config = load_planning_assist_config()

    assert config.enabled is False
    assert config.provider == "github_copilot_sdk"
    assert config.mode == "assist_only"
    assert config.direct_write is False
    assert config.model_override is None


def test_load_planning_assist_config_model_override(monkeypatch) -> None:
    monkeypatch.setenv("MF_PLANNING_ASSIST_ENABLED", "true")
    monkeypatch.setenv("MF_PLANNING_ASSIST_MODEL", "gpt-4.1")

    config = load_planning_assist_config()

    assert config.enabled is True
    assert config.model_override == "gpt-4.1"
