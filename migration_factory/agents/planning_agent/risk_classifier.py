from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal
import re

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint
from migration_factory.profile_semantics import should_openrewrite_impact_be_fatal

RiskSeverity = Literal["BLOCKER", "HIGH", "WARNING", "INFO"]


@dataclass(frozen=True)
class PlanningRiskItem:
    code: str
    severity: RiskSeverity
    message: str
    source: str


@dataclass(frozen=True)
class PlanningRiskResult:
    ok: bool
    risks: list[PlanningRiskItem] = field(default_factory=list)


def classify_planning_risks(
    loaded_artifacts: LoadedAnalysisArtifacts,
    source_stack: StackFingerprint,
    *,
    target_stack: StackFingerprint | None = None,
    selected_route_id: str | None = None,
    route_strategy: str | None = None,
    selected_hops: tuple[dict[str, Any], ...] = (),
    planned_unit_ids: tuple[str, ...] = (),
    profile_id: str | None = None,
    migration_units: Sequence[str] | None = None,
) -> PlanningRiskResult:
    risks: list[PlanningRiskItem] = []

    if _has_unreadable_or_invalid_build_metadata(loaded_artifacts):
        risks.append(
            PlanningRiskItem(
                code="UNREADABLE_BUILD_METADATA",
                severity="BLOCKER",
                message="Build metadata unreadable or invalid from analysis artifacts.",
                source="analysis",
            )
        )

    if source_stack.java is None:
        risks.append(
            PlanningRiskItem(
                code="UNKNOWN_SOURCE_JAVA",
                severity="WARNING",
                message="Source Java version unknown in analysis artifacts.",
                source="analysis",
            )
        )

    if source_stack.spring_boot is None:
        risks.append(
            PlanningRiskItem(
                code="UNKNOWN_SOURCE_SPRING_BOOT",
                severity="WARNING",
                message="Source Spring Boot version unknown in analysis artifacts.",
                source="analysis",
            )
        )

    target = target_stack or StackFingerprint()
    risks.extend(
        _classify_route_governance_risks(
            source_stack=source_stack,
            target_stack=target,
            selected_route_id=selected_route_id,
            route_strategy=route_strategy,
            selected_hops=selected_hops,
        )
    )

    imports = _extract_imports(loaded_artifacts)
    dependencies = _extract_dependencies(loaded_artifacts)
    project_kind = _extract_project_kind(loaded_artifacts)
    internal_dependencies = _extract_internal_dependencies(loaded_artifacts)
    has_juneau_contracts = _extract_bool(loaded_artifacts, ("has_juneau_contracts",))

    risks.extend(
        _classify_jakarta_namespace_risks(
            loaded_artifacts=loaded_artifacts,
            target_stack=target,
            imports=imports,
            dependencies=dependencies,
            planned_unit_ids=planned_unit_ids,
        )
    )
    javax_count = _extract_javax_count(loaded_artifacts)
    if javax_count is not None and javax_count > 0 and not _is_boot3_target(target.spring_boot):
        risks.append(
            PlanningRiskItem(
                code="JAKARTA_MIGRATION_REQUIRED",
                severity="WARNING",
                message=f"Detected javax usage count: {javax_count}.",
                source="analysis",
            )
        )
    risks.extend(
        _classify_framework_library_risks(
            target_stack=target,
            imports=imports,
            dependencies=dependencies,
            project_kind=project_kind,
            has_juneau_contracts=has_juneau_contracts,
            internal_dependencies=internal_dependencies,
        )
    )

    risks.extend(
        _classify_openrewrite_impact(
            loaded_artifacts,
            profile_id=profile_id,
            migration_units=migration_units,
        )
    )

    has_blocker = any(r.severity == "BLOCKER" for r in risks)
    return PlanningRiskResult(ok=not has_blocker, risks=risks)


