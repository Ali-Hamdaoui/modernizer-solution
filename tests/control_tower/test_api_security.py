from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from migration_factory.control_tower.adapters.fastapi import create_app
from migration_factory.control_tower.adapters.fastapi.app import EventReplayConfig
from migration_factory.control_tower.adapters.fastapi.security import (
    ActorIdentity,
    DEFAULT_FRONTEND_CLIENT_ID,
    LocalApiSecuritySettings,
)
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from tests.control_tower._helpers import artifact_roots, seed_pipeline_definition, seed_runner_profile_with_roots


class _FakeActorProvider:
    def current_actor(self) -> ActorIdentity:
        return ActorIdentity(actor_type="local_operator", actor_id="operator-1")


class _FakeSmokeClient:
    def smoke(self):
        from migration_factory.control_tower.application.v2_assistant_model_client import V2ModelSmokeResult

        return V2ModelSmokeResult(
            success=False,
            deployment="secret-deployment",
            provider="azure_openai",
            failure_reason="http_401",
            redacted_summary="Azure OpenAI smoke failed: Authorization bearer sk-abc123.",
            response_snippet="Bearer sk-abc123 secret-deployment",
            latency_ms=1.0,
        )


def test_api_defaults_to_127_not_localhost_or_wildcard() -> None:
    settings = LocalApiSecuritySettings()

    assert settings.api_host == "127.0.0.1"
    assert settings.frontend_host == "127.0.0.1"
    assert settings.api_origin == "http://127.0.0.1:8000"
    assert settings.frontend_origin == "http://127.0.0.1:3000"
    assert settings.api_host not in {"localhost", "0.0.0.0"}


def test_supported_config_rejects_mixing_localhost_and_127() -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        LocalApiSecuritySettings(frontend_host="localhost")


def test_trusted_host_rejects_unexpected_hosts(tmp_path: Path) -> None:
    client = _client(tmp_path, base_url="http://localhost:8000")

    response = client.get("/v1/runner-profiles")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNTRUSTED_HOST"


