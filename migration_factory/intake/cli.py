from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.readiness import generate_candidate_project_readiness_pack
from migration_factory.wave_planner import (
    build_consumer_validation_config,
    plan_migration_wave,
)


DEFAULT_CONSUMER_COMMAND = "mvn clean test"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.intake.cli",
        description="Generate pre-migration intake artifacts for one or more local Maven projects.",
    )
    parser.add_argument("--project", action="append", required=True, help="Local Maven project path. Repeat for multiple projects.")
    parser.add_argument("--project-id", action="append", default=[], help="Optional project id aligned by order with --project.")
    parser.add_argument("--output-dir", required=True, help="Directory for intake artifacts.")
    parser.add_argument("--profile", default="", help="Optional target profile id.")
    parser.add_argument("--generate-wave-plan", action="store_true", help="Force wave-plan generation even for single project.")
    parser.add_argument("--generate-consumer-configs", action="store_true", help="Generate consumer validation config per project when wave plan available.")
    parser.add_argument("--capability-inventory", default="", help="Optional existing factory capability inventory JSON path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        _run_intake(args)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


def _run_intake(args: argparse.Namespace) -> None:
    project_paths = [Path(path).expanduser().resolve() for path in list(args.project or [])]
    project_ids = list(args.project_id or [])
    if project_ids and len(project_ids) != len(project_paths):
        raise ValueError("--project-id count must match --project count when provided.")

    output_root = Path(str(args.output_dir)).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    capability_inventory_path = _ensure_capability_inventory(
        provided_path=str(args.capability_inventory or ""),
        output_root=output_root,
    )

    project_records = []
    for index, project_path in enumerate(project_paths):
        project_id = project_ids[index] if index < len(project_ids) and project_ids[index] else project_path.name
        project_records.append(
            {
                "project_id": project_id,
                "path": project_path,
            }
        )

    should_generate_wave = bool(args.generate_wave_plan or len(project_records) > 1)
    wave_result: dict[str, Any] | None = None
    if should_generate_wave:
        wave_result = plan_migration_wave(project_records, output_dir=output_root / "wave")

    readiness_results: list[dict[str, Any]] = []
    consumer_config_paths: dict[str, str] = {}
    warnings: list[str] = []
    for record in project_records:
        project_output = output_root / record["project_id"]
        readiness = generate_candidate_project_readiness_pack(
            candidate_project_path=record["path"],
            output_dir=project_output,
            project_id=record["project_id"],
            factory_capability_inventory_path=capability_inventory_path,
            migration_wave_plan_path=(wave_result or {}).get("report_path"),
            target_profile_id=str(args.profile or ""),
        )
        readiness_results.append(
            {
                "project_id": record["project_id"],
                "project_path": str(record["path"]),
                "readiness_status": readiness.payload["readiness_status"],
                "readiness_pack_path": str(readiness.report_path),
                "readiness_summary_path": str(readiness.summary_path),
                "warnings": list(readiness.payload.get("warnings", []) or []),
            }
        )
        warnings.extend(list(readiness.payload.get("warnings", []) or []))

        if args.generate_consumer_configs and wave_result:
            consumer_dir = project_output / "consumer-validation"
            config_result = build_consumer_validation_config(
                migration_wave_plan_path=wave_result["report_path"],
                project_id=record["project_id"],
                output_dir=consumer_dir,
            )
            consumer_config_paths[record["project_id"]] = str(config_result["config_path"])

    payload = {
        "projects_analyzed": readiness_results,
        "artifact_paths": {
            "factory_capability_inventory": str(capability_inventory_path),
            "factory_capability_summary": str(capability_inventory_path.with_name("factory_capability_summary.md")),
            "migration_wave_plan": str((wave_result or {}).get("report_path") or ""),
            "migration_wave_summary": str((wave_result or {}).get("summary_path") or ""),
        },
        "wave_order": list(((wave_result or {}).get("payload") or {}).get("migration_waves", []) or []),
        "consumer_validation_config_paths": consumer_config_paths,
        "warnings": _dedupe_preserve_order([warning for warning in warnings if warning]),
        "recommended_next_actions": _recommended_next_actions(readiness_results, wave_result, bool(args.generate_consumer_configs)),
    }
    index_path = output_root / "intake_index.json"
    summary_path = output_root / "intake_summary.md"
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    print(json.dumps({"intake_index": str(index_path), "intake_summary": str(summary_path)}, indent=2))


def _ensure_capability_inventory(*, provided_path: str, output_root: Path) -> Path:
    if provided_path:
        path = Path(provided_path).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"Capability inventory not found: {path}")
        return path
    result = export_factory_capability_inventory(output_dir=output_root / "factory-capabilities")
    return result.report_path


def _recommended_next_actions(
    readiness_results: list[dict[str, Any]],
    wave_result: dict[str, Any] | None,
    consumer_configs_enabled: bool,
) -> list[str]:
    actions: list[str] = []
    if wave_result:
        actions.append("Review migration wave order before starting sandbox migrations.")
    if any(result["readiness_status"] == "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION" for result in readiness_results):
        actions.append("Resolve human-review readiness items before launching sandbox migration.")
    if consumer_configs_enabled and wave_result:
        actions.append("Use generated consumer validation configs after successful producer/library migrations.")
    if not actions:
        actions.append("Readiness pack complete; candidate projects are ready for read-only assessment.")
    return actions


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Intake Summary",
        "",
        f"- Projects Analyzed: {len(list(payload.get('projects_analyzed', []) or []))}",
        "",
        "## Project Status",
        "",
    ]
    for item in list(payload.get("projects_analyzed", []) or []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('project_id', '')}: {item.get('readiness_status', '')}")
    wave_order = list(payload.get("wave_order", []) or [])
    if wave_order:
        lines.extend(["", "## Wave Order", ""])
        for index, wave in enumerate(wave_order, start=1):
            if isinstance(wave, list):
                lines.append(f"- Wave {index}: {', '.join(str(part) for part in wave)}")
    consumer_paths = dict(payload.get("consumer_validation_config_paths", {}) or {})
    if consumer_paths:
        lines.extend(["", "## Consumer Validation Configs", ""])
        for project_id, path in sorted(consumer_paths.items()):
            lines.append(f"- {project_id}: {path}")
    warnings = list(payload.get("warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    actions = list(payload.get("recommended_next_actions", []) or [])
    if actions:
        lines.extend(["", "## Recommended Next Actions", ""])
        lines.extend(f"- {action}" for action in actions)
    return "\n".join(lines).rstrip() + "\n"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
