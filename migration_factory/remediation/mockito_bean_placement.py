from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
import re
from pathlib import Path
from typing import Any


MOCKITO_BEAN_PLACEMENT_GATE = "MOCKITOBEAN_PLACEMENT_COMPATIBILITY"
_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z0-9_$.]+)\s*;", re.MULTILINE)
_CLASS_RE = re.compile(r"\b(?:abstract\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)")
_EXTENDS_RE = re.compile(r"\bclass\s+[A-Za-z_][A-Za-z0-9_]*\s+extends\s+([A-Za-z_][A-Za-z0-9_]*)")
_MOCK_BEAN_FIELD_RE = re.compile(
    r"@(MockBean|MockitoBean)[\s\S]{0,120}?\b([A-Za-z_][A-Za-z0-9_$.]*)\b\s+([A-Za-z_][A-Za-z0-9_]*)\s*[;=]"
)
_FIELD_TEMPLATE = "@MockitoBean\n    {bean_simple} {field_name};"


@dataclass(frozen=True)
class MockitoBeanPlacementResult:
    __test__ = False
    report_path: Path
    summary_path: Path
    patch_path: Path | None
    payload: dict[str, Any]
    warning: str


def generate_mockito_bean_placement_report(
    *,
    run_dir: str | Path,
    sandbox_project_path: str | Path,
    legacy_project_path: str | Path,
    legacy_behavior_equivalence_report_path: str | Path,
    test_context_repair_proposal_path: str | Path,
    legacy_guided_patch_proposal_path: str | Path,
    behavioral_failure_context_pack_path: str | Path,
    migrated_reference_path: str | Path | None = None,
    surefire_reports_dir: str | Path | None = None,
    legacy_behavior_equivalence_report: dict[str, Any] | None = None,
    test_context_repair_proposal: dict[str, Any] | None = None,
    legacy_guided_patch_proposal: dict[str, Any] | None = None,
    behavioral_failure_context_pack: dict[str, Any] | None = None,
) -> MockitoBeanPlacementResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    sandbox_root = _resolve_path(sandbox_project_path)
    legacy_root = _resolve_path(legacy_project_path)
    reference_root = _resolve_path(migrated_reference_path)
    equivalence = legacy_behavior_equivalence_report or _read_optional_json(legacy_behavior_equivalence_report_path) or {}
    repair = test_context_repair_proposal or _read_optional_json(test_context_repair_proposal_path) or {}
    guided = legacy_guided_patch_proposal or _read_optional_json(legacy_guided_patch_proposal_path) or {}
    context_pack = behavioral_failure_context_pack or _read_optional_json(behavioral_failure_context_pack_path) or {}

    repair_by_bean = {
        str(item.get("missing_bean_type") or "").strip(): item
        for item in list(repair.get("proposals") or [])
        if isinstance(item, dict) and str(item.get("missing_bean_type") or "").strip()
    }
    guided_by_bean = {
        str(item.get("missing_bean_type") or "").strip(): item
        for item in list(guided.get("proposals") or [])
        if isinstance(item, dict) and str(item.get("missing_bean_type") or "").strip()
    }
    context_failures = list(context_pack.get("failing_tests") or [])

    proposals: list[dict[str, Any]] = []
    patch_chunks: list[str] = []
    for bean in list(equivalence.get("beans") or []):
        if not isinstance(bean, dict):
            continue
        missing_bean_type = str(bean.get("missing_bean_type") or "").strip()
        if not missing_bean_type:
            continue
        repair_row = dict(repair_by_bean.get(missing_bean_type) or {})
        guided_row = dict(guided_by_bean.get(missing_bean_type) or {})
        row = _analyze_missing_bean(
            bean=bean,
            repair_row=repair_row,
            guided_row=guided_row,
            context_failures=context_failures,
            sandbox_root=sandbox_root,
            legacy_root=legacy_root,
            reference_root=reference_root,
        )
        proposals.append(row)
        patch_text = str(row.get("patch_text") or "")
        if patch_text:
            patch_chunks.append(patch_text)

    patch_path = None
    if patch_chunks:
        patch_path = remediation_dir / "mockito_bean_placement_patch_proposal.patch"
        patch_path.write_text("\n".join(chunk.rstrip() for chunk in patch_chunks if chunk).rstrip() + "\n", encoding="utf-8")

    payload = {
        "run_id": str(
            context_pack.get("run_id")
            or guided.get("run_id")
            or repair.get("run_id")
            or equivalence.get("run_id")
            or run_root.name
        ),
        "gate_id": MOCKITO_BEAN_PLACEMENT_GATE,
        "failed_unit": str(
            equivalence.get("failed_unit")
            or guided.get("failed_unit")
            or repair.get("failed_unit")
            or context_pack.get("failed_unit")
            or ""
        ),
        "final_status": str(context_pack.get("final_status") or guided.get("final_status") or ""),
        "build_status": str(context_pack.get("build_status") or guided.get("build_status") or ""),
        "test_status": str(context_pack.get("test_status") or guided.get("test_status") or ""),
        "proposal_mode": "legacy_sandbox_reference" if reference_root else "legacy_sandbox_only",
        "legacy_project_path": str(legacy_root) if legacy_root else "",
        "sandbox_project_path": str(sandbox_root) if sandbox_root else "",
        "migrated_reference_path": str(reference_root) if reference_root else "",
        "proposals": proposals,
        "patch_proposal_available": any(bool(item.get("patch_proposal_available")) for item in proposals),
        "patch_proposal_path": str(patch_path) if patch_path else "",
        "safe_to_auto_apply": False,
        "human_review_required": bool(proposals),
        "llm_candidate": any(bool(item.get("llm_candidate")) for item in proposals),
    }
    summary_text = _render_summary(payload)

    report_path = remediation_dir / "mockito_bean_placement_report.json"
    summary_path = remediation_dir / "mockito_bean_placement_summary.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path, patch_path)

    warning = ""
    if proposals:
        warning = "MockitoBean placement compatibility report generated; human review required before any patch is applied."
    return MockitoBeanPlacementResult(
        report_path=report_path,
        summary_path=summary_path,
        patch_path=patch_path,
        payload=payload,
        warning=warning,
    )


