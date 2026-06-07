from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from migration_factory.remediation.policy import LlmPolicy

BEHAVIORAL_CONTEXT_ONLY = "LLM_DISABLED_CONTEXT_ONLY"
LLM_PROPOSAL_ALLOWED_BY_POLICY = "LLM_PROPOSAL_ALLOWED_BY_POLICY"
HUMAN_REVIEW_ONLY = "HUMAN_REVIEW_ONLY"

_BEHAVIORAL_CATEGORIES = {
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
    "HTTP_STATUS_CONTRACT_DRIFT",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH",
    "APPLICATION_BEHAVIOR_REGRESSION",
    "UNKNOWN_TEST_FAILURE",
}
_SOURCE_MARKERS = {
    "CONTROLLER_ADVICE": "@ControllerAdvice",
    "REST_CONTROLLER_ADVICE": "@RestControllerAdvice",
    "RESPONSE_ENTITY_EXCEPTION_HANDLER": "ResponseEntityExceptionHandler",
    "EXCEPTION_HANDLER": "@ExceptionHandler",
    "BEAN_CONFIGURATION": "@Configuration",
    "BEAN_FACTORY_METHOD": "@Bean",
    "SERVICE_COMPONENT": "@Service",
    "AUTOWIRED": "@Autowired",
    "SECURITY_FILTER_CHAIN": "SecurityFilterChain",
}
_TEST_MARKERS = {
    "SPRING_BOOT_TEST": "@SpringBootTest",
    "WEB_MVC_TEST": "@WebMvcTest",
    "CONTEXT_CONFIGURATION": "@ContextConfiguration",
    "MOCK_MVC": "MockMvc",
    "HTTP_STATUS_ASSERTION": "status().",
    "JSON_BODY_ASSERTION": "jsonPath(",
}
_MISSING_BEAN_RE = re.compile(r"No qualifying bean of type '([^']+)'")


@dataclass(frozen=True)
class BehavioralFailureContextResult:
    context_pack_path: Path
    summary_path: Path
    llm_gate_path: Path
    payload: dict[str, Any]
    gate_payload: dict[str, Any]
    warning: str


