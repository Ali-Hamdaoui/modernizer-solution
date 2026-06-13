"""Integration tests for V2 approval and stage progression API endpoints."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_approval_mapping import (
    V2ApprovalMappingService,
)
from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_approval_repository import (
    SqliteV2ApprovalRepository,
    V2ApprovalDecisionRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
)


def _mutation_headers():
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID
    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _api_client(tmp_path: Path):
    from migration_factory.control_tower.adapters.fastapi import create_app
    conn = sqlite3.connect(
        tmp_path / "approval_stage_test.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn))
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, conn


def _create_setup(conn: sqlite3.Connection) -> str:
    repo = SqliteV2SetupRepository(conn)
    service = V2SetupService(repo)
    req = CreateSetupRequest(
        run_name="test-api",
        legacy_app_path="/tmp/legacy",
        output_parent_path="/tmp/output",
        ai_hub_path="/tmp/ai-hub",
        java11_home="/usr/lib/jvm/java-11",
        java17_home="/usr/lib/jvm/java-17",
        java21_home="/usr/lib/jvm/java-21",
        maven_cmd="/usr/bin/mvn",
    )
    return service.create_setup(req).setup_id


def _create_pending_card(conn: sqlite3.Connection) -> str:
    repo = SqliteV2ApprovalRepository(conn)
    now = utc_now_text()
    card = V2ApprovalDecisionRecord(
        card_id=uuid4().hex,
        interrupt_id="int-test",
        request_checksum="chk-123",
        stage_index=1,
        summary="Test approval",
        status="pending",
        created_at=now,
    )
    repo.save_card(card)
    return card.card_id


# ── Approval endpoint tests ─────────────────────────────────────────


class TestApprovalEndpoints:

    def test_approve_with_correct_checksum(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        card_id = _create_pending_card(conn)

        response = client.post(
            f"/v1/v2/jobs/job-1/approvals/{card_id}/approve",
            json={"expected_checksum": "chk-123"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["decision"] == "approved"
        assert body["card_id"] == card_id

    def test_approve_with_wrong_checksum(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        card_id = _create_pending_card(conn)

        response = client.post(
            f"/v1/v2/jobs/job-1/approvals/{card_id}/approve",
            json={"expected_checksum": "wrong-checksum"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 400
        assert "Checksum mismatch" in response.text

    def test_reject_card(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        card_id = _create_pending_card(conn)

        response = client.post(
            f"/v1/v2/jobs/job-1/approvals/{card_id}/reject",
            json={},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "rejected"

    def test_get_card(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        card_id = _create_pending_card(conn)

        response = client.get(
            f"/v1/v2/jobs/job-1/approvals/{card_id}",
            headers={"Host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["card_id"] == card_id
        assert body["status"] == "pending"

    def test_get_nonexistent_card(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.get(
            "/v1/v2/jobs/job-1/approvals/nonexistent",
            headers={"Host": "127.0.0.1:8000"},
        )
        assert response.status_code == 404

    def test_approve_persists_across_requests(self, tmp_path: Path) -> None:
        """Approved card should persist across separate API calls."""
        client1, conn1 = _api_client(tmp_path)
        card_id = _create_pending_card(conn1)

        # Approve
        response = client1.post(
            f"/v1/v2/jobs/job-1/approvals/{card_id}/approve",
            json={"expected_checksum": "chk-123"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200

        # Get from a new client/connection
        db_path = tmp_path / "approval_stage_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        conn2.execute("PRAGMA foreign_keys = ON")
        repo2 = SqliteV2ApprovalRepository(conn2)
        loaded = repo2.get_card(card_id)
        assert loaded is not None
        assert loaded.status == "approved"
        conn2.close()


# ── Stage progression endpoint tests ────────────────────────────────


class TestStageProgressionEndpoints:

    def test_progress_to_stage2(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _create_setup(conn)

        response = client.post(
            "/v1/v2/jobs/job-1/stages/progress",
            json={
                "setup_id": setup_id,
                "current_stage": 1,
                "sandbox_path": "/tmp/sandbox/s1",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["to_stage"] == 2
        assert body["status"] == "queued"

    def test_progress_to_stage3(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _create_setup(conn)

        response = client.post(
            "/v1/v2/jobs/job-1/stages/progress",
            json={
                "setup_id": setup_id,
                "current_stage": 2,
                "sandbox_path": "/tmp/sandbox/s2",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["to_stage"] == 3

    def test_cannot_progress_beyond_stage3(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        setup_id = _create_setup(conn)

        response = client.post(
            "/v1/v2/jobs/job-1/stages/progress",
            json={
                "setup_id": setup_id,
                "current_stage": 3,
                "sandbox_path": "/tmp/sandbox/s3",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 400
        assert "Cannot progress" in response.text

    def test_progression_persists_command(self, tmp_path: Path) -> None:
        """Progression should persist the next stage command."""
        client, conn = _api_client(tmp_path)
        setup_id = _create_setup(conn)

        response = client.post(
            "/v1/v2/jobs/job-1/stages/progress",
            json={
                "setup_id": setup_id,
                "current_stage": 1,
                "sandbox_path": "/tmp/sandbox/s1",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200

        # Verify the command was persisted
        db_path = tmp_path / "approval_stage_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        conn2.execute("PRAGMA foreign_keys = ON")
        cmd_repo = SqliteV2CommandRepository(conn2)
        cmds = cmd_repo.list_by_job("job-1")
        assert len(cmds) == 1
        assert cmds[0].stage_index == 2
        assert "springboot-2.7-to-3.5-java17" in cmds[0].argv_json
        conn2.close()

    def test_progression_missing_setup(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/stages/progress",
            json={
                "setup_id": "nonexistent",
                "current_stage": 1,
                "sandbox_path": "/tmp/sandbox/s1",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 400


# ── Security: browser cannot approve without mutation headers ──────


def test_approval_rejects_missing_mutation_headers(tmp_path: Path) -> None:
    client, conn = _api_client(tmp_path)
    card_id = _create_pending_card(conn)

    # Missing Origin header
    response = client.post(
        f"/v1/v2/jobs/job-1/approvals/{card_id}/approve",
        json={"expected_checksum": "chk-123"},
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 403


def test_approval_rejects_wrong_checksum_at_api(tmp_path: Path) -> None:
    """Checksum mismatch must be enforced at the API level."""
    client, conn = _api_client(tmp_path)
    card_id = _create_pending_card(conn)

    response = client.post(
        f"/v1/v2/jobs/job-1/approvals/{card_id}/approve",
        json={"expected_checksum": "wrong"},
        headers=_mutation_headers(),
    )
    assert response.status_code == 400
    assert "checksum" in response.text.lower()
