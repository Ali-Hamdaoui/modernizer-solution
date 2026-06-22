from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re
import xml.etree.ElementTree as ET

from .pom_patches import collect_jjwt_parser_compatibility_candidates


POWERMOCK_GROUP_PREFIX = "org.powermock"
AZURE_OLD_GROUP_PREFIXES = (
    "com.microsoft.azure",
    "com.microsoft.rest",
    "com.microsoft.windowsazure",
)
AZURE_NEW_GROUP_PREFIXES = ("com.azure",)
AZURE_USAGE_MARKERS: tuple[tuple[str, str], ...] = (
    ("AZURE_OLD_IMPORT", "import com.microsoft.azure"),
    ("AZURE_OLD_IMPORT", "import com.microsoft.rest"),
    ("AZURE_OLD_IMPORT", "import com.microsoft.windowsazure"),
    ("AZURE_NEW_IMPORT", "import com.azure"),
    ("SERVICE_BUS_USAGE", "ServiceBus"),
    ("SERVICE_BUS_USAGE", "QueueClient"),
    ("SERVICE_BUS_USAGE", "TopicClient"),
    ("BLOB_STORAGE_USAGE", "Blob"),
    ("BLOB_STORAGE_USAGE", "CloudBlob"),
    ("IDENTITY_AUTH_USAGE", "TokenCredential"),
    ("IDENTITY_AUTH_USAGE", "DefaultAzureCredential"),
)
POWERMOCK_USAGE_MARKERS: tuple[tuple[str, str], ...] = (
    ("POWERMOCK_RUNNER", "@RunWith(PowerMockRunner.class)"),
    ("POWERMOCK_PREPARE_FOR_TEST", "@PrepareForTest"),
    ("POWERMOCK_API", "PowerMockito"),
    ("POWERMOCK_STATIC_MOCKING", "mockStatic"),
    ("POWERMOCK_CONSTRUCTOR_MOCKING", "whenNew"),
    ("POWERMOCK_SUPPRESS", "suppress"),
    ("POWERMOCK_WHITEBOX", "Whitebox"),
)
JAKARTA_NAMESPACE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("javax.validation", re.compile(r"\bjavax\.validation(?:\.[A-Za-z0-9_.*]+)?")),
    ("javax.xml.bind", re.compile(r"\bjavax\.xml\.bind(?:\.[A-Za-z0-9_.*]+)?")),
    ("javax.servlet", re.compile(r"\bjavax\.servlet(?:\.[A-Za-z0-9_.*]+)?")),
    ("javax.annotation", re.compile(r"\bjavax\.annotation(?:\.[A-Za-z0-9_.*]+)?")),
    ("javax.persistence", re.compile(r"\bjavax\.persistence(?:\.[A-Za-z0-9_.*]+)?")),
    ("javax.ws.rs", re.compile(r"\bjavax\.ws\.rs(?:\.[A-Za-z0-9_.*]+)?")),
)
GENERIC_JAVAX_PATTERN = re.compile(r"\b(javax\.[A-Za-z0-9_.]+)")


@dataclass(frozen=True)
class PowerMockReviewResult:
    artifact_path: Path
    detected: bool
    dependencies: list[str]
    usage_files: list[str]
    usage_patterns: list[str]
    risk_level: str
    recommended_next_actions: list[str]
    human_review_required: bool


@dataclass(frozen=True)
class JakartaHybridStrategyResult:
    artifact_path: Path
    detected: bool
    detected_namespaces: list[str]
    human_review_required: bool
    consumer_compatibility_warning: bool
    warnings: list[str]


@dataclass(frozen=True)
class AzureSdkMigrationReviewResult:
    artifact_path: Path
    detected: bool
    migration_mode: str
    old_azure_dependencies: list[str]
    new_azure_dependencies: list[str]
    source_usage_files: list[str]
    usage_patterns: list[str]
    risk_level: str
    human_review_required: bool
    warnings: list[str]


@dataclass(frozen=True)
class JjwtApiMigrationReviewResult:
    artifact_path: Path
    detected: bool
    source_usage_files: list[str]
    usage_patterns: list[str]
    human_review_required: bool
    warnings: list[str]


