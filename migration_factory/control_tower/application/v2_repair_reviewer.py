"""Read-only reviewer over R7D evidence-bound repair drafts."""

from __future__ import annotations

from typing import Any, Protocol

from migration_factory.control_tower.domain.checksums import sha256_canonical_json


SUPPORTED_FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
REVIEWER_KIND = "deterministic_local"
REVIEWER_ORIGIN = "backend_evidence_bound"


class RepairDraftReviewerProtocol(Protocol):
    """Future LLM and deterministic reviewers must share this envelope."""

    def review(
        self,
        classification: dict[str, Any] | None,
        stage_evidence: dict[str, Any] | None,
        migration_memory: dict[str, Any] | None,
        repair_proposal_draft: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...


class FutureLlmRepairDraftReviewer:
    """Placeholder only. R7E must not call a live LLM/API provider."""

    def review(
        self,
        classification: dict[str, Any] | None,
        stage_evidence: dict[str, Any] | None,
        migration_memory: dict[str, Any] | None,
        repair_proposal_draft: dict[str, Any] | None,
    ) -> dict[str, Any]:
        _ = classification, stage_evidence, migration_memory, repair_proposal_draft
        return _with_review_checksum(_base_result({}, {}, {}, {}, status="unavailable", verdict="rejected", reasons=[
            "future_llm_reviewer_not_enabled_in_R7E",
        ]))


class DeterministicRepairDraftReviewer:
    """Deterministic safety fallback for non-actionable draft review."""

    def review(
        self,
        classification: dict[str, Any] | None,
        stage_evidence: dict[str, Any] | None,
        migration_memory: dict[str, Any] | None,
        repair_proposal_draft: dict[str, Any] | None,
    ) -> dict[str, Any]:
        classification = classification if isinstance(classification, dict) else {}
        stage_evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
        migration_memory = migration_memory if isinstance(migration_memory, dict) else {}
        draft = repair_proposal_draft if isinstance(repair_proposal_draft, dict) else {}

        gate = str(classification.get("governance_gate_type") or draft.get("governance_gate_type") or "")
        blocked_reason = str(classification.get("repair_blocked_reason") or draft.get("blocked_reason") or "")
        if gate == "human_review_gate" or draft.get("proposal_status") == "blocked_human_review_gate":
            return _with_review_checksum(_base_result(
                classification,
                stage_evidence,
                migration_memory,
                draft,
                status="not_reviewable_blocked_human_gate",
                verdict="blocked",
                reasons=[blocked_reason or "human_review_gate_no_auto_repair"],
            ))

        reasons = _review_rejection_reasons(classification, migration_memory, draft)
        verdict = "rejected" if reasons else "accepted_for_future_apply_gate"
        return _with_review_checksum(_base_result(
            classification,
            stage_evidence,
            migration_memory,
            draft,
            status="reviewed_non_actionable",
            verdict=verdict,
            reasons=reasons,
        ))


def review_stage_repair_draft(
    classification: dict[str, Any] | None,
    stage_evidence: dict[str, Any] | None,
    migration_memory: dict[str, Any] | None,
    repair_proposal_draft: dict[str, Any] | None,
) -> dict[str, Any]:
    """Review a non-actionable R7D draft with deterministic fallback."""

    return DeterministicRepairDraftReviewer().review(
        classification,
        stage_evidence,
        migration_memory,
        repair_proposal_draft,
    )


def _base_result(
    classification: dict[str, Any],
    stage_evidence: dict[str, Any],
    migration_memory: dict[str, Any],
    draft: dict[str, Any],
    *,
    status: str,
    verdict: str,
    reasons: list[str],
) -> dict[str, Any]:
    reviewed_family = str(draft.get("supported_family") or "")
    evidence_pack_id = str(draft.get("evidence_pack_id") or classification.get("evidence_pack_id") or stage_evidence.get("evidence_pack_id") or "")
    evidence_pack_checksum = str(draft.get("evidence_pack_checksum") or classification.get("evidence_pack_checksum") or stage_evidence.get("evidence_pack_checksum") or "")
    target_files = [str(item) for item in list(draft.get("target_files") or [])[:4]]
    target_file_checksums = {
        str(key): str(value)
        for key, value in (draft.get("target_file_checksums") or {}).items()
        if isinstance(key, str)
    } if isinstance(draft.get("target_file_checksums"), dict) else {}
    memory_authority = str(migration_memory.get("authority_level") or "advisory_only")
    checksum_fields = _checksum_fields(draft, applicable=status != "not_reviewable_blocked_human_gate")
    result = {
        "review_status": status,
        "verdict": verdict,
        "reviewer_kind": REVIEWER_KIND,
        "reviewer_origin": REVIEWER_ORIGIN,
        "llm_invoked": False,
        "future_llm_reviewer_compatible": True,
        "reviewed_family": reviewed_family,
        "failure_type": str(draft.get("failure_type") or classification.get("failure_type") or ""),
        "classification_status": str(draft.get("classification_status") or classification.get("classification_status") or ""),
        "governance_gate_type": str(draft.get("governance_gate_type") or classification.get("governance_gate_type") or ""),
        "stage_index": draft.get("stage_index") if draft.get("stage_index") is not None else classification.get("stage_index"),
        "source_boot_version": str(draft.get("source_boot_version") or classification.get("source_boot_version") or stage_evidence.get("source_boot_version") or ""),
        "target_boot_version": str(draft.get("target_boot_version") or classification.get("target_boot_version") or stage_evidence.get("target_boot_version") or ""),
        "source_java_version": str(draft.get("source_java_version") or classification.get("source_java_version") or stage_evidence.get("source_java_version") or ""),
        "target_java_version": str(draft.get("target_java_version") or classification.get("target_java_version") or stage_evidence.get("target_java_version") or ""),
        "evidence_pack_id": evidence_pack_id,
        "evidence_pack_checksum": evidence_pack_checksum,
        "memory_query_signature": str(draft.get("memory_query_signature") or (migration_memory.get("query_signature") or "")),
        "retrieved_memory_case_ids": [str(item) for item in list(draft.get("retrieved_memory_case_ids") or migration_memory.get("retrieved_case_ids") or [])[:8]],
        "target_files": target_files,
        "target_file_checksums": target_file_checksums,
        "proposed_diff_checksum": str(draft.get("proposed_diff_checksum") or ""),
        "proposal_checksum": str(draft.get("proposal_checksum") or ""),
        **checksum_fields,
        "review_checksum": "",
        "required_followup_gate": "future_human_approval_and_backend_apply_gate",
        "sandbox_only": True,
        "memory_authority": "advisory_only" if memory_authority != "advisory_only" else memory_authority,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
        "reasons": reasons,
        "safety_warnings": [
            "Reviewer verdict is non-actionable in R7E.",
            "Apply remains disabled until a later governed milestone.",
            "Future LLM reviewer must use the same backend-validated envelope.",
        ],
    }
    return _clamp_no_authority(result)


def _review_rejection_reasons(
    classification: dict[str, Any],
    migration_memory: dict[str, Any],
    draft: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    _require(draft.get("proposal_status") == "drafted_non_actionable", "proposal_status_not_drafted_non_actionable", reasons)
    _require(draft.get("proposer_origin") == "backend_evidence_bound", "proposer_origin_not_backend_evidence_bound", reasons)
    _require(draft.get("supported_family") == SUPPORTED_FAMILY, "unsupported_family", reasons)
    _require(draft.get("failure_type") == SUPPORTED_FAMILY, "failure_type_mismatch", reasons)
    _require(draft.get("classification_status") == "known_family_candidate", "classification_status_not_known_family_candidate", reasons)
    _require(draft.get("governance_gate_type") == "future_deterministic_candidate", "governance_gate_type_not_future_deterministic_candidate", reasons)
    _require(bool(draft.get("evidence_pack_checksum")), "evidence_pack_checksum_missing", reasons)
    _require(bool(draft.get("memory_query_signature")), "memory_query_signature_missing", reasons)
    _require(bool(draft.get("proposal_checksum")), "proposal_checksum_missing", reasons)
    _require(bool(draft.get("proposed_diff_checksum")), "proposed_diff_checksum_missing", reasons)
    checksum_fields = _checksum_fields(draft, applicable=True)
    if checksum_fields["declared_diff_checksum"] and not checksum_fields["diff_checksum_match"]:
        _reject(True, "proposed_diff_checksum_mismatch", reasons)
    if checksum_fields["declared_proposal_checksum"] and not checksum_fields["proposal_checksum_match"]:
        _reject(True, "proposal_checksum_mismatch", reasons)
    target_files = list(draft.get("target_files") or [])
    _require(len(target_files) == 1, "target_file_count_not_one", reasons)
    target = str(target_files[0]) if len(target_files) == 1 else ""
    target_checksums = draft.get("target_file_checksums") if isinstance(draft.get("target_file_checksums"), dict) else {}
    _require(bool(target and target_checksums.get(target)), "target_file_checksum_missing", reasons)
    _require(_safe_relative_path(target), "target_file_untrusted", reasons)

    diff = str(draft.get("proposed_diff_preview") or "")
    _require(_has_removed_initmocks(diff), "initmocks_removal_missing", reasons)
    _require(_has_added_openmocks(diff), "openmocks_addition_missing", reasons)
    _reject("powermock" in diff.lower(), "powermock_change_detected", reasons)
    _reject(_contains_dependency_change(diff), "dependency_change_detected", reasons)
    _reject(_contains_shell_command(diff), "shell_command_detected", reasons)

    authority_flags = {
        "apply_enabled": draft.get("apply_enabled"),
        "approval_enabled": draft.get("approval_enabled"),
        "repair_enabled": draft.get("repair_enabled"),
        "downstream_start_allowed": draft.get("downstream_start_allowed"),
        "legacy_mutation_allowed": draft.get("legacy_mutation_allowed"),
    }
    for field, value in authority_flags.items():
        _require(value is False, f"{field}_not_disabled", reasons)

    _require(classification.get("repair_enabled") is False, "classification_repair_enabled_not_disabled", reasons)
    if migration_memory:
        _require(str(migration_memory.get("authority_level") or "advisory_only") == "advisory_only", "memory_authority_not_advisory", reasons)
        _require(migration_memory.get("repair_enabled") is False, "memory_repair_enabled_not_disabled", reasons)
        _require(migration_memory.get("memory_can_apply") is False, "memory_can_apply_not_disabled", reasons)
        _require(migration_memory.get("memory_can_approve") is False, "memory_can_approve_not_disabled", reasons)
        _require(migration_memory.get("memory_can_start_downstream") is False, "memory_can_start_downstream_not_disabled", reasons)
    return reasons


def _checksum_fields(draft: dict[str, Any], *, applicable: bool) -> dict[str, Any]:
    declared_diff = str(draft.get("proposed_diff_checksum") or "")
    declared_proposal = str(draft.get("proposal_checksum") or "")
    if not applicable:
        return {
            "declared_diff_checksum": declared_diff,
            "recomputed_diff_checksum": "",
            "diff_checksum_match": False,
            "declared_proposal_checksum": declared_proposal,
            "recomputed_proposal_checksum": "",
            "proposal_checksum_match": False,
            "checksum_verification_status": "not_applicable",
        }
    diff = str(draft.get("proposed_diff_preview") or "")
    recomputed_diff = f"sha256:{sha256_canonical_json({'diff': diff})}" if diff else ""
    draft_without_checksum = {key: value for key, value in draft.items() if key != "proposal_checksum"}
    recomputed_proposal = f"sha256:{sha256_canonical_json(draft_without_checksum)}" if draft else ""
    diff_match = bool(declared_diff and recomputed_diff and declared_diff == recomputed_diff)
    proposal_match = bool(declared_proposal and recomputed_proposal and declared_proposal == recomputed_proposal)
    status = "verified" if diff_match and proposal_match else "failed"
    return {
        "declared_diff_checksum": declared_diff,
        "recomputed_diff_checksum": recomputed_diff,
        "diff_checksum_match": diff_match,
        "declared_proposal_checksum": declared_proposal,
        "recomputed_proposal_checksum": recomputed_proposal,
        "proposal_checksum_match": proposal_match,
        "checksum_verification_status": status,
    }


def _with_review_checksum(result: dict[str, Any]) -> dict[str, Any]:
    result = _clamp_no_authority(result)
    body = {key: value for key, value in result.items() if key != "review_checksum"}
    result["review_checksum"] = f"sha256:{sha256_canonical_json(body)}"
    return result


def _clamp_no_authority(result: dict[str, Any]) -> dict[str, Any]:
    result["apply_enabled"] = False
    result["approval_enabled"] = False
    result["repair_enabled"] = False
    result["llm_invoked"] = False
    result["sandbox_only"] = True
    result["legacy_mutation_allowed"] = False
    result["downstream_start_allowed"] = False
    result["memory_can_apply"] = False
    result["memory_can_approve"] = False
    result["memory_can_start_downstream"] = False
    result["memory_authority"] = "advisory_only"
    return result


def _require(condition: bool, reason: str, reasons: list[str]) -> None:
    if not condition and reason not in reasons:
        reasons.append(reason)


def _reject(condition: bool, reason: str, reasons: list[str]) -> None:
    if condition and reason not in reasons:
        reasons.append(reason)


def _has_removed_initmocks(diff: str) -> bool:
    return any(
        line.startswith("-")
        and not line.startswith("---")
        and "MockitoAnnotations.initMocks" in line
        for line in diff.splitlines()
    )


def _has_added_openmocks(diff: str) -> bool:
    return any(
        line.startswith("+")
        and not line.startswith("+++")
        and "MockitoAnnotations.openMocks" in line
        for line in diff.splitlines()
    )


def _contains_dependency_change(diff: str) -> bool:
    lowered = diff.lower()
    return any(marker in lowered for marker in (
        "pom.xml",
        "build.gradle",
        "<dependency",
        "</dependency",
        "implementation ",
        "api ",
        "compile ",
        "runtimeonly",
        "testimplementation",
    ))


def _contains_shell_command(diff: str) -> bool:
    lowered = diff.lower()
    return any(marker in lowered for marker in (
        "rm -rf",
        "del /",
        "powershell",
        "cmd.exe",
        "bash ",
        "sh ",
        "curl ",
        "wget ",
        "mvn ",
        "gradle ",
    ))


def _safe_relative_path(value: str) -> bool:
    text = value.replace("\\", "/").strip()
    return bool(
        text
        and not text.startswith("/")
        and ":" not in text
        and "[redacted" not in text.lower()
        and all(part not in ("", ".", "..") for part in text.split("/"))
    )
