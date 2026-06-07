from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


LEGACY_BEHAVIOR_EQUIVALENCE_GATE = "LEGACY_BEHAVIOR_EQUIVALENCE_REVIEW"
_MISSING_BEAN_RE = re.compile(r"No qualifying bean of type '([^']+)'")
_NO_SUCH_BEAN_RE = re.compile(r"NoSuchBeanDefinitionException(?::|\b).*?'([^']+)'")
_CLASS_RE = re.compile(r"\b(class|interface|enum|record)\s+([A-Za-z_][A-Za-z0-9_]*)")
_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z0-9_$.]+)\s*;", re.MULTILINE)
_BEAN_METHOD_TEMPLATE = r"@Bean[\s\S]{{0,240}}?\b{simple}\b\s+[A-Za-z_][A-Za-z0-9_]*\s*\("
_ANNOTATED_TYPE_TEMPLATE = r"@(?:MockBean|MockitoBean)[\s\S]{{0,120}}?\b{simple}\b\s+[A-Za-z_][A-Za-z0-9_]*\s*[;=]"
_FIELD_INJECTION_TEMPLATE = r"@Autowired[\s\S]{{0,120}}?\b{simple}\b\s+[A-Za-z_][A-Za-z0-9_]*\s*[;=]"
_CONSTRUCTOR_TEMPLATE = r"\(\s*(?:final\s+)?(?:[A-Za-z0-9_$.<>?, ]*,\s*)*(?:final\s+)?\b{simple}\b\s+[A-Za-z_][A-Za-z0-9_]*"

_PROVIDER_MARKERS: tuple[tuple[str, str], ...] = (
    ("COMPONENT", "@Component"),
    ("SERVICE", "@Service"),
    ("REPOSITORY", "@Repository"),
    ("CONTROLLER", "@Controller"),
    ("CONTROLLER_ADVICE", "@ControllerAdvice"),
    ("REST_CONTROLLER_ADVICE", "@RestControllerAdvice"),
    ("CONFIGURATION", "@Configuration"),
    ("TEST_CONFIGURATION", "@TestConfiguration"),
    ("IMPORT", "@Import"),
    ("MOCKBEAN", "@MockBean"),
    ("MOCKITOBEAN", "@MockitoBean"),
    ("BEAN_METHOD", "@Bean"),
    ("COMPONENT_SCAN", "@ComponentScan"),
    ("SPRING_BOOT_APPLICATION", "@SpringBootApplication"),
)

_PROVIDER_PRIORITY = [
    "TEST_CONFIGURATION",
    "MOCKITOBEAN",
    "MOCKBEAN",
    "BEAN_METHOD",
    "CONFIGURATION",
    "CONTROLLER_ADVICE",
    "REST_CONTROLLER_ADVICE",
    "SERVICE",
    "COMPONENT",
    "REPOSITORY",
    "CONTROLLER",
]


@dataclass(frozen=True)
class LegacyBehaviorEquivalenceResult:
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]
    warning: str


