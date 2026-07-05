"""Backend-owned post-repair verification and recursive diagnosis."""

from __future__ import annotations

import json
import os
import subprocess
import time
import re
from pathlib import Path
from typing import Any, Callable
import shutil

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.application.v2_stage_failure_classifier import classify_stage_failure
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text
from migration_factory.maven import resolve_java_executable, resolve_maven_executable


CommandRunner = Callable[[list[str], Path], dict[str, Any]]

POST_REPAIR_COMMANDS: tuple[list[str], ...] = (
    ["__MAVEN__", "-DskipTests", "clean", "compile"],
    ["__MAVEN__", "test"],
)
ENVIRONMENT_COMMANDS: tuple[list[str], ...] = (
    ["__JAVA__", "-version"],
    ["__MAVEN__", "-version"],
)
DEPENDENCY_TREE_COMMAND: list[str] = ["__MAVEN__", "dependency:tree", "-DoutputType=text"]
LOG_EXCERPT_PATTERNS: tuple[str, ...] = (
    "NoClassDefFoundError",
    "ClassNotFoundException",
    "ToStringSerializerBase",
    "MessageUtilsTest",
    "MessageUtils.createObjectMapper",
    "BUILD FAILURE",
    "COMPILATION ERROR",
    "Tests run:",
    "Failures:",
    "Errors:",
    "omitted for conflict",
    "jackson-databind",
    "jackson-core",
    "jackson-annotations",
    "new Sort",
    "Sort.by",
    "PowerMock",
    "Mockito",
    "initMocks",
    "MockBean",
    "Jacoco",
    "lombok",
    "jackson-dataformat-csv",
    "jackson-datatype-jsr310",
    "version managed from",
    "2.9.6",
    "2.10.0",
    "2.13.5",
    "2.8.11",
)


