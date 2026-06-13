"""V1-15A deterministic patch policy validation for sandbox mutation.

Enforces:
- No shell metacharacters in patch content.
- No escape sequences or path traversal.
- No oversize patches.
- No unapproved patches (missing prior approval).
- Snapshot-before-write invariant (enforced at service level).
- LLM cannot execute, approve, or write files directly.
- Browser payloads cannot choose raw paths, Maven goals,
  shell commands, working directories, or model deployments.
"""

from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from migration_factory.control_tower.application.dto import (
    PatchPolicyValidationDto,
    SandboxSnapshotDto,
)
from migration_factory.control_tower.domain.checksums import (
    canonical_json_text,
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import (
    V1PatchPolicyValidationRecord,
    V1SandboxSnapshotRecord,
)
from migration_factory.control_tower.domain.errors import (
    NotFoundError,
    PatchContentEscapeError,
    PatchContentMismatchError,
    PatchContentOversizeError,
    PatchNotApprovedError,
    PatchPolicyValidationError,
    PatchRollbackError,
    PatchSnapshotNotFoundError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATCH_POLICY_VERSION = "v1.0"

# Maximum allowed patch size in bytes (V1 limit: 1 MiB)
MAX_PATCH_SIZE_BYTES = 1_048_576

# Shell metacharacters that are forbidden in patch content
_SHELL_METACHARACTERS: tuple[str, ...] = (
    "`",
    "$(",
    "${",
    "|",
    ";",
    "&",
    "&&",
    "||",
    ">",
    "<",
    ">>",
    "<<",
    "2>",
    "2>&1",
    "1>&2",
)

# Path escape patterns that indicate directory traversal
_PATH_TRAVERSAL_RE = re.compile(r"(?:^|/)\.\.(?:/|$)")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[a-zA-Z]:)?[/\\]")

# Allowed diff-target paths must be within allowed roots
_ALLOWED_PATH_PREFIXES: tuple[str, ...] = (
    "src/",
    "test/",
    "pom.xml",
    "build.gradle",
    "gradle/",
)

# Forbidden path tokens (redacted deployment IDs, secrets, etc.)
_FORBIDDEN_PATH_TOKENS: tuple[str, ...] = (
    ".env",
    "secrets",
    "credentials",
    "token",
    "password",
    "secret",
    "deployment",
    "model_profile",
    "api_key",
    ".netrc",
)

# Unsafe content patterns
_UNSAFE_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"subprocess\.(call|check_call|Popen|run)"),
    re.compile(r"os\.system"),
    re.compile(r"shutil\.rmtree"),
    re.compile(r"pathlib\.Path\.unlink"),
    re.compile(r"eval\(|exec\("),
    re.compile(r"__import__\(|builtins\.exec"),
    re.compile(r"chmod\s*\(?\s*0o?777"),
    re.compile(r"chown\s+"),
    re.compile(r"rm\s+-rf"),
    re.compile(r"sudo\s+"),
)


