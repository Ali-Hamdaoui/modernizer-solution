from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


SCHEMA_VERSION = "1.0.0"
SKIP_DIR_NAMES = {".git", ".migration", "target", "build", "node_modules", "__pycache__", ".idea", ".venv"}
CONFIG_SUFFIXES = {".properties", ".yml", ".yaml", ".xml", ".jks", ".p12", ".pem", ".crt", ".cer"}
TEXT_SUFFIXES = {
    ".java",
    ".kt",
    ".groovy",
    ".xml",
    ".properties",
    ".yml",
    ".yaml",
    ".md",
    ".txt",
    ".json",
    ".sh",
    ".ps1",
    ".cmd",
    ".bat",
    ".gradle",
    ".kts",
}
ENV_VAR_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
IMPORT_PATTERN = re.compile(r"^\s*import\s+([a-zA-Z0-9_.*]+)\s*;", re.MULTILINE)
METHOD_PATTERN = re.compile(r"\b(public|protected|private)\s+[\w<>\[\], ?]+\s+(\w+\s*\([^)]*\))")


@dataclass(frozen=True)
class ReferenceDeltaAnalysisResult:
    legacy_root: Path
    reference_root: Path
    output_path: Path
    payload: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = analyze_reference_delta(
            legacy_path=args.legacy,
            reference_path=args.reference,
            output_path=args.output,
        )
    except ValueError as exc:
        print(str(exc))
        return 2

    summary = _render_cli_summary(result.payload)
    print(summary)
    return 0


def analyze_reference_delta(
    *,
    legacy_path: str | Path,
    reference_path: str | Path,
    output_path: str | Path,
) -> ReferenceDeltaAnalysisResult:
    legacy_root = Path(legacy_path).expanduser().resolve()
    reference_root = Path(reference_path).expanduser().resolve()
    resolved_output = Path(output_path).expanduser().resolve()

    if not legacy_root.exists():
        raise ValueError(f"Legacy path does not exist: {legacy_root}")
    if not reference_root.exists():
        raise ValueError(f"Reference path does not exist: {reference_root}")

    legacy_poms = discover_pom_files(legacy_root)
    reference_poms = discover_pom_files(reference_root)
    if not legacy_poms:
        raise ValueError(f"No pom.xml found under legacy path: {legacy_root}")
    if not reference_poms:
        raise ValueError(f"No pom.xml found under reference path: {reference_root}")

    legacy_primary = select_primary_pom(legacy_root, legacy_poms)
    reference_primary = select_primary_pom(reference_root, reference_poms)
    legacy_snapshot = snapshot_directory(legacy_root)
    reference_snapshot = snapshot_directory(reference_root)
    legacy_pom_data = parse_pom(legacy_primary)
    reference_pom_data = parse_pom(reference_primary)

    dependency_delta = build_dependency_delta(legacy_pom_data, reference_pom_data)
    pom_delta = build_pom_delta(legacy_pom_data, reference_pom_data)
    source_delta = build_source_delta(legacy_snapshot, reference_snapshot)
    runtime_environment = analyze_runtime_environment(reference_root, reference_snapshot)
    api_indicators = detect_api_migration_indicators(
        legacy_snapshot=legacy_snapshot,
        reference_snapshot=reference_snapshot,
        legacy_pom=legacy_pom_data,
        reference_pom=reference_pom_data,
    )
    suspicious_artifacts = detect_suspicious_artifacts(reference_root, reference_snapshot)
    recommended_capability_packs = recommend_capability_packs(
        pom_delta=pom_delta,
        dependency_delta=dependency_delta,
        source_delta=source_delta,
        runtime_environment=runtime_environment,
        api_migration_indicators=api_indicators,
        suspicious_artifacts=suspicious_artifacts,
    )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "legacy": build_project_summary(legacy_root, legacy_primary, legacy_poms, legacy_pom_data, legacy_snapshot),
        "reference": build_project_summary(reference_root, reference_primary, reference_poms, reference_pom_data, reference_snapshot),
        "pom_delta": pom_delta,
        "dependency_delta": dependency_delta,
        "source_delta": source_delta,
        "runtime_environment": runtime_environment,
        "api_migration_indicators": api_indicators,
        "suspicious_artifacts": suspicious_artifacts,
        "recommended_capability_packs": recommended_capability_packs,
    }

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return ReferenceDeltaAnalysisResult(
        legacy_root=legacy_root,
        reference_root=reference_root,
        output_path=resolved_output,
        payload=payload,
    )


