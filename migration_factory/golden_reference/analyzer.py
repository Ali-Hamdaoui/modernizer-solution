from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import json
import re
import xml.etree.ElementTree as ET


BUILD_FILE_NAMES = {
    "pom.xml",
    "mvnw",
    "mvnw.cmd",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
}
DETERMINISTIC_RULE_CANDIDATES = {
    "JAVA_VERSION_ALIGNMENT",
    "SPRING_BOOT_VERSION_ALIGNMENT",
    "LOMBOK_VERSION_ALIGNMENT",
    "JACOCO_VERSION_ALIGNMENT",
    "SLF4J_VERSION_ALIGNMENT",
    "JACKSON_VERSION_ALIGNMENT",
    "SPRING_SECURITY_VERSION_ALIGNMENT",
    "JJWT_VERSION_ALIGNMENT",
    "JAKARTA_DEPENDENCY_ADDITION",
    "IMPORT_JAVAX_XML_BIND_TO_JAKARTA",
    "IMPORT_JAVAX_VALIDATION_TO_JAKARTA",
    "IMPORT_JAVAX_SERVLET_TO_JAKARTA",
    "SPRING_DATA_SORT_BY_MIGRATION",
    "MOCKBEAN_TO_MOCKITOBEAN",
    "INITMOCKS_TO_OPENMOCKS",
}
HUMAN_REVIEW_RULE_CANDIDATES = {
    "AZURE_SDK_API_MIGRATION",
    "SPRING_SECURITY_BEHAVIOR_REVIEW",
    "PUBLIC_API_SIGNATURE_CHANGE",
}
LLM_RULE_CANDIDATES = {
    "UNMAPPED_SOURCE_TRANSFORMATION",
}


@dataclass(frozen=True)
class GoldenReferenceAnalysisResult:
    report_path: Path
    summary_path: Path
    payload: dict[str, Any]


def analyze_golden_reference(
    *,
    legacy_path: str | Path,
    migrated_reference_path: str | Path,
    output_dir: str | Path,
    factory_sandbox_path: str | Path | None = None,
    project_id: str | None = None,
) -> GoldenReferenceAnalysisResult:
    legacy_root = Path(legacy_path).expanduser().resolve()
    reference_root = Path(migrated_reference_path).expanduser().resolve()
    factory_root = Path(factory_sandbox_path).expanduser().resolve() if factory_sandbox_path else None
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    legacy_pom = _select_primary_pom(legacy_root)
    reference_pom = _select_primary_pom(reference_root)

    legacy_snapshot = _snapshot_directory(legacy_root)
    reference_snapshot = _snapshot_directory(reference_root)
    factory_snapshot = _snapshot_directory(factory_root) if factory_root else None

    build_changes = _build_file_changes(legacy_snapshot, reference_snapshot)
    pom_diff = _compare_pom_versions(legacy_pom, reference_pom)
    import_changes = _compare_import_patterns(legacy_snapshot, reference_snapshot)
    code_patterns = _detect_code_patterns(legacy_snapshot, reference_snapshot)
    files_delta = _files_delta(legacy_snapshot, reference_snapshot)
    api_changes = _public_api_signature_changes(legacy_snapshot, reference_snapshot)
    azure_changes = _detect_azure_dependency_pattern(pom_diff)
    framework_library_signals = _detect_framework_library_signals(pom_diff)
    anti_patterns = _anti_pattern_warnings(reference_pom)
    candidate_rules = _candidate_rules(
        pom_diff=pom_diff,
        import_changes=import_changes,
        code_patterns=code_patterns,
        api_changes=api_changes,
        azure_changes=azure_changes,
    )
    gap_analysis = (
        _compare_factory_gap(
            legacy_snapshot=legacy_snapshot,
            reference_snapshot=reference_snapshot,
            factory_snapshot=factory_snapshot,
            reference_patterns={item["rule_id"] for item in candidate_rules["deterministic_safe_candidates"]},
        )
        if factory_snapshot is not None
        else {}
    )

    payload = {
        "project_id": project_id or "",
        "legacy_path": str(legacy_root),
        "migrated_reference_path": str(reference_root),
        "factory_sandbox_path": str(factory_root) if factory_root else "",
        "detected_build_files_changed": build_changes,
        "dependency_version_changes": pom_diff["dependency_changes"],
        "plugin_tooling_changes": pom_diff["plugin_changes"],
        "java_version_change": pom_diff["java_version_change"],
        "spring_boot_version_change": pom_diff["spring_boot_version_change"],
        "javax_to_jakarta_import_changes": import_changes,
        "framework_library_signals": framework_library_signals,
        "test_modernization_patterns": [item for item in code_patterns if item["scope"] == "test"],
        "source_code_transformation_patterns": [item for item in code_patterns if item["scope"] == "source"],
        "files_added": files_delta["added"],
        "files_removed": files_delta["removed"],
        "files_renamed_if_detectable": files_delta["renamed"],
        "candidate_deterministic_rules": candidate_rules["deterministic_safe_candidates"],
        "candidate_human_review_items": candidate_rules["human_review_candidates"],
        "candidate_llm_remediation_items": candidate_rules["llm_candidates"],
        "anti_pattern_warnings": anti_patterns,
        "factory_gap_analysis": gap_analysis,
    }

    report_path = resolved_output_dir / "golden_reference_gap_report.json"
    summary_path = resolved_output_dir / "golden_reference_summary.md"
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(_render_summary(payload), encoding="utf-8")
    return GoldenReferenceAnalysisResult(report_path=report_path, summary_path=summary_path, payload=payload)


