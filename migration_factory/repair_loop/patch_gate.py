from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from migration_factory.control_tower.application.safe_diff_preview import (
    MAX_TOTAL_BYTES as SAFE_DIFF_MAX_TOTAL_BYTES,
    SafeDiffPreview,
    build_safe_diff_preview,
)
from migration_factory.control_tower.application.redaction import redact_public_value
from migration_factory.control_tower.domain.checksums import sha256_hex
from migration_factory.repair_loop.patch_apply import validate_patch_artifact
from migration_factory.repair_loop.rule_registry import evaluate_rule


PATCH_SOURCE_LLM_REVIEWED = "llm_reviewed"
POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1 = "generic_reviewed_llm_patch_v1"
REVIEWED_LLM_DECISION_ALLOWED = "ALLOWED"
REVIEWED_LLM_DECISION_BLOCKED = "BLOCKED"

REASON_UNSUPPORTED_FILE_EXTENSION = "unsupported_file_extension"
REASON_ROUTE_SCOPE_VIOLATION = "route_scope_violation"
REASON_TOO_MANY_TOUCHED_FILES = "too_many_touched_files"
REASON_TOO_MANY_CHANGED_LINES = "too_many_changed_lines"
REASON_DIFF_BYTE_SIZE_EXCEEDED = "diff_byte_size_exceeded"
REASON_DECLARED_CHANGED_FILES_MISMATCH = "declared_changed_files_mismatch"
REASON_RENAME_BLOCKED = "rename_blocked"
REASON_DELETE_BLOCKED = "delete_blocked"
REASON_PRODUCTION_CODE_DELETION = "production_code_deletion"
REASON_SECRET_LIKE_ADDED_CONTENT = "secret_like_added_content"
REASON_TEST_DISABLED_OR_SKIPPED = "test_disabled_or_skipped"
REASON_ASSERTION_WEAKENING = "assertion_weakening"
REASON_TRIVIALLY_PASSING_ASSERTION = "trivially_passing_assertion"
REASON_EXPECTED_EXCEPTION_MASKING = "expected_exception_masking"
REASON_DIRECT_TEST_FAILURE_MASKING = "direct_test_failure_masking"
REASON_MALFORMED_DIFF = "malformed_diff"
REASON_INVALID_ENCODING = "invalid_encoding"
REASON_APPLY_CHECK_FAILED = "apply_check_failed"
REASON_SHARED_PATH_VALIDATION_FAILED = "shared_path_validation_failed"
REASON_SECURITY_SENSITIVE_MODIFICATION = "security_sensitive_modification"
REASON_CONTEXT_BINDING_UNAVAILABLE = "context_binding_unavailable"
REASON_REVIEWER_DECISION_NOT_ACCEPTED = "reviewer_decision_not_accepted"
REASON_REVIEW_CHAIN_INVALID = "review_chain_invalid"
REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH = "reviewed_diff_checksum_mismatch"

MAX_REVIEWED_LLM_TOUCHED_FILES = 8
MAX_REVIEWED_LLM_CHANGED_LINES = 160
SUPPORTED_REVIEWED_LLM_EXTENSIONS = frozenset({
    ".java",
    ".xml",
    ".properties",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".txt",
})

BLOCKED_PARTS = {".git", ".migration", "target", "build", "node_modules"}
BLOCKED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "docker-compose.yml",
    "docker-compose.yaml",
    "Dockerfile",
    "Jenkinsfile",
}
BLOCKED_PREFIXES = (".github/workflows/", "deploy/", "deployment/", "k8s/", "helm/", "charts/")
SECRET_TOKENS = ("password", "secret", "token", "apikey", "api_key", "privatekey", "private_key", "keystore")
SECURITY_TOKENS = (
    "SecurityFilterChain",
    "HttpSecurity",
    "authorizeRequests",
    "authorizeHttpRequests",
    "antMatchers",
    "mvcMatchers",
    "requestMatchers",
    "permitAll",
    "denyAll",
    "authenticated",
    "hasRole",
    "hasAuthority",
    "OAuth2",
    "JWT",
    "Jwt",
    "csrf",
    "cors",
    "filter",
    "keystore",
    "SAML",
    "@PreAuthorize",
    "@PostAuthorize",
)
FORBIDDEN_SECURITY_PATTERNS = (
    re.compile(r"\+.*\.permitAll\s*\(", re.IGNORECASE),
    re.compile(r"-.*\.authenticated\s*\(", re.IGNORECASE),
    re.compile(r"-.*\.has(?:Role|Authority)\s*\(", re.IGNORECASE),
    re.compile(r"\+.*csrf\s*\([^)]*disable", re.IGNORECASE),
    re.compile(r"\+.*cors\s*\([^)]*disable", re.IGNORECASE),
    re.compile(r"\+.*(?:jwt|oauth2|resourceserver|auth).*disable", re.IGNORECASE),
)
SQL_SERVER_CLAIMS = ("sql server validated", "production db validated", "endpoint validated", "endpoint smoke validated")


