from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


TEST_CONTEXT_REPAIR_GATE = "SPRING_BOOT_TEST_CONTEXT_REPAIR_PROPOSAL"
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")
_SPRING_BOOT_TEST_CLASSES_RE = re.compile(r"@SpringBootTest\s*\(\s*classes\s*=\s*([A-Za-z0-9_$.]+)\.class")
_CONTEXT_CONFIGURATION_RE = re.compile(r"@ContextConfiguration\s*\(\s*classes\s*=\s*\{?([^)\}]+)")
_IMPORT_RE = re.compile(r"@Import\s*\(\s*\{?([^)\}]+)")
_SYMPTOM_CONTEXT_CLASSES_RE = re.compile(r"classes\s*=\s*\[([^\]]+)\]")


@dataclass(frozen=True)
class TestContextRepairProposalResult:
    __test__ = False
    report_path: Path
    summary_path: Path
    patch_path: Path | None
    payload: dict[str, Any]
    warning: str


def generate_test_context_repair_proposal(
    *,
    run_dir: str | Path,
    legacy_behavior_equivalence_report_path: str | Path,
    behavioral_failure_context_pack_path: str | Path,
    sandbox_project_path: str | Path,
    migrated_reference_path: str | Path | None = None,
    surefire_reports_dir: str | Path | None = None,
    legacy_behavior_equivalence_report: dict[str, Any] | None = None,
    behavioral_failure_context_pack: dict[str, Any] | None = None,
) -> TestContextRepairProposalResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    equivalence = legacy_behavior_equivalence_report or _read_optional_json(legacy_behavior_equivalence_report_path) or {}
    context_pack = behavioral_failure_context_pack or _read_optional_json(behavioral_failure_context_pack_path) or {}
    sandbox_root = _resolve_path(sandbox_project_path)
    reference_root = _resolve_path(migrated_reference_path)
    surefire_root = _resolve_path(
        surefire_reports_dir or (sandbox_root / "target" / "surefire-reports" if sandbox_root else None)
    )

    failing_tests = list(context_pack.get("failing_tests") or [])
    tests_by_class = _tests_by_class(failing_tests, context_pack, surefire_root)
    proposals: list[dict[str, Any]] = []
    for bean in list(equivalence.get("beans") or []):
        if not isinstance(bean, dict):
            continue
        missing_bean_type = str(bean.get("missing_bean_type") or "").strip()
        if not missing_bean_type:
            continue
        provider_exists_not_loaded = str(bean.get("provider_status") or "") == "not_loaded"
        relevant_tests = _relevant_tests(tests_by_class, missing_bean_type)
        test_context_classes = _test_context_classes(relevant_tests)
        sandbox_support = _provider_support_classes(bean.get("sandbox_occurrences") or [], sandbox_root)
        reference_support = _provider_support_classes(bean.get("migrated_reference_occurrences") or [], reference_root)
        strategies = _repair_strategies(
            bean=bean,
            relevant_tests=relevant_tests,
            sandbox_support=sandbox_support,
            reference_support=reference_support,
        )
        deterministic_candidate = any(
            strategy["strategy_id"] in {"ensure_mockito_bean_in_loaded_test_context", "adjust_context_configuration_classes"}
            for strategy in strategies
        ) and provider_exists_not_loaded and bool(reference_support)
        llm_candidate = bool(bean.get("llm_candidate")) or not deterministic_candidate
        patch_text = _patch_text_for_narrow_case(bean=bean, relevant_tests=relevant_tests, sandbox_support=sandbox_support)
        proposal = {
            "missing_bean_type": missing_bean_type,
            "failing_tests": relevant_tests,
            "test_classes_likely_loading_application_context": test_context_classes,
            "existing_mock_or_provider_classes": sandbox_support,
            "provider_exists_but_not_loaded": provider_exists_not_loaded,
            "migrated_reference_shows_equivalent_test_setup": bool(reference_support),
            "migrated_reference_support_classes": reference_support,
            "proposal_strategies": strategies,
            "deterministic_candidate": deterministic_candidate and bool(patch_text),
            "llm_candidate": llm_candidate,
            "human_review_required": True,
            "unsafe_to_auto_apply": True,
            "safe_to_auto_apply": False,
            "patch_proposal_available": bool(patch_text),
        }
        proposals.append(proposal)

    patch_path = None
    patch_text = _render_patch_bundle(proposals)
    if patch_text:
        patch_path = remediation_dir / "test_context_repair_proposal.patch"
        patch_path.write_text(patch_text, encoding="utf-8")

    payload = {
        "run_id": str(context_pack.get("run_id") or equivalence.get("run_id") or run_root.name),
        "gate_id": TEST_CONTEXT_REPAIR_GATE,
        "failed_unit": str(equivalence.get("failed_unit") or context_pack.get("failed_unit") or ""),
        "final_status": str(context_pack.get("final_status") or equivalence.get("final_status") or ""),
        "build_status": str(context_pack.get("build_status") or equivalence.get("build_status") or ""),
        "test_status": str(context_pack.get("test_status") or equivalence.get("test_status") or ""),
        "proposals": proposals,
        "safe_to_auto_apply": False,
        "human_review_required": True if proposals else False,
        "llm_candidate": any(bool(item.get("llm_candidate")) for item in proposals),
        "patch_proposal_path": str(patch_path) if patch_path else "",
    }
    summary_text = _render_summary(payload)

    report_path = remediation_dir / "test_context_repair_proposal.json"
    summary_path = remediation_dir / "test_context_repair_proposal.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path, patch_path)

    warning = ""
    if proposals:
        warning = "Spring Boot test context repair proposal generated; human review required before any patch is applied."
    return TestContextRepairProposalResult(
        report_path=report_path,
        summary_path=summary_path,
        patch_path=patch_path,
        payload=payload,
        warning=warning,
    )


