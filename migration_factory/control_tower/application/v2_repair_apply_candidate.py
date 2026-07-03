"""R8/R8.1 governed sandbox repair candidate/apply for initMocks -> openMocks."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, stream_sha256, utc_now_text


SUPPORTED_FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"
BACKEND_RECIPE = "INITMOCKS_TO_OPENMOCKS"
INITMOCKS_PATTERN = re.compile(r"MockitoAnnotations\.initMocks\(([^)]*)\);")
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

    before = target.read_text(encoding="utf-8", errors="replace")
    rollback_dir = sandbox / ".migration" / "rollback" / str(candidate["repair_candidate_id"])
    rollback_dir.mkdir(parents=True, exist_ok=True)
    rollback_file = rollback_dir / _rollback_filename(str(candidate.get("target_file") or "target.txt"))
    rollback_file.write_text(before, encoding="utf-8")

    try:
        after = str(candidate.get("_after_text") or "")
        _must(after and after != before, "backend_recipe_noop")
        target.write_text(after, encoding="utf-8")
        verified, verification_log = verification_runner(target) if verification_runner else _default_verification(target)
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
        return _execution_result(candidate, approval, "verified", f"sha256:{post_checksum}", "passed", verification_log, "not_needed", proof)
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
        return "Repair candidate: none. Failure remains human-gated. Downstream remains blocked until backend proof exists."
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

    reasons: list[str] = []
    _require(classification.get("failure_type") == SUPPORTED_FAMILY, "classification_not_supported_family", reasons)
    _require(draft.get("proposal_status") == "drafted_non_actionable", "deterministic_draft_missing", reasons)
    _require(review.get("verdict") == "accepted_for_future_apply_gate", "deterministic_reviewer_not_accepted", reasons)
    _require(review.get("checksum_verification_status") == "verified", "deterministic_review_checksum_not_verified", reasons)
    _require(proposer.get("schema_validation_status") == "validated", "llm_proposer_schema_not_validated", reasons)
    _require(reviewer.get("schema_validation_status") == "validated", "llm_reviewer_schema_not_validated", reasons)
    _require(proposer_output.get("required_backend_recipe") == BACKEND_RECIPE, "llm_proposer_recipe_not_supported", reasons)
    _require(reviewer_output.get("verdict") == "advisory_accept", "llm_reviewer_not_advisory_accept", reasons)
    if reasons:
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
    patch_payload = {
        "recipe": BACKEND_RECIPE,
        "target_file": target_rel,
        "before_marker": "MockitoAnnotations.initMocks",
        "after_marker": "MockitoAnnotations.openMocks",
    }
    if proposed_diff_checksum:
        patch_payload["proposed_diff_checksum"] = proposed_diff_checksum
    candidate = {
        "job_id": job_id,
        "stage_index": stage_index,
        "repair_candidate_id": f"repair-candidate-{uuid4().hex[:12]}",
        "status": "pending_human_approval",
        "family": SUPPORTED_FAMILY,
        "patch_source": "backend_deterministic_recipe",
        "llm_source": "advisory_only",
        "target_file": target_rel,
        "pre_apply_checksum": pre_apply_checksum,
        "target_file_checksum": pre_apply_checksum,
        "patch_checksum": f"sha256:{sha256_canonical_json(patch_payload)}",
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
        "_sandbox_root": str(sandbox_root),
        "_target_path": str(target_path),
        "_after_text": after,
        "_patch_payload": patch_payload,
    }
    candidate["candidate_checksum"] = f"sha256:{sha256_canonical_json(public_repair_apply_candidate(candidate))}"
    return candidate


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