def run_post_repair_verification(
    *,
    job_id: str,
    stage_index: int,
    repair_candidate: dict[str, Any],
    approval: dict[str, Any],
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    sandbox = _resolve_sandbox_root(repair_candidate)
    proof_dir = sandbox / ".migration" / "post-repair-verification" / str(repair_candidate.get("repair_candidate_id") or "repair")
    proof_dir.mkdir(parents=True, exist_ok=True)
    pom_path = (sandbox / "pom.xml").resolve()
    if not pom_path.is_file():
        proof_path = proof_dir / "post-repair-verification.json"
        proof = {
            "job_id": job_id,
            "stage_index": stage_index,
            "repair_candidate_id": repair_candidate.get("repair_candidate_id", ""),
            "approval_id": approval.get("approval_id", ""),
            "post_repair_verification_status": "skipped",
            "stage_recovery_status": "unknown",
            "commands": [],
            "evidence_pack_checksum": "",
            "classification": {},
            "proof_created_at": utc_now_text(),
            "downstream_start_allowed": False,
            "reason": "pom_missing",
        }
        proof["proof_checksum"] = f"sha256:{sha256_canonical_json(proof)}"
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
        return {
            "post_repair_verification_status": "skipped",
            "stage_recovery_status": "unknown",
            "commands": [],
            "evidence_pack": {},
            "classification": {},
            "proof_artifact": redact_absolute_paths(str(proof_path)),
            "post_repair_proof_artifact": redact_absolute_paths(str(proof_path)),
            "downstream_start_allowed": False,
            "started_at": "",
            "completed_at": "",
            "sandbox_path": redact_absolute_paths(str(sandbox)),
            "working_directory": redact_absolute_paths(str(sandbox)),
            "next_repair_candidate": None,
            "_next_repair_candidate": None,
        }

    runner = command_runner or _run_command
    resolved_toolchain = _resolve_backend_toolchain()
    toolchain_warnings: list[str] = []
    java_environment_command = _render_command(ENVIRONMENT_COMMANDS[0], resolved_toolchain)
    java_environment_record = _normalize_command_result(java_environment_command, sandbox, runner(java_environment_command, sandbox))
    maven_environment_command = _render_command(ENVIRONMENT_COMMANDS[1], resolved_toolchain)
    if resolved_toolchain["maven_available"]:
        maven_environment_record = _normalize_command_result(maven_environment_command, sandbox, runner(maven_environment_command, sandbox))
    else:
        maven_environment_record = {
            "command": maven_environment_command,
            "working_directory": str(sandbox),
            "stdout": "",
            "stderr": "maven_unavailable",
            "exit_code": 1,
            "started_at": java_environment_record["started_at"],
            "completed_at": java_environment_record["completed_at"],
            "duration_ms": 0,
        }
    environment_records = [java_environment_record, maven_environment_record]
    environment_summary = _environment_summary(environment_records)
    java_warning = _java_toolchain_warning(environment_summary, repair_candidate)
    if java_warning:
        toolchain_warnings.append(java_warning)
    if not resolved_toolchain["maven_available"]:
        proof_path = _write_toolchain_failure_proof(
            proof_dir=proof_dir,
            job_id=job_id,
            stage_index=stage_index,
            repair_candidate=repair_candidate,
            approval=approval,
            sandbox=sandbox,
            environment_summary=environment_summary,
            toolchain_warnings=toolchain_warnings,
            resolved_toolchain=resolved_toolchain,
        )
        classification = {
            "job_id": job_id,
            "stage_index": stage_index,
            "failure_type": "TOOLCHAIN_UNAVAILABLE",
            "classification_status": "toolchain_failure",
            "repair_blocked_reason": "post_repair_maven_unavailable",
            "missing_tool": "maven",
            "toolchain_warnings": toolchain_warnings,
            "repair_enabled": False,
        }
        return {
            "post_repair_verification_status": "failed",
            "stage_recovery_status": "still_failed",
            "post_repair_failure_kind": "toolchain_unavailable",
            "missing_tool": "maven",
            "repair_blocked_reason": "post_repair_maven_unavailable",
            "toolchain_warnings": toolchain_warnings,
            "commands": environment_records,
            "evidence_pack": {
                "job_id": job_id,
                "stage_index": stage_index,
                "stage_name": repair_candidate.get("stage_name") or f"Stage {stage_index}",
                "output_sandbox_ref": str(sandbox),
                "usable_artifacts": [
                    {"kind": "sandbox", "internal_ref": str(sandbox), "ref": redact_absolute_paths(str(sandbox))},
                ],
                "missing_artifacts": ["maven"],
                "repair_enabled": False,
                "environment_summary": environment_summary,
                "toolchain_warnings": toolchain_warnings,
                "post_repair_failure_kind": "toolchain_unavailable",
                "missing_tool": "maven",
                "repair_blocked_reason": "post_repair_maven_unavailable",
                "evidence_pack_id": f"post-repair-evidence-{repair_candidate.get('repair_candidate_id') or 'repair'}",
                "evidence_pack_checksum": "",
            },
            "classification": classification,
            "environment_summary": environment_summary,
            "proof_artifact": redact_absolute_paths(str(proof_path)),
            "post_repair_proof_artifact": redact_absolute_paths(str(proof_path)),
            "downstream_start_allowed": False,
            "started_at": environment_records[0]["started_at"],
            "completed_at": environment_records[-1]["completed_at"],
            "sandbox_path": redact_absolute_paths(str(sandbox)),
            "working_directory": redact_absolute_paths(str(sandbox)),
            "next_repair_candidate": None,
            "_next_repair_candidate": None,
        }

    compile_command = _render_command(POST_REPAIR_COMMANDS[0], resolved_toolchain)
    test_command = _render_command(POST_REPAIR_COMMANDS[1], resolved_toolchain)
    command_records = [
        _normalize_command_result(compile_command, sandbox, runner(compile_command, sandbox)),
        _normalize_command_result(test_command, sandbox, runner(test_command, sandbox)),
    ]
    build_ok = command_records[0]["exit_code"] == 0
    test_ok = command_records[1]["exit_code"] == 0
    dependency_record: dict[str, Any] | None = None
    if build_ok and not test_ok:
        dependency_command = _render_command(DEPENDENCY_TREE_COMMAND, resolved_toolchain)
        dependency_record = _normalize_command_result(dependency_command, sandbox, runner(dependency_command, sandbox))
        command_records.append(dependency_record)
    elif not build_ok:
        dependency_command = _render_command(DEPENDENCY_TREE_COMMAND, resolved_toolchain)
        dependency_record = _normalize_command_result(dependency_command, sandbox, runner(dependency_command, sandbox))
        command_records.append(dependency_record)

    build_log_path = proof_dir / "build.log"
    test_log_path = proof_dir / "test.log"
    build_log_path.write_text(_command_log_text(command_records[0]), encoding="utf-8")
    test_log_path.write_text(_command_log_text(command_records[1]), encoding="utf-8")
    dependency_log_path = None
    if dependency_record is not None:
        dependency_log_path = proof_dir / "dependency-tree.log"
        dependency_log_path.write_text(_command_log_text(dependency_record), encoding="utf-8")

    evidence_pack = {
        "job_id": job_id,
        "stage_index": stage_index,
        "stage_name": repair_candidate.get("stage_name") or f"Stage {stage_index}",
        "source_boot_version": repair_candidate.get("source_boot_version") or "",
        "target_boot_version": repair_candidate.get("target_boot_version") or "",
        "source_java_version": repair_candidate.get("source_java_version") or "",
        "target_java_version": repair_candidate.get("target_java_version") or "",
        "build_status": "BUILD_PASSED_IN_SANDBOX" if build_ok else "BUILD_FAILED_IN_SANDBOX",
        "test_status": "TEST_PASSED" if test_ok else "TEST_FAILED",
        "failure_summary": redact_model_summary(
            f"post-repair verification for {repair_candidate.get('family') or 'repair'}"
        ),
        "output_sandbox_ref": str(sandbox),
        "usable_artifacts": [
            {"kind": "sandbox", "internal_ref": str(sandbox), "ref": redact_absolute_paths(str(sandbox))},
            {"kind": "pom_xml", "internal_ref": str(pom_path), "ref": redact_absolute_paths(str(pom_path))},
            {
                "kind": "build_error_contract",
                "internal_ref": str(build_log_path),
                "ref": redact_absolute_paths(str(build_log_path)),
                "excerpt": _extract_relevant_log_excerpt(build_log_path.read_text(encoding="utf-8", errors="replace"), LOG_EXCERPT_PATTERNS),
            },
            {
                "kind": "test_report",
                "internal_ref": str(test_log_path),
                "ref": redact_absolute_paths(str(test_log_path)),
                "excerpt": _extract_relevant_log_excerpt(test_log_path.read_text(encoding="utf-8", errors="replace"), LOG_EXCERPT_PATTERNS),
            },
        ],
        "missing_artifacts": [],
        "repair_enabled": False,
        "environment_summary": environment_summary,
        "toolchain_warnings": toolchain_warnings,
    }
    if dependency_log_path is not None:
        evidence_pack["usable_artifacts"].append(
            {
                "kind": "dependency_graph",
                "internal_ref": str(dependency_log_path),
                "ref": redact_absolute_paths(str(dependency_log_path)),
                "excerpt": _extract_relevant_log_excerpt(
                    dependency_log_path.read_text(encoding="utf-8", errors="replace"),
                    LOG_EXCERPT_PATTERNS,
                    max_chars=16000,
                ),
            }
        )
    evidence_pack["evidence_pack_id"] = f"post-repair-evidence-{repair_candidate.get('repair_candidate_id') or 'repair'}"
    evidence_pack["evidence_pack_checksum"] = f"sha256:{sha256_canonical_json(evidence_pack)}"

    classification = classify_stage_failure(evidence_pack)
    next_candidate = None
    next_candidate_public = None
    next_candidate_blocked_reason = ""
    next_candidate_blocked_gate = ""
    next_candidate_gate_trace: dict[str, Any] | None = None
    if classification.get("classification_status") == "known_family_candidate":
        from migration_factory.control_tower.application.v2_repair_apply_candidate import (
            create_repair_apply_candidate,
            public_repair_apply_candidate,
        )

        next_candidate = create_repair_apply_candidate(classification, evidence_pack, {})
        if next_candidate is not None:
            next_candidate_public = public_repair_apply_candidate(next_candidate)
        else:
            next_candidate_blocked_reason = str(
                classification.get("repair_apply_candidate_blocked_reason")
                or "known_family_candidate_generation_returned_null"
            )
            next_candidate_blocked_gate = str(classification.get("governance_gate_type") or "backend_candidate_generation")
            next_candidate_gate_trace = {
                "classification_status": classification.get("classification_status"),
                "failure_type": classification.get("failure_type"),
                "repair_family_candidate": classification.get("repair_family_candidate"),
                "missing_required_evidence": classification.get("missing_required_evidence", []),
                "usable_artifacts": classification.get("usable_artifacts", []),
            }

    passed = build_ok and test_ok
    post_status = "passed" if passed else "failed"
    stage_recovery_status = "recovered" if passed else "still_failed"
    proof = {
        "job_id": job_id,
        "stage_index": stage_index,
        "repair_candidate_id": repair_candidate.get("repair_candidate_id", ""),
        "approval_id": approval.get("approval_id", ""),
        "post_repair_verification_status": post_status,
        "stage_recovery_status": stage_recovery_status,
        "commands": command_records,
        "evidence_pack_checksum": evidence_pack["evidence_pack_checksum"],
        "classification": classification,
        "environment_summary": evidence_pack["environment_summary"],
        "toolchain_warnings": toolchain_warnings,
        "next_repair_candidate_blocked_reason": next_candidate_blocked_reason,
        "next_repair_candidate_blocked_gate": next_candidate_blocked_gate,
        "next_repair_candidate_gate_trace": next_candidate_gate_trace,
        "proof_created_at": utc_now_text(),
        "downstream_start_allowed": False,
    }
    proof["proof_checksum"] = f"sha256:{sha256_canonical_json(proof)}"
    proof_path = proof_dir / "post-repair-verification.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")

    result = {
        "post_repair_verification_status": post_status,
        "stage_recovery_status": stage_recovery_status,
        "commands": command_records,
        "evidence_pack": evidence_pack,
        "classification": classification,
        "environment_summary": evidence_pack["environment_summary"],
        "toolchain_warnings": toolchain_warnings,
        "proof_artifact": redact_absolute_paths(str(proof_path)),
        "post_repair_proof_artifact": redact_absolute_paths(str(proof_path)),
        "downstream_start_allowed": False,
        "started_at": command_records[0]["started_at"],
        "completed_at": command_records[-1]["completed_at"],
        "sandbox_path": redact_absolute_paths(str(sandbox)),
        "working_directory": redact_absolute_paths(str(sandbox)),
        "next_repair_candidate": next_candidate_public,
        "next_repair_candidate_blocked_reason": next_candidate_blocked_reason,
        "next_repair_candidate_blocked_gate": next_candidate_blocked_gate,
        "next_repair_candidate_gate_trace": next_candidate_gate_trace,
        "_next_repair_candidate": next_candidate,
    }
    return result


