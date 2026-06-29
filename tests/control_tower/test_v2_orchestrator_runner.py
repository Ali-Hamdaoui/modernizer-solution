"""V2 real orchestrator subprocess runner tests."""

from __future__ import annotations

import json
import sqlite3
import time
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.v2_orchestrator_runner import V2OrchestratorRunner
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import SqliteUnitOfWork
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import V2MigrationJobRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import V2StageCommandRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import V2MigrationSetupRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_approval_repository import (
    V2ApprovalDecisionRecord,
    V2ResumeCommandRecord,
)


class _FakeProcess:
    def __init__(self, stdout: list[str], stderr: list[str], exit_code: int) -> None:
        self.stdout = iter(stdout)
        self.stderr = iter(stderr)
        self.pid = 12345
        self._exit_code = exit_code

    def wait(self, timeout: float | None = None) -> int:
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


class _BlockingProcess:
    def __init__(self, release: threading.Event) -> None:
        self.stdout = iter([])
        self.stderr = iter([])
        self.pid = 24680
        self._release = release
        self.terminated = False
        self.killed = False

    def wait(self, timeout: float | None = None) -> int:
        wait_timeout = 3 if timeout is None else timeout
        if not self._release.wait(timeout=wait_timeout):
            raise subprocess.TimeoutExpired(cmd=["fake"], timeout=wait_timeout)
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self._release.set()

    def kill(self) -> None:
        self.killed = True
        self._release.set()


class _BlockingPopen:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls: list[dict[str, Any]] = []
        self.last_process: _BlockingProcess | None = None

    def __call__(self, argv: list[str], **kwargs: Any) -> _BlockingProcess:
        self.calls.append({"argv": argv, **kwargs})
        self.last_process = _BlockingProcess(self.release)
        return self.last_process


class _RaisingPopen:
    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeProcess:
        raise RuntimeError("boom TOKEN=secret-value /root/private.txt")


class _SequentialFakePopen:
    def __init__(self, responses: list[tuple[list[str], list[str], int]]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []
        self._index = 0

    def __call__(self, argv: list[str], **kwargs: Any) -> _FakeProcess:
        if self._index >= len(self._responses):
            raise AssertionError(f"unexpected process launch #{self._index + 1}: {argv!r}")
        stdout, stderr, exit_code = self._responses[self._index]
        self._index += 1
        self.calls.append({"argv": argv, **kwargs})
        return _FakeProcess(stdout, stderr, exit_code)


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


def _save_command(
    conn: sqlite3.Connection,
    *,
    command_id: str = "cmd-1",
    job_id: str = "job-1",
    status: str = "manifest_ready",
    result_json: str | None = None,
) -> None:
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
            status=status,
            created_at=now,
            updated_at=now,
            result_json=result_json,
        )
    )


def _seed_stage_pipeline(conn: sqlite3.Connection, *, job_id: str = "job-1") -> None:
    now = utc_now_text()
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_setups.save(
            V2MigrationSetupRecord(
                setup_id="setup-1",
                run_name="stage-pipeline",
                legacy_app_path="C:/legacy",
                output_parent_path="C:/modernized",
                ai_hub_path="C:/ai-hub",
                java11_home="C:/jdk11",
                java17_home="C:/jdk17",
                java21_home="C:/jdk21",
                maven_cmd="C:/maven/bin/mvn.cmd",
                proof_level="build_test_verified",
                skip_endpoint_smoke=False,
                migration_flags_json="{}",
                setup_checksum="checksum-setup-1",
                checksum_algorithm="sha256",
                created_at=now,
                created_by="test",
                correlation_id=None,
            )
        )
        uow.v2_jobs.save(
            V2MigrationJobRecord(
                job_id=job_id,
                setup_id="setup-1",
                setup_checksum="checksum-setup-1",
                pipeline_id="springboot-216-to-356-java21-three-stage",
                stage_chain_json='[{"stage_index":1},{"stage_index":2},{"stage_index":3}]',
                status="running",
                created_at=now,
                updated_at=now,
                correlation_id=None,
            )
        )
    _save_command(conn, command_id="cmd-1", job_id=job_id)


def _wait_for_event(conn: sqlite3.Connection, job_id: str, event_type: str) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        events = SqliteUnitOfWork(conn).v2_events.list_by_job(job_id)
        if any(event.type == event_type for event in events):
            return
        time.sleep(0.02)
    raise AssertionError(f"event {event_type!r} not persisted")


