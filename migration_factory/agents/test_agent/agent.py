from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


TEST_STATUS_PASSED = "TEST_PASSED"
TEST_STATUS_FAILED = "TEST_FAILED"
TEST_STATUS_ERROR = "TEST_ERROR"


@dataclass(frozen=True)
class TestAgentResult:
    test_status: str
    totals: dict[str, int]
    report_path: Path
    summary_path: Path
    log_path: Path
    report_paths: list[str]


def run_test_agent(
    *,
    sandbox_path: str | Path,
    run_dir: str | Path,
    run_id: str,
    source_log_path: str | Path,
    command: list[str] | None = None,
    cwd: str | None = None,
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

    if not resolved_sandbox.is_dir():
        log_lines.append(f"Invalid sandbox path: {resolved_sandbox}")
    else:
        candidates = sorted(resolved_sandbox.glob("**/target/surefire-reports/TEST-*.xml"))
        report_paths = [str(path) for path in candidates]
        if not candidates:
            log_lines.append("No surefire reports found.")
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
                log_lines.append(parse_error)
            elif totals["failures"] > 0 or totals["errors"] > 0:
                test_status = TEST_STATUS_FAILED
            else:
                test_status = TEST_STATUS_PASSED

    source_log = str(Path(source_log_path).expanduser().resolve())
    payload = {
        "schema_version": "1.0.0",
        "agent": "test-agent",
        "run_id": run_id,
        "phase": "post_transform",
        "test_status": test_status,
        "totals": totals,
        "command": command or [],
        "cwd": cwd,
        "sandbox_path": str(resolved_sandbox),
        "execution_owner": "build-agent",
        "execution_mode": "parse_existing_surefire",
        "report_paths": report_paths,
        "test_log_path": str(log_path),
        "source_log_path": source_log,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "artifact_refs": {
            "self": str(report_path),
            "summary": str(summary_path),
            "log": str(log_path),
        },
    }

    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_summary_markdown(payload), encoding="utf-8")
    log_path.write_text("\n".join(log_lines) + ("\n" if log_lines else ""), encoding="utf-8")

    return TestAgentResult(
        test_status=test_status,
        totals=totals,
        report_path=report_path,
        summary_path=summary_path,
        log_path=log_path,
        report_paths=report_paths,
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
    lines.append("")
    return "\n".join(lines)
