from __future__ import annotations

import json
from pathlib import Path

from migration_factory.agents.test_agent import run_test_agent


def test_test_agent_parses_surefire_pass(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-A.xml").write_text(
        '<testsuite tests="3" failures="0" errors="0" skipped="1"></testsuite>',
        encoding="utf-8",
    )

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
        command=["mvn", "clean", "test"],
        cwd=str(sandbox),
    )

    assert result.test_status == "TEST_PASSED"
    assert result.totals == {"tests": 3, "passed": 2, "failures": 0, "errors": 0, "skipped": 1}
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["execution_mode"] == "parse_existing_surefire"
    assert payload["execution_owner"] == "build-agent"
    assert payload["parse_duration_seconds"] >= 0


def test_test_agent_parses_surefire_failed(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    reports = sandbox / "module" / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-A.xml").write_text(
        '<testsuite tests="2" failures="1" errors="0" skipped="0"></testsuite>',
        encoding="utf-8",
    )

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
    )

    assert result.test_status == "TEST_FAILED"
    assert result.totals["failures"] == 1


def test_test_agent_missing_reports_is_error(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
    )

    assert result.test_status == "TEST_ERROR"
    assert result.report_paths == []


def test_test_agent_malformed_report_is_error(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-A.xml").write_text("<testsuite", encoding="utf-8")

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
    )

    assert result.test_status == "TEST_ERROR"


def test_test_agent_skipped_only_is_pass(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    reports = sandbox / "target" / "surefire-reports"
    reports.mkdir(parents=True)
    (reports / "TEST-A.xml").write_text(
        '<testsuite tests="2" failures="0" errors="0" skipped="2"></testsuite>',
        encoding="utf-8",
    )

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
    )

    assert result.test_status == "TEST_PASSED"
    assert result.totals["passed"] == 0