def generate_legacy_behavior_equivalence_report(
    *,
    run_dir: str | Path,
    legacy_project_path: str | Path,
    sandbox_project_path: str | Path,
    migrated_reference_path: str | Path | None = None,
    behavioral_context_pack_path: str | Path | None = None,
    build_error_contract_path: str | Path | None = None,
    surefire_reports_dir: str | Path | None = None,
    behavioral_context_pack: dict[str, Any] | None = None,
    build_error_contract: dict[str, Any] | None = None,
    orchestration_summary: dict[str, Any] | None = None,
) -> LegacyBehaviorEquivalenceResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    legacy_root = _resolve_path(legacy_project_path)
    sandbox_root = _resolve_path(sandbox_project_path)
    reference_root = _resolve_path(migrated_reference_path)
    context_pack = behavioral_context_pack or _read_optional_json(behavioral_context_pack_path)
    build_error = build_error_contract or _read_optional_json(build_error_contract_path)
    orchestration = orchestration_summary if isinstance(orchestration_summary, dict) else {}
    surefire_root = _resolve_path(
        surefire_reports_dir or (sandbox_root / "target" / "surefire-reports" if sandbox_root else None)
    )

    missing_bean_types = _missing_bean_types(context_pack, build_error, surefire_root)
    beans: list[dict[str, Any]] = []
    for bean_type in missing_bean_types:
        legacy_occurrences = _scan_project_for_bean(legacy_root, bean_type, project_role="legacy")
        sandbox_occurrences = _scan_project_for_bean(sandbox_root, bean_type, project_role="sandbox")
        reference_occurrences = _scan_project_for_bean(reference_root, bean_type, project_role="reference")
        likely_provider_type = _likely_provider_type(legacy_occurrences, reference_occurrences, sandbox_occurrences)
        provider_status = _provider_status(legacy_occurrences, sandbox_occurrences, reference_occurrences)
        suspected_cause = _suspected_cause(
            bean_type=bean_type,
            legacy_occurrences=legacy_occurrences,
            sandbox_occurrences=sandbox_occurrences,
            reference_occurrences=reference_occurrences,
        )
        recommended_fix = _recommended_fix_strategy(
            bean_type=bean_type,
            legacy_occurrences=legacy_occurrences,
            sandbox_occurrences=sandbox_occurrences,
            reference_occurrences=reference_occurrences,
        )
        reference_classification = _reference_resolution_classification(reference_occurrences, sandbox_occurrences)
        beans.append(
            {
                "missing_bean_type": bean_type,
                "legacy_occurrences": legacy_occurrences,
                "sandbox_occurrences": sandbox_occurrences,
                "migrated_reference_occurrences": reference_occurrences,
                "likely_legacy_provider_type": likely_provider_type,
                "provider_status": provider_status,
                "suspected_cause": suspected_cause,
                "recommended_equivalent_fix_strategy": recommended_fix,
                "reference_resolution_classification": reference_classification,
                "safe_to_auto_apply": False,
                "human_review_required": True,
                "llm_candidate": _is_ambiguous(legacy_occurrences, sandbox_occurrences, reference_occurrences),
            }
        )

    payload = {
        "run_id": str(orchestration.get("run_id") or run_root.name),
        "gate_id": LEGACY_BEHAVIOR_EQUIVALENCE_GATE,
        "failed_unit": str(
            (build_error or {}).get("unit_id")
            or (context_pack or {}).get("failed_unit")
            or orchestration.get("current_phase")
            or ""
        ),
        "final_status": str((context_pack or {}).get("final_status") or orchestration.get("final_status") or ""),
        "build_status": str((context_pack or {}).get("build_status") or orchestration.get("build_status") or ""),
        "test_status": str((context_pack or {}).get("test_status") or orchestration.get("test_status") or ""),
        "missing_bean_types": missing_bean_types,
        "beans": beans,
        "safe_to_auto_apply": False,
        "human_review_required": bool(beans),
        "llm_candidate": any(bool(item.get("llm_candidate")) for item in beans),
        "legacy_project_path": str(legacy_root) if legacy_root else "",
        "sandbox_project_path": str(sandbox_root) if sandbox_root else "",
        "migrated_reference_path": str(reference_root) if reference_root else "",
    }
    summary_text = _render_summary(payload)

    report_path = remediation_dir / "legacy_behavior_equivalence_report.json"
    summary_path = remediation_dir / "legacy_behavior_equivalence_summary.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path)

    warning = ""
    if beans:
        warning = "Legacy behavior equivalence report generated; missing bean behavior requires human review before patching."
    return LegacyBehaviorEquivalenceResult(
        report_path=report_path,
        summary_path=summary_path,
        payload=payload,
        warning=warning,
    )