@dataclass(frozen=True)
class PatchGateResult:
    status: str
    reason: str
    rule_id: str = ""
    risk: str = "BLOCKED"
    touched_paths: tuple[str, ...] = ()
    human_review_required: bool = False


@dataclass(frozen=True)
class ReviewedLlmPatchPolicyResult:
    decision: str
    reason_codes: tuple[str, ...]
    details: tuple[dict[str, Any], ...] = ()
    touched_paths: tuple[str, ...] = ()
    reviewed_diff_checksum: str = ""
    failure_evidence_checksum: str = ""
    context_checksum: str = ""
    base_repo_state_checksum: str = ""
    reviewer_output_checksum: str = ""
    review_chain_identity_checksum: str = ""
    job_id: str = ""
    stage_index: int = 0
    command_id: str = ""
    route: str = ""
    evidence_changed_files: tuple[str, ...] = ()
    declared_changed_files: tuple[str, ...] = ()
    allowed_route_scope: tuple[str, ...] = ()


def evaluate_reviewed_llm_patch(
    *,
    reviewed_diff_bytes: bytes,
    reviewed_diff_path: str | Path,
    reviewed_diff_checksum: str,
    sandbox_path: str | Path,
    run_dir: str | Path,
    legacy_path: str | Path,
    declared_changed_files: tuple[str, ...],
    allowed_route_scope: tuple[str, ...],
    evidence_changed_files: tuple[str, ...] = (),
    job_id: str,
    stage_index: int,
    command_id: str,
    route: str,
    failure_evidence_checksum: str,
    context_checksum: str,
    base_repo_state_checksum: str,
    reviewer_output_checksum: str,
    review_chain_identity_checksum: str,
) -> ReviewedLlmPatchPolicyResult:
    base = {
        "reviewed_diff_checksum": "sha256:" + sha256_hex(reviewed_diff_bytes),
        "failure_evidence_checksum": failure_evidence_checksum,
        "context_checksum": context_checksum,
        "base_repo_state_checksum": base_repo_state_checksum,
        "reviewer_output_checksum": reviewer_output_checksum,
        "review_chain_identity_checksum": review_chain_identity_checksum,
        "job_id": job_id,
        "stage_index": stage_index,
        "command_id": command_id,
        "route": route,
        "evidence_changed_files": tuple(sorted(_normalize_rel_path(path) for path in evidence_changed_files if path)),
        "declared_changed_files": tuple(sorted(_normalize_rel_path(path) for path in declared_changed_files if path)),
        "allowed_route_scope": tuple(sorted(dict.fromkeys(allowed_route_scope))),
    }
    reason_codes: list[str] = []
    details: list[dict[str, Any]] = []
    computed_reviewed_diff_checksum = base["reviewed_diff_checksum"]
    if computed_reviewed_diff_checksum != _sha256_prefixed_text(reviewed_diff_checksum):
        return ReviewedLlmPatchPolicyResult(
            decision=REVIEWED_LLM_DECISION_BLOCKED,
            reason_codes=(REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,),
            details=_bounded_details([
                {
                    "code": REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,
                    "provided_checksum": _sha256_prefixed_text(reviewed_diff_checksum),
                    "computed_checksum": computed_reviewed_diff_checksum,
                }
            ]),
            **base,
        )

    binding_errors = _reviewed_llm_context_binding_errors(
        sandbox_path=sandbox_path,
        run_dir=run_dir,
        legacy_path=legacy_path,
        allowed_route_scope=allowed_route_scope,
    )
    if binding_errors:
        binding_reason_codes = tuple(dict.fromkeys(str(error.get("code") or REASON_CONTEXT_BINDING_UNAVAILABLE) for error in binding_errors))
        return ReviewedLlmPatchPolicyResult(
            decision=REVIEWED_LLM_DECISION_BLOCKED,
            reason_codes=binding_reason_codes,
            details=_bounded_details(binding_errors),
            **base,
        )

    if len(reviewed_diff_bytes) > SAFE_DIFF_MAX_TOTAL_BYTES:
        reason_codes.append(REASON_DIFF_BYTE_SIZE_EXCEEDED)
        details.append({"code": REASON_DIFF_BYTE_SIZE_EXCEEDED, "limit_bytes": SAFE_DIFF_MAX_TOTAL_BYTES})

    try:
        diff_text = reviewed_diff_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ReviewedLlmPatchPolicyResult(
            decision=REVIEWED_LLM_DECISION_BLOCKED,
            reason_codes=tuple(dict.fromkeys([*reason_codes, REASON_INVALID_ENCODING])),
            details=tuple(details),
            **base,
        )

    if not is_unified_diff(diff_text):
        reason_codes.append(REASON_MALFORMED_DIFF)

    paths, path_errors = extract_touched_paths(diff_text)
    if path_errors:
        reason_codes.append(REASON_MALFORMED_DIFF)
        details.extend({"code": REASON_MALFORMED_DIFF, "detail": _bounded(error)} for error in path_errors)

    validation_errors = validate_patch_paths(
        paths,
        sandbox_path=sandbox_path,
        run_dir=run_dir,
        legacy_path=legacy_path,
    )
    if validation_errors:
        reason_codes.append(REASON_SHARED_PATH_VALIDATION_FAILED)
        details.extend({"code": _path_reason_code(error), "detail": _bounded(error)} for error in validation_errors)

    if len(paths) > MAX_REVIEWED_LLM_TOUCHED_FILES:
        reason_codes.append(REASON_TOO_MANY_TOUCHED_FILES)
        details.append({"code": REASON_TOO_MANY_TOUCHED_FILES, "limit": MAX_REVIEWED_LLM_TOUCHED_FILES})

    changed_lines = _changed_line_count(diff_text)
    if changed_lines > MAX_REVIEWED_LLM_CHANGED_LINES:
        reason_codes.append(REASON_TOO_MANY_CHANGED_LINES)
        details.append({"code": REASON_TOO_MANY_CHANGED_LINES, "limit": MAX_REVIEWED_LLM_CHANGED_LINES})

    unsupported = [path for path in paths if Path(path).suffix.lower() not in SUPPORTED_REVIEWED_LLM_EXTENSIONS]
    if unsupported:
        reason_codes.append(REASON_UNSUPPORTED_FILE_EXTENSION)
        details.extend({"code": REASON_UNSUPPORTED_FILE_EXTENSION, "path": path} for path in unsupported[:5])

    scope_errors = _route_scope_errors(paths=paths, allowed_route_scope=allowed_route_scope)
    if scope_errors:
        reason_codes.append(REASON_ROUTE_SCOPE_VIOLATION)
        details.extend({"code": REASON_ROUTE_SCOPE_VIOLATION, "path": path} for path in scope_errors[:5])

    declared = tuple(sorted(dict.fromkeys(path for path in declared_changed_files if path)))
    touched = tuple(sorted(dict.fromkeys(paths)))
    if declared and declared != touched:
        reason_codes.append(REASON_DECLARED_CHANGED_FILES_MISMATCH)
        details.append({"code": REASON_DECLARED_CHANGED_FILES_MISMATCH, "declared_count": len(declared), "touched_count": len(touched)})
    elif not declared:
        reason_codes.append(REASON_DECLARED_CHANGED_FILES_MISMATCH)
        details.append({"code": REASON_DECLARED_CHANGED_FILES_MISMATCH, "declared_count": 0, "touched_count": len(touched)})

    security_reason = security_patch_reason(paths, diff_text)
    if security_reason:
        reason_codes.append(REASON_SECURITY_SENSITIVE_MODIFICATION)
        details.append({"code": REASON_SECURITY_SENSITIVE_MODIFICATION, "detail": security_reason})

    preview = build_safe_diff_preview(
        proposal_id="reviewed-llm-policy",
        diff_ref=None,
        diff_text=diff_text,
        stored_diff_checksum=reviewed_diff_checksum.removeprefix("sha256:"),
    )
    structural_codes, structural_details = _reviewed_llm_structural_controls(preview, diff_text)
    reason_codes.extend(structural_codes)
    details.extend(structural_details)
    if preview.checksum_mismatch:
        reason_codes.append(REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH)
        details.append({"code": REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH, "detail": "safe diff preview checksum mismatch"})

    if not reason_codes:
        apply_ok, apply_reason = validate_patch_artifact(patch_path=reviewed_diff_path, cwd=sandbox_path)
        if not apply_ok:
            reason_codes.append(REASON_APPLY_CHECK_FAILED)
            details.append({"code": REASON_APPLY_CHECK_FAILED, "detail": _bounded(apply_reason)})

    deduped_codes = tuple(dict.fromkeys(reason_codes))
    return ReviewedLlmPatchPolicyResult(
        decision=REVIEWED_LLM_DECISION_BLOCKED if deduped_codes else REVIEWED_LLM_DECISION_ALLOWED,
        reason_codes=deduped_codes,
        details=_bounded_details(details),
        touched_paths=tuple(paths),
        **base,
    )