def generate_behavioral_failure_context_pack(
    *,
    run_dir: str | Path,
    failed_unit: str,
    build_error_contract_path: str | Path | None = None,
    failure_classification_path: str | Path | None = None,
    surefire_reports_dir: str | Path | None = None,
    sandbox_project_path: str | Path | None = None,
    llm_policy: LlmPolicy | None = None,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
    orchestration_summary: dict[str, Any] | None = None,
) -> BehavioralFailureContextResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    llm_policy = llm_policy or LlmPolicy()
    build_error_contract = build_error_contract or _read_optional_json(build_error_contract_path)
    failure_classification = failure_classification or _read_optional_json(failure_classification_path)
    orchestration_summary = orchestration_summary or {}
    sandbox_root = _resolve_path(
        sandbox_project_path
        or (orchestration_summary or {}).get("sandbox_path")
        or (build_error_contract or {}).get("project_path")
    )
    surefire_dir = _resolve_path(
        surefire_reports_dir or (sandbox_root / "target" / "surefire-reports" if sandbox_root else None)
    )

    category_counts = _category_counts(build_error_contract, failure_classification)
    failing_tests = _collect_failing_tests(failure_classification, surefire_dir)
    if not category_counts and failing_tests:
        category_counts = _counts_from_failing_tests(failing_tests)
    primary_failure_message = _primary_failure_message(build_error_contract, failing_tests)
    missing_bean_errors = _missing_bean_errors(build_error_contract, failing_tests)
    affected_source_files = _collect_source_context(sandbox_root, failing_tests)
    affected_test_files = _collect_test_context(sandbox_root, failing_tests)
    suspected_framework_areas = _suspected_framework_areas(
        category_counts=category_counts,
        primary_failure_message=primary_failure_message,
        missing_bean_errors=missing_bean_errors,
        affected_source_files=affected_source_files,
        affected_test_files=affected_test_files,
    )
    deterministic_fixes = _deterministic_fixes(run_root)
    review_gates = _review_gates(run_root, sandbox_root)
    llm_candidate = bool(category_counts) or any(_behavioral_symptom(test.get("symptom", "")) for test in failing_tests)

    payload = {
        "run_id": str((orchestration_summary or {}).get("run_id") or run_root.name),
        "failed_unit": failed_unit,
        "final_status": str((orchestration_summary or {}).get("final_status") or ""),
        "build_status": str((orchestration_summary or {}).get("build_status") or ""),
        "test_status": str((orchestration_summary or {}).get("test_status") or ""),
        "primary_failure_message": primary_failure_message,
        "failing_tests": failing_tests,
        "failure_categories": category_counts,
        "missing_bean_type_errors": missing_bean_errors,
        "affected_source_files": affected_source_files,
        "affected_test_files": affected_test_files,
        "suspected_framework_areas": suspected_framework_areas,
        "deterministic_fixes_already_applied": deterministic_fixes,
        "review_gates_already_triggered": review_gates,
        "human_review_required": True,
        "safe_to_auto_apply": False,
        "llm_candidate": llm_candidate,
    }
    gate_payload = _llm_gate_payload(
        llm_policy=llm_policy,
        llm_candidate=llm_candidate,
        category_counts=category_counts,
    )
    summary_text = _render_summary(payload, gate_payload)

    context_pack_path = remediation_dir / "behavioral_failure_context_pack.json"
    summary_path = remediation_dir / "behavioral_failure_context_summary.md"
    llm_gate_path = remediation_dir / "llm_proposal_gate.json"
    context_pack_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    llm_gate_path.write_text(json.dumps(gate_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    warning = ""
    if llm_candidate:
        warning = "Behavioral failure context pack generated; human review required before any proposal workflow."
    return BehavioralFailureContextResult(
        context_pack_path=context_pack_path,
        summary_path=summary_path,
        llm_gate_path=llm_gate_path,
        payload=payload,
        gate_payload=gate_payload,
        warning=warning,
    )


def should_generate_behavioral_context(
    *,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
) -> bool:
    categories = _category_counts(build_error_contract, failure_classification)
    if any(category in _BEHAVIORAL_CATEGORIES for category in categories):
        return True
    message = " ".join(
        str((build_error_contract or {}).get(key) or "")
        for key in ("message", "matched_line")
    )
    return _behavioral_symptom(message)


def _llm_gate_payload(
    *,
    llm_policy: LlmPolicy,
    llm_candidate: bool,
    category_counts: dict[str, int],
) -> dict[str, Any]:
    decision = HUMAN_REVIEW_ONLY
    reason = "Behavioral failure requires human review."
    if llm_candidate and not llm_policy.enabled:
        decision = BEHAVIORAL_CONTEXT_ONLY
        reason = "LLM policy disabled; collect context only for human review or future governed proposal."
    elif llm_candidate and llm_policy.enabled:
        decision = LLM_PROPOSAL_ALLOWED_BY_POLICY
        reason = "LLM proposal may be prepared later under policy guardrails; no external call made now."
    return {
        "decision": decision,
        "reason": reason,
        "llm_candidate": llm_candidate,
        "human_review_required": True,
        "safe_to_auto_apply": False,
        "llm_policy": llm_policy.to_dict(),
        "failure_categories": category_counts,
    }


def _collect_failing_tests(
    failure_classification: dict[str, Any] | None,
    surefire_dir: Path | None,
) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    failures = (failure_classification or {}).get("failures")
    if isinstance(failures, list):
        for item in failures:
            if not isinstance(item, dict):
                continue
            collected.append(
                {
                    "test_class": str(item.get("test_class") or ""),
                    "test_method": str(item.get("test_method") or ""),
                    "category": str(item.get("category") or ""),
                    "symptom": str(item.get("symptom") or ""),
                    "exception_type": str(item.get("exception_type") or ""),
                }
            )
    if collected:
        return collected
    if not surefire_dir or not surefire_dir.is_dir():
        return []
    for report in sorted(surefire_dir.glob("TEST-*.xml")):
        try:
            root = ElementTree.fromstring(report.read_text(encoding="utf-8"))
        except (OSError, ElementTree.ParseError):
            continue
        for testcase in root.findall("testcase"):
            failure_node = testcase.find("failure") or testcase.find("error")
            if failure_node is None:
                continue
            symptom = str(failure_node.get("message") or failure_node.text or "").strip()
            collected.append(
                {
                    "test_class": str(testcase.get("classname") or root.get("name") or ""),
                    "test_method": str(testcase.get("name") or ""),
                    "category": _infer_category_from_symptom(symptom),
                    "symptom": _normalize_symptom(symptom),
                    "exception_type": str(failure_node.get("type") or ""),
                }
            )
    return collected


def _primary_failure_message(build_error_contract: dict[str, Any] | None, failing_tests: list[dict[str, Any]]) -> str:
    for key in ("matched_line", "message"):
        text = str((build_error_contract or {}).get(key) or "").strip()
        if text:
            return text
    for item in failing_tests:
        text = str(item.get("symptom") or "").strip()
        if text:
            return text
    return ""


def _missing_bean_errors(
    build_error_contract: dict[str, Any] | None,
    failing_tests: list[dict[str, Any]],
) -> list[dict[str, str]]:
    lines: list[str] = []
    for key in ("matched_line", "message"):
        text = str((build_error_contract or {}).get(key) or "").strip()
        if text:
            lines.append(text)
    for key in ("stdout_tail", "stderr_tail"):
        for item in list((build_error_contract or {}).get(key, []) or []):
            lines.append(str(item))
    for item in failing_tests:
        lines.append(str(item.get("symptom") or ""))
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in lines:
        match = _MISSING_BEAN_RE.search(line)
        if not match:
            continue
        bean_type = match.group(1)
        if bean_type in seen:
            continue
        seen.add(bean_type)
        errors.append({"bean_type": bean_type, "message": line.strip()})
    return errors


def _collect_source_context(sandbox_root: Path | None, failing_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _collect_file_context(
        sandbox_root=sandbox_root,
        roots=("src/main/java",),
        markers=_SOURCE_MARKERS,
        failing_tests=failing_tests,
    )


def _collect_test_context(sandbox_root: Path | None, failing_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _collect_file_context(
        sandbox_root=sandbox_root,
        roots=("src/test/java", "src/integrationTest/java"),
        markers=_TEST_MARKERS,
        failing_tests=failing_tests,
    )


def _collect_file_context(
    *,
    sandbox_root: Path | None,
    roots: tuple[str, ...],
    markers: dict[str, str],
    failing_tests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not sandbox_root or not sandbox_root.is_dir():
        return []
    target_names = {
        _simple_name(str(item.get("test_class") or ""))
        for item in failing_tests
        if str(item.get("test_class") or "").strip()
    }
    results: list[dict[str, Any]] = []
    for root_name in roots:
        root = sandbox_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.java")):
            text = _read_text(path)
            if not text:
                continue
            matched_markers = [label for label, token in markers.items() if token in text]
            if not matched_markers:
                continue
            if target_names and _simple_name(path.stem) not in target_names and "src/test/" in path.as_posix():
                if not any(_simple_name(path.stem) in name for name in target_names):
                    continue
            results.append(
                {
                    "file": str(path),
                    "class_name": _detect_class_name(text, path.stem),
                    "matched_markers": matched_markers,
                    "snippet": _snippet_for_markers(text, [markers[label] for label in matched_markers if label in markers]),
                }
            )
    return results[:12]


def _suspected_framework_areas(
    *,
    category_counts: dict[str, int],
    primary_failure_message: str,
    missing_bean_errors: list[dict[str, str]],
    affected_source_files: list[dict[str, Any]],
    affected_test_files: list[dict[str, Any]],
) -> list[str]:
    areas: list[str] = []
    for category in category_counts:
        if category == "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT":
            areas.extend(["Spring MVC", "ControllerAdvice", "ExceptionHandler"])
        elif category == "HTTP_STATUS_CONTRACT_DRIFT":
            areas.extend(["Spring MVC", "ControllerAdvice"])
        elif category == "JAKARTA_VALIDATION_HANDLER_MISMATCH":
            areas.extend(["Validation", "ExceptionHandler"])
        elif category == "UNKNOWN_TEST_FAILURE":
            areas.extend(["ApplicationContext", "Test configuration"])
    if missing_bean_errors or "No qualifying bean of type" in primary_failure_message:
        areas.extend(["ApplicationContext", "Bean wiring"])
    if "Failed to load ApplicationContext" in primary_failure_message:
        areas.extend(["ApplicationContext", "Test configuration"])
    if "Request processing failed" in primary_failure_message:
        areas.extend(["Spring MVC", "ExceptionHandler"])
    joined = "\n".join(
        [
            *(str(item.get("snippet") or "") for item in affected_source_files),
            *(str(item.get("snippet") or "") for item in affected_test_files),
        ]
    )
    if "ResponseEntityExceptionHandler" in joined or "@ControllerAdvice" in joined or "@RestControllerAdvice" in joined:
        areas.extend(["ControllerAdvice", "ExceptionHandler"])
    if "SecurityFilterChain" in joined:
        areas.append("Security")
    return _dedupe_preserve_order(areas)


def _deterministic_fixes(run_dir: Path) -> list[dict[str, str]]:
    ledger_path = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"
    payload = _read_optional_json(ledger_path)
    transformations = list((payload or {}).get("transformations", []) or [])
    fixes: list[dict[str, str]] = []
    for item in transformations:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        if status not in {"applied", "updated"}:
            continue
        fixes.append(
            {
                "type": str(item.get("type") or item.get("op") or ""),
                "status": status,
                "unit": str(item.get("unit") or item.get("unit_id") or ""),
            }
        )
    return fixes


def _review_gates(run_dir: Path, sandbox_root: Path | None) -> list[dict[str, str]]:
    gates: list[dict[str, str]] = []
    directories = [run_dir / "review"]
    if sandbox_root:
        directories.append(sandbox_root / ".migration" / "review")
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            payload = _read_optional_json(path)
            gate_id = str((payload or {}).get("gate_id") or path.stem)
            gates.append({"gate_id": gate_id, "path": str(path)})
    return gates


def _render_summary(payload: dict[str, Any], gate_payload: dict[str, Any]) -> str:
    lines = [
        "# Behavioral Failure Context Summary",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Final Status: {payload.get('final_status', '')}",
        f"- Build Status: {payload.get('build_status', '')}",
        f"- Test Status: {payload.get('test_status', '')}",
        f"- Primary Failure: {payload.get('primary_failure_message', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- LLM Candidate: {str(payload.get('llm_candidate')).lower()}",
        f"- LLM Gate Decision: {gate_payload.get('decision', '')}",
        "",
        "## Failure Categories",
        "",
    ]
    for category, count in dict(payload.get("failure_categories", {}) or {}).items():
        lines.append(f"- {category}: {count}")
    missing_beans = list(payload.get("missing_bean_type_errors", []) or [])
    if missing_beans:
        lines.extend(["", "## Missing Bean Signals", ""])
        for item in missing_beans[:6]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('bean_type', '')}")
    lines.extend(["", "## Suspected Framework Areas", ""])
    for area in list(payload.get("suspected_framework_areas", []) or []):
        lines.append(f"- {area}")
    lines.extend(["", "## Recommended Next Step", "", f"- {gate_payload.get('reason', '')}"])
    return "\n".join(lines).rstrip() + "\n"


def _category_counts(
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
) -> dict[str, int]:
    for payload in (failure_classification, build_error_contract):
        if not isinstance(payload, dict):
            continue
        raw = payload.get("category_counts") if "category_counts" in payload else payload.get("failure_categories")
        if isinstance(raw, dict):
            return {str(key): int(value) for key, value in raw.items()}
    return {}


def _infer_category_from_symptom(symptom: str) -> str:
    if "expected:<" in symptom and "but was:<" in symptom:
        return "HTTP_STATUS_CONTRACT_DRIFT"
    if "Failed to load ApplicationContext" in symptom:
        return "UNKNOWN_TEST_FAILURE"
    if "ConstraintViolationException" in symptom:
        return "JAKARTA_VALIDATION_HANDLER_MISMATCH"
    if "Request processing failed" in symptom:
        return "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT"
    return "UNKNOWN_TEST_FAILURE"


def _counts_from_failing_tests(failing_tests: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in failing_tests:
        category = str(item.get("category") or "").strip()
        if not category:
            continue
        counts[category] = counts.get(category, 0) + 1
    return counts


def _behavioral_symptom(text: str) -> bool:
    return any(
        token in text
        for token in (
            "No qualifying bean of type",
            "NoSuchBeanDefinitionException",
            "Failed to load ApplicationContext",
            "Request processing failed",
            "expected:<",
            "ConstraintViolationException",
        )
    )


def _normalize_symptom(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").strip()


def _snippet_for_markers(text: str, tokens: list[str]) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if any(token in line for token in tokens):
            start = max(0, index - 1)
            end = min(len(lines), index + 3)
            return "\n".join(lines[start:end]).strip()
    return ""


def _simple_name(value: str) -> str:
    text = str(value or "").strip()
    return text.rsplit(".", 1)[-1]


def _detect_class_name(text: str, fallback: str) -> str:
    match = re.search(r"\bclass\s+([A-Za-z0-9_]+)", text)
    if match:
        return match.group(1)
    return fallback


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _resolve_path(path_like: Any) -> Path | None:
    text = str(path_like or "").strip()
    if not text:
        return None
    return Path(text).expanduser().resolve()


def _read_optional_json(path_like: Any) -> dict[str, Any] | None:
    path = _resolve_path(path_like)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