def _missing_bean_types(
    context_pack: dict[str, Any] | None,
    build_error_contract: dict[str, Any] | None,
    surefire_root: Path | None,
) -> list[str]:
    collected: list[str] = []
    for item in list((context_pack or {}).get("missing_bean_type_errors") or []):
        if isinstance(item, dict):
            bean_type = str(item.get("bean_type") or "").strip()
            if bean_type:
                collected.append(bean_type)
    sources: list[str] = []
    for key in ("matched_line", "message"):
        text = str((build_error_contract or {}).get(key) or "").strip()
        if text:
            sources.append(text)
    for key in ("stdout_tail", "stderr_tail"):
        for line in list((build_error_contract or {}).get(key) or []):
            sources.append(str(line))
    if surefire_root and surefire_root.is_dir():
        for report in sorted(surefire_root.glob("TEST-*.xml")):
            try:
                root = ElementTree.fromstring(report.read_text(encoding="utf-8"))
            except (OSError, ElementTree.ParseError):
                continue
            for testcase in root.findall("testcase"):
                for tag in ("failure", "error"):
                    node = testcase.find(tag)
                    if node is None:
                        continue
                    sources.append(str(node.get("message") or ""))
                    sources.append(str(node.text or ""))
    for text in sources:
        collected.extend(_extract_missing_bean_types_from_text(text))
    return _dedupe_preserve_order(item for item in collected if item)


def _extract_missing_bean_types_from_text(text: str) -> list[str]:
    if not text:
        return []
    matches = [*(_MISSING_BEAN_RE.findall(text)), *(_NO_SUCH_BEAN_RE.findall(text))]
    return [match.strip() for match in matches if str(match).strip()]


def _scan_project_for_bean(root: Path | None, bean_type: str, *, project_role: str) -> list[dict[str, Any]]:
    if root is None or not root.is_dir():
        return []
    full_type = bean_type.strip()
    simple_name = full_type.rsplit(".", 1)[-1]
    findings: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.java")):
        rel = _safe_relative(path, root)
        if not rel:
            continue
        text = _read_text(path)
        if simple_name not in text and full_type not in text:
            continue
        markers = _matched_markers(text, simple_name)
        class_name = _class_name(text)
        package_name = _package_name(text)
        scope = "test" if _is_test_path(rel) else "main"
        occurrence_role = _occurrence_role(text, simple_name, class_name, markers)
        if not markers and occurrence_role == "reference_only":
            continue
        findings.append(
            {
                "project_role": project_role,
                "file": rel,
                "scope": scope,
                "class_name": class_name,
                "package_name": package_name,
                "occurrence_role": occurrence_role,
                "matched_markers": markers,
                "snippet": _snippet(text, simple_name),
            }
        )
    return findings


def _matched_markers(text: str, simple_name: str) -> list[str]:
    markers = [label for label, token in _PROVIDER_MARKERS if token in text]
    if re.search(_BEAN_METHOD_TEMPLATE.format(simple=re.escape(simple_name)), text, flags=re.MULTILINE):
        markers.append("BEAN_METHOD")
    if re.search(_ANNOTATED_TYPE_TEMPLATE.format(simple=re.escape(simple_name)), text, flags=re.MULTILINE):
        if "@MockitoBean" in text:
            markers.append("MOCKITOBEAN")
        if "@MockBean" in text:
            markers.append("MOCKBEAN")
    if re.search(_FIELD_INJECTION_TEMPLATE.format(simple=re.escape(simple_name)), text, flags=re.MULTILINE):
        markers.append("FIELD_INJECTION")
    if re.search(_CONSTRUCTOR_TEMPLATE.format(simple=re.escape(simple_name)), text, flags=re.MULTILINE):
        markers.append("CONSTRUCTOR_INJECTION")
    if "scanBasePackages" in text or "@ComponentScan" in text:
        markers.append("PACKAGE_SCAN_HINT")
    return _dedupe_preserve_order(markers)


def _occurrence_role(text: str, simple_name: str, class_name: str, markers: list[str]) -> str:
    explicit_provider_markers = {
        "BEAN_METHOD",
        "MOCKBEAN",
        "MOCKITOBEAN",
        "IMPORT",
        "TEST_CONFIGURATION",
    }
    stereotype_markers = {
        "COMPONENT",
        "SERVICE",
        "REPOSITORY",
        "CONTROLLER",
        "CONTROLLER_ADVICE",
        "REST_CONTROLLER_ADVICE",
        "CONFIGURATION",
    }
    marker_set = set(markers)
    if class_name == simple_name and stereotype_markers.intersection(marker_set):
        return "provider"
    if class_name == simple_name and not {"FIELD_INJECTION", "CONSTRUCTOR_INJECTION"}.intersection(markers):
        return "provider"
    if explicit_provider_markers.intersection(marker_set):
        return "provider"
    if {"FIELD_INJECTION", "CONSTRUCTOR_INJECTION"}.intersection(markers):
        return "consumer"
    return "reference_only"


