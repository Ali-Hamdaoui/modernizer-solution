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
        if override not in config.allowed_models:
            return CopilotModelResolutionResult(
                ok=False,
                model=None,
                source=None,
                errors=[f"Planning assist model unavailable or not allowed: {override}."],
            )
        return CopilotModelResolutionResult(
            ok=True,
            model=override,
            source="planning_model_override",
        )

    phase_overrides = config.phase_model_overrides or {}
    default_model = (
        phase_overrides.get(request.phase)
        or phase_overrides.get("planning")
        or request.model
        or config.default_model
        or ""
    ).strip()
    if default_model:
        if default_model not in config.allowed_models:
            return CopilotModelResolutionResult(
                ok=False,
                model=None,
                source=None,
                errors=[f"Planning assist model unavailable or not allowed: {default_model}."],
            )
        return CopilotModelResolutionResult(
            ok=True,
            model=default_model,
            source="phase_override" if default_model in phase_overrides.values() else "default_model",
        )

    return CopilotModelResolutionResult(
        ok=False,
        model=None,
        source=None,
        errors=["Planning assist model resolution failed: model is empty or missing."],
    )