def _classify_route_governance_risks(
    *,
    source_stack: StackFingerprint,
    target_stack: StackFingerprint,
    selected_route_id: str | None,
    route_strategy: str | None,
    selected_hops: tuple[dict[str, Any], ...],
) -> list[PlanningRiskItem]:
    if not _is_boot3_target(target_stack.spring_boot):
        return []
    if not _is_pre_27_boot(source_stack.spring_boot):
        return []

    source_boot = source_stack.spring_boot or "unknown"
    hop_ids = [str(hop.get("id") or "unknown") for hop in selected_hops if isinstance(hop, dict)]
    has_intermediate_27 = any(_hop_targets_boot_27(hop) for hop in selected_hops if isinstance(hop, dict))

    if route_strategy == "direct_sandbox":
        return [
            PlanningRiskItem(
                code="BOOT_PRE_27_TO_BOOT3_DIRECT_SANDBOX",
                severity="HIGH",
                message=(
                    f"Source Spring Boot {source_boot} targets Boot 3.x through direct sandbox route "
                    f"{selected_route_id or 'unknown'}. Direct Boot < 2.7 to Boot 3.x migration is sandbox-only; "
                    "preferred enterprise governance should pass through latest Boot 2.7.x with build/test evidence."
                ),
                source="route",
            )
        ]

    if route_strategy == "multi_hop" and has_intermediate_27:
        return [
            PlanningRiskItem(
                code="BOOT_PRE_27_TO_BOOT3_MULTI_HOP",
                severity="HIGH",
                message=(
                    f"Source Spring Boot {source_boot} targets Boot 3.x through a governed multi-hop route: "
                    f"{' -> '.join(hop_ids)}. Each hop should produce build/test evidence before final Boot 3.x approval."
                ),
                source="route",
            )
        ]

    severity: RiskSeverity = "BLOCKER" if not selected_route_id and not route_strategy else "HIGH"
    return [
        PlanningRiskItem(
            code="BOOT_PRE_27_TO_BOOT3_WITHOUT_MITIGATION",
            severity=severity,
            message=(
                f"Source Spring Boot {source_boot} targets Boot 3.x without explicit Boot 2.7 mitigation route metadata. "
                "Preferred enterprise route should pass through latest Boot 2.7.x before Boot 3.x."
            ),
            source="route",
        )
    ]


def _classify_jakarta_namespace_risks(
    *,
    loaded_artifacts: LoadedAnalysisArtifacts,
    target_stack: StackFingerprint,
    imports: set[str],
    dependencies: list[dict[str, str]],
    planned_unit_ids: tuple[str, ...],
) -> list[PlanningRiskItem]:
    risks: list[PlanningRiskItem] = []
    if not _is_boot3_target(target_stack.spring_boot):
        return risks

    has_jakarta_unit = "jakarta" in planned_unit_ids
    has_jaxb_unit = "jaxb-jakarta" in planned_unit_ids

    namespace_rules = (
        (
            "JAVAX_PERSISTENCE_BOOT3",
            "javax.persistence",
            ["javax.persistence", "javax.persistence-api"],
            "JPA `javax.persistence` usage must migrate to Jakarta for Boot 3.x.",
            not has_jakarta_unit,
            "JAKARTA_UNIT_MISSING_FOR_JPA",
            "Boot 3.x target with javax.persistence usage requires planned Jakarta migration unit.",
        ),
        (
            "JAVAX_XML_BIND_BOOT3",
            "javax.xml.bind",
            ["javax.xml.bind", "jaxb-api"],
            "JAXB `javax.xml.bind` usage must migrate to Jakarta XML Bind for Boot 3.x.",
            not has_jaxb_unit,
            "JAXB_JAKARTA_UNIT_MISSING",
            "Boot 3.x target with javax.xml.bind usage requires planned jaxb-jakarta migration unit.",
        ),
        (
            "JAVAX_SERVLET_BOOT3",
            "javax.servlet",
            ["javax.servlet", "javax.servlet-api"],
            "Servlet `javax.servlet` usage must migrate to Jakarta Servlet for Boot 3.x.",
            not has_jakarta_unit,
            "JAKARTA_UNIT_MISSING_FOR_SERVLET",
            "Boot 3.x target with javax.servlet usage requires planned Jakarta migration unit.",
        ),
        (
            "JAVAX_ANNOTATION_BOOT3",
            "javax.annotation",
            ["javax.annotation", "javax.annotation-api"],
            "`javax.annotation` usage must migrate to Jakarta-compatible annotations for Boot 3.x.",
            not has_jakarta_unit,
            "JAKARTA_UNIT_MISSING_FOR_ANNOTATION",
            "Boot 3.x target with javax.annotation usage requires planned Jakarta migration unit.",
        ),
        (
            "JAVAX_VALIDATION_BOOT3",
            "javax.validation",
            ["javax.validation", "validation-api"],
            "`javax.validation` usage must migrate to Jakarta Validation for Boot 3.x.",
            not has_jakarta_unit,
            "JAKARTA_UNIT_MISSING_FOR_VALIDATION",
            "Boot 3.x target with javax.validation usage requires planned Jakarta migration unit.",
        ),
    )

    for high_code, import_prefix, dependency_markers, high_message, needs_blocker, blocker_code, blocker_message in namespace_rules:
        if _has_import_prefix(imports, import_prefix) or _has_dependency_marker(dependencies, dependency_markers):
            risks.append(
                PlanningRiskItem(
                    code=high_code,
                    severity="HIGH",
                    message=high_message,
                    source="analysis",
                )
            )
            if needs_blocker:
                risks.append(
                    PlanningRiskItem(
                        code=blocker_code,
                        severity="BLOCKER",
                        message=blocker_message,
                        source="planning",
                    )
                )

    javax_count = _extract_javax_count(loaded_artifacts)
    if javax_count is not None and javax_count > 0:
        risks.append(
            PlanningRiskItem(
                code="JAKARTA_MIGRATION_REQUIRED",
                severity="HIGH",
                message=f"Detected javax usage count: {javax_count}. Boot 3.x target requires Jakarta migration review.",
                source="analysis",
            )
        )

    return _dedupe_risks(risks)


