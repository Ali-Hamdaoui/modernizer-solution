"""F5-T2: Repair context pack — checksum-bound input bundle for Primary Repair LLM.

Builds a model-safe RepairContextPack from failure evidence, job/command state,
upstream artifacts, prior repair attempts, reviewer notes, and user comments.
Redacts secrets, absolute paths, raw env, endpoints, deployments, raw commands,
and sandbox paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from typing import Any

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    sha256_hex,
    utc_now_text,
)
from migration_factory.repair_loop.failure_evidence import FailureEvidence


FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset({
    "sandbox_path",
    "argv",
    "env",
    "raw_command",
    "endpoint",
    "deployment",
    "env_ref",
    "user_supplied_file_path",
    "filesystem_target",
})

MAX_SOURCE_EVIDENCE_FILES = 8
MAX_SOURCE_EVIDENCE_BYTES = 12_000
SOURCE_EVIDENCE_ALLOWED_SUFFIXES: frozenset[str] = frozenset({
    ".java",
    ".xml",
    ".properties",
    ".yml",
    ".yaml",
})
SOURCE_EVIDENCE_BLOCKED_PARTS: frozenset[str] = frozenset({
    ".git",
    ".github",
    ".migration",
    "target",
    "build",
    ".gradle",
    ".idea",
    "node_modules",
    "dist",
    "out",
    "deploy",
    "deployment",
    "k8s",
    "helm",
    "charts",
})

_JAVA_TEST_FQCN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_$])"
    r"((?:[A-Za-z_$][A-Za-z0-9_$]*\.)+"
    r"[A-Z][A-Za-z0-9_$]*(?:Tests|Test|IT))\b"
)


@dataclass(frozen=True)
class RepairContextPack:
    job_id: str
    stage_index: int
    command_id: str
    failure_source: str
    failure_evidence_checksum: str
    source_profile: str = ""
    target_profile: str = ""
    accepted_analysis_checksum: str = ""
    accepted_planning_checksum: str = ""
    prior_proposal_checksums: tuple[str, ...] = ()
    prior_reviewer_notes: tuple[str, ...] = ()
    user_comments: str = ""
    changed_files: tuple[str, ...] = ()
    safe_log_preview: str = ""
    source_evidence: tuple[dict[str, Any], ...] = ()
    base_repo_state_checksum: str = ""
    context_pack_checksum: str = ""
    prior_revision_ids: tuple[str, ...] = ()
    cycle_number: int = 0
    max_cycles: int = 3
    created_at: str = ""
    schema_version: str = "1.0.0"


def compute_context_pack_checksum(pack: RepairContextPack) -> str:
    payload: dict[str, Any] = {
        "job_id": pack.job_id,
        "stage_index": pack.stage_index,
        "command_id": pack.command_id,
        "failure_source": pack.failure_source,
        "failure_evidence_checksum": pack.failure_evidence_checksum,
        "source_profile": pack.source_profile,
        "target_profile": pack.target_profile,
        "accepted_analysis_checksum": pack.accepted_analysis_checksum,
        "accepted_planning_checksum": pack.accepted_planning_checksum,
        "prior_proposal_checksums": list(sorted(pack.prior_proposal_checksums)),
        "prior_reviewer_notes": list(pack.prior_reviewer_notes),
        "user_comments": pack.user_comments,
        "changed_files": list(sorted(pack.changed_files)),
        "safe_log_preview": pack.safe_log_preview,
        "source_evidence": list(pack.source_evidence),
        "base_repo_state_checksum": pack.base_repo_state_checksum,
        "prior_revision_ids": list(sorted(pack.prior_revision_ids)),
        "cycle_number": pack.cycle_number,
        "max_cycles": pack.max_cycles,
    }
    return sha256_canonical_json(payload)


def compute_base_repo_state_checksum(
    *,
    changed_files: tuple[str, ...] = (),
    file_checksums: dict[str, str] | None = None,
    source_profile: str = "",
    target_profile: str = "",
    accepted_artifact_checksums: tuple[str, ...] = (),
) -> str:
    payload: dict[str, Any] = {
        "changed_files": list(sorted(changed_files)),
        "file_checksums": dict(sorted((file_checksums or {}).items())),
        "source_profile": source_profile,
        "target_profile": target_profile,
        "accepted_artifact_checksums": list(sorted(accepted_artifact_checksums)),
    }
    return sha256_canonical_json(payload)


def _validate_context_forbidden_keys(pack: RepairContextPack) -> list[str]:
    failures: list[str] = []
    for forbidden in FORBIDDEN_CONTEXT_KEYS:
        if hasattr(pack, forbidden):
            value = getattr(pack, forbidden)
            if value:
                failures.append(f"forbidden key {forbidden!r} present in context pack")
    return failures


def build_repair_context_pack(
    *,
    failure_evidence: FailureEvidence,
    job_id: str = "",
    stage_index: int = 0,
    command_id: str = "",
    source_profile: str = "",
    target_profile: str = "",
    accepted_analysis_checksum: str = "",
    accepted_planning_checksum: str = "",
    prior_proposal_checksums: tuple[str, ...] | None = None,
    prior_reviewer_notes: tuple[str, ...] | None = None,
    user_comments: str = "",
    changed_files: tuple[str, ...] | None = None,
    file_checksums: dict[str, str] | None = None,
    sandbox_path: str | Path | None = None,
    accepted_artifact_checksums: tuple[str, ...] | None = None,
    prior_revision_ids: tuple[str, ...] | None = None,
    cycle_number: int = 0,
    max_cycles: int = 3,
) -> RepairContextPack:
    resolved_job = job_id or failure_evidence.job_id
    resolved_stage = stage_index or failure_evidence.stage_index
    resolved_command = command_id or failure_evidence.command_id

    resolved_changed = tuple(changed_files) if changed_files else failure_evidence.changed_files
    resolved_profile_source = source_profile or failure_evidence.source_profile
    resolved_profile_target = target_profile or failure_evidence.target_profile
    source_evidence = _collect_bounded_source_evidence(
        sandbox_path=sandbox_path,
        failure_evidence=failure_evidence,
        changed_files=resolved_changed,
    )

    base_repo_checksum = compute_base_repo_state_checksum(
        changed_files=resolved_changed,
        file_checksums=file_checksums,
        source_profile=resolved_profile_source,
        target_profile=resolved_profile_target,
        accepted_artifact_checksums=accepted_artifact_checksums or failure_evidence.accepted_artifact_checksums,
    )

    pack = RepairContextPack(
        job_id=resolved_job,
        stage_index=resolved_stage,
        command_id=resolved_command,
        failure_source=failure_evidence.failure_source.value,
        failure_evidence_checksum=failure_evidence.content_checksum,
        source_profile=resolved_profile_source,
        target_profile=resolved_profile_target,
        accepted_analysis_checksum=accepted_analysis_checksum,
        accepted_planning_checksum=accepted_planning_checksum,
        prior_proposal_checksums=tuple(sorted(prior_proposal_checksums or ())),
        prior_reviewer_notes=tuple(prior_reviewer_notes or ()),
        user_comments=user_comments,
        changed_files=resolved_changed,
        safe_log_preview=failure_evidence.safe_log_preview,
        source_evidence=source_evidence,
        base_repo_state_checksum=base_repo_checksum,
        prior_revision_ids=tuple(sorted(prior_revision_ids or ())),
        cycle_number=cycle_number,
        max_cycles=max_cycles,
        created_at=utc_now_text(),
    )

    context_checksum = compute_context_pack_checksum(pack)
    return RepairContextPack(
        job_id=pack.job_id,
        stage_index=pack.stage_index,
        command_id=pack.command_id,
        failure_source=pack.failure_source,
        failure_evidence_checksum=pack.failure_evidence_checksum,
        source_profile=pack.source_profile,
        target_profile=pack.target_profile,
        accepted_analysis_checksum=pack.accepted_analysis_checksum,
        accepted_planning_checksum=pack.accepted_planning_checksum,
        prior_proposal_checksums=pack.prior_proposal_checksums,
        prior_reviewer_notes=pack.prior_reviewer_notes,
        user_comments=pack.user_comments,
        changed_files=pack.changed_files,
        safe_log_preview=pack.safe_log_preview,
        source_evidence=pack.source_evidence,
        base_repo_state_checksum=pack.base_repo_state_checksum,
        context_pack_checksum=context_checksum,
        prior_revision_ids=pack.prior_revision_ids,
        cycle_number=pack.cycle_number,
        max_cycles=pack.max_cycles,
        created_at=pack.created_at,
        schema_version=pack.schema_version,
    )


def is_context_pack_stale(
    pack: RepairContextPack,
    current_file_checksums: dict[str, str] | None = None,
    current_accepted_artifact_checksums: tuple[str, ...] | None = None,
) -> bool:
    new_repo_checksum = compute_base_repo_state_checksum(
        changed_files=pack.changed_files,
        file_checksums=current_file_checksums,
        source_profile=pack.source_profile,
        target_profile=pack.target_profile,
        accepted_artifact_checksums=current_accepted_artifact_checksums or (),
    )
    return new_repo_checksum != pack.base_repo_state_checksum


def context_pack_to_dict(pack: RepairContextPack) -> dict[str, Any]:
    return {
        "job_id": pack.job_id,
        "stage_index": pack.stage_index,
        "command_id": pack.command_id,
        "failure_source": pack.failure_source,
        "failure_evidence_checksum": pack.failure_evidence_checksum,
        "source_profile": pack.source_profile,
        "target_profile": pack.target_profile,
        "accepted_analysis_checksum": pack.accepted_analysis_checksum,
        "accepted_planning_checksum": pack.accepted_planning_checksum,
        "prior_proposal_checksums": list(pack.prior_proposal_checksums),
        "prior_reviewer_notes": list(pack.prior_reviewer_notes),
        "user_comments": pack.user_comments,
        "changed_files": list(pack.changed_files),
        "safe_log_preview": pack.safe_log_preview,
        "source_evidence": list(pack.source_evidence),
        "base_repo_state_checksum": pack.base_repo_state_checksum,
        "context_pack_checksum": pack.context_pack_checksum,
        "prior_revision_ids": list(pack.prior_revision_ids),
        "cycle_number": pack.cycle_number,
        "max_cycles": pack.max_cycles,
        "created_at": pack.created_at,
        "schema_version": pack.schema_version,
    }


def _collect_bounded_source_evidence(
    *,
    sandbox_path: str | Path | None,
    failure_evidence: FailureEvidence,
    changed_files: tuple[str, ...],
) -> tuple[dict[str, Any], ...]:
    if sandbox_path is None or not str(sandbox_path).strip():
        return ()
    try:
        sandbox = Path(sandbox_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return ()
    if not sandbox.is_dir():
        return ()

    compiler_paths: list[str] = []
    for error in failure_evidence.compiler_errors:
        _append_candidate(compiler_paths, error.file_path)

    test_failure_paths: list[str] = []
    for failure in failure_evidence.test_failures:
        _append_candidate(test_failure_paths, failure.file_path)
        for path in _java_test_paths_from_text(failure.test_class):
            _append_candidate(test_failure_paths, path)

    log_test_paths: list[str] = []
    for value in (
        failure_evidence.failure_summary,
        failure_evidence.safe_log_preview,
        failure_evidence.stdout_tail,
        failure_evidence.stderr_tail,
    ):
        for path in _java_test_paths_from_text(value):
            _append_candidate(log_test_paths, path)

    resolved_test_paths: list[str] = []
    for relative in (*compiler_paths, *test_failure_paths, *log_test_paths):
        resolved = _resolve_source_file(sandbox, relative)
        if resolved is None:
            continue
        normalized, _ = resolved
        if normalized.startswith("src/test/java/") and normalized.endswith(".java"):
            _append_candidate(resolved_test_paths, normalized)

    production_paths = _infer_production_source_candidates(
        sandbox=sandbox,
        test_paths=tuple(resolved_test_paths),
    )

    candidates: list[str] = []
    for group in (
        compiler_paths,
        test_failure_paths,
        log_test_paths,
        production_paths,
        ["pom.xml"],
        list(changed_files),
    ):
        for path in group:
            _append_candidate(candidates, path)

    entries: list[dict[str, Any]] = []
    total_bytes = 0
    for relative in candidates:
        if len(entries) >= MAX_SOURCE_EVIDENCE_FILES:
            break
        resolved = _resolve_source_file(sandbox, relative)
        if resolved is None:
            continue
        normalized, path = resolved
        try:
            if path.stat().st_size > MAX_SOURCE_EVIDENCE_BYTES:
                continue
            raw = path.read_bytes()
            if len(raw) > MAX_SOURCE_EVIDENCE_BYTES:
                continue
            if total_bytes + len(raw) > MAX_SOURCE_EVIDENCE_BYTES:
                continue
            content = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        total_bytes += len(raw)
        entries.append(
            {
                "path": normalized,
                "checksum": "sha256:" + sha256_hex(raw),
                "byte_length": len(raw),
                "content": content,
            }
        )
    return tuple(entries)


def _append_candidate(candidates: list[str], value: str) -> None:
    normalized = _normalize_source_path(value)
    if normalized and normalized not in candidates:
        candidates.append(normalized)


def _infer_production_source_candidates(
    *,
    sandbox: Path,
    test_paths: tuple[str, ...],
) -> tuple[str, ...]:
    inferred: list[str] = []
    for normalized in test_paths:
        resolved = _resolve_source_file(sandbox, normalized)
        if resolved is None:
            continue
        _, test_file = resolved
        _append_candidate(inferred, _test_path_to_main_path(normalized))
        try:
            if test_file.stat().st_size > MAX_SOURCE_EVIDENCE_BYTES:
                continue
            test_bytes = test_file.read_bytes()
            if len(test_bytes) > MAX_SOURCE_EVIDENCE_BYTES:
                continue
            test_text = test_bytes.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            test_text = ""
        package_prefix = "/".join(PurePosixPath(normalized).parts[3:-1])
        for class_name in _referenced_java_classes(test_text):
            _append_candidate(inferred, f"src/main/java/{package_prefix}/{class_name}.java")
    return tuple(inferred)


def _test_path_to_main_path(path: str) -> str:
    relative = path.removeprefix("src/test/java/")
    filename = PurePosixPath(relative).name
    stem = filename[:-5] if filename.endswith(".java") else filename
    for suffix in ("Test", "Tests", "IT"):
        if stem.endswith(suffix) and len(stem) > len(suffix):
            stem = stem[: -len(suffix)]
            break
    parent = PurePosixPath(relative).parent
    return str(PurePosixPath("src/main/java") / parent / f"{stem}.java")


def _referenced_java_classes(text: str) -> tuple[str, ...]:
    names = re.findall(r"\bnew\s+([A-Z][A-Za-z0-9_]*)\s*\(", text)
    return tuple(dict.fromkeys(name for name in names if name not in {"String", "RuntimeException", "IllegalStateException"}))


def _java_test_paths_from_text(text: str) -> tuple[str, ...]:
    paths: list[str] = []
    for match in _JAVA_TEST_FQCN_PATTERN.finditer(str(text or "")):
        fqcn = match.group(1)
        parts = fqcn.split(".")
        class_name = parts[-1].split("$", 1)[0]
        _append_candidate(
            paths,
            str(PurePosixPath("src/test/java", *parts[:-1], f"{class_name}.java")),
        )
    return tuple(paths)


def _normalize_source_path(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if PureWindowsPath(text).is_absolute() or PureWindowsPath(text).drive or PurePosixPath(text).is_absolute():
        return ""
    while text.startswith("./"):
        text = text[2:]
    normalized = PurePosixPath(text).as_posix()
    if normalized in {"", "."}:
        return ""
    if ".." in PurePosixPath(normalized).parts:
        return ""
    return normalized


def _source_path_blocked(path: str) -> bool:
    pure = PurePosixPath(path)
    if pure.suffix.lower() not in SOURCE_EVIDENCE_ALLOWED_SUFFIXES:
        return True
    return any(part.lower() in SOURCE_EVIDENCE_BLOCKED_PARTS for part in pure.parts)


def _resolve_source_file(sandbox: Path, value: str) -> tuple[str, Path] | None:
    normalized = _normalize_source_path(value)
    if not normalized or _source_path_blocked(normalized):
        return None
    try:
        resolved = (sandbox / PurePosixPath(normalized)).resolve(strict=True)
        resolved_relative = resolved.relative_to(sandbox).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None
    if _source_path_blocked(resolved_relative) or not resolved.is_file():
        return None
    return normalized, resolved
