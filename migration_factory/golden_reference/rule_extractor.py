from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import json


DEFAULT_FACTORY_CAPABILITIES = {
    "already_covered_rule_ids": {
        "LOMBOK_VERSION_ALIGNMENT",
        "JACOCO_VERSION_ALIGNMENT",
        "SLF4J_VERSION_ALIGNMENT",
        "JACKSON_VERSION_ALIGNMENT",
        "SPRING_SECURITY_VERSION_ALIGNMENT",
        "JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT",
        "SPRING_DATA_SORT_BY_MIGRATION",
        "MAVEN_COMPILER_PARAMETERS_ALIGNMENT",
        "FAILED_SANDBOX_REPORTING",
        "FAILURE_CLASSIFICATION",
        "REMEDIATION_PLAN",
        "LLM_POLICY_GATE",
    }
}
DEFAULT_REVIEW_CAPABILITIES = {
    "already_covered_review_rule_ids": set(),
}
TEST_MODERNIZATION_RULE_IDS = {
    "MOCKBEAN_TO_MOCKITOBEAN",
    "INITMOCKS_TO_OPENMOCKS",
    "POWERMOCK_LEGACY_TEST_STRATEGY",
}
HIGH_PRIORITY_RULE_IDS = {
    "JJWT_VERSION_ALIGNMENT",
    "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW",
    "MOCKBEAN_TO_MOCKITOBEAN",
    "INITMOCKS_TO_OPENMOCKS",
    "POWERMOCK_LEGACY_TEST_STRATEGY",
    "AZURE_SDK_MIGRATION_PLAYBOOK",
    "JAKARTA_HYBRID_STRATEGY",
    "API_CONTRACT_REVIEW_GATE",
    "CONSUMER_COMPATIBILITY_VALIDATION",
}
SIGNAL_RULE_MAP = {
    "JJWT": ("JJWT_VERSION_ALIGNMENT", "missing_deterministic_rules", "Align JJWT versions during framework hops."),
    "JUNEAU": (
        "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW",
        "missing_deterministic_rules",
        "Review or align Juneau stack for Boot 3 migration.",
    ),
    "POWERMOCK": (
        "POWERMOCK_LEGACY_TEST_STRATEGY",
        "missing_test_modernization_rules",
        "Create legacy PowerMock migration or containment strategy.",
    ),
}


@dataclass(frozen=True)
class RuleExtractionResult:
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]


def extract_rules_from_golden_reports(
    *,
    report_paths: Iterable[str | Path],
    output_dir: str | Path,
    factory_capabilities: dict[str, Any] | None = None,
    factory_capability_inventory: dict[str, Any] | str | Path | None = None,
) -> RuleExtractionResult:
    reports = [_read_report(path) for path in report_paths]
    capabilities = _merge_capabilities(factory_capabilities, factory_capability_inventory)
    buckets: dict[str, dict[str, dict[str, Any]]] = {
        "already_covered_by_factory": {},
        "covered_review_capabilities": {},
        "missing_deterministic_rules": {},
        "missing_test_modernization_rules": {},
        "human_review_gates": {},
        "llm_remediation_candidates": {},
        "migration_playbooks_needed": {},
        "anti_pattern_warnings": {},
    }

    for report in reports:
        project_id = str(report.get("project_id") or "").strip() or "unknown-project"
        _ingest_candidate_rules(report, project_id, buckets, capabilities)
        _ingest_framework_signals(report, project_id, buckets, capabilities)
        _ingest_jakarta_import_rules(report, project_id, buckets, capabilities)
        _ingest_derived_gates(report, project_id, buckets, capabilities)
        _ingest_anti_patterns(report, project_id, buckets)

    payload = {
        "source_report_paths": [str(Path(path).expanduser().resolve()) for path in report_paths],
        "factory_capabilities": {
            "already_covered_rule_ids": sorted(capabilities["already_covered_rule_ids"]),
            "already_covered_review_rule_ids": sorted(capabilities["already_covered_review_rule_ids"]),
            "coverage_sources": capabilities["coverage_sources"],
        },
    }
    for bucket_name, items in buckets.items():
        payload[bucket_name] = _finalize_bucket(items)

    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "rule_extraction_report.json"
    summary_path = resolved_output_dir / "rule_extraction_summary.md"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    return RuleExtractionResult(report_path=report_path, summary_path=summary_path, payload=payload)


