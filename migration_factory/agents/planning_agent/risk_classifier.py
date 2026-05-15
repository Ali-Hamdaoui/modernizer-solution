from dataclasses import dataclass, field
from typing import Any, Literal

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.profile_compatibility import StackFingerprint

RiskSeverity = Literal["BLOCKER", "WARNING", "INFO"]


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

    javax_count = _extract_javax_count(loaded_artifacts)
    if javax_count is not None and javax_count > 0:
        risks.append(
            PlanningRiskItem(
                code="JAKARTA_MIGRATION_REQUIRED",
                severity="WARNING",
                message=f"Detected javax usage count: {javax_count}.",
                source="analysis",
            )
        )

    has_blocker = any(r.severity == "BLOCKER" for r in risks)
    return PlanningRiskResult(ok=not has_blocker, risks=risks)


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
        ):
            value = _get_by_path(obj, key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip().isdigit():
                return int(value.strip())
    return None


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
