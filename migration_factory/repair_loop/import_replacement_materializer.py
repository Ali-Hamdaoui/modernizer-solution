"""AMF-250A: Deterministic backend import replacement materialization."""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_REPLACEMENTS: dict[str, str] = {
    "import tools.jackson.databind.JsonNode;": "import com.fasterxml.jackson.databind.JsonNode;",
    "import tools.jackson.databind.annotation.JsonDeserialize;": "import com.fasterxml.jackson.databind.annotation.JsonDeserialize;",
    "import tools.jackson.databind.annotation.JsonSerialize;": "import com.fasterxml.jackson.databind.annotation.JsonSerialize;",
}

_ELIGIBILITY_PATTERNS: list[re.Pattern] = [
    re.compile(r"tools\.jackson", re.IGNORECASE),
    re.compile(r"com\.fasterxml\.jackson", re.IGNORECASE),
    re.compile(r"replace.*invalid.*tools\.jackson.*import", re.IGNORECASE),
    re.compile(r"import.*from.*non-existent.*package.*tools\.jackson", re.IGNORECASE),
    re.compile(r"missing.*tools\.jackson.*package", re.IGNORECASE),
]

_IMPORT_TOOLS_JACKSON = re.compile(r"^\s*import\s+tools\.jackson\.")


@dataclass(frozen=True)
class ImportReplacementMaterializationResult:
    attempted: bool
    eligible: bool
    succeeded: bool
    reason_code: str
    detail: str
    candidate_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    replacement_count: int = 0
    generated_diff_path: str = ""
    generated_diff_checksum: str = ""
    diff_text: str = ""
    rejected_paths: list[dict[str, Any]] = field(default_factory=list)
    changed_lines_summary: list[dict[str, Any]] = field(default_factory=list)
    original_failure_reason_code: str = ""
    original_struct_issue: str = ""
    reviewer_decision: str = ""
    reviewer_self_repair_attempted: bool = False
    reviewer_self_repair_succeeded: bool = False


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_eligible(main_output: dict[str, Any] | None = None,
                 reviewer_output: dict[str, Any] | None = None) -> bool:
    texts: list[str] = []
    if main_output:
        texts.append(str(main_output.get("root_cause") or ""))
        texts.append(str(main_output.get("fix_strategy") or ""))
        texts.append(str(main_output.get("rationale") or ""))
    if reviewer_output:
        texts.append(str(reviewer_output.get("review_summary") or ""))
        texts.append(json.dumps(reviewer_output.get("main_patch_findings", [])))
        texts.append(json.dumps(reviewer_output.get("notes", [])))
    combined = " ".join(texts)
    return any(p.search(combined) for p in _ELIGIBILITY_PATTERNS)


