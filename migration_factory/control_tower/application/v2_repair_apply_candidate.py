"""R8/R8.1 governed sandbox repair candidate/apply for initMocks -> openMocks."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.application.v2_post_repair_verification import run_post_repair_verification
from migration_factory.control_tower.application.v2_repair_family_registry import repair_family_policy
from migration_factory.control_tower.application.v2_repair_subfamily_classifier import classify_repair_subfamily
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, stream_sha256, utc_now_text


SUPPORTED_FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
BACKEND_RECIPE = "INITMOCKS_TO_OPENMOCKS"
SORT_FAMILY = "SPRING_DATA_SORT_API_DRIFT"
SORT_BACKEND_RECIPE = "SPRING_DATA_SORT_BY"
JACKSON_FAMILY = "JACKSON_VERSION_ALIGNMENT_DRIFT"
JACKSON_BACKEND_RECIPE = "JACKSON_PROPERTY_BOM_ALIGNMENT"
JACKSON_TARGET_VERSION = "2.13.5"
INITMOCKS_PATTERN = re.compile(r"MockitoAnnotations\.initMocks\(([^)]*)\);")
SORT_CONSTRUCTOR_PATTERN = re.compile(r"\bnew\s+Sort\s*\(")
JACKSON_PROPERTY_PATTERN = re.compile(
    r"(<fasterxml-jackson\.version>\s*)(?P<version>[^<]+)(\s*</fasterxml-jackson\.version>)"
)
PUBLIC_STATUSES = {
    "pending_human_approval",
    "approved",
    "applying",
    "verified",
    "failed",
    "rolled_back",
}


def create_repair_apply_candidate(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    """Create pending candidate from backend-owned evidence or explicit internal inputs.

    R8 callers pass classification/stage_evidence/llm_shadow_trace.
    R8.1 tests/internal store callers pass keyword fields with sandbox/target paths.
    Browser/API callers must never create candidates or supply paths/patches.
    """

    if kwargs:
        return _create_candidate_from_internal_inputs(**kwargs)
    if len(args) != 3:
        raise TypeError("create_repair_apply_candidate expects R8 evidence args or R8.1 keyword inputs")
    return _create_candidate_from_r8_evidence(args[0], args[1], args[2])


def approve_repair_apply_candidate(candidate: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Record checksum-bound human approval. Request carries no patch/path."""

    candidate = candidate if isinstance(candidate, dict) else {}
    request = request if isinstance(request, dict) else {}
    _must(candidate.get("status") == "pending_human_approval", "candidate_not_pending_human_approval")
    _must(str(request.get("repair_candidate_id") or "") == str(candidate.get("repair_candidate_id") or ""), "repair_candidate_id_mismatch")
    _must(str(request.get("patch_checksum") or "") == str(candidate.get("patch_checksum") or ""), "patch_checksum_mismatch")
    _must(str(request.get("target_file_checksum") or "") == str(candidate.get("target_file_checksum") or ""), "target_file_checksum_mismatch")
    _must(str(request.get("review_checksum") or "") == str(candidate.get("review_checksum") or ""), "review_checksum_mismatch")
    return {
        "approval_id": f"repair-approval-{uuid4().hex[:12]}",
        "approval_status": "approved",
        "repair_candidate_id": candidate["repair_candidate_id"],
        "patch_checksum": candidate["patch_checksum"],
        "target_file_checksum": candidate["target_file_checksum"],
        "review_checksum": candidate["review_checksum"],
        "approval_checksum": f"sha256:{sha256_canonical_json({'candidate': candidate['repair_candidate_id'], 'patch': candidate['patch_checksum'], 'target': candidate['target_file_checksum'], 'review': candidate['review_checksum']})}",
        "approval_scope": "sandbox_only",
        "apply_enabled": True,
        "created_at": utc_now_text(),
    }