def _analyze_missing_bean(
    *,
    bean: dict[str, Any],
    repair_row: dict[str, Any],
    guided_row: dict[str, Any],
    context_failures: list[dict[str, Any]],
    sandbox_root: Path | None,
    legacy_root: Path | None,
    reference_root: Path | None,
) -> dict[str, Any]:
    missing_bean_type = str(bean.get("missing_bean_type") or "").strip()
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    legacy_mock_locations = _mock_locations(list(bean.get("legacy_occurrences") or []), want="MockBean")
    sandbox_mock_locations = _mock_locations(list(bean.get("sandbox_occurrences") or []), want="MockitoBean")
    support_locations = _support_locations(repair_row, bean)
    candidate_tests = _candidate_tests(
        repair_row=repair_row,
        guided_row=guided_row,
        context_failures=context_failures,
        sandbox_root=sandbox_root,
        bean=bean,
    )
    test_class_infos = _test_class_infos(candidate_tests, sandbox_root)
    placement = _placement_for_candidates(
        missing_bean_type=missing_bean_type,
        test_class_infos=test_class_infos,
        support_locations=support_locations,
        sandbox_root=sandbox_root,
    )
    patch_candidate = _patch_candidate(
        missing_bean_type=missing_bean_type,
        placement=placement,
        sandbox_root=sandbox_root,
    )
    reference_evidence = _reference_evidence(
        patch_candidate=patch_candidate,
        reference_root=reference_root,
        sandbox_root=sandbox_root,
        support_locations=support_locations,
        missing_bean_type=missing_bean_type,
    )
    if reference_evidence["classification"] == "supports_patch":
        placement["reference_supports_patch"] = True
    if placement["classification"] == "MOCK_PLACEMENT_AMBIGUOUS":
        patch_candidate = None
    patch_text = ""
    if patch_candidate:
        patch_text = _render_patch(
            path=Path(str(patch_candidate["target_file"])),
            original_text=str(patch_candidate["original_text"]),
            updated_text=str(patch_candidate["updated_text"]),
        )
    return {
        "missing_bean_type": missing_bean_type,
        "legacy_mock_locations": legacy_mock_locations,
        "sandbox_mock_locations": sandbox_mock_locations,
        "failing_test_classes": _dedupe_strings(
            str(item.get("test_class") or "") for item in candidate_tests if isinstance(item, dict)
        ),
        "test_class_hierarchy": test_class_infos,
        "placement_classification": placement["classification"],
        "support_class_loaded_by_failing_tests": placement["support_loaded"],
        "target_superclass": placement["target_superclass"],
        "reference_evidence": reference_evidence,
        "proposal_strategies": _proposal_strategies(placement["classification"], patch_candidate),
        "patch_proposal_available": bool(patch_text),
        "patch_strategy": str(patch_candidate.get("strategy_id") or "") if patch_candidate else "",
        "patch_target_file": str(patch_candidate.get("target_file") or "") if patch_candidate else "",
        "patch_text": patch_text,
        "llm_candidate": patch_candidate is None,
        "human_review_required": True,
        "safe_to_auto_apply": False,
        "unsafe_to_auto_apply": True,
        "recommended_investigation_steps": _recommended_steps(
            missing_bean_type=missing_bean_type,
            placement=placement["classification"],
            support_locations=support_locations,
            candidate_tests=candidate_tests,
            patch_candidate=patch_candidate,
        ),
        "tests_to_rerun": _dedupe_strings(
            [str(item.get("test_class") or "") for item in candidate_tests if isinstance(item, dict)]
            + ["target/surefire-reports for the affected test slice"]
        ),
    }