def _collect_candidates(
    main_output: dict[str, Any] | None = None,
    reviewed_diff: str = "",
    reviewed_diff_rejected_path: str | None = None,
    context_pack: Any = None,
    deterministic_artifact: dict[str, Any] | None = None,
) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []

    def _add(path: str) -> None:
        norm = path.replace("\\", "/").strip()
        if not norm or norm in seen:
            return
        if not norm.endswith(".java"):
            return
        if norm.startswith("/") or ".." in norm.split("/"):
            return
        if re.match(r"^[a-zA-Z]:", norm):
            return
        seen.add(norm)
        candidates.append(norm)

    if main_output:
        for p in main_output.get("changed_files", []):
            if isinstance(p, str):
                _add(p)

    def _from_diff(text: str) -> None:
        for line in text.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                for r in parts[2:4]:
                    c = r.strip()
                    if c.startswith("a/"): c = c[2:]
                    elif c.startswith("b/"): c = c[2:]
                    _add(c)
            elif line.startswith("--- ") or line.startswith("+++ "):
                r = line[4:].split("\t", 1)[0].strip().strip('"')
                if r.startswith("a/") or r.startswith("b/"):
                    r = r[2:]
                _add(r)

    _from_diff(reviewed_diff)

    if reviewed_diff_rejected_path:
        try:
            _from_diff(Path(reviewed_diff_rejected_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    if context_pack is not None:
        try:
            for ctx in context_pack.source_contexts:
                src = getattr(ctx, "path", None) or getattr(ctx, "source_path", None)
                if isinstance(src, str):
                    _add(src)
        except (AttributeError, TypeError):
            pass

    if deterministic_artifact:
        for p in deterministic_artifact.get("changed_files", ()):
            if isinstance(p, str):
                _add(p)

    return candidates


def _safe_path(candidate: str, sandbox: Path) -> tuple[bool, str]:
    if not candidate.endswith(".java"):
        return False, "not_java"
    normalized = candidate.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", normalized):
        return False, "absolute_path"
    if ".." in PurePosixPath(normalized).parts:
        return False, "path_traversal"
    try:
        resolved = (sandbox / PurePosixPath(normalized)).resolve()
        if not resolved.is_relative_to(sandbox.resolve()):
            return False, "escapes_sandbox"
    except (ValueError, OSError):
        return False, "path_error"
    return True, ""


def materialize_import_replacement_diff(
    *,
    sandbox_root: Path,
    candidate_paths: Sequence[str] | None = None,
    output_diff_path: Path,
    allowed_replacements: Mapping[str, str] | None = None,
    main_output: dict[str, Any] | None = None,
    reviewer_output: dict[str, Any] | None = None,
    reviewed_diff: str = "",
    reviewed_diff_rejected_path: str | None = None,
    context_pack: Any = None,
    deterministic_artifact: dict[str, Any] | None = None,
    original_failure_reason_code: str = "",
    original_struct_issue: str = "",
    reviewer_decision: str = "",
    reviewer_self_repair_attempted: bool = False,
    reviewer_self_repair_succeeded: bool = False,
) -> ImportReplacementMaterializationResult:
    eligible = _is_eligible(main_output=main_output, reviewer_output=reviewer_output)
    if not eligible:
        return ImportReplacementMaterializationResult(
            attempted=True, eligible=False, succeeded=False,
            reason_code="IMPORT_REPLACEMENT_FALLBACK_INELIGIBLE",
            detail="output does not indicate tools.jackson import fix strategy",
            original_failure_reason_code=original_failure_reason_code,
            original_struct_issue=original_struct_issue,
            reviewer_decision=reviewer_decision,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            reviewer_self_repair_succeeded=reviewer_self_repair_succeeded,
        )

    if candidate_paths:
        resolved = list(candidate_paths)
    else:
        resolved = _collect_candidates(
            main_output=main_output, reviewed_diff=reviewed_diff,
            reviewed_diff_rejected_path=reviewed_diff_rejected_path,
            context_pack=context_pack, deterministic_artifact=deterministic_artifact,
        )

    if not resolved:
        return ImportReplacementMaterializationResult(
            attempted=True, eligible=True, succeeded=False,
            reason_code="IMPORT_REPLACEMENT_NO_CANDIDATE_FILES",
            detail="no candidate files from chain evidence",
            original_failure_reason_code=original_failure_reason_code,
            original_struct_issue=original_struct_issue,
            reviewer_decision=reviewer_decision,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            reviewer_self_repair_succeeded=reviewer_self_repair_succeeded,
        )

    replacements = dict(allowed_replacements or _DEFAULT_ALLOWED_REPLACEMENTS)
    sandbox = Path(sandbox_root).resolve()
    valid: list[str] = []
    rejected: list[dict[str, Any]] = []

    for c in resolved:
        ok, reason = _safe_path(c, sandbox)
        if ok:
            valid.append(c)
        else:
            rejected.append({"path": c, "reason_code": "IMPORT_REPLACEMENT_PATH_REJECTED", "detail": reason})

    if not valid:
        return ImportReplacementMaterializationResult(
            attempted=True, eligible=True, succeeded=False,
            reason_code="IMPORT_REPLACEMENT_NO_CANDIDATE_FILES",
            detail="no valid Java files after path safety checks",
            candidate_files=list(resolved), rejected_paths=rejected,
            original_failure_reason_code=original_failure_reason_code,
            original_struct_issue=original_struct_issue,
            reviewer_decision=reviewer_decision,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            reviewer_self_repair_succeeded=reviewer_self_repair_succeeded,
        )

    changed_files: list[str] = []
    replacement_count = 0
    before_map: dict[str, list[str]] = {}
    after_map: dict[str, list[str]] = {}
    line_summaries: list[dict[str, Any]] = []

    for candidate in valid:
        fpath = (sandbox / PurePosixPath(candidate)).resolve()
        if not fpath.is_file():
            rejected.append({"path": candidate, "reason_code": "IMPORT_REPLACEMENT_FILE_MISSING", "detail": "file not found"})
            continue
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines(keepends=True)
        except (OSError, ValueError) as exc:
            rejected.append({"path": candidate, "reason_code": "IMPORT_REPLACEMENT_FILE_MISSING", "detail": str(exc)})
            continue

        new_lines: list[str] = []
        file_changed = False
        for ln in lines:
            stripped = ln.strip()
            m = _IMPORT_TOOLS_JACKSON.match(stripped)
            if m:
                ci = stripped.rstrip(";").strip() + ";"
                if ci in replacements:
                    ri = replacements[ci]
                    indent = ln[:len(ln) - len(ln.lstrip())]
                    new_lines.append(indent + ri + "\n")
                    replacement_count += 1
                    file_changed = True
                    continue
            new_lines.append(ln)

        if file_changed:
            changed_files.append(candidate)
            before_map[candidate] = lines
            after_map[candidate] = new_lines

    if not changed_files:
        return ImportReplacementMaterializationResult(
            attempted=True, eligible=True, succeeded=False,
            reason_code="IMPORT_REPLACEMENT_NO_EXACT_IMPORTS",
            detail="no exact tools.jackson import lines found",
            candidate_files=list(resolved), changed_files=[], rejected_paths=rejected,
            original_failure_reason_code=original_failure_reason_code,
            original_struct_issue=original_struct_issue,
            reviewer_decision=reviewer_decision,
            reviewer_self_repair_attempted=reviewer_self_repair_attempted,
            reviewer_self_repair_succeeded=reviewer_self_repair_succeeded,
        )

    diff_parts: list[str] = []
    for path in changed_files:
        before = before_map[path]
        after = after_map[path]
        before_no_eol = [l.rstrip("\n\r") for l in before]
        after_no_eol = [l.rstrip("\n\r") for l in after]
        udiff = list(difflib.unified_diff(
            before_no_eol, after_no_eol,
            fromfile=f"a/{path}", tofile=f"b/{path}", n=3,
            lineterm="",
        ))
        if not udiff:
            continue
        diff_parts.append(f"diff --git a/{path} b/{path}")
        diff_parts.extend(udiff)

        for idx, l in enumerate(before_no_eol):
            if _IMPORT_TOOLS_JACKSON.match(l):
                ci = l.rstrip(";").strip() + ";"
                if ci in replacements:
                    line_summaries.append({
                        "path": path, "old_line": idx + 1, "new_line": idx + 1,
                        "old_text": l.strip(), "new_text": replacements[ci],
                    })

    diff_text = "\n".join(diff_parts)
    diff_checksum = _sha256(diff_text)

    output_diff_path.parent.mkdir(parents=True, exist_ok=True)
    output_diff_path.write_text(diff_text + "\n", encoding="utf-8")

    return ImportReplacementMaterializationResult(
        attempted=True, eligible=True, succeeded=True,
        reason_code="IMPORT_REPLACEMENT_DIFF_GENERATED",
        detail=f"generated diff: {replacement_count} replacements in {len(changed_files)} files",
        candidate_files=list(resolved),
        changed_files=changed_files,
        replacement_count=replacement_count,
        generated_diff_path=str(output_diff_path),
        generated_diff_checksum=diff_checksum,
        diff_text=diff_text,
        rejected_paths=rejected,
        changed_lines_summary=line_summaries,
        original_failure_reason_code=original_failure_reason_code,
        original_struct_issue=original_struct_issue,
        reviewer_decision=reviewer_decision,
        reviewer_self_repair_attempted=reviewer_self_repair_attempted,
        reviewer_self_repair_succeeded=reviewer_self_repair_succeeded,
    )