class PatchPolicyService:
    """Validates patch content against V1 patch policy rules.

    The service enforces:
    1. No shell escape sequences or metacharacters.
    2. No path traversal or absolute paths outside allowed prefixes.
    3. No oversize patches.
    4. No unapproved patches.
    5. Snapshot is recorded before patch write.
    6. All public output is redacted.
    """

    def __init__(self, unit_of_work_factory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def validate_patch(
        self,
        *,
        command_id: str,
        job_id: str,
        target_path: str,
        patch_content: str,
        patch_size_bytes: int,
        approval_id: str | None = None,
        actor_type: str = "system",
        actor_id: str = "controller",
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> PatchPolicyValidationDto:
        """Validate a patch against all policy rules.

        Returns a validation DTO with approved=True only if all checks pass.
        Validation is recorded as an append-only audit record.
        The actual patch content is never persisted.
        """
        now = utc_now_text()
        target_path_hash = self._hash_path(target_path)

        # 1. Check shell metacharacters in patch target path
        self._check_path_escapes(target_path)

        # 2. Check path traversal and absolute paths
        self._check_path_safety(target_path)

        # 3. Check forbidden path tokens
        self._check_forbidden_path_tokens(target_path)

        # 4. Check patch content for shell metacharacters
        self._check_content_escapes(patch_content)

        # 5. Check oversize
        self._check_oversize(patch_size_bytes)

        # 6. Check approval
        self._check_approval(command_id, approval_id)

        # 7. Check unsafe content patterns
        self._check_unsafe_content(patch_content)

        # --- All checks passed ---
        validation_id = f"ppv-{uuid4().hex}"
        validation_code = "APPROVED"
        reason_code = "policy_pass"
        approved = True
        metacharacter_hits = self._count_metacharacter_hits(patch_content)

        record = V1PatchPolicyValidationRecord(
            validation_id=validation_id,
            command_id=command_id,
            job_id=job_id,
            approved=approved,
            validation_code=validation_code,
            reason_code=reason_code,
            target_path_hash=target_path_hash,
            patch_size_bytes=patch_size_bytes,
            metacharacter_hits=metacharacter_hits,
            policy_version=PATCH_POLICY_VERSION,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        with self._unit_of_work_factory() as uow:
            uow.v1_patch_policy_validations.insert(record)
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                action="patch_policy_validation_recorded",
                payload_json=canonical_json_text(
                    {
                        "validation_id": validation_id,
                        "command_id": command_id,
                        "job_id": job_id,
                        "approved": approved,
                        "validation_code": validation_code,
                        "reason_code": reason_code,
                    }
                ),
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )

        return self._to_validation_dto(record)

    def validate_patch_and_reject(
        self,
        *,
        command_id: str,
        job_id: str,
        target_path: str,
        patch_content: str,
        patch_size_bytes: int,
        rejection_reason: str,
        approval_id: str | None = None,
        actor_type: str = "system",
        actor_id: str = "controller",
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> PatchPolicyValidationDto:
        """Record a rejection without running all checks.

        Used when the caller already knows the patch is invalid
        (e.g., from an earlier pre-check), ensuring the rejection
        is always audited.
        """
        now = utc_now_text()
        target_path_hash = self._hash_path(target_path)
        validation_id = f"ppv-{uuid4().hex}"
        metacharacter_hits = self._count_metacharacter_hits(patch_content)

        record = V1PatchPolicyValidationRecord(
            validation_id=validation_id,
            command_id=command_id,
            job_id=job_id,
            approved=False,
            validation_code="REJECTED",
            reason_code=rejection_reason,
            target_path_hash=target_path_hash,
            patch_size_bytes=patch_size_bytes,
            metacharacter_hits=metacharacter_hits,
            policy_version=PATCH_POLICY_VERSION,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        with self._unit_of_work_factory() as uow:
            uow.v1_patch_policy_validations.insert(record)
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                action="patch_policy_validation_recorded",
                payload_json=canonical_json_text(
                    {
                        "validation_id": validation_id,
                        "command_id": command_id,
                        "job_id": job_id,
                        "approved": False,
                        "validation_code": "REJECTED",
                        "reason_code": rejection_reason,
                    }
                ),
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )

        return self._to_validation_dto(record)

    def get_validation(self, validation_id: str) -> PatchPolicyValidationDto | None:
        """Get a specific patch policy validation record."""
        with self._unit_of_work_factory() as uow:
            record = uow.v1_patch_policy_validations.get(validation_id)
            if record is None:
                return None
            return self._to_validation_dto(record)

    def get_latest_validation_for_command(
        self, command_id: str
    ) -> PatchPolicyValidationDto | None:
        """Get the latest validation record for a command."""
        with self._unit_of_work_factory() as uow:
            record = uow.v1_patch_policy_validations.get_latest_for_command(command_id)
            if record is None:
                return None
            return self._to_validation_dto(record)

    def list_validations_for_command(
        self, command_id: str
    ) -> tuple[PatchPolicyValidationDto, ...]:
        """List all validation records for a command."""
        with self._unit_of_work_factory() as uow:
            records = uow.v1_patch_policy_validations.list_for_command(command_id)
            return tuple(self._to_validation_dto(r) for r in records)

    def record_sandbox_snapshot(
        self,
        *,
        command_id: str,
        job_id: str,
        stage_index: int,
        sandbox_artifact_id: str,
        sandbox_checksum: str,
        actor_type: str = "system",
        actor_id: str = "controller",
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> SandboxSnapshotDto:
        """Record a sandbox snapshot taken before patch application."""
        now = utc_now_text()
        snapshot_id = f"snp-{uuid4().hex}"

        record = V1SandboxSnapshotRecord(
            snapshot_id=snapshot_id,
            command_id=command_id,
            job_id=job_id,
            stage_index=stage_index,
            sandbox_artifact_id=sandbox_artifact_id,
            sandbox_checksum=sandbox_checksum,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=now,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        with self._unit_of_work_factory() as uow:
            uow.v1_sandbox_snapshots.insert(record)
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                action="sandbox_snapshot_recorded",
                payload_json=canonical_json_text(
                    {
                        "snapshot_id": snapshot_id,
                        "command_id": command_id,
                        "job_id": job_id,
                        "stage_index": stage_index,
                        "sandbox_artifact_id": sandbox_artifact_id,
                    }
                ),
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )

        return self._to_snapshot_dto(record)

    def get_sandbox_snapshot_for_command(
        self, command_id: str
    ) -> SandboxSnapshotDto | None:
        """Get the latest sandbox snapshot for a command."""
        with self._unit_of_work_factory() as uow:
            record = uow.v1_sandbox_snapshots.get_for_command(command_id)
            if record is None:
                return None
            return self._to_snapshot_dto(record)

    # ------------------------------------------------------------------
    # Internal validation helpers
    # ------------------------------------------------------------------

    def _check_path_escapes(self, target_path: str) -> None:
        """Reject shell metacharacters in target path."""
        for meta in _SHELL_METACHARACTERS:
            if meta in target_path:
                raise PatchContentEscapeError(
                    f"Target path contains shell metacharacter {meta!r}: "
                    f"{target_path!r}"
                )

    def _check_path_safety(self, target_path: str) -> None:
        """Reject path traversal and absolute paths."""
        if _PATH_TRAVERSAL_RE.search(target_path):
            raise PatchContentEscapeError(
                f"Target path contains path traversal: {target_path!r}"
            )
        if _ABSOLUTE_PATH_RE.match(target_path):
            raise PatchContentMismatchError(
                f"Target path is absolute, not relative: {target_path!r}"
            )
        # Must start with an allowed prefix
        allowed = False
        for prefix in _ALLOWED_PATH_PREFIXES:
            if target_path.startswith(prefix):
                allowed = True
                break
        if not allowed:
            raise PatchContentMismatchError(
                f"Target path {target_path!r} is not in allowed path prefixes"
            )

    def _check_forbidden_path_tokens(self, target_path: str) -> None:
        """Reject paths containing forbidden tokens (secrets, env files, etc.)."""
        lowered = target_path.lower()
        for token in _FORBIDDEN_PATH_TOKENS:
            if token in lowered:
                raise PatchContentMismatchError(
                    f"Target path contains forbidden token {token!r}: {target_path!r}"
                )

    def _check_content_escapes(self, patch_content: str) -> None:
        """Reject shell metacharacters in patch content."""
        for meta in _SHELL_METACHARACTERS:
            if meta in patch_content:
                raise PatchContentEscapeError(
                    f"Patch content contains shell metacharacter {meta!r}"
                )

    def _check_oversize(self, patch_size_bytes: int) -> None:
        """Reject oversize patches."""
        if patch_size_bytes <= 0:
            raise PatchContentOversizeError(
                f"Patch size {patch_size_bytes} must be positive"
            )
        if patch_size_bytes > MAX_PATCH_SIZE_BYTES:
            raise PatchContentOversizeError(
                f"Patch size {patch_size_bytes} exceeds limit {MAX_PATCH_SIZE_BYTES}"
            )

    def _check_approval(self, command_id: str, approval_id: str | None) -> None:
        """Reject unapproved patches.

        In V1, patches must be pre-approved via the privileged action
        approval workflow. This check ensures that an approval_id
        is present.
        """
        if not approval_id:
            raise PatchNotApprovedError(
                f"Patch for command {command_id!r} has no prior approval"
            )

    def _check_unsafe_content(self, patch_content: str) -> None:
        """Reject unsafe content patterns in patch content."""
        for pattern in _UNSAFE_CONTENT_PATTERNS:
            if pattern.search(patch_content):
                raise PatchContentEscapeError(
                    f"Patch content contains unsafe pattern: {pattern.pattern}"
                )

    def _count_metacharacter_hits(self, content: str) -> int:
        """Count shell metacharacter occurrences in content (for audit)."""
        count = 0
        for meta in _SHELL_METACHARACTERS:
            count += content.count(meta)
        return count

    @staticmethod
    def _hash_path(target_path: str) -> str:
        return hashlib.sha256(target_path.encode("utf-8")).hexdigest()

    @staticmethod
    def _to_validation_dto(
        record: V1PatchPolicyValidationRecord,
    ) -> PatchPolicyValidationDto:
        return PatchPolicyValidationDto(
            validation_id=record.validation_id,
            command_id=record.command_id,
            job_id=record.job_id,
            approved=record.approved,
            validation_code=record.validation_code,
            reason_code=record.reason_code,
            target_path_hash=record.target_path_hash,
            patch_size_bytes=record.patch_size_bytes,
            metacharacter_hits=record.metacharacter_hits,
            policy_version=record.policy_version,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            created_at=record.created_at,
            correlation_id=record.correlation_id,
            causation_id=record.causation_id,
        )

    @staticmethod
    def _to_snapshot_dto(
        record: V1SandboxSnapshotRecord,
    ) -> SandboxSnapshotDto:
        return SandboxSnapshotDto(
            snapshot_id=record.snapshot_id,
            command_id=record.command_id,
            job_id=record.job_id,
            stage_index=record.stage_index,
            sandbox_artifact_id=record.sandbox_artifact_id,
            sandbox_checksum=record.sandbox_checksum,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            created_at=record.created_at,
            correlation_id=record.correlation_id,
            causation_id=record.causation_id,
        )


def validate_patch_target_path(target_path: str) -> None:
    """Standalone function to validate a target path without a full DTO.

    Raises PatchPolicyValidationError (or subclass) on failure.
    """
    policy = _StandalonePatchPolicy()
    policy.check_path_escapes(target_path)
    policy.check_path_safety(target_path)
    policy.check_forbidden_path_tokens(target_path)


def validate_patch_size(patch_size_bytes: int) -> None:
    """Standalone function to validate patch size."""
    if patch_size_bytes <= 0:
        raise PatchContentOversizeError(
            f"Patch size {patch_size_bytes} must be positive"
        )
    if patch_size_bytes > MAX_PATCH_SIZE_BYTES:
        raise PatchContentOversizeError(
            f"Patch size {patch_size_bytes} exceeds limit {MAX_PATCH_SIZE_BYTES}"
        )


class _StandalonePatchPolicy:
    """Minimal policy checker for standalone validation functions."""

    def check_path_escapes(self, target_path: str) -> None:
        for meta in _SHELL_METACHARACTERS:
            if meta in target_path:
                raise PatchContentEscapeError(
                    f"Target path contains shell metacharacter {meta!r}: "
                    f"{target_path!r}"
                )

    def check_path_safety(self, target_path: str) -> None:
        if _PATH_TRAVERSAL_RE.search(target_path):
            raise PatchContentEscapeError(
                f"Target path contains path traversal: {target_path!r}"
            )
        if _ABSOLUTE_PATH_RE.match(target_path):
            raise PatchContentMismatchError(
                f"Target path is absolute, not relative: {target_path!r}"
            )
        allowed = False
        for prefix in _ALLOWED_PATH_PREFIXES:
            if target_path.startswith(prefix):
                allowed = True
                break
        if not allowed:
            raise PatchContentMismatchError(
                f"Target path {target_path!r} is not in allowed path prefixes"
            )

    def check_forbidden_path_tokens(self, target_path: str) -> None:
        lowered = target_path.lower()
        for token in _FORBIDDEN_PATH_TOKENS:
            if token in lowered:
                raise PatchContentMismatchError(
                    f"Target path contains forbidden token {token!r}: {target_path!r}"
                )
