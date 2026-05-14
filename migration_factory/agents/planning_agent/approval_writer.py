from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from migration_factory.agents.planning_agent.paths import get_run_planning_dir
from migration_factory.agents.planning_agent.unit_builder import MigrationUnit


DECISION_OPTIONS = (
    "approve",
    "approve_with_changes",
    "reject",
    "replan",
)


@dataclass(frozen=True)
class ApprovalRequestPayload:
    run_id: str
    summary: str
    units: tuple[MigrationUnit, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def write_approval_request(
    modernized_app_path: str,
    payload: ApprovalRequestPayload,
) -> Path:
    planning_dir = get_run_planning_dir(modernized_app_path, payload.run_id)
    planning_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = planning_dir / "approval_request.json"
    artifact_path.write_text(
        json.dumps(_build_payload(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact_path


def _build_payload(payload: ApprovalRequestPayload) -> dict[str, object]:
    return {
        "run_id": payload.run_id,
        "requires_human_approval": True,
        "decision_options": list(DECISION_OPTIONS),
        "summary": payload.summary,
        "units_to_execute": [unit.id for unit in payload.units],
        "blockers": list(payload.blockers),
        "warnings": list(payload.warnings),
    }
