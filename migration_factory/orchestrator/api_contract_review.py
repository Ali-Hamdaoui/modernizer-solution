from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


API_CONTRACT_REVIEW_GATE = "API_CONTRACT_REVIEW_GATE"
API_CONTRACT_CATEGORIES = {
    "HTTP_STATUS_CONTRACT_DRIFT",
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH",
    "APPLICATION_BEHAVIOR_REGRESSION",
}
SOURCE_HINT_MARKERS: tuple[tuple[str, str], ...] = (
    ("CONTROLLER_ADVICE", "@ControllerAdvice"),
    ("REST_CONTROLLER_ADVICE", "@RestControllerAdvice"),
    ("RESPONSE_ENTITY_EXCEPTION_HANDLER", "ResponseEntityExceptionHandler"),
    ("ZALANDO_PROBLEM", "org.zalando.problem"),
    ("ADVICE_TRAIT", "AdviceTrait"),
)
TEST_HINT_MARKERS: tuple[tuple[str, str], ...] = (
    ("HTTP_STATUS_ASSERTION", "status().is"),
    ("HTTP_STATUS_ASSERTION", "andExpect(status()."),
    ("RESPONSE_BODY_ASSERTION", "jsonPath("),
    ("RESPONSE_BODY_ASSERTION", "content().json("),
    ("RESPONSE_BODY_ASSERTION", "content().string("),
    ("PROBLEM_PAYLOAD_ASSERTION", "Problem"),
    ("PROBLEM_PAYLOAD_ASSERTION", "application/problem+json"),
)


@dataclass(frozen=True)
class ApiContractReviewResult:
    artifact_path: Path
    detected: bool
    warning: str


def build_api_contract_review(
    *,
    run_dir: Path,
    sandbox_path: Path | None,
    build_error_contract: dict[str, Any] | None = None,
    failure_classification: dict[str, Any] | None = None,
    orchestration_summary: dict[str, Any] | None = None,
) -> ApiContractReviewResult:
    run_dir = Path(run_dir).expanduser().resolve()
    sandbox_root = Path(sandbox_path).expanduser().resolve() if sandbox_path else None
    classification = failure_classification if isinstance(failure_classification, dict) else {}
    build_error = build_error_contract if isinstance(build_error_contract, dict) else {}
    summary = orchestration_summary if isinstance(orchestration_summary, dict) else {}
    category_counts = _category_counts(build_error, classification)
    relevant_categories = [category for category in category_counts if category in API_CONTRACT_CATEGORIES]
    surefire_hints = _scan_surefire_reports(sandbox_root)
    source_hints = _scan_source_hints(sandbox_root)
    test_hints = _scan_test_hints(sandbox_root)
    affected_tests = _affected_tests(classification, surefire_hints, test_hints)
    affected_source_files = _affected_source_files(source_hints)
    suspected_contract_areas = _suspected_contract_areas(
        relevant_categories=relevant_categories,
        source_hints=source_hints,
        test_hints=test_hints,
    )
    detected = bool(relevant_categories or surefire_hints["detected_categories"])
    detected_failure_categories = _dedupe_preserve_order(
        [*relevant_categories, *surefire_hints["detected_categories"]]
    )
    human_review_required = detected
    payload = {
        "run_id": str(summary.get("run_id") or ""),
        "detected": detected,
        "gate_id": API_CONTRACT_REVIEW_GATE,
        "risk_level": "HIGH" if detected else "NONE",
        "human_review_required": human_review_required,
        "safe_to_auto_apply": False,
        "detected_failure_categories": detected_failure_categories,
        "category_counts": {key: int(value) for key, value in category_counts.items() if key in detected_failure_categories},
        "affected_tests": affected_tests,
        "affected_source_files": affected_source_files,
        "suspected_contract_areas": suspected_contract_areas,
        "recommended_next_actions": _recommended_next_actions(
            detected_failure_categories,
            source_hints=source_hints,
            test_hints=test_hints,
        ),
    }
    artifact_path = run_dir / "review" / "api_contract_review.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    warning = ""
    if detected:
        warning = "API contract drift detected; human review required before changing controller/advice behavior or test expectations."
    return ApiContractReviewResult(
        artifact_path=artifact_path,
        detected=detected,
        warning=warning,
    )


def _category_counts(build_error_contract: dict[str, Any], failure_classification: dict[str, Any]) -> dict[str, int]:
    raw = failure_classification.get("category_counts")
    if not isinstance(raw, dict):
        raw = build_error_contract.get("failure_categories")
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for key, value in raw.items():
        try:
            counts[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return counts


def _scan_surefire_reports(sandbox_root: Path | None) -> dict[str, Any]:
    result = {
        "detected_categories": [],
        "tests": [],
    }
    if sandbox_root is None or not sandbox_root.is_dir():
        return result
    category_set: set[str] = set()
    tests: list[dict[str, Any]] = []
    for report in sorted(sandbox_root.glob("**/target/surefire-reports/TEST-*.xml")):
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, OSError):
            continue
        suite_name = str(root.attrib.get("name") or "")
        for testcase in root.findall("testcase"):
            test_class = str(testcase.attrib.get("classname") or suite_name or "")
            test_method = str(testcase.attrib.get("name") or "")
            for outcome in ("failure", "error"):
                detail = testcase.find(outcome)
                if detail is None:
                    continue
                message = str(detail.attrib.get("message") or "")
                detail_text = str(detail.text or "")
                hint_categories = _classify_api_contract_text("\n".join((message, detail_text)))
                for category in hint_categories:
                    category_set.add(category)
                if hint_categories:
                    tests.append(
                        {
                            "test_class": test_class,
                            "test_method": test_method,
                            "detected_categories": hint_categories,
                            "symptom": _first_nonempty_line(message, detail_text),
                            "evidence": str(report.relative_to(sandbox_root)),
                        }
                    )
    result["detected_categories"] = sorted(category_set)
    result["tests"] = tests
    return result


def _scan_source_hints(sandbox_root: Path | None) -> list[dict[str, Any]]:
    if sandbox_root is None or not sandbox_root.is_dir():
        return []
    findings: list[dict[str, Any]] = []
    source_root = sandbox_root / "src"
    if not source_root.is_dir():
        return findings
    for path in sorted(source_root.rglob("*.java")):
        rel = _safe_relative(path, sandbox_root)
        if not rel or _is_test_path(rel):
            continue
        text = _read_text(path)
        markers = [label for label, marker in SOURCE_HINT_MARKERS if marker in text]
        if not markers:
            continue
        findings.append(
            {
                "file": rel,
                "markers": _dedupe_preserve_order(markers),
            }
        )
    return findings


def _scan_test_hints(sandbox_root: Path | None) -> list[dict[str, Any]]:
    if sandbox_root is None or not sandbox_root.is_dir():
        return []
    findings: list[dict[str, Any]] = []
    source_root = sandbox_root / "src"
    if not source_root.is_dir():
        return findings
    for path in sorted(source_root.rglob("*.java")):
        rel = _safe_relative(path, sandbox_root)
        if not rel or not _is_test_path(rel):
            continue
        text = _read_text(path)
        markers = [label for label, marker in TEST_HINT_MARKERS if marker in text]
        if not markers:
            continue
        findings.append(
            {
                "file": rel,
                "markers": _dedupe_preserve_order(markers),
            }
        )
    return findings


def _affected_tests(
    failure_classification: dict[str, Any],
    surefire_hints: dict[str, Any],
    test_hints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    classification_failures = failure_classification.get("failures")
    rows: list[dict[str, Any]] = []
    if isinstance(classification_failures, list):
        for item in classification_failures:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            if category not in API_CONTRACT_CATEGORIES:
                continue
            rows.append(
                {
                    "test_class": str(item.get("test_class") or ""),
                    "test_method": str(item.get("test_method") or ""),
                    "category": category,
                    "symptom": str(item.get("symptom") or ""),
                    "suggested_next_action": str(item.get("suggested_next_action") or ""),
                    "test_hint_files": _matching_test_hint_files(str(item.get("test_class") or ""), test_hints),
                }
            )
    if rows:
        return rows
    fallback: list[dict[str, Any]] = []
    for item in list(surefire_hints.get("tests") or []):
        if not isinstance(item, dict):
            continue
        for category in list(item.get("detected_categories") or []):
            if category not in API_CONTRACT_CATEGORIES:
                continue
            fallback.append(
                {
                    "test_class": str(item.get("test_class") or ""),
                    "test_method": str(item.get("test_method") or ""),
                    "category": category,
                    "symptom": str(item.get("symptom") or ""),
                    "suggested_next_action": _category_next_action(category),
                    "test_hint_files": _matching_test_hint_files(str(item.get("test_class") or ""), test_hints),
                }
            )
    return fallback


def _affected_source_files(source_hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "file": str(item.get("file") or ""),
            "markers": list(item.get("markers") or []),
        }
        for item in source_hints
    ]