def blocked_reviewed_llm_policy_result(
    *,
    reason_code: str,
    detail: str = "",
    reviewed_diff_checksum: str = "",
    failure_evidence_checksum: str = "",
    context_checksum: str = "",
    base_repo_state_checksum: str = "",
    reviewer_output_checksum: str = "",
    review_chain_identity_checksum: str = "",
    job_id: str = "",
    stage_index: int = 0,
    command_id: str = "",
    route: str = "",
    evidence_changed_files: tuple[str, ...] = (),
    declared_changed_files: tuple[str, ...] = (),
    allowed_route_scope: tuple[str, ...] = (),
) -> ReviewedLlmPatchPolicyResult:
    details = ({"code": reason_code, "detail": _bounded(detail)},) if detail else ()
    return ReviewedLlmPatchPolicyResult(
        decision=REVIEWED_LLM_DECISION_BLOCKED,
        reason_codes=(reason_code,),
        details=details,
        reviewed_diff_checksum=reviewed_diff_checksum,
        failure_evidence_checksum=failure_evidence_checksum,
        context_checksum=context_checksum,
        base_repo_state_checksum=base_repo_state_checksum,
        reviewer_output_checksum=reviewer_output_checksum,
        review_chain_identity_checksum=review_chain_identity_checksum,
        job_id=job_id,
        stage_index=stage_index,
        command_id=command_id,
        route=route,
        evidence_changed_files=tuple(sorted(_normalize_rel_path(path) for path in evidence_changed_files if path)),
        declared_changed_files=tuple(sorted(_normalize_rel_path(path) for path in declared_changed_files if path)),
        allowed_route_scope=tuple(sorted(dict.fromkeys(allowed_route_scope))),
    )