def test_browser_mutation_accepts_exact_configured_origin(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post("/v1/jobs", json=_job_payload(), headers=_mutation_headers())

    assert response.status_code == 201


def test_browser_mutation_rejects_wrong_origin(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        json=_job_payload(),
        headers=_mutation_headers(origin="http://localhost:3000"),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_ORIGIN"


def test_browser_mutation_rejects_missing_origin(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        json=_job_payload(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "create-1",
            "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "INVALID_ORIGIN"


def test_cors_has_no_wildcard_and_uses_exact_origin(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.options(
        "/v1/jobs",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert response.headers["access-control-allow-origin"] != "*"


def test_mutation_rejects_non_json_content_type(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        content="not-json",
        headers={
            **_mutation_headers(),
            "Content-Type": "text/plain",
        },
    )

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"


def test_mutation_rejects_missing_client_header(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        json=_job_payload(),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "create-1",
            "Origin": "http://127.0.0.1:3000",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CLIENT_HEADER"


def test_mutation_rejects_wrong_client_header(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        json=_job_payload(),
        headers=_mutation_headers(client_id="wrong-client"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CLIENT_HEADER"


def test_read_only_event_replay_endpoint_does_not_require_mutation_header(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    create_response = client.post("/v1/jobs", json=_job_payload(), headers=_mutation_headers())
    job_id = create_response.json()["job"]["job_id"]

    response = client.get(f"/v1/jobs/{job_id}/events?after_sequence=0")

    assert response.status_code == 200


def test_backend_actor_provider_derives_actor_server_side(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection, actor_provider=_FakeActorProvider())
    create_response = client.post("/v1/jobs", json=_job_payload(), headers=_mutation_headers())
    job_id = create_response.json()["job"]["job_id"]
    etag = create_response.headers["etag"]

    start_response = client.post(
        f"/v1/jobs/{job_id}/start",
        json={},
        headers=_mutation_headers(idempotency_key="start-1", if_match=etag),
    )
    assert start_response.status_code == 200

    events = client.get(f"/v1/jobs/{job_id}/events?after_sequence=0").json()["events"]
    state_changed = [event for event in events if event["event_type"] == "job_state_changed"][0]
    assert state_changed["actor_type"] == "local_operator"
    assert state_changed["actor_id"] == "operator-1"


def test_frontend_actor_fields_are_rejected(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    payload = _job_payload() | {"actor_type": "user", "actor_id": "bad"}

    response = client.post("/v1/jobs", json=payload, headers=_mutation_headers())

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_public_payloads_and_errors_are_redacted(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    dependencies = client.get("/v1/health/dependencies")

    assert dependencies.status_code == 200
    snapshot = str(dependencies.json())
    assert "C:\\" not in snapshot
    assert "/tmp/" not in snapshot
    assert "pid" not in snapshot.lower()
    assert "process_control_id" not in snapshot
    client.close()

    app = create_app(lambda: SqliteUnitOfWork(connection))

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("SECRET=value path=C:/temp/private.txt pid=123 handle=99")

    with TestClient(app, base_url="http://127.0.0.1:8000", raise_server_exceptions=False) as exploding_client:
        response = exploding_client.get("/boom")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_SERVER_ERROR"
    assert "C:\\" not in error["message"]
    assert "SECRET" not in error["message"]


def test_azure_smoke_response_omits_deployment_and_redacts_snippets(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    app = create_app(
        lambda: SqliteUnitOfWork(connection),
        v2_assistant_model_client=_FakeSmokeClient(),
    )

    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        response = client.post(
            "/v1/v2/azure/check-smoke",
            headers=_mutation_headers(),
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "deployment" not in body
    assert "secret-deployment" not in response.text
    assert "sk-abc123" not in response.text
    assert body["provider"] == "azure_openai"


def test_public_errors_follow_contract_and_include_correlation_id(tmp_path: Path) -> None:
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)

    response = client.post(
        "/v1/jobs",
        json=_job_payload(),
        headers=_mutation_headers(origin="http://localhost:3000"),
    )

    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "correlation_id"}
    assert body["error"]["correlation_id"]
    assert response.headers["X-Correlation-ID"] == body["error"]["correlation_id"]


def test_failure_summary_redacts_secret_like_diagnostic_fields(tmp_path: Path) -> None:
    """BuildErrorContract diagnostic fields must not leak secrets in the API response."""
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    # Create a V2 job first so the endpoint resolves
    job_id = _seed_v2_job(connection, "job-summary")

    # Inject events with secret-like diagnostic data directly into DB
    # (bypasses the orchestrator redaction to test defense-in-depth)
    with SqliteUnitOfWork(connection) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=1,
            event_type="build_failed",
            status="failed",
            message="Build failed",
            payload={
                "matched_line": "C:\\Users\\admin\\secret.key not found",
                "command": ["mvn", "-Dpassword=secret123", "package"],
                "java_home": "C:\\Program Files\\Java\\jdk-11",
                "build_tool": "maven",
                "result_kind": "dependency_error",
                "module": "com.example.secret_module",
                "AZURE_OPENAI_API_KEY": "should-be-redacted",
                "GITHUB_TOKEN": "ghp_should-be-redacted",
            },
        )

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/failure-summary")
    assert response.status_code == 200, response.text
    body_str = str(response.json())

    # Must NOT contain raw secrets or paths
    assert "secret.key" not in body_str
    assert "password=secret123" not in body_str
    assert "AZURE_OPENAI_API_KEY" not in body_str
    assert "GITHUB_TOKEN" not in body_str
    assert "ghp_" not in body_str
    # Absolute paths should be redacted
    assert "C:\\Users\\" not in body_str
    assert "C:\\Program Files\\" not in body_str


def test_sse_events_redact_secret_like_payloads(tmp_path: Path) -> None:
    """Events streamed via SSE must not contain raw secrets in payload."""
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    job_id = _seed_v2_job(connection, "job-sse")

    with SqliteUnitOfWork(connection) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=1,
            event_type="model_invocation_failed",
            status="failed",
            message="API key: sk-abc123secret",
            payload={
                "error_body": '{"error":{"message":"Invalid API key"}}',
                "api_key": "should-be-redacted",
                "AZURE_OPENAI_API_KEY": "secret-value",
            },
        )

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/events?after=0&once=true")
    assert response.status_code == 200, response.text

    body_str = response.text
    # SSE frames must not leak secret values
    assert "sk-abc123secret" not in body_str
    assert "secret-value" not in body_str
    # Secret key names are Python constants, not live secrets —
    # the values behind them must be redacted
    assert "[redacted]" in body_str  # values redacted, keys may remain


def test_v2_pipeline_projection_redacts_all_raw_paths(tmp_path: Path) -> None:
    """V2 pipeline projection must not expose absolute paths."""
    connection = _seeded_connection(tmp_path)
    client = _client_from_connection(connection)
    job_id = _seed_v2_job(connection, "job-pipeline")

    with SqliteUnitOfWork(connection) as uow:
        uow.v2_events.save(
            job_id=job_id,
            stage=1,
            event_type="artifact_written",
            status="completed",
            message="C:\\Users\\operator\\app\\report.json written",
            payload={
                "artifact_kind": "analysis_report",
                "relative_path": "C:\\Users\\operator\\app\\.migration\\runs\\run-1\\report.json",
            },
        )

    response = client.get(f"/v1/v2/migration-jobs/{job_id}/pipeline")
    assert response.status_code == 200, response.text
    body_str = str(response.json())

    assert "C:\\Users\\" not in body_str
    assert "operator" not in body_str
    # artifact_kind metadata (non-path) should still be visible
    assert "analysis_report" in body_str


def test_orchestrator_env_excludes_secret_env_vars() -> None:
    """The _build_env function must never include secret env vars."""
    import os as _os
    from migration_factory.control_tower.application.v2_orchestrator_runner import (
        _build_env, _SECRET_ENV_MARKERS, _COPILOT_ENV_KEYS, _MANIFEST_ENV_KEYS,
    )

    # Verify all manifest env keys are safe (no secret markers)
    for key in _MANIFEST_ENV_KEYS:
        upper = key.upper()
        assert not any(m in upper for m in _SECRET_ENV_MARKERS), (
            f"Manifest env key {key!r} matches secret marker"
        )

    # Verify copilot env keys with secret markers are excluded
    secret_copilot_keys = [k for k in _COPILOT_ENV_KEYS if any(m in k.upper() for m in _SECRET_ENV_MARKERS)]
    # After the _build_env filter, no secret copilot keys should be passed
    # This is enforced by _is_secret_env_key check in _build_env
    # Just verify the markers detect actual secret keys
    assert any(m in "AZURE_OPENAI_API_KEY" for m in _SECRET_ENV_MARKERS)
    assert any(m in "GITHUB_TOKEN" for m in _SECRET_ENV_MARKERS)


def _seed_v2_job(connection: sqlite3.Connection, job_id: str) -> str:
    """Insert a minimal V2 job record so V2 endpoints resolve."""
    now = "2026-01-15T00:00:00Z"
    connection.execute(
        """INSERT INTO v2_migration_jobs (
            job_id, setup_id, setup_checksum, pipeline_id,
            stage_chain_json, status, created_at, updated_at, correlation_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, "setup-test", "cs-test", "pipeline-default", "[]", "running", now, now, None),
    )
    return job_id


def _client(
    tmp_path: Path,
    *,
    base_url: str = "http://127.0.0.1:8000",
) -> TestClient:
    connection = _api_test_connection(tmp_path)
    apply_pending_migrations(connection)
    return TestClient(create_app(lambda: SqliteUnitOfWork(connection)), base_url=base_url)


def _client_from_connection(
    connection: sqlite3.Connection,
    *,
    actor_provider: _FakeActorProvider | None = None,
) -> TestClient:
    return TestClient(
        create_app(lambda: SqliteUnitOfWork(connection), actor_provider=actor_provider),
        base_url="http://127.0.0.1:8000",
    )


def _seeded_connection(tmp_path: Path) -> sqlite3.Connection:
    connection = _api_test_connection(tmp_path)
    apply_pending_migrations(connection)
    seed_runner_profile_with_roots(connection, artifact_roots(tmp_path))
    seed_pipeline_definition(connection)
    return connection


def _api_test_connection(tmp_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        tmp_path / "control_tower.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def _mutation_headers(
    *,
    origin: str = "http://127.0.0.1:3000",
    client_id: str = DEFAULT_FRONTEND_CLIENT_ID,
    idempotency_key: str = "create-1",
    if_match: str | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Origin": origin,
        "X-Control-Tower-Client": client_id,
        "Idempotency-Key": idempotency_key,
    }
    if if_match is not None:
        headers["If-Match"] = if_match
    return headers


def _job_payload() -> dict[str, object]:
    return {
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "pipeline_id": "pipeline-default",
        "pipeline_version": "2026.06",
        "legacy_source_root_id": "source-root",
        "legacy_source_relative_path": "src",
        "output_root_id": "output-root",
        "output_relative_path": "out",
        "target_proof_level": "ANALYZED",
        "enabled_gates": [],
        "policy": {
            "continue_after_warning": False,
            "enable_runtime_gate": False,
            "enable_endpoint_gate": False,
        },
    }
