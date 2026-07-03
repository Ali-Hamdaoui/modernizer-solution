from __future__ import annotations

import sqlite3
from pathlib import Path

from migration_factory.control_tower.application.v2_repair_strategy_packet import create_repair_strategy_packet
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_strategy_repository import (
    SqliteV2RepairStrategyRepository,
)

from .test_v2_repair_strategy_packet import _powermock_classification, _powermock_evidence


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "strategy.sqlite3"), isolation_level=None)
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


def test_same_checksum_does_not_duplicate_and_identity_is_stable(tmp_path: Path) -> None:
    repo = SqliteV2RepairStrategyRepository(_conn(tmp_path))
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=2,
        classification=_powermock_classification(),
        stage_evidence=_powermock_evidence(),
    )

    first = repo.save_strategy_packet(packet)
    second = repo.save_strategy_packet(dict(packet))

    assert first["strategy_id"] == second["strategy_id"]
    assert first["version"] == 1
    assert repo.history_for_stage("job-r9", 2) == [first]


def test_changed_checksum_creates_next_version(tmp_path: Path) -> None:
    repo = SqliteV2RepairStrategyRepository(_conn(tmp_path))
    packet = create_repair_strategy_packet(
        job_id="job-r9",
        stage_index=2,
        classification=_powermock_classification(),
        stage_evidence=_powermock_evidence(),
    )
    first = repo.save_strategy_packet(packet)
    changed = dict(packet)
    changed["recommended_strategy"] = "Engineer-reviewed alternate strategy."

    second = repo.save_strategy_packet(changed)

    assert first["strategy_base_id"] == second["strategy_base_id"]
    assert second["strategy_id"].endswith("-v2")
    assert second["version"] == 2
    assert second["strategy_checksum"] != first["strategy_checksum"]
    assert repo.latest_for_stage("job-r9", 2)["strategy_id"] == second["strategy_id"]
    assert repo.get_by_id("job-r9", first["strategy_id"])["version"] == 1