def reviewed_llm_policy_payload(
    result: ReviewedLlmPatchPolicyResult,
    *,
    policy_checksum: str,
    evaluated_at: str,
) -> dict[str, Any]:
    return {
        "patch_source": PATCH_SOURCE_LLM_REVIEWED,
        "policy_id": POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
        "decision": result.decision,
        "reason_codes": list(result.reason_codes),
        "details": list(_redacted_bounded_details(result.details)),
        "touched_paths": sorted(result.touched_paths),
        "reviewed_diff_checksum": result.reviewed_diff_checksum,
        "failure_evidence_checksum": result.failure_evidence_checksum,
        "context_checksum": result.context_checksum,
        "base_repo_state_checksum": result.base_repo_state_checksum,
        "reviewer_output_checksum": result.reviewer_output_checksum,
        "review_chain_identity_checksum": result.review_chain_identity_checksum,
        "job_id": result.job_id,
        "stage_index": result.stage_index,
        "command_id": result.command_id,
        "route": result.route,
        "evidence_changed_files": sorted(result.evidence_changed_files),
        "declared_changed_files": sorted(result.declared_changed_files),
        "allowed_route_scope": sorted(result.allowed_route_scope),
        "policy_checksum": policy_checksum,
        "evaluated_at": evaluated_at,
    }