def apply_approved_repair_candidate(
    candidate: dict[str, Any],
    approval: dict[str, Any],
    *,
    verification_runner: Callable[[Path], tuple[bool, str]] | None = None,
    post_repair_verification_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Apply backend-owned recipe to sandbox only, verify, rollback on failure."""

    candidate = candidate if isinstance(candidate, dict) else {}
    approval = approval if isinstance(approval, dict) else {}
    _must(approval.get("approval_status") == "approved", "approval_required")
    _must(approval.get("repair_candidate_id") == candidate.get("repair_candidate_id"), "approval_candidate_mismatch")
    target = Path(str(candidate.get("_target_path") or "")).resolve()
    sandbox = Path(str(candidate.get("_sandbox_root") or "")).resolve()
    _must(_is_contained(target, sandbox), "target_not_sandbox_contained")
    checksum, _ = stream_sha256(target)
    _must(f"sha256:{checksum}" == candidate.get("pre_apply_checksum"), "pre_apply_checksum_mismatch")

    file_changes = candidate.get("_file_changes") if isinstance(candidate.get("_file_changes"), list) else []
    if file_changes:
        return _apply_multi_file_candidate(
            candidate,
            approval,
            verification_runner=verification_runner,
            post_repair_verification_runner=post_repair_verification_runner,
        )

    before = target.read_text(encoding="utf-8", errors="replace")
    rollback_dir = sandbox / ".migration" / "rollback" / str(candidate["repair_candidate_id"])
    rollback_dir.mkdir(parents=True, exist_ok=True)
    rollback_file = rollback_dir / _rollback_filename(str(candidate.get("target_file") or "target.txt"))
    rollback_file.write_text(before, encoding="utf-8")

    try:
        after = str(candidate.get("_after_text") or "")
        _must(after and after != before, "backend_recipe_noop")
        target.write_text(after, encoding="utf-8")
        verified, verification_log = verification_runner(target) if verification_runner else _default_verification_for_candidate(candidate, target)
        if not verified:
            raise RuntimeError("verification_failed")
        post_checksum, _ = stream_sha256(target)
        proof = _write_proof(
            sandbox=sandbox,
            candidate=candidate,
            approval=approval,
            status="verified",
            post_apply_checksum=f"sha256:{post_checksum}",
            verification_log=verification_log,
            rollback_status="not_needed",
        )
        execution = _execution_result(candidate, approval, "verified", f"sha256:{post_checksum}", "passed", verification_log, "not_needed", proof)
        post_repair = run_post_repair_verification(
            job_id=str(candidate.get("job_id") or ""),
            stage_index=int(candidate.get("stage_index") or 1),
            repair_candidate=candidate,
            approval=approval,
            command_runner=post_repair_verification_runner,
        )
        execution["post_repair_verification"] = {key: value for key, value in post_repair.items() if key != "_next_repair_candidate"}
        execution.update(post_repair)
        return execution
    except Exception as exc:
        target.write_text(before, encoding="utf-8")
        rollback_checksum, _ = stream_sha256(target)
        proof = _write_proof(
            sandbox=sandbox,
            candidate=candidate,
            approval=approval,
            status="rolled_back",
            post_apply_checksum=f"sha256:{rollback_checksum}",
            verification_log=redact_model_summary(str(exc)),
            rollback_status="succeeded",
        )
        return _execution_result(candidate, approval, "rolled_back", f"sha256:{rollback_checksum}", "failed", str(exc), "succeeded", proof)


def public_repair_apply_candidate(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    return {key: value for key, value in candidate.items() if not key.startswith("_")}


def repair_state_narration(candidate: dict[str, Any] | None) -> str:
    public = public_repair_apply_candidate(candidate)
    if not public:
        return (
            "Repair candidate: none. Failure remains human-gated; PowerMock or unsupported failures require human review "
            "and no backend apply candidate exists. Checksums: unavailable. Approval: unavailable. Apply: unavailable. "
            "Verification: not_started. Rollback: not_started. Proof: pending. Downstream remains blocked until backend proof exists."
        )
    return (
        f"Repair candidate: {public['repair_candidate_id']} for {public['family']}. "
        f"Status: {public['status']}. Required checksums: patch={public['patch_checksum']}, "
        f"target={public['target_file_checksum']}, review={public['review_checksum']}. "
        f"Verification: {public.get('verification_status') or 'not_started'}. "
        f"Rollback: {public.get('rollback_status') or 'not_started'}. "
        f"Proof: {public.get('proof_artifact') or 'pending'}. "
        "Downstream remains blocked because repair apply never auto-starts next stages and proof must be reviewed."
    )


def _create_candidate_from_r8_evidence(
    classification: dict[str, Any] | None,
    stage_evidence: dict[str, Any] | None,
    llm_shadow_trace: dict[str, Any] | None,
) -> dict[str, Any] | None:
    classification = classification if isinstance(classification, dict) else {}
    stage_evidence = stage_evidence if isinstance(stage_evidence, dict) else {}
    trace = llm_shadow_trace if isinstance(llm_shadow_trace, dict) else {}
    draft = classification.get("repair_proposal_draft") if isinstance(classification.get("repair_proposal_draft"), dict) else {}
    review = classification.get("repair_draft_review") if isinstance(classification.get("repair_draft_review"), dict) else {}
    proposer = trace.get("proposer_trace") if isinstance(trace.get("proposer_trace"), dict) else {}
    reviewer = trace.get("reviewer_trace") if isinstance(trace.get("reviewer_trace"), dict) else {}
    proposer_output = proposer.get("output") if isinstance(proposer.get("output"), dict) else {}
    reviewer_output = reviewer.get("output") if isinstance(reviewer.get("output"), dict) else {}
    assessment = classification.get("repair_subfamily_assessment")
    if not isinstance(assessment, dict):
        assessment = classify_repair_subfamily(
            family_policy=repair_family_policy(classification.get("failure_type")),
            stage_evidence=stage_evidence,
            classification=classification,
            migration_memory=classification.get("migration_memory") if isinstance(classification.get("migration_memory"), dict) else None,
        )

    if classification.get("failure_type") == SORT_FAMILY:
        candidate = _create_sort_candidate_from_evidence(classification, stage_evidence)
        if candidate is None:
            classification["repair_apply_candidate_blocked_reason"] = "sort_by_candidate_safety_gate_failed"
        return candidate

    if classification.get("failure_type") == JACKSON_FAMILY:
        candidate = _create_jackson_candidate_from_evidence(classification, stage_evidence)
        if candidate is None:
            classification["repair_apply_candidate_blocked_reason"] = "jackson_alignment_candidate_safety_gate_failed"
        return candidate

    reasons: list[str] = []
    _require(classification.get("failure_type") == SUPPORTED_FAMILY, "classification_not_supported_family", reasons)
    _require(assessment.get("subfamily") == "INITMOCKS_DIRECT_REPLACEMENT", "subfamily_not_initmocks_direct_replacement", reasons)
    _require(assessment.get("promotion_status") == "safe_recipe_candidate", "subfamily_not_safe_recipe_candidate", reasons)
    _require(bool(assessment.get("backend_recipe_available")), "subfamily_backend_recipe_unavailable", reasons)
    _require(bool(assessment.get("apply_candidate_allowed")), "subfamily_apply_candidate_not_allowed", reasons)
    _require(not list(assessment.get("missing_evidence") or []), "subfamily_missing_required_evidence", reasons)
    _require(draft.get("proposal_status") == "drafted_non_actionable", "deterministic_draft_missing", reasons)
    _require(review.get("verdict") == "accepted_for_future_apply_gate", "deterministic_reviewer_not_accepted", reasons)
    _require(review.get("checksum_verification_status") == "verified", "deterministic_review_checksum_not_verified", reasons)
    _require(proposer.get("schema_validation_status") == "validated", "llm_proposer_schema_not_validated", reasons)
    _require(reviewer.get("schema_validation_status") == "validated", "llm_reviewer_schema_not_validated", reasons)
    _require(proposer_output.get("required_backend_recipe") == BACKEND_RECIPE, "llm_proposer_recipe_not_supported", reasons)
    _require(reviewer_output.get("verdict") == "advisory_accept", "llm_reviewer_not_advisory_accept", reasons)
    if reasons:
        classification["repair_apply_candidate_blocked_reason"] = ";".join(reasons)
        return None

    targets = list(draft.get("target_files") or [])
    if len(targets) != 1:
        return None
    target_rel = _safe_relative(str(targets[0]))
    if not target_rel:
        return None
    target_path = _find_internal_target(stage_evidence, target_rel)
    sandbox_root = _find_sandbox_root(stage_evidence, target_path)
    if target_path is None or sandbox_root is None:
        return None
    expected_checksum = str((draft.get("target_file_checksums") or {}).get(target_rel) or "")
    candidate = _build_candidate(
        job_id=str(stage_evidence.get("job_id") or classification.get("job_id") or ""),
        stage_index=int(stage_evidence.get("stage_index") or classification.get("stage_index") or 1),
        target_rel=target_rel,
        sandbox_root=sandbox_root,
        target_path=target_path,
        review_checksum=str(review.get("review_checksum") or ""),
        proposal_checksum=str(draft.get("proposal_checksum") or ""),
        proposed_diff_checksum=str(draft.get("proposed_diff_checksum") or ""),
    )
    if candidate is None or expected_checksum != candidate["pre_apply_checksum"]:
        return None
    return candidate


def _create_candidate_from_internal_inputs(
    *,
    job_id: str,
    stage_index: int,
    target_file: str,
    sandbox_root: str,
    target_path: str,
    review_checksum: str,
    proposal_checksum: str = "",
) -> dict[str, Any] | None:
    target_rel = _safe_relative(target_file)
    if not target_rel:
        return None
    return _build_candidate(
        job_id=job_id,
        stage_index=stage_index,
        target_rel=target_rel,
        sandbox_root=Path(sandbox_root).resolve(),
        target_path=Path(target_path).resolve(),
        review_checksum=review_checksum,
        proposal_checksum=proposal_checksum,
        proposed_diff_checksum="",
    )


def _build_candidate(
    *,
    job_id: str,
    stage_index: int,
    target_rel: str,
    sandbox_root: Path,
    target_path: Path,
    review_checksum: str,
    proposal_checksum: str,
    proposed_diff_checksum: str,
) -> dict[str, Any] | None:
    sandbox_root = sandbox_root.resolve()
    target_path = target_path.resolve()
    if not _is_contained(target_path, sandbox_root) or not target_path.is_file():
        return None
    checksum, _ = stream_sha256(target_path)
    pre_apply_checksum = f"sha256:{checksum}"
    before = target_path.read_text(encoding="utf-8", errors="replace")
    matches = list(INITMOCKS_PATTERN.finditer(before))
    if len(matches) != 1:
        return None
    after = INITMOCKS_PATTERN.sub(lambda match: f"MockitoAnnotations.openMocks({match.group(1)});", before, count=1)
    before_checksum = _text_checksum(before)
    after_checksum = _text_checksum(after)
    patch_payload = {
        "recipe": BACKEND_RECIPE,
        "target_file": target_rel,
        "before_marker": "MockitoAnnotations.initMocks",
        "after_marker": "MockitoAnnotations.openMocks",
        "before_checksum": before_checksum,
        "after_checksum": after_checksum,
    }
    if proposed_diff_checksum:
        patch_payload["proposed_diff_checksum"] = proposed_diff_checksum
    identity_payload = {
        "job_id": job_id,
        "stage_index": stage_index,
        "target_file": target_rel,
        "pre_apply_checksum": pre_apply_checksum,
        "patch_checksum": f"sha256:{sha256_canonical_json(patch_payload)}",
        "review_checksum": review_checksum,
    }
    candidate = {
        "job_id": job_id,
        "stage_index": stage_index,
        "repair_candidate_id": f"repair-candidate-{sha256_canonical_json(identity_payload)[:12]}",
        "status": "pending_human_approval",
        "family": SUPPORTED_FAMILY,
        "patch_source": "backend_deterministic_recipe",
        "llm_source": "advisory_only",
        "target_file": target_rel,
        "pre_apply_checksum": pre_apply_checksum,
        "target_file_checksum": pre_apply_checksum,
        "patch_checksum": identity_payload["patch_checksum"],
        "review_checksum": review_checksum,
        "proposal_checksum": proposal_checksum,
        "approval_required": True,
        "apply_enabled": False,
        "approval_enabled": True,
        "sandbox_only": True,
        "legacy_mutation_allowed": False,
        "downstream_start_allowed": False,
        "llm_can_apply": False,
        "browser_can_supply_patch": False,
        "verification_status": "not_started",
        "rollback_status": "not_started",
        "proof_artifact": "",
        "created_at": utc_now_text(),
        "_before_checksum": before_checksum,
        "_after_checksum": after_checksum,
        "_sandbox_root": str(sandbox_root),
        "_target_path": str(target_path),
        "_after_text": after,
        "_patch_payload": patch_payload,
    }
    candidate["candidate_checksum"] = f"sha256:{sha256_canonical_json(_candidate_checksum_payload(candidate))}"
    return candidate


def _create_jackson_candidate_from_evidence(classification: dict[str, Any], stage_evidence: dict[str, Any]) -> dict[str, Any] | None:
    sandbox_root = _find_sandbox_root(stage_evidence, None)
    pom_path = _find_pom_xml(stage_evidence, sandbox_root)
    if sandbox_root is None or pom_path is None:
        return None
    sandbox_root = sandbox_root.resolve()
    pom_path = pom_path.resolve()
    if not _is_contained(pom_path, sandbox_root) or pom_path.name != "pom.xml" or not pom_path.is_file():
        return None
    evidence_text = _stage_evidence_text(stage_evidence, classification)
    if not _has_jackson_mismatch_evidence(evidence_text):
        return None
    before = pom_path.read_text(encoding="utf-8", errors="replace")
    if not _is_stage1_boot27_pom(before):
        return None
    after, operations, previews = _patch_jackson_alignment_pom(before, add_direct_dependencies=_needs_direct_jackson_dependencies(evidence_text))
    if before == after or not operations:
        return None
    target_rel = _relative_to_sandbox(pom_path, sandbox_root)
    if target_rel != "pom.xml":
        return None
    checksum, _ = stream_sha256(pom_path)
    pre_apply_checksum = f"sha256:{checksum}"
    before_checksum = _text_checksum(before)
    after_checksum = _text_checksum(after)
    patch_payload = {
        "recipe": JACKSON_BACKEND_RECIPE,
        "target_files": [target_rel],
        "operations": operations,
        "target_version": JACKSON_TARGET_VERSION,
        "source": "cli_msa_utils_reference_advisory",
        "authority": "backend_deterministic_recipe",
        "change_preview": previews,
        "before_checksum": before_checksum,
        "after_checksum": after_checksum,
        "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
    }
    review_payload = {
        "family": JACKSON_FAMILY,
        "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        "target_files": [target_rel],
        "approval_required": True,
    }
    identity_payload = {
        "job_id": str(stage_evidence.get("job_id") or classification.get("job_id") or ""),
        "stage_index": int(stage_evidence.get("stage_index") or classification.get("stage_index") or 1),
        "target_file": target_rel,
        "pre_apply_checksum": pre_apply_checksum,
        "patch_checksum": f"sha256:{sha256_canonical_json(patch_payload)}",
    }
    candidate = {
        "job_id": identity_payload["job_id"],
        "stage_index": identity_payload["stage_index"],
        "repair_candidate_id": f"repair-candidate-{sha256_canonical_json(identity_payload)[:12]}",
        "status": "pending_human_approval",
        "family": JACKSON_FAMILY,
        "recipe_id": JACKSON_BACKEND_RECIPE,
        "source_java_version": str(stage_evidence.get("source_java_version") or classification.get("source_java_version") or ""),
        "target_java_version": str(stage_evidence.get("target_java_version") or classification.get("target_java_version") or ""),
        "patch_source": "backend_deterministic_recipe",
        "llm_source": "advisory_only",
        "target_file": target_rel,
        "target_files": [target_rel],
        "pre_apply_checksum": pre_apply_checksum,
        "target_file_checksum": pre_apply_checksum,
        "patch_checksum": identity_payload["patch_checksum"],
        "review_checksum": f"sha256:{sha256_canonical_json(review_payload)}",
        "proposal_checksum": "",
        "approval_required": True,
        "human_gate_required": True,
        "apply_enabled": False,
        "approval_enabled": True,
        "sandbox_only": True,
        "legacy_mutation_allowed": False,
        "downstream_start_allowed": False,
        "llm_can_apply": False,
        "browser_can_supply_patch": False,
        "verification_status": "not_started",
        "rollback_status": "not_started",
        "proof_artifact": "",
        "change_preview": previews,
        "operation_count": len(operations),
        "impact_summary": "Align Jackson dependencies in sandbox pom.xml for Stage 1 Boot 2.7 / Java 11 by using Jackson 2.13.5.",
        "risk_notes": [
            "Medium-risk POM-only dependency alignment; no source or test code changes.",
            "Boot 3.5 reference uses Jackson 2.20.0 but is advisory only and not copied into Stage 1.",
            "Human must approve exact checksums before sandbox apply.",
        ],
        "rollback_metadata": {
            "rollback_required": True,
            "rollback_scope": "sandbox_only",
            "target_files": [target_rel],
        },
        "suggested_verification_commands": [
            "mvn -DskipTests clean compile",
            "mvn -Dtest=MessageUtilsTest test",
            "mvn test",
        ],
        "created_at": utc_now_text(),
        "_before_checksum": before_checksum,
        "_after_checksum": after_checksum,
        "_evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        "_sandbox_root": str(sandbox_root),
        "_target_path": str(pom_path),
        "_after_text": after,
        "_patch_payload": patch_payload,
    }
    candidate["candidate_checksum"] = f"sha256:{sha256_canonical_json(_candidate_checksum_payload(candidate))}"
    return candidate


def _create_sort_candidate_from_evidence(classification: dict[str, Any], stage_evidence: dict[str, Any]) -> dict[str, Any] | None:
    sandbox_root = _find_sandbox_root(stage_evidence, None)
    if sandbox_root is None:
        return None
    sandbox_root = sandbox_root.resolve()
    target_paths = _sort_target_paths(classification, stage_evidence, sandbox_root)
    if not target_paths:
        return None

    changes: list[dict[str, Any]] = []
    for target_path in target_paths:
        if not _is_contained(target_path, sandbox_root) or not target_path.is_file():
            return None
        target_rel = _relative_to_sandbox(target_path, sandbox_root)
        if not target_rel:
            return None
        before = target_path.read_text(encoding="utf-8", errors="replace")
        after, replacements = _replace_sort_constructor_calls(before)
        if before == after or replacements < 1:
            return None
        preview = _sort_change_preview(target_rel, before, after, replacements)
        if preview is None:
            return None
        checksum, _ = stream_sha256(target_path)
        before_checksum = _text_checksum(before)
        after_checksum = _text_checksum(after)
        changes.append({
            "target_file": target_rel,
            "pre_apply_checksum": f"sha256:{checksum}",
            "before_marker": "new Sort(",
            "after_marker": "Sort.by(",
            "change_preview": preview,
            "before_checksum": before_checksum,
            "after_checksum": after_checksum,
            "_target_path": str(target_path),
            "_after_text": after,
            "_before_text": before,
            "replacement_count": replacements,
        })
    if not changes:
        return None

    patch_payload = {
        "recipe": SORT_BACKEND_RECIPE,
        "target_files": [change["target_file"] for change in changes],
        "operations": ["replace Spring Data Sort constructor with Sort.by"],
        "golden_reference": "msa-utils migrated/reference advisory evidence only",
        "change_preview": [change["change_preview"] for change in changes],
        "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        "file_changes": [
            {
                "target_file": change["target_file"],
                "before_checksum": change["before_checksum"],
                "after_checksum": change["after_checksum"],
                "before_marker": change["before_marker"],
                "after_marker": change["after_marker"],
            }
            for change in changes
        ],
    }
    review_payload = {
        "family": SORT_FAMILY,
        "evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        "target_files": patch_payload["target_files"],
        "approval_required": True,
    }
    identity_payload = {
        "job_id": str(stage_evidence.get("job_id") or classification.get("job_id") or ""),
        "stage_index": int(stage_evidence.get("stage_index") or classification.get("stage_index") or 1),
        "target_files": patch_payload["target_files"],
        "pre_apply_checksums": [change["pre_apply_checksum"] for change in changes],
        "patch_checksum": f"sha256:{sha256_canonical_json(patch_payload)}",
    }
    candidate = {
        "job_id": identity_payload["job_id"],
        "stage_index": identity_payload["stage_index"],
        "repair_candidate_id": f"repair-candidate-{sha256_canonical_json(identity_payload)[:12]}",
        "status": "pending_human_approval",
        "family": SORT_FAMILY,
        "recipe_id": SORT_BACKEND_RECIPE,
        "source_java_version": str(stage_evidence.get("source_java_version") or classification.get("source_java_version") or ""),
        "target_java_version": str(stage_evidence.get("target_java_version") or classification.get("target_java_version") or ""),
        "patch_source": "backend_deterministic_recipe",
        "llm_source": "advisory_only",
        "target_file": changes[0]["target_file"],
        "target_files": patch_payload["target_files"],
        "pre_apply_checksum": changes[0]["pre_apply_checksum"],
        "target_file_checksum": f"sha256:{sha256_canonical_json([change['pre_apply_checksum'] for change in changes])}",
        "patch_checksum": identity_payload["patch_checksum"],
        "review_checksum": f"sha256:{sha256_canonical_json(review_payload)}",
        "proposal_checksum": "",
        "approval_required": True,
        "human_gate_required": True,
        "apply_enabled": False,
        "approval_enabled": True,
        "sandbox_only": True,
        "legacy_mutation_allowed": False,
        "downstream_start_allowed": False,
        "llm_can_apply": False,
        "browser_can_supply_patch": False,
        "verification_status": "not_started",
        "rollback_status": "not_started",
        "proof_artifact": "",
        "change_preview": patch_payload["change_preview"],
        "impact_summary": "Replace removed Spring Data Sort constructor calls with Sort.by in sandbox main source files only.",
        "risk_notes": [
            "Low-risk API drift replacement; preserves same Direction and property arguments.",
            "CLI/reference migrated branch is advisory evidence only and cannot approve or apply.",
            "Human must approve exact checksums before sandbox apply.",
        ],
        "rollback_metadata": {
            "rollback_required": True,
            "rollback_scope": "sandbox_only",
            "target_files": patch_payload["target_files"],
        },
        "created_at": utc_now_text(),
        "_before_checksums": [change["before_checksum"] for change in changes],
        "_after_checksums": [change["after_checksum"] for change in changes],
        "_evidence_pack_checksum": stage_evidence.get("evidence_pack_checksum", ""),
        "_sandbox_root": str(sandbox_root),
        "_target_path": str(target_paths[0]),
        "_after_text": changes[0]["_after_text"],
        "_file_changes": changes,
        "_patch_payload": patch_payload,
    }
    candidate["candidate_checksum"] = f"sha256:{sha256_canonical_json(_candidate_checksum_payload(candidate))}"
    return candidate


def _sort_target_paths(classification: dict[str, Any], stage_evidence: dict[str, Any], sandbox_root: Path) -> list[Path]:
    wanted = {
        _safe_relative(str(item.get("path") or ""))
        for item in classification.get("sort_api_drift_targets", [])
        if isinstance(item, dict)
    }
    wanted.discard("")
    result: list[Path] = []

    for item in stage_evidence.get("usable_artifacts", []) or []:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "source_ref":
            continue
        ref = str(item.get("internal_ref") or item.get("ref") or "")
        if not ref or "[" in ref:
            continue
        path = Path(ref).resolve()
        rel = _relative_to_sandbox(path, sandbox_root)
        if _is_java_main_source_rel(rel) and (not wanted or rel in wanted):
            result.append(path)

    for rel in sorted(wanted):
        if not _is_java_main_source_rel(rel):
            continue
        path = (sandbox_root / rel).resolve()
        if _is_contained(path, sandbox_root) and path.is_file():
            result.append(path)

    for root in _main_source_roots(sandbox_root):
        for path in sorted(root.rglob("*.java"))[:250]:
            path = path.resolve()
            rel = _relative_to_sandbox(path, sandbox_root)
            if not _is_java_main_source_rel(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if SORT_CONSTRUCTOR_PATTERN.search(text):
                result.append(path)
    return list(dict.fromkeys(result))[:8]


def _is_java_main_source_rel(value: str) -> bool:
    rel = value.replace("\\", "/").strip()
    return bool(rel.endswith(".java") and (rel.startswith("src/main/java/") or "/src/main/java/" in rel))


def _main_source_roots(sandbox_root: Path) -> list[Path]:
    roots: list[Path] = []
    direct = (sandbox_root / "src" / "main" / "java").resolve()
    if _is_contained(direct, sandbox_root) and direct.is_dir():
        roots.append(direct)
    for child in sorted(sandbox_root.iterdir()) if sandbox_root.is_dir() else []:
        module_root = (child / "src" / "main" / "java").resolve()
        if _is_contained(module_root, sandbox_root) and module_root.is_dir():
            roots.append(module_root)
    return list(dict.fromkeys(roots))[:25]


def _replace_sort_constructor_calls(text: str) -> tuple[str, int]:
    result: list[str] = []
    index = 0
    replacements = 0
    while True:
        match = SORT_CONSTRUCTOR_PATTERN.search(text, index)
        if match is None:
            result.append(text[index:])
            break
        close = _find_matching_paren(text, match.end() - 1)
        if close < 0:
            return text, 0
        args = text[match.end():close]
        if not _safe_sort_args(args):
            return text, 0
        result.append(text[index:match.start()])
        result.append(f"Sort.by({args})")
        index = close + 1
        replacements += 1
    return "".join(result), replacements


def _find_matching_paren(text: str, open_index: int) -> int:
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _safe_sort_args(args: str) -> bool:
    if "\n" in args or ";" in args or "{" in args or "}" in args:
        return False
    if "," not in args:
        return False
    if "Direction.fromString(" in args:
        return True
    return bool(re.match(r"\s*(?:Direction\.[A-Z]+|sortDirection)\s*,\s*[A-Za-z_][A-Za-z0-9_]*(?:\([^;{}]*\))?\s*$", args))


def _sort_change_preview(target_file: str, before: str, after: str, replacements: int) -> dict[str, Any] | None:
    before_line = _first_line_containing(before, "new Sort(")
    after_line = _first_line_containing(after, "Sort.by(")
    if not before_line or not after_line:
        return None
    return {
        "target_file": target_file,
        "replacement_count": replacements,
        "before_marker": "new Sort(",
        "after_marker": "Sort.by(",
        "before": before_line[:240],
        "after": after_line[:240],
    }


def _first_line_containing(text: str, marker: str) -> str:
    for line in text.splitlines():
        if marker in line:
            return line.strip()
    return ""


def _relative_to_sandbox(path: Path, sandbox_root: Path) -> str:
    try:
        return path.resolve().relative_to(sandbox_root.resolve()).as_posix()
    except (OSError, ValueError):
        return ""


def _apply_multi_file_candidate(
    candidate: dict[str, Any],
    approval: dict[str, Any],
    *,
    verification_runner: Callable[[Path], tuple[bool, str]] | None = None,
    post_repair_verification_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    sandbox = Path(str(candidate.get("_sandbox_root") or "")).resolve()
    changes = [item for item in candidate.get("_file_changes", []) if isinstance(item, dict)]
    rollback_dir = sandbox / ".migration" / "rollback" / str(candidate["repair_candidate_id"])
    rollback_dir.mkdir(parents=True, exist_ok=True)
    before_by_path: dict[Path, str] = {}
    try:
        for change in changes:
            target = Path(str(change.get("_target_path") or "")).resolve()
            _must(_is_contained(target, sandbox), "target_not_sandbox_contained")
            checksum, _ = stream_sha256(target)
            _must(f"sha256:{checksum}" == change.get("pre_apply_checksum"), "pre_apply_checksum_mismatch")
            before = target.read_text(encoding="utf-8", errors="replace")
            before_by_path[target] = before
            rollback_file = rollback_dir / _rollback_filename(str(change.get("target_file") or target.name))
            rollback_file.write_text(before, encoding="utf-8")
            after = str(change.get("_after_text") or "")
            _must(after and after != before, "backend_recipe_noop")
            target.write_text(after, encoding="utf-8")
        verification_logs: list[str] = []
        for target in before_by_path:
            verified, verification_log = verification_runner(target) if verification_runner else _default_sort_verification(target)
            verification_logs.append(verification_log)
            if not verified:
                raise RuntimeError("verification_failed")
        post_apply_checksum = f"sha256:{sha256_canonical_json([stream_sha256(path)[0] for path in before_by_path])}"
        proof = _write_proof(
            sandbox=sandbox,
            candidate=candidate,
            approval=approval,
            status="verified",
            post_apply_checksum=post_apply_checksum,
            verification_log="; ".join(verification_logs),
            rollback_status="not_needed",
        )
        execution = _execution_result(candidate, approval, "verified", post_apply_checksum, "passed", "; ".join(verification_logs), "not_needed", proof)
        post_repair = run_post_repair_verification(
            job_id=str(candidate.get("job_id") or ""),
            stage_index=int(candidate.get("stage_index") or 1),
            repair_candidate=candidate,
            approval=approval,
            command_runner=post_repair_verification_runner,
        )
        execution["post_repair_verification"] = {key: value for key, value in post_repair.items() if key != "_next_repair_candidate"}
        execution.update(post_repair)
        return execution
    except Exception as exc:
        for target, before in before_by_path.items():
            target.write_text(before, encoding="utf-8")
        rollback_checksum = f"sha256:{sha256_canonical_json([stream_sha256(path)[0] for path in before_by_path])}"
        proof = _write_proof(
            sandbox=sandbox,
            candidate=candidate,
            approval=approval,
            status="rolled_back",
            post_apply_checksum=rollback_checksum,
            verification_log=redact_model_summary(str(exc)),
            rollback_status="succeeded",
        )
        return _execution_result(candidate, approval, "rolled_back", rollback_checksum, "failed", str(exc), "succeeded", proof)


def _execution_result(candidate: dict[str, Any], approval: dict[str, Any], status: str, post_apply_checksum: str, verification_status: str, verification_log: str, rollback_status: str, proof_artifact: str) -> dict[str, Any]:
    return {
        "repair_candidate_id": candidate.get("repair_candidate_id", ""),
        "approval_id": approval.get("approval_id", ""),
        "execution_status": status,
        "status": status,
        "target_file": candidate.get("target_file", ""),
        "post_apply_checksum": post_apply_checksum,
        "verification_status": verification_status,
        "verification_log": redact_absolute_paths(redact_model_summary(verification_log))[:1200],
        "rollback_status": rollback_status,
        "proof_artifact": proof_artifact,
        "sandbox_only": True,
        "legacy_mutation_allowed": False,
        "downstream_start_allowed": False,
        "apply_enabled": False,
        "approval_enabled": False,
        "created_at": utc_now_text(),
    }


def _write_proof(*, sandbox: Path, candidate: dict[str, Any], approval: dict[str, Any], status: str, post_apply_checksum: str, verification_log: str, rollback_status: str) -> str:
    proof_dir = sandbox / ".migration" / "repair-proofs"
    proof_dir.mkdir(parents=True, exist_ok=True)
    proof_path = proof_dir / f"{candidate['repair_candidate_id']}.json"
    proof = {
        "repair_candidate_id": candidate["repair_candidate_id"],
        "approval_id": approval.get("approval_id", ""),
        "status": status,
        "family": candidate.get("family", ""),
        "target_file": candidate.get("target_file", ""),
        "patch_checksum": candidate.get("patch_checksum", ""),
        "pre_apply_checksum": candidate.get("pre_apply_checksum", ""),
        "post_apply_checksum": post_apply_checksum,
        "verification_log": redact_model_summary(verification_log)[:1200],
        "rollback_status": rollback_status,
        "sandbox_only": True,
        "downstream_start_allowed": False,
        "created_at": utc_now_text(),
    }
    proof["proof_checksum"] = f"sha256:{sha256_canonical_json(proof)}"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    return redact_absolute_paths(str(proof_path))


def _default_verification(target: Path) -> tuple[bool, str]:
    text = target.read_text(encoding="utf-8", errors="replace")
    ok = "MockitoAnnotations.openMocks" in text and "MockitoAnnotations.initMocks" not in text
    return ok, "deterministic_file_verification_passed" if ok else "deterministic_file_verification_failed"


def _default_verification_for_candidate(candidate: dict[str, Any], target: Path) -> tuple[bool, str]:
    if candidate.get("family") == JACKSON_FAMILY:
        return _default_jackson_verification(target)
    return _default_verification(target)


def _default_sort_verification(target: Path) -> tuple[bool, str]:
    text = target.read_text(encoding="utf-8", errors="replace")
    ok = "Sort.by(" in text and "new Sort(" not in text
    return ok, "deterministic_sort_by_verification_passed" if ok else "deterministic_sort_by_verification_failed"


def _default_jackson_verification(target: Path) -> tuple[bool, str]:
    text = target.read_text(encoding="utf-8", errors="replace")
    ok = (
        f"<fasterxml-jackson.version>{JACKSON_TARGET_VERSION}</fasterxml-jackson.version>" in text
        and "<artifactId>jackson-bom</artifactId>" in text
        and "2.20.0" not in text
    )
    return ok, "deterministic_jackson_alignment_verification_passed" if ok else "deterministic_jackson_alignment_verification_failed"


def _find_internal_target(stage_evidence: dict[str, Any], target_rel: str) -> Path | None:
    for item in stage_evidence.get("usable_artifacts", []) or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("internal_ref") or item.get("ref") or "")
        if not ref or "[" in ref:
            continue
        path = Path(ref)
        normalized = ref.replace("\\", "/")
        if path.is_file() and normalized.endswith(target_rel):
            return path.resolve()
    return None


def _find_sandbox_root(stage_evidence: dict[str, Any], target: Path | None) -> Path | None:
    for item in stage_evidence.get("usable_artifacts", []) or []:
        if isinstance(item, dict) and str(item.get("kind") or "") == "sandbox":
            ref = str(item.get("internal_ref") or item.get("ref") or "")
            if ref and "[" not in ref:
                return Path(ref).resolve()
    ref = str(stage_evidence.get("output_sandbox_ref") or "")
    if ref and "[" not in ref:
        return Path(ref).resolve()
    return target.parents[5].resolve() if target is not None and len(target.parents) > 5 else None


def _find_pom_xml(stage_evidence: dict[str, Any], sandbox_root: Path | None) -> Path | None:
    for item in stage_evidence.get("usable_artifacts", []) or []:
        if not isinstance(item, dict) or str(item.get("kind") or "") != "pom_xml":
            continue
        ref = str(item.get("internal_ref") or item.get("ref") or "")
        if ref and "[" not in ref:
            path = Path(ref).resolve()
            if sandbox_root is None or _is_contained(path, sandbox_root):
                return path
    return None


def _stage_evidence_text(*values: Any) -> str:
    try:
        return json.dumps(values, sort_keys=True, default=str).lower()
    except TypeError:
        return str(values).lower()


def _has_jackson_mismatch_evidence(text: str) -> bool:
    has_missing_class = "tostringserializerbase" in text and (
        "noclassdeffounderror" in text
        or "classnotfoundexception" in text
        or "could not initialize class" in text
    )
    has_jackson_conflict = "jackson-" in text and "2.13.5" in text and _has_legacy_jackson_runtime_version(text)
    return has_missing_class and has_jackson_conflict


def _needs_direct_jackson_dependencies(text: str) -> bool:
    return _has_legacy_jackson_runtime_version(text)


def _has_legacy_jackson_runtime_version(text: str) -> bool:
    legacy_markers = (
        "jackson-databind" in text and "2.9.6" in text,
        "jackson-core" in text and "2.10.0" in text,
        "jackson-annotations" in text and "2.10.0" in text,
        "jackson-dataformat-csv" in text and "2.10.0" in text,
        "jackson-dataformat-xml" in text and "2.8.11" in text,
    )
    return any(legacy_markers)


def _is_stage1_boot27_pom(text: str) -> bool:
    lowered = text.lower()
    return ("<spring-boot.version>2.7." in lowered or "spring-boot-starter-parent" in lowered and "<version>2.7." in lowered)


def _patch_jackson_alignment_pom(text: str, *, add_direct_dependencies: bool) -> tuple[str, list[str], list[dict[str, Any]]]:
    operations: list[str] = []
    previews: list[dict[str, Any]] = []
    match = JACKSON_PROPERTY_PATTERN.search(text)
    if match is None:
        return text, [], []
    old_version = match.group("version").strip()
    updated = text
    if old_version != JACKSON_TARGET_VERSION:
        updated = JACKSON_PROPERTY_PATTERN.sub(
            lambda item: f"{item.group(1)}{JACKSON_TARGET_VERSION}{item.group(3)}",
            text,
            count=1,
        )
        operations.append("update fasterxml-jackson.version property to 2.13.5")
        previews.append({
            "target_file": "pom.xml",
            "operation": "replace_property",
            "replacement_count": 1,
            "before": f"<fasterxml-jackson.version>{old_version}</fasterxml-jackson.version>",
            "after": f"<fasterxml-jackson.version>{JACKSON_TARGET_VERSION}</fasterxml-jackson.version>",
        })
    if "<artifactId>jackson-bom</artifactId>" not in updated:
        updated = _insert_dependency_management(updated)
        if updated == "":
            return text, [], []
        operations.append("insert jackson-bom dependencyManagement import")
        previews.append({
            "target_file": "pom.xml",
            "operation": "insert_dependency_management",
            "replacement_count": 1,
            "before": "no jackson-bom dependencyManagement import",
            "after": "jackson-bom ${fasterxml-jackson.version} import",
        })
    if add_direct_dependencies:
        updated, added = _insert_direct_jackson_dependencies(updated)
        if added:
            operations.append("insert direct Jackson core dependencies")
            previews.append({
                "target_file": "pom.xml",
                "operation": "insert_direct_dependencies",
                "replacement_count": added,
                "before": "transitive Jackson conflict can select older databind/core/annotations",
                "after": "direct jackson-databind/core/annotations use ${fasterxml-jackson.version}",
            })
    return updated, operations, previews


def _insert_dependency_management(text: str) -> str:
    dependency = (
        "            <dependency>\n"
        "                <groupId>com.fasterxml.jackson</groupId>\n"
        "                <artifactId>jackson-bom</artifactId>\n"
        "                <version>${fasterxml-jackson.version}</version>\n"
        "                <type>pom</type>\n"
        "                <scope>import</scope>\n"
        "            </dependency>\n"
    )
    existing_block = _find_top_level_block(text, "dependencyManagement")
    if existing_block is not None:
        block_start, block_end, _, _ = existing_block
        block = text[block_start:block_end]
        dependencies = re.search(r"(<dependencies>)(?P<body>.*?)(</dependencies>)", block, re.DOTALL)
        if dependencies is None:
            return ""
        insert_at = block_start + dependencies.start(3)
        return text[:insert_at] + dependency + text[insert_at:]
    block = (
        "    <dependencyManagement>\n"
        "        <dependencies>\n"
        f"{dependency}"
        "        </dependencies>\n"
        "    </dependencyManagement>\n\n"
    )
    properties = _find_top_level_block(text, "properties")
    if properties is not None:
        insert_at = properties[1]
        return text[:insert_at] + "\n\n" + block + text[insert_at:]
    project_deps = _find_top_level_block(text, "dependencies")
    if project_deps is not None:
        return text[:project_deps[0]] + block + text[project_deps[0]:]
    return ""


def _insert_direct_jackson_dependencies(text: str) -> tuple[str, int]:
    additions: list[str] = []
    for artifact in ("jackson-databind", "jackson-core", "jackson-annotations"):
        if _has_direct_dependency(text, "com.fasterxml.jackson.core", artifact):
            continue
        additions.append(
            "        <dependency>\n"
            "            <groupId>com.fasterxml.jackson.core</groupId>\n"
            f"            <artifactId>{artifact}</artifactId>\n"
            "            <version>${fasterxml-jackson.version}</version>\n"
            "        </dependency>\n"
        )
    if not additions:
        return text, 0
    project_deps = _find_top_level_block(text, "dependencies")
    if project_deps is None:
        return text, 0
    insert_at = project_deps[2]
    return text[:insert_at] + "\n" + "".join(additions) + text[insert_at:], len(additions)


def _find_top_level_block(text: str, tag_name: str) -> tuple[int, int, int, int] | None:
    token_pattern = re.compile(r"<(?P<closing>/)?(?P<name>[A-Za-z_][A-Za-z0-9_.:-]*)(?P<attrs>[^>]*)>")
    stack: list[str] = []
    target: tuple[int, int, int] | None = None
    depth = 0
    for match in token_pattern.finditer(text):
        full = match.group(0)
        if full.startswith("<?") or full.startswith("<!"):
            continue
        name = match.group("name").split(":")[-1]
        closing = bool(match.group("closing"))
        self_closing = full.rstrip().endswith("/>")
        if closing:
            if target is not None and name == tag_name:
                depth -= 1
                if depth == 0:
                    return target[0], match.end(), target[1], match.start()
            if stack:
                stack.pop()
            continue
        is_project_child = len(stack) == 1 and stack[-1].split(":")[-1] == "project"
        if is_project_child and name == tag_name and target is None:
            target = (match.start(), match.end(), len(stack))
            depth = 1
            if self_closing:
                return match.start(), match.end(), match.end(), match.start()
        elif target is not None and name == tag_name:
            depth += 1
        if not self_closing:
            stack.append(name)
    return None


def _has_direct_dependency(text: str, group_id: str, artifact_id: str) -> bool:
    pattern = (
        r"<dependency>\s*"
        rf"(?=.*<groupId>\s*{re.escape(group_id)}\s*</groupId>)"
        rf"(?=.*<artifactId>\s*{re.escape(artifact_id)}\s*</artifactId>)"
        r".*?</dependency>"
    )
    return bool(re.search(pattern, text, re.DOTALL))


def _text_checksum(text: str) -> str:
    return f"sha256:{sha256_canonical_json({'text': text})}"


def _candidate_checksum_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    public = public_repair_apply_candidate(candidate) or {}
    return {
        "public": public,
        "after_checksum": candidate.get("_after_checksum") or candidate.get("_after_checksums") or "",
        "before_checksum": candidate.get("_before_checksum") or candidate.get("_before_checksums") or "",
        "file_changes": candidate.get("_file_changes") or [],
        "target_file_checksum": public.get("target_file_checksum", ""),
        "patch_checksum": public.get("patch_checksum", ""),
        "review_checksum": public.get("review_checksum", ""),
        "evidence_pack_checksum": candidate.get("_evidence_pack_checksum") or public.get("evidence_pack_checksum", ""),
    }


def _safe_relative(value: str) -> str:
    text = value.replace("\\", "/").strip()
    if not text or text.startswith("/") or PureWindowsPath(text).is_absolute():
        return ""
    parts = PurePosixPath(text).parts
    if any(part in ("", ".", "..") for part in parts):
        return ""
    return "/".join(parts)


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _rollback_filename(target_file: str) -> str:
    return target_file.replace("/", "__").replace("\\", "__")


def _require(condition: bool, reason: str, reasons: list[str]) -> None:
    if not condition and reason not in reasons:
        reasons.append(reason)


def _must(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)
