"""V2 real orchestrator subprocess runner tests."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.v2_orchestrator_runner import V2OrchestratorRunner
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import V2StageCommandRecord


class _FakeProcess:
    def __init__(self, stdout: list[str], stderr: list[str], exit_code: int) -> None:
        self.stdout = iter(stdout)
        self.stderr = iter(stderr)
        self.pid = 12345
        self._exit_code = exit_code

    def wait(self) -> int:
        return self._exit_code


class _FakePopen:
    def __init__(self, stdout: list[str], stderr: list[str], exit_code: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeProcess:
        self.calls.append({"argv": argv, **kwargs})
        return _FakeProcess(self.stdout, self.stderr, self.exit_code)


def _conn(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        tmp_path / "runner.sqlite3",
        check_same_thread=False,
        isolation_level=None,
        timeout=5.0,
    )
    conn.row_factory = sqlite3.Row
    apply_pending_migrations(conn)
    return conn


def _save_command(conn: sqlite3.Connection, *, command_id: str = "cmd-1", job_id: str = "job-1") -> None:
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_commands.save(
        V2StageCommandRecord(
            command_id=command_id,
            job_id=job_id,
            stage_index=1,
            manifest_checksum="checksum",
            argv_json=json.dumps(["python", "-m", "migration_factory.orchestrator.runner", "--run-id", "run-1"]),
            env_json=json.dumps({
                "JAVA_HOME": "C:/jdk11",
                "JAVA11_HOME": "C:/jdk11",
                "JAVA17_HOME": "C:/jdk17",
                "JAVA21_HOME": "C:/jdk21",
                "MAVEN_CMD": "C:/maven/bin/mvn.cmd",
                "PATH_PREPEND": "C:/jdk11/bin",
            }),
            status="manifest_ready",
            created_at=now,
            updated_at=now,
            result_json=None,
        )
    )


def _wait_for_event(conn: sqlite3.Connection, job_id: str, event_type: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        events = SqliteUnitOfWork(conn).v2_events.list_by_job(job_id)
        if any(event.type == event_type for event in events):
            return
        time.sleep(0.02)
    raise AssertionError(f"event {event_type!r} not persisted")


def test_v2_runner_launches_manifest_with_shell_false_and_safe_env(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    popen = _FakePopen(
        stdout=[
            'CONTROL_TOWER_EVENT {"phase":"analysis","status":"running","message":"analysis started"}\n',
            json.dumps({"final_status": "APPLIED", "artifact_refs": {"analysis_report": "C:/out/.migration/runs/run-1/analysis/report.json"}, "sandbox_path": "C:/out/sandbox"}) + "\n",
        ],
        stderr=["warning from runner\n"],
        exit_code=0,
    )
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_completed")

    assert popen.calls
    call = popen.calls[0]
    assert call["shell"] is False
    assert call["cwd"] == str(tmp_path)
    assert "MAVEN_CMD" in call["env"]
    assert "AZURE_OPENAI_API_KEY" not in call["env"]

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "analysis_started" in event_types
    assert "stderr" in event_types
    assert "artifact_written" in event_types
    assert "proof_updated" in event_types
    assert "stage_completed" in event_types


def test_v2_runner_maps_failure_to_stage_failed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[], stderr=["boom\n"], exit_code=2),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    failed = [event for event in events if event.type == "stage_failed"][-1]
    assert failed.status == "failed"
    assert "code 2" in failed.message


def test_v2_runner_maps_approval_interrupt_to_card_and_blocked_events(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "status": "human_approval_required",
        "run_id": "run-1",
        "summary": {"analysis_status": "PASS"},
        "artifact_refs": {"plan": "C:/out/.migration/runs/run-1/planning/plan.json"},
        "decision_options": ["approved", "rejected", "replan_required"],
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_blocked_for_approval")

    uow = SqliteUnitOfWork(conn)
    events = uow.v2_events.list_by_job("job-1")
    assert "approval_required" in [event.type for event in events]
    cards = uow.v2_approvals.list_cards_by_status("pending")
    assert len(cards) == 1
    assert cards[0].request_checksum
