"""V1-14A deterministic repair classification and fake proposal recording."""

from __future__ import annotations

import re
from uuid import uuid4

from migration_factory.control_tower.application.dto import (
    FakeRepairProposalDto,
    RepairAttemptDto,
    RepairClassificationDto,
    RepairStatusDto,
)
from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.domain.checksums import canonical_json_text, sha256_canonical_json, utc_now_text
from migration_factory.control_tower.domain.commands import CommandState
from migration_factory.control_tower.domain.entities import (
    V1FakeRepairProposalRecord,
    V1RepairClassificationRecord,
)
from migration_factory.control_tower.domain.errors import (
    NotFoundError,
    RepairAttemptLimitExceededError,
    RepairClassificationError,
    RepairProposalValidationError,
)


_REPAIRABLE_IMPORT_PATTERNS: tuple[str, ...] = (
    "importerror",
    "modulenotfounderror",
    "cannot find symbol",
    "package does not exist",
    "no module named",
    "unresolved import",
)
_REPAIRABLE_COMPILE_PATTERNS: tuple[str, ...] = (
    "compilation failure",
    "compile error",
    "failed to compile",
    "syntaxerror",
    "javac",
)
_REPAIRABLE_TEST_PATTERNS: tuple[str, ...] = (
    "assertionerror",
    "tests failed",
    "test failure",
    "pytest",
    "junit",
    "expected:",
    "actual:",
)
_NOT_REPAIRABLE_POLICY_PATTERNS: tuple[str, ...] = (
    "policy violation",
    "approval required",
    "forbidden",
    "not allowed",
    "unsupported",
    "boot 4",
)
_NOT_REPAIRABLE_INFRA_PATTERNS: tuple[str, ...] = (
    "timed out",
    "timeout",
    "connection reset",
    "dns",
    "network is unreachable",
    "no space left",
    "out of memory",
    "permission denied",
    "access is denied",
    "controller ownership",
    "busy_timeout",
)
_PATCH_MARKERS: tuple[str, ...] = (
    "diff --git",
    "@@",
    "*** begin patch",
    "*** update file:",
    "*** add file:",
    "```patch",
)
_COMMAND_LINE_RE = re.compile(
    r"\b(?:mvn(?:w)?|gradle|bash|sh|cmd(?:\.exe)?|powershell(?:\.exe)?|pwsh|java)\b[^\r\n]*",
    re.IGNORECASE,
)
_STACK_TRACE_RE = re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE)


