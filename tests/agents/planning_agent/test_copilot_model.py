from migration_factory.agents.planning_agent.assist_config import PlanningAssistConfig
from migration_factory.agents.planning_agent.copilot_model import resolve_copilot_model
from migration_factory.contracts.planning_assist import PlanningAssistRequest


def _request(model: str | None) -> PlanningAssistRequest:
    return PlanningAssistRequest(
        run_id="r1",
        agent="planning_agent",
        phase="planning",
        model=model,
        prompt="review",
        context={"migration_units": []},
    )


def test_resolve_copilot_model_prefers_planning_override() -> None:
    result = resolve_copilot_model(
        request=_request("default-model"),
        config=PlanningAssistConfig(
            enabled=True,
            model_override="override-model",
            allowed_models=("default-model", "override-model"),
        ),
    )

    assert result.ok is True
    assert result.model == "override-model"
    assert result.source == "planning_model_override"
    assert result.errors == []


def test_resolve_copilot_model_falls_back_to_default_model() -> None:
    result = resolve_copilot_model(
        request=_request("default-model"),
        config=PlanningAssistConfig(
            enabled=True,
            model_override=None,
            allowed_models=("default-model",),
        ),
    )

    assert result.ok is True
    assert result.model == "default-model"
    assert result.source == "default_model"
    assert result.errors == []


def test_resolve_copilot_model_empty_missing_returns_controlled_failure() -> None:
    result = resolve_copilot_model(
        request=_request(None),
        config=PlanningAssistConfig(enabled=True, model_override="   ", default_model=""),
    )

    assert result.ok is False
    assert result.model is None
    assert result.source is None
    assert result.errors == [
        "Planning assist model resolution failed: model is empty or missing."
    ]
