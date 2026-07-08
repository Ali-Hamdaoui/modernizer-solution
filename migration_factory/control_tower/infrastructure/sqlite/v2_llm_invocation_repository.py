"""SQLite repository for v2_llm_invocations governed ledger table."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class V2LLMInvocationRecord:
    invocation_id: str
    job_id: str
    role: str
    responsibility: str
    status: str
    created_at: str
    proposal_id: str | None = None
    gate_id: str | None = None
    provider_alias: str | None = None
    deployment_alias_hash: str | None = None
    context_checksum: str | None = None
    input_checksum: str | None = None
    output_checksum: str | None = None
    schema_name: str | None = None
    fallback_used: int = 0
    redacted_error: str | None = None
    redacted_summary: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int | None = None
    completed_at: str | None = None


class SqliteV2LLMInvocationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, record: V2LLMInvocationRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_llm_invocations (
                invocation_id, job_id, proposal_id, gate_id,
                role, responsibility, provider_alias, deployment_alias_hash,
                context_checksum, input_checksum, output_checksum,
                schema_name, status, fallback_used,
                redacted_error, redacted_summary,
                prompt_tokens, completion_tokens, total_tokens,
                latency_ms, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.invocation_id,
                record.job_id,
                record.proposal_id,
                record.gate_id,
                record.role,
                record.responsibility,
                record.provider_alias,
                record.deployment_alias_hash,
                record.context_checksum,
                record.input_checksum,
                record.output_checksum,
                record.schema_name,
                record.status,
                record.fallback_used,
                record.redacted_error,
                record.redacted_summary,
                record.prompt_tokens,
                record.completion_tokens,
                record.total_tokens,
                record.latency_ms,
                record.created_at,
                record.completed_at,
            ),
        )

    def update_status(
        self,
        invocation_id: str,
        status: str,
        *,
        output_checksum: str | None = None,
        redacted_error: str | None = None,
        redacted_summary: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | None = None,
        completed_at: str | None = None,
        fallback_used: int | None = None,
    ) -> None:
        parts: list[str] = ["status = ?"]
        params: list[Any] = [status]
        if output_checksum is not None:
            parts.append("output_checksum = ?")
            params.append(output_checksum)
        if redacted_error is not None:
            parts.append("redacted_error = ?")
            params.append(redacted_error)
        if redacted_summary is not None:
            parts.append("redacted_summary = ?")
            params.append(redacted_summary)
        if prompt_tokens is not None:
            parts.append("prompt_tokens = ?")
            params.append(prompt_tokens)
        if completion_tokens is not None:
            parts.append("completion_tokens = ?")
            params.append(completion_tokens)
        if total_tokens is not None:
            parts.append("total_tokens = ?")
            params.append(total_tokens)
        if latency_ms is not None:
            parts.append("latency_ms = ?")
            params.append(latency_ms)
        if completed_at is not None:
            parts.append("completed_at = ?")
            params.append(completed_at)
        if fallback_used is not None:
            parts.append("fallback_used = ?")
            params.append(fallback_used)
        params.append(invocation_id)
        self._connection.execute(
            f"UPDATE v2_llm_invocations SET {', '.join(parts)} WHERE invocation_id = ?",
            params,
        )

    def get(self, invocation_id: str) -> V2LLMInvocationRecord | None:
        row = self._connection.execute(
            "SELECT * FROM v2_llm_invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list_by_job(self, job_id: str) -> tuple[V2LLMInvocationRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_llm_invocations
               WHERE job_id = ?
               ORDER BY created_at DESC""",
            (job_id,),
        ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def list_by_proposal(self, proposal_id: str) -> tuple[V2LLMInvocationRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_llm_invocations
               WHERE proposal_id = ?
               ORDER BY created_at DESC""",
            (proposal_id,),
        ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def _row_to_record(self, row: sqlite3.Row) -> V2LLMInvocationRecord:
        return V2LLMInvocationRecord(
            invocation_id=str(row["invocation_id"]),
            job_id=str(row["job_id"]),
            proposal_id=str(row["proposal_id"]) if row["proposal_id"] is not None else None,
            gate_id=str(row["gate_id"]) if row["gate_id"] is not None else None,
            role=str(row["role"]),
            responsibility=str(row["responsibility"]),
            provider_alias=str(row["provider_alias"]) if row["provider_alias"] is not None else None,
            deployment_alias_hash=str(row["deployment_alias_hash"]) if row["deployment_alias_hash"] is not None else None,
            context_checksum=str(row["context_checksum"]) if row["context_checksum"] is not None else None,
            input_checksum=str(row["input_checksum"]) if row["input_checksum"] is not None else None,
            output_checksum=str(row["output_checksum"]) if row["output_checksum"] is not None else None,
            schema_name=str(row["schema_name"]) if row["schema_name"] is not None else None,
            status=str(row["status"]),
            fallback_used=int(row["fallback_used"]) if row["fallback_used"] is not None else 0,
            redacted_error=str(row["redacted_error"]) if row["redacted_error"] is not None else None,
            redacted_summary=str(row["redacted_summary"]) if row["redacted_summary"] is not None else None,
            prompt_tokens=int(row["prompt_tokens"]) if row["prompt_tokens"] is not None else None,
            completion_tokens=int(row["completion_tokens"]) if row["completion_tokens"] is not None else None,
            total_tokens=int(row["total_tokens"]) if row["total_tokens"] is not None else None,
            latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
            created_at=str(row["created_at"]),
            completed_at=str(row["completed_at"]) if row["completed_at"] is not None else None,
        )
