"""SQLite repository for persisted V2 failure diagnoses."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class V2FailureDiagnosisPersistedRecord:
    diagnosis_id: str
    job_id: str
    stage_index: int
    command_id: str
    event_type: str
    failure_type: str
    likely_root_cause: str
    confidence: str
    recommended_fix_type: str
    affected_paths_json: str
    validation_plan_json: str
    evidence_json: str
    missing_artifacts_json: str
    context_pack_checksum: str
    evidence_pack_checksum: str
    diagnosis_checksum: str
    redaction_status: str
    created_at: str


class SqliteV2FailureDiagnosisRepository:
    """Append-only repository for deterministic V2 failure diagnoses."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_diagnosis(self, record: V2FailureDiagnosisPersistedRecord) -> None:
        self._connection.execute(
            """INSERT INTO v2_failure_diagnoses (
                diagnosis_id, job_id, stage_index, command_id, event_type,
                failure_type, likely_root_cause, confidence, recommended_fix_type,
                affected_paths_json, validation_plan_json, evidence_json,
                missing_artifacts_json, context_pack_checksum, evidence_pack_checksum,
                diagnosis_checksum, redaction_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.diagnosis_id,
                record.job_id,
                record.stage_index,
                record.command_id,
                record.event_type,
                record.failure_type,
                record.likely_root_cause,
                record.confidence,
                record.recommended_fix_type,
                record.affected_paths_json,
                record.validation_plan_json,
                record.evidence_json,
                record.missing_artifacts_json,
                record.context_pack_checksum,
                record.evidence_pack_checksum,
                record.diagnosis_checksum,
                record.redaction_status,
                record.created_at,
            ),
        )

    def get_by_id(self, diagnosis_id: str) -> V2FailureDiagnosisPersistedRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_failure_diagnoses
               WHERE diagnosis_id = ?
               LIMIT 1""",
            (diagnosis_id,),
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def get_by_command_and_event(
        self,
        command_id: str,
        event_type: str,
    ) -> V2FailureDiagnosisPersistedRecord | None:
        row = self._connection.execute(
            """SELECT * FROM v2_failure_diagnoses
               WHERE command_id = ? AND event_type = ?
               LIMIT 1""",
            (command_id, event_type),
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def get_latest_for_job(
        self,
        job_id: str,
        *,
        stage_index: int | None = None,
    ) -> V2FailureDiagnosisPersistedRecord | None:
        if stage_index is None:
            row = self._connection.execute(
                """SELECT * FROM v2_failure_diagnoses
                   WHERE job_id = ?
                   ORDER BY created_at DESC, diagnosis_id DESC
                   LIMIT 1""",
                (job_id,),
            ).fetchone()
            return self._row_to_record(row) if row is not None else None
        row = self._connection.execute(
            """SELECT * FROM v2_failure_diagnoses
               WHERE job_id = ? AND stage_index = ?
               ORDER BY created_at DESC, diagnosis_id DESC
               LIMIT 1""",
            (job_id, stage_index),
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_for_job(self, job_id: str) -> tuple[V2FailureDiagnosisPersistedRecord, ...]:
        rows = self._connection.execute(
            """SELECT * FROM v2_failure_diagnoses
               WHERE job_id = ?
               ORDER BY created_at DESC, diagnosis_id DESC""",
            (job_id,),
        ).fetchall()
        return tuple(self._row_to_record(row) for row in rows)

    def _row_to_record(self, row: sqlite3.Row) -> V2FailureDiagnosisPersistedRecord:
        return V2FailureDiagnosisPersistedRecord(
            diagnosis_id=str(row["diagnosis_id"]),
            job_id=str(row["job_id"]),
            stage_index=int(row["stage_index"]),
            command_id=str(row["command_id"]),
            event_type=str(row["event_type"]),
            failure_type=str(row["failure_type"]),
            likely_root_cause=str(row["likely_root_cause"]),
            confidence=str(row["confidence"]),
            recommended_fix_type=str(row["recommended_fix_type"]),
            affected_paths_json=str(row["affected_paths_json"]),
            validation_plan_json=str(row["validation_plan_json"]),
            evidence_json=str(row["evidence_json"]),
            missing_artifacts_json=str(row["missing_artifacts_json"]),
            context_pack_checksum=str(row["context_pack_checksum"]),
            evidence_pack_checksum=str(row["evidence_pack_checksum"]),
            diagnosis_checksum=str(row["diagnosis_checksum"]),
            redaction_status=str(row["redaction_status"]),
            created_at=str(row["created_at"]),
        )