def _likely_provider_type(*occurrence_groups: list[dict[str, Any]]) -> str:
    if occurrence_groups:
        for priority in _PROVIDER_PRIORITY:
            for item in occurrence_groups[0]:
                if str(item.get("occurrence_role") or "") != "provider":
                    continue
                if priority in list(item.get("matched_markers") or []):
                    return priority
    for priority in _PROVIDER_PRIORITY:
        for group in occurrence_groups[1:]:
            for item in group:
                if str(item.get("occurrence_role") or "") != "provider":
                    continue
                if priority in list(item.get("matched_markers") or []):
                    return priority
    for group in occurrence_groups:
        for item in group:
            if str(item.get("occurrence_role") or "") == "provider":
                return "DIRECT_CLASS_PROVIDER"
    return "UNKNOWN"


def _provider_status(
    legacy_occurrences: list[dict[str, Any]],
    sandbox_occurrences: list[dict[str, Any]],
    reference_occurrences: list[dict[str, Any]],
) -> str:
    legacy_providers = _providers(legacy_occurrences)
    sandbox_providers = _providers(sandbox_occurrences)
    reference_providers = _providers(reference_occurrences)
    if legacy_providers and not sandbox_providers:
        return "disappeared"
    if legacy_providers and sandbox_providers:
        return "not_loaded"
    if not legacy_providers and reference_providers and not sandbox_providers:
        return "changed"
    if sandbox_providers and reference_providers:
        return "changed"
    return "not_found"


def _suspected_cause(
    *,
    bean_type: str,
    legacy_occurrences: list[dict[str, Any]],
    sandbox_occurrences: list[dict[str, Any]],
    reference_occurrences: list[dict[str, Any]],
) -> str:
    legacy_providers = _providers(legacy_occurrences)
    sandbox_providers = _providers(sandbox_occurrences)
    reference_providers = _providers(reference_occurrences)
    if legacy_providers and not sandbox_providers:
        legacy_type = _likely_provider_type(legacy_occurrences)
        return f"Legacy provided {bean_type} via {legacy_type}; sandbox no longer exposes equivalent provider in loaded context."
    if sandbox_providers:
        return f"Sandbox still references {bean_type}, but provider may no longer be loaded by Spring Boot 3 test or component scan context."
    if reference_providers:
        return f"Reference project still provisions {bean_type}; sandbox equivalent likely missing from test context or bean configuration."
    return f"Missing bean {bean_type} detected, but provider pattern remains ambiguous."


def _recommended_fix_strategy(
    *,
    bean_type: str,
    legacy_occurrences: list[dict[str, Any]],
    sandbox_occurrences: list[dict[str, Any]],
    reference_occurrences: list[dict[str, Any]],
) -> str:
    if _has_marker(reference_occurrences, {"MOCKITOBEAN", "MOCKBEAN", "TEST_CONFIGURATION", "IMPORT"}):
        return (
            f"Use migrated reference only as evidence that {bean_type} may need explicit test-context provisioning; "
            "do not copy blindly."
        )
    if _has_marker(legacy_occurrences, {"MOCKBEAN", "MOCKITOBEAN", "TEST_CONFIGURATION", "IMPORT"}):
        return (
            f"Review Boot 3 test-context equivalence for {bean_type}; preserve legacy test bean setup with explicit "
            "@MockitoBean, @Import, or @TestConfiguration only after human review."
        )
    if _has_marker(legacy_occurrences, {"BEAN_METHOD", "CONFIGURATION"}):
        return (
            f"Review legacy configuration that created {bean_type}; confirm equivalent @Bean/@Configuration still loads "
            "under Boot 3 application or test context."
        )
    if _has_marker(legacy_occurrences, {"COMPONENT", "SERVICE", "REPOSITORY", "CONTROLLER_ADVICE", "REST_CONTROLLER_ADVICE"}):
        return (
            f"Review component-scan or conditional bean loading for {bean_type}; verify provider remains discoverable "
            "in sandbox and Boot 3 test slices."
        )
    return (
        f"Review legacy vs sandbox behavior for {bean_type}; determine whether missing bean should come from component scan, "
        "configuration, or explicit Boot 3 test wiring."
    )


