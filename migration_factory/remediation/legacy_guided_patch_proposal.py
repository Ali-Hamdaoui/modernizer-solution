from __future__ import annotations

from dataclasses import dataclass
import difflib
import json
import re
from pathlib import Path
from typing import Any


LEGACY_GUIDED_PATCH_GATE = "LEGACY_GUIDED_TEST_CONTEXT_PATCH_PROPOSAL"
_CLASS_RE = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")
_PACKAGE_RE = re.compile(r"^\s*package\s+([A-Za-z0-9_$.]+)\s*;", re.MULTILINE)
_SPRING_BOOT_TEST_RE = re.compile(r"@SpringBootTest\s*\(\s*classes\s*=\s*(\{?[^)]*?\}?)\s*\)", re.MULTILINE)
_CONTEXT_CONFIGURATION_RE = re.compile(r"@ContextConfiguration\s*\(\s*classes\s*=\s*(\{?[^)]*?\}?)\s*\)", re.MULTILINE)
_IMPORT_RE = re.compile(r"@Import\s*\(\s*(\{?[^)]*?\}?)\s*\)", re.MULTILINE)
_ANNOTATION_CLASS_RE = re.compile(r"([A-Za-z0-9_$.]+)\.class")
_MISSING_BEAN_RE = re.compile(r"No qualifying bean of type '([^']+)'")
_NO_SUCH_BEAN_RE = re.compile(r"NoSuchBeanDefinitionException(?::|\b).*?'([^']+)'")
_MOCKITO_FIELD_RE = re.compile(
    r"@MockitoBean[\s\S]{0,120}?\b([A-Za-z_][A-Za-z0-9_$.]*)\b\s+([A-Za-z_][A-Za-z0-9_]*)\s*[;=]"
)
_MOCK_FIELD_TEMPLATE = "@MockitoBean\n    {bean_simple} {field_name};"


@dataclass(frozen=True)
class LegacyGuidedPatchProposalResult:
    __test__ = False
    report_path: Path
    summary_path: Path
    patch_path: Path | None
    payload: dict[str, Any]
    warning: str


