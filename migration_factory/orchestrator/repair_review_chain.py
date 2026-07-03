"""F5: Repair review-chain producer — extends the F2 review-chain pattern for repair.

Deterministic repair artifact -> Primary Repair LLM (PROPOSER) -> Reviewer Repair LLM (REVIEWER)
-> Final reviewed repair diff artifact.

Core rule: A model reviews another model for repair. Reviewer is mandatory.
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
    ) -> None:
        super().__init__(message)
        self.schema_diagnostics = schema_diagnostics
        self.reason_code = reason_code or ""
        self.schema_name = schema_name or ""
        self.role = role or ""


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
        "- For 'cannot find symbol: class JsonNode' in a Java source file that references JsonNode without import, "
        "prefer adding 'import com.fasterxml.jackson.databind.JsonNode;' to the source file when dependency evidence "
        "already shows Jackson is available.\n"
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
    primary_output: dict[str, Any],
    deterministic_checksum: str,
    context_checksum: str,
    primary_checksum: str,
    diff_checksum: str,
) -> str:
    return (
        "You are a repair reviewer. Validate the repair proposal below against the "
        "exact checksums, context, and policy constraints.\n\n"
        "Output only valid JSON. No markdown. No code fences. No commentary.\n\n"
        "Match the RepairReviewerOutput schema exactly.\n\n"
        "Required fields:\n"
        "  decision: \"accept\" | \"reject\" | \"needs_revision\"\n"
        "  notes: list of strings\n"
        "  risks: list of strings\n"
        "  policy_concerns: list of strings\n"
        "  changed_files_verified: boolean\n"
        "  diff_parseable: boolean\n"
        f"  reviewed_context_checksum: \"{context_checksum}\"\n"
        f"  reviewed_primary_output_checksum: \"{primary_checksum}\"\n"
        f"  reviewed_diff_checksum: \"{diff_checksum}\"\n\n"
        "If decision is \"reject\", include reason_for_rejection (string).\n"
        "If decision is \"needs_revision\", include revision_request (string).\n\n"
        "Review the normalized proposed diff, not only the Main summary. Bind your "
        "decision to the exact top-level checksum fields.\n\n"
        "Valid JSON example:\n"
        "{\n"
        '  "decision": "accept",\n'
        '  "notes": [],\n'
        '  "risks": [],\n'
        '  "policy_concerns": [],\n'
        '  "changed_files_verified": true,\n'
        '  "diff_parseable": true,\n'
        f'  "reviewed_context_checksum": "{context_checksum}",\n'
        f'  "reviewed_primary_output_checksum": "{primary_checksum}",\n'
        f'  "reviewed_diff_checksum": "{diff_checksum}"\n'
        "}\n\n"
        "CONSTRAINTS:\n"
        "- Accept only if the diff is valid unified diff format and addresses "
        "the exact failure evidence.\n"
        "- Reject any unsafe diff (absolute paths, security config changes, "
        "execution instructions, test disabling, deleted production code).\n"
        "- Reject if the diff scope exceeds the declared changed files.\n"
        "- Bind your decision to the exact checksums provided.\n"
        "- changed_files_verified must be true if all declared changed files are "
        "present in the diff.\n"
        "- diff_parseable must be false if the diff cannot be parsed as a valid "
        "unified diff.\n\n"
        f"Deterministic repair artifact checksum: {deterministic_checksum}\n"
        f"Context pack checksum: {context_checksum}\n"
        f"Primary output checksum: {primary_checksum}\n"
        f"Normalized proposed diff checksum: {diff_checksum}\n"
        f"Primary output:\n{json.dumps(primary_output, sort_keys=True)}"
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
    diff_checksum: str,
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
    if decision not in {"accept", "revise", "reject", "needs_revision"}:
        raise RepairReviewChainProductionError(
            f"invalid reviewer decision {decision!r}; must be accept/reject/needs_revision",
            reason_code="reviewer_invalid_decision",
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )
    if decision == "revise":
        decision = "needs_revision"

    required_checksum_fields = {
        "reviewed_context_checksum",
        "reviewed_primary_output_checksum",
        "reviewed_diff_checksum",
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
    reviewed_diff_checksum = str(parsed["reviewed_diff_checksum"]).strip()
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
    if reviewed_diff_checksum != diff_checksum:
        raise RepairReviewChainProductionError(
            "reviewer diff checksum binding did not match the reviewed artifacts",
            reason_code="reviewer_checksum_mismatch",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_diff_checksum"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    changed_files_verified = bool(parsed.get("changed_files_verified", False))
    diff_parseable = bool(parsed.get("diff_parseable", False))
    if decision == "accept" and not diff_parseable:
        raise RepairReviewChainProductionError(
            "reviewer accepted a diff it marked unparseable",
            reason_code="reviewer_rejected_diff",
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )
    if decision == "accept" and not changed_files_verified:
        raise RepairReviewChainProductionError(
            "reviewer accepted without verifying changed files",
            reason_code="reviewer_policy_reject",
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    return {
        "decision": decision,
        "notes": parsed.get("notes") if isinstance(parsed.get("notes"), list) else [str(parsed.get("reasoning") or "No notes.")],
        "confidence": float(parsed.get("confidence", 0.8)),
        "risks": parsed.get("risks") if isinstance(parsed.get("risks"), list) else [],
        "policy_concerns": parsed.get("policy_concerns") if isinstance(parsed.get("policy_concerns"), list) else [],
        "changed_files_verified": changed_files_verified,
        "diff_parseable": diff_parseable,
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
        "notes": list(output.get("notes", [])),
        "confidence": float(output.get("confidence", 0.0)),
        "risks": list(output.get("risks", [])),
        "policy_concerns": list(output.get("policy_concerns", [])),
        "changed_files_verified": bool(output.get("changed_files_verified", False)),
        "diff_parseable": bool(output.get("diff_parseable", False)),
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
        "changed_files": list(primary_output.get("changed_files", [])),
        "base_repo_state_checksum": context_pack.base_repo_state_checksum,
        "root_cause": str(primary_output.get("root_cause", "")),
        "fix_strategy": str(primary_output.get("fix_strategy", "")),
        "risk": str(primary_output.get("risk", "")),
        "confidence": float(primary_output.get("confidence", 0.0)),
        "reviewer_decision": str(reviewer_output.get("decision", "")),
        "reviewer_notes": list(reviewer_output.get("notes", [])),
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

    if not reviewer_result.success:
        raise RepairReviewChainProductionError(
            f"reviewer repair model failed closed: {reviewer_result.failure_reason or reviewer_result.model_status}",
            schema_diagnostics=getattr(reviewer_result, "schema_diagnostics", None),
            reason_code=str(reviewer_result.failure_reason or "reviewer_model_failed"),
            schema_name="RepairReviewerOutput",
            role="reviewer",
        )

    reviewer_output = _coerce_reviewer_repair_output(
        reviewer_result.content,
        deterministic_checksum,
        context_checksum,
        primary_checksum,
        diff_checksum,
    )

    if reviewer_output["reviewed_context_checksum"] != context_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer context checksum mismatch: expected {context_checksum}, got {reviewer_output['reviewed_context_checksum']}",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_context_checksum"),
            reason_code="reviewer_checksum_mismatch",
        )
    if reviewer_output["reviewed_primary_output_checksum"] != primary_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer primary checksum mismatch: expected {primary_checksum}, got {reviewer_output['reviewed_primary_output_checksum']}",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_primary_output_checksum"),
            reason_code="reviewer_checksum_mismatch",
        )
    if reviewer_output["reviewed_diff_checksum"] != diff_checksum:
        raise RepairReviewChainProductionError(
            f"reviewer diff checksum mismatch: expected {diff_checksum}, got {reviewer_output['reviewed_diff_checksum']}",
            schema_diagnostics=_reviewer_checksum_mismatch_diagnostics("reviewed_diff_checksum"),
            reason_code="reviewer_checksum_mismatch",
        )

    if not reviewer_output["diff_parseable"]:
        raise RepairReviewChainProductionError(
            "reviewer accepted an unparseable diff; refusing to materialize reviewed repair",
            reason_code="reviewer_rejected_diff",
        )
    if not reviewer_output["changed_files_verified"]:
        raise RepairReviewChainProductionError(
            "reviewer accepted without changed files verification; refusing to materialize reviewed repair",
            reason_code="reviewer_policy_reject",
        )

    if reviewer_output["decision"] != "accept":
        raise RepairReviewChainProductionError(
            f"reviewer decision failed closed: {reviewer_output['decision']}",
            reason_code="reviewer_rejected_diff",
        )

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
    diff_path.write_text(proposed_diff, encoding="utf-8")

    review_chain: dict[str, Any] = {
        "deterministic_artifact_checksum": deterministic_checksum,
        "context_pack_checksum": context_checksum,
        "primary_output_checksum": primary_checksum,
        "reviewer_output_checksum": reviewer_checksum,
        "proposed_diff_checksum": diff_checksum,
        "final_artifact_checksum": final_artifact_checksum,
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
    }
    if was_normalized:
        review_chain["diff_normalized"] = True
    if was_hunk_repaired:
        review_chain["hunks_repaired"] = True
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
    """Public-safe role metadata: no deployment, endpoint, provider, or env refs."""
    return {
        "role": str(getattr(result, "role", "") or ""),
        "available": bool(getattr(result, "success", False)),
        "status": "available" if bool(getattr(result, "success", False)) else "blocked",
        "fallback_used": str(getattr(result, "source", "") or "") == "azure_openai_fallback",
    }


def _reviewer_checksum_mismatch_diagnostics(field_name: str) -> dict[str, Any]:
    return {
        "schema_validated": False,
        "schema_name": "RepairReviewerOutput",
        "role": "reviewer",
        "stage": "reviewer",
        "reason_code": "reviewer_checksum_mismatch",
        "mismatched_fields": [field_name],
    }
