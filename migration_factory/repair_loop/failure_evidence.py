"""F5-T1: Deterministic, redacted, backend-owned build/test failure evidence.

Creates stable FailureEvidence before any Repair LLM prompt exists.
Two checksum layers:
  - content_checksum: canonical over stable normalized evidence (excludes volatile fields)
  - artifact_checksum: checksum over the full persisted envelope
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)


class FailureSource(str, Enum):
    BUILD = "build"
    TEST = "test"
    VALIDATION = "validation"
    TRANSFORM = "transform"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class NormalizedCompilerError:
    message: str = ""
    file_path: str = ""
    line: int = 0
    column: int = 0
    severity: str = "error"


@dataclass(frozen=True)
class NormalizedTestFailure:
    test_name: str = ""
    test_class: str = ""
    message: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class FailureEvidence:
    failure_source: FailureSource = FailureSource.UNKNOWN
    stage_index: int = 0
    job_id: str = ""
    command_id: str = ""
    failure_summary: str = ""
    compiler_errors: tuple[NormalizedCompilerError, ...] = ()
    test_failures: tuple[NormalizedTestFailure, ...] = ()
    changed_files: tuple[str, ...] = ()
    source_profile: str = ""
    target_profile: str = ""
    accepted_artifact_checksums: tuple[str, ...] = ()
    artifact_refs: dict[str, str] = field(default_factory=dict)
    stdout_tail: str = ""
    stderr_tail: str = ""
    safe_log_preview: str = ""
    content_checksum: str = ""
    artifact_checksum: str = ""
    created_at: str = ""
    schema_version: str = "1.0.0"

    # Maximum length for log tails to prevent unbounded evidence
    MAX_LOG_TAIL_LENGTH: int = 4000

    def __post_init__(self):
        for field_name in (
            "stdout_tail",
            "stderr_tail",
            "safe_log_preview",
            "failure_summary",
        ):
            value = getattr(self, field_name)
            if isinstance(value, str) and len(value) > self.MAX_LOG_TAIL_LENGTH:
                object.__setattr__(self, field_name, value[: self.MAX_LOG_TAIL_LENGTH])


def compute_failure_content_checksum(evidence: FailureEvidence) -> str:
    payload: dict[str, Any] = {
        "failure_source": evidence.failure_source.value,
        "stage_index": evidence.stage_index,
        "job_id": evidence.job_id,
        "command_id": evidence.command_id,
        "failure_summary": evidence.failure_summary,
        "compiler_errors": [
            {
                "message": e.message,
                "file_path": e.file_path,
                "line": e.line,
                "column": e.column,
                "severity": e.severity,
            }
            for e in sorted(evidence.compiler_errors, key=lambda x: (x.file_path, x.line, x.column))
        ],
        "test_failures": [
            {
                "test_name": t.test_name,
                "test_class": t.test_class,
                "message": t.message,
                "file_path": t.file_path,
            }
            for t in sorted(evidence.test_failures, key=lambda x: (x.test_class, x.test_name))
        ],
        "changed_files": tuple(sorted(evidence.changed_files)),
        "source_profile": evidence.source_profile,
        "target_profile": evidence.target_profile,
        "accepted_artifact_checksums": tuple(sorted(evidence.accepted_artifact_checksums)),
        "artifact_refs": dict(sorted(evidence.artifact_refs.items())),
        "safe_log_preview": evidence.safe_log_preview,
    }
    return sha256_canonical_json(payload)


def compute_failure_artifact_checksum(evidence: FailureEvidence) -> str:
    content_checksum = evidence.content_checksum or compute_failure_content_checksum(evidence)
    payload: dict[str, Any] = {
        "content_checksum": content_checksum,
        "created_at": evidence.created_at,
        "schema_version": evidence.schema_version,
    }
    return sha256_canonical_json(payload)


def build_failure_evidence(
    *,
    failure_source: FailureSource,
    stage_index: int = 0,
    job_id: str = "",
    command_id: str = "",
    failure_summary: str = "",
    compiler_errors: tuple[NormalizedCompilerError, ...] | None = None,
    test_failures: tuple[NormalizedTestFailure, ...] | None = None,
    changed_files: tuple[str, ...] | None = None,
    source_profile: str = "",
    target_profile: str = "",
    accepted_artifact_checksums: tuple[str, ...] | None = None,
    artifact_refs: dict[str, str] | None = None,
    stdout_tail: str = "",
    stderr_tail: str = "",
    safe_log_preview: str = "",
) -> FailureEvidence:
    evidence = FailureEvidence(
        failure_source=failure_source,
        stage_index=stage_index,
        job_id=job_id,
        command_id=command_id,
        failure_summary=failure_summary,
        compiler_errors=tuple(compiler_errors or ()),
        test_failures=tuple(test_failures or ()),
        changed_files=tuple(sorted(changed_files or ())),
        source_profile=source_profile,
        target_profile=target_profile,
        accepted_artifact_checksums=tuple(sorted(accepted_artifact_checksums or ())),
        artifact_refs=artifact_refs or {},
        stdout_tail=stdout_tail[:FailureEvidence.MAX_LOG_TAIL_LENGTH] if stdout_tail else "",
        stderr_tail=stderr_tail[:FailureEvidence.MAX_LOG_TAIL_LENGTH] if stderr_tail else "",
        safe_log_preview=safe_log_preview[:FailureEvidence.MAX_LOG_TAIL_LENGTH] if safe_log_preview else "",
        created_at=utc_now_text(),
    )
    content_checksum = compute_failure_content_checksum(evidence)
    artifact_checksum = compute_failure_artifact_checksum(
        FailureEvidence(
            failure_source=evidence.failure_source,
            stage_index=evidence.stage_index,
            job_id=evidence.job_id,
            command_id=evidence.command_id,
            failure_summary=evidence.failure_summary,
            compiler_errors=evidence.compiler_errors,
            test_failures=evidence.test_failures,
            changed_files=evidence.changed_files,
            source_profile=evidence.source_profile,
            target_profile=evidence.target_profile,
            accepted_artifact_checksums=evidence.accepted_artifact_checksums,
            artifact_refs=evidence.artifact_refs,
            stdout_tail=evidence.stdout_tail,
            stderr_tail=evidence.stderr_tail,
            safe_log_preview=evidence.safe_log_preview,
            content_checksum=content_checksum,
            created_at=evidence.created_at,
            schema_version=evidence.schema_version,
        )
    )
    return FailureEvidence(
        failure_source=evidence.failure_source,
        stage_index=evidence.stage_index,
        job_id=evidence.job_id,
        command_id=evidence.command_id,
        failure_summary=evidence.failure_summary,
        compiler_errors=evidence.compiler_errors,
        test_failures=evidence.test_failures,
        changed_files=evidence.changed_files,
        source_profile=evidence.source_profile,
        target_profile=evidence.target_profile,
        accepted_artifact_checksums=evidence.accepted_artifact_checksums,
        artifact_refs=evidence.artifact_refs,
        stdout_tail=evidence.stdout_tail,
        stderr_tail=evidence.stderr_tail,
        safe_log_preview=evidence.safe_log_preview,
        content_checksum=content_checksum,
        artifact_checksum=artifact_checksum,
        created_at=evidence.created_at,
        schema_version=evidence.schema_version,
    )


def failure_evidence_to_dict(evidence: FailureEvidence) -> dict[str, Any]:
    return {
        "failure_source": evidence.failure_source.value,
        "stage_index": evidence.stage_index,
        "job_id": evidence.job_id,
        "command_id": evidence.command_id,
        "failure_summary": evidence.failure_summary,
        "compiler_errors": [
            {
                "message": e.message,
                "file_path": e.file_path,
                "line": e.line,
                "column": e.column,
                "severity": e.severity,
            }
            for e in sorted(evidence.compiler_errors, key=lambda x: (x.file_path, x.line, x.column))
        ],
        "test_failures": [
            {
                "test_name": t.test_name,
                "test_class": t.test_class,
                "message": t.message,
                "file_path": t.file_path,
            }
            for t in sorted(evidence.test_failures, key=lambda x: (x.test_class, x.test_name))
        ],
        "changed_files": list(evidence.changed_files),
        "source_profile": evidence.source_profile,
        "target_profile": evidence.target_profile,
        "accepted_artifact_checksums": list(evidence.accepted_artifact_checksums),
        "artifact_refs": dict(sorted(evidence.artifact_refs.items())),
        "stdout_tail": evidence.stdout_tail,
        "stderr_tail": evidence.stderr_tail,
        "safe_log_preview": evidence.safe_log_preview,
        "content_checksum": evidence.content_checksum,
        "artifact_checksum": evidence.artifact_checksum,
        "created_at": evidence.created_at,
        "schema_version": evidence.schema_version,
    }