def generate_legacy_guided_patch_proposal(
    *,
    run_dir: str | Path,
    sandbox_project_path: str | Path,
    legacy_project_path: str | Path,
    legacy_behavior_equivalence_report_path: str | Path,
    test_context_repair_proposal_path: str | Path,
    behavioral_failure_context_pack_path: str | Path,
    migrated_reference_path: str | Path | None = None,
    surefire_reports_dir: str | Path | None = None,
    legacy_behavior_equivalence_report: dict[str, Any] | None = None,
    test_context_repair_proposal: dict[str, Any] | None = None,
    behavioral_failure_context_pack: dict[str, Any] | None = None,
) -> LegacyGuidedPatchProposalResult:
    run_root = Path(run_dir).expanduser().resolve()
    remediation_dir = run_root / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    sandbox_root = _resolve_path(sandbox_project_path)
    legacy_root = _resolve_path(legacy_project_path)
    reference_root = _resolve_path(migrated_reference_path)
    equivalence = legacy_behavior_equivalence_report or _read_optional_json(legacy_behavior_equivalence_report_path) or {}
    repair = test_context_repair_proposal or _read_optional_json(test_context_repair_proposal_path) or {}
    context_pack = behavioral_failure_context_pack or _read_optional_json(behavioral_failure_context_pack_path) or {}

    repair_by_bean = {
        str(item.get("missing_bean_type") or "").strip(): item
        for item in list(repair.get("proposals") or [])
        if isinstance(item, dict) and str(item.get("missing_bean_type") or "").strip()
    }
    context_failures = list(context_pack.get("failing_tests") or [])
    proposal_rows: list[dict[str, Any]] = []
    patch_chunks: list[str] = []
    for bean in list(equivalence.get("beans") or []):
        if not isinstance(bean, dict):
            continue
        bean_type = str(bean.get("missing_bean_type") or "").strip()
        if not bean_type:
            continue
        repair_row = dict(repair_by_bean.get(bean_type) or {})
        row = _proposal_for_missing_bean(
            bean=bean,
            repair_row=repair_row,
            context_failures=context_failures,
            sandbox_root=sandbox_root,
            legacy_root=legacy_root,
            reference_root=reference_root,
        )
        proposal_rows.append(row)
        patch_text = str(row.get("patch_text") or "")
        if patch_text:
            patch_chunks.append(patch_text)

    patch_path = None
    if patch_chunks:
        patch_path = remediation_dir / "legacy_guided_patch_proposal.patch"
        patch_path.write_text("\n".join(chunk.rstrip() for chunk in patch_chunks if chunk).rstrip() + "\n", encoding="utf-8")

    payload = {
        "run_id": str(
            context_pack.get("run_id")
            or repair.get("run_id")
            or equivalence.get("run_id")
            or run_root.name
        ),
        "gate_id": LEGACY_GUIDED_PATCH_GATE,
        "failed_unit": str(
            equivalence.get("failed_unit")
            or repair.get("failed_unit")
            or context_pack.get("failed_unit")
            or ""
        ),
        "final_status": str(
            context_pack.get("final_status")
            or repair.get("final_status")
            or equivalence.get("final_status")
            or ""
        ),
        "build_status": str(
            context_pack.get("build_status")
            or repair.get("build_status")
            or equivalence.get("build_status")
            or ""
        ),
        "test_status": str(
            context_pack.get("test_status")
            or repair.get("test_status")
            or equivalence.get("test_status")
            or ""
        ),
        "proposal_mode": "legacy_sandbox_reference" if reference_root else "legacy_sandbox_only",
        "legacy_project_path": str(legacy_root) if legacy_root else "",
        "sandbox_project_path": str(sandbox_root) if sandbox_root else "",
        "migrated_reference_path": str(reference_root) if reference_root else "",
        "proposals": proposal_rows,
        "patch_proposal_available": any(bool(item.get("patch_proposal_available")) for item in proposal_rows),
        "patch_proposal_path": str(patch_path) if patch_path else "",
        "safe_to_auto_apply": False,
        "human_review_required": bool(proposal_rows),
        "llm_candidate": any(bool(item.get("llm_candidate")) for item in proposal_rows),
    }
    summary_text = _render_summary(payload)

    report_path = remediation_dir / "legacy_guided_patch_proposal.json"
    summary_path = remediation_dir / "legacy_guided_patch_proposal.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(summary_text, encoding="utf-8")
    _backfill_artifact_refs(run_root, report_path, summary_path, patch_path)

    warning = ""
    if proposal_rows:
        warning = "Legacy-guided test context patch proposal generated; human review required before any patch is applied."
    return LegacyGuidedPatchProposalResult(
        report_path=report_path,
        summary_path=summary_path,
        patch_path=patch_path,
        payload=payload,
        warning=warning,
    )


def _proposal_for_missing_bean(
    *,
    bean: dict[str, Any],
    repair_row: dict[str, Any],
    context_failures: list[dict[str, Any]],
    sandbox_root: Path | None,
    legacy_root: Path | None,
    reference_root: Path | None,
) -> dict[str, Any]:
    missing_bean_type = str(bean.get("missing_bean_type") or "").strip()
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    support_classes = _dedupe_support_classes(
        list(repair_row.get("existing_mock_or_provider_classes") or []),
        list(bean.get("sandbox_occurrences") or []),
    )
    failing_tests = _dedupe_failing_tests(
        list(repair_row.get("failing_tests") or []),
        context_failures,
    )
    provider_exists_not_loaded = bool(repair_row.get("provider_exists_but_not_loaded")) or str(bean.get("provider_status") or "") == "not_loaded"
    reference_shows_equivalent = bool(repair_row.get("migrated_reference_shows_equivalent_test_setup")) or bool(
        list(bean.get("migrated_reference_occurrences") or [])
    )

    patch_candidate = _narrow_patch_candidate(
        missing_bean_type=missing_bean_type,
        failing_tests=failing_tests,
        support_classes=support_classes,
        sandbox_root=sandbox_root,
    )
    reference_evidence = _reference_evidence(
        patch_candidate=patch_candidate,
        failing_tests=failing_tests,
        support_classes=support_classes,
        sandbox_root=sandbox_root,
        reference_root=reference_root,
        bean=bean,
    )
    if reference_evidence["classification"] == "broad_change_not_safe":
        patch_candidate = None

    proposal_strategies = _strategy_ids_from_repair(repair_row)
    if patch_candidate:
        proposal_strategies = _dedupe_strings([patch_candidate["strategy_id"], *proposal_strategies])
    if not proposal_strategies:
        proposal_strategies = ["human_investigation_required"]

    llm_candidate = not bool(patch_candidate)
    recommended_steps = _recommended_steps(
        missing_bean_type=missing_bean_type,
        patch_candidate=patch_candidate,
        support_classes=support_classes,
        failing_tests=failing_tests,
    )
    patch_text = ""
    if patch_candidate and patch_candidate.get("updated_text"):
        patch_text = _render_patch(
            path=Path(str(patch_candidate["target_file"])),
            original_text=str(patch_candidate["original_text"]),
            updated_text=str(patch_candidate["updated_text"]),
        )
    return {
        "missing_bean_type": missing_bean_type,
        "failing_test_classes": _dedupe_strings(str(item.get("test_class") or "") for item in failing_tests if item),
        "failing_tests": failing_tests,
        "test_support_classes": support_classes,
        "provider_exists_but_not_loaded": provider_exists_not_loaded,
        "migrated_reference_shows_equivalent_test_setup": reference_shows_equivalent,
        "support_class_loaded_by_failing_tests": bool(patch_candidate["support_loaded"]) if patch_candidate else _support_loaded_guess(failing_tests, support_classes),
        "proposal_strategies": proposal_strategies,
        "deterministic_candidate": bool(patch_candidate),
        "llm_candidate": llm_candidate,
        "human_review_required": True,
        "unsafe_to_auto_apply": True,
        "safe_to_auto_apply": False,
        "patch_proposal_available": bool(patch_text),
        "patch_strategy": str(patch_candidate.get("strategy_id") or "") if patch_candidate else "",
        "patch_target_file": str(patch_candidate.get("target_file") or "") if patch_candidate else "",
        "reference_evidence": reference_evidence,
        "patch_risks": [
            "Patch is proposal-only and may still alter loaded Boot 3 test context semantics.",
            "Bean override or configuration import changes can affect multiple tests sharing the same ApplicationContext.",
        ],
        "tests_to_rerun": _dedupe_strings(
            [str(item.get("test_class") or "") for item in failing_tests if item]
            + ["target/surefire-reports for the affected test slice"]
        ),
        "recommended_investigation_steps": recommended_steps,
        "patch_text": patch_text,
        "legacy_evidence_summary": _legacy_evidence_summary(bean, legacy_root),
    }


def _narrow_patch_candidate(
    *,
    missing_bean_type: str,
    failing_tests: list[dict[str, Any]],
    support_classes: list[dict[str, Any]],
    sandbox_root: Path | None,
) -> dict[str, Any] | None:
    if sandbox_root is None or len(support_classes) != 1:
        return None
    test_files = _unique_test_files(failing_tests)
    if len(test_files) != 1:
        return None
    support = support_classes[0]
    support_class = str(support.get("class_name") or "").strip()
    support_file = _resolve_repo_file(sandbox_root, str(support.get("file") or ""))
    if not support_class or support_file is None or not support_file.is_file():
        return None
    test_file = test_files[0]
    if not test_file.is_file():
        return None
    test_text = _read_text(test_file)
    support_text = _read_text(support_file)
    support_markers = set(str(item) for item in list(support.get("matched_markers") or []))
    if "MOCKITOBEAN" not in support_markers and "MOCKBEAN" not in support_markers and "TEST_CONFIGURATION" not in support_markers:
        return None

    test_state = _annotation_state(test_text)
    support_loaded = _support_loaded(test_state, support_class)
    support_class_ref = f"{support_class}.class"
    support_package = _package_name(support_text)
    test_package = _package_name(test_text)

    for annotation_kind, key in (
        ("spring_boot_test_classes", "classes ="),
        ("context_configuration_classes", "classes ="),
        ("import_classes", None),
    ):
        classes = list(test_state.get(annotation_kind) or [])
        if classes and support_class not in classes:
            updated_text = _append_support_class(
                text=test_text,
                annotation_kind=annotation_kind,
                support_class=support_class,
                support_package=support_package,
                test_package=test_package,
            )
            if updated_text and updated_text != test_text:
                return {
                    "strategy_id": {
                        "spring_boot_test_classes": "add_support_class_to_spring_boot_test_classes",
                        "context_configuration_classes": "add_support_class_to_context_configuration_classes",
                        "import_classes": "add_import_for_test_support_configuration",
                    }[annotation_kind],
                    "target_file": str(test_file),
                    "original_text": test_text,
                    "updated_text": updated_text,
                    "support_loaded": support_loaded,
                    "support_class": support_class,
                    "support_class_ref": support_class_ref,
                }

    if not support_loaded and support_markers.intersection({"MOCKITOBEAN", "MOCKBEAN", "TEST_CONFIGURATION"}):
        if bool(test_state.get("uses_spring_boot_test")) and not list(test_state.get("spring_boot_test_classes") or []):
            updated_text = _add_import_annotation(
                text=test_text,
                support_class=support_class,
                support_package=support_package,
                test_package=test_package,
            )
            if updated_text and updated_text != test_text:
                return {
                    "strategy_id": "add_import_for_test_support_configuration",
                    "target_file": str(test_file),
                    "original_text": test_text,
                    "updated_text": updated_text,
                    "support_loaded": support_loaded,
                    "support_class": support_class,
                    "support_class_ref": support_class_ref,
                }

    if support_loaded and support_markers.intersection({"MOCKITOBEAN", "MOCKBEAN"}):
        support_fields = _mockito_bean_fields(support_text, missing_bean_type)
        if len(support_fields) == 1 and "@MockitoBean" not in test_text and "@MockBean" not in test_text:
            updated_text = _duplicate_mockito_bean_into_test(
                text=test_text,
                bean_simple=missing_bean_type.rsplit(".", 1)[-1],
                field_name=support_fields[0]["field_name"],
                bean_package=missing_bean_type.rsplit(".", 1)[0] if "." in missing_bean_type else "",
                test_package=test_package,
            )
            if updated_text and updated_text != test_text:
                return {
                    "strategy_id": "duplicate_mockito_bean_into_failing_test_context",
                    "target_file": str(test_file),
                    "original_text": test_text,
                    "updated_text": updated_text,
                    "support_loaded": support_loaded,
                    "support_class": support_class,
                    "support_class_ref": support_class_ref,
                }
    return None


def _reference_evidence(
    *,
    patch_candidate: dict[str, Any] | None,
    failing_tests: list[dict[str, Any]],
    support_classes: list[dict[str, Any]],
    sandbox_root: Path | None,
    reference_root: Path | None,
    bean: dict[str, Any],
) -> dict[str, Any]:
    if reference_root is None or not reference_root.is_dir():
        return {"classification": "unrelated", "summary": "No migrated reference evidence provided.", "related_files": []}
    related_files: list[str] = []
    if patch_candidate:
        target_file = _resolve_path(patch_candidate.get("target_file"))
        if target_file and sandbox_root:
            rel = _safe_relative(target_file, sandbox_root)
            if rel:
                related_files.append(rel)
    for support in support_classes:
        file_ref = str(support.get("file") or "")
        if file_ref:
            related_files.append(file_ref)
    related_files = _dedupe_strings(related_files)
    if len(list(bean.get("migrated_reference_occurrences") or [])) > 4:
        return {
            "classification": "broad_change_not_safe",
            "summary": "Reference touches several related occurrences; broad change is not safe to collapse into a narrow patch proposal.",
            "related_files": related_files,
        }
    if not patch_candidate:
        return {
            "classification": "ambiguous",
            "summary": "Reference exists, but current sandbox evidence does not narrow to a single safe patch strategy.",
            "related_files": related_files,
        }
    target_rel = _safe_relative(Path(str(patch_candidate["target_file"])), sandbox_root) if sandbox_root else ""
    if not target_rel:
        return {
            "classification": "ambiguous",
            "summary": "Reference comparison could not resolve related sandbox test file.",
            "related_files": related_files,
        }
    reference_target = reference_root / target_rel
    if not reference_target.is_file():
        return {
            "classification": "unrelated",
            "summary": "Reference project does not contain the matching failing test file path.",
            "related_files": related_files,
        }
    reference_text = _read_text(reference_target)
    support_class = str(patch_candidate.get("support_class") or "").strip()
    if not support_class:
        return {
            "classification": "ambiguous",
            "summary": "Reference comparison found matching file, but support class could not be resolved.",
            "related_files": related_files,
        }
    if f"{support_class}.class" in reference_text or f"@Import({support_class}.class)" in reference_text:
        return {
            "classification": "supports_patch",
            "summary": "Reference test wiring shows the same support class explicitly attached to the failing Boot test context.",
            "related_files": related_files,
        }
    if "@MockitoBean" in reference_text and str(patch_candidate.get("strategy_id") or "") == "duplicate_mockito_bean_into_failing_test_context":
        return {
            "classification": "supports_patch",
            "summary": "Reference test class contains direct @MockitoBean override evidence matching the proposed localized repair.",
            "related_files": related_files,
        }
    if "@SpringBootTest" in reference_text or "@ContextConfiguration" in reference_text:
        return {
            "classification": "ambiguous",
            "summary": "Reference uses related Boot test wiring, but it does not clearly narrow to the same localized patch shape.",
            "related_files": related_files,
        }
    return {
        "classification": "unrelated",
        "summary": "Reference file is present, but it does not show matching localized support wiring for this bean failure.",
        "related_files": related_files,
    }


def _strategy_ids_from_repair(repair_row: dict[str, Any]) -> list[str]:
    values = []
    for item in list(repair_row.get("proposal_strategies") or []):
        if isinstance(item, dict):
            values.append(str(item.get("strategy_id") or ""))
    return _dedupe_strings(item for item in values if item)


def _dedupe_support_classes(repair_support: list[dict[str, Any]], sandbox_occurrences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for item in [*repair_support, *sandbox_occurrences]:
        if not isinstance(item, dict):
            continue
        file_ref = str(item.get("file") or "")
        class_name = str(item.get("class_name") or "")
        if not file_ref or not class_name:
            continue
        markers = list(item.get("matched_markers") or [])
        scope = str(item.get("scope") or "")
        role = str(item.get("occurrence_role") or "")
        if scope and scope != "test":
            continue
        if role and role != "provider":
            continue
        key = (file_ref, class_name)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "class_name": class_name,
                "file": file_ref,
                "matched_markers": markers,
            }
        )
    return rows


def _dedupe_failing_tests(repair_failing: list[dict[str, Any]], context_failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen: set[tuple[str, str]] = set()
    candidates = [*repair_failing]
    for item in context_failures:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "test_class": str(item.get("test_class") or ""),
                "test_method": str(item.get("test_method") or ""),
                "category": str(item.get("category") or ""),
                "symptom": str(item.get("symptom") or ""),
            }
        )
    for item in candidates:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("test_class") or ""), str(item.get("test_method") or ""))
        if key in seen or not key[0]:
            continue
        seen.add(key)
        rows.append(dict(item))
    return rows


def _annotation_state(text: str) -> dict[str, Any]:
    return {
        "uses_spring_boot_test": "@SpringBootTest" in text,
        "uses_context_configuration": "@ContextConfiguration" in text,
        "uses_web_mvc_test": "@WebMvcTest" in text,
        "spring_boot_test_classes": _annotation_classes(_SPRING_BOOT_TEST_RE, text),
        "context_configuration_classes": _annotation_classes(_CONTEXT_CONFIGURATION_RE, text),
        "import_classes": _annotation_classes(_IMPORT_RE, text),
    }


def _annotation_classes(pattern: re.Pattern[str], text: str) -> list[str]:
    match = pattern.search(text)
    if not match:
        return []
    return _dedupe_strings(
        cleaned.rsplit(".", 1)[-1]
        for cleaned in _ANNOTATION_CLASS_RE.findall(match.group(1))
        if cleaned
    )


def _support_loaded(test_state: dict[str, Any], support_class: str) -> bool:
    for key in ("spring_boot_test_classes", "context_configuration_classes", "import_classes"):
        if support_class in list(test_state.get(key) or []):
            return True
    return False


def _support_loaded_guess(failing_tests: list[dict[str, Any]], support_classes: list[dict[str, Any]]) -> bool:
    if len(support_classes) != 1:
        return False
    support_class = str(support_classes[0].get("class_name") or "")
    for test in failing_tests:
        state = _annotation_state(_read_text(_resolve_path(test.get("file"))) if test.get("file") else "")
        if _support_loaded(state, support_class):
            return True
        symptom = str(test.get("symptom") or "")
        if f"{support_class}]" in symptom or f"{support_class}," in symptom or f"{support_class}.class" in symptom:
            return True
    return False


def _append_support_class(
    *,
    text: str,
    annotation_kind: str,
    support_class: str,
    support_package: str,
    test_package: str,
) -> str:
    pattern = {
        "spring_boot_test_classes": _SPRING_BOOT_TEST_RE,
        "context_configuration_classes": _CONTEXT_CONFIGURATION_RE,
        "import_classes": _IMPORT_RE,
    }[annotation_kind]
    match = pattern.search(text)
    if not match:
        return ""
    current = match.group(1).strip()
    existing = _ANNOTATION_CLASS_RE.findall(current)
    support_ref = f"{support_class}.class"
    if any(item.rsplit(".", 1)[-1] == support_class for item in existing):
        return ""
    refs = [item if item.endswith(".class") else f"{item}.class" for item in _split_refs(current)]
    refs.append(support_ref)
    body = "{%s}" % ", ".join(refs)
    updated_annotation = match.group(0).replace(match.group(1), body)
    updated_text = text[: match.start()] + updated_annotation + text[match.end() :]
    return _ensure_import(updated_text, support_class, support_package, test_package)


def _add_import_annotation(
    *,
    text: str,
    support_class: str,
    support_package: str,
    test_package: str,
) -> str:
    if "@Import" in text:
        return ""
    import_stmt = "import org.springframework.context.annotation.Import;\n"
    updated = text
    if import_stmt not in updated:
        updated = _insert_import(updated, import_stmt)
    class_annotation = f"@Import({support_class}.class)\n"
    anchor = "@SpringBootTest"
    idx = updated.find(anchor)
    if idx < 0:
        return ""
    updated = updated[:idx] + class_annotation + updated[idx:]
    return _ensure_import(updated, support_class, support_package, test_package)


def _duplicate_mockito_bean_into_test(
    *,
    text: str,
    bean_simple: str,
    field_name: str,
    bean_package: str,
    test_package: str,
) -> str:
    if "@MockitoBean" in text and bean_simple in text:
        return ""
    import_stmt = "import org.springframework.test.context.bean.override.mockito.MockitoBean;\n"
    updated = text
    if import_stmt not in updated:
        updated = _insert_import(updated, import_stmt)
    updated = _ensure_import(updated, bean_simple, bean_package, test_package)
    class_match = _CLASS_RE.search(updated)
    if not class_match:
        return ""
    brace_idx = updated.find("{", class_match.end())
    if brace_idx < 0:
        return ""
    field_block = "\n\n    " + _MOCK_FIELD_TEMPLATE.format(bean_simple=bean_simple, field_name=field_name) + "\n"
    return updated[: brace_idx + 1] + field_block + updated[brace_idx + 1 :]


def _mockito_bean_fields(text: str, missing_bean_type: str) -> list[dict[str, str]]:
    bean_simple = missing_bean_type.rsplit(".", 1)[-1]
    rows = []
    for bean_type, field_name in _MOCKITO_FIELD_RE.findall(text):
        if bean_type.rsplit(".", 1)[-1] != bean_simple:
            continue
        rows.append({"bean_type": bean_type, "field_name": field_name})
    return rows


def _legacy_evidence_summary(bean: dict[str, Any], legacy_root: Path | None) -> str:
    provider_type = str(bean.get("likely_legacy_provider_type") or "")
    provider_status = str(bean.get("provider_status") or "")
    occurrences = list(bean.get("legacy_occurrences") or [])
    test_provider = next(
        (
            item
            for item in occurrences
            if isinstance(item, dict)
            and str(item.get("scope") or "") == "test"
            and str(item.get("occurrence_role") or "") == "provider"
        ),
        None,
    )
    if test_provider:
        return (
            f"Legacy test support still provisioned this bean via {provider_type or 'test support'}"
            f" in {str(test_provider.get('file') or '')}."
        )
    if legacy_root and occurrences:
        return f"Legacy project still referenced the bean and provider status is {provider_status or 'unknown'}."
    return "Legacy evidence was limited; provider pattern remains under human review."


def _recommended_steps(
    *,
    missing_bean_type: str,
    patch_candidate: dict[str, Any] | None,
    support_classes: list[dict[str, Any]],
    failing_tests: list[dict[str, Any]],
) -> list[str]:
    if patch_candidate:
        return [
            f"Review the localized proposal for {missing_bean_type} before editing any Boot 3 test context.",
            "Rerun only the affected failing test class first, then rerun the full shared test slice if context starts successfully.",
        ]
    support_files = ", ".join(str(item.get("file") or "") for item in support_classes[:2] if item)
    test_classes = ", ".join(str(item.get("test_class") or "") for item in failing_tests[:2] if item)
    return [
        f"Inspect whether failing tests ({test_classes or 'affected tests'}) actually load support from {support_files or 'the legacy support class'}.",
        "Compare Boot 3 test annotations, imported classes, and bean override visibility before changing business behavior.",
        "Use governed human review or later LLM proposal flow only after narrowing the minimal context repair.",
    ]


def _unique_test_files(failing_tests: list[dict[str, Any]]) -> list[Path]:
    files = []
    seen = set()
    for item in failing_tests:
        file_ref = str(item.get("file") or "").strip()
        if not file_ref or file_ref in seen:
            continue
        path = _resolve_path(file_ref)
        if path is None:
            continue
        seen.add(file_ref)
        files.append(path)
    return files


def _split_refs(value: str) -> list[str]:
    cleaned = value.strip()
    if cleaned.startswith("{") and cleaned.endswith("}"):
        cleaned = cleaned[1:-1]
    return [part.strip().replace(".class", "") + ".class" for part in cleaned.split(",") if part.strip()]


def _ensure_import(text: str, class_name: str, class_package: str, test_package: str) -> str:
    if not class_package or class_package == test_package:
        return text
    import_stmt = f"import {class_package}.{class_name};\n"
    if import_stmt in text:
        return text
    return _insert_import(text, import_stmt)


def _insert_import(text: str, import_stmt: str) -> str:
    imports = list(re.finditer(r"^import\s+.*?;\s*$", text, flags=re.MULTILINE))
    if imports:
        last = imports[-1]
        return text[: last.end()] + "\n" + import_stmt.rstrip("\n") + text[last.end() :]
    package_match = _PACKAGE_RE.search(text)
    if package_match:
        return text[: package_match.end()] + "\n\n" + import_stmt + text[package_match.end() :]
    return import_stmt + "\n" + text


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
        "# Legacy Guided Patch Proposal",
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
            lines.append(
                f"  provider exists but not loaded: {str(proposal.get('provider_exists_but_not_loaded')).lower()}"
            )
            lines.append(
                f"  support loaded by failing tests: {str(proposal.get('support_class_loaded_by_failing_tests')).lower()}"
            )
            lines.append(f"  patch strategy: {proposal.get('patch_strategy', '') or 'none'}")
            reference_evidence = dict(proposal.get("reference_evidence") or {})
            lines.append(
                f"  reference evidence: {reference_evidence.get('classification', '') or 'none'}"
            )
    return "\n".join(lines) + "\n"


def _backfill_artifact_refs(run_root: Path, report_path: Path, summary_path: Path, patch_path: Path | None) -> None:
    refs = {
        "legacy_guided_patch_proposal": str(report_path),
        "legacy_guided_patch_proposal_summary": str(summary_path),
    }
    if patch_path:
        refs["legacy_guided_patch_proposal_patch"] = str(patch_path)
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
        line = f"- Legacy Guided Patch Proposal: {report_path}"
        if line not in text:
            anchor = "- Test Context Repair Proposal:"
            if anchor in text:
                text = text.replace(anchor, f"{anchor}\n{line}", 1)
            else:
                text = text.rstrip() + f"\n{line}\n"
            final_summary.write_text(text, encoding="utf-8")


def _package_name(text: str) -> str:
    match = _PACKAGE_RE.search(text)
    return str(match.group(1) if match else "").strip()


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return ""


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
