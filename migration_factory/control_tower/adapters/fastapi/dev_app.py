"""Local ASGI bootstrap for manual Control Tower diagnostic testing.

Sets ``CONTROL_TOWER_DEV_MODE=1`` so the migration runner auto-resets the
local SQLite database on checksum mismatch (e.g. after a branch pull that
changed migration files).  In production this flag is absent and any
checksum mismatch is a hard crash.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

# Enable dev-mode auto-reset for local development
os.environ.setdefault("CONTROL_TOWER_DEV_MODE", "1")

from migration_factory.control_tower.adapters.fastapi.app import create_app
from migration_factory.control_tower.application.v2_job_service import PIPELINE_ID
from migration_factory.control_tower.domain.checksums import (
    canonical_json,
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteControlTowerUnitOfWork


def _dev_root() -> Path:
    configured = os.environ.get("CONTROL_TOWER_DEV_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd() / ".control-tower-dev"


def _db_path() -> Path:
    configured = os.environ.get("CONTROL_TOWER_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return _dev_root() / "control_tower.sqlite3"


def _unit_of_work_factory():
    return SqliteControlTowerUnitOfWork(connect_control_tower(_db_path()), close_connection=True)


def _ensure_seed_data() -> None:
    root = _dev_root()
    source = root / "source"
    output = root / "output"
    workspace = root / "workspace"
    for path in (source, output, workspace):
        path.mkdir(parents=True, exist_ok=True)

    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_control_tower(db_path)
    try:
        apply_pending_migrations(connection)
        _ensure_runner_profile(connection, source=source, output=output, workspace=workspace)
        _ensure_pipeline(connection)
    finally:
        connection.close()


def _runner_profile_payload(*, source: Path, output: Path, workspace: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "display_name": "Default local runner",
        "python_executable": sys.executable,
        "ai_hub_path": str(_dev_root()),
        "maven": {
            "executable_path": "mvn",
            "expected_version": "3.9.9",
            "allow_wrapper": False,
        },
        "jdks": [
            {
                "jdk_id": "jdk-17",
                "java_home": str(_dev_root() / "jdk-17"),
                "expected_major": 17,
                "role": "source",
            },
            {
                "jdk_id": "jdk-21",
                "java_home": str(_dev_root() / "jdk-21"),
                "expected_major": 21,
                "role": "target",
            },
        ],
        "filesystem": {
            "roots": [
                {"root_id": "source-root", "kind": "source", "path": str(source)},
                {"root_id": "output-root", "kind": "output", "path": str(output)},
                {"root_id": "working-root", "kind": "output", "path": str(workspace)},
            ],
        },
        "network": {"mode": "allowlisted", "allowed_hosts": ["repo.local"]},
        "ai_profile": {"profile_id": "local-disabled"},
    }


def _ensure_runner_profile(connection, *, source: Path, output: Path, workspace: Path) -> None:
    payload = _runner_profile_payload(source=source, output=output, workspace=workspace)
    payload_json = canonical_json(payload)
    payload_checksum = sha256_canonical_json(payload)
    row = connection.execute(
        """
        SELECT payload_checksum
        FROM runner_profiles
        WHERE runner_profile_id = ? AND runner_profile_version = ?
        """,
        ("runner-default", "2026.06"),
    ).fetchone()
    if row is None:
        _insert_runner_profile(connection, payload=payload, payload_json=payload_json, payload_checksum=payload_checksum)
        return
    if str(row["payload_checksum"]) != payload_checksum:
        _update_runner_profile(connection, payload=payload, payload_json=payload_json, payload_checksum=payload_checksum)


def _insert_runner_profile(connection, *, payload: dict[str, object], payload_json: str, payload_checksum: str) -> None:
    connection.execute(
        """
        INSERT INTO runner_profiles (
            runner_profile_id, runner_profile_version, display_name, schema_version,
            payload_json, payload_checksum, created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["runner_profile_id"],
            payload["runner_profile_version"],
            payload["display_name"],
            payload["schema_version"],
            payload_json,
            payload_checksum,
            utc_now_text(),
            "local-dev",
        ),
    )


