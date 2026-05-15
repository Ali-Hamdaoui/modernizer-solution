from dataclasses import dataclass, field
from typing import Any

from migration_factory.agents.planning_agent.artifact_reader import LoadedAnalysisArtifacts
from migration_factory.agents.planning_agent.profile_reader import LoadedMigrationProfile


@dataclass(frozen=True)
class StackFingerprint:
    build_tool: str | None = None
    java: str | None = None
    spring_boot: str | None = None


@dataclass(frozen=True)
class ProfileCompatibilityResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_stack: StackFingerprint = field(default_factory=StackFingerprint)
    target_stack: StackFingerprint = field(default_factory=StackFingerprint)


def validate_profile_compatibility(
    loaded_artifacts: LoadedAnalysisArtifacts,
    loaded_profile: LoadedMigrationProfile,
) -> ProfileCompatibilityResult:
    errors: list[str] = []
    warnings: list[str] = []

    source_stack = _extract_source_stack(loaded_artifacts)
    target_stack = _extract_target_stack(loaded_profile)

    if source_stack.build_tool:
        if source_stack.build_tool.lower() != "maven":
            errors.append(
                "Source build tool incompatible with planning target. Expected Maven-compatible source build metadata."
            )
    else:
        warnings.append("Source build tool unknown from analysis artifacts.")

    if source_stack.java:
        if source_stack.java not in {"8", "11"}:
            errors.append(
                f"Source Java version unsupported for this planning path: {source_stack.java}. Expected 8 or 11."
            )
    else:
        warnings.append("Source Java version missing or unknown in analysis artifacts.")

    if source_stack.spring_boot:
        if source_stack.spring_boot != "2.7":
            errors.append(
                "Source Spring Boot version unsupported for this planning path: "
                f"{source_stack.spring_boot}. Expected 2.7."
            )
    else:
        warnings.append("Source Spring Boot version missing or unknown in analysis artifacts.")

    if target_stack.java != "17":
        errors.append(
            f"Target Java mismatch: expected 17, got {target_stack.java or 'missing'}"
        )

    if target_stack.spring_boot != "3.5.14":
        errors.append(
            "Target Spring Boot mismatch: expected 3.5.14, got "
            f"{target_stack.spring_boot or 'missing'}"
        )

    return ProfileCompatibilityResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        source_stack=source_stack,
        target_stack=target_stack,
    )


def _extract_source_stack(loaded_artifacts: LoadedAnalysisArtifacts) -> StackFingerprint:
    candidates: list[dict[str, Any]] = []

    for obj in (
        loaded_artifacts.required.get("analysis_report.json"),
        loaded_artifacts.required.get("dependency_graph.json"),
        loaded_artifacts.optional.get("config_inventory.json"),
    ):
        if isinstance(obj, dict):
            candidates.append(obj)

    build_tool = _first_string(
        candidates,
        [
            "build_tool",
            "build.tool",
            "source.build_tool",
            "source.build.tool",
            "metadata.build_tool",
        ],
    )
    java_raw = _first_string(
        candidates,
        [
            "java",
            "java_version",
            "source.java",
            "source.java_version",
            "runtime.java",
            "metadata.java",
            "metadata.java_version",
        ],
    )
    spring_raw = _first_string(
        candidates,
        [
            "spring_boot",
            "spring_boot_version",
            "spring.boot",
            "source.spring_boot",
            "source.spring_boot_version",
            "metadata.spring_boot",
        ],
    )

    return StackFingerprint(
        build_tool=_normalize_build_tool(build_tool),
        java=_normalize_java(java_raw),
        spring_boot=_normalize_spring_boot(spring_raw),
    )


def _extract_target_stack(loaded_profile: LoadedMigrationProfile) -> StackFingerprint:
    target = loaded_profile.profile.get("target")
    if not isinstance(target, dict):
        return StackFingerprint()

    build_tool = (
        target.get("build")
        or target.get("build_tool")
        or target.get("buildTool")
    )
    return StackFingerprint(
        build_tool=_normalize_build_tool(build_tool),
        java=_normalize_java(target.get("java")),
        spring_boot=_normalize_spring_boot(target.get("spring_boot")),
    )


def _first_string(candidates: list[dict[str, Any]], paths: list[str]) -> str | None:
    for candidate in candidates:
        for path in paths:
            value = _get_by_path(candidate, path)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, int):
                return str(value)
    return None


def _get_by_path(obj: dict[str, Any], path: str) -> Any:
    current: Any = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _normalize_build_tool(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if "maven" in lower or lower == "mvn":
        return "maven"
    if "gradle" in lower:
        return "gradle"
    return lower


def _normalize_java(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text.startswith("1.8"):
        return "8"
    if text.startswith("8"):
        return "8"
    if text.startswith("11"):
        return "11"
    if text.startswith("17"):
        return "17"
    return text


def _normalize_spring_boot(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        if parts[0] == "2" and parts[1] == "7":
            return "2.7"
        if parts[0] == "3" and parts[1] == "5":
            return "3.5.14" if text == "3.5.14" else f"{parts[0]}.{parts[1]}"
    return text