def _candidate_tests(
    *,
    repair_row: dict[str, Any],
    guided_row: dict[str, Any],
    context_failures: list[dict[str, Any]],
    sandbox_root: Path | None,
    bean: dict[str, Any],
) -> list[dict[str, Any]]:
    support_files = {str(item.get("file") or "") for item in list(guided_row.get("test_support_classes") or []) if isinstance(item, dict)}
    support_packages = set()
    support_classes = set()
    for item in list(guided_row.get("test_support_classes") or []):
        if not isinstance(item, dict):
            continue
        support_classes.add(str(item.get("class_name") or ""))
        path = _resolve_repo_file(sandbox_root, str(item.get("file") or ""))
        if path and path.is_file():
            support_packages.add(_package_name(_read_text(path)))
    consumer_classes = {
        str(item.get("class_name") or "")
        for item in list(bean.get("sandbox_occurrences") or [])
        if isinstance(item, dict) and str(item.get("occurrence_role") or "") == "consumer"
    }
    candidates = []
    rows = list(repair_row.get("failing_tests") or []) or [
        {
            "test_class": str(item.get("test_class") or ""),
            "test_method": str(item.get("test_method") or ""),
            "category": str(item.get("category") or ""),
            "symptom": str(item.get("symptom") or ""),
        }
        for item in context_failures
        if isinstance(item, dict)
    ]
    for item in rows:
        if not isinstance(item, dict):
            continue
        file_ref = str(item.get("file") or "")
        file_path = _resolve_path(file_ref)
        text = _read_text(file_path)
        package_name = _package_name(text)
        score = 0
        symptom = str(item.get("symptom") or "")
        if any(cls and cls in symptom for cls in support_classes):
            score += 5
        if package_name and package_name in support_packages:
            score += 4
        if any(cls and cls in text for cls in consumer_classes):
            score += 4
        if any(cls and cls in text for cls in support_classes):
            score += 3
        if str(item.get("matched_missing_bean")).lower() == "true":
            score += 3
        if support_files and file_ref and file_ref in support_files:
            score -= 2
        candidates.append({**dict(item), "_score": score})
    if not candidates:
        return []
    max_score = max(int(item.get("_score", 0)) for item in candidates)
    if max_score <= 0:
        if len(candidates) == 1:
            return [dict(candidates[0])]
        return []
    return [dict(item) for item in candidates if int(item.get("_score", 0)) == max_score]


