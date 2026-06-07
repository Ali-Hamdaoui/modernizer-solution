from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from migration_factory.wave_planner.planner import DEFAULT_CONSUMER_COMMAND


def build_consumer_validation_config(
    *,
    migration_wave_plan_path: str | Path,
    output_dir: str | Path,
    project_id: str | None = None,
    coordinates: dict[str, str] | None = None,
    command_override: str | None = None,
) -> dict[str, Any]:
    plan_path = Path(migration_wave_plan_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    projects = list(payload.get("projects", []) or [])
    consumer_plan = list(payload.get("consumer_validation_plan", []) or [])
    cycles = list(payload.get("cycles", []) or [])
    warnings = list(payload.get("warnings", []) or [])

    selected = _select_project(projects, project_id=project_id, coordinates=coordinates or {})
    status = "READY"
    human_review_required = False
    selected_consumers: list[dict[str, Any]] = []
    selected_id = ""
    selected_path = ""
    selected_coordinates = {"groupId": "", "artifactId": "", "version": "", "packaging": ""}
    config_warnings = list(warnings)

    if cycles:
        human_review_required = True
        config_warnings.append("Wave plan contains internal dependency cycles; consumer validation selection requires human review.")

    if selected is None:
        status = "PROJECT_NOT_FOUND"
        human_review_required = True
        config_warnings.append("Selected migrated project was not found in migration wave plan.")
    else:
        selected_id = str(selected.get("project_id") or "")
        selected_path = str(selected.get("project_path") or "")
        selected_coordinates = dict(selected.get("coordinates") or selected_coordinates)
        consumers = _consumers_for_project(consumer_plan, selected_id)
        consumer_records = {str(project.get("project_id") or ""): project for project in projects if isinstance(project, dict)}
        command = str(command_override or _suggested_command(consumer_plan, selected_id) or DEFAULT_CONSUMER_COMMAND)
        for consumer_id in consumers:
            consumer = consumer_records.get(consumer_id, {})
            selected_consumers.append(
                {
                    "consumer_project_id": consumer_id,
                    "consumer_project_path": str(consumer.get("project_path") or ""),
                    "suggested_command": command,
                    "validation_reason": f"Internal dependency on migrated project {selected_id}.",
                }
            )
        if not selected_consumers:
            status = "NO_CONSUMERS_FOUND"

    config_payload = {
        "status": status,
        "human_review_required": human_review_required,
        "migrated_project_id": selected_id,
        "migrated_project_path": selected_path,
        "migrated_coordinates": selected_coordinates,
        "consumers": selected_consumers,
        "warnings": _dedupe_preserve_order(config_warnings),
    }
    json_path = output_root / "consumer_validation_config.json"
    json_path.write_text(json.dumps(config_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path = output_root / "consumer_validation_config_summary.md"
    summary_path.write_text(_build_summary(config_payload), encoding="utf-8")
    return {
        "config_path": str(json_path),
        "summary_path": str(summary_path),
        "payload": config_payload,
    }


def load_consumer_validation_gate_config(config_path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(config_path).expanduser().resolve().read_text(encoding="utf-8"))
    consumers = []
    for item in list(payload.get("consumers", []) or []):
        if not isinstance(item, dict):
            continue
        consumers.append(
            {
                "path": str(item.get("consumer_project_path") or ""),
                "command": str(item.get("suggested_command") or DEFAULT_CONSUMER_COMMAND),
            }
        )
    commands = [str(item.get("suggested_command") or "").strip() for item in list(payload.get("consumers", []) or []) if isinstance(item, dict)]
    shared_command = commands[0] if commands and len(set(commands)) == 1 else DEFAULT_CONSUMER_COMMAND
    return {
        "consumers": consumers,
        "consumer_command": shared_command,
    }


def _select_project(
    projects: list[Any],
    *,
    project_id: str | None,
    coordinates: dict[str, str],
) -> dict[str, Any] | None:
    if project_id:
        for project in projects:
            if isinstance(project, dict) and str(project.get("project_id") or "") == project_id:
                return project
    if coordinates:
        group_id = str(coordinates.get("groupId") or "")
        artifact_id = str(coordinates.get("artifactId") or "")
        version = str(coordinates.get("version") or "")
        for project in projects:
            if not isinstance(project, dict):
                continue
            candidate = dict(project.get("coordinates") or {})
            if str(candidate.get("groupId") or "") != group_id:
                continue
            if str(candidate.get("artifactId") or "") != artifact_id:
                continue
            if version and str(candidate.get("version") or "") != version:
                continue
            return project
    return None


def _consumers_for_project(consumer_validation_plan: list[Any], selected_project_id: str) -> list[str]:
    for item in consumer_validation_plan:
        if not isinstance(item, dict):
            continue
        if str(item.get("migrated_project") or "") != selected_project_id:
            continue
        return [str(value) for value in list(item.get("consumers", []) or [])]
    return []


def _suggested_command(consumer_validation_plan: list[Any], selected_project_id: str) -> str:
    for item in consumer_validation_plan:
        if not isinstance(item, dict):
            continue
        if str(item.get("migrated_project") or "") != selected_project_id:
            continue
        return str(item.get("suggested_command") or DEFAULT_CONSUMER_COMMAND)
    return DEFAULT_CONSUMER_COMMAND


def _build_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Consumer Validation Config Summary",
        "",
        f"- Status: {payload.get('status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Migrated Project: {payload.get('migrated_project_id', '')}",
        "",
    ]
    consumers = list(payload.get("consumers", []) or [])
    if consumers:
        lines.extend(["## Consumers", ""])
        for item in consumers:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- {item.get('consumer_project_id', '')}: "
                f"{item.get('consumer_project_path', '')} "
                f"[{item.get('suggested_command', '')}]"
            )
    else:
        lines.extend(["## Consumers", "", "- none"])
    warnings = list(payload.get("warnings", []) or [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).rstrip() + "\n"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped
