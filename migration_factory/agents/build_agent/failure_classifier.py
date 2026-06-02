from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import re
from typing import Any
import xml.etree.ElementTree as ET


ARTIFACT_NAME = "post_transform_failure_classification.json"
SCHEMA_VERSION = "1.0.0"

SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT = "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT"
JAKARTA_VALIDATION_HANDLER_MISMATCH = "JAKARTA_VALIDATION_HANDLER_MISMATCH"
HTTP_STATUS_CONTRACT_DRIFT = "HTTP_STATUS_CONTRACT_DRIFT"
MOCKITO_FINAL_CLASS_MOCKING_LIMITATION = "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION"
APPLICATION_BEHAVIOR_REGRESSION = "APPLICATION_BEHAVIOR_REGRESSION"
UNKNOWN_TEST_FAILURE = "UNKNOWN_TEST_FAILURE"


@dataclass(frozen=True)
class ClassifiedTestFailure:
    test_class: str
    test_method: str
    outcome: str
    symptom: str
    exception_type: str
    category: str
    suggested_next_action: str


@dataclass(frozen=True)
class FailureClassificationArtifact:
    schema_version: str
    agent: str
    created_at: str
    project_path: str
    unit_id: str | None
    suite_count: int
    failure_count: int
    category_counts: dict[str, int]
    failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FailureClassificationResult:
    artifact_path: Path | None
    category_counts: dict[str, int]
    failures: list[ClassifiedTestFailure]


def classify_post_transform_test_failures(
    project_path: str | Path,
    *,
    output_dir: str | Path,
    unit_id: str | None = None,
) -> FailureClassificationResult:
    project_root = Path(project_path).expanduser().resolve()
    reports = sorted(project_root.glob("**/target/surefire-reports/TEST-*.xml"))
    if not reports:
        return FailureClassificationResult(None, {}, [])

    context = _build_context(project_root)
    failures: list[ClassifiedTestFailure] = []
    suite_count = 0

    for report in reports:
        try:
            root = ET.parse(report).getroot()
        except (ET.ParseError, OSError):
            continue
        suite_count += 1
        suite_name = str(root.attrib.get("name") or "")
        for testcase in root.findall("testcase"):
            for outcome in ("failure", "error"):
                detail = testcase.find(outcome)
                if detail is None:
                    continue
                test_class = str(testcase.attrib.get("classname") or suite_name or "")
                test_method = str(testcase.attrib.get("name") or "")
                exception_type = str(detail.attrib.get("type") or "").strip()
                message = str(detail.attrib.get("message") or "").strip()
                detail_text = (detail.text or "").strip()
                symptom = _symptom(message, detail_text)
                category = _classify_failure(
                    test_class=test_class,
                    test_method=test_method,
                    outcome=outcome,
                    exception_type=exception_type,
                    message=message,
                    detail_text=detail_text,
                    context=context,
                )
                failures.append(
                    ClassifiedTestFailure(
                        test_class=test_class,
                        test_method=test_method,
                        outcome=outcome,
                        symptom=symptom,
                        exception_type=exception_type,
                        category=category,
                        suggested_next_action=_suggested_next_action(category),
                    )
                )

    if not failures:
        return FailureClassificationResult(None, {}, [])

    category_counts: dict[str, int] = {}
    for item in failures:
        category_counts[item.category] = category_counts.get(item.category, 0) + 1

    payload = FailureClassificationArtifact(
        schema_version=SCHEMA_VERSION,
        agent="build-agent",
        created_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        project_path=str(project_root),
        unit_id=unit_id,
        suite_count=suite_count,
        failure_count=len(failures),
        category_counts=category_counts,
        failures=[asdict(item) for item in failures],
    )
    output_path = Path(output_dir).expanduser().resolve() / ARTIFACT_NAME
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(payload), indent=2) + "\n", encoding="utf-8")
    return FailureClassificationResult(output_path, category_counts, failures)


def _build_context(project_root: Path) -> dict[str, bool]:
    return {
        "has_legacy_constraint_handler": _has_legacy_constraint_handler(project_root),
    }


def _has_legacy_constraint_handler(project_root: Path) -> bool:
    source_root = project_root / "src" / "main" / "java"
    if not source_root.is_dir():
        return False
    for java_file in source_root.rglob("*.java"):
        try:
            text = java_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = java_file.read_text(encoding="latin-1")
        if "handleConstraintViolation" not in text:
            continue
        if "javax.validation.ConstraintViolationException" in text:
            return True
    return False


def _symptom(message: str, detail_text: str) -> str:
    for candidate in (message, detail_text):
        for line in candidate.splitlines():
            text = line.strip()
            if text:
                return text
    return "Unknown test failure symptom"


def _classify_failure(
    *,
    test_class: str,
    test_method: str,
    outcome: str,
    exception_type: str,
    message: str,
    detail_text: str,
    context: dict[str, bool],
) -> str:
    haystack = "\n".join(
        part for part in (test_class, test_method, outcome, exception_type, message, detail_text) if part
    )
    lower = haystack.lower()

    if (
        "cannot mock" in lower
        and "final class" in lower
    ) or "cannot mock/spy class" in lower:
        return MOCKITO_FINAL_CLASS_MOCKING_LIMITATION

    if re.search(r"expected:<\d{3}> but was:<\d{3}>", haystack):
        return HTTP_STATUS_CONTRACT_DRIFT

    if (
        "jakarta.validation.constraintviolationexception" in lower
        and context.get("has_legacy_constraint_handler", False)
    ):
        return JAKARTA_VALIDATION_HANDLER_MISMATCH

    if (
        "request processing failed" in lower
        or "responseentityexceptionhandler" in lower
        or "exceptiontranslator" in lower
        or test_class.endswith("ExceptionTranslatorTest")
    ):
        return SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT

    if (
        "nosuchelementexception" in lower
        or "badrequestlistexception" in lower
        or "jwtexception" in lower
        or "assertionerror" in lower
        or "comparisonfailure" in lower
    ):
        return APPLICATION_BEHAVIOR_REGRESSION

    return UNKNOWN_TEST_FAILURE


def _suggested_next_action(category: str) -> str:
    actions = {
        SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: (
            "Review controller advice / ResponseEntityExceptionHandler overrides for Spring 6 behavior changes."
        ),
        JAKARTA_VALIDATION_HANDLER_MISMATCH: (
            "Align validation exception handling between jakarta.validation runtime types and legacy javax handler signatures."
        ),
        HTTP_STATUS_CONTRACT_DRIFT: (
            "Review expected HTTP status codes and exception-to-response mappings under Spring Boot 3."
        ),
        MOCKITO_FINAL_CLASS_MOCKING_LIMITATION: (
            "Review test double strategy for final classes or enable supported Mockito inline/final-class configuration."
        ),
        APPLICATION_BEHAVIOR_REGRESSION: (
            "Review behavioral drift in migrated code path and update migration plan with targeted deterministic fixes."
        ),
        UNKNOWN_TEST_FAILURE: (
            "Review failing test stack trace manually and add a new deterministic classifier or fix path if pattern repeats."
        ),
    }
    return actions[category]