def _update_runner_profile(connection, *, payload: dict[str, object], payload_json: str, payload_checksum: str) -> None:
    connection.execute(
        """
        UPDATE runner_profiles
        SET display_name = ?,
            schema_version = ?,
            payload_json = ?,
            payload_checksum = ?,
            created_at = ?,
            created_by = ?
        WHERE runner_profile_id = ? AND runner_profile_version = ?
        """,
        (
            payload["display_name"],
            payload["schema_version"],
            payload_json,
            payload_checksum,
            utc_now_text(),
            "local-dev",
            payload["runner_profile_id"],
            payload["runner_profile_version"],
        ),
    )


def _pipeline_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "pipeline_id": PIPELINE_ID,
        "pipeline_version": "2026.06",
        "display_name": "Spring Boot 2.1.6 to 4.0.0 Java 21 four-stage pipeline",
        "graph_version": "1.0",
        "graph_state_schema_version": "1.0",
        "stages": [
            {
                "stage_index": 1,
                "stage_id": "foundation-diagnostic",
                "profile_id": "diagnostic-profile",
                "command_jdk": "jdk-17",
                "input_source": {"kind": "legacy_source"},
                "continuation_policy_id": "default",
                "target": {"java": 17, "spring_boot": "3.5.6"},
            },
            {
                "stage_index": 2,
                "stage_id": "boot-35-upgrade",
                "profile_id": "rewrite-profile",
                "command_jdk": "jdk-17",
                "input_source": {"kind": "previous_stage", "previous_stage_index": 1},
                "continuation_policy_id": "default",
                "target": {"java": 17, "spring_boot": "3.5.6"},
            },
            {
                "stage_index": 3,
                "stage_id": "java-21-upgrade",
                "profile_id": "rewrite-profile",
                "command_jdk": "jdk-21",
                "input_source": {"kind": "previous_stage", "previous_stage_index": 2},
                "continuation_policy_id": "default",
                "target": {"java": 21, "spring_boot": "3.5.6"},
            },
            {
                "stage_index": 4,
                "stage_id": "boot-4-upgrade",
                "profile_id": "rewrite-profile",
                "command_jdk": "jdk-21",
                "input_source": {"kind": "previous_stage", "previous_stage_index": 3},
                "continuation_policy_id": "default",
                "target": {"java": 21, "spring_boot": "4.0.0"},
            },
        ],
    }


def _ensure_pipeline(connection) -> None:
    payload = _pipeline_payload()
    payload_json = canonical_json(payload)
    payload_checksum = sha256_canonical_json(payload)
    row = connection.execute(
        """
        SELECT payload_checksum
        FROM pipeline_definitions
        WHERE pipeline_id = ? AND pipeline_version = ?
        """,
        (PIPELINE_ID, "2026.06"),
    ).fetchone()
    if row is None:
        _insert_pipeline(connection, payload=payload, payload_json=payload_json, payload_checksum=payload_checksum)
        return
    if str(row["payload_checksum"]) != payload_checksum:
        _update_pipeline(connection, payload=payload, payload_json=payload_json, payload_checksum=payload_checksum)


def _insert_pipeline(connection, *, payload: dict[str, object], payload_json: str, payload_checksum: str) -> None:
    connection.execute(
        """
        INSERT INTO pipeline_definitions (
            pipeline_id, pipeline_version, display_name, schema_version,
            graph_version, graph_state_schema_version, payload_json, payload_checksum,
            created_at, created_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["pipeline_id"],
            payload["pipeline_version"],
            payload["display_name"],
            payload["schema_version"],
            payload["graph_version"],
            payload["graph_state_schema_version"],
            payload_json,
            payload_checksum,
            utc_now_text(),
            "local-dev",
        ),
    )


def _update_pipeline(connection, *, payload: dict[str, object], payload_json: str, payload_checksum: str) -> None:
    connection.execute(
        """
        UPDATE pipeline_definitions
        SET display_name = ?,
            schema_version = ?,
            graph_version = ?,
            graph_state_schema_version = ?,
            payload_json = ?,
            payload_checksum = ?,
            created_at = ?,
            created_by = ?
        WHERE pipeline_id = ? AND pipeline_version = ?
        """,
        (
            payload["display_name"],
            payload["schema_version"],
            payload["graph_version"],
            payload["graph_state_schema_version"],
            payload_json,
            payload_checksum,
            utc_now_text(),
            "local-dev",
            payload["pipeline_id"],
            payload["pipeline_version"],
        ),
    )


_ensure_seed_data()

app = create_app(_unit_of_work_factory)