def _classify_framework_library_risks(
    *,
    target_stack: StackFingerprint,
    imports: set[str],
    dependencies: list[dict[str, str]],
    project_kind: str | None,
    has_juneau_contracts: bool,
    internal_dependencies: list[dict[str, Any]],
) -> list[PlanningRiskItem]:
    risks: list[PlanningRiskItem] = []

    if has_juneau_contracts or _has_import_prefix(imports, "org.apache.juneau") or _has_dependency_text(dependencies, "juneau"):
        risks.append(
            PlanningRiskItem(
                code="APACHE_JUNEAU_HUMAN_REVIEW",
                severity="HIGH",
                message="Apache Juneau usage detected. Human review required for contract/runtime compatibility.",
                source="analysis",
            )
        )

    if (
        _has_import_prefix(imports, "org.springframework.security.config.annotation.web.configuration.WebSecurityConfigurerAdapter")
        or _has_dependency_marker(dependencies, ["spring-security-oauth", "spring-security-jwt"])
    ):
        risks.append(
            PlanningRiskItem(
                code="SPRING_SECURITY_LEGACY_HUMAN_REVIEW",
                severity="HIGH",
                message="Legacy Spring Security usage detected. Human review required before Boot 3.x migration approval.",
                source="analysis",
            )
        )

    if _has_import_prefix(imports, "com.microsoft.azure") or _has_dependency_group_prefix(dependencies, "com.microsoft.azure"):
        risks.append(
            PlanningRiskItem(
                code="AZURE_LEGACY_SDK_HUMAN_REVIEW",
                severity="HIGH",
                message="Legacy Azure SDK usage detected under com.microsoft.azure.*. Human review required for SDK replacement strategy.",
                source="analysis",
            )
        )

    lombok = _find_dependency(dependencies, "org.projectlombok", "lombok")
    if lombok is not None:
        version = lombok.get("version") or ""
        severity: RiskSeverity = "HIGH" if _is_old_lombok_version(version) else "WARNING"
        risks.append(
            PlanningRiskItem(
                code="LOMBOK_VERSION_REVIEW",
                severity=severity,
                message=(
                    f"Lombok dependency detected"
                    + (f" at version {version}." if version else ".")
                    + " Review Lombok compatibility for target Java/Spring baseline."
                ),
                source="analysis",
            )
        )

    if project_kind == "contract_library":
        risks.append(
            PlanningRiskItem(
                code="CONTRACT_LIBRARY_HUMAN_REVIEW",
                severity="HIGH",
                message="Project classified as contract_library. Human review required for contract compatibility and consumer impact.",
                source="analysis",
            )
        )

    if internal_dependencies:
        risks.append(
            PlanningRiskItem(
                code="INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW",
                severity="WARNING",
                message=(
                    f"Detected {len(internal_dependencies)} internal dependency candidate(s). "
                    "Review migration order across repositories before approval."
                ),
                source="analysis",
            )
        )

    return _dedupe_risks(risks)


