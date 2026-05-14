import os
from dataclasses import dataclass, field
from typing import Literal

CopilotAuthMode = Literal["github_signed_in_user", "oauth_github_app", "unknown"]


@dataclass(frozen=True)
class CopilotAuthResult:
    ok: bool
    auth_mode: CopilotAuthMode
    token: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _first_present_env(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def resolve_copilot_auth() -> CopilotAuthResult:
    auth_mode_raw = os.getenv("MF_PLANNING_ASSIST_AUTH_MODE", "").strip().lower()
    auth_mode = auth_mode_raw or "github_signed_in_user"

    if auth_mode == "github_signed_in_user":
        return CopilotAuthResult(
            ok=True,
            auth_mode="github_signed_in_user",
            warnings=["Using signed-in GitHub user auth context."],
        )

    if auth_mode == "oauth_github_app":
        token = _first_present_env(
            (
                "MF_PLANNING_ASSIST_GITHUB_APP_TOKEN",
                "MF_PLANNING_ASSIST_TOKEN",
                "GITHUB_TOKEN",
                "GH_TOKEN",
            )
        )
        if not token:
            return CopilotAuthResult(
                ok=False,
                auth_mode="oauth_github_app",
                errors=["Missing GitHub app OAuth token for planning assist."],
            )
        return CopilotAuthResult(
            ok=True,
            auth_mode="oauth_github_app",
            token=token,
        )

    return CopilotAuthResult(
        ok=False,
        auth_mode="unknown",
        errors=[f"Unsupported planning assist auth mode: {auth_mode}."],
    )
