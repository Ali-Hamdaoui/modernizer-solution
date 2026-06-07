from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from typing import Any

from migration_factory.contracts.migration import load_ledger, save_ledger


APPROVED_PATCH_APPLY_GATE = "HUMAN_APPROVED_BEHAVIORAL_PATCH_APPLY"
_PATCH_FILE_RE = re.compile(r"^(---|\+\+\+) ([ab]/)?(.+)$")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_TEST_PATH_TOKENS = ("src/test/", "src/test\\", "src/integrationTest/", "src/integrationTest\\")


@dataclass(frozen=True)
class ApprovedPatchApplyResult:
    __test__ = False
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]
    warning: str


def apply_approved_behavioral_patch(
    *,
    run_dir: str | Path,
    patch_proposal_path: str | Path,
    approved_by: str,
    approval_comment: str,
    failed_unit_id: str,
    sandbox_project_path: str | Path,
    validation_command: list[str] | str | None = None,
    allow_production_source: bool = False,
    allow_pom_xml: bool = False,
    validation_env: dict[str, str] | None = None,
    subprocess_runner: Any = subprocess.run,
) -> ApprovedPatchApplyResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)
    sandbox_root = Path(sandbox_project_path).expanduser().resolve()
    patch_path = Path(patch_proposal_path).expanduser().resolve()

    payload = {
        "gate_id": APPROVED_PATCH_APPLY_GATE,
        "run_id": run_root.name,
        "status": "",
        "approved_by": approved_by,
        "approval_comment": approval_comment,
        "failed_unit_id": failed_unit_id,
        "patch_proposal_path": str(patch_path),
        "sandbox_project_path": str(sandbox_root),
        "safe_to_auto_apply": False,
        "human_review_required": True,
        "files_changed": [],
        "file_hashes": [],
        "rerun": {
            "attempted": False,
            "command": validation_command if isinstance(validation_command, list) else (validation_command or ""),
            "exit_code": None,
            "stdout_tail": [],
            "stderr_tail": [],
            "cwd": str(sandbox_root),
        },
        "error": "",
    }

    if not approved_by.strip() or not approval_comment.strip():
        payload["status"] = "rejected_missing_approval"
        payload["error"] = "Explicit approved_by and approval_comment are required."
        return _write_result(run_root, payload)
    if not patch_path.is_file():
        payload["status"] = "error_patch_missing"
        payload["error"] = f"Patch proposal not found: {patch_path}"
        return _write_result(run_root, payload)
    if not _is_within(patch_path, remediation_dir):
        payload["status"] = "rejected_patch_outside_remediation"
        payload["error"] = "Patch proposal must live under run_dir/remediation."
        return _write_result(run_root, payload)
    if not sandbox_root.is_dir():
        payload["status"] = "error_sandbox_missing"
        payload["error"] = f"Sandbox project path not found: {sandbox_root}"
        return _write_result(run_root, payload)

    parsed_files = _parse_unified_patch(patch_path)
    if not parsed_files:
        payload["status"] = "error_patch_parse"
        payload["error"] = "Patch proposal contains no supported unified diff entries."
        return _write_result(run_root, payload)

    planned_changes: list[dict[str, Any]] = []
    for file_patch in parsed_files:
        target_path = _resolve_patch_target(file_patch["target"], sandbox_root)
        if target_path is None:
            payload["status"] = "rejected_path_traversal"
            payload["error"] = f"Patch target is invalid or attempts path traversal: {file_patch['target']}"
            return _write_result(run_root, payload)
        if not _is_within(target_path, sandbox_root):
            payload["status"] = "rejected_patch_outside_sandbox"
            payload["error"] = f"Patch target is outside sandbox: {target_path}"
            return _write_result(run_root, payload)
        if not target_path.is_file():
            payload["status"] = "error_target_missing"
            payload["error"] = f"Patch target file not found in sandbox: {target_path}"
            return _write_result(run_root, payload)
        if _looks_like_pom(target_path) and not allow_pom_xml:
            payload["status"] = "rejected_pom_xml"
            payload["error"] = f"Patch touches pom.xml without explicit allow flag: {target_path}"
            return _write_result(run_root, payload)
        if _is_production_source(target_path, sandbox_root) and not allow_production_source:
            payload["status"] = "rejected_production_source"
            payload["error"] = f"Patch touches production source without explicit allow flag: {target_path}"
            return _write_result(run_root, payload)
        if not _is_test_source(target_path, sandbox_root) and not _looks_like_pom(target_path):
            payload["status"] = "rejected_non_test_scope"
            payload["error"] = f"Patch target is outside default test-only scope: {target_path}"
            return _write_result(run_root, payload)

        original_text = target_path.read_text(encoding="utf-8")
        try:
            updated_text = _apply_file_patch(original_text, file_patch)
            already_applied = False
        except PatchAlreadyApplied:
            updated_text = original_text
            already_applied = True
        except PatchApplyError as exc:
            if _is_patch_already_applied(original_text, file_patch):
                updated_text = original_text
                already_applied = True
            else:
                payload["status"] = "error_patch_apply"
                payload["error"] = str(exc)
                return _write_result(run_root, payload)

        planned_changes.append(
            {
                "path": target_path,
                "relative_path": str(target_path.resolve().relative_to(sandbox_root.resolve())),
                "before_hash": _hash_text(original_text),
                "after_hash": _hash_text(updated_text),
                "already_applied": already_applied,
                "updated_text": updated_text,
                "changed": original_text != updated_text,
            }
        )

    overall_already_applied = all(item["already_applied"] or not item["changed"] for item in planned_changes)
    for item in planned_changes:
        if item["changed"]:
            Path(item["path"]).write_text(str(item["updated_text"]), encoding="utf-8")

    payload["files_changed"] = [item["relative_path"] for item in planned_changes if item["changed"] or item["already_applied"]]
    payload["file_hashes"] = [
        {
            "file": item["relative_path"],
            "before_sha256": item["before_hash"],
            "after_sha256": item["after_hash"],
            "already_applied": item["already_applied"],
        }
        for item in planned_changes
    ]
    payload["status"] = "already_applied" if overall_already_applied else "applied"

    ledger_path = sandbox_root / ".migration" / "ledger.json"
    _record_in_ledger(
        ledger_path=ledger_path,
        patch_path=patch_path,
        approved_by=approved_by,
        approval_comment=approval_comment,
        failed_unit_id=failed_unit_id,
        files_changed=payload["files_changed"],
        status=payload["status"],
        rerun=payload["rerun"],
    )
    payload["ledger_path"] = str(ledger_path)

    if validation_command:
        rerun = _run_validation(
            command=validation_command,
            cwd=sandbox_root,
            env=validation_env,
            subprocess_runner=subprocess_runner,
        )
        payload["rerun"] = rerun
        _record_in_ledger(
            ledger_path=ledger_path,
            patch_path=patch_path,
            approved_by=approved_by,
            approval_comment=approval_comment,
            failed_unit_id=failed_unit_id,
            files_changed=payload["files_changed"],
            status=payload["status"],
            rerun=rerun,
        )

    return _write_result(run_root, payload)