def _test_class_infos(candidate_tests: list[dict[str, Any]], sandbox_root: Path | None) -> list[dict[str, Any]]:
    rows = []
    for item in candidate_tests:
        file_path = _resolve_path(item.get("file"))
        if file_path is None or not file_path.is_file():
            continue
        text = _read_text(file_path)
        superclass = _superclass_name(text)
        superclass_file = _find_class_file(sandbox_root, superclass) if superclass and sandbox_root else None
        superclass_text = _read_text(superclass_file)
        rows.append(
            {
                "test_class": str(item.get("test_class") or ""),
                "file": str(file_path),
                "declares_mockito_bean": False,
                "superclass": superclass or "",
                "superclass_file": str(superclass_file) if superclass_file else "",
                "superclass_declares_mockito_bean": False,
                "is_superclass_abstract": "abstract class" in superclass_text,
            }
        )
    return rows


def _placement_for_candidates(
    *,
    missing_bean_type: str,
    test_class_infos: list[dict[str, Any]],
    support_locations: list[dict[str, Any]],
    sandbox_root: Path | None,
) -> dict[str, Any]:
    support_loaded = bool(support_locations)
    if not support_locations:
        return {
            "classification": "MOCK_PROVIDER_NOT_FOUND",
            "support_loaded": False,
            "target_superclass": "",
            "support_field": None,
        }
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    for info in test_class_infos:
        text = _read_text(info.get("file"))
        field = _mock_field(text, missing_bean_type)
        if field:
            return {
                "classification": "MOCK_IN_FAILING_TEST_CLASS",
                "support_loaded": True,
                "target_superclass": "",
                "support_field": field,
            }
    superclass_fields = []
    for info in test_class_infos:
        superclass_file = _resolve_path(info.get("superclass_file"))
        if superclass_file and superclass_file.is_file():
            field = _mock_field(_read_text(superclass_file), missing_bean_type)
            if field:
                superclass_fields.append((str(info.get("superclass") or ""), field))
    if superclass_fields:
        return {
            "classification": "MOCK_IN_TEST_SUPERCLASS",
            "support_loaded": True,
            "target_superclass": superclass_fields[0][0],
            "support_field": superclass_fields[0][1],
        }
    support_field = None
    for support in support_locations:
        support_file = _resolve_repo_file(sandbox_root, str(support.get("file") or ""))
        field = _mock_field(_read_text(support_file), missing_bean_type)
        if field:
            support_field = field
            break
    if support_field:
        if len(test_class_infos) > 1:
            superclass_names = _dedupe_strings(str(item.get("superclass") or "") for item in test_class_infos if item.get("superclass"))
            if len(superclass_names) == 1:
                return {
                    "classification": "MOCK_IN_SUPPORT_CLASS_ONLY",
                    "support_loaded": support_loaded,
                    "target_superclass": superclass_names[0],
                    "target_test_file": "",
                    "support_field": support_field,
                }
            return {
                "classification": "MOCK_PLACEMENT_AMBIGUOUS",
                "support_loaded": support_loaded,
                "target_superclass": "",
                "target_test_file": "",
                "support_field": support_field,
            }
        return {
            "classification": "MOCK_IN_SUPPORT_CLASS_ONLY",
            "support_loaded": support_loaded,
            "target_superclass": "",
            "target_test_file": str(test_class_infos[0].get("file") or "") if test_class_infos else "",
            "support_field": support_field,
        }
    return {
        "classification": "MOCK_PLACEMENT_AMBIGUOUS",
        "support_loaded": support_loaded,
        "target_superclass": "",
        "target_test_file": "",
        "support_field": None,
    }


def _patch_candidate(
    *,
    missing_bean_type: str,
    placement: dict[str, Any],
    sandbox_root: Path | None,
) -> dict[str, Any] | None:
    if sandbox_root is None:
        return None
    field = placement.get("support_field")
    if not isinstance(field, dict):
        return None
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    bean_package = missing_bean_type.rsplit(".", 1)[0] if "." in missing_bean_type else ""
    field_name = str(field.get("field_name") or "mock" + bean_simple)
    classification = str(placement.get("classification") or "")
    if classification == "MOCK_IN_SUPPORT_CLASS_ONLY":
        superclass = str(placement.get("target_superclass") or "")
        if superclass:
            target_file = _find_class_file(sandbox_root, superclass)
            if target_file and target_file.is_file() and "abstract class" in _read_text(target_file):
                original_text = _read_text(target_file)
                updated_text = _add_mockito_field(
                    text=original_text,
                    bean_simple=bean_simple,
                    bean_package=bean_package,
                    field_name=field_name,
                )
                if updated_text and updated_text != original_text:
                    return {
                        "strategy_id": "duplicate_mockito_bean_into_shared_abstract_superclass",
                        "target_file": str(target_file),
                        "original_text": original_text,
                        "updated_text": updated_text,
                    }
        # Fall through to single failing test-class duplication when no shared superclass target is clear.
    if classification != "MOCK_IN_FAILING_TEST_CLASS":
        # Only propose direct duplication when one failing test class was narrowed and support mock is obvious.
        candidate_file = _resolve_path(placement.get("target_test_file"))
        if candidate_file and candidate_file.is_file():
            original_text = _read_text(candidate_file)
            updated_text = _add_mockito_field(
                text=original_text,
                bean_simple=bean_simple,
                bean_package=bean_package,
                field_name=field_name,
            )
            if updated_text and updated_text != original_text:
                return {
                    "strategy_id": "duplicate_mockito_bean_into_failing_test_class",
                    "target_file": str(candidate_file),
                    "original_text": original_text,
                    "updated_text": updated_text,
                }
    return None


def _reference_evidence(
    *,
    patch_candidate: dict[str, Any] | None,
    reference_root: Path | None,
    sandbox_root: Path | None,
    support_locations: list[dict[str, Any]],
    missing_bean_type: str,
) -> dict[str, Any]:
    if reference_root is None or not reference_root.is_dir():
        return {"classification": "unrelated", "summary": "No migrated reference evidence provided."}
    if patch_candidate and sandbox_root:
        target_rel = _safe_relative(Path(str(patch_candidate.get("target_file") or "")), sandbox_root)
        if target_rel:
            reference_target = reference_root / target_rel
            if reference_target.is_file():
                field = _mock_field(_read_text(reference_target), missing_bean_type)
                if field:
                    return {
                        "classification": "supports_patch",
                        "summary": "Reference declares equivalent MockitoBean placement in the corresponding test context file.",
                    }
    if len(support_locations) == 1:
        support_rel = str(support_locations[0].get("file") or "")
        if support_rel and (reference_root / support_rel).is_file():
            return {
                "classification": "ambiguous",
                "summary": "Reference keeps related support mock, but placement alone does not prove the minimal safe repair.",
            }
    return {
        "classification": "unrelated",
        "summary": "Reference did not reveal a stronger localized MockitoBean placement signal.",
    }


def _proposal_strategies(classification: str, patch_candidate: dict[str, Any] | None) -> list[str]:
    mapping = {
        "MOCK_IN_FAILING_TEST_CLASS": ["verify_existing_mockito_bean_registration"],
        "MOCK_IN_TEST_SUPERCLASS": ["duplicate_mockito_bean_into_shared_abstract_superclass"],
        "MOCK_IN_SUPPORT_CLASS_ONLY": [
            "duplicate_mockito_bean_into_failing_test_class",
            "create_test_configuration_with_mockito_mock",
            "human_review_of_test_context_loading",
        ],
        "MOCK_PROVIDER_NOT_FOUND": ["human_review_of_missing_mock_provider"],
        "MOCK_PLACEMENT_AMBIGUOUS": ["human_review_of_mockito_bean_placement"],
    }
    rows = list(mapping.get(classification, ["human_review_of_mockito_bean_placement"]))
    if patch_candidate:
        rows.insert(0, str(patch_candidate.get("strategy_id") or ""))
    return _dedupe_strings(rows)


def _recommended_steps(
    *,
    missing_bean_type: str,
    placement: str,
    support_locations: list[dict[str, Any]],
    candidate_tests: list[dict[str, Any]],
    patch_candidate: dict[str, Any] | None,
) -> list[str]:
    if patch_candidate:
        return [
            f"Review the proposal for {missing_bean_type} before editing Boot 3 test classes.",
            "Rerun the narrowed failing test class first, then rerun the shared test slice if ApplicationContext starts.",
        ]
    support_files = ", ".join(str(item.get("file") or "") for item in support_locations[:2] if item)
    test_classes = ", ".join(str(item.get("test_class") or "") for item in candidate_tests[:3] if isinstance(item, dict))
    return [
        f"Inspect MockitoBean placement for {missing_bean_type} across {test_classes or 'the failing tests'}.",
        f"Compare support-only mock placement in {support_files or 'the support class'} against legacy MockBean visibility.",
        f"Treat placement classification {placement} as review-only until one localized Boot 3 test-context repair is proven.",
    ]


def _support_locations(repair_row: dict[str, Any], bean: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for source in [*list(repair_row.get("existing_mock_or_provider_classes") or []), *list(bean.get("sandbox_occurrences") or [])]:
        if not isinstance(source, dict):
            continue
        file_ref = str(source.get("file") or "")
        class_name = str(source.get("class_name") or "")
        markers = list(source.get("matched_markers") or [])
        if not file_ref or not class_name:
            continue
        if not {"MOCKBEAN", "MOCKITOBEAN", "TEST_CONFIGURATION"}.intersection(set(markers)):
            continue
        key = (file_ref, class_name)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"file": file_ref, "class_name": class_name, "matched_markers": markers})
    return rows


def _mock_locations(occurrences: list[dict[str, Any]], *, want: str) -> list[dict[str, Any]]:
    rows = []
    marker = want.upper()
    for item in occurrences:
        if not isinstance(item, dict):
            continue
        if marker not in {str(m).upper() for m in list(item.get("matched_markers") or [])}:
            continue
        rows.append(
            {
                "class_name": str(item.get("class_name") or ""),
                "file": str(item.get("file") or ""),
                "scope": str(item.get("scope") or ""),
                "matched_markers": list(item.get("matched_markers") or []),
            }
        )
    return rows


def _mock_field(text: str, missing_bean_type: str) -> dict[str, str] | None:
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    for annotation, bean_type, field_name in _MOCK_BEAN_FIELD_RE.findall(text):
        if bean_type.rsplit(".", 1)[-1] != bean_simple:
            continue
        return {"annotation": annotation, "bean_type": bean_type, "field_name": field_name}
    return None


def _superclass_name(text: str) -> str:
    match = _EXTENDS_RE.search(text)
    return str(match.group(1) if match else "").strip()


def _find_class_file(root: Path | None, simple_name: str) -> Path | None:
    if root is None or not simple_name:
        return None
    candidates = sorted(root.rglob(f"{simple_name}.java"))
    return candidates[0] if candidates else None


