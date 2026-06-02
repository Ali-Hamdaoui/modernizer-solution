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
    assert result.severity == "INFO"
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
    assert result.severity == "ERROR"
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
    assert "No Surefire reports found" in result.message


def test_test_agent_missing_reports_with_baseline_tests_is_error(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    analysis = tmp_path / "run" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "test_inventory.json").write_text(json.dumps({"test_count": 2}), encoding="utf-8")
    (analysis / "analysis_report.json").write_text(json.dumps({"project_kind": "shared_library"}), encoding="utf-8")

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
        build_succeeded=True,
    )

    assert result.test_status == "TEST_ERROR"
    assert "baseline analysis detected tests" in result.message


def test_test_agent_no_tests_build_passed_is_warning(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    analysis = tmp_path / "run" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "test_inventory.json").write_text(
        json.dumps({"test_count": 0, "test_files": [], "surefire_summary": {"available": False}}),
        encoding="utf-8",
    )
    (analysis / "analysis_report.json").write_text(json.dumps({"project_kind": "shared_library"}), encoding="utf-8")

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
        build_succeeded=True,
    )

    assert result.test_status == "NO_TESTS_FOUND"
    assert result.severity == "WARNING"
    assert "Build passed" in result.message
    assert result.warnings == [result.message]


def test_test_agent_contract_library_no_tests_adds_consumer_warning(tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    analysis = tmp_path / "run" / "analysis"
    analysis.mkdir(parents=True)
    (analysis / "test_inventory.json").write_text(json.dumps({"test_count": 0}), encoding="utf-8")
    (analysis / "analysis_report.json").write_text(json.dumps({"project_kind": "contract_library"}), encoding="utf-8")

    result = run_test_agent(
        sandbox_path=sandbox,
        run_dir=tmp_path / "run",
        run_id="run-001",
        source_log_path=tmp_path / "phase2.log",
        build_succeeded=True,
    )

    assert result.test_status == "NO_TESTS_FOUND"
    assert any("consumer compatibility validation is required" in warning for warning in result.warnings)


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
    assert result.severity == "ERROR"


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
