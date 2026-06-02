from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any
import xml.etree.ElementTree as ET


TEST_STATUS_PASSED = "TEST_PASSED"
TEST_STATUS_FAILED = "TEST_FAILED"
TEST_STATUS_ERROR = "TEST_ERROR"
TEST_STATUS_NO_TESTS_FOUND = "NO_TESTS_FOUND"
TEST_STATUS_NO_TESTS_EXECUTED = "NO_TESTS_EXECUTED"


@dataclass(frozen=True)
class TestAgentResult:
    test_status: str
    severity: str
    message: str
    totals: dict[str, int]
    report_path: Path
    summary_path: Path
    log_path: Path
    report_paths: list[str]
    parse_duration_seconds: float
    warnings: list[str]


def run_test_agent(
    *,
    sandbox_path: str | Path,
    run_dir: str | Path,
    run_id: str,
    source_log_path: str | Path,
    command: list[str] | None = None,
    cwd: str | None = None,
    build_succeeded: bool = False,
) -> TestAgentResult:
    resolved_sandbox = Path(sandbox_path).expanduser().resolve()
    resolved_run_dir = Path(run_dir).expanduser().resolve()
    out_dir = resolved_run_dir / "test" / "post_transform"
    out_dir.mkdir(parents=True, exist_ok=True)

    report_path = out_dir / "test_report.json"
    summary_path = out_dir / "test_summary.md"
    log_path = out_dir / "test_agent.log"

    log_lines: list[str] = []
    report_paths: list[str] = []
    totals = {"tests": 0, "passed": 0, "failures": 0, "errors": 0, "skipped": 0}
    test_status = TEST_STATUS_ERROR
    severity = "ERROR"
    message = "Test validation could not be completed."
    warnings: list[str] = []
    started = time.monotonic()
    policy_context = _load_policy_context(resolved_run_dir)

    if not resolved_sandbox.is_dir():
        message = f"Invalid sandbox path: {resolved_sandbox}"
        log_lines.append(message)
    else:
        candidates = sorted(resolved_sandbox.glob("**/target/surefire-reports/TEST-*.xml"))
        report_paths = [str(path) for path in candidates]
        if not candidates:
            if build_succeeded and _allow_missing_reports_as_warning(policy_context):
                test_status = TEST_STATUS_NO_TESTS_FOUND
                severity = "WARNING"
                message = (
                    "No Surefire reports found, but baseline analysis detected no tests and no "
                    "baseline Surefire reports. Build passed; treating as warning."
                )
                warnings.append(message)
                if policy_context["project_kind"] == "contract_library":
                    warnings.append(
                        "Contract library has no automated tests; consumer compatibility validation is required."
                    )
                log_lines.extend(warnings)
            else:
                message = _missing_reports_error_message(policy_context)
                log_lines.append(message)
        else:
            parse_error: str | None = None
            for report in candidates:
                try:
                    root = ET.parse(report).getroot()
                except (ET.ParseError, OSError) as exc:
                    parse_error = f"Unable to parse report {report}: {exc}"
                    break
                tests = _int_attr(root, "tests")
                failures = _int_attr(root, "failures")
                errors = _int_attr(root, "errors")
                skipped = _int_attr(root, "skipped")
                if min(tests, failures, errors, skipped) < 0:
                    parse_error = f"Malformed numeric attribute in report: {report}"
                    break
                passed = tests - failures - errors - skipped
                if passed < 0:
                    parse_error = f"Malformed suite counts in report: {report}"
                    break
                totals["tests"] += tests
                totals["failures"] += failures
                totals["errors"] += errors
                totals["skipped"] += skipped
                totals["passed"] += passed

            if parse_error:
                message = parse_error
                log_lines.append(parse_error)
            elif totals["failures"] > 0 or totals["errors"] > 0:
                test_status = TEST_STATUS_FAILED
                severity = "ERROR"
                message = "Surefire reports contain test failures or errors."
            else:
                test_status = TEST_STATUS_PASSED
                severity = "INFO"
                message = "Surefire reports parsed successfully."

    source_log = str(Path(source_log_path).expanduser().resolve())
    payload = {
        "schema_version": "1.0.0",
        "agent": "test-agent",
        "run_id": run_id,
        "phase": "post_transform",
        "test_status": test_status,
        "severity": severity,
        "message": message,
        "totals": totals,
        "command": command or [],
        "cwd": cwd,
        "sandbox_path": str(resolved_sandbox),
        "execution_owner": "build-agent",
        "execution_mode": "parse_existing_surefire",
        "report_paths": report_paths,
        "warnings": warnings,
        "test_log_path": str(log_path),
        "source_log_path": source_log,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "artifact_refs": {
            "self": str(report_path),
            "summary": str(summary_path),
            "log": str(log_path),
        },
        "parse_duration_seconds": round(time.monotonic() - started, 6),
    }

    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_summary_markdown(payload), encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")

    return TestAgentResult(
        test_status=test_status,
        severity=severity,
        message=message,
        totals=totals,
        report_path=report_path,
        summary_path=summary_path,
        log_path=log_path,
        report_paths=report_paths,
        parse_duration_seconds=float(payload["parse_duration_seconds"]),
        warnings=warnings,
    )


