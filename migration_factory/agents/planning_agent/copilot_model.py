from dataclasses import dataclass, field

from migration_factory.agents.planning_agent.assist_config import PlanningAssistConfig
from migration_factory.contracts.planning_assist import PlanningAssistRequest


@dataclass(frozen=True)
class CopilotModelResolutionResult:
    ok: bool
    model: str | None
    source: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def resolve_copilot_model(
    request: PlanningAssistRequest, config: PlanningAssistConfig
) -> CopilotModelResolutionResult:
    override = (config.model_override or "").strip()
    if override:
        return CopilotModelResolutionResult(
            ok=True,
            model=override,
            source="planning_model_override",
        )

    default_model = (request.model or "").strip()
    if default_model:
        return CopilotModelResolutionResult(
            ok=True,
            model=default_model,
            source="default_model",
        )

    return CopilotModelResolutionResult(
        ok=False,
        model=None,
        source=None,
        errors=["Planning assist model resolution failed: model is empty or missing."],
    )