def review_powermock_legacy_test_strategy(
    project_path: Path,
    *,
    unit_id: str,
    run_id: str | None = None,
) -> PowerMockReviewResult:
    project_path = Path(project_path).expanduser().resolve()
    dependencies = _detect_powermock_dependencies(project_path / "pom.xml")
    file_findings = _detect_powermock_usage(project_path)
    usage_files = [item["file"] for item in file_findings]
    usage_patterns = sorted({pattern for item in file_findings for pattern in item["patterns"]})
    detected = bool(dependencies or usage_files)
    recommended_next_actions = _recommended_actions(dependencies, usage_patterns)
    payload = {
        "run_id": run_id or "",
        "unit_id": unit_id,
        "detected": detected,
        "dependencies": dependencies,
        "usage_files": usage_files,
        "usage_patterns": usage_patterns,
        "file_findings": file_findings,
        "risk_level": "HIGH" if detected else "NONE",
        "gate_id": "POWERMOCK_LEGACY_TEST_STRATEGY",
        "safe_to_auto_apply": False,
        "requires_human_approval": detected,
        "human_review_required": detected,
        "recommended_next_actions": recommended_next_actions,
    }
    artifact_path = project_path / ".migration" / "review" / "powermock_review.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return PowerMockReviewResult(
        artifact_path=artifact_path,
        detected=detected,
        dependencies=dependencies,
        usage_files=usage_files,
        usage_patterns=usage_patterns,
        risk_level=str(payload["risk_level"]),
        recommended_next_actions=recommended_next_actions,
        human_review_required=detected,
    )


def review_jakarta_hybrid_strategy(
    project_path: Path,
    *,
    unit_id: str,
    run_id: str | None = None,
) -> JakartaHybridStrategyResult:
    project_path = Path(project_path).expanduser().resolve()
    file_findings = _detect_jakarta_usage(project_path)
    namespace_summary = _summarize_jakarta_namespaces(file_findings)
    detected_namespaces = sorted(namespace_summary.keys())
    detected = bool(detected_namespaces)
    consumer_warning = any(item.get("consumer_compatibility_warning") for item in namespace_summary.values())
    human_review_required = any(bool(item.get("requires_human_approval")) for item in namespace_summary.values())
    warnings = _jakarta_warnings(namespace_summary)
    payload = {
        "run_id": run_id or "",
        "unit_id": unit_id,
        "detected": detected,
        "detected_namespaces": detected_namespaces,
        "namespaces": namespace_summary,
        "risk_level": "HIGH" if human_review_required else ("INFO" if detected else "NONE"),
        "gate_id": "JAKARTA_HYBRID_STRATEGY",
        "human_review_required": human_review_required,
        "consumer_compatibility_warning": consumer_warning,
        "warnings": warnings,
    }
    artifact_path = project_path / ".migration" / "review" / "jakarta_hybrid_strategy.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return JakartaHybridStrategyResult(
        artifact_path=artifact_path,
        detected=detected,
        detected_namespaces=detected_namespaces,
        human_review_required=human_review_required,
        consumer_compatibility_warning=consumer_warning,
        warnings=warnings,
    )


def review_azure_sdk_migration_playbook(
    project_path: Path,
    *,
    unit_id: str,
    run_id: str | None = None,
) -> AzureSdkMigrationReviewResult:
    project_path = Path(project_path).expanduser().resolve()
    old_dependencies, new_dependencies = _detect_azure_dependencies(project_path / "pom.xml")
    file_findings = _detect_azure_usage(project_path)
    source_usage_files = [item["file"] for item in file_findings]
    usage_patterns = sorted({pattern for item in file_findings for pattern in item["patterns"]})
    migration_mode = _azure_migration_mode(old_dependencies, new_dependencies)
    detected = migration_mode != "NOT_DETECTED" or bool(source_usage_files)
    warnings = _azure_warnings(migration_mode)
    payload = {
        "run_id": run_id or "",
        "unit_id": unit_id,
        "detected": detected,
        "gate_id": "AZURE_SDK_MIGRATION_PLAYBOOK",
        "risk_level": _azure_risk_level(migration_mode),
        "human_review_required": migration_mode in {"OLD_SDK_ONLY", "MIXED_OLD_AND_NEW"},
        "safe_to_auto_apply": False,
        "old_azure_dependencies": old_dependencies,
        "new_azure_dependencies": new_dependencies,
        "source_usage_files": source_usage_files,
        "usage_patterns": usage_patterns,
        "migration_mode": migration_mode,
        "recommended_next_actions": _azure_recommended_actions(migration_mode, usage_patterns),
        "llm_candidate": migration_mode in {"OLD_SDK_ONLY", "MIXED_OLD_AND_NEW"} and bool(source_usage_files),
        "warnings": warnings,
        "file_findings": file_findings,
    }
    artifact_path = project_path / ".migration" / "review" / "azure_sdk_migration_review.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return AzureSdkMigrationReviewResult(
        artifact_path=artifact_path,
        detected=detected,
        migration_mode=migration_mode,
        old_azure_dependencies=old_dependencies,
        new_azure_dependencies=new_dependencies,
        source_usage_files=source_usage_files,
        usage_patterns=usage_patterns,
        risk_level=str(payload["risk_level"]),
        human_review_required=bool(payload["human_review_required"]),
        warnings=warnings,
    )


def review_jjwt_api_migration(
    project_path: Path,
    *,
    unit_id: str,
    run_id: str | None = None,
) -> JjwtApiMigrationReviewResult:
    project_path = Path(project_path).expanduser().resolve()
    file_findings = _detect_jjwt_api_usage(project_path)
    source_usage_files = [item["file"] for item in file_findings]
    usage_patterns = sorted({pattern for item in file_findings for pattern in item["patterns"]})
    detected = bool(source_usage_files)
    warnings = (
        ["Legacy JJWT parser API usage remains after version alignment; manual review required before trusting Boot 3 compatibility."]
        if detected
        else []
    )
    payload = {
        "run_id": run_id or "",
        "unit_id": unit_id,
        "detected": detected,
        "gate_id": "JJWT_API_MIGRATION_REVIEW",
        "risk_level": "HIGH" if detected else "NONE",
        "human_review_required": detected,
        "safe_to_auto_apply": False,
        "source_usage_files": source_usage_files,
        "usage_patterns": usage_patterns,
        "file_findings": file_findings,
        "recommended_next_actions": (
            [
                "Review remaining JJWT parser builder migration manually where deterministic .build() completion is not obviously safe.",
                "Update legacy parser API usage to JJWT builder completion before rerunning Boot 3 validation.",
            ]
            if detected
            else []
        ),
        "warnings": warnings,
    }
    artifact_path = project_path / ".migration" / "review" / "jjwt_api_migration_review.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return JjwtApiMigrationReviewResult(
        artifact_path=artifact_path,
        detected=detected,
        source_usage_files=source_usage_files,
        usage_patterns=usage_patterns,
        human_review_required=detected,
        warnings=warnings,
    )


def _detect_powermock_dependencies(pom_path: Path) -> list[str]:
    if not pom_path.is_file():
        return []
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return []
    namespace = _namespace(root.tag)
    detected: list[str] = []
    seen: set[str] = set()
    for dependency in root.findall(f".//{_tag(namespace, 'dependency')}"):
        group_id = _child_text(dependency, namespace, "groupId")
        artifact_id = _child_text(dependency, namespace, "artifactId")
        if not group_id.startswith(POWERMOCK_GROUP_PREFIX) or not artifact_id:
            continue
        coordinate = f"{group_id}:{artifact_id}"
        if coordinate in seen:
            continue
        seen.add(coordinate)
        detected.append(coordinate)
    return detected


def _detect_azure_dependencies(pom_path: Path) -> tuple[list[str], list[str]]:
    if not pom_path.is_file():
        return [], []
    try:
        root = ET.parse(pom_path).getroot()
    except ET.ParseError:
        return [], []
    namespace = _namespace(root.tag)
    old_detected: list[str] = []
    new_detected: list[str] = []
    old_seen: set[str] = set()
    new_seen: set[str] = set()
    for dependency in root.findall(f".//{_tag(namespace, 'dependency')}"):
        group_id = _child_text(dependency, namespace, "groupId")
        artifact_id = _child_text(dependency, namespace, "artifactId")
        if not group_id or not artifact_id:
            continue
        coordinate = f"{group_id}:{artifact_id}"
        if any(group_id.startswith(prefix) for prefix in AZURE_OLD_GROUP_PREFIXES):
            if coordinate not in old_seen:
                old_seen.add(coordinate)
                old_detected.append(coordinate)
        if any(group_id.startswith(prefix) for prefix in AZURE_NEW_GROUP_PREFIXES):
            if coordinate not in new_seen:
                new_seen.add(coordinate)
                new_detected.append(coordinate)
    return old_detected, new_detected


def _detect_powermock_usage(project_path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in _iter_test_java_files(project_path):
        text = path.read_text(encoding="utf-8")
        patterns = [label for label, marker in POWERMOCK_USAGE_MARKERS if marker in text]
        if not patterns:
            continue
        findings.append(
            {
                "file": str(path.relative_to(project_path)),
                "patterns": patterns,
            }
        )
    return findings


def _detect_jakarta_usage(project_path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in sorted((project_path / "src").rglob("*.java")) if (project_path / "src").is_dir() else []:
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        text = path.read_text(encoding="utf-8")
        namespaces = _namespaces_in_text(text)
        if not namespaces:
            continue
        findings.append(
            {
                "file": str(relative_path),
                "source_kind": _source_kind(relative_path),
                "public_api_like": _is_public_api_like(relative_path),
                "generated_source": _is_generated_source(relative_path),
                "namespaces": namespaces,
            }
        )
    return findings


def _detect_azure_usage(project_path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    src_root = project_path / "src"
    if not src_root.is_dir():
        return findings
    for path in sorted(src_root.rglob("*.java")):
        relative_path = _safe_relative(path, project_path)
        if not relative_path:
            continue
        text = _read_text(path)
        patterns = [label for label, marker in AZURE_USAGE_MARKERS if marker in text]
        if not patterns:
            continue
        findings.append(
            {
                "file": relative_path,
                "source_kind": _source_kind(Path(relative_path)),
                "patterns": _dedupe_preserve_order(patterns),
            }
        )
    return findings


def _detect_jjwt_api_usage(project_path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    source_root = project_path / "src" / "main" / "java"
    if not source_root.is_dir():
        return findings
    for path in sorted(source_root.rglob("*.java")):
        relative_path = _safe_relative(path, project_path)
        if not relative_path:
            continue
        text = _read_text(path)
        if "io.jsonwebtoken" not in text and "Jwts.parser()" not in text:
            continue
        candidates = [
            candidate
            for candidate in collect_jjwt_parser_compatibility_candidates(text)
            if not bool(candidate["already_built"])
        ]
        if not candidates:
            continue
        patterns: list[str] = []
        if "import io.jsonwebtoken.JwtParser;" in text:
            patterns.append("JWT_PARSER_IMPORT")
        if "Jwts.parser()" in text:
            patterns.append("JWTS_PARSER_CALL")
        if "JwtParserBuilder" in text:
            patterns.append("JWT_PARSER_BUILDER_TYPE")
        if "parseClaimsJws" in text:
            patterns.append("PARSE_CLAIMS_JWS")
        if "setSigningKey(" in text:
            patterns.append("SET_SIGNING_KEY")
        if any(candidate["mode"] == "assignment" for candidate in candidates):
            patterns.append("JWT_PARSER_ASSIGNMENT")
        if any(candidate["mode"] == "return" for candidate in candidates):
            patterns.append("JWT_PARSER_RETURN")
        if not patterns:
            continue
        findings.append(
            {
                "file": relative_path,
                "source_kind": "production",
                "patterns": _dedupe_preserve_order(patterns),
            }
        )
    return findings


def _summarize_jakarta_namespaces(file_findings: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for finding in file_findings:
        for namespace in list(finding.get("namespaces", []) or []):
            entry = summary.setdefault(
                namespace,
                {
                    "files": [],
                    "classification": _jakarta_classification(namespace),
                    "safe_to_auto_apply": _jakarta_safe_to_auto_apply(namespace),
                    "requires_human_approval": _jakarta_requires_human_approval(namespace),
                    "recommended_action": _jakarta_recommended_action(namespace),
                    "dependency_recommendations": _jakarta_dependency_recommendations(namespace),
                    "consumer_compatibility_warning": False,
                },
            )
            entry["files"].append(
                {
                    "file": finding["file"],
                    "source_kind": finding["source_kind"],
                    "public_api_like": finding["public_api_like"],
                    "generated_source": finding["generated_source"],
                }
            )
            if finding["public_api_like"] and namespace in {"javax.persistence", "javax.validation", "javax.xml.bind"}:
                entry["consumer_compatibility_warning"] = True
                entry["requires_human_approval"] = True
                entry["safe_to_auto_apply"] = False
    return summary


def _recommended_actions(dependencies: list[str], usage_patterns: list[str]) -> list[str]:
    actions: list[str] = []
    if dependencies and not usage_patterns:
        actions.append("PowerMock dependencies declared but no active usage found; review dependency cleanup before Boot 3 validation.")
    if "POWERMOCK_STATIC_MOCKING" in usage_patterns or "POWERMOCK_API" in usage_patterns:
        actions.append("PowerMock static mocking detected; perform human test modernization review for Mockito inline or test design alternatives.")
    if (
        "POWERMOCK_CONSTRUCTOR_MOCKING" in usage_patterns
        or "POWERMOCK_WHITEBOX" in usage_patterns
        or "POWERMOCK_SUPPRESS" in usage_patterns
    ):
        actions.append("Constructor mocking, Whitebox, or suppress usage detected; treat as high-risk manual review.")
    if not actions and (dependencies or usage_patterns):
        actions.append("PowerMock usage detected; manual test modernization review required before trusting Boot 3 behavior.")
    return actions


def _azure_migration_mode(old_dependencies: list[str], new_dependencies: list[str]) -> str:
    if old_dependencies and new_dependencies:
        return "MIXED_OLD_AND_NEW"
    if old_dependencies:
        return "OLD_SDK_ONLY"
    if new_dependencies:
        return "NEW_SDK_ONLY"
    return "NOT_DETECTED"


def _azure_risk_level(migration_mode: str) -> str:
    if migration_mode in {"OLD_SDK_ONLY", "MIXED_OLD_AND_NEW"}:
        return "HIGH"
    if migration_mode == "NEW_SDK_ONLY":
        return "INFO"
    return "NONE"


def _azure_warnings(migration_mode: str) -> list[str]:
    warnings: list[str] = []
    if migration_mode == "OLD_SDK_ONLY":
        warnings.append("Legacy Azure SDK usage detected; manual migration review required before changing client APIs or runtime behavior.")
    if migration_mode == "MIXED_OLD_AND_NEW":
        warnings.append("Mixed old and new Azure SDK usage detected; partial coexistence requires human review to avoid duplicate runtime stacks.")
    return warnings


def _azure_recommended_actions(migration_mode: str, usage_patterns: list[str]) -> list[str]:
    actions: list[str] = []
    if "SERVICE_BUS_USAGE" in usage_patterns:
        actions.append("Review migration from legacy Service Bus SDK usage to com.azure:azure-messaging-servicebus.")
    if "BLOB_STORAGE_USAGE" in usage_patterns:
        actions.append("Review migration from legacy Blob Storage SDK usage to com.azure:azure-storage-blob.")
    if "IDENTITY_AUTH_USAGE" in usage_patterns:
        actions.append("Review migration of Azure identity/auth flows to com.azure:azure-identity.")
    if migration_mode == "MIXED_OLD_AND_NEW":
        actions.append("Mixed Azure SDK generations detected; require human review before accepting dual-stack runtime behavior.")
    if migration_mode in {"OLD_SDK_ONLY", "MIXED_OLD_AND_NEW"} and not actions:
        actions.append("Legacy Azure SDK detected; localized API migration proposals may be useful later if LLM policy allows, but manual review required now.")
    if migration_mode == "NEW_SDK_ONLY" and not actions:
        actions.append("Modern Azure SDK already present; review configuration and runtime behavior only if migration issues surface.")
    return actions


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _jakarta_warnings(namespace_summary: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if "javax.persistence" in namespace_summary:
        warnings.append("Jakarta hybrid strategy detected javax.persistence usage; manual review required before blind namespace migration.")
    if any(ns.startswith("javax.") and ns not in {
        "javax.validation",
        "javax.xml.bind",
        "javax.servlet",
        "javax.annotation",
        "javax.persistence",
        "javax.ws.rs",
    } for ns in namespace_summary):
        warnings.append("Unknown javax.* usage detected; manual Jakarta review required.")
    if any(bool(item.get("consumer_compatibility_warning")) for item in namespace_summary.values()):
        warnings.append("Public API or DTO package uses javax.* namespace; consumer compatibility review required.")
    return warnings


def _namespaces_in_text(text: str) -> list[str]:
    detected: list[str] = []
    seen: set[str] = set()
    for namespace, pattern in JAKARTA_NAMESPACE_PATTERNS:
        if pattern.search(text) and namespace not in seen:
            seen.add(namespace)
            detected.append(namespace)
    for match in GENERIC_JAVAX_PATTERN.findall(text):
        base = ".".join(match.split(".")[:3]) if match.count(".") >= 2 else match
        namespace = match
        for known, _ in JAKARTA_NAMESPACE_PATTERNS:
            if match.startswith(known):
                namespace = known
                break
        if namespace not in seen:
            seen.add(namespace)
            detected.append(namespace)
    return detected


def _source_kind(relative_path: Path) -> str:
    parts = [part.lower() for part in relative_path.parts]
    if "test" in parts or any("test" in part for part in parts):
        return "test"
    return "production"


def _is_public_api_like(relative_path: Path) -> bool:
    lowered = [part.lower() for part in relative_path.parts]
    return any(part in {"dto", "api", "contract", "public"} for part in lowered)


def _is_generated_source(relative_path: Path) -> bool:
    lowered = [part.lower() for part in relative_path.parts]
    return any("generated" in part for part in lowered)


def _jakarta_classification(namespace: str) -> str:
    if namespace == "javax.xml.bind":
        return "DETERMINISTIC_SAFE_MIGRATION_CANDIDATE"
    if namespace in {"javax.validation", "javax.servlet"}:
        return "DETERMINISTIC_PLUS_DEPENDENCY_ALIGNMENT"
    if namespace == "javax.annotation":
        return "REVIEW_OR_DETERMINISTIC_CANDIDATE"
    if namespace == "javax.persistence":
        return "HUMAN_REVIEW_CANDIDATE"
    return "HUMAN_REVIEW_CANDIDATE"


def _jakarta_safe_to_auto_apply(namespace: str) -> bool:
    return namespace in {"javax.xml.bind", "javax.validation", "javax.servlet"}


def _jakarta_requires_human_approval(namespace: str) -> bool:
    return namespace not in {"javax.xml.bind", "javax.validation", "javax.servlet"}


def _jakarta_recommended_action(namespace: str) -> str:
    mapping = {
        "javax.xml.bind": "Use existing deterministic JAXB Jakarta migration and review generated contract compatibility.",
        "javax.validation": "Use validation namespace migration with Jakarta validation dependency alignment.",
        "javax.servlet": "Use servlet namespace migration and review servlet dependency alignment.",
        "javax.annotation": "Review whether deterministic jakarta.annotation mapping is safe for this library and source set.",
        "javax.persistence": "Treat JPA namespace migration as high-risk manual review with schema and consumer compatibility checks.",
        "javax.ws.rs": "Review JAX-RS migration path manually; namespace and runtime stack may vary by library.",
    }
    return mapping.get(namespace, "Unknown javax.* namespace detected; manual Jakarta migration review required.")


def _jakarta_dependency_recommendations(namespace: str) -> list[str]:
    mapping = {
        "javax.xml.bind": ["jakarta.xml.bind-api"],
        "javax.validation": ["spring-boot-starter-validation or jakarta.validation-api"],
        "javax.servlet": ["jakarta.servlet-api or container-managed servlet stack"],
    }
    return list(mapping.get(namespace, []))


def _iter_test_java_files(project_path: Path) -> list[Path]:
    src_root = project_path / "src"
    if not src_root.is_dir():
        return []
    matches: list[Path] = []
    for path in sorted(src_root.rglob("*.java")):
        try:
            relative_path = path.relative_to(project_path)
        except ValueError:
            continue
        parts = [part.lower() for part in relative_path.parts[:-1]]
        if "main" in parts:
            continue
        if not any("test" in part for part in parts):
            continue
        matches.append(path)
    return matches


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _namespace(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1 : tag.index("}")]
    return ""


def _tag(namespace: str, name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{name}"
    return name


def _child_text(parent: ET.Element, namespace: str, name: str) -> str:
    child = parent.find(_tag(namespace, name))
    if child is None or child.text is None:
        return ""
    return child.text.strip()
