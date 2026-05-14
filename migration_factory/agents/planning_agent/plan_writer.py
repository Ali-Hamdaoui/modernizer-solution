from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from migration_factory.agents.planning_agent.paths import get_run_planning_dir
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.agents.planning_agent.unit_builder import MigrationUnit


SCHEMA_VERSION = "1.0"


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


def write_migration_plan(
    modernized_app_path: str,
    payload: MigrationPlanPayload,
) -> Path:
    planning_dir = get_run_planning_dir(modernized_app_path, payload.run_id)
    planning_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = planning_dir / "migration_plan.yaml"
    artifact_path.write_text(_render_plan_yaml(payload), encoding="utf-8")
    return artifact_path


def _render_plan_yaml(payload: MigrationPlanPayload) -> str:
    executable = not bool(payload.blockers)
    unit_refs = [unit.id for unit in payload.units]

    lines: list[str] = [
        f"schema_version: {_yaml_quote(SCHEMA_VERSION)}",
        f"run_id: {_yaml_quote(payload.run_id)}",
        f"profile: {_yaml_quote(payload.profile)}",
        "source_stack:",
        f"  build_tool: {_yaml_scalar(payload.source_stack.build_tool)}",
        f"  java: {_yaml_scalar(payload.source_stack.java)}",
        f"  spring_boot: {_yaml_scalar(payload.source_stack.spring_boot)}",
        "target_stack:",
        f"  build_tool: {_yaml_scalar(payload.target_stack.build_tool)}",
        f"  java: {_yaml_scalar(payload.target_stack.java)}",
        f"  spring_boot: {_yaml_scalar(payload.target_stack.spring_boot)}",
        f"executable: {'true' if executable else 'false'}",
        "requires_human_approval: true",
        "risks:",
    ]
    lines.extend(_yaml_list(payload.risks, indent=2))
    lines.append("blockers:")
    lines.extend(_yaml_list(payload.blockers, indent=2))
    lines.append("warnings:")
    lines.extend(_yaml_list(payload.warnings, indent=2))
    lines.append("unit_references:")
    lines.extend(_yaml_list(tuple(unit_refs), indent=2))
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


def _yaml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
