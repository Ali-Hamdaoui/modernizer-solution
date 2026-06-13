from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_assistant_model_client import V2AssistantModelResult
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import V2MigrationJobRecord


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


class _FakeModelClient:
    def __init__(self, result: V2AssistantModelResult) -> None:
        self.result = result
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str) -> V2AssistantModelResult:
        self.calls.append({"prompt": prompt, "fallback": fallback})
        return self.result


def _client(tmp_path: Path, model_client: _FakeModelClient) -> tuple[TestClient, sqlite3.Connection]:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = sqlite3.connect(
        tmp_path / "assistant_model.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=model_client)
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_jobs.save(
        V2MigrationJobRecord(
            job_id="job-model",
            setup_id="setup",
            setup_checksum="checksum",
            pipeline_id="springboot-216-to-356-java21-three-stage",
            stage_chain_json="[]",
            status="running",
            created_at=now,
            updated_at=now,
            correlation_id=None,
        )
    )
    return TestClient(app, base_url="http://127.0.0.1:8000"), conn


def test_assistant_uses_model_client_and_does_not_return_key(tmp_path: Path) -> None:
    fake = _FakeModelClient(
        V2AssistantModelResult(
            content="Azure-backed status answer.",
            source="azure_openai",
            model_status="configured",
            provider="azure_openai",
            role="assistant",
            success=True,
            redacted_summary="ok",
        )
    )
    client, conn = _client(tmp_path, fake)

    response = client.post(
        "/v1/v2/jobs/job-model/assistant/ask",
        json={"question": "status?"},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert fake.calls
    assert body["model"]["status"] == "configured"
    assert body["model"]["source"] == "azure_openai"
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "azure_openai_api_key" not in serialized
    assert body["guardrails"]["cannot_approve"] is True
    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-model")
    assert events[-1].type == "model_invocation_completed"
    assert events[-1].message == "ok"


def test_assistant_fallback_is_labeled_and_read_only(tmp_path: Path) -> None:
    fake = _FakeModelClient(
        V2AssistantModelResult(
            content="fallback: deterministic\n\nModel: fallback\nSource: deterministic",
            source="deterministic",
            model_status="fallback",
            provider="deterministic",
            role="assistant",
            success=False,
            redacted_summary="fallback",
        )
    )
    client, _conn = _client(tmp_path, fake)

    response = client.post(
        "/v1/v2/jobs/job-model/assistant/ask",
        json={"question": "approve it"},
        headers=_mutation_headers(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model"]["status"] == "fallback"
    assert body["model"]["source"] == "deterministic"
    assert "fallback" in body["assistant_message"]["content"].lower()
    assert body["guardrails"]["cannot_execute"] is True
    assert body["guardrails"]["cannot_approve"] is True
    assert body["guardrails"]["cannot_write_files"] is True