def evaluate_patch_proposal(
    *,
    proposal: dict[str, Any],
    sandbox_path: str | Path,
    run_dir: str | Path,
    legacy_path: str | Path,
    failure_classification: dict[str, Any] | None = None,
    h2_required: bool = False,
) -> PatchGateResult:
    rule_id = str(proposal.get("deterministic_rule_id") or "")
    risk = str(proposal.get("risk") or "").upper()
    requires_human_review = bool(proposal.get("requires_human_review", False))
    diff = str(proposal.get("unified_diff") or "")

    if not rule_id:
        return PatchGateResult("INVALID_PATCH", "patch proposal is missing deterministic_rule_id")
    if risk != "LOW":
        return PatchGateResult("HUMAN_REVIEW_REQUIRED", f"patch risk is not LOW: {risk}", rule_id, risk, human_review_required=True)
    if requires_human_review:
        return PatchGateResult("HUMAN_REVIEW_REQUIRED", "patch proposal requires human review", rule_id, risk, human_review_required=True)
    if not is_unified_diff(diff):
        return PatchGateResult("INVALID_PATCH", "patch proposal is not a unified diff", rule_id, risk)
    if _claims_out_of_scope(proposal):
        return PatchGateResult("BLOCKED", "patch proposal claims out-of-scope validation", rule_id, risk)

    paths, path_errors = extract_touched_paths(diff)
    if path_errors:
        return PatchGateResult("INVALID_PATCH", "; ".join(path_errors), rule_id, risk)
    validation_errors = validate_patch_paths(
        paths,
        sandbox_path=sandbox_path,
        run_dir=run_dir,
        legacy_path=legacy_path,
    )
    if validation_errors:
        return PatchGateResult("INVALID_PATCH", "; ".join(validation_errors), rule_id, risk, tuple(paths))

    security_reason = security_patch_reason(paths, diff)
    if security_reason:
        return PatchGateResult("HUMAN_REVIEW_REQUIRED", security_reason, rule_id, risk, tuple(paths), True)

    rule_decision = evaluate_rule(
        rule_id=rule_id,
        sandbox_path=sandbox_path,
        touched_paths=paths,
        unified_diff=diff,
        failure_classification=failure_classification,
        h2_required=h2_required,
    )
    if not rule_decision.allowed:
        status = "HUMAN_REVIEW_REQUIRED" if rule_decision.human_review_required else "BLOCKED"
        return PatchGateResult(status, rule_decision.reason, rule_id, risk, tuple(paths), rule_decision.human_review_required)
    return PatchGateResult("ALLOWED", rule_decision.reason, rule_id, risk, tuple(paths))


def is_unified_diff(diff: str) -> bool:
    text = diff.strip()
    if not text:
        return False
    if "GIT binary patch" in text or "Binary files " in text:
        return False
    return "diff --git " in text and "\n--- " in text and "\n+++ " in text and "\n@@" in text


def extract_touched_paths(diff: str) -> tuple[list[str], list[str]]:
    paths: list[str] = []
    errors: list[str] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) < 4:
                errors.append("malformed diff --git header")
                continue
            for raw in parts[2:4]:
                path = _strip_diff_prefix(raw)
                if path != "/dev/null":
                    paths.append(path)
        elif line.startswith("--- ") or line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0].strip()
            path = _strip_diff_prefix(raw)
            if path != "/dev/null":
                paths.append(path)
    deduped: list[str] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    if not deduped:
        errors.append("unified diff contains no touched paths")
    return deduped, errors


def validate_patch_paths(
    paths: list[str],
    *,
    sandbox_path: str | Path,
    run_dir: str | Path,
    legacy_path: str | Path,
) -> list[str]:
    sandbox = Path(sandbox_path).resolve()
    run_root = Path(run_dir).resolve()
    legacy = Path(legacy_path).resolve()
    errors: list[str] = []
    for rel in paths:
        errors.extend(_relative_path_errors(rel))
        if errors and any(rel in error for error in errors):
            continue
        candidate = (sandbox / PurePosixPath(rel)).resolve()
        if not candidate.is_relative_to(sandbox):
            errors.append(f"patch path escapes sandbox: {rel}")
        if candidate == legacy or candidate.is_relative_to(legacy):
            errors.append(f"patch path touches legacy source: {rel}")
        if candidate == run_root:
            errors.append(f"patch path touches run root: {rel}")
        if _has_symlink_parent(candidate, sandbox):
            errors.append(f"patch path traverses a symlink: {rel}")
    return errors


