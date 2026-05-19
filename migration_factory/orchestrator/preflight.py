from pathlib import Path

from migration_factory.orchestrator.state import (
    ORCHESTRATION_MODES,
    READ_ONLY_ASSESSMENT_MODE,
    MigrationState,
)


class PreflightError(ValueError):
    """Raised when orchestrator inputs are invalid before graph execution."""


def build_langgraph_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def validate_preflight(state: MigrationState, config: dict) -> None:
    run_id = state.get("run_id", "")
    if not run_id:
        raise PreflightError("run_id is required")

    if state.get("mode") not in ORCHESTRATION_MODES:
        raise PreflightError(
            f"mode must be {READ_ONLY_ASSESSMENT_MODE}: {state.get('mode')} "
            "(or full_sandbox_migration)"
        )

    legacy_app_path_value = state.get("legacy_app_path", "")
    legacy_app_path = Path(legacy_app_path_value)
    if not legacy_app_path_value:
        raise PreflightError("legacy_app_path not found")
    if not legacy_app_path.exists():
        raise PreflightError(f"legacy_app_path not found: {legacy_app_path}")

    modernized_app_path_value = state.get("modernized_app_path", "")
    if not modernized_app_path_value:
        raise PreflightError("modernized_app_path is required")
    modernized_app_path = Path(modernized_app_path_value)
    try:
        modernized_app_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PreflightError(
            f"modernized_app_path cannot be created: {modernized_app_path}"
        ) from exc

    ai_hub_path_value = state.get("ai_hub_path", "")
    ai_hub_path = Path(ai_hub_path_value)
    if not ai_hub_path_value:
        raise PreflightError("ai_hub_path not found")
    if not ai_hub_path.exists():
        raise PreflightError(f"ai_hub_path not found: {ai_hub_path}")

    profile_id = state.get("profile_id", "")
    profile_path = ai_hub_path / "profiles" / f"{profile_id}.yaml"
    if not profile_path.is_file():
        raise PreflightError(f"AI Hub profile not found: {profile_path}")

    thread_id = config.get("configurable", {}).get("thread_id")
    if thread_id != run_id:
        raise PreflightError(f"thread_id must match run_id: {run_id}")
