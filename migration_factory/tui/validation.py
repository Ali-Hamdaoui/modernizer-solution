from __future__ import annotations

from dataclasses import dataclass

from migration_factory.orchestrator.preflight import (
    PreflightError,
    build_langgraph_config,
    validate_preflight,
)
from migration_factory.orchestrator.state import MigrationState, build_initial_state
from migration_factory.tui.config import TuiConfig


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str = ""
    state: MigrationState | None = None
    langgraph_config: dict | None = None


def validate_setup(config: TuiConfig) -> ValidationResult:
    state = build_initial_state(
        run_id=config.run_id,
        legacy_app_path=config.legacy_app_path,
        modernized_app_path=config.modernized_app_path,
        ai_hub_path=config.ai_hub_path,
        profile_id=config.profile_id,
        thread_id=config.run_id,
        mode=config.mode,
    )
    langgraph_config = build_langgraph_config(config.run_id)

    try:
        validate_preflight(state, langgraph_config)
    except PreflightError as exc:
        return ValidationResult(
            ok=False,
            message=str(exc),
            state=state,
            langgraph_config=langgraph_config,
        )

    return ValidationResult(ok=True, state=state, langgraph_config=langgraph_config)
