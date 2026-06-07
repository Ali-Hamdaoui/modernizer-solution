from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from migration_factory.tools.reference_delta_analyzer import (
    discover_pom_files,
    parse_pom,
    select_primary_pom,
    should_skip_relative_parts,
    snapshot_directory,
)


SCHEMA_VERSION = "1.0.0"
CONFIG_SUFFIXES = {".properties", ".yml", ".yaml", ".json"}
SECURITY_SUFFIXES = {".jks", ".p12", ".pem", ".crt", ".cer", ".key"}
JAVA_SOURCE_SUFFIXES = {".java", ".kt", ".groovy"}
ENV_VAR_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
WORKFLOW_JAVA_VERSION_PATTERN = re.compile(r"java-version\s*:\s*[\"']?([^\"'\n#]+)")
WORKFLOW_JAVA_DISTRIBUTION_PATTERN = re.compile(r"distribution\s*:\s*[\"']?([^\"'\n#]+)")
WORKFLOW_MAVEN_VERSION_PATTERN = re.compile(r"maven-version\s*:\s*[\"']?([^\"'\n#]+)")
PATH_PATTERN = re.compile(r"([A-Za-z]:\\[^\s\"']+|/(usr|opt|Library)/[^\s\"']+)")
MAVEN_SETTINGS_FLAG_PATTERN = re.compile(r"\bmvn(?:w)?\b[^\n]*\s(?:-s|--settings)\s+([^\s\"']+)")
REPOSITORY_URL_PATTERN = re.compile(r"<url>\s*([^<]+)\s*</url>")
RESOURCE_REF_PATTERN = re.compile(
    r"(@Value\s*\(|\bEnvironment\b|\bResourceLoader\b|\bFileSystemResource\b|\bClassPathResource\b|\bPaths\.get\s*\(|\bFileInputStream\s*\(|new\s+File\s*\()"
)
ACTIVE_PROFILE_PATTERN = re.compile(r"@ActiveProfiles\s*\(([^)]*)\)")

PRIVATE_REGISTRY_HINTS = (
    "codeartifact",
    "artifactregistry",
    "packages.",
    "maven.pkg",
    "nexus",
    "artifactory",
)
PRIVATE_REGISTRY_ENV_HINTS = (
    "TOKEN",
    "PASSWORD",
    "PASS",
    "USERNAME",
    "USER",
    "SECRET",
    "CODEARTIFACT",
    "MAVEN",
    "REGISTRY",
)
COMMON_PUBLIC_GROUP_PREFIXES = (
    "org.springframework",
    "org.apache",
    "org.junit",
    "org.mockito",
    "org.slf4j",
    "org.hamcrest",
    "org.thymeleaf",
    "com.fasterxml",
    "com.google",
    "com.azure",
    "io.jsonwebtoken",
    "io.micrometer",
    "jakarta",
    "javax",
    "ch.qos",
    "commons-",
    "org.testcontainers",
    "software.amazon",
)


@dataclass(frozen=True)
class RuntimeContractAnalysisResult:
    project_root: Path
    output_path: Path
    payload: dict[str, Any]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = analyze_runtime_contract(
            project_path=args.project,
            output_path=args.output,
            reference_delta_path=args.reference_delta,
        )
    except ValueError as exc:
        print(str(exc))
        return 2

    print(_render_cli_summary(result.payload))
    return 0