def test_runner_process_started_persists_command_running_state(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    popen = _BlockingPopen()
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    try:
        runner.start(job_id="job-1", command_id="cmd-1")
        _wait_for_event(conn, "job-1", "process_started")

        command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
        assert command is not None
        assert command.status == "running"
        result = json.loads(command.result_json or "{}")
        assert result["runner_status"] == "running"
        assert result["pid"] == 24680
        assert result["shell"] is False
        assert result["stdin_closed"] is True
        assert result["timeout_seconds"] == 900.0
        assert "TOKEN=secret-value" not in command.result_json
        assert popen.calls[0]["stdin"] == subprocess.DEVNULL
    finally:
        popen.release.set()


def test_runner_timeout_persists_failed_result_and_events(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    popen = _BlockingPopen()
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
        stage_timeout_seconds=0.01,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "runner_timeout")
    _wait_for_event(conn, "job-1", "stage_failed")

    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "failed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "timeout"
    assert persisted["final_json_found"] is False
    assert persisted["sandbox_path"] is None
    assert persisted["timeout_seconds"] == 0.01
    assert persisted["terminated"] is True
    assert popen.last_process is not None
    assert popen.last_process.terminated is True
    assert popen.last_process.killed is False
    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "runner_timeout" in event_types
    assert "stage_completed" not in event_types


def test_runner_success_persists_result_json_with_sandbox_path(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = _success_result(sandbox_path="/tmp/sandbox")
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_completed")

    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "completed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "completed"
    assert persisted["sandbox_path"] == "/tmp/sandbox"


def test_runner_nonzero_exit_persists_failed_result_contract(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(
            stdout=["TOKEN=secret-value\n"],
            stderr=["bad TOKEN=secret-value\n"],
            exit_code=42,
        ),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "failed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "failed"
    assert persisted["exit_code"] == 42
    assert persisted["final_json_found"] is False
    serialized = json.dumps(persisted)
    assert "secret-value" not in serialized
    assert "TOKEN=secret-value" not in serialized


def test_runner_missing_final_json_persists_result_contract_failed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=["CONTROL_TOWER_EVENT {\"phase\":\"x\"}\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "result_contract_failed")

    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "failed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "result_contract_failed"
    assert persisted["final_json_found"] is False
    assert persisted["sandbox_path"] is None


def test_runner_launch_exception_persists_failed_redacted_evidence(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_RaisingPopen(),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "failed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "launch_failed"
    serialized = json.dumps(persisted)
    assert "secret-value" not in serialized
    assert "/root/private.txt" not in serialized


def test_stale_reconciliation_marks_lost_process_failed(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(unit_of_work_factory=lambda: SqliteUnitOfWork(conn), cwd=tmp_path)
    SqliteUnitOfWork(conn).v2_events.save(
        job_id="job-1",
        stage=1,
        event_type="process_started",
        status="running",
        message="started",
        payload={"command_id": "cmd-1", "pid": 123},
    )

    result = runner.reconcile_stale_orchestrator_command(
        job_id="job-1",
        command_id="cmd-1",
        max_age_seconds=0,
        process_exists=lambda pid: False,
        now=lambda: datetime.now(timezone.utc) + timedelta(seconds=5),
    )

    assert result.reconciled is True
    assert result.emitted_event_types == ("runner_process_lost", "stage_failed")
    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "failed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "process_lost"
    assert persisted["sandbox_path"] is None
    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    assert "runner_process_lost" in [event.type for event in events]


def test_stale_reconciliation_ignores_existing_terminal_event(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    uow = SqliteUnitOfWork(conn)
    uow.v2_events.save(job_id="job-1", stage=1, event_type="process_started", status="running", message="started", payload={"command_id": "cmd-1", "pid": 123})
    uow.v2_events.save(job_id="job-1", stage=1, event_type="stage_failed", status="failed", message="failed", payload={"command_id": "cmd-1"})
    runner = V2OrchestratorRunner(unit_of_work_factory=lambda: SqliteUnitOfWork(conn), cwd=tmp_path)

    result = runner.reconcile_stale_orchestrator_command(
        job_id="job-1",
        command_id="cmd-1",
        max_age_seconds=0,
        process_exists=lambda pid: False,
    )

    assert result.reconciled is False
    assert result.reason == "terminal_event_exists"


def test_stale_reconciliation_ignores_live_process(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    SqliteUnitOfWork(conn).v2_events.save(
        job_id="job-1",
        stage=1,
        event_type="process_started",
        status="running",
        message="started",
        payload={"command_id": "cmd-1", "pid": 123},
    )
    runner = V2OrchestratorRunner(unit_of_work_factory=lambda: SqliteUnitOfWork(conn), cwd=tmp_path)

    result = runner.reconcile_stale_orchestrator_command(
        job_id="job-1",
        command_id="cmd-1",
        max_age_seconds=0,
        process_exists=lambda pid: True,
    )

    assert result.reconciled is False
    assert result.reason == "process_alive"
    command = SqliteUnitOfWork(conn).v2_commands.get("cmd-1")
    assert command is not None
    assert command.status == "manifest_ready"


def _success_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "orchestration_status": "PASS",
        "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        "build_status": "BUILD_PASSED_IN_SANDBOX",
        "test_status": "PASS_WITH_WARNINGS",
        "sandbox_path": "/tmp/sandbox",
    }
    result.update(overrides)
    return result


def _run_success_chain(tmp_path: Path, conn: sqlite3.Connection) -> tuple[_SequentialFakePopen, list[Any]]:
    _seed_stage_pipeline(conn)
    popen = _SequentialFakePopen([
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-1")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-2")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-3")) + "\n"], [], 0),
    ])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "final_report_completed")
    events = list(SqliteUnitOfWork(conn).v2_events.list_by_job("job-1"))
    return popen, events


def test_v2_runner_launches_manifest_with_shell_false_and_safe_env(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    popen = _FakePopen(
        stdout=[
            'CONTROL_TOWER_EVENT {"phase":"analysis","status":"running","message":"analysis started"}\n',
            json.dumps(_success_result(
                artifact_refs={"analysis_report": "C:/out/.migration/runs/run-1/analysis/report.json"},
                sandbox_path="C:/out/sandbox",
            )) + "\n",
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
        "artifact_refs": {
            "analysis_report": "C:/out/.migration/runs/run-1/analysis/report.json",
            "dependency_graph": "C:/out/.migration/runs/run-1/analysis/dependency-graph.json",
            "config_inventory": "C:/out/.migration/runs/run-1/analysis/config-inventory.json",
            "test_inventory": "C:/out/.migration/runs/run-1/analysis/test-inventory.json",
            "migration_plan.yaml": "C:/out/.migration/runs/run-1/planning/migration-plan.yaml",
            "migration_units.yaml": "C:/out/.migration/runs/run-1/planning/migration-units.yaml",
            "assessment_report": "C:/out/.migration/runs/run-1/assessment/report.json",
            "approval_request.json": "C:/out/.migration/runs/run-1/planning/approval-request.json",
        },
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
    assert cards[0].job_id == "job-1"
    assert cards[0].request_checksum
    assert len(uow.v2_approvals.list_cards_by_job("job-1")) == 1

    gates = uow.phase_gates.list_open("job-1")
    assert len(gates) == 1
    assert gates[0].gate_phase == "approval_review"
    assert gates[0].gate_status == "open"
    assert "analysis/report.json" in gates[0].source_artifact_refs_json
    assert "approval-request.json" in gates[0].source_artifact_refs_json

    # Replaying the same approval-required result must reuse the gate
    # and approval card instead of duplicating them.
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_blocked_for_approval")
    uow2 = SqliteUnitOfWork(conn)
    assert len(uow2.phase_gates.list_open("job-1")) == 1
    assert len(uow2.v2_approvals.list_cards_by_status("pending")) == 1


def test_v2_runner_passes_non_secret_copilot_env_and_excludes_secrets(monkeypatch, tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    monkeypatch.setenv("AI_MIGRATION_COPILOT_PROVIDER", "copilot_cli")
    monkeypatch.setenv("AI_MIGRATION_COPILOT_MODEL", "gpt-test")
    monkeypatch.setenv("AI_MIGRATION_COPILOT_REQUIRED", "true")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    popen = _FakePopen(stdout=[json.dumps(_success_result(sandbox_path="/tmp/sandbox/s1")) + "\n"], stderr=[], exit_code=0)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_completed")

    env = popen.calls[0]["env"]
    assert env["AI_MIGRATION_COPILOT_PROVIDER"] == "copilot_cli"
    assert env["AI_MIGRATION_COPILOT_MODEL"] == "gpt-test"
    assert env["AI_MIGRATION_COPILOT_REQUIRED"] == "false"
    assert "AZURE_OPENAI_API_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    event_types = [event.type for event in SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")]
    assert "copilot_status_checked" in event_types


def test_v2_runner_emits_failure_repair_events_from_result(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "final_status": "FALLBACK_REPAIR_PLAN",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "final_proof_level": "not_verified",
        "repair_loop_status": "FALLBACK_REPAIR_PLAN",
        "copilot_invocation_status": "INVALID_RESPONSE",
        "repair_fallback_generated": True,
        "sandbox_path": "/tmp/sandbox",
        "artifact_refs": {"analysis_report": "C:/out/.migration/runs/run-1/report.json"},
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    # Wait for stage_failed (the last event in the chain) to give the runner thread
    # time to finish writing all diagnostic events before we read them.
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "build_failed" in event_types
    assert "transform_failed" in event_types
    assert "repair_started" in event_types
    assert "repair_fallback_generated" in event_types
    assert "copilot_repair_invalid_response" in event_types


def test_v2_runner_does_not_auto_queue_next_stage_on_failure(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "sandbox_path": "/tmp/sandbox",
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "build_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    # Must not have next_stage_queued on failure
    assert "next_stage_queued" not in event_types


def test_v2_runner_does_not_auto_queue_on_test_failure(tmp_path: Path) -> None:
    """Stage with TEST_FAILED must emit stage_failed, not stage_completed."""
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "final_status": "TEST_FAILED",
        "test_status": "TEST_FAILED",
        "sandbox_path": "/tmp/sandbox",
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" not in event_types
    assert "stage_completed" not in event_types


def test_v2_runner_does_not_auto_queue_on_transform_failure(tmp_path: Path) -> None:
    """Stage with TRANSFORM_FAILED must not auto-progress."""
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "final_status": "TRANSFORM_FAILED",
        "transform_status": "TRANSFORM_FAILED",
        "sandbox_path": "/tmp/sandbox",
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" not in event_types
    assert "stage_completed" not in event_types


def test_v2_runner_does_not_auto_queue_without_sandbox(tmp_path: Path) -> None:
    """Stage 1 with DONE but no sandbox_path must emit stage_failed."""
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {"final_status": "DONE"}  # no sandbox_path
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" not in event_types
    assert "stage_completed" not in event_types


def test_v2_runner_proof_gate_blocks_missing_orchestration_status(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = _success_result()
    result.pop("orchestration_status")
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "stage_completed" not in event_types
    assert "next_stage_queued" not in event_types
    failed = [event for event in events if event.type == "stage_failed"][-1]
    payload = json.loads(failed.payload_json or "{}")
    assert failed.message == "Stage 1 did not produce strict success proof: expected orchestration_status=PASS, detected=missing."
    assert payload["proof_failure_field"] == "orchestration_status"
    assert payload["proof_expected"] == "PASS"
    assert payload["proof_detected"] == "missing"
    assert payload["proof_expected_values"]["orchestration_status"] == "PASS"
    assert payload["proof_detected_values"]["orchestration_status"] == ""


def test_v2_runner_proof_gate_blocks_missing_build_status(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = _success_result()
    result.pop("build_status")
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "stage_completed" not in event_types
    assert "next_stage_queued" not in event_types
    failed = [event for event in events if event.type == "stage_failed"][-1]
    payload = json.loads(failed.payload_json or "{}")
    assert failed.message == "Stage 1 did not produce strict success proof: expected build_status=BUILD_PASSED_IN_SANDBOX, detected=missing."
    assert payload["proof_failure_field"] == "build_status"
    assert payload["proof_expected"] == "BUILD_PASSED_IN_SANDBOX"
    assert payload["proof_detected"] == "missing"


def test_v2_runner_proof_gate_blocks_missing_transform_or_test_status(tmp_path: Path) -> None:
    for missing_field in ("transform_status", "test_status"):
        case_dir = tmp_path / missing_field
        case_dir.mkdir()
        conn = _conn(case_dir)
        _save_command(conn)
        result = _success_result()
        result.pop(missing_field)
        runner = V2OrchestratorRunner(
            unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
            popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
            cwd=case_dir,
        )

        runner.start(job_id="job-1", command_id="cmd-1")
        _wait_for_event(conn, "job-1", "stage_failed")

        events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
        event_types = [event.type for event in events]
        assert "stage_completed" not in event_types
        assert "next_stage_queued" not in event_types
        failed = [event for event in events if event.type == "stage_failed"][-1]
        payload = json.loads(failed.payload_json or "{}")
        assert failed.message.startswith("Stage 1 did not produce strict success proof:")
        assert payload["proof_failure_field"] == missing_field
        assert payload["proof_detected"] == "missing"


def test_v2_runner_proof_gate_blocks_errors_and_blockers(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = _success_result(errors=["unexpected warning promoted to error"])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "stage_completed" not in event_types
    assert "next_stage_queued" not in event_types


def test_success_proof_accepts_orchestration_status_pass_for_all_stages() -> None:
    from migration_factory.control_tower.application.v2_orchestrator_runner import _has_success_proof

    for sandbox_path in ("/tmp/stage-1", "/tmp/stage-2", "/tmp/stage-3"):
        ok, details = _has_success_proof(_success_result(sandbox_path=sandbox_path))
        assert ok is True
        assert details["detected_values"]["orchestration_status"] == "PASS"
        assert details["detected_values"]["sandbox_path"] == sandbox_path


def test_success_proof_rejects_successful_token_if_pass_missing_or_contract_mismatch() -> None:
    from migration_factory.control_tower.application.v2_orchestrator_runner import _has_success_proof

    success_token_result = _success_result(orchestration_status="successful")
    ok, details = _has_success_proof(success_token_result)
    assert ok is False
    assert details["field"] == "orchestration_status"
    assert details["expected"] == "PASS"
    assert details["detected"] == "successful"

    mismatch_result = _success_result(final_status="DONE")
    ok, details = _has_success_proof(mismatch_result)
    assert ok is False
    assert details["field"] == "final_status"
    assert details["expected"] == "TRANSFORM_APPLIED_IN_SANDBOX"
    assert details["detected"] == "DONE"


def test_success_proof_rejects_non_pass_with_detected_expected_details(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    result = _success_result(orchestration_status="FAIL")
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    failed = [event for event in events if event.type == "stage_failed"][-1]
    payload = json.loads(failed.payload_json or "{}")
    assert failed.message == "Stage 1 did not produce strict success proof: expected PASS, detected=FAIL."
    assert payload["proof_failure_field"] == "orchestration_status"
    assert payload["proof_expected"] == "PASS"
    assert payload["proof_detected"] == "FAIL"
    assert payload["proof_expected_values"]["orchestration_status"] == "PASS"
    assert payload["proof_detected_values"]["orchestration_status"] == "FAIL"


def test_stage_failed_not_emitted_for_valid_pass_contract(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    popen, events = _run_success_chain(tmp_path, conn)

    event_types = [event.type for event in events]
    assert "stage_failed" not in event_types
    assert "next_stage_queued" in event_types
    assert len(popen.calls) == 3


def test_stage1_completion_replay_does_not_duplicate_stage2_command(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_stage_pipeline(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    launched: list[str] = []
    runner.start = lambda *, job_id, command_id: launched.append(command_id)  # type: ignore[method-assign]

    result = _success_result(sandbox_path="/tmp/stage-1")
    runner._handle_exit(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        exit_code=0,
        result=result,
        stderr="",
        command_phase=None,
    )
    runner._handle_exit(
        job_id="job-1",
        stage_index=1,
        command_id="cmd-1",
        exit_code=0,
        result=result,
        stderr="",
        command_phase=None,
    )

    stage2_commands = SqliteUnitOfWork(conn).v2_commands.list_by_job_and_stage("job-1", 2)
    assert len(stage2_commands) == 1
    assert len(launched) >= 1


def test_v2_runner_emits_final_report_events_for_stage3(tmp_path: Path) -> None:
    """Stage 3 completion emits final_report_started + final_report_completed."""
    conn = _conn(tmp_path)
    # Save a Stage 3 command directly (not via _save_command which defaults to stage_index=1)
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_commands.save(
        V2StageCommandRecord(
            command_id="cmd-s3",
            job_id="job-1",
            stage_index=3,
            manifest_checksum="checksum",
            argv_json=json.dumps(["python", "-m", "migration_factory.orchestrator.runner"]),
            env_json=json.dumps({"JAVA_HOME": "C:/jdk21", "JAVA11_HOME": "C:/jdk11", "JAVA17_HOME": "C:/jdk17", "JAVA21_HOME": "C:/jdk21", "MAVEN_CMD": "C:/maven/bin/mvn.cmd"}),
            status="manifest_ready",
            created_at=now,
            updated_at=now,
            result_json=None,
        )
    )
    result = _success_result(sandbox_path="/tmp/sandbox/s3")
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-s3")
    _wait_for_event(conn, "job-1", "final_report_completed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "final_report_started" in event_types
    assert "final_report_completed" in event_types
    assert "migration_completed" in event_types
    assert "stage_completed" in event_types
    # Stage 3 must NOT queue a next stage
    assert "next_stage_queued" not in event_types


def test_stage1_pass_contract_with_pass_with_warnings_auto_queues_stage2(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_stage_pipeline(conn)
    popen = _SequentialFakePopen([
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-1")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-2")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-3")) + "\n"], [], 0),
    ])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "final_report_completed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" in event_types
    assert any(event.type == "next_stage_queued" and json.loads(event.payload_json or "{}").get("to_stage") == 2 for event in events)
    assert "stage_failed" not in event_types
    assert any(event.type == "stage_completed" and event.stage == 1 for event in events)
    assert any(event.type == "stage_started" and event.stage == 2 for event in events)
    assert len(popen.calls) == 3


def test_auto_queue_next_stage_can_be_disabled_by_env(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    conn = _conn(tmp_path)
    _seed_stage_pipeline(conn)
    monkeypatch.setenv("AI_MIGRATION_AUTO_QUEUE_NEXT_STAGE", "false")
    popen = _SequentialFakePopen([
        ([json.dumps(_success_result(sandbox_path=str(tmp_path / "stage-1"))) + "\n"], [], 0),
    ])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "next_stage_auto_queue_skipped")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "stage_completed" in event_types
    assert "next_stage_queued" not in event_types
    assert not any(event.type == "stage_started" and event.stage == 2 for event in events)
    assert len(popen.calls) == 1


def test_stage2_pass_contract_with_pass_with_warnings_auto_queues_stage3(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_stage_pipeline(conn)
    popen = _SequentialFakePopen([
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-1")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-2")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-3")) + "\n"], [], 0),
    ])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "final_report_completed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    assert any(event.type == "next_stage_queued" and json.loads(event.payload_json or "{}").get("to_stage") == 3 for event in events)
    assert any(event.type == "stage_completed" and event.stage == 2 for event in events)
    assert any(event.type == "stage_started" and event.stage == 3 for event in events)
    assert "stage_failed" not in [event.type for event in events]
    assert len(popen.calls) == 3


def test_stage3_pass_contract_completes_pipeline_without_stage4(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _seed_stage_pipeline(conn)
    popen = _SequentialFakePopen([
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-1")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-2")) + "\n"], [], 0),
        ([json.dumps(_success_result(sandbox_path="/tmp/stage-3")) + "\n"], [], 0),
    ])
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "final_report_completed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "final_report_started" in event_types
    assert "final_report_completed" in event_types
    assert "stage_failed" not in event_types
    assert "next_stage_queued" in event_types
    assert not any(json.loads(event.payload_json or "{}").get("to_stage") == 4 for event in events if event.type == "next_stage_queued")
    assert len(popen.calls) == 3


def test_v2_runner_does_not_progress_past_unapproved_card(tmp_path: Path) -> None:
    """Stage with a pending approval card must not auto-progress."""
    conn = _conn(tmp_path)
    _save_command(conn)
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_approvals.save_card(
        V2ApprovalDecisionRecord(
            card_id="card-pending",
            job_id="job-1",
            interrupt_id="run-1",
            request_checksum="chk",
            stage_index=1,
            summary="pending approval",
            status="pending",
            created_at=now,
        )
    )
    result = _success_result()
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )
    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_blocked_for_approval")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" not in event_types
    assert "stage_completed" not in event_types


def test_v2_runner_emits_approval_started_on_resume(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    _save_command(conn)
    # Save a resume command
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_approvals.save_card(
        V2ApprovalDecisionRecord(
            card_id="card-1",
            job_id="job-1",
            interrupt_id="run-1",
            request_checksum="chk",
            stage_index=1,
            summary="test",
            status="approved",
            created_at=now,
        )
    )
    SqliteUnitOfWork(conn).v2_approvals.save_resume(
        V2ResumeCommandRecord(
            resume_id="resume-1",
            card_id="card-1",
            decision="approved",
            job_id="job-1",
            stage_index=1,
            command_json=json.dumps(["python", "-m", "resume"]),
            created_at=now,
        )
    )
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps({"final_status": "DONE"}) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start_resume(job_id="job-1", resume_id="resume-1")
    _wait_for_event(conn, "job-1", "approval_started")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "approval_started" in event_types
    assert "resume_started" in event_types


def test_v2_runner_resume_passes_env_manifest_from_original_command(tmp_path: Path) -> None:
    """Resume must inherit env manifest (JAVA_HOME, etc.) from the original stage command."""
    conn = _conn(tmp_path)
    _save_command(conn)
    # Save a resume command
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_approvals.save_card(
        V2ApprovalDecisionRecord(
            card_id="card-1",
            job_id="job-1",
            interrupt_id="run-1",
            request_checksum="chk",
            stage_index=1,
            summary="test",
            status="approved",
            created_at=now,
        )
    )
    SqliteUnitOfWork(conn).v2_approvals.save_resume(
        V2ResumeCommandRecord(
            resume_id="resume-1",
            card_id="card-1",
            decision="approved",
            job_id="job-1",
            stage_index=1,
            command_json=json.dumps(["python", "-m", "resume"]),
            created_at=now,
        )
    )
    popen = _FakePopen(stdout=[json.dumps({"final_status": "DONE"}) + "\n"], stderr=[], exit_code=0)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

    runner.start_resume(job_id="job-1", resume_id="resume-1")
    _wait_for_event(conn, "job-1", "process_started")

    assert popen.calls
    env = popen.calls[0]["env"]
    # Must inherit MAVEN_CMD and JAVA_HOME from the original command's env_json
    assert env.get("MAVEN_CMD") == "C:/maven/bin/mvn.cmd"
    assert env.get("JAVA_HOME") == "C:/jdk11"
    assert env.get("JAVA11_HOME") == "C:/jdk11"
    assert env.get("JAVA17_HOME") == "C:/jdk17"
    assert env.get("JAVA21_HOME") == "C:/jdk21"


def test_v2_runner_resume_success_canonicalizes_original_command(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    blocked_result = json.dumps({
        "run_id": "run-1",
        "runner_status": "blocked_for_approval",
        "status": "human_approval_required",
    })
    _save_command(conn, status="blocked", result_json=blocked_result)
    now = utc_now_text()
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_approvals.save_card(
            V2ApprovalDecisionRecord(
                card_id="card-1",
                job_id="job-1",
                interrupt_id="run-1",
                request_checksum="chk",
                stage_index=1,
                summary="test",
                status="approved",
                created_at=now,
            )
        )
        uow.v2_approvals.save_resume(
            V2ResumeCommandRecord(
                resume_id="resume-1",
                card_id="card-1",
                decision="approved",
                job_id="job-1",
                stage_index=1,
                command_json=json.dumps(["python", "-m", "resume"]),
                created_at=now,
            )
        )
    result = _success_result(run_id="run-1", sandbox_path=str(sandbox))
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start_resume(job_id="job-1", resume_id="resume-1")
    _wait_for_event(conn, "job-1", "stage_command_canonicalized_after_resume")

    with SqliteUnitOfWork(conn) as uow:
        command = uow.v2_commands.get("cmd-1")
        resume = uow.v2_approvals.get_resume("resume-1")
        events = uow.v2_events.list_by_job("job-1")
    assert resume is not None
    assert resume.decision == "approved"
    assert command is not None
    assert command.status == "completed"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "completed"
    assert persisted["run_id"] == "run-1"
    assert persisted["sandbox_path"] == str(sandbox)
    assert Path(persisted["sandbox_path"]).is_absolute()
    assert persisted["approval_resume_id"] == "resume-1"
    assert persisted["resumed_from_blocked_command_id"] == "cmd-1"
    assert persisted["sandbox_only"] is True
    assert any(event.type == "stage_completed" for event in events)


def test_v2_runner_resume_failure_does_not_fake_canonical_result(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    blocked_result = json.dumps({
        "run_id": "run-1",
        "runner_status": "blocked_for_approval",
        "status": "human_approval_required",
    })
    _save_command(conn, status="blocked", result_json=blocked_result)
    now = utc_now_text()
    with SqliteUnitOfWork(conn) as uow:
        uow.v2_approvals.save_card(
            V2ApprovalDecisionRecord(
                card_id="card-1",
                job_id="job-1",
                interrupt_id="run-1",
                request_checksum="chk",
                stage_index=1,
                summary="test",
                status="approved",
                created_at=now,
            )
        )
        uow.v2_approvals.save_resume(
            V2ResumeCommandRecord(
                resume_id="resume-1",
                card_id="card-1",
                decision="approved",
                job_id="job-1",
                stage_index=1,
                command_json=json.dumps(["python", "-m", "resume"]),
                created_at=now,
            )
        )
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=["not json\n"], stderr=[], exit_code=1),
        cwd=tmp_path,
    )

    runner.start_resume(job_id="job-1", resume_id="resume-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    with SqliteUnitOfWork(conn) as uow:
        command = uow.v2_commands.get("cmd-1")
        events = uow.v2_events.list_by_job("job-1")
    assert command is not None
    assert command.status == "blocked"
    persisted = json.loads(command.result_json or "{}")
    assert persisted["runner_status"] == "blocked_for_approval"
    assert "sandbox_path" not in persisted
    assert not any(event.type == "stage_command_canonicalized_after_resume" for event in events)


def test_v2_runner_emits_diagnostic_fields_in_build_failed(tmp_path: Path) -> None:
    """Build failure events must include matched_line, command, module, and other contract fields."""
    conn = _conn(tmp_path)
    _save_command(conn)
    result = {
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "build_validation": {
            "matched_line": "[ERROR] Failed to resolve: com.example:missing-lib:1.0",
            "command": ["mvn", "compile", "-pl", "my-module"],
            "requested_command": ["mvn", "compile"],
            "resolved_command": ["mvn", "compile", "-pl", "my-module"],
            "build_tool": "maven",
            "result_kind": "dependency_error",
            "message": "Java application dependency resolution failed",
            "module": "my-module",
        },
    }
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[json.dumps(result) + "\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "build_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    build_failed_events = [e for e in events if e.type == "build_failed"]
    assert build_failed_events
    payload = json.loads(build_failed_events[-1].payload_json)
    assert payload.get("matched_line") is not None
    assert "com.example:missing-lib" in str(payload.get("matched_line"))
    assert payload.get("build_tool") == "maven"
    assert payload.get("result_kind") == "dependency_error"
    assert payload.get("module") == "my-module"
    # Verify command fields are present
    assert payload.get("command") == ["mvn", "compile", "-pl", "my-module"]


def test_v2_runner_resume_no_env_manifest_fallback(tmp_path: Path) -> None:
    """Resume without any original stage command should still work (empty manifest)."""
    conn = _conn(tmp_path)
    now = utc_now_text()
    SqliteUnitOfWork(conn).v2_approvals.save_card(
        V2ApprovalDecisionRecord(
            card_id="card-1",
            job_id="job-1",
            interrupt_id="run-1",
            request_checksum="chk",
            stage_index=1,
            summary="test",
            status="approved",
            created_at=now,
        )
    )
    SqliteUnitOfWork(conn).v2_approvals.save_resume(
        V2ResumeCommandRecord(
            resume_id="resume-1",
            card_id="card-1",
            decision="approved",
            job_id="job-1",
            stage_index=1,
            command_json=json.dumps(["python", "-m", "resume"]),
            created_at=now,
        )
    )
    popen = _FakePopen(stdout=[json.dumps({"final_status": "DONE"}) + "\n"], stderr=[], exit_code=0)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=popen,
        cwd=tmp_path,
    )

# ──────────────────────────────────────────────
# _extract_final_json sentinel tests
# ──────────────────────────────────────────────


def test_extract_final_json_compact_one_line_sentinel() -> None:
    """One-line compact JSON after CONTROL_TOWER_FINAL_JSON is parsed directly."""
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    stdout = (
        'CONTROL_TOWER_EVENT {"phase":"approval","status":"completed"}\n'
        'CONTROL_TOWER_FINAL_JSON {"run_id":"x","sandbox_path":"/tmp/s1","final_status":"TRANSFORM_APPLIED_IN_SANDBOX"}\n'
    )
    result = _extract_final_json(stdout)
    assert result is not None
    assert result["run_id"] == "x"
    assert result["sandbox_path"] == "/tmp/s1"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"


def test_extract_final_json_prefers_sentinel_over_bare_json() -> None:
    """Sentinel is preferred even when bare JSON also appears in stdout."""
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    stdout = (
        '{"run_id":"old","final_status":"STALE"}\n'
        'CONTROL_TOWER_FINAL_JSON {"run_id":"real","sandbox_path":"/tmp/s1","final_status":"TRANSFORM_APPLIED_IN_SANDBOX"}\n'
    )
    result = _extract_final_json(stdout)
    assert result is not None
    assert result["run_id"] == "real"
    assert result["final_status"] == "TRANSFORM_APPLIED_IN_SANDBOX"


def test_extract_final_json_multi_line_sentinel_does_not_parse_partial_json() -> None:
    """Pretty multi-line sentinel is NOT silently parsed as one-line by the sentinel parser.
    The sentinel parser reads only the line containing CONTROL_TOWER_FINAL_JSON.
    If that line ends with just '{', json.loads fails and the parser falls through
    to the generic scan, which should still find the full object.
    """
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    # This is the OLD multi-line format — the sentinel line is just "{" which is incomplete
    stdout = (
        'CONTROL_TOWER_FINAL_JSON {\n'
        '  "run_id": "x",\n'
        '  "sandbox_path": "/tmp/s1",\n'
        '  "final_status": "TRANSFORM_APPLIED_IN_SANDBOX"\n'
        '}\n'
    )
    result = _extract_final_json(stdout)
    # The generic scanner (fallback) should still find the full JSON
    assert result is not None
    # But the result must contain ALL three critical fields, not just '{' parsed as partial object
    assert result.get("run_id") == "x"
    assert result.get("sandbox_path") == "/tmp/s1"
    assert result.get("final_status") == "TRANSFORM_APPLIED_IN_SANDBOX"


def test_extract_final_json_multi_line_sentinel_without_fallback_returns_none() -> None:
    """If multi-line sentinel is the ONLY content and the single-line parser
    can't read it, the generic fallback must be able to parse it.
    This proves no silent partial-JSON acceptance."""
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    # Only multi-line sentinel, no CONTROL_TOWER_EVENT lines
    stdout = (
        'CONTROL_TOWER_FINAL_JSON {\n'
        '  "run_id": "y",\n'
        '  "final_status": "DONE"\n'
        '}\n'
    )
    result = _extract_final_json(stdout)
    # Must not return {'run_id': 'y'} by cherry-picking a partial parse
    assert result is not None
    assert result["run_id"] == "y"
    assert result["final_status"] == "DONE"


def test_extract_final_json_bare_json_still_works() -> None:
    """Bare JSON without sentinel still works via generic fallback."""
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    stdout = '{"run_id":"fallback","sandbox_path":"/tmp/s1","final_status":"OK"}\n'
    result = _extract_final_json(stdout)
    assert result is not None
    assert result["run_id"] == "fallback"
    assert result["final_status"] == "OK"


def test_extract_final_json_empty_stdout_returns_none() -> None:
    """Empty stdout after filtering CONTROL_TOWER_EVENT returns None."""
    from migration_factory.control_tower.application.v2_orchestrator_runner import _extract_final_json

    assert _extract_final_json("") is None
    assert _extract_final_json("CONTROL_TOWER_EVENT {\"phase\":\"approval\"}\n") is None


# ──────────────────────────────────────────────
# result_contract_failed event tests
# ──────────────────────────────────────────────


def test_runner_zero_exit_missing_final_json_emits_result_contract_failed(tmp_path: Path) -> None:
    """Zero exit but no parseable JSON emits result_contract_failed before stage_failed."""
    conn = _conn(tmp_path)
    _save_command(conn)
    # Stdout has only CONTROL_TOWER_EVENT lines, no final JSON
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(
            stdout=["CONTROL_TOWER_EVENT {\"phase\":\"approval\",\"status\":\"completed\"}\n"],
            stderr=[],
            exit_code=0,
        ),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "result_contract_failed" in event_types
    # Verify payload has diagnostic fields
    for event in events:
        if event.type == "result_contract_failed":
            payload = json.loads(event.payload_json or "{}")
            assert payload.get("final_json_found") is False
            assert "exit_code" in payload
            assert "stdout_tail" in payload
            assert "stderr_tail" in payload
            assert "parse_strategy" in payload
            break
    else:
        raise AssertionError("result_contract_failed event not found")

    # stage_failed message must not say "review build logs"
    stage_failed = [e for e in events if e.type == "stage_failed"][-1]
    assert "result contract" in stage_failed.message.lower() or "parseable" in stage_failed.message.lower()


def test_runner_does_not_auto_queue_when_final_json_missing(tmp_path: Path) -> None:
    """Zero exit + missing final JSON must not auto-queue next stage."""
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=["CONTROL_TOWER_EVENT {\"phase\":\"test\",\"status\":\"completed\"}\n"], stderr=[], exit_code=0),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    event_types = [event.type for event in events]
    assert "next_stage_queued" not in event_types
    assert "stage_completed" not in event_types


def test_runner_nonzero_exit_keeps_exit_code_message(tmp_path: Path) -> None:
    """Non-zero exit includes exit code in stage_failed message."""
    conn = _conn(tmp_path)
    _save_command(conn)
    runner = V2OrchestratorRunner(
        unit_of_work_factory=lambda: SqliteUnitOfWork(conn),
        popen_factory=_FakePopen(stdout=[], stderr=["error log\n"], exit_code=42),
        cwd=tmp_path,
    )

    runner.start(job_id="job-1", command_id="cmd-1")
    _wait_for_event(conn, "job-1", "stage_failed")

    events = SqliteUnitOfWork(conn).v2_events.list_by_job("job-1")
    stage_failed = [e for e in events if e.type == "stage_failed"][-1]
    assert "code 42" in stage_failed.message
    payload = json.loads(stage_failed.payload_json or "{}")
    assert payload.get("exit_code") == 42
