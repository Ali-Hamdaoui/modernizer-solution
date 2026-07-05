"""Backend-owned post-repair verification and recursive diagnosis."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.application.redaction import redact_absolute_paths, redact_model_summary
from migration_factory.control_tower.application.v2_stage_failure_classifier import classify_stage_failure
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


CommandRunner = Callable[[list[str], Path], dict[str, Any]]

POST_REPAIR_COMMANDS: tuple[list[str], ...] = (
    ["mvn", "-DskipTests", "clean", "compile"],
    ["mvn", "test"],
)
DEPENDENCY_TREE_COMMAND: list[str] = ["mvn", "dependency:tree", "-DoutputType=text"]


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
    command_records = [
        _normalize_command_result(POST_REPAIR_COMMANDS[0], sandbox, runner(POST_REPAIR_COMMANDS[0], sandbox)),
        _normalize_command_result(POST_REPAIR_COMMANDS[1], sandbox, runner(POST_REPAIR_COMMANDS[1], sandbox)),
    ]
    build_ok = command_records[0]["exit_code"] == 0
    test_ok = command_records[1]["exit_code"] == 0
    dependency_record: dict[str, Any] | None = None
    if not (build_ok and test_ok):
        dependency_record = _normalize_command_result(DEPENDENCY_TREE_COMMAND, sandbox, runner(DEPENDENCY_TREE_COMMAND, sandbox))
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
                "excerpt": build_log_path.read_text(encoding="utf-8", errors="replace")[:4000],
            },
            {
                "kind": "test_report",
                "internal_ref": str(test_log_path),
                "ref": redact_absolute_paths(str(test_log_path)),
                "excerpt": test_log_path.read_text(encoding="utf-8", errors="replace")[:4000],
            },
        ],
        "missing_artifacts": [],
        "repair_enabled": False,
    }
    if dependency_log_path is not None:
        evidence_pack["usable_artifacts"].append(
            {
                "kind": "dependency_graph",
                "internal_ref": str(dependency_log_path),
                "ref": redact_absolute_paths(str(dependency_log_path)),
                "excerpt": dependency_log_path.read_text(encoding="utf-8", errors="replace")[:4000],
            }
        )
    evidence_pack["evidence_pack_id"] = f"post-repair-evidence-{repair_candidate.get('repair_candidate_id') or 'repair'}"
    evidence_pack["evidence_pack_checksum"] = f"sha256:{sha256_canonical_json(evidence_pack)}"

    classification = classify_stage_failure(evidence_pack)
    next_candidate = None
    next_candidate_public = None
    if classification.get("classification_status") == "known_family_candidate":
        from migration_factory.control_tower.application.v2_repair_apply_candidate import (
            create_repair_apply_candidate,
            public_repair_apply_candidate,
        )

        next_candidate = create_repair_apply_candidate(classification, evidence_pack, {})
        if next_candidate is not None:
            next_candidate_public = public_repair_apply_candidate(next_candidate)

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
        "proof_artifact": redact_absolute_paths(str(proof_path)),
        "post_repair_proof_artifact": redact_absolute_paths(str(proof_path)),
        "downstream_start_allowed": False,
        "started_at": command_records[0]["started_at"],
        "completed_at": command_records[-1]["completed_at"],
        "sandbox_path": redact_absolute_paths(str(sandbox)),
        "working_directory": redact_absolute_paths(str(sandbox)),
        "next_repair_candidate": next_candidate_public,
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
