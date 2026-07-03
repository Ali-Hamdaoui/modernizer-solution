"""Governed sandbox repair candidate/apply for initMocks -> openMocks."""

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


def create_repair_apply_candidate(
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
    target = Path(target_path).resolve()
    sandbox = Path(sandbox_root).resolve()
    if not _is_contained(target, sandbox) or not target.is_file():
        return None
    checksum, _ = stream_sha256(target)
    pre_apply_checksum = f"sha256:{checksum}"
    before = target.read_text(encoding="utf-8", errors="replace")
    matches = list(INITMOCKS_PATTERN.finditer(before))
    if len(matches) != 1:
        return None
    after = INITMOCKS_PATTERN.sub(
        lambda match: f"MockitoAnnotations.openMocks({match.group(1)});",
        before,
        count=1,
    )
    patch_payload = {
        "recipe": BACKEND_RECIPE,
        "target_file": target_rel,
        "before_marker": "MockitoAnnotations.initMocks",
        "after_marker": "MockitoAnnotations.openMocks",
    }
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
        "_sandbox_root": str(sandbox),
        "_target_path": str(target),
        "_after_text": after,
        "_patch_payload": patch_payload,
    }
    candidate["candidate_checksum"] = f"sha256:{sha256_canonical_json(public_repair_apply_candidate(candidate))}"
    return candidate


def approve_repair_apply_candidate(candidate: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
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


def _must(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)