def _tests_by_class(
    failing_tests: list[dict[str, Any]],
    context_pack: dict[str, Any],
    surefire_root: Path | None,
) -> dict[str, dict[str, Any]]:
    affected_tests = list(context_pack.get("affected_test_files") or [])
    by_simple: dict[str, dict[str, Any]] = {}
    for item in affected_tests:
        if not isinstance(item, dict):
            continue
        class_name = str(item.get("class_name") or "").strip()
        if class_name:
            by_simple[class_name] = dict(item)
    if surefire_root and surefire_root.is_dir():
        for report in sorted(surefire_root.glob("TEST-*.xml")):
            try:
                root = ElementTree.fromstring(report.read_text(encoding="utf-8"))
            except (OSError, ElementTree.ParseError):
                continue
            for testcase in root.findall("testcase"):
                class_name = str(testcase.get("classname") or "").rsplit(".", 1)[-1]
                if class_name and class_name not in by_simple:
                    by_simple[class_name] = {"class_name": class_name, "file": "", "matched_markers": []}
    rows: dict[str, dict[str, Any]] = {}
    for failure in failing_tests:
        if not isinstance(failure, dict):
            continue
        test_class = str(failure.get("test_class") or "").strip()
        if not test_class:
            continue
        simple = test_class.rsplit(".", 1)[-1]
        hint = dict(by_simple.get(simple) or {})
        row = {
            "test_class": test_class,
            "test_method": str(failure.get("test_method") or ""),
            "category": str(failure.get("category") or ""),
            "symptom": str(failure.get("symptom") or ""),
            "file": str(hint.get("file") or ""),
            "matched_markers": list(hint.get("matched_markers") or []),
            "context_annotations": _context_annotations_from_file(hint.get("file")),
        }
        rows[f"{test_class}::{row['test_method']}"] = row
    return rows


