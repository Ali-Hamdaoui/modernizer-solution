"""F5-T14: Backend projection for repair proposal review — safe, redacted, checksum-bound.

Exposes repair proposal data for Cockpit/API without letting UI supply diffs
or execution details. Full diff loaded by backend artifact ref endpoint only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from migration_factory.control_tower.domain.checksums import sha256_canonical_json


FORBIDDEN_PROJECTION_KEYS: frozenset[str] = frozenset({
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "endpoint",
    "deployment",
    "env_ref",
    "filesystem_target",
    "user_supplied_file_path",
})


@dataclass(frozen=True)
class RepairProposalProjection:
    proposal_id: str = ""
    gate_id: str = ""
    job_id: str = ""
    stage_index: int = 0
    command_id: str = ""
    failure_source: str = ""
    failure_summary: str = ""
    error_summary: str = ""
    root_cause: str = ""
    fix_strategy: str = ""
    changed_files: tuple[str, ...] = ()
    diff_preview: str = ""
    reviewed_diff_artifact_ref: str = ""
    reviewed_diff_artifact_checksum: str = ""
    risk: str = ""
    confidence: float = 0.0
    reviewer_decision: str = ""
    reviewer_notes: tuple[str, ...] = ()
    policy_status: str = ""
    policy_reason: str = ""
    policy_checksum: str = ""
    gate_checksum: str = ""
    allowed_actions: tuple[str, ...] = ()
    context_pack_checksum: str = ""
    base_repo_state_checksum: str = ""
    primary_output_checksum: str = ""
    reviewer_output_checksum: str = ""
    cycle_number: int = 0
    remaining_attempts: int = 3
    deterministic_artifact_checksum: str = ""


def build_repair_projection_from_review_chain(
    *,
    proposal_id: str = "",
    gate_id: str = "",
    job_id: str = "",
    stage_index: int = 0,
    command_id: str = "",
    review_chain: dict[str, Any] | None = None,
    gate_checksum: str = "",
    allowed_actions: tuple[str, ...] = (),
    remaining_attempts: int = 3,
) -> RepairProposalProjection:
    chain = review_chain or {}
    return RepairProposalProjection(
        proposal_id=proposal_id,
        gate_id=gate_id,
        job_id=job_id,
        stage_index=stage_index,
        command_id=command_id,
        failure_source=str(chain.get("failure_source", "")),
        failure_summary=str(chain.get("failure_summary", "")),
        error_summary=str(chain.get("error_summary", chain.get("failure_summary", ""))),
        root_cause=str(chain.get("root_cause", "")),
        fix_strategy=str(chain.get("fix_strategy", "")),
        changed_files=tuple(chain.get("changed_files", ())),
        diff_preview=_safe_diff_preview(str(chain.get("diff_preview", ""))),
        reviewed_diff_artifact_ref=str(chain.get("final_artifact_ref", "")),
        reviewed_diff_artifact_checksum=str(chain.get("final_artifact_checksum", "")),
        risk=str(chain.get("risk", "")),
        confidence=float(chain.get("confidence", 0.0)),
        reviewer_decision=str(chain.get("reviewer_decision", "")),
        reviewer_notes=tuple(chain.get("reviewer_notes", ())),
        policy_status=str(chain.get("policy_status", chain.get("policy_validation_status", ""))),
        policy_reason=str(chain.get("policy_reason", "")),
        policy_checksum=str(chain.get("policy_validation_checksum", "")),
        gate_checksum=gate_checksum,
        allowed_actions=allowed_actions,
        context_pack_checksum=str(chain.get("context_pack_checksum", "")),
        base_repo_state_checksum=str(chain.get("base_repo_state_checksum", "")),
        primary_output_checksum=str(chain.get("primary_output_checksum", "")),
        reviewer_output_checksum=str(chain.get("reviewer_output_checksum", "")),
        cycle_number=int(chain.get("cycle_number", 0)),
        remaining_attempts=remaining_attempts,
        deterministic_artifact_checksum=str(chain.get("deterministic_artifact_checksum", "")),
    )


def _safe_diff_preview(diff: str, max_lines: int = 20) -> str:
    lines = diff.strip().splitlines()
    return "\n".join(lines[:max_lines])


def validate_projection_safety(projection: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    projection_dict = _to_dict(projection) if not isinstance(projection, dict) else projection
    for forbidden in FORBIDDEN_PROJECTION_KEYS:
        if forbidden in projection_dict and projection_dict[forbidden]:
            failures.append(f"forbidden key {forbidden!r} found in repair projection")
    return failures


def projection_to_safe_dict(projection: RepairProposalProjection) -> dict[str, Any]:
    result: dict[str, Any] = {
        "proposal_id": projection.proposal_id,
        "gate_id": projection.gate_id,
        "job_id": projection.job_id,
        "stage_index": projection.stage_index,
        "command_id": projection.command_id,
        "failure_source": projection.failure_source,
        "failure_summary": projection.failure_summary,
        "error_summary": projection.error_summary,
        "root_cause": projection.root_cause,
        "fix_strategy": projection.fix_strategy,
        "changed_files": list(projection.changed_files),
        "diff_preview": projection.diff_preview,
        "reviewed_diff_artifact_ref": projection.reviewed_diff_artifact_ref,
        "reviewed_diff_artifact_checksum": projection.reviewed_diff_artifact_checksum,
        "risk": projection.risk,
        "confidence": projection.confidence,
        "reviewer_decision": projection.reviewer_decision,
        "reviewer_notes": list(projection.reviewer_notes),
        "policy_status": projection.policy_status,
        "policy_reason": projection.policy_reason,
        "policy_checksum": projection.policy_checksum,
        "gate_checksum": projection.gate_checksum,
        "allowed_actions": list(projection.allowed_actions),
        "context_pack_checksum": projection.context_pack_checksum,
        "base_repo_state_checksum": projection.base_repo_state_checksum,
        "primary_output_checksum": projection.primary_output_checksum,
        "reviewer_output_checksum": projection.reviewer_output_checksum,
        "cycle_number": projection.cycle_number,
        "remaining_attempts": projection.remaining_attempts,
        "deterministic_artifact_checksum": projection.deterministic_artifact_checksum,
    }
    # Redact any forbidden fields that may have crept in
    for forbidden in FORBIDDEN_PROJECTION_KEYS:
        result.pop(forbidden, None)
    return result


def _to_dict(obj: Any) -> dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dataclass_fields__"):
        from dataclasses import asdict
        return asdict(obj)
    return {}
