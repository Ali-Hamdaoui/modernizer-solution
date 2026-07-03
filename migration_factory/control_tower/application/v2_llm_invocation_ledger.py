"""V2 governed LLM invocation ledger — capture point service.

Records every model invocation (proposer, reviewer, fallback) to the
v2_llm_invocations table with role, responsibility, checksums, and
safe deployment aliases. Raw prompts, completions, endpoints, and
API keys are never stored.

This is the capture-point service that PR-G hooks into the existing
model client and repair chains. It does NOT replace the model client
or the repair chain — it observes and records.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.ports import V2LLMInvocationRepository
from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_model_role_config import (
    ModelRoleConfigLoader,
    ModelRoleConfigMissingError,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    V2LLMInvocationRecord,
)


def compute_content_checksum(content: str) -> str:
    """Content-derived SHA-256 checksum."""
    return sha256_canonical_json({"content": content})


def compute_deployment_alias_hash(deployment: str) -> str:
    """Hash a deployment name to a safe opaque identifier."""
    if not deployment:
        return ""
    return hashlib.sha256(deployment.encode("utf-8")).hexdigest()[:16]


def _normalize_role_to_key(role: str) -> str:
    """Map role strings to config keys (main, reviewer, fallback)."""
    normalized = str(role or "").strip().lower()
    if normalized in {"main", "proposer", "primary"}:
        return "main"
    if normalized == "reviewer":
        return "reviewer"
    if normalized == "fallback":
        return "fallback"
    return ""


def safe_provider_alias(role: str = "") -> str:
    """Return a safe provider display label from role config if available."""
    from migration_factory.control_tower.application.v2_model_role_config import (
        ModelRoleConfigLoader,
    )
    role_key = _normalize_role_to_key(role)
    if role_key:
        config = ModelRoleConfigLoader.try_load_role(role_key)
        if config is not None:
            return config.provider_alias
    return "azure_openai"


def safe_deployment_label() -> str:
    """Return a safe public deployment label — never the raw name."""
    return "configured"


def safe_model_display_name(role: str) -> str:
    """Return model display name from role config.

    Uses ModelRoleConfigLoader to resolve the display name from
    AI_MIGRATION_{ROLE}_MODEL_DISPLAY_NAME. Falls back to "configured"
    when no config is found.
    """
    from migration_factory.control_tower.application.v2_model_role_config import (
        ModelRoleConfigLoader,
    )
    role_key = _normalize_role_to_key(role)
    if role_key:
        config = ModelRoleConfigLoader.try_load_role(role_key)
        if config is not None:
            return config.model_display_name
    return "configured"


def deployment_alias_hash_for_role(role: str) -> str:
    """Resolve deployment/model ID for a role and return only its safe hash.

    Uses ModelRoleConfigLoader to get the deployment_or_model_id from
    AI_MIGRATION_{ROLE}_MODEL. Falls back to empty hash when no config found.
    """
    from migration_factory.control_tower.application.v2_model_role_config import (
        ModelRoleConfigLoader,
    )
    role_key = _normalize_role_to_key(role)
    if role_key:
        config = ModelRoleConfigLoader.try_load_role(role_key)
        if config is not None:
            return config.deployment_alias_hash()
    return compute_deployment_alias_hash("")


class V2LLMInvocationLedger:
    """Capture-point service for the governed LLM invocation ledger.

    Usage pattern:
        ledger = V2LLMInvocationLedger(repository)
        inv_id = ledger.start_invocation(job_id="...", role="main", responsibility="repair_proposal")
        # ... model call ...
        ledger.complete_invocation(inv_id, output_checksum="...")
    """

    def __init__(self, repository: V2LLMInvocationRepository) -> None:
        self._repository = repository

    def start_invocation(
        self,
        *,
        job_id: str,
        role: str,
        responsibility: str,
        proposal_id: str | None = None,
        gate_id: str | None = None,
        context_checksum: str | None = None,
        input_checksum: str | None = None,
        schema_name: str | None = None,
    ) -> str:
        """Record the start of a model invocation.

        Returns the invocation_id for later completion/failure update.
        """
        invocation_id = uuid4().hex
        created_at = utc_now_text()
        record = V2LLMInvocationRecord(
            invocation_id=invocation_id,
            job_id=job_id,
            role=role,
            responsibility=responsibility,
            status="started",
            created_at=created_at,
            proposal_id=proposal_id,
            gate_id=gate_id,
            context_checksum=context_checksum,
            input_checksum=input_checksum,
            schema_name=schema_name,
            provider_alias=safe_provider_alias(role),
            deployment_alias_hash=deployment_alias_hash_for_role(role),
        )
        self._repository.save(record)
        return invocation_id

    def complete_invocation(
        self,
        invocation_id: str,
        *,
        output: str | None = None,
        output_checksum: str | None = None,
        redacted_summary: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        fallback_used: bool = False,
    ) -> None:
        """Record successful completion of a model invocation."""
        if output_checksum is None and output is not None:
            output_checksum = compute_content_checksum(output)
        safe_summary = str(redact_model_summary(redacted_summary or ""))[:500] if redacted_summary else None
        self._repository.update_status(
            invocation_id=invocation_id,
            status="fallback" if fallback_used else "completed",
            output_checksum=output_checksum,
            redacted_summary=safe_summary,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            completed_at=utc_now_text(),
            fallback_used=1 if fallback_used else 0,
        )

    def fail_invocation(
        self,
        invocation_id: str,
        *,
        redacted_error: str | None = None,
        redacted_summary: str | None = None,
        latency_ms: int | None = None,
        fallback_used: bool = False,
    ) -> None:
        """Record failure of a model invocation."""
        safe_error = str(redact_model_summary(redacted_error or ""))[:500] if redacted_error else None
        safe_summary = str(redact_model_summary(redacted_summary or ""))[:500] if redacted_summary else None
        failure_status = "failed"
        combined = f"{safe_error or ''} {safe_summary or ''}".lower()
        if "schema_invalid" in combined or "schema validation" in combined:
            failure_status = "schema_invalid"
        self._repository.update_status(
            invocation_id=invocation_id,
            status="fallback" if fallback_used else failure_status,
            redacted_error=safe_error,
            redacted_summary=safe_summary,
            latency_ms=latency_ms,
            completed_at=utc_now_text(),
            fallback_used=1 if fallback_used else 0,
        )

    def get_invocation(self, invocation_id: str) -> V2LLMInvocationRecord | None:
        return self._repository.get(invocation_id)

    def list_by_job(self, job_id: str) -> tuple[V2LLMInvocationRecord, ...]:
        return self._repository.list_by_job(job_id)

    def list_by_proposal(self, proposal_id: str) -> tuple[V2LLMInvocationRecord, ...]:
        return self._repository.list_by_proposal(proposal_id)

    @staticmethod
    def record_to_dto(record: V2LLMInvocationRecord) -> dict[str, Any]:
        """Convert a ledger record to a safe API response dict.

        No raw prompts, completions, endpoints, or API keys are included.
        """
        from migration_factory.control_tower.application.dto import LlmInvocationDto

        dto = LlmInvocationDto(
            invocation_id=record.invocation_id,
            job_id=record.job_id,
            role=record.role,
            responsibility=record.responsibility,
            status=record.status,
            created_at=record.created_at,
            proposal_id=record.proposal_id,
            gate_id=record.gate_id,
            provider_alias=record.provider_alias,
            model_display_name=safe_model_display_name(record.role),
            deployment_alias_hash=record.deployment_alias_hash,
            context_checksum=record.context_checksum,
            input_checksum=record.input_checksum,
            output_checksum=record.output_checksum,
            schema_name=record.schema_name,
            fallback_used=bool(record.fallback_used),
            redacted_error=record.redacted_error,
            redacted_summary=record.redacted_summary,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            total_tokens=record.total_tokens,
            latency_ms=record.latency_ms,
            completed_at=record.completed_at,
        )
        reason_code = _derive_invocation_reason_code(record)
        status = dto.status
        if status == "completed" and reason_code in {"main_schema_invalid", "proposer_schema_invalid", "reviewer_schema_invalid"}:
            status = "schema_invalid"
        return {
            "invocation_id": dto.invocation_id,
            "job_id": dto.job_id,
            "role": dto.role,
            "responsibility": dto.responsibility,
            "status": status,
            "reason_code": reason_code,
            "proposal_id": dto.proposal_id,
            "gate_id": dto.gate_id,
            "provider_alias": dto.provider_alias,
            "model_display_name": dto.model_display_name,
            "deployment_alias_hash": dto.deployment_alias_hash,
            "context_checksum": dto.context_checksum,
            "input_checksum": dto.input_checksum,
            "output_checksum": dto.output_checksum,
            "schema_name": dto.schema_name,
            "fallback_used": dto.fallback_used,
            "redacted_error": dto.redacted_error,
            "redacted_summary": dto.redacted_summary,
            "prompt_tokens": dto.prompt_tokens,
            "completion_tokens": dto.completion_tokens,
            "total_tokens": dto.total_tokens,
            "latency_ms": dto.latency_ms,
            "created_at": dto.created_at,
            "completed_at": dto.completed_at,
        }

    @staticmethod
    def forbidden_fields_exposed(dto_dict: dict[str, Any]) -> list[str]:
        """Check a response dict for forbidden fields.

        Checks for field names that would leak raw prompts, completions,
        endpoints, API keys, or secrets. Token count field names
        (prompt_tokens, completion_tokens) are explicitly allowed.
        Returns a list of forbidden field names found.
        """
        allowed_prefixes = ("prompt_tokens", "completion_tokens")
        forbidden = []
        key_lower = {k.lower(): k for k in dto_dict}
        for field in ("prompt", "completion", "endpoint", "api_key", "api-key", "apikey", "secret", "raw_content"):
            for pattern in (field, field.replace("-", "_"), field.replace("_", "")):
                for k in key_lower:
                    if pattern in k:
                        is_allowed = any(k.startswith(a) for a in allowed_prefixes)
                        if not is_allowed:
                            forbidden.append(key_lower[k])
        if dto_dict.get("deployment_alias_hash") and len(str(dto_dict["deployment_alias_hash"])) > 64:
            forbidden.append("deployment_alias_hash_too_long")
        return list(set(forbidden))


def _derive_invocation_reason_code(record: V2LLMInvocationRecord) -> str | None:
    combined = " ".join(
        str(value or "").lower()
        for value in (
            record.status,
            record.redacted_error,
            record.redacted_summary,
            record.schema_name,
        )
    )
    role = str(record.role or "").strip().lower()
    responsibility = str(record.responsibility or "").strip().lower()
    is_main = role in {"main", "proposer", "primary"} or responsibility == "repair_proposal"
    is_reviewer = role == "reviewer" or responsibility == "repair_review"
    if "reviewer_schema_invalid" in combined:
        return "reviewer_schema_invalid"
    if "proposer_schema_invalid" in combined:
        return "proposer_schema_invalid"
    if "main_schema_invalid" in combined:
        return "main_schema_invalid"
    if ("schema_invalid" in combined or "schema validation" in combined) and is_main:
        return "proposer_schema_invalid"
    if ("schema_invalid" in combined or "schema validation" in combined) and is_reviewer:
        return "reviewer_schema_invalid"
    return None