def _context_annotations_from_file(path_like: Any) -> dict[str, Any]:
    path = _resolve_path(path_like)
    if path is None or not path.is_file():
        return {}
    text = _read_text(path)
    class_name = _class_name(text)
    spring_boot_match = _SPRING_BOOT_TEST_CLASSES_RE.search(text)
    context_match = _CONTEXT_CONFIGURATION_RE.search(text)
    import_match = _IMPORT_RE.search(text)
    return {
        "class_name": class_name,
        "spring_boot_test_classes": _split_class_refs(spring_boot_match.group(1) if spring_boot_match else ""),
        "context_configuration_classes": _split_class_refs(context_match.group(1) if context_match else ""),
        "import_classes": _split_class_refs(import_match.group(1) if import_match else ""),
        "uses_spring_boot_test": "@SpringBootTest" in text,
        "uses_context_configuration": "@ContextConfiguration" in text,
        "uses_web_mvc_test": "@WebMvcTest" in text,
    }


def _split_class_refs(text: str) -> list[str]:
    refs = []
    for part in text.split(","):
        cleaned = part.replace("{", "").replace("}", "").strip()
        if not cleaned:
            continue
        refs.append(cleaned.replace(".class", "").strip())
    return refs


def _symptom_context_classes(symptom: str) -> list[str]:
    match = _SYMPTOM_CONTEXT_CLASSES_RE.search(symptom)
    if not match:
        return []
    return _split_class_refs(match.group(1))


def _relevant_tests(tests_by_class: dict[str, dict[str, Any]], missing_bean_type: str) -> list[dict[str, Any]]:
    simple = missing_bean_type.rsplit(".", 1)[-1]
    selected = list(tests_by_class.values())
    selected.sort(key=lambda item: (item.get("test_class", ""), item.get("test_method", "")))
    for row in selected:
        if simple in str(row.get("symptom") or ""):
            row["matched_missing_bean"] = True
        else:
            row["matched_missing_bean"] = False
    return selected


