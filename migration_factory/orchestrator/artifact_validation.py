from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from migration_factory.contracts import ANALYSIS_OPTIONAL_ARTIFACTS
from migration_factory.contracts.schema_validation import validate_against_schema
from migration_factory.orchestrator.state import MigrationState


@dataclass(frozen=True)
class ArtifactValidationResult:
    valid: bool
    artifact_refs: dict[str, str]
    blockers: list[str]
    warnings: list[str]


ANALYSIS_REQUIRED_ARTIFACTS = (
    "analysis_report.json",
    "dependency_graph.json",
    "test_inventory.json",
    "analysis_summary.md",
    "read_only_verification.json",
)
PLANNING_REQUIRED_ARTIFACTS = (
    "migration_plan.yaml",
    "migration_units.yaml",
    "plan_summary.md",
    "approval_request.json",
    "plan_validation_report.json",
)
ASSESSMENT_REQUIRED_ARTIFACTS = (
    "assessment_report.json",
    "assessment_summary.md",
)

SCHEMA_BACKED_ARTIFACTS = {
    "analysis_report.json": "analysis_report.schema.json",
    "read_only_verification.json": "read_only_verification.schema.json",
    "rewrite_plugin_plan.json": "rewrite_plugin_plan.schema.json",
    "rewrite_impact_summary.json": "rewrite_impact_summary.schema.json",
    "migration_plan.yaml": "migration_plan.schema.json",
    "migration_units.yaml": "migration_units.schema.json",
    "approval_request.json": "approval_request.schema.json",
    "assessment_report.json": "assessment_report.schema.json",
}

ASSESSMENT_EXECUTION_CLAIMS = (
    "transformation_executed",
    "openrewrite_apply_executed",
    "migrated_build_executed",
    "migrated_tests_executed",
    "final_migration_executed",
)


def validate_analysis_artifacts(state: MigrationState) -> ArtifactValidationResult:
    result = _validate_artifacts(
        Path(state["analysis_dir"]),
        required=ANALYSIS_REQUIRED_ARTIFACTS,
        optional=ANALYSIS_OPTIONAL_ARTIFACTS,
    )
    read_only = _load_payload(Path(state["analysis_dir"]) / "read_only_verification.json", result.blockers)
    if isinstance(read_only, dict) and read_only.get("source_modified") is not False:
        result.blockers.append("read_only_verification.json source_modified must be false")
    return _finish(result)


def validate_planning_artifacts(state: MigrationState) -> ArtifactValidationResult:
    return _validate_artifacts(
        Path(state["planning_dir"]),
        required=PLANNING_REQUIRED_ARTIFACTS,
        optional=(),
    )


def validate_assessment_artifacts(state: MigrationState) -> ArtifactValidationResult:
    result = _validate_artifacts(
        Path(state["assessment_dir"]),
        required=ASSESSMENT_REQUIRED_ARTIFACTS,
        optional=(),
    )
    report = _load_payload(Path(state["assessment_dir"]) / "assessment_report.json", result.blockers)
    if isinstance(report, dict):
        readiness = report.get("approval_readiness")
        readiness_status = readiness.get("status") if isinstance(readiness, dict) else readiness
        if readiness_status != "READY_FOR_REVIEW":
            result.blockers.append("assessment_report.json approval_readiness must be READY_FOR_REVIEW")

        claims = report.get("execution_claims")
        if isinstance(claims, dict):
            for claim in ASSESSMENT_EXECUTION_CLAIMS:
                if claims.get(claim) is True:
                    result.blockers.append(f"assessment_report.json execution claim {claim} must be false")
    return _finish(result)


def _validate_artifacts(
    directory: Path,
    *,
    required: tuple[str, ...],
    optional: tuple[str, ...],
) -> ArtifactValidationResult:
    artifact_refs: dict[str, str] = {}
    blockers: list[str] = []
    warnings: list[str] = []

    for artifact in required:
        path = directory / artifact
        if not path.exists():
            blockers.append(f"Missing required artifact: {artifact}")
            continue
        artifact_refs[artifact] = str(path)
        _validate_schema_backed_artifact(artifact, path, blockers)

    for artifact in optional:
        path = directory / artifact
        if path.exists():
            artifact_refs[artifact] = str(path)
            _validate_schema_backed_artifact(artifact, path, blockers)

    return ArtifactValidationResult(
        valid=not blockers,
        artifact_refs=artifact_refs,
        blockers=blockers,
        warnings=warnings,
    )


def _validate_schema_backed_artifact(artifact: str, path: Path, blockers: list[str]) -> None:
    schema_name = SCHEMA_BACKED_ARTIFACTS.get(artifact)
    if not schema_name:
        return

    payload = _load_payload(path, blockers)
    if payload is None:
        return
    for error in validate_against_schema(payload, schema_name):
        blockers.append(f"Invalid artifact schema for {artifact}: {error}")


def _load_payload(path: Path, blockers: list[str]) -> Any:
    if not path.exists():
        return None
    try:
        if path.suffix in {".yaml", ".yml"}:
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        blockers.append(f"Unable to read artifact {path.name}: {exc}")
        return None


def _finish(result: ArtifactValidationResult) -> ArtifactValidationResult:
    return ArtifactValidationResult(
        valid=not result.blockers,
        artifact_refs=result.artifact_refs,
        blockers=result.blockers,
        warnings=result.warnings,
    )
