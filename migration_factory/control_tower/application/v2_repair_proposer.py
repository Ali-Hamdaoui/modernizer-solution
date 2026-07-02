"""Evidence-bound, non-actionable repair drafts for narrow stage families."""

from __future__ import annotations

import difflib
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, stream_sha256


SUPPORTED_FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
PROPOSAL_TYPE = "evidence_bound_repair_draft"
INITMOCKS_PATTERN = re.compile(r"MockitoAnnotations\.initMocks\(([^)]*)\);")


def propose_stage_repair(
    classification: dict[str, Any] | None,
    stage_evidence: dict[str, Any] | None,
    migration_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    classification = classification if isinstance(classification, dict) else {}
    stage_evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
    migration_memory = migration_memory if isinstance(migration_memory, dict) else {}
    base = _base_result(classification, stage_evidence, migration_memory)

    gate = str(classification.get("governance_gate_type") or "")
    failure_type = str(classification.get("failure_type") or "")
    family = str(classification.get("repair_family_candidate") or "")
    status = str(classification.get("classification_status") or "")

    if not classification or not stage_evidence:
        return _blocked(base, "unavailable", "classification_or_stage_evidence_unavailable", "collect_missing_stage_evidence")

    if gate == "human_review_gate":
        return _blocked(base, "blocked_human_review_gate", str(classification.get("repair_blocked_reason") or "human_review_gate_no_auto_repair"), str(classification.get("assistant_next_action") or "human_review_gate"))

    if failure_type != SUPPORTED_FAMILY or family != SUPPORTED_FAMILY:
        reason = "unsupported_family_in_R7D"
        if status == "blocked_pending_evidence" or gate == "blocked_pending_evidence":
            return _blocked(base, "blocked_pending_evidence", str(classification.get("repair_blocked_reason") or "missing_required_failure_evidence"), "collect_missing_stage_evidence")
        return _blocked(base, "blocked_unsupported_family", reason, "record_unsupported_failure_and_plan_taxonomy_expansion")

    if status != "known_family_candidate" or gate != "future_deterministic_candidate":
        return _blocked(base, "blocked_pending_evidence", "initmocks_candidate_requires_known_family_candidate_classification", "collect_missing_stage_evidence")

    if not stage_evidence.get("evidence_pack_checksum"):
        return _blocked(base, "blocked_pending_evidence", "evidence_pack_checksum_missing", "collect_missing_stage_evidence")

    artifact = _find_test_source_artifact(stage_evidence)
    if artifact is None:
        return _blocked(base, "blocked_pending_evidence", "test_source_evidence_missing", "collect_missing_stage_evidence")

    excerpt = str(artifact.get("excerpt") or "")
    if "MockitoAnnotations.initMocks" not in excerpt and "initMocks(" not in excerpt:
        return _blocked(base, "blocked_pending_evidence", "initmocks_marker_missing", "collect_missing_stage_evidence")

    internal_ref = str(artifact.get("internal_ref") or artifact.get("ref") or "")
    sandbox_ref = _sandbox_ref(stage_evidence)
    target = _bound_target_file(internal_ref, sandbox_ref)
    if target.get("error"):
        return _blocked(base, "blocked_pending_evidence", target["error"], "collect_missing_stage_evidence")

    file_path = Path(str(target["path"]))
    if not file_path.is_file():
        return _blocked(base, "blocked_pending_evidence", "target_file_unreadable", "collect_missing_stage_evidence")

    before_checksum, _ = stream_sha256(file_path)
    before_text = file_path.read_text(encoding="utf-8", errors="replace")
    matches = list(INITMOCKS_PATTERN.finditer(before_text))
    if len(matches) != 1:
        reason = "initmocks_marker_ambiguous" if matches else "initmocks_marker_missing"
        return _blocked(base, "blocked_pending_evidence", reason, "collect_missing_stage_evidence")

    after_text = INITMOCKS_PATTERN.sub(lambda match: f"MockitoAnnotations.openMocks({match.group(1)});", before_text, count=1)
    diff = "".join(difflib.unified_diff(
        before_text.splitlines(keepends=True),
        after_text.splitlines(keepends=True),
        fromfile=f"a/{target['relative']}",
        tofile=f"b/{target['relative']}",
    ))
    if not diff or "initMocks" not in diff or "openMocks" not in diff:
        return _blocked(base, "blocked_pending_evidence", "bounded_initmocks_diff_unavailable", "collect_missing_stage_evidence")

    draft = {
        **base,
        "proposal_status": "drafted_non_actionable",
        "supported_family": SUPPORTED_FAMILY,
        "target_files": [str(target["relative"])],
        "source_markers": ["MockitoAnnotations.initMocks"],
        "target_file_checksums": {str(target["relative"]): f"sha256:{before_checksum}"},
        "proposed_diff_preview": redact_absolute_paths(redact_model_summary(diff[:4000])),
        "blocked_reason": "",
        "assistant_next_action": "send_draft_to_future_reviewer_gate",
        "safety_warnings": [
            "Draft is non-actionable in R7D.",
            "Reviewer, human approval, and backend apply gates are required later.",
            "No AutoCloseable lifecycle field management is introduced in R7D.",
        ],
    }
    draft["proposed_diff_checksum"] = f"sha256:{sha256_canonical_json({'diff': draft['proposed_diff_preview']})}"
    draft["proposal_checksum"] = f"sha256:{sha256_canonical_json({k: v for k, v in draft.items() if k != 'proposal_checksum'})}"
    return _clamp_no_authority(draft)


def _base_result(
    classification: dict[str, Any],
    stage_evidence: dict[str, Any],
    migration_memory: dict[str, Any],
) -> dict[str, Any]:
    return _clamp_no_authority({
        "proposal_status": "unavailable",
        "proposal_type": PROPOSAL_TYPE,
        "supported_family": "",
        "failure_type": str(classification.get("failure_type") or ""),
        "classification_status": str(classification.get("classification_status") or ""),
        "governance_gate_type": str(classification.get("governance_gate_type") or ""),
        "stage_index": stage_evidence.get("stage_index") if stage_evidence else classification.get("stage_index"),
        "source_boot_version": str(classification.get("source_boot_version") or stage_evidence.get("source_boot_version") or ""),
        "target_boot_version": str(classification.get("target_boot_version") or stage_evidence.get("target_boot_version") or ""),
        "source_java_version": str(classification.get("source_java_version") or stage_evidence.get("source_java_version") or ""),
        "target_java_version": str(classification.get("target_java_version") or stage_evidence.get("target_java_version") or ""),
        "evidence_pack_id": str(stage_evidence.get("evidence_pack_id") or classification.get("evidence_pack_id") or ""),
        "evidence_pack_checksum": str(stage_evidence.get("evidence_pack_checksum") or classification.get("evidence_pack_checksum") or ""),
        "memory_query_signature": str(migration_memory.get("query_signature") or ""),
        "retrieved_memory_case_ids": [str(item) for item in (migration_memory.get("retrieved_case_ids") or [])[:8]],
        "target_files": [],
        "source_markers": [],
        "target_file_checksums": {},
        "proposed_diff_preview": "",
        "proposed_diff_checksum": "",
        "proposal_checksum": "",
        "proposer_kind": "deterministic_local",
        "proposer_origin": "backend_evidence_bound",
        "llm_invoked": False,
        "reviewer_required": True,
        "human_approval_required": True,
        "backend_apply_required": True,
        "blocked_reason": "",
        "assistant_next_action": "",
        "safety_warnings": [],
    })


def _blocked(base: dict[str, Any], status: str, reason: str, next_action: str) -> dict[str, Any]:
    result = {
        **base,
        "proposal_status": status,
        "blocked_reason": reason,
        "assistant_next_action": next_action,
        "proposed_diff_preview": "",
        "proposed_diff_checksum": "",
        "proposal_checksum": "",
        "target_files": [],
        "source_markers": [],
        "target_file_checksums": {},
        "safety_warnings": [
            "No repair draft is actionable in R7D.",
            "Memory cannot approve, apply, or start downstream stages.",
        ],
    }
    return _clamp_no_authority(result)


def _clamp_no_authority(result: dict[str, Any]) -> dict[str, Any]:
    result["apply_enabled"] = False
    result["approval_enabled"] = False
    result["repair_enabled"] = False
    result["llm_invoked"] = False
    result["sandbox_only"] = True
    result["legacy_mutation_allowed"] = False
    result["downstream_start_allowed"] = False
    return result


def _find_test_source_artifact(stage_evidence: dict[str, Any]) -> dict[str, Any] | None:
    for item in stage_evidence.get("usable_artifacts", []) or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        ref = str(item.get("ref") or item.get("internal_ref") or "")
        excerpt = str(item.get("excerpt") or "")
        if kind == "test_source" or ref.endswith("Test.java") or "src/test/" in ref.replace("\\", "/"):
            return item
        if "MockitoAnnotations.initMocks" in excerpt or "initMocks(" in excerpt:
            return item
    return None


def _sandbox_ref(stage_evidence: dict[str, Any]) -> str:
    for item in stage_evidence.get("usable_artifacts", []) or []:
        if isinstance(item, dict) and str(item.get("kind") or "") == "sandbox":
            return str(item.get("internal_ref") or item.get("ref") or "")
    return str(stage_evidence.get("output_sandbox_ref") or "")


def _bound_target_file(ref: str, sandbox_ref: str) -> dict[str, str]:
    if not ref:
        return {"error": "target_file_ref_missing"}
    if _looks_redacted(ref):
        return {"error": "target_file_ref_untrusted"}
    ref_path = Path(ref)
    if not ref_path.is_absolute():
        return {"error": "target_file_ref_untrusted"}
    if not sandbox_ref or _looks_redacted(sandbox_ref):
        return {"error": "sandbox_binding_unavailable_for_target_file"}
    try:
        sandbox = Path(sandbox_ref).resolve()
        resolved = ref_path.resolve()
        relative = resolved.relative_to(sandbox)
    except (OSError, ValueError):
        return {"error": "target_file_not_sandbox_contained"}
    rel_text = _safe_relative(relative.as_posix())
    if not rel_text:
        return {"error": "target_file_ref_untrusted"}
    return {"path": str(resolved), "relative": rel_text}


def _safe_relative(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if not text or text.startswith("/") or PureWindowsPath(text).is_absolute():
        return ""
    parts = PurePosixPath(text).parts
    if any(part in ("", ".", "..") for part in parts):
        return ""
    return "/".join(parts)


def _looks_redacted(value: str) -> bool:
    return "[" in value and "redacted" in value.lower()