def _suspected_contract_areas(
    *,
    relevant_categories: list[str],
    source_hints: list[dict[str, Any]],
    test_hints: list[dict[str, Any]],
) -> list[str]:
    areas: list[str] = []
    if "HTTP_STATUS_CONTRACT_DRIFT" in relevant_categories:
        areas.append("http_status_mapping")
    if "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT" in relevant_categories:
        areas.append("controller_advice_behavior")
    if "JAKARTA_VALIDATION_HANDLER_MISMATCH" in relevant_categories:
        areas.append("validation_exception_mapping")
    if "APPLICATION_BEHAVIOR_REGRESSION" in relevant_categories:
        areas.append("application_runtime_behavior")
    if any("ZALANDO_PROBLEM" in list(item.get("markers") or []) or "ADVICE_TRAIT" in list(item.get("markers") or []) for item in source_hints):
        areas.append("problem_json_payload_contract")
    if any("RESPONSE_BODY_ASSERTION" in list(item.get("markers") or []) or "PROBLEM_PAYLOAD_ASSERTION" in list(item.get("markers") or []) for item in test_hints):
        areas.append("response_body_contract")
    return _dedupe_preserve_order(areas)


def _recommended_next_actions(
    detected_failure_categories: list[str],
    *,
    source_hints: list[dict[str, Any]],
    test_hints: list[dict[str, Any]],
) -> list[str]:
    actions: list[str] = []
    if detected_failure_categories:
        actions.append("Review whether legacy API behavior must be preserved for consumers before changing controller/advice implementation.")
        actions.append("If Spring Boot 3 behavior is acceptable, update tests only after product/API owner decision.")
        actions.append("Require consumer compatibility validation for externally visible HTTP status, exception, and payload changes.")
    if "HTTP_STATUS_CONTRACT_DRIFT" in detected_failure_categories:
        actions.append("Compare legacy and migrated HTTP status mappings and decide whether to preserve legacy status codes or accept new framework defaults.")
    if "JAKARTA_VALIDATION_HANDLER_MISMATCH" in detected_failure_categories:
        actions.append("Review validation exception handler contract for javax-to-jakarta runtime drift before changing source or tests.")
    if any("RESPONSE_ENTITY_EXCEPTION_HANDLER" in list(item.get("markers") or []) for item in source_hints):
        actions.append("Review ResponseEntityExceptionHandler / controller advice overrides for Spring 6 contract differences.")
    if any("PROBLEM_PAYLOAD_ASSERTION" in list(item.get("markers") or []) for item in test_hints):
        actions.append("Compare Problem/JSON payload shape with legacy consumers before accepting payload drift.")
    return _dedupe_preserve_order(actions)


def _classify_api_contract_text(text: str) -> list[str]:
    categories: list[str] = []
    lower = text.lower()
    if re.search(r"expected:<\d{3}> but was:<\d{3}>", text):
        categories.append("HTTP_STATUS_CONTRACT_DRIFT")
    if "jakarta.validation.constraintviolationexception" in lower:
        categories.append("JAKARTA_VALIDATION_HANDLER_MISMATCH")
    if (
        "request processing failed" in lower
        or "responseentityexceptionhandler" in lower
        or "exceptiontranslator" in lower
    ):
        categories.append("SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT")
    if (
        "assertionerror" in lower
        or "comparisonfailure" in lower
        or "nosuchelementexception" in lower
        or "problem" in lower
    ):
        categories.append("APPLICATION_BEHAVIOR_REGRESSION")
    return _dedupe_preserve_order(categories)


def _matching_test_hint_files(test_class: str, test_hints: list[dict[str, Any]]) -> list[str]:
    class_suffix = test_class.split(".")[-1] if test_class else ""
    matches: list[str] = []
    for item in test_hints:
        file_path = str(item.get("file") or "")
        if class_suffix and file_path.endswith(f"{class_suffix}.java"):
            matches.append(file_path)
    return matches


def _category_next_action(category: str) -> str:
    actions = {
        "HTTP_STATUS_CONTRACT_DRIFT": "Review expected HTTP status codes and exception-to-response mappings under Spring Boot 3.",
        "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": "Review controller advice / exception handler behavior under Spring Framework 6.",
        "JAKARTA_VALIDATION_HANDLER_MISMATCH": "Review jakarta.validation runtime behavior against legacy handler contract.",
        "APPLICATION_BEHAVIOR_REGRESSION": "Review behavioral drift before changing source or tests.",
    }
    return actions.get(category, "Manual API contract review required.")


def _first_nonempty_line(*parts: str) -> str:
    for part in parts:
        for line in part.splitlines():
            text = line.strip()
            if text:
                return text
    return ""


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return ""


def _is_test_path(relative_path: str) -> bool:
    parts = [part.lower() for part in Path(relative_path).parts[:-1]]
    return any("test" in part for part in parts)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped
