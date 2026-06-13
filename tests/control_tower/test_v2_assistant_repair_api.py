"""Integration tests for V2 assistant and repair API endpoints."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_setup_service import (
    CreateSetupRequest,
    V2SetupService,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_assistant_repository import (
    SqliteV2AssistantRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
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
        tmp_path / "assistant_repair_test.sqlite3",
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


# ── Assistant API tests ────────────────────────────────────────────


class TestAssistantAPI:

    def test_add_message(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "user", "content": "Hello"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["role"] == "user"
        assert body["content"] == "Hello"

    def test_add_assistant_message(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "assistant", "content": "Status: ready"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["role"] == "assistant"

    def test_list_messages(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        # Add two messages
        client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "user", "content": "Hi"},
            headers=_mutation_headers(),
        )
        client.post(
            "/v1/v2/jobs/job-1/assistant/messages",
            json={"job_id": "job-1", "role": "assistant", "content": "Hello"},
            headers=_mutation_headers(),
        )
        response = client.get(
            "/v1/v2/jobs/job-1/assistant/messages",
            headers={"Host": "127.0.0.1:8000"},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["messages"]) == 2

    def test_draft_action(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "plan_instruction",
                "reason": "Need plan for stage 1",
                "stage_index": 1,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert body["action_type"] == "plan_instruction"

    def test_draft_action_persists(self, tmp_path: Path) -> None:
        """Draft should persist and be retrievable."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "repair_instruction",
                "reason": "Fix NPE",
                "stage_index": 2,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        action_id = response.json()["action_id"]

        # Verify persistence
        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2AssistantRepository(conn2)
        loaded = repo.get_draft(action_id)
        assert loaded is not None
        assert loaded.status == "draft"
        conn2.close()

    def test_message_persists(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-persist/assistant/messages",
            json={"job_id": "job-persist", "role": "user", "content": "Persist me"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200
        msg_id = response.json()["message_id"]

        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2AssistantRepository(conn2)
        loaded = repo.get_message(msg_id)
        assert loaded is not None
        assert loaded.content == "Persist me"
        conn2.close()


# ── Repair API tests ───────────────────────────────────────────────


class TestRepairAPI:

    def test_create_proposal(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-1/repair/flow-proposal",
            json={
                "command_id": "cmd-1",
                "failure_summary": "Build failed",
                "hypothesis": "Missing import",
                "patch_summary": "Add import statement",
                "affected_paths": ["src/main.java"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert "Missing import" in body["hypothesis"]

    def test_approve_proposal(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        # Create proposal
        create_resp = client.post(
            "/v1/v2/commands/cmd-2/repair/flow-proposal",
            json={
                "command_id": "cmd-2",
                "failure_summary": "Error",
                "hypothesis": "Bug",
                "patch_summary": "Fix",
                "affected_paths": ["src/Fix.java"],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200
        proposal_id = create_resp.json()["proposal_id"]

        # Approve with checksum
        response = client.post(
            f"/v1/v2/commands/cmd-2/repair/proposal/{proposal_id}/approve",
            json={"approval_checksum": "chk-abc"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "approved"
        assert body["approval_checksum"] == "chk-abc"

    def test_approve_missing_proposal(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-3/repair/proposal/nonexistent/approve",
            json={"approval_checksum": "chk"},
            headers=_mutation_headers(),
        )
        assert response.status_code == 400

    def test_proposal_persistence(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        # Create proposal
        create_resp = client.post(
            "/v1/v2/commands/cmd-persist/repair/flow-proposal",
            json={
                "command_id": "cmd-persist",
                "failure_summary": "Persist test",
                "hypothesis": "Check persistence",
                "patch_summary": "Verify",
                "affected_paths": ["test.txt"],
            },
            headers=_mutation_headers(),
        )
        assert create_resp.status_code == 200
        proposal_id = create_resp.json()["proposal_id"]

        # Verify in DB
        db_path = tmp_path / "assistant_repair_test.sqlite3"
        conn2 = sqlite3.connect(
            db_path, check_same_thread=False, isolation_level=None, timeout=5.0
        )
        conn2.row_factory = sqlite3.Row
        repo = SqliteV2RepairRepository(conn2)
        loaded = repo.get_proposal(proposal_id)
        assert loaded is not None
        assert loaded.failure_summary == "Persist test"
        conn2.close()