def discover_pom_files(root: Path) -> list[Path]:
    pom_files = [
        path
        for path in root.rglob("pom.xml")
        if path.is_file() and not should_skip_relative_parts(path.relative_to(root).parts)
    ]
    pom_files.sort(key=lambda item: (len(item.relative_to(root).parts), item.relative_to(root).as_posix().lower()))
    return pom_files


def select_primary_pom(root: Path, pom_files: list[Path]) -> Path:
    candidates: list[tuple[int, int, str, Path]] = []
    for pom_path in pom_files:
        pom_data = parse_pom(pom_path)
        relative = pom_path.relative_to(root).as_posix()
        packaging = str(pom_data.get("packaging") or "").strip().lower()
        score = 0
        if packaging != "pom":
            score -= 5
        if relative == "pom.xml":
            score -= 1
        candidates.append((score, len(pom_path.relative_to(root).parts), relative.lower(), pom_path))
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]


def snapshot_directory(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if should_skip_relative_parts(relative_parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {"pom.xml", "settings.xml"}:
            continue
        try:
            snapshot[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return snapshot


def parse_pom(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if not path.is_file():
        return empty_pom_data(raw)
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return empty_pom_data(raw)
    root = tree.getroot()
    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0][1:]

    properties = {}
    properties_node = root.find(tag(namespace, "properties"))
    if properties_node is not None:
        for child in list(properties_node):
            properties[local_name(child.tag)] = (child.text or "").strip()

    parent_node = root.find(tag(namespace, "parent"))
    parent = {
        "group_id": resolve_property(child_text(parent_node, namespace, "groupId"), properties),
        "artifact_id": resolve_property(child_text(parent_node, namespace, "artifactId"), properties),
        "version": resolve_property(child_text(parent_node, namespace, "version"), properties),
    } if parent_node is not None else {"group_id": "", "artifact_id": "", "version": ""}

    dependencies = {}
    dependency_management = {}
    for search_path, target in (
        (".//" + tag(namespace, "dependencies") + "/" + tag(namespace, "dependency"), dependencies),
        (
            ".//" + tag(namespace, "dependencyManagement") + "//" + tag(namespace, "dependency"),
            dependency_management,
        ),
    ):
        for dependency in root.findall(search_path):
            group_id = resolve_property(child_text(dependency, namespace, "groupId"), properties)
            artifact_id = resolve_property(child_text(dependency, namespace, "artifactId"), properties)
            if not group_id or not artifact_id:
                continue
            coordinate = f"{group_id}:{artifact_id}"
            target[coordinate] = {
                "version": resolve_property(child_text(dependency, namespace, "version"), properties),
                "scope": resolve_property(child_text(dependency, namespace, "scope"), properties),
            }

    plugins = {}
    for plugin in root.findall(".//" + tag(namespace, "plugin")):
        group_id = resolve_property(child_text(plugin, namespace, "groupId"), properties) or "org.apache.maven.plugins"
        artifact_id = resolve_property(child_text(plugin, namespace, "artifactId"), properties)
        if not artifact_id:
            continue
        plugins[f"{group_id}:{artifact_id}"] = resolve_property(child_text(plugin, namespace, "version"), properties)

    group_id = resolve_property(child_text(root, namespace, "groupId"), properties) or parent["group_id"]
    artifact_id = resolve_property(child_text(root, namespace, "artifactId"), properties)
    version = resolve_property(child_text(root, namespace, "version"), properties) or parent["version"]
    packaging = resolve_property(child_text(root, namespace, "packaging"), properties) or "jar"
    java_version = (
        properties.get("java.version")
        or properties.get("maven.compiler.release")
        or properties.get("maven.compiler.target")
        or properties.get("maven.compiler.source")
        or ""
    )
    spring_boot_version = properties.get("spring-boot.version", "")
    if not spring_boot_version and parent["group_id"] == "org.springframework.boot":
        spring_boot_version = parent["version"]

    return {
        "path": str(path),
        "raw": raw,
        "coordinates": {"group_id": group_id, "artifact_id": artifact_id, "version": version},
        "packaging": packaging,
        "parent": parent,
        "properties": properties,
        "dependencies": dependencies,
        "dependency_management": dependency_management,
        "plugins": plugins,
        "java_version": java_version,
        "spring_boot_version": spring_boot_version,
    }


def empty_pom_data(raw: str) -> dict[str, Any]:
    return {
        "path": "",
        "raw": raw,
        "coordinates": {"group_id": "", "artifact_id": "", "version": ""},
        "packaging": "",
        "parent": {"group_id": "", "artifact_id": "", "version": ""},
        "properties": {},
        "dependencies": {},
        "dependency_management": {},
        "plugins": {},
        "java_version": "",
        "spring_boot_version": "",
    }


def build_project_summary(
    root: Path,
    primary_pom: Path,
    pom_files: list[Path],
    pom_data: dict[str, Any],
    snapshot: dict[str, str],
) -> dict[str, Any]:
    imports = collect_imports(snapshot)
    return {
        "root_path": str(root),
        "primary_pom": primary_pom.relative_to(root).as_posix(),
        "discovered_poms": [path.relative_to(root).as_posix() for path in pom_files],
        "coordinates": dict(pom_data["coordinates"]),
        "parent": dict(pom_data["parent"]),
        "java_version": pom_data["java_version"],
        "spring_boot_version": pom_data["spring_boot_version"],
        "plugin_versions": dict(pom_data["plugins"]),
        "dependency_coordinates": sorted(pom_data["dependencies"]),
        "dependency_management_coordinates": sorted(pom_data["dependency_management"]),
        "source_file_count": len([path for path in snapshot if path.endswith(".java")]),
        "import_count": len(imports),
    }


def build_pom_delta(legacy_pom: dict[str, Any], reference_pom: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_coordinate_change": {
            "legacy": legacy_pom["coordinates"],
            "reference": reference_pom["coordinates"],
        },
        "java_version_change": {
            "legacy": legacy_pom["java_version"],
            "reference": reference_pom["java_version"],
        },
        "spring_boot_version_change": {
            "legacy": legacy_pom["spring_boot_version"],
            "reference": reference_pom["spring_boot_version"],
        },
        "parent_pom_change": {
            "legacy": legacy_pom["parent"],
            "reference": reference_pom["parent"],
        },
        "maven_plugin_version_changes": compare_string_maps(legacy_pom["plugins"], reference_pom["plugins"]),
        "dependency_management_changes": compare_dependency_maps(
            legacy_pom["dependency_management"],
            reference_pom["dependency_management"],
        ),
    }


def build_dependency_delta(legacy_pom: dict[str, Any], reference_pom: dict[str, Any]) -> dict[str, Any]:
    return compare_dependency_maps(legacy_pom["dependencies"], reference_pom["dependencies"])


def compare_dependency_maps(legacy_map: dict[str, dict[str, str]], reference_map: dict[str, dict[str, str]]) -> dict[str, Any]:
    added = []
    removed = []
    version_changed = []
    for coordinate in sorted(set(legacy_map) | set(reference_map)):
        legacy_item = legacy_map.get(coordinate)
        reference_item = reference_map.get(coordinate)
        if legacy_item is None:
            added.append({"coordinate": coordinate, **reference_item})
            continue
        if reference_item is None:
            removed.append({"coordinate": coordinate, **legacy_item})
            continue
        if legacy_item.get("version") != reference_item.get("version") or legacy_item.get("scope") != reference_item.get("scope"):
            version_changed.append(
                {
                    "coordinate": coordinate,
                    "legacy_version": legacy_item.get("version", ""),
                    "reference_version": reference_item.get("version", ""),
                    "legacy_scope": legacy_item.get("scope", ""),
                    "reference_scope": reference_item.get("scope", ""),
                }
            )
    return {
        "added": added,
        "removed": removed,
        "version_changed": version_changed,
    }


def compare_string_maps(legacy_map: dict[str, str], reference_map: dict[str, str]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for coordinate in sorted(set(legacy_map) | set(reference_map)):
        legacy_value = legacy_map.get(coordinate, "")
        reference_value = reference_map.get(coordinate, "")
        if legacy_value == reference_value:
            continue
        changes.append(
            {
                "coordinate": coordinate,
                "legacy_version": legacy_value,
                "reference_version": reference_value,
            }
        )
    return changes


def build_source_delta(legacy_snapshot: dict[str, str], reference_snapshot: dict[str, str]) -> dict[str, Any]:
    legacy_imports = collect_imports(legacy_snapshot)
    reference_imports = collect_imports(reference_snapshot)
    added_imports = sorted(reference_imports - legacy_imports)
    removed_imports = sorted(legacy_imports - reference_imports)
    changed_families = detect_changed_import_families(legacy_imports, reference_imports)
    javax_to_jakarta = detect_javax_to_jakarta_changes(legacy_imports, reference_imports)
    return {
        "added_imports": added_imports,
        "removed_imports": removed_imports,
        "changed_import_families": changed_families,
        "javax_to_jakarta_imports": javax_to_jakarta,
    }


def collect_imports(snapshot: dict[str, str]) -> set[str]:
    imports: set[str] = set()
    for path, text in snapshot.items():
        if not path.endswith(".java"):
            continue
        imports.update(match.strip() for match in IMPORT_PATTERN.findall(text))
    return imports


def detect_changed_import_families(legacy_imports: set[str], reference_imports: set[str]) -> list[dict[str, Any]]:
    families = [
        "javax.",
        "jakarta.",
        "org.springframework.security.",
        "org.thymeleaf.",
        "io.jsonwebtoken.",
        "org.apache.juneau.",
        "com.microsoft.azure.",
        "com.azure.",
    ]
    changes: list[dict[str, Any]] = []
    for family in families:
        legacy_matches = sorted(item for item in legacy_imports if item.startswith(family))
        reference_matches = sorted(item for item in reference_imports if item.startswith(family))
        if legacy_matches != reference_matches and (legacy_matches or reference_matches):
            changes.append(
                {
                    "family": family,
                    "legacy": legacy_matches,
                    "reference": reference_matches,
                }
            )
    return changes


def detect_javax_to_jakarta_changes(legacy_imports: set[str], reference_imports: set[str]) -> list[dict[str, Any]]:
    mappings = [
        ("javax.validation.", "jakarta.validation."),
        ("javax.xml.bind.", "jakarta.xml.bind."),
        ("javax.servlet.", "jakarta.servlet."),
        ("javax.persistence.", "jakarta.persistence."),
        ("javax.annotation.", "jakarta.annotation."),
    ]
    changes: list[dict[str, Any]] = []
    for legacy_prefix, reference_prefix in mappings:
        legacy_matches = sorted(item for item in legacy_imports if item.startswith(legacy_prefix))
        reference_matches = sorted(item for item in reference_imports if item.startswith(reference_prefix))
        if legacy_matches or reference_matches:
            changes.append(
                {
                    "legacy_prefix": legacy_prefix,
                    "reference_prefix": reference_prefix,
                    "legacy_matches": legacy_matches,
                    "reference_matches": reference_matches,
                }
            )
    return changes


def analyze_runtime_environment(root: Path, snapshot: dict[str, str]) -> dict[str, Any]:
    filesystem_files = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not should_skip_relative_parts(path.relative_to(root).parts)
    ]
    workflow_files = sorted(
        path.relative_to(root).as_posix()
        for path in root.glob(".github/workflows/*")
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )
    config_files = sorted(
        path for path in filesystem_files
        if Path(path).suffix.lower() in {".properties", ".yml", ".yaml"} or Path(path).name in {"settings.xml"}
    )
    indicators = []
    env_vars: set[str] = set()
    resource_usages: set[str] = set()
    keystore_files: list[str] = []
    text = "\n".join(snapshot.values())
    lower_text = text.lower()

    if workflow_files:
        indicators.append("github-workflows")
    if "codeartifact" in lower_text:
        indicators.append("codeartifact")
    if any(token in lower_text for token in ("aws secretsmanager", "aws_secret_access_key", "secretsmanager", "secret-id")):
        indicators.append("aws-secrets")
    if any(token in lower_text for token in ("settings.xml", "maven-settings", "setup-java", "server-id")):
        indicators.append("maven-settings-injection")
    if any(token in text for token in ("JAVA_HOME", "JAVA_HOME_11", "JAVA_HOME_17")) or any(
        token in lower_text for token in ("program files\\java", "/usr/lib/jvm", "jdk-", "/java/")
    ):
        indicators.append("jdk-path-assumptions")
    if any(token in text for token in ("M2_HOME", "MAVEN_HOME")) or "apache-maven" in lower_text or "mvnw" in lower_text:
        indicators.append("maven-path-assumptions")
    if "ResourceLoader" in text:
        resource_usages.add("ResourceLoader")
    if "FileSystemResource" in text:
        resource_usages.add("FileSystemResource")
    if "@Value" in text:
        resource_usages.add("@Value")
    if re.search(r"\bEnvironment\b", text):
        resource_usages.add("Environment")
    if any(token in lower_text for token in ("keystore", "truststore", ".jks", ".p12", ".pem", "certificate")):
        indicators.append("keystore-certificate-usage")

    for path, content in snapshot.items():
        if Path(path).suffix.lower() in CONFIG_SUFFIXES:
            for match in ENV_VAR_PATTERN.findall(content):
                if match.startswith(("JAVA_", "MAVEN_", "AWS_", "SPRING_", "CODEARTIFACT_", "M2_", "CI", "GITHUB_")):
                    env_vars.add(match)
    for path in filesystem_files:
        if Path(path).suffix.lower() in {".jks", ".p12", ".pem", ".crt", ".cer"}:
            keystore_files.append(path)

    return {
        "workflow_files": workflow_files,
        "detected_indicators": sorted(set(indicators)),
        "environment_variables": sorted(env_vars),
        "config_files": config_files,
        "resource_config_usage": sorted(resource_usages),
        "keystore_files": sorted(keystore_files),
        "yaml_or_properties_files": sorted(
            path for path in filesystem_files if Path(path).suffix.lower() in {".properties", ".yml", ".yaml"}
        ),
    }


def detect_api_migration_indicators(
    *,
    legacy_snapshot: dict[str, str],
    reference_snapshot: dict[str, str],
    legacy_pom: dict[str, Any],
    reference_pom: dict[str, Any],
) -> dict[str, Any]:
    return {
        "jjwt_parser_api": detect_source_indicator(
            legacy_snapshot=legacy_snapshot,
            reference_snapshot=reference_snapshot,
            legacy_markers=["Jwts.parser(", ".setSigningKey(", "io.jsonwebtoken.Jwts"],
            reference_markers=["Jwts.parserBuilder(", ".verifyWith(", ".build()", "io.jsonwebtoken.Jwts"],
            dependency_prefixes=["io.jsonwebtoken:"],
            legacy_dependencies=legacy_pom["dependencies"],
            reference_dependencies=reference_pom["dependencies"],
        ),
        "juneau_restclient_api": detect_source_indicator(
            legacy_snapshot=legacy_snapshot,
            reference_snapshot=reference_snapshot,
            legacy_markers=["org.apache.juneau.rest.client.RestClient", "RestClient.create("],
            reference_markers=["org.apache.juneau.rest.client.RestClient", ".rootUrl(", "RestClient.create("],
            dependency_prefixes=["org.apache.juneau:"],
            legacy_dependencies=legacy_pom["dependencies"],
            reference_dependencies=reference_pom["dependencies"],
        ),
        "azure_sdk": detect_source_indicator(
            legacy_snapshot=legacy_snapshot,
            reference_snapshot=reference_snapshot,
            legacy_markers=["com.microsoft.azure", "com.microsoft.azure.servicebus"],
            reference_markers=["com.azure", "com.azure.messaging.servicebus"],
            dependency_prefixes=["com.microsoft.azure:", "com.azure:", "com.azure.spring:"],
            legacy_dependencies=legacy_pom["dependencies"],
            reference_dependencies=reference_pom["dependencies"],
        ),
        "spring_security_5_to_6": detect_source_indicator(
            legacy_snapshot=legacy_snapshot,
            reference_snapshot=reference_snapshot,
            legacy_markers=["WebSecurityConfigurerAdapter", "authorizeRequests(", "antMatchers("],
            reference_markers=["SecurityFilterChain", "authorizeHttpRequests(", "requestMatchers("],
            dependency_prefixes=["org.springframework.security:"],
            legacy_dependencies=legacy_pom["dependencies"],
            reference_dependencies=reference_pom["dependencies"],
        ),
        "thymeleaf_spring_compatibility": {
            "detected": any(
                item.startswith("org.thymeleaf:thymeleaf-spring")
                for item in set(legacy_pom["dependencies"]) | set(reference_pom["dependencies"])
            ),
            "legacy_dependencies": sorted(
                item for item in legacy_pom["dependencies"] if item.startswith("org.thymeleaf:thymeleaf-spring")
            ),
            "reference_dependencies": sorted(
                item for item in reference_pom["dependencies"] if item.startswith("org.thymeleaf:thymeleaf-spring")
            ),
            "evidence_files": [],
        },
    }


def detect_source_indicator(
    *,
    legacy_snapshot: dict[str, str],
    reference_snapshot: dict[str, str],
    legacy_markers: list[str],
    reference_markers: list[str],
    dependency_prefixes: list[str],
    legacy_dependencies: dict[str, dict[str, str]],
    reference_dependencies: dict[str, dict[str, str]],
) -> dict[str, Any]:
    legacy_files = matching_files(legacy_snapshot, legacy_markers)
    reference_files = matching_files(reference_snapshot, reference_markers)
    legacy_deps = sorted(
        coordinate
        for coordinate in legacy_dependencies
        if any(coordinate.startswith(prefix) for prefix in dependency_prefixes)
    )
    reference_deps = sorted(
        coordinate
        for coordinate in reference_dependencies
        if any(coordinate.startswith(prefix) for prefix in dependency_prefixes)
    )
    return {
        "detected": bool(legacy_files or reference_files or legacy_deps or reference_deps),
        "legacy_markers": [marker for marker in legacy_markers if snapshot_contains(legacy_snapshot, marker)],
        "reference_markers": [marker for marker in reference_markers if snapshot_contains(reference_snapshot, marker)],
        "legacy_dependencies": legacy_deps,
        "reference_dependencies": reference_deps,
        "evidence_files": sorted(set(legacy_files + reference_files)),
    }


def matching_files(snapshot: dict[str, str], markers: list[str]) -> list[str]:
    files = []
    for path, text in snapshot.items():
        if any(marker in text for marker in markers):
            files.append(path)
    return files


def snapshot_contains(snapshot: dict[str, str], token: str) -> bool:
    return any(token in text for text in snapshot.values())


def detect_suspicious_artifacts(root: Path, snapshot: dict[str, str]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    pom_like_files = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and not should_skip_relative_parts(path.relative_to(root).parts)
        and (
            path.name.lower() == "pom.xml"
            or ("pom" in path.stem.lower() and path.suffix.lower() == ".xml")
        )
    ]
    pom_like_by_dir: dict[str, list[str]] = {}
    for item in pom_like_files:
        pom_like_by_dir.setdefault(str(Path(item).parent), []).append(item)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or should_skip_relative_parts(path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        lower = path.name.lower()
        if lower.endswith(".bak"):
            findings.append({"type": "backup_file", "path": rel, "reason": ".bak file"})
        elif lower.endswith(".backup"):
            findings.append({"type": "backup_file", "path": rel, "reason": ".backup file"})
        elif lower == "pom copy.xml":
            findings.append({"type": "duplicate_pom", "path": rel, "reason": "pom copy.xml"})
        elif lower.endswith(" copy.java") or "(copy)" in lower or lower.endswith("_copy.java"):
            findings.append({"type": "copied_java_file", "path": rel, "reason": "copied Java source"})
        elif any(token in lower for token in ("tmp", "temp", "migration-old", "old", "backup")) and path.suffix.lower() in {".java", ".xml", ".properties", ".yml", ".yaml"}:
            findings.append({"type": "temporary_migration_remnant", "path": rel, "reason": "temporary migration artifact"})
    for items in pom_like_by_dir.values():
        if len(items) > 1:
            for item in sorted(items):
                findings.append({"type": "duplicate_pom_like_file", "path": item, "reason": "multiple pom-like files in directory"})
    return dedupe_findings(findings)


def recommend_capability_packs(
    *,
    pom_delta: dict[str, Any],
    dependency_delta: dict[str, Any],
    source_delta: dict[str, Any],
    runtime_environment: dict[str, Any],
    api_migration_indicators: dict[str, Any],
    suspicious_artifacts: list[dict[str, str]],
) -> list[str]:
    packs: list[str] = []
    if source_delta["javax_to_jakarta_imports"]:
        packs.append("javax-to-jakarta")
    boot_change = pom_delta["spring_boot_version_change"]
    if boot_change["legacy"] != boot_change["reference"] and (boot_change["legacy"] or boot_change["reference"]):
        packs.append("spring-boot-2-to-3")
    if api_migration_indicators["spring_security_5_to_6"]["detected"]:
        packs.append("spring-security-5-to-6")
    if api_migration_indicators["jjwt_parser_api"]["detected"]:
        packs.append("jjwt-modernization")
    if api_migration_indicators["juneau_restclient_api"]["detected"]:
        packs.append("juneau-modernization")
    if runtime_environment["detected_indicators"] or runtime_environment["resource_config_usage"]:
        packs.append("runtime-environment-contract")
    if pom_delta["maven_plugin_version_changes"] or "maven-path-assumptions" in runtime_environment["detected_indicators"]:
        packs.append("maven-build-environment")
    if dependency_delta["added"] or dependency_delta["removed"] or dependency_delta["version_changed"]:
        packs.append("internal-dependency-graph")
    if any("test" in item["path"].lower() for item in suspicious_artifacts):
        packs.append("test-modernization")
    return sorted(set(packs))


def dedupe_findings(findings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, str]] = []
    for item in findings:
        key = (item["type"], item["path"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def should_skip_relative_parts(parts: tuple[str, ...]) -> bool:
    return any(part in SKIP_DIR_NAMES for part in parts)


def tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def child_text(element: ET.Element | None, namespace: str, name: str) -> str:
    if element is None:
        return ""
    child = element.find(tag(namespace, name))
    return (child.text or "").strip() if child is not None and child.text else ""


def local_name(tag_name: str) -> str:
    return tag_name.split("}", 1)[-1]


def resolve_property(value: str, properties: dict[str, str]) -> str:
    text = (value or "").strip()
    if text.startswith("${") and text.endswith("}"):
        return properties.get(text[2:-1], text)
    return text


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.tools.reference_delta_analyzer",
        description="Compare legacy and migrated reference Java/Maven projects and write migration delta report.",
    )
    parser.add_argument("--legacy", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def _render_cli_summary(payload: dict[str, Any]) -> str:
    java_change = payload["pom_delta"]["java_version_change"]
    boot_change = payload["pom_delta"]["spring_boot_version_change"]
    return "\n".join(
        [
            "Reference delta report written.",
            f"legacy_pom={payload['legacy']['primary_pom']} reference_pom={payload['reference']['primary_pom']}",
            f"java={java_change['legacy']} -> {java_change['reference']}",
            f"spring_boot={boot_change['legacy']} -> {boot_change['reference']}",
            "capability_packs=" + ",".join(payload["recommended_capability_packs"]),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