def _resolve_sandbox_root(repair_candidate: dict[str, Any]) -> Path:
    sandbox_ref = str(repair_candidate.get("_sandbox_root") or "").strip()
    if not sandbox_ref:
        raise ValueError("missing_sandbox_root")
    return Path(sandbox_ref).resolve()


def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    started_at = utc_now_text()
    start = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            shell=False,
            check=False,
        )
        exit_code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except Exception as exc:
        exit_code = 1
        stdout = ""
        stderr = str(exc)
    completed_at = utc_now_text()
    duration_ms = int((time.monotonic() - start) * 1000)
    return {
        "command": command,
        "working_directory": str(cwd),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
    }


def _normalize_command_result(command: list[str], cwd: Path, result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        normalized = dict(result)
    elif isinstance(result, tuple) and len(result) >= 3:
        normalized = {
            "exit_code": int(result[0]),
            "stdout": str(result[1]),
            "stderr": str(result[2]),
        }
    else:
        normalized = {"exit_code": 1, "stdout": "", "stderr": str(result)}
    normalized.setdefault("command", command)
    normalized.setdefault("working_directory", str(cwd))
    normalized.setdefault("stdout", "")
    normalized.setdefault("stderr", "")
    normalized.setdefault("started_at", utc_now_text())
    normalized.setdefault("completed_at", utc_now_text())
    normalized.setdefault("duration_ms", 0)
    normalized["exit_code"] = int(normalized.get("exit_code") or 0)
    normalized["command"] = [str(item) for item in normalized.get("command") or command]
    normalized["working_directory"] = str(normalized.get("working_directory") or cwd)
    return normalized


def _command_log_text(record: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"$ {' '.join(record.get('command') or [])}",
            str(record.get("stdout") or "").strip(),
            str(record.get("stderr") or "").strip(),
        ]
    ).strip()