def analyze_runtime_contract(
    *,
    project_path: str | Path,
    output_path: str | Path,
    reference_delta_path: str | Path | None = None,
) -> RuntimeContractAnalysisResult:
    project_root = Path(project_path).expanduser().resolve()
    resolved_output = Path(output_path).expanduser().resolve()
    reference_delta_file = Path(reference_delta_path).expanduser().resolve() if reference_delta_path else None

    if not project_root.exists():
        raise ValueError(f"Project path does not exist: {project_root}")
    if reference_delta_file is not None and not reference_delta_file.exists():
        raise ValueError(f"Reference delta path does not exist: {reference_delta_file}")

    pom_files = discover_pom_files(project_root)
    if not pom_files:
        raise ValueError(f"No pom.xml found under project path: {project_root}")

    primary_pom = select_primary_pom(project_root, pom_files)
    pom_data = parse_pom(primary_pom)
    snapshot = snapshot_directory(project_root)
    reference_delta = _load_reference_delta(reference_delta_file)

    project_summary = _build_project_summary(project_root, primary_pom, pom_files, pom_data)
    build_tool = {
        "type": "maven",
        "wrapper_present": any((project_root / name).is_file() for name in ("mvnw", "mvnw.cmd")),
    }
    workflow_indicators = _collect_workflow_indicators(snapshot)
    env_vars = _collect_environment_variables(snapshot)
    jdk_requirements = _build_jdk_requirements(pom_data, workflow_indicators, env_vars)
    maven_requirements = _build_maven_requirements(project_root, pom_data, snapshot, workflow_indicators)
    private_registry_requirements = _build_private_registry_requirements(pom_data, snapshot, env_vars, workflow_indicators)
    configuration_files = _collect_configuration_files(project_root)
    resource_access = _collect_resource_access(snapshot)
    security_materials = _collect_security_materials(project_root, snapshot)
    internal_dependencies = _collect_internal_dependencies(pom_data, reference_delta)
    test_runtime_requirements = _collect_test_runtime_requirements(project_root, snapshot)
    detected_risks = _build_detected_risks(
        jdk_requirements=jdk_requirements,
        maven_requirements=maven_requirements,
        private_registry_requirements=private_registry_requirements,
        configuration_files=configuration_files,
        security_materials=security_materials,
        internal_dependencies=internal_dependencies,
        workflow_indicators=workflow_indicators,
        test_runtime_requirements=test_runtime_requirements,
        reference_delta=reference_delta,
    )
    recommended_actions = _build_recommended_actions(detected_risks, reference_delta)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "project": project_summary,
        "build_tool": build_tool,
        "jdk_requirements": jdk_requirements,
        "maven_requirements": maven_requirements,
        "private_registry_requirements": private_registry_requirements,
        "environment_variables": env_vars,
        "configuration_files": configuration_files,
        "resource_access": resource_access,
        "security_materials": security_materials,
        "internal_dependencies": internal_dependencies,
        "workflow_indicators": workflow_indicators,
        "test_runtime_requirements": test_runtime_requirements,
        "detected_risks": detected_risks,
        "recommended_actions": recommended_actions,
    }

    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return RuntimeContractAnalysisResult(project_root=project_root, output_path=resolved_output, payload=payload)


