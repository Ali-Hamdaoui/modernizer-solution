"""F5-T2: Repair context pack — checksum-bound input bundle for Primary Repair LLM.

Builds a model-safe RepairContextPack from failure evidence, job/command state,
upstream artifacts, prior repair attempts, reviewer notes, and user comments.
Redacts secrets, absolute paths, raw env, endpoints, deployments, raw commands,
and sandbox paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.repair_loop.failure_evidence import FailureEvidence


FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset({
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "endpoint",
    "deployment",
    "env_ref",
    "user_supplied_file_path",
    "filesystem_target",
})


@dataclass(frozen=True)
class RepairContextPack:
    job_id: str
    stage_index: int
    command_id: str
    failure_source: str
    failure_evidence_checksum: str
    source_profile: str = ""
    target_profile: str = ""
    accepted_analysis_checksum: str = ""
    accepted_planning_checksum: str = ""
    prior_proposal_checksums: tuple[str, ...] = ()
    prior_reviewer_notes: tuple[str, ...] = ()
    user_comments: str = ""
    changed_files: tuple[str, ...] = ()
    normalized_build_evidence: tuple[dict[str, Any], ...] = ()
    source_contexts: tuple[dict[str, Any], ...] = ()
    diff_generation_rules: tuple[str, ...] = ()
    safe_log_preview: str = ""
    base_repo_state_checksum: str = ""
    context_pack_checksum: str = ""
    prior_revision_ids: tuple[str, ...] = ()
    cycle_number: int = 0
    max_cycles: int = 3
    created_at: str = ""
    schema_version: str = "1.0.0"


def compute_context_pack_checksum(pack: RepairContextPack) -> str:
    payload: dict[str, Any] = {
        "job_id": pack.job_id,
        "stage_index": pack.stage_index,
        "command_id": pack.command_id,
        "failure_source": pack.failure_source,
        "failure_evidence_checksum": pack.failure_evidence_checksum,
        "source_profile": pack.source_profile,
        "target_profile": pack.target_profile,
        "accepted_analysis_checksum": pack.accepted_analysis_checksum,
        "accepted_planning_checksum": pack.accepted_planning_checksum,
        "prior_proposal_checksums": list(sorted(pack.prior_proposal_checksums)),
        "prior_reviewer_notes": list(pack.prior_reviewer_notes),
        "user_comments": pack.user_comments,
        "changed_files": list(sorted(pack.changed_files)),
        "normalized_build_evidence": list(pack.normalized_build_evidence),
        "source_contexts": list(pack.source_contexts),
        "diff_generation_rules": list(pack.diff_generation_rules),
        "safe_log_preview": pack.safe_log_preview,
        "base_repo_state_checksum": pack.base_repo_state_checksum,
        "prior_revision_ids": list(sorted(pack.prior_revision_ids)),
        "cycle_number": pack.cycle_number,
        "max_cycles": pack.max_cycles,
    }
    return sha256_canonical_json(payload)


def compute_base_repo_state_checksum(
    *,
    changed_files: tuple[str, ...] = (),
    file_checksums: dict[str, str] | None = None,
    source_profile: str = "",
    target_profile: str = "",
    accepted_artifact_checksums: tuple[str, ...] = (),
) -> str:
    payload: dict[str, Any] = {
        "changed_files": list(sorted(changed_files)),
        "file_checksums": dict(sorted((file_checksums or {}).items())),
        "source_profile": source_profile,
        "target_profile": target_profile,
        "accepted_artifact_checksums": list(sorted(accepted_artifact_checksums)),
    }
    return sha256_canonical_json(payload)


def _validate_context_forbidden_keys(pack: RepairContextPack) -> list[str]:
    failures: list[str] = []
    for forbidden in FORBIDDEN_CONTEXT_KEYS:
        if hasattr(pack, forbidden):
            value = getattr(pack, forbidden)
            if value:
                failures.append(f"forbidden key {forbidden!r} present in context pack")
    return failures


def build_repair_context_pack(
    *,
    failure_evidence: FailureEvidence,
    job_id: str = "",
    stage_index: int = 0,
    command_id: str = "",
    source_profile: str = "",
    target_profile: str = "",
    accepted_analysis_checksum: str = "",
    accepted_planning_checksum: str = "",
    prior_proposal_checksums: tuple[str, ...] | None = None,
    prior_reviewer_notes: tuple[str, ...] | None = None,
    user_comments: str = "",
    changed_files: tuple[str, ...] | None = None,
    normalized_build_evidence: tuple[dict[str, Any], ...] | None = None,
    source_contexts: tuple[dict[str, Any], ...] | None = None,
    diff_generation_rules: tuple[str, ...] | None = None,
    file_checksums: dict[str, str] | None = None,
    accepted_artifact_checksums: tuple[str, ...] | None = None,
    prior_revision_ids: tuple[str, ...] | None = None,
    cycle_number: int = 0,
    max_cycles: int = 3,
) -> RepairContextPack:
    resolved_job = job_id or failure_evidence.job_id
    resolved_stage = stage_index or failure_evidence.stage_index
    resolved_command = command_id or failure_evidence.command_id

    resolved_changed = tuple(changed_files) if changed_files else failure_evidence.changed_files
    resolved_profile_source = source_profile or failure_evidence.source_profile
    resolved_profile_target = target_profile or failure_evidence.target_profile

    base_repo_checksum = compute_base_repo_state_checksum(
        changed_files=resolved_changed,
        file_checksums=file_checksums,
        source_profile=resolved_profile_source,
        target_profile=resolved_profile_target,
        accepted_artifact_checksums=accepted_artifact_checksums or failure_evidence.accepted_artifact_checksums,
    )

    pack = RepairContextPack(
        job_id=resolved_job,
        stage_index=resolved_stage,
        command_id=resolved_command,
        failure_source=failure_evidence.failure_source.value,
        failure_evidence_checksum=failure_evidence.content_checksum,
        source_profile=resolved_profile_source,
        target_profile=resolved_profile_target,
        accepted_analysis_checksum=accepted_analysis_checksum,
        accepted_planning_checksum=accepted_planning_checksum,
        prior_proposal_checksums=tuple(sorted(prior_proposal_checksums or ())),
        prior_reviewer_notes=tuple(prior_reviewer_notes or ()),
        user_comments=user_comments,
        changed_files=resolved_changed,
        normalized_build_evidence=tuple(normalized_build_evidence or ()),
        source_contexts=tuple(source_contexts or ()),
        diff_generation_rules=tuple(diff_generation_rules or _default_diff_generation_rules()),
        safe_log_preview=failure_evidence.safe_log_preview,
        base_repo_state_checksum=base_repo_checksum,
        prior_revision_ids=tuple(sorted(prior_revision_ids or ())),
        cycle_number=cycle_number,
        max_cycles=max_cycles,
        created_at=utc_now_text(),
    )

    context_checksum = compute_context_pack_checksum(pack)
    return RepairContextPack(
        job_id=pack.job_id,
        stage_index=pack.stage_index,
        command_id=pack.command_id,
        failure_source=pack.failure_source,
        failure_evidence_checksum=pack.failure_evidence_checksum,
        source_profile=pack.source_profile,
        target_profile=pack.target_profile,
        accepted_analysis_checksum=pack.accepted_analysis_checksum,
        accepted_planning_checksum=pack.accepted_planning_checksum,
        prior_proposal_checksums=pack.prior_proposal_checksums,
        prior_reviewer_notes=pack.prior_reviewer_notes,
        user_comments=pack.user_comments,
        changed_files=pack.changed_files,
        normalized_build_evidence=pack.normalized_build_evidence,
        source_contexts=pack.source_contexts,
        diff_generation_rules=pack.diff_generation_rules,
        safe_log_preview=pack.safe_log_preview,
        base_repo_state_checksum=pack.base_repo_state_checksum,
        context_pack_checksum=context_checksum,
        prior_revision_ids=pack.prior_revision_ids,
        cycle_number=pack.cycle_number,
        max_cycles=pack.max_cycles,
        created_at=pack.created_at,
        schema_version=pack.schema_version,
    )


def is_context_pack_stale(
    pack: RepairContextPack,
    current_file_checksums: dict[str, str] | None = None,
    current_accepted_artifact_checksums: tuple[str, ...] | None = None,
) -> bool:
    new_repo_checksum = compute_base_repo_state_checksum(
        changed_files=pack.changed_files,
        file_checksums=current_file_checksums,
        source_profile=pack.source_profile,
        target_profile=pack.target_profile,
        accepted_artifact_checksums=current_accepted_artifact_checksums or (),
    )
    return new_repo_checksum != pack.base_repo_state_checksum


def context_pack_to_dict(pack: RepairContextPack) -> dict[str, Any]:
    return {
        "job_id": pack.job_id,
        "stage_index": pack.stage_index,
        "command_id": pack.command_id,
        "failure_source": pack.failure_source,
        "failure_evidence_checksum": pack.failure_evidence_checksum,
        "source_profile": pack.source_profile,
        "target_profile": pack.target_profile,
        "accepted_analysis_checksum": pack.accepted_analysis_checksum,
        "accepted_planning_checksum": pack.accepted_planning_checksum,
        "prior_proposal_checksums": list(pack.prior_proposal_checksums),
        "prior_reviewer_notes": list(pack.prior_reviewer_notes),
        "user_comments": pack.user_comments,
        "changed_files": list(pack.changed_files),
        "normalized_build_evidence": list(pack.normalized_build_evidence),
        "source_contexts": list(pack.source_contexts),
        "diff_generation_rules": list(pack.diff_generation_rules),
        "safe_log_preview": pack.safe_log_preview,
        "base_repo_state_checksum": pack.base_repo_state_checksum,
        "context_pack_checksum": pack.context_pack_checksum,
        "prior_revision_ids": list(pack.prior_revision_ids),
        "cycle_number": pack.cycle_number,
        "max_cycles": pack.max_cycles,
        "created_at": pack.created_at,
        "schema_version": pack.schema_version,
    }


def _default_diff_generation_rules() -> tuple[str, ...]:
    return (
        "The host runtime is Windows. Do not output absolute Windows paths or C:\\ paths.",
        "Use repo-relative POSIX-style paths only in unified diffs.",
        "Unified diff headers must use forward slashes: diff --git a/src/Foo.java b/src/Foo.java.",
        "Never include sandbox_path, target_path, argv, env, raw_command, API keys, endpoints, or local absolute paths in LLM output.",
        "Use only provided source context. Do not invent file bodies, placeholder lines, ellipses, or // interface methods in patches.",
        "Do not assume Jackson package family. Respect existing imports and the target profile; if tools.jackson.* is present, keep tools.jackson.*.",
    )
