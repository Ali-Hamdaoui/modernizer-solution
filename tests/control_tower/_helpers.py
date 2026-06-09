from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations


def canonical_json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")  # type: ignore[assignment]
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_migrated_connection(tmp_path: Path) -> sqlite3.Connection:
    connection = connect_control_tower(tmp_path / "control_tower.sqlite3")
    apply_pending_migrations(connection)
    return connection


def seed_runner_profile(connection: sqlite3.Connection) -> None:
    payload = runner_profile_payload()
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
            canonical_json(payload),
            sha256_json(payload),
            utc_now_text(),
            "tester",
        ),
    )


def seed_pipeline_definition(connection: sqlite3.Connection) -> None:
    payload = pipeline_definition_payload()
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
            canonical_json(payload),
            sha256_json(payload),
            utc_now_text(),
            "tester",
        ),
    )


def seed_runner_and_pipeline(connection: sqlite3.Connection) -> None:
    seed_runner_profile(connection)
    seed_pipeline_definition(connection)


def runner_profile_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "display_name": "Default runner",
        "python_executable": "C:/Python313/python.exe",
        "ai_hub_path": "C:/ai-hub",
        "maven": {
            "executable_path": "C:/tools/apache-maven-3.9.9/bin/mvn.cmd",
            "expected_version": "3.9.9",
            "allow_wrapper": False,
        },
        "jdks": (
            {
                "jdk_id": "jdk-17",
                "java_home": "C:/jdks/temurin-17",
                "expected_major": 17,
                "role": "source",
            },
            {
                "jdk_id": "jdk-21",
                "java_home": "C:/jdks/temurin-21",
                "expected_major": 21,
                "role": "target",
            },
        ),
        "filesystem": {
            "roots": (
                {
                    "root_id": "source-root",
                    "kind": "source",
                    "path": "C:/workspace/source",
                },
                {
                    "root_id": "output-root",
                    "kind": "output",
                    "path": "C:/workspace/output",
                },
            )
        },
        "network": {
            "mode": "allowlisted",
            "allowed_hosts": ("repo.local",),
        },
        "ai_profile": {
            "profile_id": "azure-gpt",
        },
    }


def pipeline_definition_payload() -> dict:
    return {
        "schema_version": "1.0.0",
        "pipeline_id": "pipeline-default",
        "pipeline_version": "2026.06",
        "display_name": "Default pipeline",
        "graph_version": "1.0",
        "graph_state_schema_version": "1.0",
        "stages": (
            {
                "stage_index": 1,
                "stage_id": "analyze",
                "profile_id": "analysis-profile",
                "command_jdk": "jdk-17",
                "input_source": {"kind": "legacy_source"},
                "continuation_policy_id": "default",
                "target": {"spring_boot": "3.5.14", "java": 17},
            },
            {
                "stage_index": 2,
                "stage_id": "transform",
                "profile_id": "transform-profile",
                "command_jdk": "jdk-21",
                "input_source": {"kind": "previous_stage", "previous_stage_index": 1},
                "continuation_policy_id": "default",
                "target": {"spring_boot": "3.5.14", "java": 21},
            },
        ),
    }