def _environment_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"java": {}, "maven": {}}
    for record in records:
        command_list = [str(item) for item in (record.get("command") or [])]
        command = " ".join(command_list)
        stdout = str(record.get("stdout") or "").strip()
        stderr = str(record.get("stderr") or "").strip()
        text = "\n".join([stdout, stderr]).strip()
        executable = _normalize_executable_name(command_list[0] if command_list else "")
        if executable == "java":
            summary["java"] = {"command": command_list, "exit_code": record.get("exit_code"), "output": text}
        elif executable == "mvn":
            summary["maven"] = {"command": command_list, "exit_code": record.get("exit_code"), "output": text}
    return summary


def _normalize_executable_name(value: str) -> str:
    name = Path(value).name.lower()
    if name in {"mvn.cmd", "mvn.bat", "mvn.exe"}:
        return "mvn"
    if name in {"java.exe", "java"}:
        return "java"
    return name


def _extract_java_major_version(text: str) -> str:
    match = re.search(r'(?i)(?:openjdk|java) version "?(\d+)(?:\.(\d+)\.(\d+))?', text)
    if match is None:
        return ""
    first = match.group(1) or ""
    second = match.group(2) or ""
    if first == "1" and second:
        return second
    return first


def _resolve_backend_toolchain() -> dict[str, Any]:
    env = os.environ
    java_command = resolve_java_executable(env)
    maven_command = resolve_maven_executable(env)
    maven_available = _maven_command_available(env, maven_command)
    return {
        "java_command": java_command,
        "maven_command": maven_command,
        "maven_available": maven_available,
    }