def _load_reference_delta(reference_delta_path: Path | None) -> dict[str, Any]:
    if reference_delta_path is None:
        return {}
    try:
        payload = json.loads(reference_delta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_project_summary(
    root: Path,
    primary_pom: Path,
    pom_files: list[Path],
    pom_data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "root_label": root.name.lower(),
        "root_basename": root.name,
        "input_name": root.name,
        "primary_pom": primary_pom.relative_to(root).as_posix(),
        "discovered_poms": [path.relative_to(root).as_posix() for path in pom_files],
        "coordinates": dict(pom_data["coordinates"]),
    }


def _collect_workflow_indicators(snapshot: dict[str, str]) -> list[dict[str, Any]]:
    indicators: list[dict[str, Any]] = []
    for relative_path, content in sorted(snapshot.items()):
        if not relative_path.startswith(".github/workflows/"):
            continue
        found_indicators: set[str] = set()
        hardcoded_paths = _extract_hardcoded_path_evidence(relative_path, content)
        if "actions/setup-java" in content:
            found_indicators.add("setup-java")
        if "codeartifact" in content.lower():
            found_indicators.add("codeartifact")
        if "settings.xml" in content or "--settings" in content or " -s " in content:
            found_indicators.add("maven-settings")
        if hardcoded_paths:
            found_indicators.add("hardcoded-tool-path")
        indicators.append(
            {
                "path": relative_path,
                "indicators": sorted(found_indicators),
                "setup_java_versions": sorted(
                    {match.strip() for match in WORKFLOW_JAVA_VERSION_PATTERN.findall(content) if match.strip()}
                ),
                "setup_java_distributions": sorted(
                    {match.strip() for match in WORKFLOW_JAVA_DISTRIBUTION_PATTERN.findall(content) if match.strip()}
                ),
                "maven_versions": sorted({match.strip() for match in WORKFLOW_MAVEN_VERSION_PATTERN.findall(content)}),
                "environment_variables": sorted(_extract_env_var_names(content)),
                "hardcoded_tool_paths": hardcoded_paths,
            }
        )
    return indicators


def _collect_environment_variables(snapshot: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for relative_path, content in sorted(snapshot.items()):
        for name in _extract_env_var_names(content):
            key = (name, relative_path)
            if key in seen:
                continue
            seen.add(key)
            items.append({"name": name, "evidence_path": relative_path})
    return items


def _build_jdk_requirements(
    pom_data: dict[str, Any],
    workflow_indicators: list[dict[str, Any]],
    env_vars: list[dict[str, str]],
) -> dict[str, Any]:
    properties = pom_data.get("properties", {})
    hardcoded_paths = [
        entry
        for entry in _collect_hardcoded_path_evidence(workflow_indicators)
        if entry["kind"] == "jdk"
    ]
    return {
        "java_version": pom_data.get("java_version") or "",
        "compiler_source": properties.get("maven.compiler.source", ""),
        "compiler_target": properties.get("maven.compiler.target", ""),
        "compiler_release": properties.get("maven.compiler.release", ""),
        "workflow_setup_java_versions": sorted(
            {version for workflow in workflow_indicators for version in workflow.get("setup_java_versions", []) if version}
        ),
        "workflow_setup_java_distributions": sorted(
            {value for workflow in workflow_indicators for value in workflow.get("setup_java_distributions", []) if value}
        ),
        "hardcoded_jdk_paths": hardcoded_paths,
        "environment_variables": sorted(
            {
                item["name"]
                for item in env_vars
                if item["name"].startswith("JAVA_HOME") or item["name"] in {"JDK_HOME", "JAVA_VERSION"}
            }
        ),
    }


def _build_maven_requirements(
    project_root: Path,
    pom_data: dict[str, Any],
    snapshot: dict[str, str],
    workflow_indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    settings_files = sorted(
        {
            relative_path
            for relative_path in snapshot
            if Path(relative_path).name == "settings.xml"
        }
    )
    settings_evidence: list[dict[str, str]] = []
    hardcoded_maven_paths: list[dict[str, str]] = []
    for relative_path, content in sorted(snapshot.items()):
        for match in MAVEN_SETTINGS_FLAG_PATTERN.findall(content):
            settings_evidence.append({"path": relative_path, "settings_arg": match})
    seen_hardcoded: set[tuple[str, str, str]] = set()
    for entry in _collect_hardcoded_path_evidence(workflow_indicators):
        if entry["kind"] != "maven":
            continue
        key = (entry["path"], entry["match"], entry["kind"])
        if key in seen_hardcoded:
            continue
        seen_hardcoded.add(key)
        hardcoded_maven_paths.append(entry)
    return {
        "wrapper_present": any((project_root / name).is_file() for name in ("mvnw", "mvnw.cmd")),
        "plugin_versions": dict(pom_data.get("plugins", {})),
        "settings_files": settings_files,
        "settings_flag_evidence": settings_evidence,
        "workflow_maven_versions": sorted(
            {version for workflow in workflow_indicators for version in workflow.get("maven_versions", []) if version}
        ),
        "hardcoded_maven_paths": hardcoded_maven_paths,
    }


def _build_private_registry_requirements(
    pom_data: dict[str, Any],
    snapshot: dict[str, str],
    env_vars: list[dict[str, str]],
    workflow_indicators: list[dict[str, Any]],
) -> dict[str, Any]:
    repository_urls = sorted(
        {
            url.strip()
            for url in REPOSITORY_URL_PATTERN.findall(pom_data.get("raw", ""))
            if _looks_private_registry_url(url)
        }
    )
    detected_indicators: set[str] = set()
    evidence: list[dict[str, str]] = []
    for relative_path, content in sorted(snapshot.items()):
        lowered = content.lower()
        if any(hint in lowered for hint in PRIVATE_REGISTRY_HINTS):
            detected_indicators.add("private-registry")
            evidence.append({"path": relative_path, "type": "private_registry_hint"})
        for match in MAVEN_SETTINGS_FLAG_PATTERN.findall(content):
            detected_indicators.add("maven-settings")
            evidence.append({"path": relative_path, "type": "settings_flag", "settings_arg": match})
        if "settings.xml" in lowered:
            detected_indicators.add("maven-settings")
    if repository_urls:
        detected_indicators.add("private-registry")
    if any("codeartifact" in indicator for workflow in workflow_indicators for indicator in workflow.get("indicators", [])):
        detected_indicators.add("codeartifact")
    env_names = sorted(
        {
            item["name"]
            for item in env_vars
            if any(hint in item["name"] for hint in PRIVATE_REGISTRY_ENV_HINTS)
        }
    )
    return {
        "detected_indicators": sorted(detected_indicators),
        "repository_urls": repository_urls,
        "environment_variables": env_names,
        "evidence": evidence,
    }


def _collect_configuration_files(project_root: Path) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(project_root).parts
        if should_skip_relative_parts(relative_parts):
            continue
        if path.suffix.lower() not in CONFIG_SUFFIXES:
            continue
        relative = path.relative_to(project_root).as_posix()
        if relative.startswith("src/main/resources/"):
            location = "main-resources"
        elif relative.startswith("src/test/resources/"):
            location = "test-resources"
        elif "/config/" in f"/{relative}/" or relative.startswith("config/"):
            location = "config-dir"
        else:
            location = "project-root"
        items.append({"path": relative, "location": location})
    return items


def _collect_resource_access(snapshot: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for relative_path, content in sorted(snapshot.items()):
        if Path(relative_path).suffix.lower() not in JAVA_SOURCE_SUFFIXES:
            continue
        for raw_match in RESOURCE_REF_PATTERN.findall(content):
            detection = _normalize_resource_detection(raw_match)
            key = (detection, relative_path)
            if key in seen:
                continue
            seen.add(key)
            items.append({"type": detection, "path": relative_path})
    return items


def _collect_security_materials(project_root: Path, snapshot: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(project_root).parts
        if should_skip_relative_parts(relative_parts):
            continue
        relative = path.relative_to(project_root).as_posix()
        lowered_name = path.name.lower()
        if path.suffix.lower() in SECURITY_SUFFIXES or "keystore" in lowered_name or "truststore" in lowered_name:
            detection = "file"
            key = (detection, relative)
            if key not in seen:
                seen.add(key)
                items.append({"type": detection, "path": relative})
    for relative_path, content in sorted(snapshot.items()):
        lowered = content.lower()
        if any(token in lowered for token in ("keystore", "truststore", ".jks", ".p12", ".pem", ".crt", ".cer", ".key")):
            key = ("reference", relative_path)
            if key not in seen:
                seen.add(key)
                items.append({"type": "reference", "path": relative_path})
    return items


def _collect_internal_dependencies(pom_data: dict[str, Any], reference_delta: dict[str, Any]) -> list[dict[str, str]]:
    project_group = str(pom_data.get("coordinates", {}).get("group_id") or "")
    project_prefix = ".".join(project_group.split(".")[:2]) if "." in project_group else project_group
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for coordinate, metadata in sorted(pom_data.get("dependencies", {}).items()):
        group_id, artifact_id = coordinate.split(":", 1)
        version = str(metadata.get("version") or "")
        reasons: list[str] = []
        if project_prefix and group_id.startswith(project_prefix):
            reasons.append("same_group_prefix")
        if version.endswith("SNAPSHOT"):
            reasons.append("snapshot_version")
        if _looks_non_public_group(group_id):
            reasons.append("non_public_group")
        if coordinate in _reference_delta_internal_coordinates(reference_delta):
            reasons.append("reference_delta_context")
        if not reasons:
            continue
        if coordinate in seen:
            continue
        seen.add(coordinate)
        items.append(
            {
                "coordinate": coordinate,
                "version": version,
                "reason": ",".join(sorted(set(reasons))),
                "artifact_id": artifact_id,
            }
        )
    return items


def _collect_test_runtime_requirements(project_root: Path, snapshot: dict[str, str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(project_root).parts
        if should_skip_relative_parts(relative_parts):
            continue
        relative = path.relative_to(project_root).as_posix()
        if relative.startswith("src/test/resources/") and path.suffix.lower() in CONFIG_SUFFIXES:
            key = ("test-resource-config", relative)
            if key not in seen:
                seen.add(key)
                items.append({"type": "test-resource-config", "path": relative})
    for relative_path, content in sorted(snapshot.items()):
        normalized_path = relative_path.replace("\\", "/")
        if not (normalized_path.startswith("src/test/") or "/src/test/" in normalized_path):
            continue
        for marker, detection in (
            ("org.junit.Test", "junit4"),
            ("org.junit.jupiter", "junit5"),
            ("org.mockito", "mockito"),
            ("org.powermock", "powermock"),
            ("@SpringBootTest", "spring-boot-test"),
        ):
            if marker in content:
                key = (detection, relative_path)
                if key not in seen:
                    seen.add(key)
                    items.append({"type": detection, "path": relative_path})
        for match in ACTIVE_PROFILE_PATTERN.findall(content):
            key = ("active-profiles", relative_path)
            if key not in seen:
                seen.add(key)
                items.append({"type": "active-profiles", "path": relative_path, "value": match.strip()})
    return items


def _build_detected_risks(
    *,
    jdk_requirements: dict[str, Any],
    maven_requirements: dict[str, Any],
    private_registry_requirements: dict[str, Any],
    configuration_files: list[dict[str, str]],
    security_materials: list[dict[str, str]],
    internal_dependencies: list[dict[str, str]],
    workflow_indicators: list[dict[str, Any]],
    test_runtime_requirements: list[dict[str, str]],
    reference_delta: dict[str, Any],
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    if private_registry_requirements["repository_urls"] or "maven-settings" in private_registry_requirements["detected_indicators"]:
        risks.append({"code": "MISSING_PRIVATE_MAVEN_SETTINGS", "evidence": private_registry_requirements["evidence"][:3]})
    if "private-registry" in private_registry_requirements["detected_indicators"] or "codeartifact" in private_registry_requirements["detected_indicators"]:
        risks.append(
            {
                "code": "PRIVATE_REGISTRY_AUTH_REQUIRED",
                "evidence": private_registry_requirements["environment_variables"][:5],
            }
        )
    workflow_versions = set(jdk_requirements.get("workflow_setup_java_versions", []))
    if jdk_requirements.get("java_version") and workflow_versions and jdk_requirements["java_version"] not in workflow_versions:
        risks.append(
            {
                "code": "JDK_VERSION_MISMATCH_RISK",
                "evidence": {
                    "pom_java_version": jdk_requirements["java_version"],
                    "workflow_java_versions": sorted(workflow_versions),
                },
            }
        )
    if internal_dependencies:
        risks.append({"code": "INTERNAL_DEPENDENCY_BUILD_ORDER_REQUIRED", "evidence": internal_dependencies[:5]})
    if configuration_files:
        risks.append({"code": "RESOURCE_FILES_REQUIRED", "evidence": configuration_files[:5]})
    if security_materials:
        risks.append({"code": "SECURITY_MATERIALS_REQUIRED", "evidence": security_materials[:5]})
    if test_runtime_requirements:
        risks.append({"code": "TEST_RUNTIME_CONFIG_REQUIRED", "evidence": test_runtime_requirements[:5]})
    if workflow_indicators:
        risks.append({"code": "WORKFLOW_ONLY_ENVIRONMENT_RISK", "evidence": workflow_indicators[:3]})
    runtime_indicators = reference_delta.get("runtime_environment", {}).get("detected_indicators", [])
    if runtime_indicators:
        risks.append({"code": "REFERENCE_DELTA_RUNTIME_CONTEXT_PRESENT", "evidence": runtime_indicators[:5]})
    if maven_requirements.get("hardcoded_maven_paths") or jdk_requirements.get("hardcoded_jdk_paths"):
        risks.append(
            {
                "code": "TOOLCHAIN_PATH_ASSUMPTION_RISK",
                "evidence": {
                    "jdk_paths": jdk_requirements.get("hardcoded_jdk_paths", []),
                    "maven_paths": maven_requirements.get("hardcoded_maven_paths", []),
                },
            }
        )
    return risks


def _build_recommended_actions(detected_risks: list[dict[str, Any]], reference_delta: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(code: str, summary: str) -> None:
        if code in seen:
            return
        seen.add(code)
        actions.append({"code": code, "summary": summary})

    risk_codes = {item["code"] for item in detected_risks}
    if "INTERNAL_DEPENDENCY_BUILD_ORDER_REQUIRED" in risk_codes:
        add("BUILD_INTERNAL_DEPENDENCIES_FIRST", "Build and install likely internal dependencies before migration build/test.")
    if "MISSING_PRIVATE_MAVEN_SETTINGS" in risk_codes or "PRIVATE_REGISTRY_AUTH_REQUIRED" in risk_codes:
        add("PROVIDE_MAVEN_SETTINGS", "Provide Maven settings and private registry credentials through safe environment injection.")
    if "JDK_VERSION_MISMATCH_RISK" in risk_codes or "TOOLCHAIN_PATH_ASSUMPTION_RISK" in risk_codes:
        add("SET_REQUIRED_JDK_ENV_VARS", "Set required JDK and Maven environment variables to match project and workflow assumptions.")
    if "RESOURCE_FILES_REQUIRED" in risk_codes:
        add("COPY_REQUIRED_CONFIG_FILES", "Copy required config/resource files into sandbox before running build or tests.")
    if "TEST_RUNTIME_CONFIG_REQUIRED" in risk_codes:
        add("PROVIDE_TEST_RUNTIME_CONFIG", "Provide test profiles, mock config, and test resources before verification.")
    if "SECURITY_MATERIALS_REQUIRED" in risk_codes:
        add("PROVIDE_SECURITY_MATERIALS", "Mount required certificates, keystores, or truststores by relative path without exposing secrets.")
    if "WORKFLOW_ONLY_ENVIRONMENT_RISK" in risk_codes or "REFERENCE_DELTA_RUNTIME_CONTEXT_PRESENT" in risk_codes:
        add("REVIEW_WORKFLOW_ENVIRONMENT", "Review workflow-only environment steps and reproduce required settings in local sandbox.")
    capability_packs = reference_delta.get("recommended_capability_packs", [])
    if capability_packs:
        add("REVIEW_REFERENCE_DELTA_CAPABILITY_PACKS", f"Review reference delta capability packs: {', '.join(sorted(capability_packs)[:6])}.")
    add("AVOID_COMMITTING_SECRETS", "Capture variable names and file paths only; never commit secret values or key contents.")
    return actions


def _collect_hardcoded_path_evidence(workflow_indicators: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for workflow in workflow_indicators:
        for item in workflow.get("hardcoded_tool_paths", []):
            evidence.append(dict(item))
    return evidence


def _extract_hardcoded_path_evidence(relative_path: str, content: str) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_match in PATH_PATTERN.findall(content):
        candidate = raw_match[0].strip()
        lowered = candidate.lower()
        kind = "generic-tool"
        if "jdk" in lowered or re.search(r"java[-_/\\]?\d+", lowered):
            kind = "jdk"
        elif "maven" in lowered or lowered.endswith("/mvn") or lowered.endswith("\\mvn") or "\\mvn" in lowered or "/mvn" in lowered:
            kind = "maven"
        key = (relative_path, candidate, kind)
        if key in seen:
            continue
        seen.add(key)
        evidence.append({"path": relative_path, "match": candidate, "kind": kind})
    return evidence


def _extract_env_var_names(content: str) -> list[str]:
    names = set(ENV_VAR_PATTERN.findall(content))
    return sorted(name for name in names if name not in {"XML", "HTTP", "HTTPS", "JSON", "PATHS"})


def _looks_private_registry_url(url: str) -> bool:
    lowered = url.strip().lower()
    return any(hint in lowered for hint in PRIVATE_REGISTRY_HINTS) or "amazonaws.com" in lowered


def _normalize_resource_detection(raw: str) -> str:
    lowered = raw.lower().replace(" ", "")
    if lowered.startswith("@value"):
        return "@Value"
    if lowered == "environment":
        return "Environment"
    if lowered == "resourceloader":
        return "ResourceLoader"
    if lowered == "filesystemresource":
        return "FileSystemResource"
    if lowered == "classpathresource":
        return "ClassPathResource"
    if lowered.startswith("paths.get"):
        return "Paths.get"
    if lowered.startswith("fileinputstream"):
        return "FileInputStream"
    return "new File"


def _looks_non_public_group(group_id: str) -> bool:
    return not any(group_id.startswith(prefix) for prefix in COMMON_PUBLIC_GROUP_PREFIXES)


def _reference_delta_internal_coordinates(reference_delta: dict[str, Any]) -> set[str]:
    coordinates = set()
    for item in reference_delta.get("dependency_delta", {}).get("added", []):
        coordinate = item.get("coordinate")
        if isinstance(coordinate, str) and coordinate:
            coordinates.add(coordinate)
    for item in reference_delta.get("dependency_delta", {}).get("version_changed", []):
        coordinate = item.get("coordinate")
        if isinstance(coordinate, str) and coordinate:
            coordinates.add(coordinate)
    return coordinates


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.tools.runtime_contract_analyzer",
        description="Generate deterministic runtime environment contract for Java/Maven project.",
    )
    parser.add_argument("--project", required=True, help="Path to project root.")
    parser.add_argument("--output", required=True, help="Path to runtime contract JSON output.")
    parser.add_argument(
        "--reference-delta",
        help="Optional reference delta report JSON from migration_factory.tools.reference_delta_analyzer.",
    )
    return parser.parse_args(argv)


def _render_cli_summary(payload: dict[str, Any]) -> str:
    project_name = payload.get("project", {}).get("root_basename", "project")
    java_version = payload.get("jdk_requirements", {}).get("java_version") or "unknown"
    risk_count = len(payload.get("detected_risks", []))
    env_count = len(payload.get("environment_variables", []))
    return (
        "Runtime contract report written. "
        f"project={project_name} java={java_version} risks={risk_count} env_vars={env_count}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