def _int_attr(root: ET.Element, attr: str) -> int:
    value = root.attrib.get(attr, "0")
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _summary_markdown(payload: dict[str, Any]) -> str:
    totals = payload["totals"]
    lines = [
        "# Test Summary (Post Transform)",
        "",
        f"- test_status: {payload['test_status']}",
        f"- severity: {payload['severity']}",
        f"- message: {payload['message']}",
        f"- tests: {totals['tests']}",
        f"- passed: {totals['passed']}",
        f"- failures: {totals['failures']}",
        f"- errors: {totals['errors']}",
        f"- skipped: {totals['skipped']}",
        f"- execution_owner: {payload['execution_owner']}",
        f"- execution_mode: {payload['execution_mode']}",
        f"- source_log_path: {payload['source_log_path']}",
    ]
    if payload["report_paths"]:
        lines.append("- report_paths:")
        lines.extend([f"  - {path}" for path in payload["report_paths"]])
    else:
        lines.append("- report_paths: []")
    if payload["warnings"]:
        lines.append("- warnings:")
        lines.extend([f"  - {warning}" for warning in payload["warnings"]])
    lines.append("")
    return "\n".join(lines)


def _load_policy_context(run_dir: Path) -> dict[str, Any]:
    analysis_dir = run_dir / "analysis"
    inventory_path = analysis_dir / "test_inventory.json"
    analysis_report_path = analysis_dir / "analysis_report.json"
    inventory = _read_json(inventory_path)
    analysis_report = _read_json(analysis_report_path)
    return {
        "policy_evidence_available": inventory_path.is_file(),
        "baseline_has_tests": _baseline_has_tests(inventory),
        "baseline_surefire_reports": _baseline_has_surefire_reports(inventory),
        "project_kind": str(analysis_report.get("project_kind", "")) if isinstance(analysis_report, dict) else "",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _baseline_has_tests(inventory: dict[str, Any]) -> bool:
    if not inventory:
        return False
    count_keys = ("test_count", "legacy_test_count", "modernized_test_count")
    if any(int(inventory.get(key, 0) or 0) > 0 for key in count_keys):
        return True
    for key in ("test_files", "tests", "missing_tests"):
        value = inventory.get(key)
        if isinstance(value, list) and value:
            return True
    return False


def _baseline_has_surefire_reports(inventory: dict[str, Any]) -> bool:
    if not inventory:
        return False
    if bool(inventory.get("surefire_reports_available")):
        return True
    summary = inventory.get("surefire_summary")
    return isinstance(summary, dict) and bool(summary.get("available"))


def _allow_missing_reports_as_warning(policy_context: dict[str, Any]) -> bool:
    return (
        bool(policy_context["policy_evidence_available"])
        and not policy_context["baseline_has_tests"]
        and not policy_context["baseline_surefire_reports"]
    )


def _missing_reports_error_message(policy_context: dict[str, Any]) -> str:
    if policy_context["baseline_has_tests"]:
        return "No Surefire reports found after build, but baseline analysis detected tests."
    if policy_context["baseline_surefire_reports"]:
        return "No Surefire reports found after build, but baseline Surefire reports existed."
    return "No Surefire reports found."
