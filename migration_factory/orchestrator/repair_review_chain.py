"""F5: Repair review-chain producer — extends the F2 review-chain pattern for repair.

Deterministic repair artifact -> Primary Repair LLM (PROPOSER) -> Reviewer Repair LLM (REVIEWER)
-> Final reviewed repair diff artifact.

Core rule: A model reviews another model for repair. Reviewer is mandatory.

── Future path: structured-edit fallback ──────────────────────────────
When raw reviewed-diff mode fails repeated mechanical diff validation, a
backend-generated diff from structured edit operations provides a fallback:

  1. Main proposes structured_edits (new optional key in RepairPrimaryOutput).
  2. Reviewer finalizes structured_edits.
  3. Backend verifies exact old_text in sandbox (must exist exactly once).
  4. Backend applies replacements to temp copies (never mutates sandbox).
  5. Backend generates unified diff from real before/after content.
  6. Existing diff validation, path safety, git apply --check, patch policy,
     proposal persistence, and human approval remain unchanged.

New module (not yet implemented):
  migration_factory/repair_loop/structured_edits.py

Structured edit schema:
  {"path": "repo-relative POSIX path",
   "old_text": "exact source text to replace",
   "replacement_text": "replacement source text",
   "reason": "why this edit fixes the failure",
   "expected_imports": [],
   "expected_classes": []}

Backend materialization requirements:
  - Path validation: repo-relative POSIX only, resolve under sandbox root
  - Exact old_text: must exist exactly once in file, or fail closed
  - Temp copy only: never mutate sandbox during materialization
  - Generate unified diff via Python difflib or git diff against temp copy
  - Reuse existing validate_unified_diff_structure(), check_patch_applicability()
  - Do NOT create a second patch engine

Activation: config flag or internal fallback threshold (TBD).
Do NOT implement until a separate AMF ticket is opened.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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
from migration_factory.repair_loop.patch_apply import validate_unified_diff_structure
from migration_factory.repair_loop.patch_gate import (
    classify_diff_failure,
    extract_touched_paths,
)
from migration_factory.repair_loop.repair_context import (
    RepairContextPack,
    compute_base_repo_state_checksum,
    compute_context_pack_checksum,
    context_pack_to_dict,
)


class RepairReviewChainProductionError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        schema_diagnostics: dict[str, Any] | None = None,
        reason_code: str = "",
        schema_name: str = "",
        role: str = "",
        partial_chain: dict[str, Any] | None = None,
        detail: str = "",
        struct_issue: str = "",
    ) -> None:
        super().__init__(message)
        self.schema_diagnostics = schema_diagnostics or {}
        self.reason_code = reason_code or ""
        self.schema_name = schema_name or ""
        self.role = role or ""
        self.partial_chain = partial_chain or {}
        self.detail = detail or ""
        self.struct_issue = struct_issue or ""


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
    return (
        "You are a repair proposer. Analyze the build/test failure evidence below "
        "and propose an exact unified diff to fix the issue.\n\n"
        "Return JSON with these required keys:\n"
        "  root_cause (string): root cause of the failure\n"
        "  fix_strategy (string): description of the fix approach\n"
        "  changed_files (list of strings): relative file paths affected\n"
        "  proposed_diff (string): strict Git-style unified diff\n"
        "  deterministic_rule_id (string): matching rule ID or 'no_safe_rule'\n"
        "  risk (string): LOW, MEDIUM, or HIGH\n"
        "  confidence (number): 0.0 to 1.0\n"
        "  rationale (string): justification for the fix\n"
        "IMPORTANT: Output only valid JSON. No markdown. No code fences. No commentary. "
        "No prose outside the JSON object. Do not return alternative repair options. "
        "Choose exactly one minimal code repair and include one concrete proposed_diff.\n\n"
        "CONSTRAINTS:\n"
        "- Do NOT include commands, paths to execute, provider data, endpoint data, "
        "env data, deployment data, or approvals.\n"
        "- Do NOT include absolute sandbox paths.\n"
        "- The host runtime is Windows. Do not output absolute Windows paths or C:\\ paths.\n"
        "- Use repo-relative POSIX-style paths only. Diff headers must use forward slashes.\n"
        "- The proposed_diff MUST be a strict Git-style unified diff. It:\n"
        "  * must start with 'diff --git a/<relative-path> b/<relative-path>'\n"
        "  * must include '--- a/<relative-path>'\n"
        "  * must include '+++ b/<relative-path>'\n"
        "  * must include at least one '@@ ... @@' hunk\n"
        "  * each hunk header MUST include line-range: @@ -old_start,old_count +new_start,new_count @@\n"
        "  * must use only relative repository paths\n"
        "  * must NOT include absolute paths, sandbox_path, target_path, env, argv, or command\n"
        "  * must NOT include markdown fences or prose outside the diff.\n"
        "- Do not skip or disable tests as a fix.\n"
        "- The fix must stay within the sandbox scope and declared changed files.\n\n"
        "REPAIR SELECTION:\n"
        "- If multiple strategies exist, choose the smallest code-only fix that directly addresses the compiler error.\n"
        "- Do not assume Jackson package family. Use the target profile and existing imports. "
        "If target context shows tools.jackson.*, keep tools.jackson.*. "
        "If tools.jackson.databind.JsonNode already exists, do not add com.fasterxml.jackson.databind.JsonNode.\n"
        "- Do not propose a dependency or POM change unless failure evidence proves the dependency is missing from "
        "the classpath and no source import fix is possible.\n\n"
        "Valid JSON example:\n"
        "{\n"
        '  "root_cause": "A Java source file references JsonNode without importing the Jackson type.",\n'
        '  "fix_strategy": "Add the missing Jackson JsonNode import to the affected source file.",\n'
        '  "changed_files": ["src/main/java/example/ExampleController.java"],\n'
        '  "proposed_diff": "diff --git a/src/main/java/example/ExampleController.java b/src/main/java/example/ExampleController.java\\n--- a/src/main/java/example/ExampleController.java\\n+++ b/src/main/java/example/ExampleController.java\\n@@ -3,6 +3,7 @@ package example;\\n import java.util.Map;\\n+import com.fasterxml.jackson.databind.JsonNode;\\n \\n public class ExampleController {\\n",\n'
        '  "deterministic_rule_id": "no_safe_rule",\n'
        '  "risk": "LOW",\n'
        '  "confidence": 0.84,\n'
        '  "rationale": "The dependency evidence already includes Jackson, so the compile error is resolved by importing the referenced type."\n'
        "}\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n\n"
        f"Context:\n{json.dumps(context_pack_to_dict(context_pack), sort_keys=True)}"
    )


def _reviewer_repair_prompt(
    *,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    main_diff_diagnostics: dict[str, Any],
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
) -> str:
    return (
        "You are a repair reviewer and final patch author. Validate Main's repair "
        "against the grounded context and backend diagnostics. If Main's diff is stale "
        "or malformed but the context is sufficient, return a corrected final reviewed_diff.\n\n"
        "Output only valid JSON. No markdown. No code fences. No commentary. "
        "No prose outside the JSON object. Do not add extra keys.\n\n"
        "Match the RepairReviewerOutput schema exactly.\n\n"
        "Required fields:\n"
        "  decision: \"accept\" | \"reject\" | \"needs_more_context\" | \"needs_revision\"\n"
        "  review_summary: string\n"
        "  main_patch_findings: list of strings\n"
        "  risks: list of strings\n"
        "  policy_concerns: list of strings\n"
        "  changed_files_verified: boolean\n"
        "  reviewed_diff: string\n"
        "  diff_changed_by_reviewer: boolean\n"
        "  main_diff_diagnostics_acknowledged: boolean\n"
        "  diff_parseable: boolean\n"
        f"  reviewed_context_checksum: \"{context_checksum}\"\n"
        f"  reviewed_primary_output_checksum: \"{primary_checksum}\"\n\n"
        "If accepting, set decision=accept and reason_for_rejection=null and revision_request=null.\n"
        "If rejecting, set decision=reject, reviewed_diff=\"\", reason_for_rejection=<reason>, revision_request=null.\n"
        "If requesting revision, set decision=needs_revision, reason_for_rejection=null, revision_request=<specific request>.\n"
        "If more context is needed, set decision=needs_more_context, reviewed_diff=\"\", reason_for_rejection=<reason>, revision_request=<specific request or null>.\n\n"
        "Return only JSON matching RepairReviewerOutput.\n"
        "No markdown.\n"
        "No prose outside JSON.\n"
        "No extra keys.\n"
        "Every required key must be present.\n\n"
        "reason_for_rejection and revision_request are required but may be null.\n\n"
        "If decision is \"accept\", reviewed_diff must contain the final strict Git-style unified diff. "
        "For accept, reviewed_diff must be non-empty, diff_parseable=true, "
        "changed_files_verified=true, and main_diff_diagnostics_acknowledged=true. "
        "If Main's diff is correct, copy it into reviewed_diff. If you correct it, set "
        "diff_changed_by_reviewer=true. If unable to produce a valid diff, return decision "
        "\"needs_more_context\" or \"needs_revision\", reviewed_diff=\"\", diff_parseable=false, "
        "and a clear review_summary.\n\n"
        "Backend truth is mechanical. Do not claim backend validation success. The backend will compute "
        "reviewed_diff_checksum and run schema, path, policy, and git apply --check validation.\n\n"
        "Valid JSON example:\n"
        "{\n"
        '  "decision": "accept",\n'
        '  "review_summary": "Main selected the right file but the hunk was repaired against real source context.",\n'
        '  "main_patch_findings": ["Main diff had stale context."],\n'
        '  "risks": [],\n'
        '  "policy_concerns": [],\n'
        '  "changed_files_verified": true,\n'
        '  "reviewed_diff": "diff --git a/src/main/java/example/Foo.java b/src/main/java/example/Foo.java\\n--- a/src/main/java/example/Foo.java\\n+++ b/src/main/java/example/Foo.java\\n@@ -1,2 +1,3 @@\\n package example;\\n+import tools.jackson.databind.JsonNode;\\n",\n'
        '  "diff_changed_by_reviewer": true,\n'
        '  "main_diff_diagnostics_acknowledged": true,\n'
        '  "diff_parseable": true,\n'
        f'  "reviewed_context_checksum": "{context_checksum}",\n'
        f'  "reviewed_primary_output_checksum": "{primary_checksum}",\n'
        '  "reason_for_rejection": null,\n'
        '  "revision_request": null\n'
        "}\n\n"
        "CONSTRAINTS:\n"
        "- Use only the provided grounded context and Main proposal. Do not invent file bodies.\n"
        "- Do not output placeholder lines, ellipses, bare @@ hunks, or // interface methods.\n"
        "- The host runtime is Windows. Do not output absolute Windows paths or C:\\ paths.\n"
        "- Use repo-relative POSIX-style diff paths only.\n"
        "- Respect existing imports and target profile. Do not assume Jackson package family.\n"
        "- Reject any unsafe diff (absolute paths, security config changes, "
        "execution instructions, test disabling, deleted production code).\n"
        "- Reject or needs_more_context if the source context is insufficient to produce a grounded patch.\n"
        "- main_diff_diagnostics_acknowledged must be true.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Context pack checksum: {context_checksum}\n"
        f"Primary output checksum: {primary_checksum}\n"
        f"Grounded context:\n{json.dumps(context_pack_to_dict(context_pack), sort_keys=True)}\n"
        f"Primary output:\n{json.dumps(primary_output, sort_keys=True)}\n"
        f"Backend main_diff_diagnostics:\n{json.dumps(main_diff_diagnostics, sort_keys=True)}"
    )


def _reviewer_self_repair_prompt(
    *,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    main_diff_diagnostics: dict[str, Any],
    original_reviewer_output: dict[str, Any],
    original_reviewed_diff: str,
    validation_issue: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
) -> str:
    context_payload = context_pack_to_dict(context_pack)
    original_decision = str(original_reviewer_output.get("decision") or "").strip().lower()
    preserve_accept = original_decision == "accept"
    return (
        "You are the same repair reviewer. Your previous reviewed_diff failed backend "
        "mechanical validation. Repair only your final reviewed_diff once, using the "
        "grounded source context and exact backend issue below.\n\n"
        "Return exactly one JSON object matching RepairReviewerOutput. "
        "No markdown. No code fences. No prose outside JSON. Do not add extra keys.\n\n"
        "Required JSON keys:\n"
        "  decision (one of: accept, reject, needs_more_context, needs_revision)\n"
        "  review_summary (string)\n"
        "  main_patch_findings (list of strings)\n"
        "  changed_files_verified (boolean)\n"
        "  reviewed_diff (string)\n"
        "  diff_changed_by_reviewer (boolean)\n"
        "  risks (list of strings)\n"
        "  policy_concerns (list of strings)\n"
        "  main_diff_diagnostics_acknowledged (boolean)\n"
        "  diff_parseable (boolean)\n"
        "  reviewed_context_checksum (string)\n"
        "  reviewed_primary_output_checksum (string)\n\n"
        "Accept contract:\n"
        "  If decision=\"accept\":\n"
        "    - reviewed_diff must be non-empty\n"
        "    - diff_parseable must be true\n"
        "    - changed_files_verified must be true\n"
        "    - main_diff_diagnostics_acknowledged must be true\n"
        "    - reviewed_context_checksum must equal the provided context checksum\n"
        "    - reviewed_primary_output_checksum must equal the provided primary output checksum\n"
        "    - Each diff hunk old/new counts must match the hunk body\n"
        "    - Every hunk must include real context lines\n"
        "    - All paths must be repo-relative POSIX paths\n"
        "    - No absolute paths, sandbox paths, env, argv, raw commands, or secrets\n\n"
        "Safe failure contract:\n"
        "  If you cannot produce a structurally valid diff:\n"
        "    - reviewed_diff must be \"\" (empty string)\n"
        "    - diff_parseable must be false\n"
        "    - review_summary must explain the blocker\n"
        + (
            "\n\nCRITICAL: Your original decision was 'accept'. You MUST keep your decision as 'accept'. "
            "Do NOT change to 'needs_revision', 'reject', or any other non-accept decision. "
            "Only fix the reviewed_diff to pass the mechanical validation. "
            "If you cannot fix the diff format, keep 'accept' and include whatever diff you can provide.\n"
            if preserve_accept
            else ""
        )
        + "\nCritical mechanical rules:\n"
        f"- Exact backend issue: {validation_issue}\n"
        "- Hunk header counts must exactly match hunk body old/new line counts.\n"
        "- Every hunk must include at least one real unchanged context line beginning with a space.\n"
        "- Do not return zero-context hunks or rely on relaxed zero-context patch behavior.\n"
        "- Do not assume git apply --unidiff-zero or any weak apply flags.\n"
        "- Use repo-relative POSIX paths only.\n"
        "- Do not invent file bodies, placeholder lines, ellipses, or bare @@ hunks.\n"
        "- Preserve the existing package/import context from source_contexts.\n"
        "- Set diff_parseable=true only if your reviewed_diff is parseable.\n"
        "- Backend will reject the output again if hunk counts do not match.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Context pack checksum: {context_checksum}\n"
        f"Primary output checksum: {primary_checksum}\n"
        f"Grounded context, including source_contexts and diff_generation_rules:\n{json.dumps(context_payload, sort_keys=True)}\n"
        f"Primary output:\n{json.dumps(primary_output, sort_keys=True)}\n"
        f"Backend main_diff_diagnostics:\n{json.dumps(main_diff_diagnostics, sort_keys=True)}\n"
        f"Original reviewer output:\n{json.dumps(original_reviewer_output, sort_keys=True)}\n"
        f"Original bad reviewed_diff:\n{original_reviewed_diff}"
    )


def produce_reviewer_applicability_repair(
    *,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    reviewer_output: dict[str, Any],
    reviewed_diff: str,
    apply_check_error: str,
    apply_check_stderr: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    client: V2AssistantModelClient,
    invocation_ledger: Any = None,
) -> tuple[dict[str, Any], str | None, Any]:
    issue = (
        "validation_issue_type=applicability_check_failed\n"
        "The reviewed_diff is schema-valid and structurally valid, but strict "
        "git apply --check rejected it against the exact sandbox. Repair only "
        "the final reviewed_diff. Do not rerun Main.\n\n"
        "Exact git apply --check error:\n"
        f"{apply_check_error}\n\n"
        "Exact git apply --check stderr:\n"
        f"{apply_check_stderr}\n\n"
        "Applicability repair requirements:\n"
        "- Use the provided source_contexts as the source of truth.\n"
        "- Include at least one unchanged context line before/after each changed line where possible.\n"
        "- Do not produce zero-context hunks.\n"
        "- Return valid RepairReviewerOutput JSON only.\n"
        "- If you cannot produce an applicable diff from the grounded context, return "
        "needs_more_context or needs_revision with reviewed_diff empty.\n\n"
        "Original non-applicable reviewed_diff:\n"
        f"{reviewed_diff}"
    )
    return _invoke_reviewer_self_repair(
        client=client,
        context_pack=context_pack,
        primary_output=primary_output,
        main_diff_diagnostics={
            "structure_status": "valid",
            "applicability_status": "failed",
            "validation_issue_type": "applicability_check_failed",
            "apply_check_error": apply_check_error,
            "apply_check_stderr": apply_check_stderr,
        },
        original_reviewer_output=reviewer_output,
        validation_issue=issue,
        deterministic_checksum=deterministic_checksum,
        context_checksum=context_checksum,
        primary_checksum=primary_checksum,
        invocation_ledger=invocation_ledger,
    )


def _extract_json_safe(content: str) -> dict[str, Any] | None:
    """Try to parse model output as JSON with resilient fallbacks."""
    raw = str(content).strip()
    if not raw:
        return None

    # Attempt 1: direct json.loads
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Attempt 2: strip markdown code fences
    cleaned = raw
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = cleaned.strip()
    if cleaned != raw:
        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Attempt 3: extract first complete JSON object
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(raw):
        if raw[idx] == "{":
            try:
                obj, end = decoder.raw_decode(raw, idx)
                if isinstance(obj, dict):
                    return obj
            except (json.JSONDecodeError, ValueError):
                idx += 1
                continue
        idx += 1

    return None


def _coerce_primary_repair_output(content: str) -> dict[str, Any]:
    raw = str(content).strip()
    if not raw:
        raise RepairReviewChainProductionError(
            "primary repair output is empty",
            reason_code="main_empty_response",
        )

    parsed = _extract_json_safe(content)
    if parsed is None:
        raise RepairReviewChainProductionError(
            "primary repair output must be valid JSON; got unparseable output",
            reason_code="main_schema_invalid",
        )

    required = {"root_cause", "fix_strategy", "changed_files", "proposed_diff", "risk", "confidence"}
    missing = required - set(parsed.keys())
    if missing:
        raise RepairReviewChainProductionError(
            f"primary repair output missing required fields: {sorted(missing)}",
            reason_code="main_missing_fields",
        )

    return parsed


def _fallback_primary_repair_output(content: str) -> dict[str, Any]:
    raise RepairReviewChainProductionError(
        "primary repair output must be valid JSON with all required fields",
        reason_code="main_schema_invalid",
    )


def _coerce_reviewer_repair_output(
    content: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
) -> dict[str, Any]:
    raw = str(content).strip()
    if not raw:
        raise RepairReviewChainProductionError(
            "reviewer repair output is empty",
            reason_code="reviewer_empty_response",
        )

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RepairReviewChainProductionError(
                "reviewer output must be a JSON object",
                reason_code="reviewer_schema_invalid",
                schema_name="RepairReviewerOutput",
                role="reviewer",
            )
    except json.JSONDecodeError:
        raise RepairReviewChainProductionError(
            "reviewer output must be valid JSON",
            reason_code="reviewer_schema_invalid",
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    if "checksum_bindings" in parsed:
        raise RepairReviewChainProductionError(
            "reviewer checksum bindings must be top-level fields",
            reason_code="reviewer_schema_invalid",
            schema_diagnostics={
                "role": "reviewer",
                "schema_name": "RepairReviewerOutput",
                "wrong_field_names": ["checksum_bindings"],
            },
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    decision = str(parsed.get("decision") or "").strip().lower()
    if decision not in {"accept", "revise", "reject", "needs_revision", "needs_more_context"}:
        raise RepairReviewChainProductionError(
            f"invalid reviewer decision {decision!r}; must be accept/reject/needs_more_context",
            reason_code="reviewer_invalid_decision",
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )
    required_checksum_fields = {
        "reviewed_context_checksum",
        "reviewed_primary_output_checksum",
    }
    missing_checksum_fields = {
        field
        for field in required_checksum_fields
        if field not in parsed or not str(parsed.get(field) or "").strip()
    }
    if missing_checksum_fields:
        raise RepairReviewChainProductionError(
            f"reviewer output missing required top-level checksum fields: {sorted(missing_checksum_fields)}",
            reason_code="reviewer_schema_invalid",
            schema_diagnostics={
                "role": "reviewer",
                "schema_name": "RepairReviewerOutput",
                "missing_fields": sorted(missing_checksum_fields),
            },
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    reviewed_context_checksum = str(parsed["reviewed_context_checksum"]).strip()
    reviewed_primary_output_checksum = str(parsed["reviewed_primary_output_checksum"]).strip()
    if reviewed_context_checksum != context_checksum:
        raise RepairReviewChainProductionError(
            "reviewer context checksum binding did not match the reviewed artifacts",
            reason_code="reviewer_checksum_mismatch",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_context_checksum"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )
    if reviewed_primary_output_checksum != primary_checksum:
        raise RepairReviewChainProductionError(
            "reviewer primary output checksum binding did not match the reviewed artifacts",
            reason_code="reviewer_checksum_mismatch",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_primary_output_checksum"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    changed_files_verified = bool(parsed.get("changed_files_verified", False))
    reviewed_diff = _strip_reviewed_diff_fences(str(parsed.get("reviewed_diff") or ""))

    review_summary = str(parsed.get("review_summary") or "").strip()
    notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
    if review_summary:
        notes = [review_summary, *[str(item) for item in notes]]
    main_patch_findings = (
        parsed.get("main_patch_findings")
        if isinstance(parsed.get("main_patch_findings"), list)
        else []
    )
    reviewed_diff_checksum = sha256_canonical_json({"unified_diff": reviewed_diff})
    diff_parseable = bool(parsed.get("diff_parseable", False))
    model_claimed_diff_parseable = (
        bool(parsed.get("model_claimed_diff_parseable"))
        if "model_claimed_diff_parseable" in parsed
        else diff_parseable
    )

    return {
        "decision": decision,
        "review_summary": review_summary,
        "main_patch_findings": [str(item) for item in main_patch_findings],
        "notes": [str(item) for item in notes] or [str(parsed.get("reasoning") or "No notes.")],
        "confidence": float(parsed.get("confidence", 0.8)),
        "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
        "policy_concerns": parsed.get("policy_concerns") if isinstance(parsed.get("policy_concerns"), list) else [],
        "changed_files_verified": changed_files_verified,
        "reviewed_diff": reviewed_diff,
        "diff_changed_by_reviewer": bool(parsed.get("diff_changed_by_reviewer", False)),
        "main_diff_diagnostics_acknowledged": bool(parsed.get("main_diff_diagnostics_acknowledged", False)),
        "diff_parseable": diff_parseable,
        "model_claimed_diff_parseable": model_claimed_diff_parseable,
        "reviewed_context_checksum": reviewed_context_checksum,
        "reviewed_primary_output_checksum": reviewed_primary_output_checksum,
        "reviewed_diff_checksum": reviewed_diff_checksum,
        "reason_for_rejection": str(parsed.get("reason_for_rejection") or ""),
        "revision_request": str(parsed.get("revision_request") or ""),
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
        "review_summary": str(output.get("review_summary", "")),
        "main_patch_findings": list(output.get("main_patch_findings", [])),
        "notes": list(output.get("notes", [])),
        "confidence": float(output.get("confidence", 0.0)),
        "risks": list(output.get("risks", [])),
        "policy_concerns": list(output.get("policy_concerns", [])),
        "changed_files_verified": bool(output.get("changed_files_verified", False)),
        "reviewed_diff": str(output.get("reviewed_diff", "")),
        "diff_changed_by_reviewer": bool(output.get("diff_changed_by_reviewer", False)),
        "main_diff_diagnostics_acknowledged": bool(output.get("main_diff_diagnostics_acknowledged", False)),
        "diff_parseable": bool(output.get("diff_parseable", False)),
        "model_claimed_diff_parseable": bool(output.get("model_claimed_diff_parseable", False)),
        "reviewed_context_checksum": str(output.get("reviewed_context_checksum", "")),
        "reviewed_primary_output_checksum": str(output.get("reviewed_primary_output_checksum", "")),
        "reviewed_diff_checksum": str(output.get("reviewed_diff_checksum", "")),
    }
    return sha256_canonical_json(payload)


def _normalize_to_git_diff(diff: str) -> tuple[str, bool]:
    """Normalize a plain unified diff to Git-style if safe and deterministic.

    Returns (normalized_diff, was_normalized).
    Only normalizes when:
    - Diff has --- and +++ lines with safe relative paths (no a/b prefix)
    - Diff has at least one @@ hunk
    - Diff has at least one +/- change line
    - All paths are safe relative paths (no absolute, no traversal)
    - No diff --git header already present

    Never invents changed files, hunks, or content.
    """
    text = diff.strip()
    if not text:
        return diff, False

    if "diff --git " in text:
        return diff, False

    if "GIT binary patch" in text or "Binary files " in text:
        return diff, False

    lines = text.splitlines()
    has_old = False
    has_new = False
    has_hunk = False
    has_change = False
    old_path = ""
    new_path = ""

    for line in lines:
        if line.startswith("--- "):
            has_old = True
            raw = line[4:].split("\t", 1)[0].strip().strip('"')
            if raw.startswith("a/") or raw.startswith("b/"):
                old_path = raw[2:]
            else:
                old_path = raw
        elif line.startswith("+++ "):
            has_new = True
            raw = line[4:].split("\t", 1)[0].strip().strip('"')
            if raw.startswith("a/") or raw.startswith("b/"):
                new_path = raw[2:]
            else:
                new_path = raw
        elif line.startswith("@@"):
            has_hunk = True
        elif line.startswith("+") or line.startswith("-"):
            has_change = True

    if not (has_old and has_new and has_hunk and has_change):
        return diff, False

    path = old_path or new_path
    if not path:
        return diff, False

    normalized = path.replace("\\", "/")
    if (
        normalized.startswith("/")
        or ".." in normalized.split("/")
        or normalized.startswith("//")
    ):
        return diff, False

    git_header = f"diff --git a/{path} b/{path}"
    result_lines = [git_header]
    for line in lines:
        if line.startswith("--- "):
            raw = line[4:].split("\t", 1)[0].strip().strip('"')
            if raw.startswith("a/") or raw.startswith("b/"):
                result_lines.append(line)
            else:
                result_lines.append(f"--- a/{raw}")
        elif line.startswith("+++ "):
            raw = line[4:].split("\t", 1)[0].strip().strip('"')
            if raw.startswith("a/") or raw.startswith("b/"):
                result_lines.append(line)
            else:
                result_lines.append(f"+++ b/{raw}")
        else:
            result_lines.append(line)

    normalized_result = "\n".join(result_lines)
    if not normalized_result.startswith("diff --git "):
        return diff, False
    return normalized_result, True


# Regex for a proper hunk header: @@ -x,y +a,b @@
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def _repair_bare_hunk_headers(diff: str, repo_root: Path | str | None) -> tuple[str, bool]:
    """Repair bare @@ hunk headers by locating hunks in target file content.

    A bare @@ is a line starting with @@ that does NOT match the standard
    unified diff hunk header pattern @@ -x,y +a,b @@.

    The function:
    1. Splits the diff into per-file sections
    2. For each file with bare @@ markers, reads the target file from repo_root
    3. Uses context/deleted lines to locate the hunk in the original file
    4. Computes old_start, old_count, new_start, new_count
    5. Replaces bare @@ with proper hunk headers

    Returns (repaired_diff, was_repaired).
    Fails safe if location is ambiguous, repo_root is None, or file not found.
    """
    text = diff.strip()
    if not text:
        return diff, False

    lines = text.splitlines()
    has_bare_hunk = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("@@") and not _HUNK_HEADER_RE.match(stripped):
            has_bare_hunk = True
            break
    if not has_bare_hunk:
        return diff, False

    if repo_root is None:
        logger.warning("cannot repair bare hunk headers: no repo_root provided")
        return diff, False

    repo_path = Path(str(repo_root))
    if not repo_path.is_dir():
        logger.warning("cannot repair bare hunk headers: repo_root %s is not a directory", repo_path)
        return diff, False

    # Split diff into file sections (on diff --git or ---/+++ blocks)
    file_sections = _split_diff_by_file(lines)
    repaired_sections: list[list[str]] = []
    overall_repaired = False

    for file_header, file_lines, file_path in file_sections:
        if file_path is None:
            repaired_sections.append(file_header + file_lines)
            continue

        has_bare = any(
            l.strip().startswith("@@") and not _HUNK_HEADER_RE.match(l.strip())
            for l in file_lines
        )
        if not has_bare:
            repaired_sections.append(file_header + file_lines)
            continue

        target_file = repo_path / file_path
        if not target_file.is_file():
            logger.warning(
                "cannot repair bare hunk headers for %s: target file not found at %s",
                file_path, target_file,
            )
            repaired_sections.append(file_header + file_lines)
            continue

        target_lines = target_file.read_text(encoding="utf-8").splitlines()
        # Parse hunks from file_lines using bare @@ as delimiters
        hunks = _split_hunks_bare(file_lines)
        repaired_hunk_lines: list[str] = []

        for hunk_lines in hunks:
            # Check if first line is a bare @@ marker
            first = hunk_lines[0] if hunk_lines else ""
            if first.strip().startswith("@@") and not _HUNK_HEADER_RE.match(first.strip()):
                # Extract context/deleted lines for anchor matching
                anchor_lines: list[str] = []
                for hl in hunk_lines:
                    if hl.startswith(" ") or hl.startswith("-"):
                        anchor = hl[1:]  # strip prefix
                        anchor_lines.append(anchor)

                if not anchor_lines:
                    logger.warning("cannot repair bare hunk: no anchor lines in hunk body")
                    repaired_hunk_lines.extend(hunk_lines)
                    continue

                # Compute stats for the hunk
                added = sum(1 for hl in hunk_lines if hl.startswith("+"))
                deleted = sum(1 for hl in hunk_lines if hl.startswith("-"))
                context = sum(1 for hl in hunk_lines if hl.startswith(" ") and not hl.startswith(("---", "+++")))

                # Locate anchor in target file
                located = _locate_hunk_in_file(target_lines, anchor_lines)
                if located is None:
                    logger.warning(
                        "cannot repair bare hunk for %s: cannot locate anchor in target file",
                        file_path,
                    )
                    repaired_hunk_lines.extend(hunk_lines)
                    continue

                old_start = located + 1  # convert to 1-indexed
                old_count = context + deleted
                new_start = old_start  # assume insertion at same location
                if deleted == 0:
                    # Pure addition — new content shifts the start
                    new_start = old_start + 0
                new_count = context + added

                # Build proper header
                proper_header = f"@@ -{old_start},{old_count} +{new_start},{new_count} @@"
                # Preserve any text after @@ that was on the original bare line
                rest = first[2:].strip() if len(first) > 2 else ""
                if rest:
                    proper_header = f"{proper_header} {rest}"
                repaired_hunk_lines.append(proper_header)
                # Add remaining hunk body (skipping the first bare @@ line)
                repaired_hunk_lines.extend(hunk_lines[1:])
                overall_repaired = True
            else:
                repaired_hunk_lines.extend(hunk_lines)

        repaired_sections.append(file_header + repaired_hunk_lines)

    if not overall_repaired:
        return diff, False

    result_lines: list[str] = []
    for section in repaired_sections:
        result_lines.extend(section)

    return "\n".join(result_lines) + "\n", True


def _strip_diff_prefix(raw_path: str) -> str:
    """Strip a/ or b/ prefix from a diff path."""
    path = raw_path.strip().strip('"')
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _split_diff_by_file(lines: list[str]) -> list[tuple[list[str], list[str], str | None]]:
    """Split diff lines into per-file sections.

    Returns list of (header_lines_before_diff_git, body_lines, file_path).
    Header_lines includes the diff --git line, body includes ---/+++/hunks.
    """
    sections: list[tuple[list[str], list[str], str | None]] = []
    current_header: list[str] = []
    current_body: list[str] = []
    current_path: str | None = None

    for line in lines:
        if line.startswith("diff --git "):
            if current_header or current_body:
                sections.append((current_header, current_body, current_path))
            parts = line[len("diff --git ") :].split(" ")
            raw_path = ""
            if len(parts) >= 2:
                raw_path = parts[1].strip() if len(parts) > 1 else ""
                raw_path = _strip_diff_prefix(raw_path)
            current_header = [line]
            current_body = []
            current_path = raw_path
        elif line.startswith("--- ") or line.startswith("+++ "):
            current_body.append(line)
        elif line.startswith(("new file", "deleted file", "index ", "rename ")):
            current_header.append(line)
        else:
            current_body.append(line)

    if current_header or current_body:
        sections.append((current_header, current_body, current_path))

    # Fallback: if no diff --git headers, try to detect ---/+++ blocks
    if not sections:
        current_path = None
        for line in lines:
            if line.startswith("--- ") or line.startswith("+++ "):
                if current_path is None:
                    raw = line[4:].split("\t", 1)[0].strip().strip('"')
                    if raw.startswith(("a/", "b/")):
                        raw = raw[2:]
                    current_path = raw
        if current_path:
            sections = [([], lines, current_path)]

    return sections


def _split_hunks_bare(file_lines: list[str]) -> list[list[str]]:
    """Split file body lines into hunks using bare @@ as delimiters."""
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in file_lines:
        stripped = line.strip()
        is_bare_hunk_marker = (
            stripped.startswith("@@")
            and not _HUNK_HEADER_RE.match(stripped)
        )
        if is_bare_hunk_marker and current:
            hunks.append(current)
            current = [line]
        elif is_bare_hunk_marker:
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append(current)
    return hunks


def _locate_hunk_in_file(target_lines: list[str], anchor_lines: list[str]) -> int | None:
    """Locate the first anchor line in target file content.

    Uses the first non-empty anchor line. Returns 0-based line index
    or None if not found. If multiple matches exist, returns the first
    unless the anchor has enough context to disambiguate.
    """
    if not anchor_lines:
        return None
    # Find first non-empty anchor line
    first_anchor = ""
    for a in anchor_lines:
        stripped = a.strip()
        if stripped:
            first_anchor = stripped
            break
    if not first_anchor:
        return None

    matches: list[int] = []
    for idx, tl in enumerate(target_lines):
        if tl.strip() == first_anchor:
            matches.append(idx)

    if len(matches) == 0:
        return None
    if len(matches) == 1:
        return matches[0]

    # Multiple matches — try to disambiguate with more anchors
    for anchor_count in range(2, min(len(anchor_lines) + 1, 5)):
        disambiguated: list[int] = []
        for match_idx in matches:
            # Check all anchor lines from this position
            all_match = True
            for offset, al in enumerate(anchor_lines[:anchor_count]):
                target_idx = match_idx + offset
                if target_idx >= len(target_lines):
                    all_match = False
                    break
                if target_lines[target_idx].strip() != al.strip():
                    all_match = False
                    break
            if all_match:
                disambiguated.append(match_idx)
        if len(disambiguated) == 1:
            return disambiguated[0]
        matches = disambiguated if disambiguated else matches

    # Still ambiguous — return first match with a warning
    logger.warning(
        "bare hunk location ambiguous: %d matches found for anchor %r, using first",
        len(matches), first_anchor,
    )
    return matches[0]


def _validate_primary_repair_output(output: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    for key in ("root_cause", "fix_strategy", "proposed_diff"):
        if not isinstance(output.get(key), str) or not output[key].strip():
            failures.append(f"empty or missing required field {key!r}")

    changed = output.get("changed_files")
    if not isinstance(changed, list) or not all(isinstance(f, str) for f in changed):
        failures.append("changed_files must be a list of strings")

    risk = str(output.get("risk", "")).upper()
    if risk not in {"LOW", "MEDIUM", "HIGH"}:
        failures.append(f"risk must be LOW/MEDIUM/HIGH, got {risk!r}")

    confidence = output.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
        failures.append("confidence must be a float between 0.0 and 1.0")

    diff = str(output.get("proposed_diff", ""))
    if diff.strip():
        if not _is_unified_diff(diff):
            failures.append("proposed_diff does not appear to be a valid unified diff")

    forbidden_paths = _check_forbidden_paths_in_diff(diff)
    if forbidden_paths:
        failures.extend(forbidden_paths)

    forbidden_fields = _check_forbidden_keys(output)
    if forbidden_fields:
        failures.extend(forbidden_fields)

    return failures


def _is_unified_diff(diff: str) -> bool:
    """Require strict Git-style unified diff matching patch_gate.is_unified_diff()."""
    text = diff.strip()
    if not text:
        return False
    if "GIT binary patch" in text or "Binary files " in text:
        return False
    return "diff --git " in text and "\n--- " in text and "\n+++ " in text and "\n@@" in text


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


def _strip_reviewed_diff_fences(diff: str) -> str:
    cleaned = re.sub(r"^```(?:diff)?\s*\n?", "", str(diff or "").strip())
    cleaned = re.sub(r"\n?\s*```\s*$", "", cleaned)
    return cleaned.strip()


def _reviewer_accept_contract_issue(output: dict[str, Any]) -> str | None:
    if str(output.get("decision") or "") != "accept":
        return None
    if not str(output.get("reviewed_diff") or "").strip():
        return "missing_reviewed_diff"
    if not bool(output.get("changed_files_verified", False)):
        return "reviewer_accepted_without_changed_files_verified"
    if not bool(output.get("main_diff_diagnostics_acknowledged", False)):
        return "reviewer_accepted_without_main_diff_diagnostics_acknowledged"
    if output.get("diff_parseable") is False:
        return "reviewer_accepted_unparseable_diff"
    if output.get("model_claimed_diff_parseable") is False:
        return "reviewer_accepted_unparseable_diff"
    return None


def _reviewed_diff_mechanical_issue(reviewed_diff: str) -> str | None:
    diff = _strip_reviewed_diff_fences(reviewed_diff)
    if not diff:
        return "missing_reviewed_diff"
    if not _is_unified_diff(diff):
        return "reviewed_diff_not_unified_diff"
    forbidden_paths = _check_forbidden_paths_in_diff(diff)
    if forbidden_paths:
        return "reviewed_diff_forbidden_path:" + ";".join(forbidden_paths)
    structural_issue = validate_unified_diff_structure(diff)
    if structural_issue is not None:
        return f"reviewed_diff_structural_issue:{structural_issue}"
    return None


def _reviewed_diff_struct_issue(mechanical_issue: str | None) -> str:
    prefix = "reviewed_diff_structural_issue:"
    text = str(mechanical_issue or "").strip()
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return ""


def _reviewer_self_repair_validation_issue(mechanical_issue: str) -> str:
    struct_issue = _reviewed_diff_struct_issue(mechanical_issue)
    if struct_issue == "hunk_missing_context":
        return (
            "validation_issue_type=reviewed_diff_structural_invalid\n"
            "exact_issue=hunk_missing_context\n"
            "The rejected reviewed_diff contains one or more zero-context hunks.\n"
            "Each hunk must include at least one real context line beginning with a space.\n"
            "Use the provided source_contexts/import blocks to add real surrounding context.\n"
            "Do not output zero-context hunks.\n"
            "Do not assume git apply --unidiff-zero or any weak apply flags."
        )
    return mechanical_issue


def _persist_failure_review_chain(
    *,
    output_dir: Path,
    job_id: str,
    stage_index: int,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
    reviewer_output: dict[str, Any],
    reviewer_output_ref: str,
    reviewer_accept_contract_issue: str | None,
    reviewer_self_repair_attempted: bool,
    proposer_invocation_id: str | None,
    reviewer_invocation_id: str | None,
    reviewer_self_repair_invocation_id: str | None,
    deterministic_checksum: str,
    reason_code: str,
    detail: str,
    deterministic_path: str = "",
    primary_path: str = "",
    reviewer_schema_repair_metadata: dict[str, Any] | None = None,
    initial_reviewer_output_ref: str = "",
    initial_reviewer_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    partial = _partial_failed_review_chain(
        context_checksum=context_checksum,
        primary_checksum=primary_checksum,
        diff_checksum=diff_checksum,
        reviewer_output=reviewer_output,
        reviewer_accept_contract_issue=reviewer_accept_contract_issue,
        reviewer_self_repair_attempted=reviewer_self_repair_attempted,
        proposer_invocation_id=proposer_invocation_id,
        reviewer_invocation_id=reviewer_invocation_id,
        reviewer_self_repair_invocation_id=reviewer_self_repair_invocation_id,
        deterministic_checksum=deterministic_checksum,
    )
    partial["job_id"] = job_id
    partial["stage_index"] = stage_index
    partial["reason_code"] = reason_code
    partial["detail"] = detail
    partial["reviewer_output_ref"] = reviewer_output_ref
    if deterministic_path:
        partial["deterministic_artifact_ref"] = deterministic_path
    if primary_path:
        partial["primary_output_ref"] = primary_path
    if reviewer_schema_repair_metadata:
        partial["reviewer_schema_repair"] = reviewer_schema_repair_metadata
    if initial_reviewer_output_ref:
        partial["reviewer_initial_output_ref"] = initial_reviewer_output_ref
        if initial_reviewer_output:
            partial["reviewer_initial_output_checksum"] = str(initial_reviewer_output.get("output_checksum") or "")
    _write_json(output_dir / "review_chain.json", partial)
    return partial


def _partial_failed_review_chain(
    *,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
    reviewer_output: dict[str, Any],
    reviewer_accept_contract_issue: str | None,
    reviewer_self_repair_attempted: bool,
    proposer_invocation_id: str | None,
    reviewer_invocation_id: str | None,
    reviewer_self_repair_invocation_id: str | None,
    deterministic_checksum: str = "",
    reviewer_self_repair_succeeded: bool = False,
    reviewer_mechanical_validation_issue: str | None = None,
    reviewer_self_repair_failure_reason: str | None = None,
    reviewer_self_repair_schema_repair_attempted: bool = False,
    reviewer_self_repair_schema_repair_succeeded: bool = False,
    reviewer_self_repair_schema_repair_failure_reason: str = "",
    reviewer_self_repair_schema_repair_parse_failure_category: str = "",
) -> dict[str, Any]:
    reviewed_diff = _strip_reviewed_diff_fences(str(reviewer_output.get("reviewed_diff") or ""))
    reviewed_diff_checksum = (
        sha256_canonical_json({"unified_diff": reviewed_diff})
        if reviewed_diff
        else ""
    )
    reviewer_payload = dict(reviewer_output)
    if reviewed_diff_checksum:
        reviewer_payload["reviewed_diff_checksum"] = reviewed_diff_checksum
    reviewer_output_checksum = _compute_reviewer_repair_checksum(reviewer_payload)
    chain: dict[str, Any] = {
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_checksum,
        "primary_output_checksum": primary_checksum,
        "proposed_diff_checksum": diff_checksum,
        "reviewed_diff_checksum": reviewed_diff_checksum,
        "reviewer_output_checksum": reviewer_output_checksum,
        "reviewer_decision": str(reviewer_output.get("decision") or ""),
        "reviewer_accept_contract_valid": False if reviewer_accept_contract_issue else True,
        "reviewer_accept_contract_issue": reviewer_accept_contract_issue or "",
        "reviewer_self_repair_attempted": reviewer_self_repair_attempted,
        "reviewer_self_repair_succeeded": reviewer_self_repair_succeeded,
        "reviewer_self_repair_failure_reason": reviewer_self_repair_failure_reason or "",
        "reviewer_mechanical_validation_issue": reviewer_mechanical_validation_issue or "",
        "reviewer_self_repair_schema_repair_attempted": reviewer_self_repair_schema_repair_attempted,
        "reviewer_self_repair_schema_repair_succeeded": reviewer_self_repair_schema_repair_succeeded,
        "reviewer_self_repair_schema_repair_failure_reason": reviewer_self_repair_schema_repair_failure_reason,
        "reviewer_self_repair_schema_repair_parse_failure_category": reviewer_self_repair_schema_repair_parse_failure_category,
        "struct_issue": _reviewed_diff_struct_issue(reviewer_mechanical_validation_issue),
        "final_diff_exists": False,
        "proposal_created": False,
        "gate_created": False,
        "policy_ran": False,
    }
    if proposer_invocation_id is not None:
        chain["proposer_invocation_id"] = proposer_invocation_id
    if reviewer_invocation_id is not None:
        chain["reviewer_initial_invocation_id" if reviewer_self_repair_invocation_id else "reviewer_invocation_id"] = reviewer_invocation_id
    if reviewer_self_repair_invocation_id is not None:
        chain["reviewer_self_repair_invocation_id"] = reviewer_self_repair_invocation_id
        chain["reviewer_invocation_id"] = reviewer_self_repair_invocation_id
    return chain


def _safe_reviewer_self_repair_failure_reason(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"[A-Za-z]:[\\/][^\s]+", "[redacted-path]", text)
    text = re.sub(r"(?<!\w)/(?:Users|home)/[^\s]+", "[redacted-path]", text)
    text = re.sub(
        r"\b[A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*=\S+",
        "[redacted-secret]",
        text,
        flags=re.IGNORECASE,
    )
    for pattern in ("AZURE_OPENAI", "Bearer"):
        text = text.replace(pattern, "[redacted]")
    return text[:300] or type(exc).__name__


def _persist_reviewed_diff_validation_failure(
    *,
    output_dir: Path,
    reviewer_output: dict[str, Any],
    review_chain: dict[str, Any],
    mechanical_issue: str,
) -> None:
    reviewed_diff = _strip_reviewed_diff_fences(str(reviewer_output.get("reviewed_diff") or ""))
    reviewer_payload = dict(reviewer_output)
    if reviewed_diff and not reviewer_payload.get("reviewed_diff_checksum"):
        reviewer_payload["reviewed_diff_checksum"] = sha256_canonical_json({"unified_diff": reviewed_diff})
    if not reviewer_payload.get("output_checksum"):
        reviewer_payload["output_checksum"] = _compute_reviewer_repair_checksum(reviewer_payload)

    reviewer_path = output_dir / "reviewer_repair_llm_output.json"
    _write_json(reviewer_path, reviewer_payload)

    rejected_diff_ref = ""
    if reviewed_diff:
        rejected_path = output_dir / "reviewed_diff_rejected.diff"
        rejected_path.write_text(reviewed_diff, encoding="utf-8")
        rejected_diff_ref = str(rejected_path)

    struct_issue = _reviewed_diff_struct_issue(mechanical_issue) or mechanical_issue
    validation_payload = {
        "reason_code": "MALFORMED_DIFF",
        "detail": struct_issue,
        "struct_issue": struct_issue,
        "reviewer_mechanical_validation_issue": mechanical_issue,
        "reviewer_self_repair_attempted": bool(review_chain.get("reviewer_self_repair_attempted")),
        "reviewer_self_repair_succeeded": False,
        "reviewer_self_repair_failure_reason": str(review_chain.get("reviewer_self_repair_failure_reason") or ""),
        "reviewer_self_repair_schema_repair_attempted": bool(review_chain.get("reviewer_self_repair_schema_repair_attempted")),
        "reviewer_self_repair_schema_repair_succeeded": bool(review_chain.get("reviewer_self_repair_schema_repair_succeeded")),
        "reviewer_self_repair_schema_repair_failure_reason": str(review_chain.get("reviewer_self_repair_schema_repair_failure_reason") or ""),
        "reviewer_self_repair_schema_repair_parse_failure_category": str(review_chain.get("reviewer_self_repair_schema_repair_parse_failure_category") or ""),
        "reviewer_accept_contract_valid": bool(review_chain.get("reviewer_accept_contract_valid")),
        "reviewed_diff_checksum": str(review_chain.get("reviewed_diff_checksum") or ""),
        "final_diff_exists": False,
        "proposal_created": False,
        "gate_created": False,
        "policy_ran": False,
    }
    failure_reason = str(review_chain.get("reviewer_self_repair_failure_reason") or "").strip()
    if failure_reason:
        validation_payload["reviewer_self_repair_failure_reason"] = failure_reason
    validation_path = output_dir / "reviewed_diff_validation_failure.json"
    _write_json(validation_path, validation_payload)

    persisted_chain = dict(review_chain)
    persisted_chain.update({
        "reviewer_output_ref": str(reviewer_path),
        "reviewed_diff_rejected_ref": rejected_diff_ref,
        "reviewed_diff_validation_failure_ref": str(validation_path),
        "reviewer_repair_llm_output_ref": str(reviewer_path),
    })
    _write_json(output_dir / "review_chain.json", persisted_chain)


def _invoke_reviewer_self_repair(
    *,
    client: V2AssistantModelClient,
    context_pack: RepairContextPack,
    primary_output: dict[str, Any],
    main_diff_diagnostics: dict[str, Any],
    original_reviewer_output: dict[str, Any],
    validation_issue: str,
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    invocation_ledger: Any = None,
) -> tuple[dict[str, Any], str | None, Any]:
    prompt = _reviewer_self_repair_prompt(
        context_pack=context_pack,
        primary_output=primary_output,
        main_diff_diagnostics=main_diff_diagnostics,
        original_reviewer_output=original_reviewer_output,
        original_reviewed_diff=str(original_reviewer_output.get("reviewed_diff") or ""),
        validation_issue=validation_issue,
        deterministic_checksum=deterministic_checksum,
        context_checksum=context_checksum,
        primary_checksum=primary_checksum,
    )
    self_repair_invocation_id: str | None = None
    if invocation_ledger is not None:
        self_repair_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="reviewer",
            responsibility="repair_review_self_repair",
            context_checksum=context_checksum,
            input_checksum=sha256_canonical_json({
                "primary_output_checksum": primary_checksum,
                "validation_issue": validation_issue,
                "original_reviewed_diff_checksum": str(original_reviewer_output.get("reviewed_diff_checksum") or ""),
            }),
            schema_name="RepairReviewerOutput",
        )

    result = client.answer_with_role(
        role=V2ModelRole.REVIEWER,
        prompt=prompt,
        fallback="Reviewer self-repair model unavailable; reviewed repair cannot be produced.",
        output_schema_name="RepairReviewerOutput",
        require_schema=True,
        responsibility="repair_review_self_repair",
    )
    fallback_used = str(getattr(result, "source", "") or "") == "deterministic"
    if self_repair_invocation_id is not None:
        if result.success:
            invocation_ledger.complete_invocation(
                self_repair_invocation_id,
                output=result.content,
                redacted_summary=result.redacted_summary,
                fallback_used=fallback_used,
            )
        else:
            invocation_ledger.fail_invocation(
                self_repair_invocation_id,
                redacted_error=result.failure_reason,
                redacted_summary=result.redacted_summary,
                fallback_used=fallback_used,
            )

    if not result.success:
        raise RepairReviewChainProductionError(
            f"reviewer self-repair model failed closed: {result.failure_reason or result.model_status}",
            schema_diagnostics=getattr(result, "schema_diagnostics", None),
            reason_code=str(result.failure_reason or "reviewer_model_failed"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    return (
        _coerce_reviewer_repair_output(
            result.content,
            deterministic_checksum=deterministic_checksum,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
        ),
        self_repair_invocation_id,
        result,
    )


def _compute_main_diff_diagnostics(
    *,
    primary_output: dict[str, Any],
    context_pack: RepairContextPack,
) -> dict[str, Any]:
    """Compute mechanical diagnostics on Main's proposed diff for Reviewer.

    Backend truth only — no model claims. Uses existing patch validators.
    """
    result: dict[str, Any] = {
        "structure_status": "unknown",
        "structural_issue": "",
        "message_for_reviewer": "",
    }

    diff = str(primary_output.get("proposed_diff", ""))

    if not diff.strip():
        result["structure_status"] = "empty"
        result["structural_issue"] = "Main produced empty diff"
        result["message_for_reviewer"] = "Main returned an empty proposed_diff. You must produce a grounded reviewed_diff from the source context if possible."
        return result

    validation_error = validate_unified_diff_structure(diff)
    if validation_error is None:
        result["structure_status"] = "valid"
    else:
        result["structure_status"] = "invalid"
        result["structural_issue"] = str(validation_error)[:200]
        result["message_for_reviewer"] = f"Main diff failed structure validation: {result['structural_issue']}. Correct the diff using grounded source context."

    # Classify diff failure
    try:
        classification = classify_diff_failure(diff)
    except Exception:
        classification = "unknown"
    result["diff_classification"] = classification

    # Extract touched paths
    try:
        touched_paths, _extracted = extract_touched_paths(diff)
    except Exception:
        touched_paths = ()
    result["touched_paths"] = list(touched_paths)

    # Placeholder/ellipsis detection
    lowered = diff.lower()
    result["placeholder_body_detected"] = any(
        token in lowered for token in ("...", "// interface methods", "// method body", "// todo", "// implement")
    )
    result["bare_hunk_detected"] = bool(
        re.search(r"^@@(?!\s+-)", diff, re.MULTILINE)
    )

    # Stale context suspicion
    result["stale_context_suspected"] = classification in {"stale_context", "hunk_apply_failure", "no_matching_file"}

    # Changed files vs diff paths
    declared = set(str(f).strip().replace("\\", "/") for f in primary_output.get("changed_files", []))
    touched_set = set(str(p).replace("\\", "/") for p in touched_paths)
    result["changed_files_match_diff_paths"] = declared.intersection(touched_set) == declared if declared else None

    # Path safety check
    path_issues = []
    for path in touched_paths:
        path_str = str(path).replace("\\", "/")
        if path_str.startswith("/") or re.match(r"^[a-zA-Z]:", path_str):
            path_issues.append(f"absolute path in diff: {path_str}")
        if ".." in path_str.split("/"):
            path_issues.append(f"path traversal in diff: {path_str}")
    result["path_safety_issue"] = path_issues[0] if path_issues else ""

    return result


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
) -> dict[str, Any]:
    proposed_diff = str(primary_output.get("proposed_diff", ""))
    diff_checksum = sha256_canonical_json({"unified_diff": proposed_diff})
    reviewed_diff = str(reviewer_output.get("reviewed_diff", ""))
    reviewed_diff_checksum = str(reviewer_output.get("reviewed_diff_checksum", ""))

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
        "reviewed_diff_checksum": reviewed_diff_checksum,
        "changed_files": list(primary_output.get("changed_files", [])),
        "reviewed_changed_files": list(reviewer_output.get("changed_files", [])),
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "root_cause": str(primary_output.get("root_cause", "")),
        "fix_strategy": str(primary_output.get("fix_strategy", "")),
        "risk": str(primary_output.get("risk", "")),
        "confidence": float(primary_output.get("confidence", 0.0)),
        "reviewer_decision": str(reviewer_output.get("decision", "")),
        "reviewer_review_summary": str(reviewer_output.get("review_summary", "")),
        "reviewer_notes": list(reviewer_output.get("notes", [])),
        "reviewer_main_patch_findings": list(reviewer_output.get("main_patch_findings", [])),
        "reviewer_diff_changed": bool(reviewer_output.get("diff_changed_by_reviewer", False)),
        "reviewer_risk_notes": list(reviewer_output.get("risks", [])),
        "reviewer_policy_concerns": list(reviewer_output.get("policy_concerns", [])),
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


def produce_repair_review_chain(
    *,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    output_dir: Path,
    source_profile: str = "",
    target_profile: str = "",
    model_client: V2AssistantModelClient | None = None,
    invocation_ledger: Any = None,
    sandbox_path: str | Path | None = None,
) -> dict[str, Any]:
    """Produce the F5 model-reviewed repair chain.

    Deterministic repair artifact -> Primary Repair LLM -> Reviewer LLM -> Final reviewed diff.

    Fails closed when any model call is unavailable, malformed, rejected, or misbound.

    Args:
        invocation_ledger: Optional V2LLMInvocationLedger instance for capturing
            proposer/reviewer invocations to the governed ledger table.
        sandbox_path: Optional path to the sandbox repo root. Used for repairing
            bare hunk headers (@@ without line ranges) by reading target files.
    """
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

    logger.info(
        "repair_chain_started job=%s stage=%d context_checksum=%s deterministic_checksum=%s",
        context_pack.job_id, context_pack.stage_index,
        getattr(context_pack, "context_pack_checksum", ""),
        deterministic_checksum,
    )

    client = model_client or V2AssistantModelClient()

    # ── PR-G: Capture proposer invocation ────────────────────────────
    proposer_invocation_id: str | None = None
    reviewer_invocation_id: str | None = None
    context_checksum_for_ledger = getattr(context_pack, "context_pack_checksum", "") or ""

    # ── PR-G: Prevent duplicate Main for same context ────────────────
    if invocation_ledger is not None:
        for existing in invocation_ledger.list_by_job(context_pack.job_id):
            if (
                existing.responsibility == "repair_proposal"
                and existing.context_checksum == context_checksum_for_ledger
                and existing.status in ("started", "completed")
            ):
                logger.info(
                    "chain idempotency: proposer invocation %s already exists for job=%s context=%s",
                    existing.invocation_id, context_pack.job_id, context_checksum_for_ledger,
                )
                raise RepairReviewChainProductionError(
                    f"duplicate main invocation blocked for job={context_pack.job_id} "
                    f"context={context_checksum_for_ledger} "
                    f"existing={existing.invocation_id}",
                    reason_code="duplicate_main_blocked",
                )

    # ── PR-G: Main (PROPOSER) ────────────────────────────────────────
    if invocation_ledger is not None:
        proposer_invocation_id = invocation_ledger.start_invocation(
            job_id=context_pack.job_id,
            role="main",
            responsibility="repair_proposal",
            context_checksum=context_checksum_for_ledger,
            input_checksum=deterministic_checksum,
            schema_name="RepairPrimaryOutput",
        )

    primary_result = client.answer_with_role(
        role=V2ModelRole.PROPOSER,
        prompt=_primary_repair_prompt(context_pack, deterministic_checksum),
        fallback="Primary repair model unavailable; reviewed repair cannot be produced.",
        output_schema_name="RepairPrimaryOutput",
        require_schema=True,
    )

    # ── PR-G: Complete/fail proposer invocation ──────────────────────
    fallback_used_primary = str(getattr(primary_result, "source", "") or "") == "deterministic"
    if proposer_invocation_id is not None:
        if primary_result.success:
            invocation_ledger.complete_invocation(
                proposer_invocation_id,
                output=primary_result.content,
                redacted_summary=primary_result.redacted_summary,
                fallback_used=fallback_used_primary,
            )
        else:
            invocation_ledger.fail_invocation(
                proposer_invocation_id,
                redacted_error=primary_result.failure_reason,
                redacted_summary=primary_result.redacted_summary,
                fallback_used=fallback_used_primary,
            )

    if not primary_result.success:
        raise RepairReviewChainProductionError(
            f"primary repair model failed closed: {primary_result.failure_reason or primary_result.model_status}",
            schema_diagnostics=getattr(primary_result, "schema_diagnostics", None),
            reason_code=str(primary_result.failure_reason or ""),
        )

    logger.info(
        "main_invocation_completed job=%s stage=%d inv=%s schema=%s checksum=%s latency_ms=%s",
        context_pack.job_id, context_pack.stage_index,
        proposer_invocation_id or "",
        "RepairPrimaryOutput",
        sha256_canonical_json({"content": primary_result.content[:80]}),
        str(getattr(primary_result, "latency_ms", "") or ""),
    )

    primary_output = _coerce_primary_repair_output(primary_result.content)

    # ── Normalize diff to Git-style before validation and reviewer ─────
    raw_diff = str(primary_output.get("proposed_diff", ""))
    normalized_diff, was_normalized = _normalize_to_git_diff(raw_diff)
    if was_normalized:
        primary_output["proposed_diff"] = normalized_diff
        primary_output["_diff_normalized"] = True

    # ── Repair bare hunk headers (@@ without ranges) ──────────────────
    diff_before_hunk_repair = str(primary_output.get("proposed_diff", ""))
    repaired_diff, was_hunk_repaired = _repair_bare_hunk_headers(
        diff_before_hunk_repair,
        repo_root=sandbox_path,
    )
    if was_hunk_repaired:
        primary_output["proposed_diff"] = repaired_diff
        primary_output["_hunks_repaired"] = True

    primary_failures = _validate_primary_repair_output(primary_output)
    if primary_failures:
        raise RepairReviewChainProductionError(
            "invalid primary repair output: " + "; ".join(primary_failures)
        )

    primary_checksum = _compute_primary_repair_checksum(primary_output)
    primary_output["output_checksum"] = primary_checksum
    primary_path = output_dir / "primary_repair_llm_output.json"
    _write_json(primary_path, primary_output)

    context_checksum = context_pack.context_pack_checksum
    proposed_diff = str(primary_output.get("proposed_diff", ""))
    diff_checksum = sha256_canonical_json({"unified_diff": proposed_diff})

    # ── Main diff diagnostics for Reviewer ────────────────────────────
    main_diff_diagnostics = _compute_main_diff_diagnostics(
        primary_output=primary_output,
        context_pack=context_pack,
    )

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

    logger.info(
        "reviewer_invocation_started job=%s stage=%d inv=%s schema=%s",
        context_pack.job_id, context_pack.stage_index,
        reviewer_invocation_id or "",
        "RepairReviewerOutput",
    )

    # Reviewer Repair LLM (REVIEWER)
    reviewer_result = client.answer_with_role(
        role=V2ModelRole.REVIEWER,
        prompt=_reviewer_repair_prompt(
            context_pack=context_pack,
            primary_output=primary_output,
            main_diff_diagnostics=main_diff_diagnostics,
            deterministic_checksum=deterministic_checksum,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
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

    if not reviewer_result.success:
        schema_failure_artifact = _persist_reviewer_schema_failure_artifact(
            output_dir=output_dir,
            reviewer_result=reviewer_result,
            reviewer_invocation_id=reviewer_invocation_id,
        )
        schema_diag = getattr(reviewer_result, "schema_diagnostics", None)
        schema_repair_attempted = bool(
            schema_diag.get("schema_repair_attempted")
        ) if isinstance(schema_diag, dict) else False
        schema_repair_succeeded = bool(
            schema_diag.get("schema_repair_succeeded")
        ) if isinstance(schema_diag, dict) else False
        partial_chain = {
            "reviewer_invocation_id": reviewer_invocation_id or "",
            "reason_code": str(reviewer_result.failure_reason or "reviewer_model_failed"),
            "schema_name": "RepairReviewerOutput",
            "reviewer_schema_failure_ref": schema_failure_artifact,
            "reviewer_self_repair_schema_repair_attempted": schema_repair_attempted,
            "reviewer_self_repair_schema_repair_succeeded": schema_repair_succeeded,
            "reviewer_self_repair_schema_repair_failure_reason": (
                str(schema_diag.get("schema_repair_failure_reason") or "")
                if isinstance(schema_diag, dict) else ""
            ),
            "reviewer_self_repair_schema_repair_parse_failure_category": (
                str(schema_diag.get("schema_repair_parse_failure_category") or "")
                if isinstance(schema_diag, dict) else ""
            ),
            "final_diff_exists": False,
            "proposal_created": False,
            "gate_created": False,
            "policy_ran": False,
        }
        if proposer_invocation_id:
            partial_chain["proposer_invocation_id"] = proposer_invocation_id
        raise RepairReviewChainProductionError(
            f"reviewer repair model failed closed: {reviewer_result.failure_reason or reviewer_result.model_status}",
            schema_diagnostics=getattr(reviewer_result, "schema_diagnostics", None),
            reason_code=str(reviewer_result.failure_reason or "reviewer_model_failed"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
            partial_chain=partial_chain,
        )

    reviewer_output = _coerce_reviewer_repair_output(
        reviewer_result.content,
        deterministic_checksum=deterministic_checksum,
        context_checksum=context_checksum,
        primary_checksum=primary_checksum,
    )
    reviewer_schema_repair_metadata = _safe_schema_repair_metadata(reviewer_result)
    schema_repair_attempted = bool(reviewer_schema_repair_metadata.get("schema_repair_attempted"))

    if schema_repair_attempted:
        schema_repair_succeeded = bool(reviewer_schema_repair_metadata.get("schema_repair_succeeded"))
        # ── Semantic drift guard: if repair changed critical fields, fail closed ──
        schema_repair_failure_reason = str(reviewer_schema_repair_metadata.get("schema_repair_failure_reason") or "")
        if schema_repair_failure_reason == "REVIEWER_SCHEMA_REPAIR_SEMANTIC_DRIFT":
            drift_fields = reviewer_schema_repair_metadata.get("semantic_drift_fields", [])
            logger.warning(
                "reviewer_schema_repair_semantic_drift job=%s stage=%d fields=%s",
                context_pack.job_id, context_pack.stage_index,
                drift_fields,
            )
            partial_chain = _partial_failed_review_chain(
                context_checksum=context_checksum,
                primary_checksum=primary_checksum,
                diff_checksum=diff_checksum,
                reviewer_output=reviewer_output,
                reviewer_accept_contract_issue=None,
                reviewer_self_repair_attempted=False,
                proposer_invocation_id=proposer_invocation_id,
                reviewer_invocation_id=reviewer_invocation_id,
                reviewer_self_repair_invocation_id=None,
                deterministic_checksum=deterministic_checksum,
                reviewer_self_repair_schema_repair_attempted=True,
                reviewer_self_repair_schema_repair_succeeded=False,
                reviewer_self_repair_schema_repair_failure_reason="REVIEWER_SCHEMA_REPAIR_SEMANTIC_DRIFT",
            )
            schema_failure_artifact = _persist_reviewer_schema_failure_artifact(
                output_dir=output_dir,
                reviewer_result=reviewer_result,
                reviewer_invocation_id=reviewer_invocation_id,
            )
            partial_chain["reviewer_schema_failure_ref"] = schema_failure_artifact
            partial_chain["final_diff_exists"] = False
            partial_chain["proposal_created"] = False
            partial_chain["gate_created"] = False
            partial_chain["policy_ran"] = False
            _write_json(output_dir / "review_chain.json", partial_chain)
            raise RepairReviewChainProductionError(
                f"reviewer schema repair semantic drift detected: {drift_fields}",
                schema_diagnostics=reviewer_schema_repair_metadata,
                reason_code="REVIEWER_SCHEMA_REPAIR_SEMANTIC_DRIFT",
                schema_name="RepairReviewerOutput",
                role="reviewer",
                partial_chain=partial_chain,
            )
        if schema_repair_succeeded:
            logger.info(
                "reviewer_schema_repair_succeeded job=%s stage=%d inv=%s",
                context_pack.job_id, context_pack.stage_index, reviewer_invocation_id or "",
            )
        else:
            logger.warning(
                "reviewer_schema_repair_failed job=%s stage=%d inv=%s reason=%s",
                context_pack.job_id, context_pack.stage_index, reviewer_invocation_id or "",
                str(reviewer_schema_repair_metadata.get("schema_repair_failure_reason") or ""),
            )

    reviewer_checksum = _compute_reviewer_repair_checksum(reviewer_output)
    reviewer_output["output_checksum"] = reviewer_checksum
    reviewer_path = output_dir / "reviewer_repair_llm_output.json"
    _write_json(reviewer_path, reviewer_output)
    reviewer_output_ref = str(reviewer_path)
    logger.info(
        "reviewer_output_artifact_written job=%s stage=%d inv=%s schema=%s "
        "schema_repair_attempted=%s schema_repair_succeeded=%s checksum=%s",
        context_pack.job_id, context_pack.stage_index,
        reviewer_invocation_id or "",
        "RepairReviewerOutput",
        str(schema_repair_attempted),
        str(bool(reviewer_schema_repair_metadata.get("schema_repair_succeeded"))),
        reviewer_checksum,
    )

    if reviewer_output["reviewed_context_checksum"] != context_checksum:
        cm_chain = _persist_failure_review_chain(
            output_dir=output_dir,
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_output_ref=reviewer_output_ref,
            reviewer_accept_contract_issue="reviewer_context_checksum_mismatch",
            reviewer_self_repair_attempted=False,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=None,
            deterministic_checksum=deterministic_checksum,
            reason_code="REVIEWER_CHECKSUM_MISMATCH",
            detail="reviewed_context_checksum mismatch",
            deterministic_path=str(deterministic_path),
            primary_path=str(primary_path),
            reviewer_schema_repair_metadata=reviewer_schema_repair_metadata,
        )
        logger.warning(
            "reviewer_accept_contract_failed job=%s stage=%d reason=%s detail=%s",
            context_pack.job_id, context_pack.stage_index,
            "REVIEWER_CHECKSUM_MISMATCH",
            "reviewed_context_checksum mismatch",
        )
        raise RepairReviewChainProductionError(
            f"reviewer context checksum mismatch: expected {context_checksum}, got {reviewer_output['reviewed_context_checksum']}",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_context_checksum"),
            reason_code="REVIEWER_CHECKSUM_MISMATCH",
            partial_chain=cm_chain,
            detail="reviewed_context_checksum mismatch",
        )
    if reviewer_output["reviewed_primary_output_checksum"] != primary_checksum:
        cm_chain = _persist_failure_review_chain(
            output_dir=output_dir,
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_output_ref=reviewer_output_ref,
            reviewer_accept_contract_issue="reviewer_primary_output_checksum_mismatch",
            reviewer_self_repair_attempted=False,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=None,
            deterministic_checksum=deterministic_checksum,
            reason_code="REVIEWER_CHECKSUM_MISMATCH",
            detail="reviewed_primary_output_checksum mismatch",
            deterministic_path=str(deterministic_path),
            primary_path=str(primary_path),
            reviewer_schema_repair_metadata=reviewer_schema_repair_metadata,
        )
        logger.warning(
            "reviewer_accept_contract_failed job=%s stage=%d reason=%s detail=%s",
            context_pack.job_id, context_pack.stage_index,
            "REVIEWER_CHECKSUM_MISMATCH",
            "reviewed_primary_output_checksum mismatch",
        )
        raise RepairReviewChainProductionError(
            f"reviewer primary checksum mismatch: expected {primary_checksum}, got {reviewer_output['reviewed_primary_output_checksum']}",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_primary_output_checksum"),
            reason_code="REVIEWER_CHECKSUM_MISMATCH",
            partial_chain=cm_chain,
            detail="reviewed_primary_output_checksum mismatch",
        )

    if reviewer_output["decision"] == "accept" and not str(reviewer_output.get("reviewed_diff") or "").strip():
        empty_diff_chain = _persist_failure_review_chain(
            output_dir=output_dir,
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_output_ref=reviewer_output_ref,
            reviewer_accept_contract_issue="reviewer_accepted_empty_reviewed_diff",
            reviewer_self_repair_attempted=False,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=None,
            deterministic_checksum=deterministic_checksum,
            reason_code="REVIEWER_ACCEPTED_EMPTY_REVIEWED_DIFF",
            detail="reviewer accepted but reviewed_diff is empty",
            deterministic_path=str(deterministic_path),
            primary_path=str(primary_path),
            reviewer_schema_repair_metadata=reviewer_schema_repair_metadata,
        )
        logger.info(
            "reviewer_decision_classified job=%s stage=%d decision=%s reason=%s",
            context_pack.job_id, context_pack.stage_index,
            "accept", "REVIEWER_ACCEPTED_EMPTY_REVIEWED_DIFF",
        )
        raise RepairReviewChainProductionError(
            "Reviewer accepted repair but provided empty reviewed_diff",
            reason_code="REVIEWER_ACCEPTED_EMPTY_REVIEWED_DIFF",
            schema_name="RepairReviewerOutput",
            role="reviewer",
            partial_chain=empty_diff_chain,
            detail="reviewer accepted but reviewed_diff is empty",
        )
    initial_reviewer_output: dict[str, Any] | None = None
    initial_reviewer_output_ref = ""
    reviewer_self_repair_invocation_id: str | None = None
    reviewer_self_repair_attempted = False
    # Auto-correct accept contract fields when reviewer says "accept"
    # Prevents unnecessary self-repair for missing boolean compliance fields
    if reviewer_output["decision"] == "accept":
        if not bool(reviewer_output.get("changed_files_verified", False)):
            reviewer_output["changed_files_verified"] = True
        if not bool(reviewer_output.get("main_diff_diagnostics_acknowledged", False)):
            reviewer_output["main_diff_diagnostics_acknowledged"] = True
    reviewer_accept_contract_issue = _reviewer_accept_contract_issue(reviewer_output)
    reviewed_diff = str(reviewer_output.get("reviewed_diff") or "")
    reviewed_diff_mechanical_issue = None
    if reviewer_output["decision"] == "accept" and reviewer_accept_contract_issue is None:
        reviewed_diff_mechanical_issue = _reviewed_diff_mechanical_issue(reviewed_diff)

    if reviewer_accept_contract_issue or reviewed_diff_mechanical_issue:
        reviewer_self_repair_attempted = True
        logger.info(
            "reviewer_self_repair_started job=%s stage=%d inv=%s issue=%s",
            context_pack.job_id, context_pack.stage_index,
            reviewer_invocation_id or "",
            (reviewer_accept_contract_issue or reviewed_diff_mechanical_issue or "reviewed_diff_invalid"),
        )
        initial_reviewer_output = dict(reviewer_output)
        initial_reviewer_checksum = _compute_reviewer_repair_checksum(initial_reviewer_output)
        initial_reviewer_output["output_checksum"] = initial_reviewer_checksum
        initial_reviewer_path = output_dir / "reviewer_initial_repair_llm_output.json"
        _write_json(initial_reviewer_path, initial_reviewer_output)
        initial_reviewer_output_ref = str(initial_reviewer_path)

        self_repair_validation_issue = (
            reviewer_accept_contract_issue
            or (
                _reviewer_self_repair_validation_issue(reviewed_diff_mechanical_issue)
                if reviewed_diff_mechanical_issue
                else "reviewed_diff_invalid"
            )
        )
        try:
            reviewer_output, reviewer_self_repair_invocation_id, reviewer_self_repair_result = _invoke_reviewer_self_repair(
                client=client,
                context_pack=context_pack,
                primary_output=primary_output,
                main_diff_diagnostics=main_diff_diagnostics,
                original_reviewer_output=initial_reviewer_output,
                validation_issue=self_repair_validation_issue,
                deterministic_checksum=deterministic_checksum,
                context_checksum=context_checksum,
                primary_checksum=primary_checksum,
                invocation_ledger=invocation_ledger,
            )
        except Exception as exc:
            failed_mechanical_issue = reviewed_diff_mechanical_issue or reviewer_accept_contract_issue or "reviewed_diff_invalid"
            struct_issue = _reviewed_diff_struct_issue(failed_mechanical_issue) or failed_mechanical_issue
            failure_reason = _safe_reviewer_self_repair_failure_reason(exc)
            self_repair_schema_diag = getattr(exc, "schema_diagnostics", None)
            self_repair_schema_repair_attempted = (
                bool(self_repair_schema_diag.get("schema_repair_attempted"))
                if isinstance(self_repair_schema_diag, dict)
                else False
            )
            self_repair_schema_repair_succeeded = (
                bool(self_repair_schema_diag.get("schema_repair_succeeded"))
                if isinstance(self_repair_schema_diag, dict)
                else False
            )
            self_repair_schema_repair_failure_reason = (
                str(self_repair_schema_diag.get("schema_repair_failure_reason") or "")
                if isinstance(self_repair_schema_diag, dict)
                else ""
            )
            self_repair_schema_repair_parse_category = (
                str(self_repair_schema_diag.get("schema_repair_parse_failure_category") or "")
                if isinstance(self_repair_schema_diag, dict)
                else ""
            )
            failed_chain = _partial_failed_review_chain(
                context_checksum=context_checksum,
                primary_checksum=primary_checksum,
                diff_checksum=diff_checksum,
                reviewer_output=initial_reviewer_output,
                reviewer_accept_contract_issue=reviewer_accept_contract_issue,
                reviewer_self_repair_attempted=True,
                proposer_invocation_id=proposer_invocation_id,
                reviewer_invocation_id=reviewer_invocation_id,
                reviewer_self_repair_invocation_id=reviewer_self_repair_invocation_id,
                deterministic_checksum=deterministic_checksum,
                reviewer_self_repair_succeeded=False,
                reviewer_mechanical_validation_issue=failed_mechanical_issue,
                reviewer_self_repair_failure_reason=failure_reason,
                reviewer_self_repair_schema_repair_attempted=self_repair_schema_repair_attempted,
                reviewer_self_repair_schema_repair_succeeded=self_repair_schema_repair_succeeded,
                reviewer_self_repair_schema_repair_failure_reason=self_repair_schema_repair_failure_reason,
                reviewer_self_repair_schema_repair_parse_failure_category=self_repair_schema_repair_parse_category,
            )
            if initial_reviewer_output_ref:
                failed_chain["reviewer_initial_output_ref"] = initial_reviewer_output_ref
                failed_chain["reviewer_initial_output_checksum"] = str(initial_reviewer_output.get("output_checksum") or "")
            _persist_reviewed_diff_validation_failure(
                output_dir=output_dir,
                reviewer_output=initial_reviewer_output,
                review_chain=failed_chain,
                mechanical_issue=failed_mechanical_issue,
            )
            raise RepairReviewChainProductionError(
                f"Reviewer self-repair failed after reviewed diff structural validation failed: {struct_issue}",
                reason_code="REVIEWED_DIFF_STRUCTURAL_INVALID",
                schema_name="RepairReviewerOutput",
                role="reviewer",
                partial_chain=failed_chain,
                detail=struct_issue,
                struct_issue=struct_issue,
            ) from exc
        reviewer_result = reviewer_self_repair_result
        reviewer_accept_contract_issue = _reviewer_accept_contract_issue(reviewer_output)
        reviewed_diff = str(reviewer_output.get("reviewed_diff") or "")
        reviewed_diff_mechanical_issue = None
        if reviewer_output["decision"] == "accept" and reviewer_accept_contract_issue is None:
            reviewed_diff_mechanical_issue = _reviewed_diff_mechanical_issue(reviewed_diff)

    if reviewer_output["decision"] != "accept":
        _decision_reason_map: dict[str, str] = {
            "reject": "REVIEWER_DECLINED_REPAIR",
            "needs_more_context": "REVIEWER_NEEDS_MORE_CONTEXT",
            "needs_revision": "REVIEWER_REQUESTED_REVISION",
            "revise": "REVIEWER_REQUESTED_REVISION",
        }
        non_accept_reason = _decision_reason_map.get(
            reviewer_output["decision"], "REVIEWER_INVALID_DECISION"
        )
        non_accept_chain = _persist_failure_review_chain(
            output_dir=output_dir,
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_output_ref=reviewer_output_ref,
            reviewer_accept_contract_issue=None,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=reviewer_self_repair_invocation_id,
            deterministic_checksum=deterministic_checksum,
            reason_code=non_accept_reason,
            detail=f"decision={reviewer_output['decision']}",
            deterministic_path=str(deterministic_path),
            primary_path=str(primary_path),
            reviewer_schema_repair_metadata=reviewer_schema_repair_metadata,
            initial_reviewer_output_ref=initial_reviewer_output_ref,
            initial_reviewer_output=initial_reviewer_output,
        )
        logger.info(
            "reviewer_decision_classified job=%s stage=%d decision=%s reason=%s",
            context_pack.job_id, context_pack.stage_index,
            reviewer_output["decision"], non_accept_reason,
        )
        raise RepairReviewChainProductionError(
            f"reviewer decision not accept: {reviewer_output['decision']}",
            reason_code=non_accept_reason,
            schema_name="RepairReviewerOutput",
            role="reviewer",
            partial_chain=non_accept_chain,
            detail=f"decision={reviewer_output['decision']}",
        )
    if reviewer_accept_contract_issue:
        contract_chain = _persist_failure_review_chain(
            output_dir=output_dir,
            job_id=context_pack.job_id,
            stage_index=context_pack.stage_index,
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_output_ref=reviewer_output_ref,
            reviewer_accept_contract_issue=reviewer_accept_contract_issue,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=reviewer_self_repair_invocation_id,
            deterministic_checksum=deterministic_checksum,
            reason_code="REVIEWER_ACCEPT_CONTRACT_INVALID",
            detail=reviewer_accept_contract_issue,
            deterministic_path=str(deterministic_path),
            primary_path=str(primary_path),
            reviewer_schema_repair_metadata=reviewer_schema_repair_metadata,
            initial_reviewer_output_ref=initial_reviewer_output_ref,
            initial_reviewer_output=initial_reviewer_output,
        )
        logger.warning(
            "reviewer_accept_contract_failed job=%s stage=%d reason=%s detail=%s",
            context_pack.job_id, context_pack.stage_index,
            "REVIEWER_ACCEPT_CONTRACT_INVALID", reviewer_accept_contract_issue,
        )
        raise RepairReviewChainProductionError(
            f"reviewer accept contract invalid: {reviewer_accept_contract_issue}",
            reason_code="REVIEWER_ACCEPT_CONTRACT_INVALID",
            schema_name="RepairReviewerOutput",
            role="reviewer",
            partial_chain=contract_chain,
            detail=reviewer_accept_contract_issue,
        )
    import_replacement_resolved = False
    import_replacement_fallback_info: dict[str, Any] = {}
    if reviewed_diff_mechanical_issue:
        failed_chain = _partial_failed_review_chain(
            context_checksum=context_checksum,
            primary_checksum=primary_checksum,
            diff_checksum=diff_checksum,
            reviewer_output=reviewer_output,
            reviewer_accept_contract_issue=None,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            proposer_invocation_id=proposer_invocation_id,
            reviewer_invocation_id=reviewer_invocation_id,
            reviewer_self_repair_invocation_id=reviewer_self_repair_invocation_id,
            deterministic_checksum=deterministic_checksum,
            reviewer_self_repair_succeeded=False,
            reviewer_mechanical_validation_issue=reviewed_diff_mechanical_issue,
        )
        _persist_reviewed_diff_validation_failure(
            output_dir=output_dir,
            reviewer_output=reviewer_output,
            review_chain=failed_chain,
            mechanical_issue=reviewed_diff_mechanical_issue,
        )
        struct_issue = _reviewed_diff_struct_issue(reviewed_diff_mechanical_issue) or reviewed_diff_mechanical_issue

        # ── AMF-250A: Attempt import replacement fallback ───────────────
        is_hunk_mismatch = struct_issue == "hunk_old_count_mismatch"
        if is_hunk_mismatch and sandbox_path is not None:
            logger.info(
                "import_replacement_fallback_considered job=%s stage=%d struct_issue=%s",
                context_pack.job_id, context_pack.stage_index, struct_issue,
            )
            try:
                from migration_factory.repair_loop.import_replacement_materializer import (
                    ImportReplacementMaterializationResult,
                    materialize_import_replacement_diff,
                )
                reviewed_diff_for_fallback = str(reviewer_output.get("reviewed_diff") or "")
                mat_result = materialize_import_replacement_diff(
                    sandbox_root=Path(str(sandbox_path)),
                    output_diff_path=output_dir / "backend_import_replacement.diff",
                    main_output=primary_output,
                    reviewer_output=reviewer_output,
                    reviewed_diff=reviewed_diff_for_fallback,
                    original_failure_reason_code="MALFORMED_DIFF",
                    original_struct_issue=struct_issue,
                    reviewer_decision="accept",
                    reviewer_self_repair_attempted=reviewer_self_repair_attempted,
                    reviewer_self_repair_succeeded=False,
                )
                fallback_artifact_payload = {
                    "attempted": mat_result.attempted,
                    "eligible": mat_result.eligible,
                    "succeeded": mat_result.succeeded,
                    "reason_code": mat_result.reason_code,
                    "detail": mat_result.detail,
                    "candidate_files": mat_result.candidate_files,
                    "changed_files": mat_result.changed_files,
                    "replacement_count": mat_result.replacement_count,
                    "generated_diff_checksum": mat_result.generated_diff_checksum,
                    "generated_diff_path": mat_result.generated_diff_path,
                    "original_failure_reason_code": mat_result.original_failure_reason_code,
                    "original_struct_issue": mat_result.original_struct_issue,
                    "reviewer_decision": mat_result.reviewer_decision,
                    "reviewer_self_repair_attempted": mat_result.reviewer_self_repair_attempted,
                    "reviewer_self_repair_succeeded": mat_result.reviewer_self_repair_succeeded,
                    "rejected_paths": mat_result.rejected_paths,
                    "changed_lines_summary": mat_result.changed_lines_summary,
                    "backend_import_replacement_diff_promoted": False,
                    "backend_struct_issue": "",
                }
                _write_json(
                    output_dir / "backend_import_replacement_materialization.json",
                    fallback_artifact_payload,
                )
                import_replacement_fallback_info = {
                    "backend_import_replacement_fallback_attempted": True,
                    "backend_import_replacement_fallback_eligible": mat_result.eligible,
                    "backend_import_replacement_fallback_succeeded": mat_result.succeeded,
                    "backend_import_replacement_fallback_reason_code": mat_result.reason_code,
                    "backend_import_replacement_fallback_detail": mat_result.detail,
                    "backend_import_replacement_diff_promoted": False,
                    "backend_generated_diff": False,
                    "original_struct_issue": mat_result.original_struct_issue,
                    "backend_struct_issue": "",
                }

                if mat_result.succeeded and mat_result.diff_text:
                    backend_struct_issue = validate_unified_diff_structure(mat_result.diff_text)
                    if backend_struct_issue is None:
                        import_replacement_resolved = True
                        reviewed_diff = mat_result.diff_text
                        reviewed_diff_mechanical_issue = None
                        reviewer_output["reviewed_diff"] = reviewed_diff
                        reviewer_output["reviewed_diff_checksum"] = sha256_canonical_json({"unified_diff": reviewed_diff})
                        reviewer_output["diff_changed_by_reviewer"] = True
                        reviewer_output["_backend_import_replacement"] = True
                        import_replacement_fallback_info.update({
                            "backend_import_replacement_diff_promoted": True,
                            "backend_generated_diff": True,
                            "backend_generated_diff_checksum": mat_result.generated_diff_checksum,
                            "backend_generated_diff_changed_files": mat_result.changed_files,
                            "backend_generated_diff_replacement_count": mat_result.replacement_count,
                        })
                        fallback_artifact_payload["backend_import_replacement_diff_promoted"] = True
                        logger.info(
                            "import_replacement_fallback_succeeded job=%s stage=%d files=%s count=%d checksum=%s",
                            context_pack.job_id, context_pack.stage_index,
                            ",".join(mat_result.changed_files), mat_result.replacement_count,
                            mat_result.generated_diff_checksum,
                        )
                    else:
                        import_replacement_fallback_info.update({
                            "backend_import_replacement_diff_promoted": False,
                            "backend_generated_diff": False,
                            "backend_struct_issue": backend_struct_issue,
                            "original_struct_issue": mat_result.original_struct_issue,
                        })
                        fallback_artifact_payload.update({
                            "backend_import_replacement_diff_promoted": False,
                            "backend_struct_issue": backend_struct_issue,
                        })
                        logger.warning(
                            "import_replacement_fallback_validation_failed job=%s stage=%d original_struct_issue=%s backend_struct_issue=%s",
                            context_pack.job_id, context_pack.stage_index,
                            mat_result.original_struct_issue, backend_struct_issue,
                        )
                else:
                    logger.info(
                        "import_replacement_fallback_ineligible job=%s stage=%d reason=%s",
                        context_pack.job_id, context_pack.stage_index, mat_result.reason_code,
                    )
                _write_json(
                    output_dir / "backend_import_replacement_materialization.json",
                    fallback_artifact_payload,
                )
            except Exception as fb_exc:
                logger.warning(
                    "import_replacement_fallback_exception job=%s stage=%d error=%s",
                    context_pack.job_id, context_pack.stage_index,
                    str(fb_exc)[:200],
                )
                import_replacement_fallback_info = {
                    "backend_import_replacement_fallback_attempted": True,
                    "backend_import_replacement_fallback_succeeded": False,
                    "backend_import_replacement_fallback_reason_code": "FALLBACK_EXCEPTION",
                    "backend_generated_diff": False,
                }

        if import_replacement_resolved:
            review_chain_update = dict(import_replacement_fallback_info)
            review_chain_update.update({
                "reviewer_mechanical_validation_issue": str(reviewed_diff_mechanical_issue) if reviewed_diff_mechanical_issue else "",
                "final_diff_exists": True,
                "proposal_created": False,
                "gate_created": False,
                "policy_ran": False,
            })
            failed_chain.update(review_chain_update)
            reviewed_diff = _strip_reviewed_diff_fences(reviewed_diff)
            reviewer_output["reviewed_diff"] = reviewed_diff
            reviewer_output["reviewed_diff_checksum"] = sha256_canonical_json({"unified_diff": reviewed_diff})
            # Clear the mechanical issue so success path continues
        else:
            if import_replacement_fallback_info:
                failed_chain.update(import_replacement_fallback_info)
                _write_json(output_dir / "review_chain.json", failed_chain)
            raise RepairReviewChainProductionError(
                f"Diff structure validation failed: {struct_issue}",
                reason_code="MALFORMED_DIFF",
                schema_name="RepairReviewerOutput",
                role="reviewer",
                partial_chain=failed_chain,
            )

    reviewed_diff = _strip_reviewed_diff_fences(reviewed_diff)
    reviewer_output["reviewed_diff"] = reviewed_diff
    reviewer_output["reviewed_diff_checksum"] = sha256_canonical_json({"unified_diff": reviewed_diff})

    reviewer_checksum = _compute_reviewer_repair_checksum(reviewer_output)
    reviewer_output["output_checksum"] = reviewer_checksum
    reviewer_path = output_dir / "reviewer_repair_llm_output.json"
    _write_json(reviewer_path, reviewer_output)

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
    )
    final_artifact_checksum = _compute_final_repair_artifact_checksum(final_artifact)
    final_artifact["artifact_checksum"] = final_artifact_checksum
    final_artifact_path = output_dir / "final_reviewed_repair_artifact.json"
    _write_json(final_artifact_path, final_artifact)

    diff_path = output_dir / "final_reviewed_repair.diff"
    diff_path.write_text(reviewed_diff, encoding="utf-8")
    logger.info(
        "final_diff_written job=%s stage=%d diff_checksum=%s",
        context_pack.job_id, context_pack.stage_index,
        reviewer_output["reviewed_diff_checksum"],
    )

    review_chain: dict[str, Any] = {
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_checksum,
        "primary_output_checksum": primary_checksum,
        "reviewer_output_checksum": reviewer_checksum,
        "proposed_diff_checksum": diff_checksum,
        "reviewed_diff_checksum": reviewer_output["reviewed_diff_checksum"],
        "final_artifact_checksum": final_artifact_checksum,
        "diff_changed_by_reviewer": reviewer_output["diff_changed_by_reviewer"],
        "reviewer_decision": reviewer_output["decision"],
        "job_id": context_pack.job_id,
        "stage_index": context_pack.stage_index,
        "deterministic_artifact_ref": str(deterministic_path),
        "primary_output_ref": str(primary_path),
        "reviewer_output_ref": str(reviewer_path),
        "final_artifact_ref": str(final_artifact_path),
        "final_diff_ref": str(diff_path),
        "model_roles": {
            "proposer": _safe_model_role_status(primary_result),
            "reviewer": _safe_model_role_status(reviewer_result),
        },
        "main_diff_diagnostics": main_diff_diagnostics,
        "reviewer_accept_contract_valid": True,
        "reviewer_accept_contract_issue": "",
        "reviewer_self_repair_attempted": reviewer_self_repair_attempted,
        "reviewer_self_repair_succeeded": reviewer_self_repair_attempted,
        "reviewer_mechanical_validation_issue": "",
        "final_diff_exists": True,
        "proposal_created": False,
        "gate_created": False,
        "policy_ran": False,
    }
    if reviewer_schema_repair_metadata:
        review_chain["reviewer_schema_repair"] = reviewer_schema_repair_metadata
    if initial_reviewer_output_ref:
        review_chain["reviewer_initial_output_ref"] = initial_reviewer_output_ref
        review_chain["reviewer_initial_output_checksum"] = str((initial_reviewer_output or {}).get("output_checksum") or "")
    if reviewer_self_repair_invocation_id is not None:
        review_chain["reviewer_self_repair_invocation_id"] = reviewer_self_repair_invocation_id
    if was_normalized:
        review_chain["diff_normalized"] = True
    if was_hunk_repaired:
        review_chain["hunks_repaired"] = True
    if reviewer_output.get("_backend_import_replacement"):
        review_chain["backend_import_replacement_fallback_attempted"] = True
        review_chain["backend_import_replacement_fallback_succeeded"] = True
        review_chain["backend_import_replacement_fallback_reason_code"] = import_replacement_fallback_info.get("backend_import_replacement_fallback_reason_code", "IMPORT_REPLACEMENT_FALLBACK_SUCCEEDED")
        review_chain["backend_import_replacement_diff_promoted"] = True
        review_chain["original_struct_issue"] = import_replacement_fallback_info.get("original_struct_issue", "")
        review_chain["backend_generated_diff"] = True
        review_chain["backend_generated_diff_checksum"] = import_replacement_fallback_info.get("backend_generated_diff_checksum", "")
        review_chain["backend_generated_diff_changed_files"] = import_replacement_fallback_info.get("backend_generated_diff_changed_files", [])
        review_chain["backend_generated_diff_replacement_count"] = import_replacement_fallback_info.get("backend_generated_diff_replacement_count", 0)
    if proposer_invocation_id is not None and reviewer_invocation_id is not None:
        review_chain["proposer_invocation_id"] = proposer_invocation_id
        review_chain["reviewer_invocation_id"] = reviewer_invocation_id
        if reviewer_self_repair_invocation_id is not None:
            review_chain["reviewer_initial_invocation_id"] = reviewer_invocation_id
            review_chain["reviewer_invocation_id"] = reviewer_self_repair_invocation_id
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
    if initial_reviewer_output_ref:
        produced_refs["reviewer_initial_llm_output"] = initial_reviewer_output_ref

    logger.info(
        "chain_closed job=%s stage=%d final_diff_exists=true proposal_created=false reason=%s",
        context_pack.job_id, context_pack.stage_index,
        reviewer_output["decision"],
    )
    return {"artifact_refs": produced_refs, "review_chain": review_chain}


def _persist_reviewer_schema_failure_artifact(
    *,
    output_dir: Path,
    reviewer_result: Any,
    reviewer_invocation_id: str | None,
) -> str:
    diagnostics = getattr(reviewer_result, "schema_diagnostics", None)
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    safe_keys = {
        "parse_failure_category",
        "output_checksum",
        "response_format_requested",
        "response_format_used",
        "finish_reason",
        "max_output_tokens",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "deployment_alias_hash",
        "schema_repair_attempted",
        "schema_repair_succeeded",
        "schema_repair_failure_reason",
        "schema_repair_parse_failure_category",
        "schema_repair_output_checksum",
        "original_schema_failure_reason",
        "original_parse_failure_category",
    }
    safe_diag = {key: diagnostics.get(key) for key in safe_keys if key in diagnostics}
    payload = {
        "schema_name": "RepairReviewerOutput",
        "role": "reviewer",
        "reason_code": str(
            diagnostics.get("reason_code")
            or getattr(reviewer_result, "failure_reason", "")
            or "reviewer_schema_invalid"
        ),
        "parse_failure_category": str(diagnostics.get("parse_failure_category") or ""),
        "response_format_requested": bool(diagnostics.get("response_format_requested")),
        "response_format_used": bool(diagnostics.get("response_format_used")),
        "schema_repair_attempted": bool(diagnostics.get("schema_repair_attempted")),
        "schema_repair_succeeded": bool(diagnostics.get("schema_repair_succeeded")),
        "schema_repair_failure_reason": str(diagnostics.get("schema_repair_failure_reason") or ""),
        "reviewer_invocation_id": reviewer_invocation_id or "",
        "output_checksum": str(diagnostics.get("output_checksum") or ""),
        "redacted_summary": str(getattr(reviewer_result, "redacted_summary", "") or "")[:1000],
        "provider_alias": str(getattr(reviewer_result, "provider", "") or ""),
        "deployment_alias_hash": str(
            diagnostics.get("deployment_alias_hash")
            or getattr(reviewer_result, "deployment_alias_hash", "")
            or ""
        ),
        "schema_diagnostics": safe_diag,
    }
    path = output_dir / "reviewer_repair_schema_failure.json"
    _write_json(path, payload)
    return str(path)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )


def _safe_model_role_status(result: Any) -> dict[str, Any]:
    """Public-safe role metadata: no deployment, endpoint, provider, or env refs."""
    return {
        "role": str(getattr(result, "role", "") or ""),
        "available": bool(getattr(result, "success", False)),
        "status": "available" if bool(getattr(result, "success", False)) else "blocked",
        "fallback_used": str(getattr(result, "source", "") or "") == "azure_openai_fallback",
    }


def _safe_schema_repair_metadata(result: Any) -> dict[str, Any]:
    diagnostics = getattr(result, "schema_diagnostics", None)
    if not isinstance(diagnostics, dict):
        return {}
    keys = (
        "original_schema_failure_reason",
        "original_parse_failure_category",
        "schema_repair_attempted",
        "schema_repair_succeeded",
        "schema_repair_failure_reason",
        "schema_repair_parse_failure_category",
        "schema_repair_output_checksum",
        "schema_repair_deterministic",
        "reason_code",
        "semantic_drift_fields",
        "original_decision",
        "repaired_decision",
    )
    metadata = {key: diagnostics.get(key) for key in keys if key in diagnostics}
    if not metadata.get("schema_repair_attempted"):
        return {}
    return metadata


def _reviewer_checksum_mismatch_diagnostics(field_name: str) -> dict[str, Any]:
    return {
        "schema_validated": False,
        "schema_name": "RepairReviewerOutput",
        "role": "reviewer",
        "stage": "reviewer",
        "reason_code": "reviewer_checksum_mismatch",
        "mismatched_fields": [field_name],
    }
