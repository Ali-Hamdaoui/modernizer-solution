import os
from dataclasses import dataclass
from typing import Literal

AssistMode = Literal["assist_only"]
AssistProvider = Literal["github_copilot_sdk"]
CopilotSdkMode = Literal["suggestion_only"]


@dataclass(frozen=True)
class PlanningAssistConfig:
    enabled: bool = False
    provider: AssistProvider = "github_copilot_sdk"
    mode: AssistMode = "assist_only"
    direct_write: bool = False
    model_override: str | None = None


@dataclass(frozen=True)
class AssistPolicy:
    copilot_sdk_allowed: bool
    copilot_sdk_mode: CopilotSdkMode = "suggestion_only"


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


def build_assist_policy(config: PlanningAssistConfig | None = None) -> AssistPolicy:
    planning_config = config or load_planning_assist_config()
    return AssistPolicy(
        copilot_sdk_allowed=bool(planning_config.enabled),
        copilot_sdk_mode="suggestion_only",
    )
