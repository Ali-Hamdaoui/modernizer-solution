"""Route-aware runtime profile resolution for DEMO3 V2 jobs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RouteRuntimeProfileUnavailableError(ValueError):
    """Raised when a persisted route has no concrete AI Hub runtime profile."""

    code = "ROUTE_RUNTIME_PROFILE_UNAVAILABLE"
    public_message = (
        "Route runtime profile is unavailable for the selected source/target profile."
    )

    def __init__(
        self,
        message: str,
        *,
        public_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.public_message = public_message or self.public_message


_ROUTE_RUNTIME_PROFILE_MAP: dict[tuple[str, str], str] = {
    # Exact route profiles that exist in the checked-in AI Hub.
    ("springboot-2.7-java11", "springboot-3.5-java17"): "springboot-2.7-to-3.5-java17",
    ("springboot-3.5-java17", "springboot-3.5-java21"): "springboot-3.5-java17-to-java21",
    ("springboot-3.5-java21", "springboot-4.0-java21"): "springboot-3.5-java21-to-4.0-java21",
    # Multi-stage routes reuse the first concrete route profile available in repo.
    ("springboot-2.7-java11", "springboot-3.5-java21"): "springboot-2.7-to-3.5-java17",
    ("springboot-2.7-java11", "springboot-4.0-java21"): "springboot-2.7-to-3.5-java17",
    ("springboot-3.5-java17", "springboot-4.0-java21"): "springboot-3.5-java17-to-java21",
}


def resolve_runtime_profile_for_route(source_profile: str, target_profile: str) -> str:
    """Resolve the backend-owned AI Hub profile for a persisted route."""
    source = str(source_profile or "").strip()
    target = str(target_profile or "").strip()
    if not source or not target:
        raise RouteRuntimeProfileUnavailableError(
            "ROUTE_RUNTIME_PROFILE_UNAVAILABLE: source_profile and target_profile are required"
        )

    profile_id = _ROUTE_RUNTIME_PROFILE_MAP.get((source, target))
    if profile_id is None:
        raise RouteRuntimeProfileUnavailableError(
            "ROUTE_RUNTIME_PROFILE_UNAVAILABLE: no runtime profile mapping exists for "
            f"source={source!r} target={target!r}"
        )
    return profile_id


def resolve_runtime_profile_for_run_configuration(run_configuration: Any) -> str:
    """Resolve a runtime profile from a persisted run-configuration record."""
    source_profile, target_profile = extract_profile_route(run_configuration)
    return resolve_runtime_profile_for_route(source_profile, target_profile)


def extract_profile_route(run_configuration: Any) -> tuple[str, str]:
    """Extract source/target profiles from a run-configuration-like object."""
    source_profile = ""
    target_profile = ""

    if isinstance(run_configuration, dict):
        source_profile = str(run_configuration.get("source_profile") or "").strip()
        target_profile = str(run_configuration.get("target_profile") or "").strip()
        if not (source_profile and target_profile):
            source_profile, target_profile = _extract_from_payload_json(run_configuration.get("payload_json"))
        return source_profile, target_profile

    source_profile = str(getattr(run_configuration, "source_profile", "") or "").strip()
    target_profile = str(getattr(run_configuration, "target_profile", "") or "").strip()
    if source_profile and target_profile:
        return source_profile, target_profile

    payload_json = getattr(run_configuration, "payload_json", "") or ""
    if payload_json:
        payload_source, payload_target = _extract_from_payload_json(payload_json)
        source_profile = source_profile or payload_source
        target_profile = target_profile or payload_target

    return source_profile, target_profile


def ensure_runtime_profile_available(ai_hub_path: str | Path, profile_id: str) -> Path:
    """Verify that the resolved runtime profile exists in the checked-in AI Hub."""
    profile_path = Path(ai_hub_path) / "profiles" / f"{profile_id}.yaml"
    if not profile_path.is_file():
        raise RouteRuntimeProfileUnavailableError(
            "ROUTE_RUNTIME_PROFILE_UNAVAILABLE: runtime profile file missing at "
            f"{profile_path}"
    )
    return profile_path


def public_runtime_profile_error_message(exc: BaseException) -> str:
    """Return a sanitized message safe for API and event surfaces."""
    if isinstance(exc, RouteRuntimeProfileUnavailableError):
        return exc.code
    return RouteRuntimeProfileUnavailableError.code


def _extract_from_payload_json(payload_json: Any) -> tuple[str, str]:
    if not isinstance(payload_json, str) or not payload_json.strip():
        return "", ""
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError, ValueError):
        return "", ""
    if not isinstance(payload, dict):
        return "", ""
    return (
        str(payload.get("source_profile") or "").strip(),
        str(payload.get("target_profile") or "").strip(),
    )