def _ingest_candidate_rules(
    report: dict[str, Any],
    project_id: str,
    buckets: dict[str, dict[str, dict[str, Any]]],
    capabilities: dict[str, Any],
) -> None:
    for item in list(report.get("candidate_deterministic_rules", []) or []):
        rule_id = _normalize_deterministic_rule_id(str(item.get("rule_id") or "").strip())
        if not rule_id:
            continue
        covered_bucket = _covered_bucket_for_rule(rule_id, capabilities)
        if covered_bucket:
            bucket = covered_bucket
            coverage_source = capabilities["coverage_sources"].get(rule_id, "static_fallback")
        elif rule_id in TEST_MODERNIZATION_RULE_IDS:
            bucket = "missing_test_modernization_rules"
            coverage_source = ""
        else:
            bucket = "missing_deterministic_rules"
            coverage_source = ""
        _accumulate(
            buckets[bucket],
            rule_id=rule_id,
            category=bucket,
            project_id=project_id,
            evidence=item.get("recommended_action") or rule_id,
            safe_to_auto_apply=bool(item.get("safe_to_auto_apply")),
            requires_human_approval=bool(item.get("requires_human_review")),
            llm_candidate=False,
            coverage_source=coverage_source,
        )

    for item in list(report.get("candidate_human_review_items", []) or []):
        rule_id = _normalize_human_rule_id(str(item.get("rule_id") or "").strip())
        target_bucket = (
            "covered_review_capabilities"
            if rule_id in capabilities["already_covered_review_rule_ids"]
            else "human_review_gates"
        )
        _accumulate(
            buckets[target_bucket],
            rule_id=rule_id,
            category=target_bucket,
            project_id=project_id,
            evidence=item.get("recommended_action") or rule_id,
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get(rule_id, ""),
        )

    for item in list(report.get("candidate_llm_remediation_items", []) or []):
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id:
            continue
        _accumulate(
            buckets["llm_remediation_candidates"],
            rule_id=rule_id,
            category="llm_remediation_candidates",
            project_id=project_id,
            evidence=item.get("recommended_action") or rule_id,
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=True,
        )


def _ingest_framework_signals(
    report: dict[str, Any],
    project_id: str,
    buckets: dict[str, dict[str, dict[str, Any]]],
    capabilities: dict[str, Any],
) -> None:
    for signal in list(report.get("framework_library_signals", []) or []):
        signal_id = str(signal.get("signal_id") or "").strip()
        if signal_id in SIGNAL_RULE_MAP:
            rule_id, bucket_name, message = SIGNAL_RULE_MAP[signal_id]
            target_bucket = _covered_bucket_for_rule(rule_id, capabilities) or bucket_name
            _accumulate(
                buckets[target_bucket],
                rule_id=rule_id,
                category=target_bucket,
                project_id=project_id,
                evidence=message,
                safe_to_auto_apply=bucket_name == "missing_deterministic_rules",
                requires_human_approval=bucket_name != "missing_deterministic_rules",
                llm_candidate=False,
                coverage_source=capabilities["coverage_sources"].get(rule_id, ""),
            )

    signal_ids = {str(item.get("signal_id") or "") for item in list(report.get("framework_library_signals", []) or [])}
    if "AZURE_OLD_SDK" in signal_ids or "AZURE_NEW_SDK" in signal_ids:
        target_bucket = _covered_bucket_for_rule("AZURE_SDK_MIGRATION_PLAYBOOK", capabilities) or "migration_playbooks_needed"
        _accumulate(
            buckets[target_bucket],
            rule_id="AZURE_SDK_MIGRATION_PLAYBOOK",
            category=target_bucket,
            project_id=project_id,
            evidence="Reference migration shows Azure SDK coordinate or API transition.",
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get("AZURE_SDK_MIGRATION_PLAYBOOK", ""),
        )


def _ingest_jakarta_import_rules(
    report: dict[str, Any],
    project_id: str,
    buckets: dict[str, dict[str, dict[str, Any]]],
    capabilities: dict[str, Any],
) -> None:
    for item in list(report.get("javax_to_jakarta_import_changes", []) or []):
        rule_id = str(item.get("rule_id") or "").strip()
        if not rule_id:
            continue
        target_bucket = _covered_bucket_for_rule(rule_id, capabilities) or "missing_deterministic_rules"
        _accumulate(
            buckets[target_bucket],
            rule_id=rule_id,
            category=target_bucket,
            project_id=project_id,
            evidence=item.get("recommended_action") or f"Apply deterministic import migration {rule_id}.",
            safe_to_auto_apply=target_bucket != "covered_review_capabilities",
            requires_human_approval=target_bucket == "covered_review_capabilities",
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get(rule_id, ""),
        )


def _ingest_derived_gates(
    report: dict[str, Any],
    project_id: str,
    buckets: dict[str, dict[str, dict[str, Any]]],
    capabilities: dict[str, Any],
) -> None:
    import_rule_ids = {str(item.get("rule_id") or "") for item in list(report.get("javax_to_jakarta_import_changes", []) or [])}
    if len(import_rule_ids) >= 2:
        target_bucket = _covered_bucket_for_rule("JAKARTA_HYBRID_STRATEGY", capabilities) or "migration_playbooks_needed"
        _accumulate(
            buckets[target_bucket],
            rule_id="JAKARTA_HYBRID_STRATEGY",
            category=target_bucket,
            project_id=project_id,
            evidence="Multiple Jakarta namespace migrations detected across the same reference project.",
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get("JAKARTA_HYBRID_STRATEGY", ""),
        )

    human_rule_ids = {str(item.get("rule_id") or "") for item in list(report.get("candidate_human_review_items", []) or [])}
    if "PUBLIC_API_SIGNATURE_CHANGE" in human_rule_ids:
        api_bucket = _covered_bucket_for_rule("API_CONTRACT_REVIEW_GATE", capabilities) or "human_review_gates"
        consumer_bucket = _covered_bucket_for_rule("CONSUMER_COMPATIBILITY_VALIDATION", capabilities) or "migration_playbooks_needed"
        _accumulate(
            buckets[api_bucket],
            rule_id="API_CONTRACT_REVIEW_GATE",
            category=api_bucket,
            project_id=project_id,
            evidence="Reference migration changed public API signatures.",
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get("API_CONTRACT_REVIEW_GATE", ""),
        )
        _accumulate(
            buckets[consumer_bucket],
            rule_id="CONSUMER_COMPATIBILITY_VALIDATION",
            category=consumer_bucket,
            project_id=project_id,
            evidence="Public API changes imply downstream consumer compatibility validation.",
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            coverage_source=capabilities["coverage_sources"].get("CONSUMER_COMPATIBILITY_VALIDATION", ""),
        )


def _ingest_anti_patterns(
    report: dict[str, Any],
    project_id: str,
    buckets: dict[str, dict[str, dict[str, Any]]],
) -> None:
    for warning in list(report.get("anti_pattern_warnings", []) or []):
        rule_id = "ANTI_PATTERN_WARNING"
        _accumulate(
            buckets["anti_pattern_warnings"],
            rule_id=f"{rule_id}:{warning}",
            category="anti_pattern_warnings",
            project_id=project_id,
            evidence=str(warning),
            safe_to_auto_apply=False,
            requires_human_approval=True,
            llm_candidate=False,
            display_rule_id=rule_id,
        )


def _accumulate(
    bucket: dict[str, dict[str, Any]],
    *,
    rule_id: str,
    category: str,
    project_id: str,
    evidence: str,
    safe_to_auto_apply: bool,
    requires_human_approval: bool,
    llm_candidate: bool,
    display_rule_id: str | None = None,
    coverage_source: str = "",
) -> None:
    item = bucket.setdefault(
        rule_id,
        {
            "rule_id": display_rule_id or rule_id,
            "category": category,
            "source_projects": [],
            "evidence_summary": [],
            "safe_to_auto_apply": safe_to_auto_apply,
            "requires_human_approval": requires_human_approval,
            "llm_candidate": llm_candidate,
            "coverage_source": coverage_source,
        },
    )
    if project_id not in item["source_projects"]:
        item["source_projects"].append(project_id)
    if evidence and evidence not in item["evidence_summary"]:
        item["evidence_summary"].append(evidence)
    item["safe_to_auto_apply"] = bool(item["safe_to_auto_apply"] or safe_to_auto_apply)
    item["requires_human_approval"] = bool(item["requires_human_approval"] or requires_human_approval)
    item["llm_candidate"] = bool(item["llm_candidate"] or llm_candidate)
    item["coverage_source"] = item["coverage_source"] or coverage_source


def _finalize_bucket(items: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for key in sorted(items):
        item = dict(items[key])
        item["source_projects"] = sorted(item["source_projects"])
        item["suggested_priority"] = _priority_for_item(item)
        item["suggested_next_ticket"] = _suggested_next_ticket(item)
        result.append(item)
    return result


def _priority_for_item(item: dict[str, Any]) -> str:
    if len(item["source_projects"]) > 1 or item["rule_id"] in HIGH_PRIORITY_RULE_IDS:
        return "HIGH"
    if item["category"] in {"missing_test_modernization_rules", "migration_playbooks_needed", "human_review_gates"}:
        return "MEDIUM"
    return "LOW"


def _suggested_next_ticket(item: dict[str, Any]) -> str:
    mapping = {
        "JJWT_VERSION_ALIGNMENT": "Add deterministic JJWT alignment rule.",
        "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW": "Add Juneau alignment/review gate.",
        "MOCKBEAN_TO_MOCKITOBEAN": "Add deterministic Spring Boot test annotation modernization.",
        "INITMOCKS_TO_OPENMOCKS": "Add deterministic Mockito initMocks to openMocks modernization.",
        "POWERMOCK_LEGACY_TEST_STRATEGY": "Define PowerMock legacy test containment or migration playbook.",
        "AZURE_SDK_MIGRATION_PLAYBOOK": "Create Azure SDK migration playbook and review gate.",
        "JAKARTA_HYBRID_STRATEGY": "Define Jakarta hybrid migration playbook for mixed namespaces.",
        "API_CONTRACT_REVIEW_GATE": "Add API contract review gate to approval flow.",
        "CONSUMER_COMPATIBILITY_VALIDATION": "Add consumer compatibility validation evidence gate.",
    }
    return mapping.get(item["rule_id"], f"Backlog {item['rule_id']} for industrialized migration support.")


def _normalize_human_rule_id(rule_id: str) -> str:
    mapping = {
        "PUBLIC_API_SIGNATURE_CHANGE": "API_CONTRACT_REVIEW_GATE",
    }
    return mapping.get(rule_id, rule_id)


def _normalize_deterministic_rule_id(rule_id: str) -> str:
    mapping = {
        "JAKARTA_DEPENDENCY_ADDITION": "JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT",
    }
    return mapping.get(rule_id, rule_id)


def _merge_capabilities(
    factory_capabilities: dict[str, Any] | None,
    factory_capability_inventory: dict[str, Any] | str | Path | None,
) -> dict[str, Any]:
    merged = {
        "already_covered_rule_ids": set(DEFAULT_FACTORY_CAPABILITIES["already_covered_rule_ids"]),
        "already_covered_review_rule_ids": set(DEFAULT_REVIEW_CAPABILITIES["already_covered_review_rule_ids"]),
        "coverage_sources": {
            rule_id: "static_fallback"
            for rule_id in set(DEFAULT_FACTORY_CAPABILITIES["already_covered_rule_ids"])
            | set(DEFAULT_REVIEW_CAPABILITIES["already_covered_review_rule_ids"])
        },
    }
    if factory_capabilities and isinstance(factory_capabilities.get("already_covered_rule_ids"), (list, set, tuple)):
        for item in factory_capabilities["already_covered_rule_ids"]:
            rule_id = str(item)
            merged["already_covered_rule_ids"].add(rule_id)
            merged["coverage_sources"][rule_id] = "explicit_config"
    if factory_capabilities and isinstance(factory_capabilities.get("already_covered_review_rule_ids"), (list, set, tuple)):
        for item in factory_capabilities["already_covered_review_rule_ids"]:
            rule_id = str(item)
            merged["already_covered_review_rule_ids"].add(rule_id)
            merged["coverage_sources"][rule_id] = "explicit_config"
    inventory_payload = _load_inventory_payload(factory_capability_inventory)
    for capability in list(inventory_payload.get("capabilities", []) or []):
        if not isinstance(capability, dict):
            continue
        capability_id = str(capability.get("capability_id") or "").strip()
        capability_type = str(capability.get("capability_type") or "").strip()
        if not capability_id:
            continue
        if capability_type == "REVIEW_GATE":
            merged["already_covered_review_rule_ids"].add(capability_id)
        else:
            merged["already_covered_rule_ids"].add(capability_id)
        merged["coverage_sources"][capability_id] = "inventory_artifact"
    return merged


def _load_inventory_payload(factory_capability_inventory: dict[str, Any] | str | Path | None) -> dict[str, Any]:
    if factory_capability_inventory is None:
        return {}
    if isinstance(factory_capability_inventory, dict):
        return dict(factory_capability_inventory)
    path = Path(factory_capability_inventory).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Factory capability inventory is not a JSON object: {path}")
    return payload


def _covered_bucket_for_rule(rule_id: str, capabilities: dict[str, Any]) -> str:
    if rule_id in capabilities["already_covered_review_rule_ids"]:
        return "covered_review_capabilities"
    if rule_id in capabilities["already_covered_rule_ids"]:
        return "already_covered_by_factory"
    return ""


def _read_report(path_like: str | Path) -> dict[str, Any]:
    path = Path(path_like).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Golden reference report is not a JSON object: {path}")
    payload["_report_path"] = str(path)
    return payload


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Rule Extraction Summary",
        "",
        "## Already Covered",
    ]
    for item in payload["already_covered_by_factory"]:
        lines.append(
            f"- {item['rule_id']} [{item['suggested_priority']}]: "
            f"{', '.join(item['source_projects'])} (coverage={item.get('coverage_source', '') or 'unknown'})"
        )
    lines.extend(["", "## Covered Review Capabilities"])
    for item in payload["covered_review_capabilities"]:
        lines.append(
            f"- {item['rule_id']} [{item['suggested_priority']}]: "
            f"{', '.join(item['source_projects'])} (coverage={item.get('coverage_source', '') or 'unknown'})"
        )
    lines.extend(["", "## Missing Deterministic Rules"])
    for item in payload["missing_deterministic_rules"]:
        lines.append(f"- {item['rule_id']} [{item['suggested_priority']}]: {item['suggested_next_ticket']}")
    lines.extend(["", "## Missing Test Modernization Rules"])
    for item in payload["missing_test_modernization_rules"]:
        lines.append(f"- {item['rule_id']} [{item['suggested_priority']}]: {item['suggested_next_ticket']}")
    lines.extend(["", "## Human Review Gates"])
    for item in payload["human_review_gates"]:
        lines.append(f"- {item['rule_id']} [{item['suggested_priority']}]: {', '.join(item['source_projects'])}")
    lines.extend(["", "## LLM Candidates"])
    for item in payload["llm_remediation_candidates"]:
        lines.append(f"- {item['rule_id']} [{item['suggested_priority']}]: {', '.join(item['source_projects'])}")
    lines.extend(["", "## Migration Playbooks Needed"])
    for item in payload["migration_playbooks_needed"]:
        lines.append(f"- {item['rule_id']} [{item['suggested_priority']}]: {item['suggested_next_ticket']}")
    lines.extend(["", "## Anti-Pattern Warnings"])
    for item in payload["anti_pattern_warnings"]:
        lines.append(f"- {item['rule_id']}: {'; '.join(item['evidence_summary'])}")
    return "\n".join(lines) + "\n"