def reviewed_llm_policy_checksum_input(result: ReviewedLlmPatchPolicyResult) -> dict[str, Any]:
    return {
        "patch_source": PATCH_SOURCE_LLM_REVIEWED,
        "policy_id": POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
        "decision": result.decision,
        "reason_codes": sorted(result.reason_codes),
        "touched_paths": sorted(_normalize_rel_path(path) for path in result.touched_paths if path),
        "reviewed_diff_checksum": result.reviewed_diff_checksum,
        "failure_evidence_checksum": result.failure_evidence_checksum,
        "context_checksum": result.context_checksum,
        "base_repo_state_checksum": result.base_repo_state_checksum,
        "reviewer_output_checksum": result.reviewer_output_checksum,
        "review_chain_identity_checksum": result.review_chain_identity_checksum,
        "job_id": result.job_id,
        "stage_index": result.stage_index,
        "command_id": result.command_id,
        "route": result.route,
        "allowed_route_scope": sorted(result.allowed_route_scope),
    }


def reviewed_llm_allowed_route_scope(*, route: str, stage_index: int) -> tuple[str, ...]:
    if route != "llm_reviewed_unknown" or stage_index < 1:
        return ()
    return ("sandbox_relative:**",)


def security_patch_reason(paths: list[str], diff: str) -> str:
    security_path = any(_looks_security_path(path) for path in paths)
    security_content = any(token.lower() in diff.lower() for token in SECURITY_TOKENS)
    if security_path or security_content:
        return "Spring Security or authentication-sensitive patch requires human review"
    for pattern in FORBIDDEN_SECURITY_PATTERNS:
        if pattern.search(diff):
            return "patch attempts to weaken Spring Security"
    return ""


def _relative_path_errors(path: str) -> list[str]:
    errors: list[str] = []
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    win = PureWindowsPath(path)
    lowered = normalized.lower()
    if normalized.startswith("/") or win.is_absolute() or re.match(r"^[a-zA-Z]:", path) or normalized.startswith("//"):
        errors.append(f"absolute patch path rejected: {path}")
    if ".." in pure.parts:
        errors.append(f"path traversal rejected: {path}")
    if any(part in BLOCKED_PARTS for part in pure.parts):
        errors.append(f"blocked generated/internal path rejected: {path}")
    if pure.name in BLOCKED_FILE_NAMES:
        errors.append(f"blocked deployment/env file rejected: {path}")
    if any(lowered.startswith(prefix) for prefix in BLOCKED_PREFIXES):
        errors.append(f"blocked deployment/release path rejected: {path}")
    if any(token in lowered for token in SECRET_TOKENS):
        errors.append(f"secret-like path rejected: {path}")
    return errors


def _strip_diff_prefix(raw: str) -> str:
    path = raw.strip().strip('"')
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _looks_security_path(path: str) -> bool:
    lowered = path.lower()
    return "security" in lowered or "auth" in lowered or "jwt" in lowered or "saml" in lowered


def _has_symlink_parent(path: Path, sandbox: Path) -> bool:
    current = sandbox
    try:
        rel_parts = path.relative_to(sandbox).parts
    except ValueError:
        return True
    for part in rel_parts:
        current = current / part
        if current.exists() and current.is_symlink():
            return True
    return False


def _claims_out_of_scope(proposal: dict[str, Any]) -> bool:
    text = " ".join(
        str(value)
        for value in (
            proposal.get("description", ""),
            proposal.get("expected_validation", []),
            proposal.get("limitations", []),
        )
    ).lower()
    return any(claim in text for claim in SQL_SERVER_CLAIMS)


