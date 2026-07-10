"""F5: Repair review-chain producer — extends the F2 review-chain pattern for repair.

Deterministic repair artifact -> Primary Repair LLM (PROPOSER) -> Reviewer Repair LLM (REVIEWER)
-> Final reviewed repair diff artifact.

Core rule: A model reviews another model for repair. Reviewer is mandatory.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_review_chain_contracts import (
    _check_forbidden_fields,
    _check_execution_instruction,
)
from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureEvidence,
    FailureSource,
    failure_evidence_to_dict,
)
from migration_factory.repair_loop.repair_context import (
    RepairContextPack,
    compute_base_repo_state_checksum,
    compute_context_pack_checksum,
    context_pack_to_dict,
)


class RepairReviewChainProductionError(RuntimeError):
    pass


_DIAGNOSTIC_SECRET_VALUE_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|token|password|secret|private[_-]?key|credential)[\"']?\s*[:=]\s*)([\"'][^\"']*[\"']|[^,\s}]+)"
)
from migration_factory.repair_loop.patch_gate import extract_touched_paths


def _safe_diagnostic_text(value: Any, *, limit: int = 1000) -> str:
    text = redact_model_summary(str(value or ""))
    text = _DIAGNOSTIC_SECRET_VALUE_RE.sub(r"\1[redacted-secret]", text)
    return text[:limit]


# ── F5-T3: Deterministic repair artifact ─────────────────────────────


class RepairArtifactPhase:
    REPAIR = "repair"


def _build_deterministic_repair_payload(
    *,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    source_profile: str = "",
    target_profile: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "phase": RepairArtifactPhase.REPAIR,
        "job_id": context_pack.job_id,
        "stage_index": context_pack.stage_index,
        "failure_source": failure_evidence.failure_source.value,
        "failure_summary": failure_evidence.failure_summary,
        "normalized_compiler_errors": [
            e.message for e in failure_evidence.compiler_errors
        ],
        "normalized_test_failures": [
            t.message for t in failure_evidence.test_failures
        ],
        "changed_files": list(failure_evidence.changed_files),
        "source_profile": source_profile or failure_evidence.source_profile,
        "target_profile": target_profile or failure_evidence.target_profile,
        "context_pack_checksum": context_pack.context_pack_checksum,
        "failure_evidence_checksum": failure_evidence.content_checksum,
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "accepted_artifact_checksums": list(failure_evidence.accepted_artifact_checksums),
        "allowed_repair_mode_hints": ["source_patch", "dependency_patch", "config_patch"],
        "created_at": utc_now_text(),
    }


# ── F5-T4/T5: Primary/Reviewer repair contracts ─────────────────────


def _primary_repair_prompt(context_pack: RepairContextPack, deterministic_checksum: str) -> str:
    context_dict = context_pack_to_dict(context_pack)
    source_contexts = context_dict.get("source_contexts") or []
    source_section = ""
    if source_contexts:
        parts = []
        for sc in source_contexts:
            parts.append(
                f"--- {sc['path']} (lines {sc['start_line']}-{sc['end_line']}, "
                f"reason: {sc['reason_included']}) ---\n"
                f"{sc['content']}\n"
                f"--- end {sc['path']} ---"
            )
        source_section = "\n\nSOURCE CONTEXT:\n" + "\n\n".join(parts)
    return (
        "You are the AMF-252 repair proposer.\n"
        "Your task is to produce a minimal, safe, raw Git unified diff that fixes the failing build/test evidence.\n\n"
        "Return ONLY valid JSON. Do NOT wrap in Markdown fences or code blocks. "
        "Do NOT include any text before or after the JSON.\n\n"
        "Required JSON keys: "
        "root_cause (string), fix_strategy (string), changed_files (list of file paths), "
        "proposed_diff (unified diff string), confidence (0.0-1.0), rationale (string). "
        "deterministic_rule_id and risk are optional metadata and must never block diff generation.\n"
        "Only set no_fix_reason when the provided context lacks enough evidence to safely create a patch.\n"
        "If no_fix_reason is set, explain exactly which required evidence is missing.\n\n"
        "CRITICAL PATCH FORMAT CONTRACT\n"
        "- proposed_diff MUST contain raw Git unified diff text.\n"
        "- The first non-whitespace content MUST be: diff --git\n"
        "- For every modified existing file, require:\n"
        "  diff --git a/<relative-path> b/<relative-path>\n"
        "  --- a/<relative-path>\n"
        "  +++ b/<relative-path>\n"
        "  @@ -oldStart,oldCount +newStart,newCount @@\n"
        "- Repository paths inside the diff must be sandbox/repository-relative paths.\n"
        "- This Codex/apply_patch dialect is invalid for AMF-252.\n"
        "- If you cannot safely produce the required Git unified diff, return:\n"
        "  proposed_diff = \"\"\n"
        "  deterministic_rule_id = \"no_safe_rule\"\n"
        "  no_fix_reason = \"<specific reason>\"\n\n"
        "CONSTRAINTS:\n"
        "- Do NOT include commands, paths to execute, provider data, endpoint data, "
        "env data, deployment data, or approvals.\n"
        "- Do NOT include absolute Windows paths.\n"
        "- Do NOT include absolute POSIX host paths.\n"
        "- Do NOT include markdown code fences in proposed_diff.\n"
        "- Do NOT include explanatory prose inside proposed_diff.\n"
        "- Do NOT include plain source code without diff headers.\n"
        "- Do NOT include JSON embedded inside proposed_diff.\n"
        "- Do NOT include any Codex/apply_patch markers such as:\n"
        "  *** Begin Patch\n"
        "  *** Update File:\n"
        "  *** Add File:\n"
        "  *** Delete File:\n"
        "  *** End Patch\n"
        "- In normal repair mode, proposed_diff must be non-empty.\n"
        "- Empty diff is an unavailable outcome, not an applyable proposal.\n"
        "- Do not skip or disable tests as a fix.\n"
        "- The fix must stay within the sandbox scope and declared changed files.\n\n"
        "VALID:\n"
        "diff --git a/src/main/java/com/example/Foo.java b/src/main/java/com/example/Foo.java\n"
        "--- a/src/main/java/com/example/Foo.java\n"
        "+++ b/src/main/java/com/example/Foo.java\n"
        "@@ -10,1 +10,1 @@\n"
        "-    final Sort sort = new Sort(direction, column);\n"
        "+    final Sort sort = Sort.by(direction, column);\n\n"
        "INVALID:\n"
        "*** Begin Patch\n"
        "*** Update File: src/main/java/com/example/Foo.java\n"
        "@@\n"
        "- old\n"
        "+ new\n"
        "*** End Patch\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Source context is provided below with exact file contents bounded around error locations.\n"
        f"Use this source context to produce an exact applicable unified diff.\n"
        f"{source_section}\n\n"
        f"Context:\n{json.dumps(context_dict, sort_keys=True)}"
    )


def _reviewer_repair_prompt(
    primary_output: dict[str, Any],
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
) -> str:
    return (
        "You are the AMF-252 final repair author and reviewer. Inspect exact failure "
        "evidence, bounded source context, proposer reasoning, and proposer diff. "
        "Correct or replace proposer work and return the best final raw Git unified diff.\n\n"
        "Return JSON with keys:\n"
        "  proposed_diff (raw unified diff; empty only when no usable repair exists), "
        "changed_files (list), review_notes (list), confidence (0.0-1.0), "
        "optional decision/risks/policy_concerns, "
        "reviewed_context_checksum, reviewed_primary_output_checksum, "
        "reviewed_diff_checksum.\n\n"
        "CONSTRAINTS:\n"
        "- proposed_diff must be raw Git unified diff, never Markdown fences.\n"
        "- Improve/correct proposer diff when evidence shows it is incomplete or wrong.\n"
        "- Use repository-relative paths only; reject commands, secrets, test disabling, "
        "absolute paths, traversal, or deployment/environment changes.\n"
        "- Bind your decision to the exact checksums provided.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Context pack checksum: {context_checksum}\n"
        f"Primary output checksum: {primary_checksum}\n"
        f"Proposed diff checksum: {diff_checksum}\n"
        f"FAILURE EVIDENCE:\n{json.dumps(failure_evidence_to_dict(failure_evidence), sort_keys=True)}\n\n"
        f"SOURCE/CONTEXT PACK:\n{json.dumps(context_pack_to_dict(context_pack), sort_keys=True)}\n\n"
        f"PROPOSER OUTPUT:\n{json.dumps(primary_output, sort_keys=True)}"
    )


def _coerce_primary_repair_output(content: str) -> dict[str, Any]:
    content = str(content)
    if not content.strip():
        raise RepairReviewChainProductionError(
            "invalid_response_missing_content: primary repair output is empty"
        )
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RepairReviewChainProductionError(
                f"invalid_response_non_json: parsed value is {type(parsed).__name__}, expected dict"
            )
    except json.JSONDecodeError as exc:
        snippet = content[:1000]
        raise RepairReviewChainProductionError(
            f"invalid_response_non_json: JSON parse error — {exc.msg} "
            f"(line {exc.lno}, col {exc.colpos}). "
            f"Content length={len(content)}, first 1000 chars: {snippet}"
        )

    required = {"root_cause", "fix_strategy", "changed_files", "proposed_diff", "confidence", "rationale"}
    missing = required - set(parsed.keys())
    if missing:
        raise RepairReviewChainProductionError(
            f"invalid_response_schema_validation_failed: missing required fields: {sorted(missing)}"
        )

    proposed_diff = str(parsed.get("proposed_diff") or "")
    if not proposed_diff.strip():
        raise RepairReviewChainProductionError(
            "invalid_response_missing_proposed_diff: proposed_diff is empty or missing"
        )
    if "```" in proposed_diff:
        raise RepairReviewChainProductionError(
            "invalid_response_markdown_fenced_diff: proposed_diff is wrapped in Markdown fences"
        )
    if not _looks_like_unified_diff(proposed_diff):
        raise RepairReviewChainProductionError(
            "invalid_response_non_unified_diff: proposed_diff does not contain unified diff markers"
        )

    return parsed


def _coerce_reviewer_repair_output(
    content: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
) -> dict[str, Any]:
    content = str(content)
    if not content.strip():
        raise RepairReviewChainProductionError(
            "invalid_response_missing_content: reviewer output is empty"
        )
    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RepairReviewChainProductionError(
                f"invalid_response_non_json: reviewer parsed value is {type(parsed).__name__}, expected dict"
            )
    except json.JSONDecodeError as exc:
        snippet = content[:1000]
        raise RepairReviewChainProductionError(
            f"invalid_response_non_json: reviewer JSON parse error — {exc.msg} "
            f"(line {exc.lno}, col {exc.colpos}). "
            f"Content length={len(content)}, first 1000 chars: {snippet}"
        )

    proposed_diff = str(parsed.get("proposed_diff") or "")
    decision = str(parsed.get("decision") or "").strip().lower()
    if decision not in {"", "accept", "revise", "reject"}:
        raise RepairReviewChainProductionError(f"invalid reviewer decision {decision!r}")
    if decision == "revise":
        decision = "request_revision"

    return {
        "decision": decision,
        "proposed_diff": proposed_diff,
        "changed_files": parsed.get("changed_files") if isinstance(parsed.get("changed_files"), list) else [],
        "notes": parsed.get("review_notes") if isinstance(parsed.get("review_notes"), list) else parsed.get("notes") if isinstance(parsed.get("notes"), list) else [],
        "confidence": float(parsed.get("confidence", 0.8)),
        "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
        "policy_concerns": parsed.get("policy_concerns") if isinstance(parsed.get("policy_concerns"), list) else [],
        "reviewed_context_checksum": str(parsed.get("reviewed_context_checksum") or context_checksum),
        "reviewed_primary_output_checksum": str(parsed.get("reviewed_primary_output_checksum") or primary_checksum),
        "reviewed_diff_checksum": str(parsed.get("reviewed_diff_checksum") or diff_checksum),
        "review_dimensions": parsed.get("review_dimensions") if isinstance(parsed.get("review_dimensions"), dict) else {},
    }


def _compute_primary_repair_checksum(output: dict[str, Any]) -> str:
    payload = {
        "root_cause": str(output.get("root_cause", "")),
        "fix_strategy": str(output.get("fix_strategy", "")),
        "changed_files": list(output.get("changed_files", [])),
        "proposed_diff": str(output.get("proposed_diff", "")),
        "deterministic_rule_id": str(output.get("deterministic_rule_id", "")),
        "risk": str(output.get("risk", "")),
        "confidence": float(output.get("confidence", 0.0)),
        "rationale": str(output.get("rationale", "")),
        "no_fix_reason": str(output.get("no_fix_reason", "")),
    }
    return sha256_canonical_json(payload)


def _compute_reviewer_repair_checksum(output: dict[str, Any]) -> str:
    payload = {
        "decision": str(output.get("decision", "")),
        "proposed_diff": str(output.get("proposed_diff", "")),
        "changed_files": list(output.get("changed_files", [])),
        "notes": list(output.get("notes", [])),
        "confidence": float(output.get("confidence", 0.0)),
        "risks": list(output.get("risks", [])),
        "policy_concerns": list(output.get("policy_concerns", [])),
        "reviewed_context_checksum": str(output.get("reviewed_context_checksum", "")),
        "reviewed_primary_output_checksum": str(output.get("reviewed_primary_output_checksum", "")),
        "reviewed_diff_checksum": str(output.get("reviewed_diff_checksum", "")),
    }
    return sha256_canonical_json(payload)


def _validate_primary_repair_output(output: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    for key in ("root_cause", "fix_strategy", "proposed_diff"):
        if not isinstance(output.get(key), str) or not output[key].strip():
            failures.append(f"empty or missing required field {key!r}")

    changed = output.get("changed_files")
    if not isinstance(changed, list) or not all(isinstance(f, str) for f in changed):
        failures.append("changed_files must be a list of strings")

    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        failures.append("confidence must be a float between 0.0 and 1.0")

    diff = str(output.get("proposed_diff", ""))
    if diff.strip():
        if "```" in diff:
            failures.append("proposed_diff appears to be Markdown fenced")
        elif not _looks_like_unified_diff(diff):
            failures.append("proposed_diff does not appear to be a valid unified diff")

    forbidden_paths = _check_forbidden_paths_in_diff(diff)
    if forbidden_paths:
        failures.extend(forbidden_paths)

    forbidden_fields = _check_forbidden_keys(output)
    if forbidden_fields:
        failures.extend(forbidden_fields)

    return failures


def _validate_candidate_diff(
    *,
    proposed_diff: str,
    changed_files: list[Any],
    role: str,
) -> list[str]:
    """Validate model diff shape/scope without semantic policy gating."""
    failures: list[str] = []
    if not proposed_diff.strip():
        failures.append(f"{role} proposed_diff is empty")
    elif "```" in proposed_diff:
        failures.append(f"{role} proposed_diff is Markdown fenced")
    elif not _looks_like_unified_diff(proposed_diff):
        failures.append(f"{role} proposed_diff is not a usable unified diff")
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        failures.append(f"{role} changed_files must be a list of strings")
    else:
        touched_paths, path_errors = extract_touched_paths(proposed_diff)
        if path_errors:
            failures.extend(f"{role} {error}" for error in path_errors)
        declared = {str(path).replace("\\", "/").removeprefix("a/").removeprefix("b/") for path in changed_files}
        actual = {str(path).replace("\\", "/") for path in touched_paths}
        if declared != actual:
            failures.append(f"{role} changed_files do not exactly match diff paths")
    failures.extend(_check_forbidden_paths_in_diff(proposed_diff))
    return failures


def _unusable_primary_output(reason: str, raw_content: str = "") -> dict[str, Any]:
    """Shape proposer failure as reviewer input without treating it as a final diff."""
    return {
        "root_cause": "Proposer output unavailable or unusable.",
        "fix_strategy": "Reviewer must independently author a repair if evidence permits.",
        "changed_files": [],
        "proposed_diff": "",
        "deterministic_rule_id": None,
        "risk": None,
        "confidence": 0.0,
        "rationale": str(reason)[:2000],
        "no_fix_reason": str(reason)[:2000],
        "proposer_raw_output_available": bool(raw_content),
    }


def _looks_like_unified_diff(diff: str) -> bool:
    if not diff or not diff.strip():
        return False
    text = diff.strip()
    if "```" in text:
        return False
    has_file_header = (
        "diff --git " in text
        or ("--- " in text and "+++ " in text)
    )
    has_hunk = "@@" in text
    has_change = any(
        line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
        for line in text.splitlines()
    )
    return has_file_header and has_hunk and has_change


def _check_forbidden_paths_in_diff(diff: str) -> list[str]:
    failures: list[str] = []
    forbidden_patterns = [
        "sandbox_path",
        ".git",
        ".env",
        "Dockerfile",
        "docker-compose",
        ".github/workflows",
        "deploy/",
        "deployment/",
        "k8s/",
        "helm/",
        ".migration",
    ]
    for pattern in forbidden_patterns:
        if pattern in diff:
            failures.append(f"diff contains forbidden path pattern {pattern!r}")
    return failures


def _check_forbidden_keys(data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for key in (
        "sandbox_path", "argv", "env", "raw_command", "filesystem_target",
        "provider", "endpoint", "deployment", "env_ref", "user_supplied_file_path",
    ):
        if key in data and data[key]:
            failures.append(f"forbidden key {key!r} found in repair output")
    return failures


# ── F5-T6: Final reviewed repair diff artifact ─────────────────────


def _build_final_reviewed_repair_artifact(
    *,
    job_id: str,
    stage_index: int,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    primary_checksum: str,
    reviewer_output: dict[str, Any],
    reviewer_checksum: str,
    deterministic_checksum: str,
    selected_diff: str,
    final_diff_source: str,
    selected_changed_files: list[str],
) -> dict[str, Any]:
    diff_checksum = sha256_canonical_json({"unified_diff": selected_diff})

    return {
        "schema_version": "2.0.0",
        "proposal_id": "",
        "job_id": job_id,
        "stage_index": stage_index,
        "failure_source": failure_evidence.failure_source.value,
        "failure_summary": failure_evidence.failure_summary,
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_pack.context_pack_checksum,
        "primary_output_checksum": primary_checksum,
        "reviewer_output_checksum": reviewer_checksum,
        "proposed_diff_checksum": diff_checksum,
        "changed_files": list(selected_changed_files),
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "root_cause": str(primary_output.get("root_cause", "")),
        "fix_strategy": str(primary_output.get("fix_strategy", "")),
        "deterministic_rule_id": str(primary_output.get("deterministic_rule_id", "")),
        "risk": str(primary_output.get("risk", "")),
        "confidence": float(primary_output.get("confidence", 0.0)),
        "reviewer_decision": str(reviewer_output.get("decision", "")),
        "reviewer_notes": list(reviewer_output.get("notes", [])),
        "final_diff_source": final_diff_source,
        "proposer_usability_reason": str(primary_output.get("usability_reason", "")),
        "reviewer_usability_reason": str(reviewer_output.get("usability_reason", "")),
        "policy_validation_checksum": "",
        "artifact_checksum": "",
        "created_at": utc_now_text(),
    }


def _compute_final_repair_artifact_checksum(payload: dict[str, Any]) -> str:
    stable = {
        k: v for k, v in payload.items()
        if k not in {"artifact_checksum", "created_at", "policy_validation_checksum"}
    }
    return sha256_canonical_json(stable)


# ── F5: Main producer ─────────────────────────────────────────────


def _persist_proposer_diagnostic(
    *,
    output_dir: Path,
    raw_content: str,
    schema_name: str,
    validation_error: str,
    finish_reason: Any = None,
    response_format: Any = None,
    model_metadata: dict[str, Any] | None = None,
) -> Path:
    """Persist a safe diagnostic artifact when proposer output is invalid.

    Captures role metadata, parsed JSON keys, content lengths, and the
    validation error reason — without leaking raw prompt, endpoint, or key data.
    """
    parsed_json: dict[str, Any] = {}
    try:
        parsed_json = json.loads(raw_content) if raw_content.strip() else {}
    except (json.JSONDecodeError, TypeError):
        pass

    changed_files = parsed_json.get("changed_files")
    changed_files_count = len(changed_files) if isinstance(changed_files, list) else 0
    proposed_diff = str(parsed_json.get("proposed_diff") or "")
    proposed_diff_preview = _safe_diagnostic_text(proposed_diff) if proposed_diff else ""
    for pattern in (
        "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
        "-----BEGIN", "bearer ", "Bearer ",
    ):
        if pattern in proposed_diff_preview:
            proposed_diff_preview = "[REDACTED - pattern detected]"

    normalized_diff = proposed_diff.lstrip()
    if not proposed_diff.strip():
        proposed_diff_format = "empty"
    elif normalized_diff.startswith("diff --git"):
        proposed_diff_format = "git_unified_diff"
    elif normalized_diff.startswith("*** Begin Patch"):
        proposed_diff_format = "apply_patch"
    elif "```" in proposed_diff:
        proposed_diff_format = "markdown_fenced"
    else:
        proposed_diff_format = "unknown"

    safe_preview = _safe_diagnostic_text(raw_content) if raw_content else ""
    for pattern in (
        "ghp_", "gho_", "ghu_", "ghs_", "ghr_",
        "-----BEGIN", "bearer ", "Bearer ",
    ):
        if pattern in safe_preview:
            safe_preview = "[REDACTED - pattern detected]"

    diagnostic: dict[str, Any] = {
        "diagnostic_kind": "proposer_validation_failure",
        "role": "main",
        "responsibility": "repair_proposal",
        "schema_name": schema_name,
        "validation_error": validation_error,
        "parsed_keys": sorted(parsed_json.keys()) if isinstance(parsed_json, dict) else [],
        "raw_content_preview": safe_preview,
        "proposed_diff_length": len(proposed_diff),
        "proposed_diff_checksum": hashlib.sha256(proposed_diff.encode("utf-8")).hexdigest() if proposed_diff else "",
        "proposed_diff_format": proposed_diff_format,
        "proposed_diff_preview": proposed_diff_preview,
        "has_diff_git": normalized_diff.startswith("diff --git"),
        "has_old_file_marker": "--- a/" in proposed_diff or "--- " in proposed_diff,
        "has_new_file_marker": "+++ b/" in proposed_diff or "+++ " in proposed_diff,
        "has_hunk_marker": "@@" in proposed_diff,
        "has_apply_patch_begin": "*** Begin Patch" in proposed_diff,
        "has_apply_patch_update_file": "*** Update File:" in proposed_diff,
        "redacted_summary": {
            "root_cause": _safe_diagnostic_text(parsed_json.get("root_cause")),
            "fix_strategy": _safe_diagnostic_text(parsed_json.get("fix_strategy")),
            "no_fix_reason": _safe_diagnostic_text(parsed_json.get("no_fix_reason")),
            "changed_files_count": changed_files_count,
        },
        "finish_reason": str(finish_reason) if finish_reason is not None else "",
        "response_format_used": str(response_format) if response_format is not None else "",
        "model_metadata": model_metadata or {},
        "created_at": utc_now_text(),
    }
    path = output_dir / "repair_diagnostic_proposer.json"
    _write_json(path, diagnostic)
    return path


def produce_repair_review_chain(
    *,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    output_dir: Path,
    source_profile: str = "",
    target_profile: str = "",
    model_client: V2AssistantModelClient | None = None,
    invocation_ledger: Any = None,
) -> dict[str, Any]:
    """Produce proposer -> reviewer-final-author chain with technical fallback."""
    output_dir.mkdir(parents=True, exist_ok=True)

    deterministic_payload = _build_deterministic_repair_payload(
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        source_profile=source_profile,
        target_profile=target_profile,
    )
    deterministic_checksum = sha256_canonical_json(deterministic_payload)
    deterministic_path = output_dir / "deterministic_repair_artifact.json"
    _write_json(deterministic_path, deterministic_payload)

    client = model_client or V2AssistantModelClient()

    # ── PR-G: Capture proposer invocation ────────────────────────────
    proposer_invocation_id: str | None = None
    reviewer_invocation_id: str | None = None
    if invocation_ledger is not None:
        context_checksum_for_ledger = getattr(context_pack, "context_pack_checksum", "") or ""
        proposer_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="main",
            responsibility="repair_proposal",
            context_checksum=context_checksum_for_ledger,
            input_checksum=deterministic_checksum,
            schema_name="RepairPrimaryOutput",
        )

    # Primary Repair LLM (PROPOSER)
    primary_result = client.answer_with_role(
        role=V2ModelRole.PROPOSER,
        prompt=_primary_repair_prompt(context_pack, deterministic_checksum),
        fallback="Primary repair model unavailable; reviewed repair cannot be produced.",
        output_schema_name="RepairPrimaryOutput",
        require_schema=True,
    )

    fallback_used_primary = str(getattr(primary_result, "source", "") or "") == "deterministic"

    primary_output: dict[str, Any] | None = None
    primary_failures: list[str] = []
    if not primary_result.success:
        if proposer_invocation_id is not None:
            invocation_ledger.fail_invocation(
                proposer_invocation_id,
                redacted_error=primary_result.failure_reason,
                redacted_summary=primary_result.redacted_summary,
                fallback_used=fallback_used_primary,
            )
        primary_output = _unusable_primary_output(
            f"proposer unavailable: {primary_result.failure_reason or primary_result.model_status}"
        )

    try:
        if primary_output is None:
            primary_output = _coerce_primary_repair_output(primary_result.content)
            primary_failures = _validate_primary_repair_output(primary_output)
    except RepairReviewChainProductionError as exc:
        validation_error = str(exc)
        _persist_proposer_diagnostic(
            output_dir=output_dir,
            raw_content=primary_result.content,
            schema_name="RepairPrimaryOutput",
            validation_error=validation_error,
            finish_reason=getattr(primary_result, "finish_reason", None),
            response_format=getattr(primary_result, "response_format_used", None),
            model_metadata={
                "source": getattr(primary_result, "source", ""),
                "model_status": getattr(primary_result, "model_status", ""),
                "provider": getattr(primary_result, "provider", ""),
                "role": getattr(primary_result, "role", ""),
                "configured_max_input_tokens": getattr(primary_result, "configured_max_input_tokens", 0),
                "configured_max_output_tokens": getattr(primary_result, "configured_max_output_tokens", 0),
                "response_format_used": getattr(primary_result, "response_format_used", ""),
            },
        )
        if proposer_invocation_id is not None:
            invocation_ledger.fail_invocation(
                proposer_invocation_id,
                redacted_error=validation_error,
                redacted_summary=primary_result.redacted_summary,
                fallback_used=fallback_used_primary,
            )
        primary_output = _unusable_primary_output(_safe_diagnostic_text(validation_error), primary_result.content)
        primary_failures = []

    if primary_failures:
        validation_error = "invalid primary repair output: " + "; ".join(primary_failures)
        _persist_proposer_diagnostic(
            output_dir=output_dir,
            raw_content=primary_result.content,
            schema_name="RepairPrimaryOutput",
            validation_error=validation_error,
            finish_reason=getattr(primary_result, "finish_reason", None),
            response_format=getattr(primary_result, "response_format_used", None),
            model_metadata={
                "source": getattr(primary_result, "source", ""),
                "model_status": getattr(primary_result, "model_status", ""),
                "provider": getattr(primary_result, "provider", ""),
                "role": getattr(primary_result, "role", ""),
                "configured_max_input_tokens": getattr(primary_result, "configured_max_input_tokens", 0),
                "configured_max_output_tokens": getattr(primary_result, "configured_max_output_tokens", 0),
                "response_format_used": getattr(primary_result, "response_format_used", ""),
            },
        )
        if proposer_invocation_id is not None:
            invocation_ledger.fail_invocation(
                proposer_invocation_id,
                redacted_error=validation_error,
                redacted_summary=primary_result.redacted_summary,
                fallback_used=fallback_used_primary,
            )
        primary_output["usability_reason"] = _safe_diagnostic_text(validation_error)

    if proposer_invocation_id is not None and primary_result.success and not primary_failures:
        invocation_ledger.complete_invocation(
            proposer_invocation_id,
            output=primary_result.content,
            redacted_summary=primary_result.redacted_summary,
            fallback_used=fallback_used_primary,
        )

    primary_checksum = _compute_primary_repair_checksum(primary_output)
    primary_output["output_checksum"] = primary_checksum
    primary_path = output_dir / "primary_repair_llm_output.json"
    _write_json(primary_path, primary_output)

    context_checksum = context_pack.context_pack_checksum
    proposed_diff = str(primary_output.get("proposed_diff", ""))
    diff_checksum = sha256_canonical_json({"unified_diff": proposed_diff})

    # ── PR-G: Capture reviewer invocation ────────────────────────────
    if invocation_ledger is not None:
        reviewer_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="reviewer",
            responsibility="repair_review",
            context_checksum=context_checksum,
            input_checksum=primary_checksum,
            schema_name="RepairReviewerOutput",
        )

    # Reviewer Repair LLM (REVIEWER)
    reviewer_result = client.answer_with_role(
        role=V2ModelRole.REVIEWER,
        prompt=_reviewer_repair_prompt(
            primary_output,
            failure_evidence,
            context_pack,
            deterministic_checksum,
            context_checksum,
            primary_checksum,
            diff_checksum,
        ),
        fallback="Reviewer repair model unavailable; reviewed repair cannot be produced.",
        output_schema_name="RepairReviewerOutput",
        require_schema=True,
    )

    # ── PR-G: Complete/fail reviewer invocation ──────────────────────
    fallback_used_reviewer = str(getattr(reviewer_result, "source", "") or "") == "deterministic"
    if reviewer_invocation_id is not None:
        if reviewer_result.success:
            invocation_ledger.complete_invocation(
                reviewer_invocation_id,
                output=reviewer_result.content,
                redacted_summary=reviewer_result.redacted_summary,
                fallback_used=fallback_used_reviewer,
            )
        else:
            invocation_ledger.fail_invocation(
                reviewer_invocation_id,
                redacted_error=reviewer_result.failure_reason,
                redacted_summary=reviewer_result.redacted_summary,
                fallback_used=fallback_used_reviewer,
            )

    reviewer_output: dict[str, Any] = {}
    reviewer_reason = ""
    if not reviewer_result.success:
        reviewer_reason = f"reviewer unavailable: {reviewer_result.failure_reason or reviewer_result.model_status}"
    else:
        try:
            reviewer_output = _coerce_reviewer_repair_output(
                reviewer_result.content, deterministic_checksum, context_checksum,
                primary_checksum, diff_checksum,
            )
            checksum_failures = []
            if reviewer_output["reviewed_context_checksum"] != context_checksum:
                checksum_failures.append("reviewer context checksum mismatch")
            if reviewer_output["reviewed_primary_output_checksum"] != primary_checksum:
                checksum_failures.append("reviewer primary checksum mismatch")
            if reviewer_output["reviewed_diff_checksum"] != diff_checksum:
                checksum_failures.append("reviewer proposer-diff checksum mismatch")
            if checksum_failures:
                reviewer_reason = "; ".join(checksum_failures)
            else:
                reviewer_failures = _validate_candidate_diff(
                    proposed_diff=str(reviewer_output.get("proposed_diff") or ""),
                    changed_files=list(reviewer_output.get("changed_files") or []),
                    role="reviewer",
                )
                if reviewer_failures:
                    reviewer_reason = "; ".join(reviewer_failures)
        except RepairReviewChainProductionError as exc:
            reviewer_reason = _safe_diagnostic_text(str(exc))
    reviewer_output["usability_reason"] = reviewer_reason
    reviewer_checksum = _compute_reviewer_repair_checksum(reviewer_output) if reviewer_output else ""
    if reviewer_output:
        reviewer_output["output_checksum"] = reviewer_checksum
    reviewer_path = output_dir / "reviewer_repair_llm_output.json"
    if reviewer_output:
        _write_json(reviewer_path, reviewer_output)

    proposer_diff = str(primary_output.get("proposed_diff") or "")
    proposer_failures = _validate_candidate_diff(
        proposed_diff=proposer_diff,
        changed_files=list(primary_output.get("changed_files") or []),
        role="proposer",
    )
    proposer_reason = "; ".join(proposer_failures)
    primary_output["usability_reason"] = proposer_reason
    final_diff = str(reviewer_output.get("proposed_diff") or "") if not reviewer_reason else ""
    final_diff_source = "reviewer" if final_diff else "proposer_fallback" if not proposer_reason else ""
    if not final_diff and not proposer_reason:
        final_diff = proposer_diff
    selected_changed_files = (
        list(reviewer_output.get("changed_files") or [])
        if final_diff_source == "reviewer"
        else list(primary_output.get("changed_files") or [])
    )
    if not final_diff:
        generation_reason = "; ".join(filter(None, [proposer_reason, reviewer_reason, "no technically usable final diff"]))
        return {"artifact_refs": {
            "deterministic_artifact": str(deterministic_path),
            "primary_llm_output": str(primary_path),
            "reviewer_llm_output": str(reviewer_path) if reviewer_output else "",
        }, "review_chain": {
            "generation_status": "repair_generation_failed",
            "generation_failure_reason": generation_reason,
            "proposer_usability_reason": proposer_reason,
            "reviewer_usability_reason": reviewer_reason,
            "proposer_diff_usable": not bool(proposer_reason),
            "reviewer_diff_usable": not bool(reviewer_reason) and bool(reviewer_output.get("proposed_diff")),
            "reviewer_output_checksum": reviewer_checksum,
            "final_diff_source": "", "final_diff_ref": "",
            "model_roles": {"proposer": _safe_model_role_status(primary_result), "reviewer": _safe_model_role_status(reviewer_result)},
        }}
    selected_diff_checksum = sha256_canonical_json({"unified_diff": final_diff})

    final_artifact = _build_final_reviewed_repair_artifact(
        job_id=context_pack.job_id,
        stage_index=context_pack.stage_index,
        failure_evidence=failure_evidence,
        context_pack=context_pack,
        primary_output=primary_output,
        primary_checksum=primary_checksum,
        reviewer_output=reviewer_output,
        reviewer_checksum=reviewer_checksum,
        deterministic_checksum=deterministic_checksum,
        selected_diff=final_diff,
        final_diff_source=final_diff_source,
        selected_changed_files=selected_changed_files,
    )
    final_artifact_checksum = _compute_final_repair_artifact_checksum(final_artifact)
    final_artifact["artifact_checksum"] = final_artifact_checksum
    final_artifact_path = output_dir / "final_reviewed_repair_artifact.json"
    _write_json(final_artifact_path, final_artifact)

    diff_path = output_dir / "final_reviewed_repair.diff"
    diff_path.write_text(final_diff, encoding="utf-8")

    review_chain: dict[str, Any] = {
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_checksum,
        "primary_output_checksum": primary_checksum,
        "reviewer_output_checksum": reviewer_checksum,
        "proposed_diff_checksum": selected_diff_checksum,
        "final_artifact_checksum": final_artifact_checksum,
        "reviewer_decision": reviewer_output.get("decision", ""),
        "final_diff_source": final_diff_source,
        "generation_status": "ready",
        "proposer_usability_reason": proposer_reason,
        "reviewer_usability_reason": reviewer_reason,
        "proposer_diff_usable": not bool(proposer_reason),
        "reviewer_diff_usable": not bool(reviewer_reason) and bool(reviewer_output.get("proposed_diff")),
        "job_id": context_pack.job_id,
        "stage_index": context_pack.stage_index,
        "deterministic_rule_id": str(final_artifact.get("deterministic_rule_id", "")),
        "risk": str(final_artifact.get("risk", "")),
        "root_cause": str(final_artifact.get("root_cause", "")),
        "fix_strategy": str(final_artifact.get("fix_strategy", "")),
        "changed_files": list(final_artifact.get("changed_files", [])),
        "confidence": float(final_artifact.get("confidence", 0.0)),
        "reviewer_notes": list(final_artifact.get("reviewer_notes", [])),
        "policy_validation_checksum": str(final_artifact.get("policy_validation_checksum", "")),
        "deterministic_artifact_ref": str(deterministic_path),
        "primary_output_ref": str(primary_path),
        "reviewer_output_ref": str(reviewer_path),
        "final_artifact_ref": str(final_artifact_path),
        "final_diff_ref": str(diff_path),
        "model_roles": {
            "proposer": _safe_model_role_status(primary_result),
            "reviewer": _safe_model_role_status(reviewer_result),
        },
    }
    if proposer_invocation_id is not None and reviewer_invocation_id is not None:
        review_chain["proposer_invocation_id"] = proposer_invocation_id
        review_chain["reviewer_invocation_id"] = reviewer_invocation_id
        assert proposer_invocation_id != reviewer_invocation_id, "proposer and reviewer invocation IDs must be distinct"
    review_chain_path = output_dir / "review_chain.json"
    _write_json(review_chain_path, review_chain)

    produced_refs = {
        "deterministic_artifact": str(deterministic_path),
        "primary_llm_output": str(primary_path),
        "reviewer_llm_output": str(reviewer_path),
        "final_reviewed_artifact": str(final_artifact_path),
        "final_reviewed_diff": str(diff_path),
        "review_chain_metadata": str(review_chain_path),
    }

    return {"artifact_refs": produced_refs, "review_chain": review_chain}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_model_role_status(result: Any) -> dict[str, Any]:
    """Safe role metadata; deployment names contain no endpoint/key material."""
    return {
        "role": str(getattr(result, "role", "") or ""),
        "available": bool(getattr(result, "success", False)),
        "status": "available" if bool(getattr(result, "success", False)) else "blocked",
        "fallback_used": bool(getattr(result, "fallback_used", False)) or str(getattr(result, "source", "") or "") == "azure_openai_fallback",
        "configured_deployment": str(getattr(result, "configured_deployment", "") or ""),
        "fallback_deployment": str(getattr(result, "fallback_deployment", "") or ""),
        "primary_failure_reason": str(getattr(result, "primary_failure_reason", "") or ""),
    }
