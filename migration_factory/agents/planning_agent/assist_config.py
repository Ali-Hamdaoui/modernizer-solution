import os
from dataclasses import dataclass
from typing import Literal

AssistMode = Literal["assist_only"]
AssistProvider = Literal["github_copilot_sdk"]


@dataclass(frozen=True)
class PlanningAssistConfig:
    enabled: bool = False
    provider: AssistProvider = "github_copilot_sdk"
    mode: AssistMode = "assist_only"
    direct_write: bool = False
    model_override: str | None = None


def load_planning_assist_config() -> PlanningAssistConfig:
    enabled = os.getenv("MF_PLANNING_ASSIST_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    provider = os.getenv("MF_PLANNING_ASSIST_PROVIDER", "github_copilot_sdk").strip() or "github_copilot_sdk"
    mode = os.getenv("MF_PLANNING_ASSIST_MODE", "assist_only").strip() or "assist_only"
    direct_write = False
    model_override = os.getenv("MF_PLANNING_ASSIST_MODEL", "").strip() or None

    if provider != "github_copilot_sdk":
        provider = "github_copilot_sdk"
    if mode != "assist_only":
        mode = "assist_only"

    return PlanningAssistConfig(
        enabled=enabled,
        provider=provider,
        mode=mode,
        direct_write=direct_write,
        model_override=model_override,
    )
