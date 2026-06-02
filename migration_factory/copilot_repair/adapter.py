from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from migration_factory.copilot_repair.evidence_session import (
    create_evidence_session,
    finalize_evidence_session,
)
from migration_factory.copilot_repair.response_validator import (
    failed_response_payload,
    parse_copilot_stdout,
    validate_copilot_repair_response,
)


DENIED_FLAGS = {"--allow-all", "--allow-all-tools", "--allow-all-paths", "--allow-all-urls", "--yolo"}


def invoke_copilot_repair(
    *,
    repo_root: str | Path,
    run_dir: str | Path,
    run_id: str,
    request_payload: dict[str, Any],
    availability: dict[str, Any],
    model: str = "",
    timeout_seconds: int = 300,
    strict_containment: bool = True,
    executable: str = "copilot",
    run=subprocess.run,
) -> dict[str, Any]:
    failures_dir = Path(run_dir) / "failures"
    failures_dir.mkdir(parents=True, exist_ok=True)
    response_path = failures_dir / "copilot_repair_response.json"
    markdown_path = failures_dir / "repair_plan.md"

    if availability.get("status") != "AVAILABLE":
        payload = failed_response_payload(reason="Copilot repair proposal mode unavailable.")
        _write_response(response_path, markdown_path, payload)
        return {"status": "SKIPPED", "artifact_refs": {"copilot_repair_response": str(response_path), "repair_plan": str(markdown_path)}}

    session = create_evidence_session(
        repo_root=repo_root,
        run_dir=run_dir,
        run_id=run_id,
        evidence=request_payload,
    )
    command = _build_command(availability, model=model, executable=executable)
    if any(flag in command for flag in DENIED_FLAGS):
        payload = failed_response_payload(reason="Unsafe Copilot command flag requested.")
        _write_response(response_path, markdown_path, payload)
        return {"status": "FAILED", "artifact_refs": {"copilot_repair_response": str(response_path), "repair_plan": str(markdown_path)}}

    try:
        completed = run(
            command,
            cwd=str(session.session_dir),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        parsed, parse_errors = parse_copilot_stdout(completed.stdout or "")
        if parse_errors:
            payload = failed_response_payload(reason="; ".join(parse_errors), stdout=completed.stdout or "", stderr=completed.stderr or "")
        else:
            valid, validation_errors = validate_copilot_repair_response(parsed)
            payload = parsed if valid else failed_response_payload(reason="; ".join(validation_errors), stdout=completed.stdout or "", stderr=completed.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as exc:
        payload = failed_response_payload(reason=f"Copilot invocation failed: {exc}")
    finally:
        manifest = finalize_evidence_session(session.session_dir, strict=strict_containment)

    if strict_containment and manifest.get("unexpected_mutations"):
        payload = failed_response_payload(reason="Strict containment detected unexpected evidence session mutation.")
    _write_response(response_path, markdown_path, payload)
    return {
        "status": "USED" if not payload.get("status") else str(payload.get("status")),
        "artifact_refs": {
            "copilot_repair_response": str(response_path),
            "repair_plan": str(markdown_path),
            "copilot_evidence_manifest": str(session.manifest_path),
        },
    }


def _build_command(availability: dict[str, Any], *, model: str, executable: str) -> list[str]:
    supported = set(availability.get("supported_flags", []) or [])
    command = [executable]
    if "--prompt" in supported:
        command.extend(["--prompt", "Read evidence/copilot_repair_request.json and return only valid JSON matching the requested schema."])
    if "--silent" in supported:
        command.append("--silent")
    if "--no-ask-user" in supported:
        command.append("--no-ask-user")
    if "--no-custom-instructions" in supported:
        command.append("--no-custom-instructions")
    if "--no-remote" in supported:
        command.append("--no-remote")
    if "--disable-builtin-mcps" in supported:
        command.append("--disable-builtin-mcps")
    if model and "--model" in supported:
        command.extend(["--model", model])
    if "--agent" in supported:
        command.extend(["--agent", "ai-migration-repair"])
    if "--available-tools" in supported:
        command.append("--available-tools=skill")
    if "--deny-tool" in supported:
        command.append("--deny-tool=read,write,shell,url,memory")
    return command


def _write_response(response_path: Path, markdown_path: Path, payload: dict[str, Any]) -> None:
    response_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(payload), encoding="utf-8")


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Copilot Repair Plan",
        "",
        str(payload.get("repair_summary", "")),
        "",
        f"- Failure classification: {payload.get('failure_classification', '')}",
        f"- Confidence: {payload.get('confidence', '')}",
        f"- Security review required: {str(payload.get('security_review_required', False)).lower()}",
        "",
        "No patches were applied by this adapter.",
    ]
    limitations = payload.get("limitations")
    if isinstance(limitations, list) and limitations:
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {item}" for item in limitations if item)
    return "\n".join(lines) + "\n"