def _maven_command_available(env: dict[str, str], command: str) -> bool:
    configured = str(env.get("MAVEN_CMD") or env.get("MVN_CMD") or "").strip()
    if configured and command == configured:
        return True
    maven_home = str(env.get("MAVEN_HOME") or "").strip()
    if maven_home:
        expected = str(Path(maven_home) / "bin" / ("mvn.cmd" if os.name == "nt" else "mvn"))
        if command == expected:
            return True
    if shutil.which("mvn.cmd", path=env.get("PATH")) == command:
        return True
    if shutil.which("mvn", path=env.get("PATH")) == command:
        return True
    return False


def _java_toolchain_warning(environment_summary: dict[str, Any], repair_candidate: dict[str, Any]) -> str:
    target_java = str(
        repair_candidate.get("target_java_version")
        or repair_candidate.get("source_java_version")
        or repair_candidate.get("stage_target_java_version")
        or ""
    ).strip()
    if not target_java:
        return ""
    actual = _extract_java_major_version(str((environment_summary.get("java") or {}).get("output") or ""))
    if not actual:
        return ""
    if actual != target_java:
        return f"java_version_mismatch_target_{target_java}_actual_{actual}"
    return ""


def _render_command(command: list[str], toolchain: dict[str, Any]) -> list[str]:
    if not command:
        return command
    executable = str(command[0])
    if executable == "__MAVEN__":
        return [str(toolchain["maven_command"]), *command[1:]]
    if executable == "__JAVA__":
        return [str(toolchain["java_command"]), *command[1:]]
    return command


def _write_toolchain_failure_proof(
    *,
    proof_dir: Path,
    job_id: str,
    stage_index: int,
    repair_candidate: dict[str, Any],
    approval: dict[str, Any],
    sandbox: Path,
    environment_summary: dict[str, Any],
    toolchain_warnings: list[str],
    resolved_toolchain: dict[str, Any],
) -> Path:
    proof = {
        "job_id": job_id,
        "stage_index": stage_index,
        "repair_candidate_id": repair_candidate.get("repair_candidate_id", ""),
        "approval_id": approval.get("approval_id", ""),
        "post_repair_verification_status": "failed",
        "stage_recovery_status": "still_failed",
        "post_repair_failure_kind": "toolchain_unavailable",
        "missing_tool": "maven",
        "repair_blocked_reason": "post_repair_maven_unavailable",
        "commands": [],
        "environment_summary": environment_summary,
        "toolchain_warnings": toolchain_warnings,
        "proof_created_at": utc_now_text(),
        "downstream_start_allowed": False,
        "resolved_toolchain": resolved_toolchain,
    }
    proof["proof_checksum"] = f"sha256:{sha256_canonical_json(proof)}"
    proof_path = proof_dir / "post-repair-verification.json"
    proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True), encoding="utf-8")
    return proof_path


def _extract_relevant_log_excerpt(text: str, patterns: list[str] | tuple[str, ...], max_chars: int = 12000) -> str:
    if not text:
        return ""
    windows: list[tuple[int, int]] = []
    total_len = len(text)
    head = min(total_len, max(1000, max_chars // 5))
    tail = min(total_len, max(1000, max_chars // 5))
    windows.append((0, head))
    windows.append((max(0, total_len - tail), total_len))
    lowered = text.lower()
    for pattern in patterns:
        needle = str(pattern).lower()
        if not needle:
            continue
        start = 0
        while True:
            index = lowered.find(needle, start)
            if index < 0:
                break
            window_start = max(0, index - 350)
            window_end = min(total_len, index + len(needle) + 650)
            windows.append((window_start, window_end))
            start = index + max(1, len(needle))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not merged or start > merged[-1][1] + 16:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    parts: list[str] = []
    last_end = 0
    for start, end in merged:
        if start > last_end:
            parts.append("...")
        parts.append(text[start:end].strip())
        last_end = end
    excerpt = "\n".join(part for part in parts if part)
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[:max_chars]