def _classify_openrewrite_impact(
    loaded_artifacts: LoadedAnalysisArtifacts,
    *,
    profile_id: str | None = None,
    migration_units: Sequence[str] | None = None,
) -> list[PlanningRiskItem]:
    impact_summary = loaded_artifacts.optional.get("rewrite_impact_summary.json")
    if not isinstance(impact_summary, dict):
        return []

    risks: list[PlanningRiskItem] = []
    raw_impact = impact_summary.get("overall_impact")
    if raw_impact is None:
        risks.append(
            PlanningRiskItem(
                code="OPENREWRITE_IMPACT_SCHEMA_MISMATCH",
                severity="WARNING",
                message="OpenRewrite impact artifact is missing overall_impact.",
                source="openrewrite",
            )
        )
    impact = raw_impact.strip().upper() if isinstance(raw_impact, str) else "UNKNOWN"

    if impact not in {"LOW", "MEDIUM", "HIGH", "BLOCKED", "UNKNOWN"}:
        impact = "UNKNOWN"

    fatal_blocked = should_openrewrite_impact_be_fatal(
        profile_id=profile_id,
        unit_ids=migration_units,
    )
    severity_by_impact: dict[str, RiskSeverity] = {
        "LOW": "INFO",
        "MEDIUM": "WARNING",
        "HIGH": "WARNING",
        "BLOCKED": "BLOCKER",
        "UNKNOWN": "WARNING",
    }
    message_by_impact = {
        "LOW": "OpenRewrite impact is low.",
        "MEDIUM": "OpenRewrite impact is medium.",
        "HIGH": "OpenRewrite impact is high; manual review is required before execution.",
        "BLOCKED": "OpenRewrite impact is blocked; planning output is not executable.",
        "UNKNOWN": "OpenRewrite impact is unknown or missing.",
    }
    severity = severity_by_impact[impact]
    message = message_by_impact[impact]
    if impact == "BLOCKED" and not fatal_blocked:
        severity = "WARNING"
        message = (
            "OpenRewrite impact is blocked for a Java 21 runtime-validation route; "
            "continuing to runtime validation gate."
        )

    risks.append(
        PlanningRiskItem(
            code=f"OPENREWRITE_IMPACT_{impact}",
            severity=severity,
            message=message,
            source="openrewrite",
        )
    )

    high_risk_files = impact_summary.get("high_risk_files")
    if isinstance(high_risk_files, list) and high_risk_files:
        risks.append(
            PlanningRiskItem(
                code="OPENREWRITE_HIGH_RISK_FILES",
                severity="WARNING",
                message=f"OpenRewrite reported high-risk files: {len(high_risk_files)}.",
                source="openrewrite",
            )
        )

    migration_signals = impact_summary.get("migration_signals")
    if isinstance(migration_signals, dict):
        if migration_signals.get("security_config_touched") is True:
            risks.append(
                PlanningRiskItem(
                    code="OPENREWRITE_SECURITY_CONFIG_TOUCHED",
                    severity="WARNING",
                    message="OpenRewrite migration signals indicate security configuration was touched.",
                    source="openrewrite",
                )
            )
        if migration_signals.get("datasource_config_touched") is True:
            risks.append(
                PlanningRiskItem(
                    code="OPENREWRITE_DATASOURCE_CONFIG_TOUCHED",
                    severity="WARNING",
                    message="OpenRewrite migration signals indicate datasource configuration was touched.",
                    source="openrewrite",
                )
            )

    return risks


def _has_unreadable_or_invalid_build_metadata(
    loaded_artifacts: LoadedAnalysisArtifacts,
) -> bool:
    errors_text = "\n".join(loaded_artifacts.errors).lower()
    if "pom" in errors_text:
        return True

    for obj in _iter_dict_candidates(loaded_artifacts):
        for key in (
            "pom_readable",
            "pom_valid",
            "build_metadata_readable",
            "build_metadata_valid",
        ):
            value = _get_by_path(obj, key)
            if value is False:
                return True

        for key in (
            "pom_error",
            "pom_parse_error",
            "build_metadata_error",
            "build_metadata_parse_error",
        ):
            value = _get_by_path(obj, key)
            if isinstance(value, str) and value.strip():
                return True

    return False


