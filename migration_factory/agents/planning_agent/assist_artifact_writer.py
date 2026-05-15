from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CopilotAssistArtifactPayload:
    run_id: str
    status: str
    provider: str | None = None
    auth: str | None = None
    model: str | None = None
    inputs_summary: dict[str, Any] = field(default_factory=dict)
    advisory_summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    failure_reason: str | None = None


def write_copilot_assist_artifact(
    modernized_app_path: str,
    payload: CopilotAssistArtifactPayload,
) -> None:
    planning_dir = Path(modernized_app_path) / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = planning_dir / "copilot_assist.json"
    artifact_body = {
        "schema_version": "1.0",
        "run_id": payload.run_id,
        "agent": "planning_agent",
        "phase": "planning",
        "status": payload.status,
        "provider": payload.provider,
        "auth": payload.auth,
        "model": payload.model,
        "inputs_summary": payload.inputs_summary,
        "advisory_summary": payload.advisory_summary,
        "warnings": payload.warnings,
        "error": payload.error,
        "failure_reason": payload.failure_reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    artifact_path.write_text(
        json.dumps(artifact_body, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
