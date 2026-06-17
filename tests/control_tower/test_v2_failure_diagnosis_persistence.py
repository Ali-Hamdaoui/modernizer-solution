from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
)
from migration_factory.control_tower.application.v2_assistant_failure_answers import (
    V2AssistantFailureAnswerService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import (
    apply_pending_migrations,
)
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteUnitOfWork,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    V2MigrationJobRecord,
)


def _mutation_headers() -> dict[str, str]:
    from migration_factory.control_tower.adapters.fastapi.security import DEFAULT_FRONTEND_CLIENT_ID

    return {
        "Content-Type": "application/json",
        "Origin": "http://127.0.0.1:3000",
        "X-Control-Tower-Client": DEFAULT_FRONTEND_CLIENT_ID,
    }


def _connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_pending_migrations(conn)
    return conn


def _seed_job(conn: sqlite3.Connection, job_id: str = "job-1") -> None:
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_jobs.save(
        V2MigrationJobRecord(
            job_id=job_id,
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


class _FakeModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def answer(self, *, prompt: str, fallback: str):
        self.calls.append({"prompt": prompt, "fallback": fallback})
        raise AssertionError("Model client should not be called in deterministic diagnosis tests")


def test_diagnosis_is_persisted_after_creation(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "diag.sqlite3")
    run_dir = tmp_path / "run"
    sandbox = tmp_path / "sandbox"
    run_dir.mkdir()
    sandbox.mkdir()
    (run_dir / "phase2_transform.log").write_text("PKIX path building failed", encoding="utf-8")
    (sandbox / "pom.xml").write_text("<project/>", encoding="utf-8")

    repo = SqliteUnitOfWork(conn).v2_failure_diagnoses
    service = V2FailureDiagnosisService(
        diagnosis_repo=repo,
        run_dir_resolver=lambda command_id, event_type: str(run_dir),
    )

    diagnosis = service.diagnose(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        event_type="build_failed",
        payload={
            "build_status": "BUILD_FAILED",
            "stderr": "PKIX path building failed",
            "sandbox_path": str(sandbox),
            "artifact_refs": {},
        },
    )

    persisted = repo.get_by_command_and_event("cmd-1", "build_failed")
    assert persisted is not None
    assert persisted.failure_type == "maven_truststore_pkix"
    assert persisted.diagnosis_id == diagnosis.diagnosis_id
    assert persisted.evidence_pack_checksum
    assert persisted.diagnosis_checksum


def test_repeated_diagnosis_for_same_command_event_is_idempotent(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "idem.sqlite3")
    repo = SqliteUnitOfWork(conn).v2_failure_diagnoses
    service = V2FailureDiagnosisService(diagnosis_repo=repo)

    first = service.diagnose(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        event_type="build_failed",
        payload={"build_status": "BUILD_FAILED", "message": "compile failed"},
    )
    second = service.diagnose(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        event_type="build_failed",
        payload={"build_status": "BUILD_FAILED", "message": "compile failed"},
    )

    assert first.diagnosis_id == second.diagnosis_id
    assert len(repo.list_for_job("job-1")) == 1


def test_evidence_and_diagnosis_checksums_are_stable() -> None:
    payload = {
        "job_id": "job-1",
        "stage_index": 1,
        "command_id": "cmd-1",
        "event_type": "build_failed",
        "failure_type": "invalid_maven_wildcard_version",
        "likely_root_cause": "POM has 3.0.x",
        "confidence": "high",
        "recommended_fix_type": "pin_exact_maven_version",
        "affected_paths": ["pom.xml"],
        "validation_plan": ["rerun maven"],
        "evidence": [{"source": "pom.xml", "label": "pom.xml", "text": "<version>3.0.x</version>"}],
        "missing_artifacts": [],
        "context_pack_checksum": "cp-1",
        "evidence_pack_checksum": "ev-1",
        "redaction_status": "redacted",
    }
    first = V2FailureDiagnosisService.compute_diagnosis_checksum(payload)
    second = V2FailureDiagnosisService.compute_diagnosis_checksum({**payload, "created_at": utc_now_text()})
    assert first == second


def test_assistant_prefers_persisted_diagnosis() -> None:
    service = V2AssistantFailureAnswerService()
    answer = service.answer_failure_question(
        job_id="job-1",
        latest_diagnosis_data={
            "failure_type": "invalid_maven_wildcard_version",
            "likely_root_cause": "Persisted diagnosis says POM has 3.0.x.",
            "confidence": "high",
            "recommended_next_step": "Use exact version from managed dependency.",
            "affected_paths": ["pom.xml"],
            "evidence": [{"source": "pom.xml", "label": "pom.xml", "text": "<version>3.0.x</version>"}],
            "missing_artifacts": [],
        },
        failure_classification={
            "failure_type": "unknown_build_failure",
            "likely_root_cause": "recomputed fallback",
            "confidence": "low",
            "recommended_next_step": "fallback",
            "affected_paths": [],
            "evidence": [],
        },
        existing_message_text="why build failed?",
    )
    assert answer.failure_type == "invalid_maven_wildcard_version"
    assert "Persisted diagnosis says" in answer.answer


def test_latest_diagnosis_can_be_fetched_read_only_and_skips_model(tmp_path: Path) -> None:
    from migration_factory.control_tower.adapters.fastapi import create_app

    conn = _connection(tmp_path / "api.sqlite3")
    _seed_job(conn)
    fake = _FakeModelClient()
    app = create_app(lambda: SqliteUnitOfWork(conn), v2_assistant_model_client=fake)
    client = TestClient(app, base_url="http://127.0.0.1:8000")

    repo = SqliteUnitOfWork(conn).v2_failure_diagnoses
    service = V2FailureDiagnosisService(diagnosis_repo=repo)
    service.diagnose(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        event_type="build_failed",
        payload={"build_status": "BUILD_FAILED", "message": "compile failed at C:/Users/private/app"},
    )

    get_response = client.get("/v1/v2/jobs/job-1/diagnosis/latest")
    assert get_response.status_code == 200, get_response.text
    diagnosis = get_response.json()["diagnosis"]
    assert diagnosis["failure_type"]
    assert "C:/Users" not in get_response.text

    ask_response = client.post(
        "/v1/v2/jobs/job-1/assistant/ask",
        json={"question": "why did the migration fail?"},
        headers=_mutation_headers(),
    )
    assert ask_response.status_code == 200, ask_response.text
    assert fake.calls == []
    assert ask_response.json()["model"]["source"] == "deterministic"