def _snapshot_directory(root: Path | None) -> dict[str, str]:
    if root is None or not root.is_dir():
        return {}
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if _should_skip_relative_parts(relative_parts):
            continue
        try:
            snapshot[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return snapshot


def _build_file_changes(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> list[str]:
    changed: list[str] = []
    for path in sorted(set(legacy_snapshot) | set(reference_snapshot)):
        name = Path(path).name
        if name not in BUILD_FILE_NAMES:
            continue
        if legacy_snapshot.get(path) != reference_snapshot.get(path):
            changed.append(path)
    return changed


def _compare_pom_versions(legacy_pom: Path, reference_pom: Path) -> dict[str, Any]:
    legacy = _parse_pom(legacy_pom)
    reference = _parse_pom(reference_pom)
    dependency_changes = []
    plugin_changes = []
    all_deps = sorted(set(legacy["dependencies"]) | set(reference["dependencies"]))
    for coordinate in all_deps:
        old_version = legacy["dependencies"].get(coordinate, "")
        new_version = reference["dependencies"].get(coordinate, "")
        if old_version != new_version:
            dependency_changes.append(
                {
                    "coordinate": coordinate,
                    "legacy_version": old_version,
                    "reference_version": new_version,
                }
            )
    all_plugins = sorted(set(legacy["plugins"]) | set(reference["plugins"]))
    for coordinate in all_plugins:
        old_version = legacy["plugins"].get(coordinate, "")
        new_version = reference["plugins"].get(coordinate, "")
        if old_version != new_version:
            plugin_changes.append(
                {
                    "coordinate": coordinate,
                    "legacy_version": old_version,
                    "reference_version": new_version,
                }
            )
    return {
        "dependency_changes": dependency_changes,
        "plugin_changes": plugin_changes,
        "java_version_change": {
            "legacy": legacy["java_version"],
            "reference": reference["java_version"],
        },
        "spring_boot_version_change": {
            "legacy": legacy["spring_boot_version"],
            "reference": reference["spring_boot_version"],
        },
        "legacy_dependencies": legacy["dependencies"],
        "reference_dependencies": reference["dependencies"],
    }


def _parse_pom(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"dependencies": {}, "plugins": {}, "java_version": "", "spring_boot_version": "", "raw": ""}
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {"dependencies": {}, "plugins": {}, "java_version": "", "spring_boot_version": "", "raw": raw}
    root = tree.getroot()
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0][1:]

    properties = {}
    props = root.find(_tag(namespace, "properties"))
    if props is not None:
        for child in list(props):
            name = child.tag.split("}", 1)[-1]
            properties[name] = (child.text or "").strip()

    dependencies = {}
    for dependency in root.findall(".//" + _tag(namespace, "dependency")):
        group_id = _child_text(dependency, namespace, "groupId")
        artifact_id = _child_text(dependency, namespace, "artifactId")
        if not group_id or not artifact_id:
            continue
        version = _resolve_property(_child_text(dependency, namespace, "version"), properties)
        dependencies[f"{group_id}:{artifact_id}"] = version

    plugins = {}
    for plugin in root.findall(".//" + _tag(namespace, "plugin")):
        group_id = _child_text(plugin, namespace, "groupId") or "org.apache.maven.plugins"
        artifact_id = _child_text(plugin, namespace, "artifactId")
        if not artifact_id:
            continue
        version = _resolve_property(_child_text(plugin, namespace, "version"), properties)
        plugins[f"{group_id}:{artifact_id}"] = version

    java_version = (
        properties.get("java.version")
        or properties.get("maven.compiler.release")
        or properties.get("maven.compiler.target")
        or properties.get("maven.compiler.source")
        or ""
    )
    spring_boot_version = properties.get("spring-boot.version", "")
    parent = root.find(_tag(namespace, "parent"))
    if parent is not None:
        if _child_text(parent, namespace, "groupId") == "org.springframework.boot":
            spring_boot_version = spring_boot_version or _resolve_property(
                _child_text(parent, namespace, "version"),
                properties,
            )
    return {
        "dependencies": dependencies,
        "plugins": plugins,
        "java_version": java_version,
        "spring_boot_version": spring_boot_version,
        "raw": raw,
    }


def _select_primary_pom(root: Path) -> Path:
    direct = root / "pom.xml"
    if direct.is_file():
        return direct
    candidates = [
        path for path in root.rglob("pom.xml")
        if not _should_skip_relative_parts(path.relative_to(root).parts)
    ]
    if not candidates:
        return direct
    candidates.sort(key=lambda item: (len(item.relative_to(root).parts), str(item.relative_to(root)).lower()))
    return candidates[0]


def _should_skip_relative_parts(parts: tuple[str, ...]) -> bool:
    return ".git" in parts or ".migration" in parts or "target" in parts


def _compare_import_patterns(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> list[dict[str, Any]]:
    patterns = [
        ("javax.xml.bind.", "jakarta.xml.bind.", "IMPORT_JAVAX_XML_BIND_TO_JAKARTA"),
        ("javax.validation.", "jakarta.validation.", "IMPORT_JAVAX_VALIDATION_TO_JAKARTA"),
        ("javax.servlet.", "jakarta.servlet.", "IMPORT_JAVAX_SERVLET_TO_JAKARTA"),
    ]
    changes: list[dict[str, Any]] = []
    for legacy_import, migrated_import, rule_id in patterns:
        legacy_count = _count_import_occurrences(legacy_snapshot, legacy_import)
        reference_count = _count_import_occurrences(reference_snapshot, migrated_import)
        if legacy_count or reference_count:
            changes.append(
                {
                    "rule_id": rule_id,
                    "legacy_import": legacy_import,
                    "reference_import": migrated_import,
                    "legacy_count": legacy_count,
                    "reference_count": reference_count,
                }
            )
    return changes


def _detect_code_patterns(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> list[dict[str, Any]]:
    rules = [
        ("SPRING_DATA_SORT_BY_MIGRATION", ("new Sort(",), ("Sort.by(",), "source"),
        ("MOCKBEAN_TO_MOCKITOBEAN", ("@MockBean", "MockBean"), ("@MockitoBean", "MockitoBean"), "test"),
        (
            "INITMOCKS_TO_OPENMOCKS",
            ("MockitoAnnotations.initMocks",),
            ("MockitoAnnotations.openMocks",),
            "test",
        ),
    ]
    results: list[dict[str, Any]] = []
    common_paths = sorted(set(legacy_snapshot) & set(reference_snapshot))
    for rule_id, before_markers, after_markers, scope in rules:
        files = []
        for path in common_paths:
            if not path.endswith(".java"):
                continue
            legacy_text = legacy_snapshot[path]
            reference_text = reference_snapshot[path]
            if any(marker in legacy_text for marker in before_markers) and any(
                marker in reference_text for marker in after_markers
            ):
                files.append(path)
        if files:
            results.append(
                {
                    "rule_id": rule_id,
                    "before": list(before_markers),
                    "after": list(after_markers),
                    "scope": scope,
                    "files": files,
                }
            )
    return results


def _files_delta(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> dict[str, list[dict[str, Any]] | list[str]]:
    legacy_paths = set(legacy_snapshot)
    reference_paths = set(reference_snapshot)
    added = sorted(reference_paths - legacy_paths)
    removed = sorted(legacy_paths - reference_paths)
    renamed = []
    unmatched_added = set(added)
    unmatched_removed = set(removed)
    for old_path in removed:
        old_name = Path(old_path).name
        old_text = legacy_snapshot[old_path]
        for new_path in list(unmatched_added):
            if Path(new_path).suffix != Path(old_path).suffix:
                continue
            similarity = SequenceMatcher(None, old_text, reference_snapshot[new_path]).ratio()
            if similarity >= 0.65 or Path(new_path).name == old_name:
                renamed.append({"legacy_path": old_path, "reference_path": new_path, "similarity": round(similarity, 3)})
                unmatched_added.discard(new_path)
                unmatched_removed.discard(old_path)
                break
    return {
        "added": sorted(unmatched_added),
        "removed": sorted(unmatched_removed),
        "renamed": renamed,
    }


def _public_api_signature_changes(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> list[dict[str, Any]]:
    changes = []
    for path in sorted(set(legacy_snapshot) & set(reference_snapshot)):
        if not path.endswith(".java"):
            continue
        legacy_sigs = set(_public_method_signatures(legacy_snapshot[path]))
        reference_sigs = set(_public_method_signatures(reference_snapshot[path]))
        if legacy_sigs != reference_sigs and (legacy_sigs or reference_sigs):
            changes.append(
                {
                    "file": path,
                    "legacy_only": sorted(legacy_sigs - reference_sigs),
                    "reference_only": sorted(reference_sigs - legacy_sigs),
                }
            )
    return changes


def _detect_azure_dependency_pattern(pom_diff: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_deps = pom_diff["legacy_dependencies"]
    reference_deps = pom_diff["reference_dependencies"]
    legacy_azure = sorted(coord for coord in legacy_deps if coord.startswith("com.microsoft.azure:"))
    reference_azure = sorted(
        coord for coord in reference_deps if coord.startswith("com.azure:") or coord.startswith("com.azure.spring:")
    )
    if not legacy_azure and not reference_azure:
        return []
    return [
        {
            "legacy_coordinates": legacy_azure,
            "reference_coordinates": reference_azure,
        }
    ]


def _detect_framework_library_signals(pom_diff: dict[str, Any]) -> list[dict[str, Any]]:
    legacy_deps = pom_diff["legacy_dependencies"]
    reference_deps = pom_diff["reference_dependencies"]
    signals = []
    signal_specs = [
        (
            "JJWT",
            lambda deps: sorted(coord for coord in deps if coord.startswith("io.jsonwebtoken:jjwt")),
        ),
        (
            "JUNEAU",
            lambda deps: sorted(coord for coord in deps if coord.startswith("org.apache.juneau:")),
        ),
        (
            "POWERMOCK",
            lambda deps: sorted(coord for coord in deps if coord.startswith("org.powermock:")),
        ),
        (
            "AZURE_OLD_SDK",
            lambda deps: sorted(coord for coord in deps if coord.startswith("com.microsoft.azure:")),
        ),
        (
            "AZURE_NEW_SDK",
            lambda deps: sorted(coord for coord in deps if coord.startswith("com.azure:") or coord.startswith("com.azure.spring:")),
        ),
    ]
    for signal_id, extractor in signal_specs:
        legacy_matches = extractor(legacy_deps)
        reference_matches = extractor(reference_deps)
        if legacy_matches or reference_matches:
            signals.append(
                {
                    "signal_id": signal_id,
                    "legacy_coordinates": legacy_matches,
                    "reference_coordinates": reference_matches,
                }
            )
    return signals


def _anti_pattern_warnings(reference_pom: Path) -> list[str]:
    if not reference_pom.is_file():
        return []
    parsed = _parse_pom(reference_pom)
    warnings: list[str] = []
    raw = parsed["raw"]
    explicit_versions = len(re.findall(r"<version>[^<]+</version>", raw))
    if explicit_versions >= 8:
        warnings.append("Migrated reference keeps many explicit versions; consider BOM-managed simplification.")
    for coordinate, version in parsed["dependencies"].items():
        if version and coordinate in parsed["plugins"]:
            warnings.append(f"Duplicate explicit version management detected for {coordinate}.")
    if "<dependencyManagement>" in raw and raw.count("<dependencyManagement>") > 1:
        warnings.append("Multiple dependencyManagement sections detected; simplify merged management.")
    return warnings


def _candidate_rules(
    *,
    pom_diff: dict[str, Any],
    import_changes: list[dict[str, Any]],
    code_patterns: list[dict[str, Any]],
    api_changes: list[dict[str, Any]],
    azure_changes: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    deterministic: list[dict[str, Any]] = []
    human_review: list[dict[str, Any]] = []
    llm_candidates: list[dict[str, Any]] = []

    java_change = pom_diff["java_version_change"]
    if java_change["legacy"] != java_change["reference"]:
        deterministic.append(_rule("JAVA_VERSION_ALIGNMENT", "Update Java version/tooling metadata."))
    boot_change = pom_diff["spring_boot_version_change"]
    if boot_change["legacy"] != boot_change["reference"]:
        deterministic.append(_rule("SPRING_BOOT_VERSION_ALIGNMENT", "Align Spring Boot target version."))

    coordinate_to_rule = {
        "org.projectlombok:lombok": "LOMBOK_VERSION_ALIGNMENT",
        "org.jacoco:jacoco-maven-plugin": "JACOCO_VERSION_ALIGNMENT",
        "org.slf4j:slf4j-api": "SLF4J_VERSION_ALIGNMENT",
        "com.fasterxml.jackson.core:jackson-databind": "JACKSON_VERSION_ALIGNMENT",
        "org.springframework.security:spring-security-core": "SPRING_SECURITY_VERSION_ALIGNMENT",
        "io.jsonwebtoken:jjwt": "JJWT_VERSION_ALIGNMENT",
        "io.jsonwebtoken:jjwt-api": "JJWT_VERSION_ALIGNMENT",
    }
    for item in pom_diff["dependency_changes"] + pom_diff["plugin_changes"]:
        rule_id = coordinate_to_rule.get(item["coordinate"])
        if rule_id and not any(existing["rule_id"] == rule_id for existing in deterministic):
            deterministic.append(_rule(rule_id, f"Align {item['coordinate']} version."))
        if item["coordinate"] == "jakarta.validation:jakarta.validation-api" or item["coordinate"] == "org.springframework.boot:spring-boot-starter-validation":
            deterministic.append(_rule("JAKARTA_DEPENDENCY_ADDITION", "Add Boot 3/Jakarta validation dependency."))
        if item["coordinate"].startswith("org.springframework.security:"):
            human_review.append(_rule("SPRING_SECURITY_BEHAVIOR_REVIEW", "Review Spring Security runtime behavior under Boot 3."))

    for change in import_changes:
        deterministic.append(_rule(change["rule_id"], f"Migrate import namespace {change['legacy_import']} to {change['reference_import']}."))
    for pattern in code_patterns:
        if pattern["rule_id"] in DETERMINISTIC_RULE_CANDIDATES:
            deterministic.append(_rule(pattern["rule_id"], f"Apply deterministic pattern {pattern['rule_id']}."))
    if azure_changes:
        human_review.append(_rule("AZURE_SDK_API_MIGRATION", "Review Azure SDK coordinate and API migration."))
    if api_changes:
        human_review.append(_rule("PUBLIC_API_SIGNATURE_CHANGE", "Review public API signature changes against consumers."))

    matched_rule_ids = {item["rule_id"] for item in deterministic} | {item["rule_id"] for item in human_review}
    if not matched_rule_ids or api_changes:
        llm_candidates.append(
            _rule(
                "UNMAPPED_SOURCE_TRANSFORMATION",
                "Review localized code/test changes not covered by deterministic rules.",
            )
        )

    return {
        "deterministic_safe_candidates": _dedupe_rules(deterministic),
        "human_review_candidates": _dedupe_rules(human_review),
        "llm_candidates": _dedupe_rules(llm_candidates),
    }


def _compare_factory_gap(
    *,
    legacy_snapshot: dict[str, str],
    reference_snapshot: dict[str, str],
    factory_snapshot: dict[str, str] | None,
    reference_patterns: set[str],
) -> dict[str, Any]:
    factory_patterns = {item["rule_id"] for item in _detect_code_patterns(legacy_snapshot, factory_snapshot or {})}
    reference_imports = {item["rule_id"] for item in _compare_import_patterns(legacy_snapshot, reference_snapshot)}
    factory_imports = {item["rule_id"] for item in _compare_import_patterns(legacy_snapshot, factory_snapshot or {})}
    reference_all = sorted(reference_patterns | reference_imports)
    factory_all = sorted(factory_patterns | factory_imports)
    statuses = []
    all_rules = sorted(set(reference_all) | set(factory_all))
    for rule_id in all_rules:
        in_reference = rule_id in reference_all
        in_factory = rule_id in factory_all
        if in_reference and in_factory:
            status = "BOTH_APPLIED"
        elif in_reference:
            status = "REFERENCE_APPLIED_FACTORY_MISSING"
        else:
            status = "FACTORY_APPLIED_REFERENCE_MISSING"
        statuses.append({"rule_id": rule_id, "status": status})
    if not statuses and factory_snapshot:
        statuses.append({"rule_id": "UNMAPPED_SOURCE_TRANSFORMATION", "status": "DIVERGENT_APPROACH"})
    return {
        "reference_detected_rules": reference_all,
        "factory_detected_rules": factory_all,
        "gap_statuses": statuses,
    }


def _render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Golden Reference Summary",
        "",
        f"Project ID: {payload.get('project_id') or '(none)'}",
        "",
        "## Version Shifts",
        f"- Java: {payload['java_version_change']['legacy']} -> {payload['java_version_change']['reference']}",
        f"- Spring Boot: {payload['spring_boot_version_change']['legacy']} -> {payload['spring_boot_version_change']['reference']}",
        "",
        "## Deterministic Candidates",
    ]
    for item in payload["candidate_deterministic_rules"]:
        lines.append(f"- {item['rule_id']}: {item['recommended_action']}")
    lines.extend(["", "## Human Review"])
    for item in payload["candidate_human_review_items"]:
        lines.append(f"- {item['rule_id']}: {item['recommended_action']}")
    lines.extend(["", "## LLM Candidates"])
    for item in payload["candidate_llm_remediation_items"]:
        lines.append(f"- {item['rule_id']}: {item['recommended_action']}")
    lines.extend(["", "## Framework Signals"])
    for item in payload.get("framework_library_signals", []):
        lines.append(
            f"- {item['signal_id']}: legacy={len(item['legacy_coordinates'])} reference={len(item['reference_coordinates'])}"
        )
    if payload.get("factory_gap_analysis"):
        lines.extend(["", "## Factory Gap Status"])
        for item in payload["factory_gap_analysis"].get("gap_statuses", []):
            lines.append(f"- {item['rule_id']}: {item['status']}")
    return "\n".join(lines) + "\n"


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _child_text(element: ET.Element, namespace: str, name: str) -> str:
    child = element.find(_tag(namespace, name))
    return (child.text or "").strip() if child is not None and child.text else ""


def _resolve_property(value: str, properties: dict[str, str]) -> str:
    text = (value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return properties.get(text[2:-1], text)
    return text


def _count_import_occurrences(snapshot: dict[str, str], token: str) -> int:
    count = 0
    for path, text in snapshot.items():
        if path.endswith(".java"):
            count += text.count(f"import {token}")
    return count


def _public_method_signatures(source_text: str) -> list[str]:
    return re.findall(r"public\s+[\w<>\[\], ?]+\s+(\w+\s*\([^)]*\))", source_text)


def _rule(rule_id: str, action: str) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "recommended_action": action,
        "safe_to_auto_apply": rule_id in DETERMINISTIC_RULE_CANDIDATES,
        "requires_human_review": rule_id in HUMAN_REVIEW_RULE_CANDIDATES or rule_id in LLM_RULE_CANDIDATES,
    }


def _dedupe_rules(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        rule_id = str(item.get("rule_id") or "")
        if not rule_id or rule_id in seen:
            continue
        seen.add(rule_id)
        result.append(item)
    return result