class RepairService:
    def __init__(self, unit_of_work_factory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def classify_failed_command(
        self,
        *,
        command_id: str,
        evidence_kind: str,
        failure_summary: str,
        actor_type: str,
        actor_id: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> RepairClassificationDto:
        cleaned_kind = evidence_kind.strip().lower() or "command_failure"
        raw_summary = failure_summary.strip()
        if not raw_summary:
            raise RepairClassificationError("failure_summary must not be empty")
        redacted_summary = redact_model_summary(raw_summary)
        public_summary = _sanitize_public_summary(redacted_summary)

        with self._unit_of_work_factory() as uow:
            command = uow.command_executions.get(command_id)
            if command is None:
                raise NotFoundError("command execution", command_id)
            _ensure_command_classifiable(command.status)
            evidence_checksum = sha256_canonical_json(
                {
                    "command_status": command.status.value,
                    "evidence_kind": cleaned_kind,
                    "failure_summary": public_summary,
                    "operation": command.operation,
                }
            )
            existing = uow.v1_repair_classifications.get_by_command_and_checksum(
                command_id,
                evidence_checksum,
            )
            if existing is not None:
                return self._to_classification_dto(existing)

            classification_code, reason_code, repairable, attempt_limit = _classify_repairability(
                command.status,
                redacted_summary,
            )
            record = V1RepairClassificationRecord(
                classification_id=f"repair-{uuid4().hex}",
                command_id=command.command_id,
                job_id=command.job_id,
                command_status=command.status.value,
                evidence_kind=cleaned_kind,
                evidence_summary=public_summary,
                evidence_checksum=evidence_checksum,
                classification_code=classification_code,
                reason_code=reason_code,
                repairable=repairable,
                attempt_limit=attempt_limit,
                actor_type=actor_type,
                actor_id=actor_id,
                created_at=utc_now_text(),
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            uow.v1_repair_classifications.insert(record)
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                action="repair_classification_recorded",
                payload_json=canonical_json_text(
                    {
                        "classification_id": record.classification_id,
                        "command_id": record.command_id,
                        "job_id": record.job_id,
                        "classification_code": record.classification_code,
                        "reason_code": record.reason_code,
                        "evidence_checksum": record.evidence_checksum,
                    }
                ),
                created_at=record.created_at,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        return self._to_classification_dto(record)

    def record_fake_repair_proposal(
        self,
        *,
        command_id: str,
        proposal_summary: str,
        actor_type: str,
        actor_id: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> FakeRepairProposalDto:
        raw_summary = proposal_summary.strip()
        _validate_fake_proposal_summary(raw_summary)
        public_summary = _sanitize_public_summary(redact_model_summary(raw_summary))
        now = utc_now_text()

        with self._unit_of_work_factory() as uow:
            command = uow.command_executions.get(command_id)
            if command is None:
                raise NotFoundError("command execution", command_id)
            classification = uow.v1_repair_classifications.get_latest_for_command(command_id)
            if classification is None:
                raise RepairClassificationError(
                    f"Command {command_id!r} has no repair classification"
                )
            if not classification.repairable:
                raise RepairClassificationError(
                    f"Command {command_id!r} is not repairable"
                )

            existing_proposals = uow.v1_fake_repair_proposals.list_for_classification(
                classification.classification_id
            )
            proposal_checksum = sha256_canonical_json(
                {
                    "classification_id": classification.classification_id,
                    "proposal_summary": public_summary,
                }
            )
            existing = uow.v1_fake_repair_proposals.get_for_classification_and_checksum(
                classification.classification_id,
                proposal_checksum,
            )
            if existing is not None:
                return self._to_proposal_dto(existing)
            if len(existing_proposals) >= classification.attempt_limit:
                raise RepairAttemptLimitExceededError(command_id, classification.attempt_limit)

            record = V1FakeRepairProposalRecord(
                proposal_id=f"fpr-{uuid4().hex}",
                classification_id=classification.classification_id,
                command_id=classification.command_id,
                job_id=classification.job_id,
                proposal_order=len(existing_proposals) + 1,
                proposal_summary=public_summary,
                proposal_checksum=proposal_checksum,
                actor_type=actor_type,
                actor_id=actor_id,
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            uow.v1_fake_repair_proposals.insert(record)
            uow.audit_records.append_global_audit(
                audit_id=uuid4().hex,
                actor_type=actor_type,
                actor_id=actor_id,
                action="fake_repair_proposal_recorded",
                payload_json=canonical_json_text(
                    {
                        "proposal_id": record.proposal_id,
                        "classification_id": record.classification_id,
                        "command_id": record.command_id,
                        "proposal_order": record.proposal_order,
                        "proposal_checksum": record.proposal_checksum,
                    }
                ),
                created_at=now,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
        return self._to_proposal_dto(record)

    def get_repair_status(self, command_id: str) -> RepairStatusDto:
        with self._unit_of_work_factory() as uow:
            command = uow.command_executions.get(command_id)
            if command is None:
                raise NotFoundError("command execution", command_id)
            classification = uow.v1_repair_classifications.get_latest_for_command(command_id)
            if classification is None:
                return RepairStatusDto(
                    command_id=command.command_id,
                    job_id=command.job_id,
                    command_status=command.status.value,
                    classification=None,
                    attempts_used=0,
                    proposal_count=0,
                    attempt_limit=0,
                    remaining_attempts=0,
                    eligible_for_fake_repair=False,
                    proposals=(),
                    attempts=(),
                )
            proposals = tuple(
                self._to_proposal_dto(item)
                for item in uow.v1_fake_repair_proposals.list_for_classification(
                    classification.classification_id
                )
            )
        attempts = tuple(self._proposal_to_attempt_dto(item) for item in proposals)
        proposal_count = len(proposals)
        remaining_attempts = max(0, classification.attempt_limit - proposal_count)
        return RepairStatusDto(
            command_id=classification.command_id,
            job_id=classification.job_id,
            command_status=classification.command_status,
            classification=self._to_classification_dto(classification),
            attempts_used=proposal_count,
            proposal_count=proposal_count,
            attempt_limit=classification.attempt_limit,
            remaining_attempts=remaining_attempts,
            eligible_for_fake_repair=classification.repairable and remaining_attempts > 0,
            proposals=proposals,
            attempts=attempts,
        )

    def record_repair_attempt(
        self,
        *,
        command_id: str,
        attempt_summary: str,
        actor_type: str,
        actor_id: str,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ) -> RepairAttemptDto:
        proposal = self.record_fake_repair_proposal(
            command_id=command_id,
            proposal_summary=attempt_summary,
            actor_type=actor_type,
            actor_id=actor_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        return self._proposal_to_attempt_dto(proposal)

    def list_repair_attempts(self, command_id: str) -> tuple[RepairAttemptDto, ...]:
        status = self.get_repair_status(command_id)
        return status.attempts

    def _to_classification_dto(
        self,
        record: V1RepairClassificationRecord,
    ) -> RepairClassificationDto:
        return RepairClassificationDto(
            classification_id=record.classification_id,
            command_id=record.command_id,
            job_id=record.job_id,
            command_status=record.command_status,
            evidence_kind=record.evidence_kind,
            evidence_summary=record.evidence_summary,
            evidence_checksum=record.evidence_checksum,
            classification_code=record.classification_code,
            reason_code=record.reason_code,
            repairable=record.repairable,
            attempt_limit=record.attempt_limit,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            created_at=record.created_at,
        )

    def _to_proposal_dto(self, record: V1FakeRepairProposalRecord) -> FakeRepairProposalDto:
        return FakeRepairProposalDto(
            proposal_id=record.proposal_id,
            classification_id=record.classification_id,
            command_id=record.command_id,
            job_id=record.job_id,
            proposal_order=record.proposal_order,
            proposal_summary=record.proposal_summary,
            proposal_checksum=record.proposal_checksum,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            created_at=record.created_at,
        )

    def _proposal_to_attempt_dto(
        self,
        proposal: FakeRepairProposalDto | V1FakeRepairProposalRecord,
    ) -> RepairAttemptDto:
        proposal_id = proposal.proposal_id
        classification_id = proposal.classification_id
        command_id = proposal.command_id
        job_id = proposal.job_id
        proposal_order = proposal.proposal_order
        proposal_summary = proposal.proposal_summary
        proposal_checksum = proposal.proposal_checksum
        actor_type = proposal.actor_type
        actor_id = proposal.actor_id
        created_at = proposal.created_at
        return RepairAttemptDto(
            attempt_id=proposal_id,
            classification_id=classification_id,
            command_id=command_id,
            job_id=job_id,
            attempt_order=proposal_order,
            attempt_status="recorded",
            attempt_summary=proposal_summary,
            attempt_checksum=proposal_checksum,
            actor_type=actor_type,
            actor_id=actor_id,
            created_at=created_at,
        )


def _ensure_command_classifiable(status: CommandState) -> None:
    if status not in {CommandState.FAILED, CommandState.TIMED_OUT, CommandState.CANCELLED}:
        raise RepairClassificationError(
            f"Command status {status.value!r} is not classifiable for repair"
        )


def _classify_repairability(
    status: CommandState,
    summary: str,
) -> tuple[str, str, bool, int]:
    lowered = summary.lower()
    if status in {CommandState.TIMED_OUT, CommandState.CANCELLED}:
        return ("not_repairable_infrastructure", "infrastructure_timeout_or_cancelled", False, 0)
    if any(token in lowered for token in _NOT_REPAIRABLE_POLICY_PATTERNS):
        return ("not_repairable_policy", "policy_violation_detected", False, 0)
    if any(token in lowered for token in _NOT_REPAIRABLE_INFRA_PATTERNS):
        return ("not_repairable_infrastructure", "infrastructure_failure_detected", False, 0)
    if any(token in lowered for token in _REPAIRABLE_IMPORT_PATTERNS):
        return ("repairable_dependency_or_import", "dependency_import_missing", True, 2)
    if any(token in lowered for token in _REPAIRABLE_COMPILE_PATTERNS):
        return ("repairable_compile_error", "compile_error_detected", True, 2)
    if any(token in lowered for token in _REPAIRABLE_TEST_PATTERNS):
        return ("repairable_test_failure", "test_failure_detected", True, 1)
    return ("not_repairable_unknown", "unknown_failure_signature", False, 0)


def _sanitize_public_summary(summary: str) -> str:
    sanitized = _COMMAND_LINE_RE.sub("[redacted-command]", summary)
    sanitized = _STACK_TRACE_RE.sub("[redacted-stack-trace]", sanitized)
    return sanitized.strip()


def _validate_fake_proposal_summary(summary: str) -> None:
    if not summary:
        raise RepairProposalValidationError("proposal_summary must not be empty")
    lowered = summary.lower()
    if any(marker in lowered for marker in _PATCH_MARKERS):
        raise RepairProposalValidationError("proposal_summary must not contain patch content")
    if redact_model_summary(summary) != summary:
        raise RepairProposalValidationError(
            "proposal_summary contains unsafe raw content that must be redacted"
        )
