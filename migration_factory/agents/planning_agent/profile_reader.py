from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from migration_factory.agents.planning_agent.paths import get_ai_hub_profile_path


@dataclass(frozen=True)
class LoadedMigrationProfile:
    profile: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None
    errors: list[str] = field(default_factory=list)
    ok: bool = True


def load_migration_profile(
    ai_hub_path: str | Path, profile_id: str
) -> LoadedMigrationProfile:
    profile_path = get_ai_hub_profile_path(ai_hub_path, profile_id)
    errors: list[str] = []

    if not profile_path.exists():
        return LoadedMigrationProfile(
            profile={},
            path=profile_path,
            errors=[f"Profile not found: {profile_path}"],
            ok=False,
        )

    try:
        with profile_path.open("r", encoding="utf-8") as file_obj:
            loaded = yaml.safe_load(file_obj)
    except (OSError, yaml.YAMLError) as exc:
        return LoadedMigrationProfile(
            profile={},
            path=profile_path,
            errors=[f"Profile YAML failed to load: {exc}"],
            ok=False,
        )

    if not isinstance(loaded, dict) or not loaded:
        return LoadedMigrationProfile(
            profile={},
            path=profile_path,
            errors=["Profile YAML is empty or not object."],
            ok=False,
        )

    for field_name in ("rules",):
        if field_name not in loaded:
            errors.append(f"Profile missing required top-level field: {field_name}")

    has_source = isinstance(loaded.get("source"), dict)
    has_target = isinstance(loaded.get("target"), dict)
    has_routes = isinstance(loaded.get("routes"), list) and bool(loaded.get("routes"))

    if not has_routes:
        for field_name in ("source", "target"):
            if field_name not in loaded:
                errors.append(f"Profile missing required top-level field: {field_name}")
    elif not has_target:
        # Route-driven profiles may rely on per-route targets only.
        target = None
    else:
        target = loaded.get("target")

    if has_target:
        target = loaded.get("target")
        if not target.get("java"):
            errors.append("Profile target missing required value: java")
        if not target.get("spring_boot"):
            errors.append("Profile target missing required value: spring_boot")

        has_build_field = any(key in target for key in ("build", "build_tool", "buildTool"))
        if has_build_field:
            build_value = target.get("build") or target.get("build_tool") or target.get("buildTool")
            if not build_value:
                errors.append("Profile target build tool field present but empty.")
    elif not has_routes:
        errors.append("Profile target must be object.")

    if has_routes:
        for index, route in enumerate(loaded.get("routes") or []):
            if not isinstance(route, dict):
                errors.append(f"Profile route at index {index} must be object.")
                continue
            if not route.get("id"):
                errors.append(f"Profile route at index {index} missing required value: id")
            route_id = route.get("id", index)
            route_source = route.get("source")
            route_target = route.get("target")
            route_hops = route.get("hops")
            has_hops = isinstance(route_hops, list) and bool(route_hops)

            if has_hops:
                for hop_index, hop in enumerate(route_hops or []):
                    if not isinstance(hop, dict):
                        errors.append(f"Profile route {route_id} hop at index {hop_index} must be object.")
                        continue
                    if not hop.get("id"):
                        errors.append(f"Profile route {route_id} hop at index {hop_index} missing required value: id")
                    hop_source = hop.get("source")
                    if not isinstance(hop_source, dict):
                        errors.append(f"Profile route {route_id} hop {hop.get('id', hop_index)} source must be object.")
                    hop_target = hop.get("target")
                    if not isinstance(hop_target, dict):
                        errors.append(f"Profile route {route_id} hop {hop.get('id', hop_index)} target must be object.")
                        continue
                    if not hop_target.get("java"):
                        errors.append(
                            f"Profile route {route_id} hop {hop.get('id', hop_index)} target missing required value: java"
                        )
                    if not hop_target.get("spring_boot"):
                        errors.append(
                            f"Profile route {route_id} hop {hop.get('id', hop_index)} target missing required value: spring_boot"
                        )
            else:
                if not isinstance(route_source, dict):
                    errors.append(f"Profile route {route_id} source must be object.")
                if not isinstance(route_target, dict):
                    errors.append(f"Profile route {route_id} target must be object.")
            if isinstance(route_target, dict):
                if not route_target.get("java"):
                    errors.append(f"Profile route {route_id} target missing required value: java")
                if not route_target.get("spring_boot"):
                    errors.append(f"Profile route {route_id} target missing required value: spring_boot")

    return LoadedMigrationProfile(
        profile=loaded,
        path=profile_path,
        errors=errors,
        ok=not errors,
    )