def _reviewed_llm_context_binding_errors(
    *,
    sandbox_path: str | Path,
    run_dir: str | Path,
    legacy_path: str | Path,
    allowed_route_scope: tuple[str, ...],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    try:
        sandbox = Path(sandbox_path).resolve(strict=True)
        run_root = Path(run_dir).resolve(strict=True)
        legacy = Path(legacy_path).resolve(strict=True)
    except (OSError, TypeError):
        return [{"code": REASON_CONTEXT_BINDING_UNAVAILABLE, "detail": "required path binding is unavailable"}]
    if not sandbox.is_dir():
        errors.append({"code": REASON_CONTEXT_BINDING_UNAVAILABLE, "detail": "sandbox is not a directory"})
    if not run_root.is_dir():
        errors.append({"code": REASON_CONTEXT_BINDING_UNAVAILABLE, "detail": "run root is not a directory"})
    if not legacy.is_dir():
        errors.append({"code": REASON_CONTEXT_BINDING_UNAVAILABLE, "detail": "legacy root is not a directory"})
    if sandbox == legacy or sandbox.is_relative_to(legacy):
        errors.append({"code": REASON_CONTEXT_BINDING_UNAVAILABLE, "detail": "sandbox overlaps legacy root"})
    if not allowed_route_scope:
        errors.append({"code": REASON_ROUTE_SCOPE_VIOLATION, "detail": "allowed route scope is empty"})
    return errors


def _changed_line_count(diff: str) -> int:
    return sum(
        1
        for line in diff.splitlines()
        if (line.startswith("+") and not line.startswith("+++")) or (line.startswith("-") and not line.startswith("---"))
    )


def _route_scope_errors(*, paths: list[str], allowed_route_scope: tuple[str, ...]) -> list[str]:
    normalized_scope = tuple(str(scope) for scope in allowed_route_scope if str(scope).strip())
    if not normalized_scope:
        return list(paths)
    errors: list[str] = []
    for path in paths:
        normalized = _normalize_rel_path(path)
        if not _path_matches_allowed_scope(normalized, normalized_scope):
            errors.append(path)
    return errors


def _path_matches_allowed_scope(path: str, allowed_route_scope: tuple[str, ...]) -> bool:
    exact = set()
    patterns = []
    for scope in allowed_route_scope:
        if scope == "sandbox_only":
            continue
        if scope.startswith("sandbox_relative:"):
            patterns.append(scope.removeprefix("sandbox_relative:"))
        else:
            exact.add(_normalize_rel_path(scope))
    return path in exact or any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _normalize_rel_path(path: str) -> str:
    return PurePosixPath(str(path).replace("\\", "/")).as_posix().lstrip("./")


def _path_reason_code(error: str) -> str:
    text = error.lower()
    if "secret-like" in text:
        return REASON_SECRET_LIKE_ADDED_CONTENT
    if "generated/internal" in text or "deployment" in text:
        return REASON_SHARED_PATH_VALIDATION_FAILED
    if "traversal" in text or "absolute" in text or "escapes" in text or "symlink" in text:
        return REASON_SHARED_PATH_VALIDATION_FAILED
    return REASON_SHARED_PATH_VALIDATION_FAILED


def _reviewed_llm_structural_controls(preview: SafeDiffPreview, diff_text: str) -> tuple[list[str], list[dict[str, Any]]]:
    codes: list[str] = []
    details: list[dict[str, Any]] = []
    if preview.truncated:
        codes.append(REASON_MALFORMED_DIFF)
        details.append({"code": REASON_MALFORMED_DIFF, "detail": "safe diff preview truncated"})
    lowered_diff = diff_text.lower()
    if "\nrename from " in lowered_diff or "\nrename to " in lowered_diff:
        codes.append(REASON_RENAME_BLOCKED)
    for file in preview.files:
        path = file.path
        if file.change_type == "renamed":
            codes.append(REASON_RENAME_BLOCKED)
            details.append({"code": REASON_RENAME_BLOCKED, "path": path})
        if file.change_type == "deleted":
            codes.append(REASON_DELETE_BLOCKED)
            details.append({"code": REASON_DELETE_BLOCKED, "path": path})
        for hunk in file.hunks:
            added = [line.text for line in hunk.lines if line.kind == "addition"]
            removed = [line.text for line in hunk.lines if line.kind == "deletion"]
            context = [line.text for line in hunk.lines if line.kind == "context"]
            if _is_production_path(path) and removed and not added:
                codes.append(REASON_PRODUCTION_CODE_DELETION)
                details.append({"code": REASON_PRODUCTION_CODE_DELETION, "path": path})
            if _secret_like_added_content(added):
                codes.append(REASON_SECRET_LIKE_ADDED_CONTENT)
                details.append({"code": REASON_SECRET_LIKE_ADDED_CONTENT, "path": path})
            test_codes = _test_behavior_reason_codes(path=path, added=added, removed=removed, context=context)
            for code in test_codes:
                codes.append(code)
                details.append({"code": code, "path": path})
    return list(dict.fromkeys(codes)), details


def _is_production_path(path: str) -> bool:
    normalized = _normalize_rel_path(path).lower()
    return "/src/main/" in f"/{normalized}" or normalized.startswith("src/main/")


def _is_test_path(path: str) -> bool:
    normalized = _normalize_rel_path(path).lower()
    return "/src/test/" in f"/{normalized}" or normalized.startswith("src/test/") or normalized.endswith("test.java")


def _secret_like_added_content(added: list[str]) -> bool:
    secret_assignment = re.compile(
        r"(?i)\b(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)\b\s*[:=]\s*['\"]?[^'\"\s]+"
    )
    return any(secret_assignment.search(line) for line in added)


def _test_behavior_reason_codes(
    *,
    path: str,
    added: list[str],
    removed: list[str],
    context: list[str],
) -> list[str]:
    if not _is_test_path(path):
        return []
    added_text = "\n".join(added)
    removed_text = "\n".join(removed)
    surrounding = "\n".join([*context, *removed, *added])
    added_lower = added_text.lower()
    removed_lower = removed_text.lower()
    surrounding_lower = surrounding.lower()
    codes: list[str] = []
    if any(marker in added_lower for marker in ("@disabled", "assumptions.", "assumetrue", "assumefalse", "ignore(")):
        codes.append(REASON_TEST_DISABLED_OR_SKIPPED)
    if any(marker in added_lower for marker in ("-dskiptests", "maven.test.skip", "skipits")):
        codes.append(REASON_DIRECT_TEST_FAILURE_MASKING)
    if _adds_trivial_assertion(added_text):
        codes.append(REASON_TRIVIALLY_PASSING_ASSERTION)
    if _weakens_assertion(removed_text, added_text):
        codes.append(REASON_ASSERTION_WEAKENING)
    if "assertthrows" in removed_lower and (
        "assertdoesnotthrow" in added_lower
        or "try {" in added_lower
        or "catch" in surrounding_lower and any(marker in added_lower for marker in ("return;", "//", "asserttrue(true"))
    ):
        codes.append(REASON_EXPECTED_EXCEPTION_MASKING)
    if any(marker in removed_lower for marker in ("fail(", "assertfalse(", "assertthrows(", "m1_unknown_runtime_sentinel")) and (
        _adds_trivial_assertion(added_text) or "return;" in added_lower or "@disabled" in added_lower
    ):
        codes.append(REASON_DIRECT_TEST_FAILURE_MASKING)
    if "m1_unknown_runtime_sentinel" in surrounding_lower and (
        _adds_trivial_assertion(added_text)
        or "assertdoesnotthrow" in added_lower
        or "@disabled" in added_lower
        or "return;" in added_lower
    ):
        codes.extend([
            REASON_ASSERTION_WEAKENING,
            REASON_DIRECT_TEST_FAILURE_MASKING,
            REASON_EXPECTED_EXCEPTION_MASKING,
        ])
    return list(dict.fromkeys(codes))


def _adds_trivial_assertion(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).lower()
    return any(
        marker in compact
        for marker in (
            "asserttrue(true)",
            "assertthat(true).istrue()",
            "assertequals(1,1)",
            "assertequals(true,true)",
            "assertnotnull(new",
        )
    )


def _weakens_assertion(removed_text: str, added_text: str) -> bool:
    removed_lower = removed_text.lower()
    added_lower = added_text.lower()
    strong_removed = any(
        marker in removed_lower
        for marker in ("assertequals", "assertthrows", "assertfalse", "assertthat", "fail(", "m1_unknown_runtime_sentinel")
    )
    weak_added = _adds_trivial_assertion(added_text) or "assertdoesnotthrow" in added_lower
    return strong_removed and weak_added


def _bounded_details(details: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for detail in details[:10]:
        safe: dict[str, Any] = {}
        for key, value in detail.items():
            if isinstance(value, str):
                safe[key] = _bounded(value)
            elif isinstance(value, (int, bool)):
                safe[key] = value
            else:
                safe[key] = _bounded(str(value))
        result.append(safe)
    return tuple(result)


def _redacted_bounded_details(details: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    redacted = redact_public_value(list(details))
    if not isinstance(redacted, list):
        return ()
    safe_details: list[dict[str, Any]] = []
    for detail in redacted[:10]:
        if isinstance(detail, dict):
            safe_details.append({str(key): _bounded(str(value)) for key, value in detail.items()})
    return tuple(safe_details)


def _bounded(value: str, limit: int = 240) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text[:limit]


def _sha256_prefixed_text(value: Any) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        return text
    return f"sha256:{text}" if text else ""