def _reference_resolution_classification(
    reference_occurrences: list[dict[str, Any]],
    sandbox_occurrences: list[dict[str, Any]],
) -> str:
    if not reference_occurrences:
        return ""
    if _has_marker(reference_occurrences, {"MOCKBEAN", "MOCKITOBEAN", "TEST_CONFIGURATION", "IMPORT"}):
        return "test_context_candidate"
    if _has_marker(reference_occurrences, {"BEAN_METHOD", "CONFIGURATION", "COMPONENT", "SERVICE", "REPOSITORY"}):
        if not _providers(sandbox_occurrences):
            return "behavioral_review_required"
        return "deterministic_candidate"
    return "project_specific"


def _is_ambiguous(
    legacy_occurrences: list[dict[str, Any]],
    sandbox_occurrences: list[dict[str, Any]],
    reference_occurrences: list[dict[str, Any]],
) -> bool:
    provider_count = sum(bool(_providers(items)) for items in (legacy_occurrences, sandbox_occurrences, reference_occurrences))
    return provider_count <= 1 or bool(reference_occurrences)


def _providers(occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in occurrences if str(item.get("occurrence_role") or "") == "provider"]


def _has_marker(occurrences: list[dict[str, Any]], markers: set[str]) -> bool:
    for item in occurrences:
        if markers.intersection(set(item.get("matched_markers") or [])):
            return True
    return False


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Legacy Behavior Equivalence Summary",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Final Status: {payload.get('final_status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- LLM Candidate: {str(payload.get('llm_candidate')).lower()}",
    ]
    beans = list(payload.get("beans") or [])
    if beans:
        lines.extend(["", "## Missing Beans", ""])
        for bean in beans:
            if not isinstance(bean, dict):
                continue
            lines.append(f"- {bean.get('missing_bean_type', '')}: {bean.get('provider_status', '')}")
            lines.append(f"  likely legacy provider: {bean.get('likely_legacy_provider_type', '')}")
            lines.append(f"  suspected cause: {bean.get('suspected_cause', '')}")
            lines.append(f"  recommended strategy: {bean.get('recommended_equivalent_fix_strategy', '')}")
            reference_classification = str(bean.get("reference_resolution_classification") or "")
            if reference_classification:
                lines.append(f"  reference classification: {reference_classification}")
    return "\n".join(lines) + "\n"


def _class_name(text: str) -> str:
    match = _CLASS_RE.search(text)
    return str(match.group(2) if match else "")


def _package_name(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    return str(match.group(1) if match else "")


def _snippet(text: str, simple_name: str) -> str:
    for line in text.splitlines():
        if simple_name in line or "@Bean" in line or "@MockBean" in line or "@MockitoBean" in line:
            return line.strip()[:240]
    return ""


def _is_test_path(path_text: str) -> bool:
    normalized = path_text.replace("\\", "/").lower()
    return "/src/test/" in normalized or "/src/integrationtest/" in normalized or normalized.startswith("src/test/")


def _resolve_path(path_like: str | Path | None) -> Path | None:
    if path_like is None:
        return None
    path_text = str(path_like).strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    return path.resolve()


def _read_optional_json(path_like: str | Path | None) -> dict[str, Any] | None:
    if path_like is None:
        return None
    path = Path(path_like).expanduser()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path) -> None:
    refs = {
        "legacy_behavior_equivalence_report": str(report_path),
        "legacy_behavior_equivalence_summary": str(summary_path),
    }
    for candidate in (
        run_root / "orchestration" / "orchestration_summary.json",
        run_root / "final" / "migration_report.json",
    ):
        payload = _read_optional_json(candidate)
        if not isinstance(payload, dict):
            continue
        artifact_refs = dict(payload.get("artifact_refs", {}) or {})
        payload["artifact_refs"] = {
            **artifact_refs,
            **refs,
        }
        candidate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")
    except OSError:
        return ""


def _dedupe_preserve_order(items: Any) -> list[Any]:
    seen: set[Any] = set()
    ordered: list[Any] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered
