from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


JAVA_IMPORT_RULES = {
    "javax.validation": "IMPORT_JAVAX_VALIDATION_TO_JAKARTA",
    "javax.xml.bind": "IMPORT_JAVAX_XML_BIND_TO_JAKARTA",
    "javax.servlet": "IMPORT_JAVAX_SERVLET_TO_JAKARTA",
}
RISK_TO_CAPABILITY = {
    "JAVA_VERSION_ALIGNMENT": "JAVA_VERSION_ALIGNMENT",
    "SPRING_BOOT_VERSION_ALIGNMENT": "SPRING_BOOT_VERSION_ALIGNMENT",
    "SPRING_BOOT_MULTI_HOP_ROUTE": "SPRING_BOOT_MULTI_HOP_ROUTE",
    "JDK_AWARE_ANALYSIS_PREVIEW": "JDK_AWARE_ANALYSIS_PREVIEW",
    "JDK_AWARE_TRANSFORMATION_UNITS": "JDK_AWARE_TRANSFORMATION_UNITS",
    "IMPORT_JAVAX_VALIDATION_TO_JAKARTA": "IMPORT_JAVAX_VALIDATION_TO_JAKARTA",
    "IMPORT_JAVAX_XML_BIND_TO_JAKARTA": "IMPORT_JAVAX_XML_BIND_TO_JAKARTA",
    "IMPORT_JAVAX_SERVLET_TO_JAKARTA": "IMPORT_JAVAX_SERVLET_TO_JAKARTA",
    "SPRING_SECURITY_VERSION_ALIGNMENT": "SPRING_SECURITY_VERSION_ALIGNMENT",
    "JJWT_VERSION_ALIGNMENT": "JJWT_VERSION_ALIGNMENT",
    "JACKSON_VERSION_ALIGNMENT": "JACKSON_VERSION_ALIGNMENT",
    "LOMBOK_VERSION_ALIGNMENT": "LOMBOK_VERSION_ALIGNMENT",
    "JACOCO_VERSION_ALIGNMENT": "JACOCO_VERSION_ALIGNMENT",
    "POWERMOCK_LEGACY_TEST_STRATEGY": "POWERMOCK_LEGACY_TEST_STRATEGY",
    "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW": "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW",
    "AZURE_SDK_MIGRATION_PLAYBOOK": "AZURE_SDK_MIGRATION_PLAYBOOK",
    "MOCKBEAN_TO_MOCKITOBEAN": "MOCKBEAN_TO_MOCKITOBEAN",
    "INITMOCKS_TO_OPENMOCKS": "INITMOCKS_TO_OPENMOCKS",
    "API_CONTRACT_REVIEW_GATE": "API_CONTRACT_REVIEW_GATE",
    "CONSUMER_COMPATIBILITY_VALIDATION": "CONSUMER_COMPATIBILITY_VALIDATION",
}
PUBLIC_API_HINTS = ("dto", "api", "contract", "public")


@dataclass(frozen=True)
class ReadinessPackResult:
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]


def generate_candidate_project_readiness_pack(
    *,
    candidate_project_path: str | Path,
    output_dir: str | Path,
    project_id: str | None = None,
    factory_capability_inventory_path: str | Path | None = None,
    migration_wave_plan_path: str | Path | None = None,
    golden_rule_extraction_report_path: str | Path | None = None,
    target_profile_id: str | None = None,
) -> ReadinessPackResult:
    candidate_root = Path(candidate_project_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    pom_payload = _parse_pom(candidate_root / "pom.xml")
    coordinates = dict(pom_payload["coordinates"])
    project_name = str(project_id or coordinates["artifactId"] or candidate_root.name)
    dependencies = list(pom_payload["dependencies"])
    internal_dependencies = _detect_internal_dependency_hints(dependencies, coordinates)
    source_scan = _scan_source_tree(candidate_root)
    risk_signals = _detect_risk_signals(pom_payload, source_scan, target_profile_id or "")
    capability_inventory = _load_json_path(factory_capability_inventory_path)
    capability_index = _capability_index(capability_inventory)
    rule_report = _load_json_path(golden_rule_extraction_report_path)
    missing_rule_ids = _missing_rule_ids(rule_report)
    matching_capabilities, uncovered_signals = _map_signals_to_capabilities(risk_signals, capability_index, missing_rule_ids)
    review_gates_expected = _review_gates(matching_capabilities)
    deterministic_transformations = _deterministic_transforms(matching_capabilities)
    llm_candidate_areas = _llm_candidates(risk_signals, matching_capabilities)
    consumer_validation_suggestions = _consumer_suggestions(
        migration_wave_plan_path=migration_wave_plan_path,
        project_id=project_id or "",
        candidate_root=candidate_root,
        coordinates=coordinates,
    )
    warnings = _warnings_for_missing_inputs(candidate_root, capability_inventory, migration_wave_plan_path)
    human_review_required = bool(
        review_gates_expected
        or uncovered_signals
        or any(str(signal.get("severity") or "") == "HIGH" for signal in risk_signals)
        or any(bool(item.get("human_review_required")) for item in consumer_validation_suggestions)
    )
    readiness_status = _readiness_status(
        candidate_root=candidate_root,
        coordinates=coordinates,
        risk_signals=risk_signals,
        uncovered_signals=uncovered_signals,
        human_review_required=human_review_required,
        warnings=warnings,
    )
    recommended_next_actions = _recommended_next_actions(
        readiness_status=readiness_status,
        uncovered_signals=uncovered_signals,
        review_gates_expected=review_gates_expected,
        consumer_validation_suggestions=consumer_validation_suggestions,
        target_profile_id=target_profile_id or "",
    )

    payload = {
        "project_id": project_name,
        "candidate_project_path": str(candidate_root),
        "target_profile_id": str(target_profile_id or ""),
        "detected_maven_coordinates": coordinates,
        "detected_packaging": coordinates.get("packaging", ""),
        "detected_java_version": pom_payload["java_version"],
        "detected_spring_boot_version": pom_payload["spring_boot_version"],
        "detected_internal_dependencies": internal_dependencies,
        "detected_risk_signals": risk_signals,
        "matching_factory_capabilities": matching_capabilities,
        "uncovered_risk_signals": uncovered_signals,
        "review_gates_expected": review_gates_expected,
        "deterministic_transformations_likely_applicable": deterministic_transformations,
        "consumer_validation_suggestions": consumer_validation_suggestions,
        "human_review_required": human_review_required,
        "llm_candidate_areas": llm_candidate_areas,
        "recommended_next_actions": recommended_next_actions,
        "warnings": warnings,
        "readiness_status": readiness_status,
    }
    report_path = output_root / "readiness_pack.json"
    summary_path = output_root / "readiness_pack_summary.md"
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    return ReadinessPackResult(report_path=report_path, summary_path=summary_path, payload=payload)


def _parse_pom(pom_path: Path) -> dict[str, Any]:
    empty = {
        "coordinates": {"groupId": "", "artifactId": "", "version": "", "packaging": ""},
        "dependencies": [],
        "properties": {},
        "java_version": "",
        "spring_boot_version": "",
    }
    if not pom_path.is_file():
        return empty
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return empty
    namespace = _namespace(root.tag)
    parent_info = _parse_parent_coordinates(root, namespace, pom_path.parent)
    properties = _project_properties(root, namespace, parent_info)
    coordinates = {
        "groupId": _resolve_property(_child_text(root, namespace, "groupId"), properties) or parent_info["groupId"],
        "artifactId": _resolve_property(_child_text(root, namespace, "artifactId"), properties),
        "version": _resolve_property(_child_text(root, namespace, "version"), properties) or parent_info["version"],
        "packaging": _resolve_property(_child_text(root, namespace, "packaging"), properties) or "jar",
    }
    dependencies: list[dict[str, str]] = []
    for dependency in root.findall(f".//{_tag(namespace, 'dependencies')}/{_tag(namespace, 'dependency')}"):
        group_id = _resolve_property(_child_text(dependency, namespace, "groupId"), properties)
        artifact_id = _resolve_property(_child_text(dependency, namespace, "artifactId"), properties)
        version = _resolve_property(_child_text(dependency, namespace, "version"), properties)
        scope = _resolve_property(_child_text(dependency, namespace, "scope"), properties) or "compile"
        if not group_id or not artifact_id:
            continue
        dependencies.append(
            {
                "groupId": group_id,
                "artifactId": artifact_id,
                "version": version,
                "scope": scope,
            }
        )
    spring_boot_version = (
        properties.get("spring-boot.version")
        or (
            parent_info["groupId"] == "org.springframework.boot"
            and parent_info["artifactId"] == "spring-boot-starter-parent"
            and parent_info["version"]
        )
        or ""
    )
    java_version = (
        properties.get("java.version")
        or properties.get("maven.compiler.release")
        or properties.get("maven.compiler.target")
        or properties.get("maven.compiler.source")
        or ""
    )
    return {
        "coordinates": coordinates,
        "dependencies": dependencies,
        "properties": properties,
        "java_version": str(java_version),
        "spring_boot_version": str(spring_boot_version),
    }


def _parse_parent_coordinates(root: ET.Element, namespace: str, project_dir: Path) -> dict[str, str]:
    parent = root.find(_tag(namespace, "parent"))
    parent_group = _child_text(parent, namespace, "groupId")
    parent_artifact = _child_text(parent, namespace, "artifactId")
    parent_version = _child_text(parent, namespace, "version")
    relative_path = _child_text(parent, namespace, "relativePath") or "../pom.xml"
    parent_path = (project_dir / relative_path).resolve()
    if parent_path.is_file():
        parsed = _parse_pom(parent_path)
        parent_group = parent_group or parsed["coordinates"]["groupId"]
        parent_artifact = parent_artifact or parsed["coordinates"]["artifactId"]
        parent_version = parent_version or parsed["coordinates"]["version"]
    return {
        "groupId": parent_group,
        "artifactId": parent_artifact,
        "version": parent_version,
    }


def _project_properties(root: ET.Element, namespace: str, parent_info: dict[str, str]) -> dict[str, str]:
    properties: dict[str, str] = {}
    properties_node = root.find(_tag(namespace, "properties"))
    if properties_node is not None:
        for child in list(properties_node):
            local_name = child.tag.rsplit("}", 1)[-1]
            properties[local_name] = (child.text or "").strip()
    project_group = _child_text(root, namespace, "groupId") or parent_info["groupId"]
    project_artifact = _child_text(root, namespace, "artifactId")
    project_version = _child_text(root, namespace, "version") or parent_info["version"]
    properties.update(
        {
            "project.groupId": project_group,
            "project.artifactId": project_artifact,
            "project.version": project_version,
            "groupId": project_group,
            "artifactId": project_artifact,
            "version": project_version,
        }
    )
    return properties


def _resolve_property(value: str, properties: dict[str, str]) -> str:
    text = (value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return properties.get(text[2:-1], text)
    return text


def _detect_internal_dependency_hints(
    dependencies: list[dict[str, str]],
    coordinates: dict[str, str],
) -> list[dict[str, str]]:
    project_group = str(coordinates.get("groupId") or "")
    project_artifact = str(coordinates.get("artifactId") or "")
    hints: list[dict[str, str]] = []
    for dependency in dependencies:
        if not project_group:
            continue
        if dependency["groupId"] != project_group:
            continue
        if dependency["artifactId"] == project_artifact:
            continue
        hints.append(dict(dependency))
    return hints


def _scan_source_tree(candidate_root: Path) -> dict[str, Any]:
    findings = {
        "namespaces": {},
        "test_modernization_hints": [],
        "public_api_files": [],
        "controller_advice_files": [],
        "azure_old_files": [],
        "azure_new_files": [],
    }
    src_root = candidate_root / "src"
    if not src_root.is_dir():
        return findings
    for path in sorted(src_root.rglob("*.java")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = str(path.relative_to(candidate_root))
        for namespace in JAVA_IMPORT_RULES:
            if namespace in text:
                findings["namespaces"].setdefault(namespace, []).append(rel)
        if "@MockBean" in text:
            findings["test_modernization_hints"].append({"rule_id": "MOCKBEAN_TO_MOCKITOBEAN", "file": rel})
        if "MockitoAnnotations.initMocks(" in text:
            findings["test_modernization_hints"].append({"rule_id": "INITMOCKS_TO_OPENMOCKS", "file": rel})
        if _is_public_api_like(Path(rel)):
            findings["public_api_files"].append(rel)
        if "@ControllerAdvice" in text or "@RestControllerAdvice" in text or "ResponseEntityExceptionHandler" in text:
            findings["controller_advice_files"].append(rel)
        if "com.microsoft.azure" in text or "com.microsoft.rest" in text or "com.microsoft.windowsazure" in text:
            findings["azure_old_files"].append(rel)
        if "com.azure" in text:
            findings["azure_new_files"].append(rel)
    return findings


def _detect_risk_signals(
    pom_payload: dict[str, Any],
    source_scan: dict[str, Any],
    target_profile_id: str,
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    java_version = str(pom_payload.get("java_version") or "")
    spring_boot_version = str(pom_payload.get("spring_boot_version") or "")
    if java_version:
        _push_signal(signals, "JAVA_VERSION_ALIGNMENT", f"Detected Java version {java_version}.", "LOW")
    if spring_boot_version:
        _push_signal(signals, "SPRING_BOOT_VERSION_ALIGNMENT", f"Detected Spring Boot version {spring_boot_version}.", "LOW")
    if spring_boot_version.startswith("2.") and "3.5" in target_profile_id:
        _push_signal(signals, "SPRING_BOOT_MULTI_HOP_ROUTE", "Boot 2.x candidate with Boot 3 target suggests multi-hop route.", "MEDIUM")
        _push_signal(signals, "JDK_AWARE_ANALYSIS_PREVIEW", "Route likely needs JDK-aware analysis preview.", "LOW")
        _push_signal(signals, "JDK_AWARE_TRANSFORMATION_UNITS", "Route likely needs JDK-aware transformation units.", "LOW")

    dependencies = list(pom_payload.get("dependencies", []) or [])
    for dependency in dependencies:
        group_id = dependency["groupId"]
        artifact_id = dependency["artifactId"]
        version = dependency["version"]
        coordinate = f"{group_id}:{artifact_id}"
        if group_id == "org.springframework.security":
            _push_signal(signals, "SPRING_SECURITY_VERSION_ALIGNMENT", f"Detected {coordinate}.", "MEDIUM")
        if group_id == "io.jsonwebtoken":
            _push_signal(signals, "JJWT_VERSION_ALIGNMENT", f"Detected {coordinate}.", "MEDIUM")
        if group_id == "org.projectlombok":
            _push_signal(signals, "LOMBOK_VERSION_ALIGNMENT", f"Detected {coordinate}.", "LOW")
        if group_id.startswith("com.fasterxml.jackson") and version:
            _push_signal(signals, "JACKSON_VERSION_ALIGNMENT", f"Detected explicit Jackson version on {coordinate}.", "MEDIUM")
        if group_id.startswith("org.apache.juneau"):
            _push_signal(signals, "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW", f"Detected {coordinate}.", "HIGH")
        if group_id.startswith("org.powermock"):
            _push_signal(signals, "POWERMOCK_LEGACY_TEST_STRATEGY", f"Detected {coordinate}.", "HIGH")
        if group_id.startswith("com.microsoft.azure") or group_id.startswith("com.microsoft.rest") or group_id.startswith("com.microsoft.windowsazure"):
            _push_signal(signals, "AZURE_SDK_MIGRATION_PLAYBOOK", f"Detected legacy Azure SDK {coordinate}.", "HIGH")
        if group_id.startswith("com.azure"):
            _push_signal(signals, "AZURE_SDK_MIGRATION_PLAYBOOK", f"Detected modern Azure SDK {coordinate}.", "MEDIUM")
    if any(dep["groupId"] == "jakarta.xml.bind" for dep in dependencies):
        _push_signal(signals, "JAKARTA_XML_BIND_DEPENDENCY_ALIGNMENT", "Detected jakarta.xml.bind dependency alignment.", "LOW")
    if any(dep["groupId"] == "jakarta.validation" or dep["artifactId"] == "spring-boot-starter-validation" for dep in dependencies):
        _push_signal(signals, "JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT", "Detected validation dependency alignment.", "LOW")

    build_text = json.dumps(pom_payload, sort_keys=True)
    if "jacoco-maven-plugin" in build_text:
        _push_signal(signals, "JACOCO_VERSION_ALIGNMENT", "Detected JaCoCo plugin usage.", "LOW")

    for namespace, rule_id in JAVA_IMPORT_RULES.items():
        files = list(source_scan["namespaces"].get(namespace, []) or [])
        if files:
            _push_signal(signals, rule_id, f"Detected {namespace} usage in source.", "MEDIUM", files)
    for item in list(source_scan.get("test_modernization_hints", []) or []):
        _push_signal(signals, str(item["rule_id"]), f"Detected {item['rule_id']} hint.", "LOW", [str(item["file"])])
    if source_scan.get("controller_advice_files"):
        _push_signal(signals, "API_CONTRACT_REVIEW_GATE", "Detected controller advice / exception handler source hints.", "MEDIUM", source_scan["controller_advice_files"])
    if source_scan.get("public_api_files"):
        _push_signal(signals, "CONSUMER_COMPATIBILITY_VALIDATION", "Detected public API / DTO package hints.", "MEDIUM", source_scan["public_api_files"])
    return signals


def _push_signal(
    signals: list[dict[str, Any]],
    signal_id: str,
    summary: str,
    severity: str,
    files: list[str] | None = None,
) -> None:
    existing = next((item for item in signals if item["signal_id"] == signal_id), None)
    if existing is None:
        signals.append(
            {
                "signal_id": signal_id,
                "summary": summary,
                "severity": severity,
                "files": sorted(set(files or [])),
            }
        )
        return
    if files:
        existing["files"] = sorted(set(list(existing.get("files", [])) + list(files)))
    if summary not in str(existing.get("summary") or ""):
        existing["summary"] = f"{existing['summary']} {summary}".strip()
    existing["severity"] = _max_severity(str(existing["severity"]), severity)


def _max_severity(left: str, right: str) -> str:
    order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    return left if order.get(left, 0) >= order.get(right, 0) else right


def _load_json_path(path_like: str | Path | None) -> dict[str, Any]:
    if not path_like:
        return {}
    path = Path(path_like).expanduser().resolve()
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _capability_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in list(payload.get("capabilities", []) or []):
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability_id") or "").strip()
        if capability_id:
            result[capability_id] = item
    return result


def _missing_rule_ids(report_payload: dict[str, Any]) -> set[str]:
    missing: set[str] = set()
    for bucket_name in (
        "missing_deterministic_rules",
        "missing_test_modernization_rules",
        "human_review_gates",
        "migration_playbooks_needed",
    ):
        for item in list(report_payload.get(bucket_name, []) or []):
            if isinstance(item, dict) and item.get("rule_id"):
                missing.add(str(item["rule_id"]))
    return missing


def _map_signals_to_capabilities(
    risk_signals: list[dict[str, Any]],
    capability_index: dict[str, dict[str, Any]],
    missing_rule_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    matches: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    for signal in risk_signals:
        capability_id = RISK_TO_CAPABILITY.get(str(signal["signal_id"]))
        capability = capability_index.get(capability_id or "")
        if capability:
            matches.append(
                {
                    "signal_id": signal["signal_id"],
                    "capability_id": capability_id,
                    "capability_type": capability.get("capability_type", ""),
                    "category": capability.get("category", ""),
                    "safe_to_auto_apply": capability.get("safe_to_auto_apply", False),
                    "requires_human_approval": capability.get("requires_human_approval", False),
                    "llm_candidate": capability.get("llm_candidate", False),
                }
            )
        elif signal["signal_id"] in missing_rule_ids or capability_id:
            uncovered.append(dict(signal))
    return matches, uncovered


def _review_gates(matching_capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in matching_capabilities if item.get("capability_type") == "REVIEW_GATE"]


def _deterministic_transforms(matching_capabilities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in matching_capabilities
        if item.get("capability_type") == "TRANSFORM" and bool(item.get("safe_to_auto_apply"))
    ]


def _llm_candidates(
    risk_signals: list[dict[str, Any]],
    matching_capabilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    llm_ids = {str(item["capability_id"]) for item in matching_capabilities if bool(item.get("llm_candidate"))}
    result = []
    for signal in risk_signals:
        if signal["signal_id"] in llm_ids:
            result.append({"signal_id": signal["signal_id"], "reason": signal["summary"]})
    return result


def _consumer_suggestions(
    *,
    migration_wave_plan_path: str | Path | None,
    project_id: str,
    candidate_root: Path,
    coordinates: dict[str, str],
) -> list[dict[str, Any]]:
    payload = _load_json_path(migration_wave_plan_path)
    if not payload:
        return []
    project_record = _match_wave_project(payload, project_id, candidate_root, coordinates)
    if not project_record:
        return []
    migrated_project = str(project_record.get("project_id") or "")
    consumers_by_id = {
        str(item.get("project_id") or ""): item
        for item in list(payload.get("projects", []) or [])
        if isinstance(item, dict)
    }
    suggestions: list[dict[str, Any]] = []
    for item in list(payload.get("consumer_validation_plan", []) or []):
        if not isinstance(item, dict) or str(item.get("migrated_project") or "") != migrated_project:
            continue
        warnings = list(payload.get("warnings", []) or [])
        human_review_required = bool(payload.get("cycles")) or any("cycle" in str(warning).lower() for warning in warnings)
        suggestions.append(
            {
                "migrated_project": migrated_project,
                "consumers": [
                    {
                        "consumer_project_id": consumer_id,
                        "consumer_project_path": str((consumers_by_id.get(consumer_id) or {}).get("project_path") or ""),
                        "suggested_command": str(item.get("suggested_command") or "mvn clean test"),
                    }
                    for consumer_id in list(item.get("consumers", []) or [])
                ],
                "warnings": warnings,
                "human_review_required": human_review_required,
            }
        )
    return suggestions


def _match_wave_project(
    payload: dict[str, Any],
    project_id: str,
    candidate_root: Path,
    coordinates: dict[str, str],
) -> dict[str, Any]:
    projects = [item for item in list(payload.get("projects", []) or []) if isinstance(item, dict)]
    if project_id:
        for item in projects:
            if str(item.get("project_id") or "") == project_id:
                return item
    for item in projects:
        if str(item.get("project_path") or "") == str(candidate_root):
            return item
    for item in projects:
        item_coordinates = dict(item.get("coordinates") or {})
        if (
            item_coordinates.get("groupId") == coordinates.get("groupId")
            and item_coordinates.get("artifactId") == coordinates.get("artifactId")
            and coordinates.get("artifactId")
        ):
            return item
    return {}


def _warnings_for_missing_inputs(
    candidate_root: Path,
    capability_inventory: dict[str, Any],
    migration_wave_plan_path: str | Path | None,
) -> list[str]:
    warnings: list[str] = []
    if not (candidate_root / "pom.xml").is_file():
        warnings.append("No pom.xml detected; Maven coordinate and dependency readiness signals may be incomplete.")
    if not capability_inventory:
        warnings.append("Factory capability inventory not provided; capability coverage mapping is limited.")
    if migration_wave_plan_path and not Path(migration_wave_plan_path).expanduser().resolve().is_file():
        warnings.append("Migration wave plan path not found; consumer validation suggestions unavailable.")
    return warnings


def _readiness_status(
    *,
    candidate_root: Path,
    coordinates: dict[str, str],
    risk_signals: list[dict[str, Any]],
    uncovered_signals: list[dict[str, Any]],
    human_review_required: bool,
    warnings: list[str],
) -> str:
    if not (candidate_root / "pom.xml").is_file() and not risk_signals:
        return "INSUFFICIENT_INFORMATION"
    if not coordinates.get("artifactId") and not risk_signals:
        return "INSUFFICIENT_INFORMATION"
    if human_review_required or uncovered_signals:
        return "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION"
    if warnings or risk_signals:
        return "READY_WITH_WARNINGS"
    return "READY_FOR_READ_ONLY_ASSESSMENT"


def _recommended_next_actions(
    *,
    readiness_status: str,
    uncovered_signals: list[dict[str, Any]],
    review_gates_expected: list[dict[str, Any]],
    consumer_validation_suggestions: list[dict[str, Any]],
    target_profile_id: str,
) -> list[str]:
    actions: list[str] = []
    if readiness_status == "INSUFFICIENT_INFORMATION":
        actions.append("Provide valid Maven metadata and source snapshot before migration assessment.")
    if target_profile_id:
        actions.append(f"Run read-only assessment with target profile {target_profile_id}.")
    if uncovered_signals:
        actions.append("Review uncovered risk signals before attempting sandbox migration.")
    if review_gates_expected:
        actions.append("Expect review gates during Boot 3 sandbox migration; prepare human approver coverage.")
    if consumer_validation_suggestions:
        actions.append("Prepare downstream consumer validation for internal dependents after successful sandbox migration.")
    if not actions:
        actions.append("Candidate appears suitable for read-only assessment with current factory coverage.")
    return actions


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Candidate Project Readiness Summary",
        "",
        f"- Project ID: {payload.get('project_id', '')}",
        f"- Readiness Status: {payload.get('readiness_status', '')}",
        f"- Human Review Required: {str(payload.get('human_review_required')).lower()}",
        "",
        "## Coordinates",
        "",
        f"- groupId: {payload.get('detected_maven_coordinates', {}).get('groupId', '')}",
        f"- artifactId: {payload.get('detected_maven_coordinates', {}).get('artifactId', '')}",
        f"- version: {payload.get('detected_maven_coordinates', {}).get('version', '')}",
        f"- packaging: {payload.get('detected_packaging', '')}",
        "",
        "## Detected Risks",
        "",
    ]
    for signal in list(payload.get("detected_risk_signals", []) or []):
        if not isinstance(signal, dict):
            continue
        lines.append(f"- {signal.get('signal_id', '')} [{signal.get('severity', '')}]: {signal.get('summary', '')}")
    lines.extend(["", "## Matching Capabilities", ""])
    for capability in list(payload.get("matching_factory_capabilities", []) or []):
        if not isinstance(capability, dict):
            continue
        lines.append(f"- {capability.get('capability_id', '')}: type={capability.get('capability_type', '')}")
    lines.extend(["", "## Recommended Next Actions", ""])
    for action in list(payload.get("recommended_next_actions", []) or []):
        lines.append(f"- {action}")
    return "\n".join(lines).rstrip() + "\n"


def _is_public_api_like(path: Path) -> bool:
    lowered = [part.lower() for part in path.parts]
    return any(part in PUBLIC_API_HINTS for part in lowered)


def _namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _tag(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}" if namespace else local_name


def _child_text(element: ET.Element | None, namespace: str, local_name: str) -> str:
    if element is None:
        return ""
    child = element.find(_tag(namespace, local_name))
    return (child.text or "").strip() if child is not None and child.text else ""