class PatchApplyError(Exception):
    pass


class PatchAlreadyApplied(PatchApplyError):
    pass


def _parse_unified_patch(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    files: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue
        old_match = _PATCH_FILE_RE.match(lines[i])
        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            raise PatchApplyError("Malformed patch file header.")
        new_match = _PATCH_FILE_RE.match(lines[i + 1])
        if not old_match or not new_match:
            raise PatchApplyError("Malformed patch file paths.")
        file_entry = {"source": old_match.group(3), "target": new_match.group(3), "hunks": []}
        i += 2
        while i < len(lines) and not lines[i].startswith("--- "):
            if lines[i].startswith("@@ "):
                hunk_match = _HUNK_RE.match(lines[i])
                if not hunk_match:
                    raise PatchApplyError(f"Malformed hunk header: {lines[i]}")
                hunk = {
                    "old_start": int(hunk_match.group(1)),
                    "old_count": int(hunk_match.group(2) or "1"),
                    "new_start": int(hunk_match.group(3)),
                    "new_count": int(hunk_match.group(4) or "1"),
                    "lines": [],
                }
                i += 1
                while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                    if lines[i] and lines[i][0] in {" ", "+", "-"}:
                        hunk["lines"].append(lines[i])
                    elif lines[i] == "":
                        hunk["lines"].append(" ")
                    i += 1
                file_entry["hunks"].append(hunk)
                continue
            i += 1
        files.append(file_entry)
    return files


def _resolve_patch_target(target: str, sandbox_root: Path) -> Path | None:
    raw = str(target).replace("\\", "/")
    if raw.startswith("/"):
        raw = raw[1:]
    candidate = Path(raw)
    try:
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (sandbox_root / candidate).resolve()
    except OSError:
        return None
    return resolved


def _apply_file_patch(original_text: str, file_patch: dict[str, Any]) -> str:
    original_lines = original_text.splitlines()
    result: list[str] = []
    cursor = 0
    changed = False
    for hunk in list(file_patch.get("hunks") or []):
        old_start = max(int(hunk.get("old_start", 1)) - 1, 0)
        if old_start < cursor:
            raise PatchApplyError("Patch hunks overlap or are out of order.")
        result.extend(original_lines[cursor:old_start])
        cursor = old_start
        for line in list(hunk.get("lines") or []):
            marker = line[:1]
            content = line[1:]
            if marker == " ":
                if cursor >= len(original_lines) or original_lines[cursor] != content:
                    raise PatchApplyError(f"Context line mismatch while applying patch: {content}")
                result.append(content)
                cursor += 1
            elif marker == "-":
                if cursor < len(original_lines) and original_lines[cursor] == content:
                    cursor += 1
                    changed = True
                else:
                    raise PatchApplyError(f"Removal line mismatch while applying patch: {content}")
            elif marker == "+":
                result.append(content)
                changed = True
            else:
                raise PatchApplyError(f"Unsupported patch line marker: {line}")
    result.extend(original_lines[cursor:])
    updated_text = "\n".join(result)
    if original_text.endswith("\n") or changed:
        updated_text += "\n"
    if not changed and updated_text == original_text:
        raise PatchAlreadyApplied("Patch already appears to be applied.")
    return updated_text


def _is_patch_already_applied(original_text: str, file_patch: dict[str, Any]) -> bool:
    original_lines = original_text.splitlines()
    result: list[str] = []
    cursor = 0
    changed = False
    already_applied = True
    for hunk in list(file_patch.get("hunks") or []):
        old_start = max(int(hunk.get("old_start", 1)) - 1, 0)
        if old_start < cursor:
            raise PatchApplyError("Patch hunks overlap or are out of order.")
        result.extend(original_lines[cursor:old_start])
        cursor = old_start
        hunk_lines = list(hunk.get("lines") or [])
        index = 0
        while index < len(hunk_lines):
            line = hunk_lines[index]
            marker = line[:1]
            content = line[1:]
            if marker == " ":
                if cursor >= len(original_lines) or original_lines[cursor] != content:
                    raise PatchApplyError(f"Context line mismatch while applying patch: {content}")
                result.append(content)
                cursor += 1
            elif marker == "-":
                if cursor < len(original_lines) and original_lines[cursor] == content:
                    cursor += 1
                    changed = True
                    already_applied = False
                elif (
                    index + 1 < len(hunk_lines)
                    and hunk_lines[index + 1].startswith("+")
                    and cursor < len(original_lines)
                    and original_lines[cursor] == hunk_lines[index + 1][1:]
                ):
                    pass
                else:
                    raise PatchApplyError(f"Removal line mismatch while applying patch: {content}")
            elif marker == "+":
                if cursor < len(original_lines) and original_lines[cursor] == content:
                    result.append(content)
                    cursor += 1
                else:
                    result.append(content)
                    changed = True
                    already_applied = False
            else:
                raise PatchApplyError(f"Unsupported patch line marker: {line}")
            index += 1
    result.extend(original_lines[cursor:])
    updated_text = "\n".join(result)
    if original_text.endswith("\n") or changed:
        updated_text += "\n"
    return not changed and updated_text == original_text and already_applied


def _run_validation(
    *,
    command: list[str] | str,
    cwd: Path,
    env: dict[str, str] | None,
    subprocess_runner: Any,
) -> dict[str, Any]:
    completed = subprocess_runner(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
        shell=isinstance(command, str),
    )
    return {
        "attempted": True,
        "command": command,
        "exit_code": int(getattr(completed, "returncode", -1)),
        "stdout_tail": _tail_lines(str(getattr(completed, "stdout", "") or "")),
        "stderr_tail": _tail_lines(str(getattr(completed, "stderr", "") or "")),
        "cwd": str(cwd),
    }


def _record_in_ledger(
    *,
    ledger_path: Path,
    patch_path: Path,
    approved_by: str,
    approval_comment: str,
    failed_unit_id: str,
    files_changed: list[str],
    status: str,
    rerun: dict[str, Any],
) -> None:
    if not ledger_path.is_file():
        return
    ledger = load_ledger(ledger_path)
    items = ledger.setdefault("approved_behavioral_patches", [])
    if not isinstance(items, list):
        items = []
        ledger["approved_behavioral_patches"] = items
    entry = {
        "patch_proposal_path": str(patch_path),
        "approved_by": approved_by,
        "approval_comment": approval_comment,
        "failed_unit_id": failed_unit_id,
        "files_changed": list(files_changed),
        "status": status,
        "rerun": dict(rerun),
    }
    items.append(entry)
    unit = ledger.setdefault("units", {}).setdefault(failed_unit_id, {})
    unit_items = unit.setdefault("approved_behavioral_patches", [])
    if not isinstance(unit_items, list):
        unit_items = []
        unit["approved_behavioral_patches"] = unit_items
    unit_items.append(entry)
    ledger["last_approved_behavioral_patch"] = entry
    save_ledger(ledger_path, ledger)


def _write_result(run_root: Path, payload: dict[str, Any]) -> ApprovedPatchApplyResult:
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)
    report_path = remediation_dir / "approved_patch_apply_result.json"
    summary_path = remediation_dir / "approved_patch_apply_summary.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path)
    warning = ""
    if str(payload.get("status") or "").startswith("rejected") or str(payload.get("status") or "").startswith("error"):
        warning = "Approved behavioral patch apply did not complete successfully."
    return ApprovedPatchApplyResult(report_path=report_path, summary_path=summary_path, payload=payload, warning=warning)


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Approved Patch Apply",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit_id', '')}",
        f"- Status: {payload.get('status', '')}",
        f"- Approved By: {payload.get('approved_by', '')}",
        f"- Files Changed: {len(list(payload.get('files_changed') or []))}",
    ]
    rerun = dict(payload.get("rerun") or {})
    if rerun.get("attempted"):
        lines.extend(
            [
                "",
                "## Rerun",
                "",
                f"- Exit Code: {rerun.get('exit_code')}",
                f"- Command: {rerun.get('command')}",
            ]
        )
    if payload.get("error"):
        lines.extend(["", "## Error", "", f"- {payload.get('error', '')}"])
    return "\n".join(lines) + "\n"


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path) -> None:
    refs = {
        "approved_patch_apply_result": str(report_path),
        "approved_patch_apply_summary": str(summary_path),
    }
    for candidate in (
        run_root / "orchestration" / "orchestration_summary.json",
        run_root / "final" / "migration_report.json",
    ):
        payload = _read_optional_json(candidate)
        if not isinstance(payload, dict):
            continue
        artifact_refs = dict(payload.get("artifact_refs", {}) or {})
        payload["artifact_refs"] = {**artifact_refs, **refs}
        candidate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    final_summary = run_root / "final" / "migration_summary.md"
    if final_summary.is_file():
        text = final_summary.read_text(encoding="utf-8")
        line = f"- Approved Patch Apply: {report_path}"
        if line not in text:
            text = text.rstrip() + f"\n{line}\n"
            final_summary.write_text(text, encoding="utf-8")


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_test_source(path: Path, sandbox_root: Path) -> bool:
    rel = str(path.resolve().relative_to(sandbox_root.resolve())).replace("\\", "/")
    return any(token in rel for token in _TEST_PATH_TOKENS)


def _is_production_source(path: Path, sandbox_root: Path) -> bool:
    rel = str(path.resolve().relative_to(sandbox_root.resolve())).replace("\\", "/")
    return "/src/main/" in f"/{rel}"


def _looks_like_pom(path: Path) -> bool:
    return path.name.lower() == "pom.xml"


def _tail_lines(text: str, *, max_lines: int = 40) -> list[str]:
    return [line for line in text.splitlines()[-max_lines:]]


def _hash_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()
