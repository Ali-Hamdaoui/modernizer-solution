"""SQLite store for immutable repair strategy packets."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from migration_factory.control_tower.application.v2_repair_strategy_packet import (
    repair_strategy_packet_checksum,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text


class SqliteV2RepairStrategyRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save_strategy_packet(self, packet: dict[str, Any]) -> dict[str, Any]:
        clean = dict(packet)
        job_id = str(clean.get("job_id") or "")
        stage_index = int(clean.get("stage_index") or 0)
        family = str(clean.get("family") or "UNKNOWN_FAILURE")
        evidence_checksum = str(clean.get("evidence_pack_checksum") or "")
        if not job_id or stage_index <= 0:
            raise ValueError("strategy_packet_job_stage_required")

        base_id = str(clean.get("strategy_base_id") or "") or self._base_id(
            job_id=job_id,
            stage_index=stage_index,
            family=family,
            evidence_pack_checksum=evidence_checksum,
        )
        clean["strategy_base_id"] = base_id
        clean["strategy_checksum"] = repair_strategy_packet_checksum(clean)
        existing = self._connection.execute(
            """SELECT packet_json
               FROM v2_repair_strategy_packets
               WHERE strategy_base_id = ? AND strategy_checksum = ?
               LIMIT 1""",
            (base_id, clean["strategy_checksum"]),
        ).fetchone()
        if existing is not None:
            return json.loads(str(existing["packet_json"]))

        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM v2_repair_strategy_packets WHERE strategy_base_id = ?",
            (base_id,),
        ).fetchone()
        version = int(row["max_version"] or 0) + 1 if row is not None else 1
        strategy_id = f"{base_id}-v{version}"
        now = utc_now_text()
        clean.update({
            "strategy_id": strategy_id,
            "version": version,
            "created_at": now,
            "updated_at": now,
        })
        clean["strategy_checksum"] = repair_strategy_packet_checksum(clean)
        packet_json = json.dumps(clean, sort_keys=True, separators=(",", ":"))
        self._connection.execute(
            """INSERT INTO v2_repair_strategy_packets (
                strategy_id, strategy_base_id, job_id, stage_index, family,
                risk_level, strategy_status, strategy_checksum,
                evidence_pack_checksum, classification_status, version,
                packet_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy_id,
                base_id,
                job_id,
                stage_index,
                family,
                str(clean.get("risk_level") or ""),
                str(clean.get("strategy_status") or ""),
                clean["strategy_checksum"],
                evidence_checksum,
                str(clean.get("classification_status") or ""),
                version,
                packet_json,
                now,
                now,
            ),
        )
        return clean

    def latest_for_job(self, job_id: str) -> dict[str, Any] | None:
        return self._one(
            """SELECT packet_json FROM v2_repair_strategy_packets
               WHERE job_id = ?
               ORDER BY created_at DESC, version DESC, strategy_id DESC
               LIMIT 1""",
            (job_id,),
        )

    def latest_for_stage(self, job_id: str, stage_index: int) -> dict[str, Any] | None:
        return self._one(
            """SELECT packet_json FROM v2_repair_strategy_packets
               WHERE job_id = ? AND stage_index = ?
               ORDER BY created_at DESC, version DESC, strategy_id DESC
               LIMIT 1""",
            (job_id, int(stage_index)),
        )

    def history_for_job(self, job_id: str) -> list[dict[str, Any]]:
        return self._many(
            """SELECT packet_json FROM v2_repair_strategy_packets
               WHERE job_id = ?
               ORDER BY created_at DESC, version DESC, strategy_id DESC""",
            (job_id,),
        )

    def history_for_stage(self, job_id: str, stage_index: int) -> list[dict[str, Any]]:
        return self._many(
            """SELECT packet_json FROM v2_repair_strategy_packets
               WHERE job_id = ? AND stage_index = ?
               ORDER BY version DESC, created_at DESC, strategy_id DESC""",
            (job_id, int(stage_index)),
        )

    def get_by_id(self, job_id: str, strategy_id: str) -> dict[str, Any] | None:
        return self._one(
            """SELECT packet_json FROM v2_repair_strategy_packets
               WHERE job_id = ? AND strategy_id = ?
               LIMIT 1""",
            (job_id, strategy_id),
        )

    def _one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        row = self._connection.execute(sql, params).fetchone()
        if row is None:
            return None
        return json.loads(str(row["packet_json"]))

    def _many(self, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return [json.loads(str(row["packet_json"])) for row in self._connection.execute(sql, params).fetchall()]

    @staticmethod
    def _base_id(*, job_id: str, stage_index: int, family: str, evidence_pack_checksum: str) -> str:
        base_hash = sha256_canonical_json({
            "job_id": job_id,
            "stage_index": stage_index,
            "family": family,
            "evidence_pack_checksum": evidence_pack_checksum,
        })[:16]
        return f"repair-strategy-{base_hash}"
