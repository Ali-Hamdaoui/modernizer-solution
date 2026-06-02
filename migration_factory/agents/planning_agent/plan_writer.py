from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from migration_factory.agents.planning_agent.paths import get_run_planning_dir
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.agents.planning_agent.unit_builder import MigrationUnit
from migration_factory.contracts.constants import SCHEMA_VERSION


@dataclass(frozen=True)
class MigrationPlanPayload:
    run_id: str
    profile: str
    source_stack: StackFingerprint
    target_stack: StackFingerprint
    risks: tuple[str, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    units: tuple[MigrationUnit, ...]
    strategy: str | None = None
    risk_level: str | None = None
    production_allowed: bool | None = None
    fallback_profile: str | None = None
    selected_route_id: str | None = None
    route_strategy: str | None = None
    route_risk_level: str | None = None
    route_production_allowed: bool | None = None
    recommended_intermediate: dict[str, str] | None = None
    selected_hops: tuple[dict[str, Any], ...] = ()
    tooling_versions: dict[str, str] | None = None
    framework_versions: dict[str, str] | None = None


def write_migration_plan(
    modernized_app_path: str,
    payload: MigrationPlanPayload,
) -> Path:
    planning_dir = get_run_planning_dir(modernized_app_path, payload.run_id)
    planning_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = planning_dir / "migration_plan.yaml"
    artifact_path.write_text(_render_plan_yaml(payload), encoding="utf-8")
    return artifact_path


def write_migration_units(
    modernized_app_path: str,
    run_id: str,
    units: tuple[MigrationUnit, ...],
) -> Path:
    planning_dir = get_run_planning_dir(modernized_app_path, run_id)
    planning_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = planning_dir / "migration_units.yaml"
    artifact_path.write_text(_render_units_yaml(run_id, units), encoding="utf-8")
    return artifact_path


def _render_plan_yaml(payload: MigrationPlanPayload) -> str:
    executable = not bool(payload.blockers)
    unit_refs = [unit.id for unit in payload.units]
    status = _status(payload.blockers, payload.warnings, payload.risks)
    risk = _risk(payload.blockers, payload.risks)

    lines: list[str] = [
        f"schema_version: {_yaml_quote(SCHEMA_VERSION)}",
        f"run_id: {_yaml_quote(payload.run_id)}",
        f"status: {_yaml_quote(status)}",
        f"risk: {_yaml_quote(risk)}",
        f"profile: {_yaml_quote(payload.profile)}",
        "source_stack:",
        f"  build_tool: {_yaml_scalar(payload.source_stack.build_tool)}",
        f"  java: {_yaml_scalar(payload.source_stack.java)}",
        f"  spring_boot: {_yaml_scalar(payload.source_stack.spring_boot)}",
        "target_stack:",
        f"  build_tool: {_yaml_scalar(payload.target_stack.build_tool)}",
        f"  java: {_yaml_scalar(payload.target_stack.java)}",
        f"  spring_boot: {_yaml_scalar(payload.target_stack.spring_boot)}",
        f"  spring_framework: {_yaml_scalar(payload.target_stack.spring_framework)}",
        f"executable: {'true' if executable else 'false'}",
        "requires_human_approval: true",
        "risks:",
    ]
    lines.extend(_yaml_list(payload.risks, indent=2))
    lines.append("blockers:")
    lines.extend(_yaml_list(payload.blockers, indent=2))
    lines.append("warnings:")
    lines.extend(_yaml_list(payload.warnings, indent=2))
    if payload.selected_route_id is not None:
        lines.append(f"selected_route_id: {_yaml_scalar(payload.selected_route_id)}")
        lines.append(f"route_strategy: {_yaml_scalar(payload.route_strategy)}")
        lines.append(f"route_risk_level: {_yaml_scalar(payload.route_risk_level)}")
        if payload.route_production_allowed is None:
            lines.append("production_allowed: null")
        else:
            lines.append(
                f"production_allowed: {'true' if payload.route_production_allowed else 'false'}"
            )
        lines.append("recommended_intermediate:")
        lines.extend(_yaml_mapping(payload.recommended_intermediate, indent=2))
        lines.append("selected_hops:")
        lines.extend(_yaml_nested_value(list(payload.selected_hops), indent=2))
    if any(
        value is not None
        for value in (
            payload.strategy,
            payload.risk_level,
            payload.production_allowed,
            payload.fallback_profile,
        )
    ):
        lines.append("profile_governance:")
        lines.append(f"  strategy: {_yaml_scalar(payload.strategy)}")
        lines.append(f"  risk_level: {_yaml_scalar(payload.risk_level)}")
        if payload.production_allowed is None:
            lines.append("  production_allowed: null")
        else:
            lines.append(
                f"  production_allowed: {'true' if payload.production_allowed else 'false'}"
            )
        lines.append(f"  fallback_profile: {_yaml_scalar(payload.fallback_profile)}")
    lines.append("tooling_versions:")
    lines.extend(_yaml_mapping(payload.tooling_versions, indent=2))
    lines.append("framework_versions:")
    lines.extend(_yaml_mapping(payload.framework_versions, indent=2))
    lines.append("unit_references:")
    lines.extend(_yaml_list(tuple(unit_refs), indent=2))
    lines.append("artifact_refs:")
    lines.append("  self: \"migration_plan.yaml\"")
    lines.append("  migration_units: \"migration_units.yaml\"")
    lines.append("  plan_summary: \"plan_summary.md\"")
    lines.append("  approval_request: \"approval_request.json\"")
    lines.append("")
    return "\n".join(lines)


def _render_units_yaml(run_id: str, units: tuple[MigrationUnit, ...]) -> str:
    lines: list[str] = [
        f"schema_version: {_yaml_quote(SCHEMA_VERSION)}",
        f"run_id: {_yaml_quote(run_id)}",
        "status: \"PASS\"",
        "artifact_refs:",
        "  self: \"migration_units.yaml\"",
        "  migration_plan: \"migration_plan.yaml\"",
        "units:",
    ]

    if not units:
        lines.append("  []")
        lines.append("")
        return "\n".join(lines)

    for unit in units:
        lines.append(f"  - id: {_yaml_quote(unit.id)}")
        lines.append(f"    goal: {_yaml_quote(unit.goal)}")
        lines.append("    tools:")
        lines.extend(_yaml_list(unit.tools, indent=6))
        lines.append("    validation:")
        lines.extend(_yaml_list(unit.validation, indent=6))
        lines.append(f"    writes_source: {'true' if unit.writes_source else 'false'}")
        lines.append(f"    required: {'true' if unit.required else 'false'}")
        lines.append(f"    java_home_env: {_yaml_scalar(unit.java_home_env)}")
        lines.append(f"    hop_id: {_yaml_scalar(unit.hop_id)}")
        lines.append("    expected_artifacts:")
        lines.extend(_yaml_list(unit.expected_artifacts, indent=6))
        lines.append(f"    rollback_strategy: {_yaml_quote(unit.rollback_strategy)}")
        lines.append(f"    blocking_gate: {_yaml_quote(unit.blocking_gate)}")
        lines.append("    assist_policy:")
        lines.append(
            "      copilot_sdk_allowed: "
            f"{'true' if unit.assist_policy.copilot_sdk_allowed else 'false'}"
        )
        lines.append(
            "      copilot_sdk_mode: "
            f"{_yaml_quote(unit.assist_policy.copilot_sdk_mode)}"
        )
        if unit.openrewrite:
            lines.append("    openrewrite:")
            for key in (
                "active_recipes",
                "recipe_artifacts",
                "apply_goal",
                "apply_maven_args",
                "analysis_preview_maven_args",
            ):
                value = unit.openrewrite.get(key)
                if value is None:
                    continue
                if isinstance(value, (list, tuple)):
                    lines.append(f"      {key}:")
                    lines.extend(_yaml_list(tuple(str(item) for item in value), indent=8))
                else:
                    lines.append(f"      {key}: {_yaml_quote(str(value))}")

    lines.append("")
    return "\n".join(lines)


def _yaml_list(values: tuple[str, ...], indent: int) -> list[str]:
    pad = " " * indent
    if not values:
        return [f"{pad}[]"]
    return [f"{pad}- {_yaml_quote(value)}" for value in values]


def _yaml_scalar(value: str | None) -> str:
    if value is None:
        return "null"
    return _yaml_quote(value)


def _yaml_mapping(values: dict[str, str] | None, indent: int) -> list[str]:
    pad = " " * indent
    if not values:
        return [f"{pad}{{}}"]
    return [f"{pad}{key}: {_yaml_quote(value)}" for key, value in values.items()]


def _yaml_nested_value(value: Any, indent: int) -> list[str]:
    pad = " " * indent
    if value is None:
        return [f"{pad}null"]
    if isinstance(value, bool):
        return [f"{pad}{'true' if value else 'false'}"]
    if isinstance(value, (str, int, float)):
        return [f"{pad}{_yaml_quote(str(value))}"]
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{{}}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{pad}{key}:")
                lines.extend(_yaml_nested_value(item, indent + 2))
            elif isinstance(item, bool):
                lines.append(f"{pad}{key}: {'true' if item else 'false'}")
            elif item is None:
                lines.append(f"{pad}{key}: null")
            else:
                lines.append(f"{pad}{key}: {_yaml_quote(str(item))}")
        return lines
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"{pad}[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list, tuple)):
                lines.append(f"{pad}-")
                lines.extend(_yaml_nested_value(item, indent + 2))
            elif isinstance(item, bool):
                lines.append(f"{pad}- {'true' if item else 'false'}")
            elif item is None:
                lines.append(f"{pad}- null")
            else:
                lines.append(f"{pad}- {_yaml_quote(str(item))}")
        return lines
    return [f"{pad}{_yaml_quote(str(value))}"]


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _status(blockers: tuple[str, ...], warnings: tuple[str, ...], risks: tuple[str, ...]) -> str:
    if blockers or any("[BLOCKER]" in risk for risk in risks):
        return "FAIL"
    if warnings or risks:
        return "WARNING"
    return "PASS"


def _risk(blockers: tuple[str, ...], risks: tuple[str, ...]) -> str:
    if blockers or any("[BLOCKER]" in risk for risk in risks):
        return "BLOCKED"
    if any("[HIGH]" in risk or "HIGH" in risk for risk in risks):
        return "HIGH"
    if any("[WARNING]" in risk or "MEDIUM" in risk for risk in risks):
        return "MEDIUM"
    return "LOW" if risks else "UNKNOWN"
