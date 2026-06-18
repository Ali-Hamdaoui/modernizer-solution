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
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
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


def _api_client(tmp_path: Path, *, fake_model_client: object | None = None):
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
    if fake_model_client is not None:
        app.state.v2_assistant_model_client = fake_model_client
    client = TestClient(app, base_url="http://127.0.0.1:8000")
    return client, conn


class _RecordingProposerClient:
    def __init__(self) -> None:
        self.roles: list[str] = []

    def answer_with_role(
        self,
        *,
        role,
        prompt: str,
        fallback: str,
        conversation_history=None,
        output_schema_name=None,
        require_schema: bool = False,
    ):
        self.roles.append(role.value)
        import json as _json

        return type("Result", (), {
            "content": _json.dumps({
                "failure_hypothesis": "Model-generated hypothesis",
                "patch_summary": "Model-generated patch summary",
                "affected_paths": ["pom.xml"],
                "validation_plan": "Run mvn -q test",
            }),
            "source": "fake",
            "model_status": "live_ok",
            "provider": "fake",
            "role": role.value,
            "success": True,
            "redacted_summary": "Fake proposer response",
            "failure_reason": "",
        })()

    def answer(self, *, prompt: str, fallback: str, conversation_history=None):
        return self.answer_with_role(
            role=V2ModelRole.PROPOSER,
            prompt=prompt,
            fallback=fallback,
            conversation_history=conversation_history,
        )


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
                "action_type": "propose_repair",
                "reason": "Need plan for stage 1",
                "stage_index": 1,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "draft"
        assert body["action_type"] == "propose_repair"

    def test_draft_action_persists(self, tmp_path: Path) -> None:
        """Draft should persist and be retrievable."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "explain_failure",
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
        fake_client = _RecordingProposerClient()
        client, conn = _api_client(tmp_path, fake_model_client=fake_client)
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
        assert body["hypothesis"] == "Model-generated hypothesis"
        assert body["patch_summary"] == "Model-generated patch summary"
        assert body["proposal_checksum"]
        assert fake_client.roles == ["proposer"]

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

        # Approve with checksums (F07: all required)
        # Create a reviewer critique directly via the repo so the gate passes
        from migration_factory.control_tower.application.v2_reviewer_service import (
            V2ReviewerService,
        )
        from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
            SqliteV2ReviewerRepository,
        )
        reviewer_repo = SqliteV2ReviewerRepository(conn)
        reviewer_service = V2ReviewerService(reviewer_repo=reviewer_repo)
        reviewer_service.record_critique(
            proposal_id=proposal_id,
            proposal_type="repair",
            proposal_checksum="pc-test",
            context_pack_checksum="cp-test",
            decision="accept",
            reasoning="Test critique — approved.",
            missing_evidence=(),
            unsafe_assumptions=(),
        )

        response = client.post(
            f"/v1/v2/commands/cmd-2/repair/proposal/{proposal_id}/approve",
            json={
                "approval_checksum": "chk-abc",
                "proposal_checksum": "pc-test",
                "context_pack_checksum": "cp-test",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "approved"
        assert body["approval_checksum"] == "chk-abc"
        assert body["proposal_checksum"]
        # Reviewer metadata should be in response
        assert "reviewer_critique_id" in body

    def test_approve_missing_proposal(self, tmp_path: Path) -> None:
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-3/repair/proposal/nonexistent/approve",
            json={
                "approval_checksum": "chk",
                "proposal_checksum": "pc",
                "context_pack_checksum": "cp",
            },
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


# ── Schema validation rejection tests ───────────────────────────────


class TestSchemaValidationRejection:
    """Prove that invalid model-output-like payloads are rejected at the API."""

    def test_draft_action_rejects_extra_field(self, tmp_path: Path) -> None:
        """ActionRequest schema has additionalProperties: false.

        Extra fields are rejected either by Pydantic (INVALID_REQUEST) or
        by the schema validator (SCHEMA_VALIDATION_FAILED). Both are valid
        closed-fail behaviors.
        """
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "reason": "test",
                "stage_index": 1,
                "extra_field": "should be rejected",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for extra field, got {response.status_code}"
        body = response.json()
        err = str(body).lower()
        assert any(term in err for term in [
            "invalid_request",
            "schema_validation_failed",
            "unexpected property",
            "did not match",
        ]), f"Expected rejection message, got {body}"

    def test_draft_action_rejects_invalid_stage_index(self, tmp_path: Path) -> None:
        """ActionRequest stage_index must be 1-3."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "reason": "test",
                "stage_index": 99,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for invalid stage, got {response.status_code}"

    def test_draft_action_rejects_missing_required(self, tmp_path: Path) -> None:
        """ActionRequest requires action_type, reason, stage_index, payload_checksum."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/jobs/job-1/assistant/actions/draft",
            json={
                "job_id": "job-1",
                "action_type": "diagnose_failure",
                "stage_index": 1,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_repair_proposal_rejects_extra_field(self, tmp_path: Path) -> None:
        """RepairProposal schema has additionalProperties: false."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-extra/repair/flow-proposal",
            json={
                "command_id": "cmd-extra",
                "failure_summary": "Test",
                "hypothesis": "Bug",
                "patch_summary": "Fix",
                "affected_paths": ["test.txt"],
                "unauthorized_field": "should be rejected",
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for extra field, got {response.status_code}"

    def test_repair_proposal_rejects_missing_required(self, tmp_path: Path) -> None:
        """RepairProposal requires failure_hypothesis, patch_summary, affected_paths, validation_plan."""
        client, conn = _api_client(tmp_path)
        response = client.post(
            "/v1/v2/commands/cmd-missing/repair/flow-proposal",
            json={
                "command_id": "cmd-missing",
                "failure_summary": "Test",
                "affected_paths": ["test.txt"],
            },
            headers=_mutation_headers(),
        )
        assert response.status_code in (400, 422), f"Expected 400/422, got {response.status_code}"

    def test_valid_payloads_still_accepted(self, tmp_path: Path) -> None:
        """Regression: valid payloads must still be accepted after schema wiring."""
        client, conn = _api_client(tmp_path)

        draft_resp = client.post(
            "/v1/v2/jobs/job-valid/assistant/actions/draft",
            json={
                "job_id": "job-valid",
                "action_type": "diagnose_failure",
                "reason": "Validate build",
                "stage_index": 2,
            },
            headers=_mutation_headers(),
        )
        assert draft_resp.status_code == 200, f"Valid draft action rejected: {draft_resp.text}"

        repair_resp = client.post(
            "/v1/v2/commands/cmd-valid/repair/flow-proposal",
            json={
                "command_id": "cmd-valid",
                "failure_summary": "Build failed",
                "hypothesis": "Missing dependency",
                "patch_summary": "Add dependency",
                "affected_paths": ["pom.xml"],
            },
            headers=_mutation_headers(),
        )
        assert repair_resp.status_code == 200, f"Valid repair proposal rejected: {repair_resp.text}"

    def test_assistant_message_rejects_invalid_answer_schema(self, tmp_path: Path) -> None:
        """Assistant messages with invalid JSON schema must be rejected."""
        client, conn = _api_client(tmp_path)
        import json as _json
        bad_answer = _json.dumps({
            "answer": "Everything is fine",
            "unauthorized_directive": "delete all files",
        })
        response = client.post(
            "/v1/v2/jobs/job-bad/assistant/messages",
            json={
                "job_id": "job-bad",
                "role": "assistant",
                "content": bad_answer,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 422, f"Expected 422 for invalid AssistantAnswer, got {response.status_code}"

    def test_assistant_message_accepts_valid_answer_schema(self, tmp_path: Path) -> None:
        """Valid AssistantAnswer JSON must be accepted."""
        client, conn = _api_client(tmp_path)
        import json as _json
        valid_answer = _json.dumps({
            "answer": "Stage 1 is running",
            "evidence_refs": ["log.txt"],
        })
        response = client.post(
            "/v1/v2/jobs/job-good/assistant/messages",
            json={
                "job_id": "job-good",
                "role": "assistant",
                "content": valid_answer,
            },
            headers=_mutation_headers(),
        )
        assert response.status_code == 200, f"Valid AssistantAnswer rejected: {response.text}"