def _test_context_classes(relevant_tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in relevant_tests:
        annotations = dict(row.get("context_annotations") or {})
        rows.append(
            {
                "test_class": str(row.get("test_class") or ""),
                "file": str(row.get("file") or ""),
                "uses_spring_boot_test": bool(annotations.get("uses_spring_boot_test")),
                "uses_context_configuration": bool(annotations.get("uses_context_configuration")),
                "uses_web_mvc_test": bool(annotations.get("uses_web_mvc_test")),
                "spring_boot_test_classes": _dedupe_strings(
                    [
                        *list(annotations.get("spring_boot_test_classes") or []),
                        *_symptom_context_classes(str(row.get("symptom") or "")),
                    ]
                ),
                "context_configuration_classes": list(annotations.get("context_configuration_classes") or []),
                "import_classes": list(annotations.get("import_classes") or []),
            }
        )
    return rows


def _provider_support_classes(occurrences: list[dict[str, Any]], root: Path | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in occurrences:
        if not isinstance(item, dict):
            continue
        if str(item.get("scope") or "") != "test":
            continue
        if str(item.get("occurrence_role") or "") != "provider":
            continue
        file_ref = str(item.get("file") or "")
        annotations = _context_annotations_from_file(root / file_ref if root and file_ref else file_ref)
        rows.append(
            {
                "class_name": str(item.get("class_name") or ""),
                "file": file_ref,
                "matched_markers": list(item.get("matched_markers") or []),
                "context_annotations": annotations,
            }
        )
    return rows


def _repair_strategies(
    *,
    bean: dict[str, Any],
    relevant_tests: list[dict[str, Any]],
    sandbox_support: list[dict[str, Any]],
    reference_support: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    strategies: list[dict[str, Any]] = []
    provider_status = str(bean.get("provider_status") or "")
    likely_provider_type = str(bean.get("likely_legacy_provider_type") or "")
    if provider_status == "not_loaded" and likely_provider_type in {"MOCKBEAN", "MOCKITOBEAN"}:
        strategies.append(
            {
                "strategy_id": "ensure_mockito_bean_in_loaded_test_context",
                "strategy_type": "human_review_required",
                "rationale": "Provider exists in test support, but failing Boot 3 tests may not be loading that support class or bean override.",
            }
        )
    if any(bool((item.get("context_annotations") or {}).get("uses_context_configuration")) for item in relevant_tests):
        strategies.append(
            {
                "strategy_id": "adjust_context_configuration_classes",
                "strategy_type": "deterministic_candidate",
                "rationale": "@ContextConfiguration detected; verify classes list still imports provider-support configuration under Boot 3.",
            }
        )
    if any(bool((item.get("context_annotations") or {}).get("uses_spring_boot_test")) for item in relevant_tests):
        strategies.append(
            {
                "strategy_id": "adjust_spring_boot_test_classes",
                "strategy_type": "human_review_required",
                "rationale": "@SpringBootTest detected; review whether Boot 3 test app class or slice still loads mock/provider support.",
            }
        )
    if any(bool((item.get("context_annotations") or {}).get("uses_web_mvc_test")) for item in relevant_tests):
        strategies.append(
            {
                "strategy_id": "adjust_web_mvc_test_slice_support",
                "strategy_type": "human_review_required",
                "rationale": "@WebMvcTest slice detected; review explicit import or bean override support for missing collaborators.",
            }
        )
    if sandbox_support or reference_support:
        strategies.append(
            {
                "strategy_id": "add_import_for_test_support_configuration",
                "strategy_type": "human_review_required",
                "rationale": "Test support/provider class exists; review @Import or equivalent context wiring so Boot 3 tests load it explicitly.",
            }
        )
    return _dedupe_dicts(strategies)


def _patch_text_for_narrow_case(
    *,
    bean: dict[str, Any],
    relevant_tests: list[dict[str, Any]],
    sandbox_support: list[dict[str, Any]],
) -> str:
    # Conservative: no patch unless one failing test and one obvious support class with missing import/config evidence.
    if len(relevant_tests) != 1 or len(sandbox_support) != 1:
        return ""
    test = relevant_tests[0]
    annotations = dict(test.get("context_annotations") or {})
    support = sandbox_support[0]
    support_class = str(support.get("class_name") or "").strip()
    if not support_class:
        return ""
    if annotations.get("uses_web_mvc_test"):
        return ""
    if support_class in list(annotations.get("import_classes") or []):
        return ""
    if not annotations.get("uses_context_configuration") and not annotations.get("uses_spring_boot_test"):
        return ""
    return ""


def _render_patch_bundle(proposals: list[dict[str, Any]]) -> str:
    # No auto patch text by default; patch proposal remains optional and narrow.
    for proposal in proposals:
        if proposal.get("patch_proposal_available"):
            return str(proposal.get("patch_text") or "")
    return ""


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Test Context Repair Proposal",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Final Status: {payload.get('final_status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Patch Proposal Available: {str(bool(payload.get('patch_proposal_path'))).lower()}",
    ]
    proposals = list(payload.get("proposals") or [])
    if proposals:
        lines.extend(["", "## Proposals", ""])
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            lines.append(f"- {proposal.get('missing_bean_type', '')}")
            lines.append(f"  provider exists but not loaded: {str(proposal.get('provider_exists_but_not_loaded')).lower()}")
            lines.append(f"  reference setup seen: {str(proposal.get('migrated_reference_shows_equivalent_test_setup')).lower()}")
            strategy_ids = [str(item.get("strategy_id") or "") for item in list(proposal.get("proposal_strategies") or []) if isinstance(item, dict)]
            lines.append(f"  strategies: {', '.join(strategy_ids) if strategy_ids else 'none'}")
    return "\n".join(lines) + "\n"


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path, patch_path: Path | None) -> None:
    refs = {
        "test_context_repair_proposal": str(report_path),
        "test_context_repair_proposal_summary": str(summary_path),
    }
    if patch_path:
        refs["test_context_repair_proposal_patch"] = str(patch_path)
    for candidate in (
        run_root / "orchestration" / "orchestration_summary.json",
        run_root / "final" / "migration_report.json",
    ):
        payload = _read_optional_json(candidate)
        if not isinstance(payload, dict):
            continue
        artifact_refs = dict(payload.get("artifact_refs", {}) or {})
        payload["artifact_refs"] = {**artifact_refs, **refs}
        candidate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _class_name(text: str) -> str:
    match = _CLASS_RE.search(text)
    return str(match.group(1) if match else "")


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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")
    except OSError:
        return ""


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for value in values:
        key = json.dumps(value, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