def _extract_javax_count(loaded_artifacts: LoadedAnalysisArtifacts) -> int | None:
    for obj in _iter_dict_candidates(loaded_artifacts):
        for key in (
            "javax_count",
            "jakarta.javax_count",
            "inventory.javax_count",
            "source.javax_count",
            "project_metadata.import_stats.javax_count",
        ):
            value = _get_by_path(obj, key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
    return None


def _extract_imports(loaded_artifacts: LoadedAnalysisArtifacts) -> set[str]:
    imports: set[str] = set()
    for obj in _iter_dict_candidates(loaded_artifacts):
        for key in (
            "java_imports",
            "imports",
            "project_metadata.imports",
            "analysis_signals.imports",
            "detected_imports",
        ):
            value = _get_by_path(obj, key)
            if isinstance(value, list):
                imports.update(str(item).strip() for item in value if str(item).strip())
    return imports


def _extract_dependencies(loaded_artifacts: LoadedAnalysisArtifacts) -> list[dict[str, str]]:
    dependencies: list[dict[str, str]] = []
    for obj in _iter_dict_candidates(loaded_artifacts):
        for key in ("dependencies", "project_metadata.dependencies", "analysis_dependencies"):
            value = _get_by_path(obj, key)
            if not isinstance(value, list):
                continue
            for item in value:
                if not isinstance(item, dict):
                    continue
                dependencies.append(
                    {
                        "groupId": str(item.get("groupId") or item.get("group_id") or "").strip(),
                        "artifactId": str(item.get("artifactId") or item.get("artifact_id") or "").strip(),
                        "version": str(item.get("version") or "").strip(),
                    }
                )
    graph = loaded_artifacts.required.get("dependency_graph.json")
    if isinstance(graph, dict):
        root = graph.get("root")
        if isinstance(root, dict):
            dependencies.extend(_flatten_dependency_graph(root))
    return dependencies


def _flatten_dependency_graph(node: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    name = str(node.get("name") or "").strip()
    group_id = ""
    artifact_id = ""
    if ":" in name:
        group_id, artifact_id = name.split(":", 1)
    out.append(
        {
            "groupId": group_id.strip(),
            "artifactId": artifact_id.strip(),
            "version": str(node.get("version") or "").strip(),
        }
    )
    for child in node.get("dependencies", []) or []:
        if isinstance(child, dict):
            out.extend(_flatten_dependency_graph(child))
    return out


def _extract_project_kind(loaded_artifacts: LoadedAnalysisArtifacts) -> str | None:
    for obj in _iter_dict_candidates(loaded_artifacts):
        value = _get_by_path(obj, "project_kind")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_internal_dependencies(loaded_artifacts: LoadedAnalysisArtifacts) -> list[dict[str, Any]]:
    for obj in _iter_dict_candidates(loaded_artifacts):
        value = _get_by_path(obj, "internal_dependencies")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_bool(loaded_artifacts: LoadedAnalysisArtifacts, paths: tuple[str, ...]) -> bool:
    for obj in _iter_dict_candidates(loaded_artifacts):
        for path in paths:
            value = _get_by_path(obj, path)
            if isinstance(value, bool):
                return value
    return False


def _iter_dict_candidates(loaded_artifacts: LoadedAnalysisArtifacts) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for obj in loaded_artifacts.required.values():
        if isinstance(obj, dict):
            out.append(obj)
    for obj in loaded_artifacts.optional.values():
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _get_by_path(obj: dict[str, Any], path: str) -> Any:
    current: Any = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_boot3_target(value: str | None) -> bool:
    major, _minor = _spring_boot_version_parts(value)
    return major == 3


def _is_pre_27_boot(value: str | None) -> bool:
    major, minor = _spring_boot_version_parts(value)
    return major == 2 and minor is not None and minor < 7


def _spring_boot_version_parts(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    match = re.match(r"^\s*(\d+)\.(\d+)", str(value))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _hop_targets_boot_27(hop: dict[str, Any]) -> bool:
    target = hop.get("target")
    if not isinstance(target, dict):
        return False
    spring_boot = target.get("spring_boot")
    return str(spring_boot).startswith("2.7")


def _has_import_prefix(imports: set[str], prefix: str) -> bool:
    return any(item == prefix or item.startswith(f"{prefix}.") for item in imports)


def _has_dependency_marker(dependencies: list[dict[str, str]], markers: list[str]) -> bool:
    for dependency in dependencies:
        haystack = " ".join(
            [
                dependency.get("groupId", "").lower(),
                dependency.get("artifactId", "").lower(),
            ]
        )
        for marker in markers:
            marker_lower = marker.lower()
            if marker_lower in haystack:
                return True
    return False


def _has_dependency_text(dependencies: list[dict[str, str]], text: str) -> bool:
    return _has_dependency_marker(dependencies, [text])


def _has_dependency_group_prefix(dependencies: list[dict[str, str]], prefix: str) -> bool:
    prefix_lower = prefix.lower()
    return any(dependency.get("groupId", "").lower().startswith(prefix_lower) for dependency in dependencies)


def _find_dependency(dependencies: list[dict[str, str]], group_id: str, artifact_id: str) -> dict[str, str] | None:
    for dependency in dependencies:
        if dependency.get("groupId") == group_id and dependency.get("artifactId") == artifact_id:
            return dependency
    return None


def _is_old_lombok_version(version: str) -> bool:
    match = re.match(r"^\s*(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return False
    major, minor, patch = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return (major, minor, patch) < (1, 18, 16)


def _dedupe_risks(risks: list[PlanningRiskItem]) -> list[PlanningRiskItem]:
    deduped: list[PlanningRiskItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for risk in risks:
        key = (risk.code, risk.severity, risk.message, risk.source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(risk)
    return deduped
