"""SQLite repository for v2_chain_attempts durable idempotency table."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.domain.checksums import utc_now_text


@dataclass(frozen=True)
class V2ChainAttemptRecord:
    chain_key: str
    job_id: str
    command_id: str
    context_checksum: str
    chain_kind: str
    status: str
    failure_reason: str | None = None
    invocation_ids_json: str | None = None
    attempt_number: int = 1
    created_at: str = ""
    updated_at: str | None = None


CHAIN_STATES = frozenset({
    "started",
    "main_schema_invalid",
    "main_empty_response",
    "main_provider_failed",
    "reviewer_failed",
    "materialized",
    "retry_requested",
    "revision_requested",
})

RETRYABLE_STATES = frozenset({
    "main_schema_invalid",
    "main_empty_response",
    "main_provider_failed",
    "reviewer_failed",
})

TERMINAL_SUCCESS_STATES = frozenset({
    "materialized",
})


def build_chain_key(
    job_id: str,
    command_id: str,
    context_checksum: str,
    chain_kind: str,
) -> str:
    return f"{job_id}::{command_id}::{context_checksum}::{chain_kind}"


class SqliteV2ChainAttemptRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, record: V2ChainAttemptRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_chain_attempts (
                chain_key, job_id, command_id, context_checksum,
                chain_kind, status, failure_reason,
                invocation_ids_json, attempt_number,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.chain_key,
                record.job_id,
                record.command_id,
                record.context_checksum,
                record.chain_kind,
                record.status,
                record.failure_reason,
                record.invocation_ids_json,
                record.attempt_number,
                record.created_at or utc_now_text(),
                record.updated_at,
            ),
        )

    def get(self, chain_key: str) -> V2ChainAttemptRecord | None:
        row = self._connection.execute(
            "SELECT * FROM v2_chain_attempts WHERE chain_key = ?",
            (chain_key,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def update_status(
        self,
        chain_key: str,
        status: str,
        *,
        failure_reason: str | None = None,
        invocation_ids_json: str | None = None,
        attempt_number: int | None = None,
    ) -> None:
        parts: list[str] = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, utc_now_text()]
        if failure_reason is not None:
            parts.append("failure_reason = ?")
            params.append(failure_reason)
        if invocation_ids_json is not None:
            parts.append("invocation_ids_json = ?")
            params.append(invocation_ids_json)
        if attempt_number is not None:
            parts.append("attempt_number = ?")
            params.append(attempt_number)
        params.append(chain_key)
        self._connection.execute(
            f"UPDATE v2_chain_attempts SET {', '.join(parts)} WHERE chain_key = ?",
            params,
        )

    def list_by_job(self, job_id: str) -> tuple[V2ChainAttemptRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_chain_attempts
               WHERE job_id = ?
               ORDER BY created_at DESC""",
            (job_id,),
        ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def _row_to_record(self, row: sqlite3.Row) -> V2ChainAttemptRecord:
        return V2ChainAttemptRecord(
            chain_key=str(row["chain_key"]),
            job_id=str(row["job_id"]),
            command_id=str(row["command_id"]),
            context_checksum=str(row["context_checksum"]),
            chain_kind=str(row["chain_kind"]),
            status=str(row["status"]),
            failure_reason=str(row["failure_reason"]) if row["failure_reason"] is not None else None,
            invocation_ids_json=str(row["invocation_ids_json"]) if row["invocation_ids_json"] is not None else None,
            attempt_number=int(row["attempt_number"]) if row["attempt_number"] is not None else 1,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
        )
