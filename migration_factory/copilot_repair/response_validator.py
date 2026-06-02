from __future__ import annotations

import json
from typing import Any

from migration_factory.contracts.schema_validation import validate_against_schema


def parse_copilot_stdout(stdout: str) -> tuple[dict[str, Any] | None, list[str]]:
    text = stdout.strip()
    if not text:
        return None, ["Copilot stdout was empty."]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"Copilot stdout was not valid JSON: {exc}"]
    if not isinstance(payload, dict):
        return None, ["Copilot JSON response must be an object."]
    return payload, []


def validate_copilot_repair_response(payload: Any) -> tuple[bool, list[str]]:
    if not isinstance(payload, dict):
        return False, ["response must be a JSON object"]
    errors = list(validate_against_schema(payload, "copilot_repair_response.schema.json"))
    checklist = payload.get("wrapper_checklist")
    if isinstance(checklist, dict):
        for key, expected in {
            "legacy_source_not_modified": True,
            "sandbox_only": True,
            "no_deployment": True,
            "no_pr_creation": True,
            "no_security_weakening": True,
            "h2_only_runtime_scope": True,
            "sql_server_out_of_scope": True,
            "endpoint_smoke_out_of_scope": True,
        }.items():
            if checklist.get(key) is not expected:
                errors.append(f"wrapper_checklist.{key}: must be true")
    return not errors, errors


def failed_response_payload(*, reason: str, stdout: str = "", stderr: str = "") -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "repair_summary": "Copilot repair proposal was not accepted.",
        "failure_classification": "UNKNOWN_MIGRATION_FAILURE",
        "skills_claimed": [],
        "wrapper_checklist": {
            "legacy_source_not_modified": True,
            "sandbox_only": True,
            "no_deployment": True,
            "no_pr_creation": True,
            "no_security_weakening": True,
            "h2_only_runtime_scope": True,
            "sql_server_out_of_scope": True,
            "endpoint_smoke_out_of_scope": True,
        },
        "patch_proposals": [],
        "security_review_required": False,
        "confidence": "LOW",
        "refusals": [reason],
        "limitations": [_tail(stdout), _tail(stderr)],
        "status": "FAILED",
    }


def _tail(text: str, max_chars: int = 1000) -> str:
    clean = str(text or "")
    return clean[-max_chars:] if len(clean) > max_chars else clean