def _add_mockito_field(*, text: str, bean_simple: str, bean_package: str, field_name: str) -> str:
    if "@MockitoBean" in text and bean_simple in text:
        return ""
    updated = text
    import_stmt = "import org.springframework.test.context.bean.override.mockito.MockitoBean;\n"
    if import_stmt not in updated:
        updated = _insert_import(updated, import_stmt)
    updated = _ensure_import(updated, bean_simple, bean_package)
    class_match = _CLASS_RE.search(updated)
    if not class_match:
        return ""
    brace_idx = updated.find("{", class_match.end())
    if brace_idx < 0:
        return ""
    field_block = "\n\n    " + _FIELD_TEMPLATE.format(bean_simple=bean_simple, field_name=field_name) + "\n"
    return updated[: brace_idx + 1] + field_block + updated[brace_idx + 1 :]


def _insert_import(text: str, import_stmt: str) -> str:
    imports = list(re.finditer(r"^import\s+.*?;\s*$", text, flags=re.MULTILINE))
    if imports:
        last = imports[-1]
        return text[: last.end()] + "\n" + import_stmt.rstrip("\n") + text[last.end() :]
    package_match = _PACKAGE_RE.search(text)
    if package_match:
        return text[: package_match.end()] + "\n\n" + import_stmt + text[package_match.end() :]
    return import_stmt + "\n" + text


def _ensure_import(text: str, class_name: str, class_package: str) -> str:
    package_name = _package_name(text)
    if not class_package or class_package == package_name:
        return text
    import_stmt = f"import {class_package}.{class_name};\n"
    if import_stmt in text:
        return text
    return _insert_import(text, import_stmt)


def _render_patch(*, path: Path, original_text: str, updated_text: str) -> str:
    rel = path.as_posix()
    diff = difflib.unified_diff(
        original_text.splitlines(),
        updated_text.splitlines(),
        fromfile=f"a/{rel}",
        tofile=f"b/{rel}",
        lineterm="",
    )
    return "\n".join(diff) + "\n"


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# MockitoBean Placement Compatibility",
        "",
        f"- Run ID: {payload.get('run_id', '')}",
        f"- Failed Unit: {payload.get('failed_unit', '')}",
        f"- Final Status: {payload.get('final_status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        f"- Patch Proposal Available: {str(bool(payload.get('patch_proposal_available'))).lower()}",
    ]
    proposals = list(payload.get("proposals") or [])
    if proposals:
        lines.extend(["", "## Proposals", ""])
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            lines.append(f"- {proposal.get('missing_bean_type', '')}")
            lines.append(f"  placement: {proposal.get('placement_classification', '')}")
            lines.append(f"  patch strategy: {proposal.get('patch_strategy', '') or 'none'}")
    return "\n".join(lines) + "\n"


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path, patch_path: Path | None) -> None:
    refs = {
        "mockito_bean_placement_report": str(report_path),
        "mockito_bean_placement_summary": str(summary_path),
    }
    if patch_path:
        refs["mockito_bean_placement_patch_proposal"] = str(patch_path)
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
    final_summary = run_root / "final" / "migration_summary.md"
    if final_summary.is_file():
        text = final_summary.read_text(encoding="utf-8")
        line = f"- MockitoBean Placement Report: {report_path}"
        if line not in text:
            text = text.rstrip() + f"\n{line}\n"
            final_summary.write_text(text, encoding="utf-8")


def _resolve_repo_file(root: Path | None, file_ref: str) -> Path | None:
    if not file_ref:
        return None
    candidate = Path(file_ref)
    if candidate.is_absolute():
        return candidate
    if root is None:
        return None
    return root / file_ref


def _resolve_path(path_like: Any) -> Path | None:
    if path_like is None:
        return None
    raw = str(path_like).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _read_optional_json(path_like: str | Path | None) -> dict[str, Any] | None:
    path = _resolve_path(path_like)
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path_like: str | Path | None) -> str:
    path = _resolve_path(path_like)
    if path is None or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _package_name(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    return str(match.group(1) if match else "").strip()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return ""


def _dedupe_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows
