"""V2 setup persistence and preflight readiness service.

This module provides the application service for creating migration
setup drafts, computing preflight readiness, and checking setup
checksum gating for job creation.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.redaction import (
    redact_absolute_paths,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2MigrationSetupRecord,
    V2PreflightResultRecord,
)


# ── Data types ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class CreateSetupRequest:
    run_name: str
    legacy_app_path: str
    output_parent_path: str
    ai_hub_path: str
    java11_home: str
    java17_home: str
    java21_home: str
    maven_cmd: str
    proof_level: str = "build_test_verified"
    skip_endpoint_smoke: bool = False
    migration_flags: dict[str, Any] = field(default_factory=dict)
    created_by: str = "operator"
    correlation_id: str | None = None


@dataclass(frozen=True)
class SetupDto:
    setup_id: str
    run_name: str
    legacy_app_path: str
    output_parent_path: str
    ai_hub_path: str
    java_homes: dict[str, str]
    maven_cmd: str
    proof_level: str
    skip_endpoint_smoke: bool
    migration_flags: dict[str, Any]
    setup_checksum: str
    created_at: str


@dataclass(frozen=True)
class PreflightDto:
    preflight_id: str
    setup_id: str
    setup_checksum: str
    all_ready: bool
    legacy_app_exists: bool
    legacy_app_has_project_file: bool
    legacy_app_not_in_output_parent: bool
    output_parent_writable: bool
    ai_hub_root_exists: bool
    ai_hub_profiles_ready: bool
    ai_hub_catalogs_ready: bool
    ai_hub_policies_ready: bool
    jdk11_ready: bool
    jdk17_ready: bool
    jdk21_ready: bool
    maven_ready: bool
    pipeline_route_ready: bool
    legacy_marker_ready: bool
    output_parent_gate_ready: bool
    readiness: dict[str, Any]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    checked_at: str


@dataclass(frozen=True)
class PreflightReadiness:
    """Aggregate deterministic readiness from a preflight result."""
    all_ready: bool
    setup_checksum: str
    preflight_checksum_match: bool
    gates: dict[str, bool]


# ── Setup checksum computation ───────────────────────────────────────


def compute_setup_checksum(request: CreateSetupRequest) -> str:
    """Compute a deterministic SHA-256 checksum of setup fields."""
    payload = {
        "run_name": request.run_name,
        "legacy_app_path": request.legacy_app_path,
        "output_parent_path": request.output_parent_path,
        "ai_hub_path": request.ai_hub_path,
        "java11_home": request.java11_home,
        "java17_home": request.java17_home,
        "java21_home": request.java21_home,
        "maven_cmd": request.maven_cmd,
        "proof_level": request.proof_level,
        "skip_endpoint_smoke": request.skip_endpoint_smoke,
        "migration_flags": request.migration_flags,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Setup service ────────────────────────────────────────────────────


class V2SetupService:
    """Application service for V2 migration setup drafts."""

    def __init__(self, repo: SqliteV2SetupRepository) -> None:
        self._repo = repo

    def create_setup(self, request: CreateSetupRequest) -> SetupDto:
        """Create a new migration setup draft."""
        setup_id = uuid4().hex
        checksum = compute_setup_checksum(request)
        now = utc_now_text()
        flags_json = json.dumps(request.migration_flags, separators=(",", ":"))

        record = V2MigrationSetupRecord(
            setup_id=setup_id,
            run_name=request.run_name,
            legacy_app_path=request.legacy_app_path,
            output_parent_path=request.output_parent_path,
            ai_hub_path=request.ai_hub_path,
            java11_home=request.java11_home,
            java17_home=request.java17_home,
            java21_home=request.java21_home,
            maven_cmd=request.maven_cmd,
            proof_level=request.proof_level,
            skip_endpoint_smoke=request.skip_endpoint_smoke,
            migration_flags_json=flags_json,
            setup_checksum=checksum,
            checksum_algorithm="sha256",
            created_at=now,
            created_by=request.created_by,
            correlation_id=request.correlation_id,
        )
        self._repo.save(record)
        return self._record_to_dto(record)

    def get_setup(self, setup_id: str) -> SetupDto | None:
        record = self._repo.get(setup_id)
        if record is None:
            return None
        return self._record_to_dto(record)

    def list_setups(self) -> tuple[SetupDto, ...]:
        return tuple(self._record_to_dto(r) for r in self._repo.list())

    def run_preflight(self, setup_id: str, checked_by: str = "system") -> PreflightDto:
        """Run preflight readiness checks for a setup."""
        record = self._repo.get(setup_id)
        if record is None:
            raise ValueError(f"Setup {setup_id!r} not found")

        readiness, warnings, errors = self._compute_readiness(record)

        all_ready = all(
            v for k, v in readiness.items()
            if k not in ("azure_model_ready",)
        )

        preflight_id = uuid4().hex
        now = utc_now_text()

        preflight = V2PreflightResultRecord(
            preflight_id=preflight_id,
            setup_id=setup_id,
            setup_checksum=record.setup_checksum,
            all_ready=all_ready,
            legacy_app_exists=readiness.get("legacy_app_exists", False),
            legacy_app_has_project_file=readiness.get("legacy_app_has_project_file", False),
            legacy_app_not_in_output_parent=readiness.get("legacy_app_not_in_output_parent", False),
            output_parent_writable=readiness.get("output_parent_writable", False),
            ai_hub_root_exists=readiness.get("ai_hub_root_exists", False),
            ai_hub_profiles_ready=readiness.get("ai_hub_profiles_ready", False),
            ai_hub_catalogs_ready=readiness.get("ai_hub_catalogs_ready", False),
            ai_hub_policies_ready=readiness.get("ai_hub_policies_ready", False),
            jdk11_ready=readiness.get("jdk11_ready", False),
            jdk17_ready=readiness.get("jdk17_ready", False),
            jdk21_ready=readiness.get("jdk21_ready", False),
            maven_ready=readiness.get("maven_ready", False),
            pipeline_route_ready=readiness.get("pipeline_route_ready", True),
            legacy_marker_ready=readiness.get("legacy_marker_ready", True),
            output_parent_gate_ready=readiness.get("output_parent_gate_ready", True),
            readiness_json=json.dumps(readiness, separators=(",", ":")),
            warnings_json=json.dumps(list(warnings), separators=(",", ":")),
            errors_json=json.dumps(list(errors), separators=(",", ":")),
            checked_at=now,
            checked_by=checked_by,
            correlation_id=record.correlation_id,
        )
        self._repo.save_preflight(preflight)

        return PreflightDto(
            preflight_id=preflight_id,
            setup_id=setup_id,
            setup_checksum=record.setup_checksum,
            all_ready=all_ready,
            legacy_app_exists=readiness.get("legacy_app_exists", False),
            legacy_app_has_project_file=readiness.get("legacy_app_has_project_file", False),
            legacy_app_not_in_output_parent=readiness.get("legacy_app_not_in_output_parent", False),
            output_parent_writable=readiness.get("output_parent_writable", False),
            ai_hub_root_exists=readiness.get("ai_hub_root_exists", False),
            ai_hub_profiles_ready=readiness.get("ai_hub_profiles_ready", False),
            ai_hub_catalogs_ready=readiness.get("ai_hub_catalogs_ready", False),
            ai_hub_policies_ready=readiness.get("ai_hub_policies_ready", False),
            jdk11_ready=readiness.get("jdk11_ready", False),
            jdk17_ready=readiness.get("jdk17_ready", False),
            jdk21_ready=readiness.get("jdk21_ready", False),
            maven_ready=readiness.get("maven_ready", False),
            pipeline_route_ready=readiness.get("pipeline_route_ready", True),
            legacy_marker_ready=readiness.get("legacy_marker_ready", True),
            output_parent_gate_ready=readiness.get("output_parent_gate_ready", True),
            readiness=readiness,
            warnings=tuple(warnings),
            errors=tuple(errors),
            checked_at=now,
        )

    def get_readiness(self, setup_id: str) -> PreflightReadiness | None:
        """Get the latest preflight readiness for a setup."""
        preflight = self._repo.get_latest_preflight(setup_id)
        if preflight is None:
            return None

        setup = self._repo.get(setup_id)
        checksum_matches = setup is not None and setup.setup_checksum == preflight.setup_checksum

        try:
            gates = json.loads(preflight.readiness_json)
        except (json.JSONDecodeError, TypeError):
            gates = {}

        return PreflightReadiness(
            all_ready=preflight.all_ready,
            setup_checksum=preflight.setup_checksum,
            preflight_checksum_match=checksum_matches,
            gates={k: bool(v) for k, v in gates.items()},
        )

    def get_readiness_by_checksum(self, checksum: str) -> PreflightReadiness | None:
        """Get the latest preflight readiness for a setup checksum."""
        preflight = self._repo.get_latest_preflight_by_checksum(checksum)
        if preflight is None:
            return None

        setup = self._repo.get_by_checksum(checksum)
        checksum_matches = setup is not None and setup.setup_checksum == preflight.setup_checksum

        try:
            gates = json.loads(preflight.readiness_json)
        except (json.JSONDecodeError, TypeError):
            gates = {}

        return PreflightReadiness(
            all_ready=preflight.all_ready,
            setup_checksum=preflight.setup_checksum,
            preflight_checksum_match=checksum_matches,
            gates={k: bool(v) for k, v in gates.items()},
        )

    # ── DTO converters ───────────────────────────────────────────

    def setup_to_dict(self, dto: SetupDto) -> dict[str, Any]:
        return {
            "setup_id": dto.setup_id,
            "run_name": dto.run_name,
            "legacy_app_path": redact_absolute_paths(dto.legacy_app_path),
            "output_parent_path": redact_absolute_paths(dto.output_parent_path),
            "ai_hub_path": redact_absolute_paths(dto.ai_hub_path),
            "java_homes": dto.java_homes,
            "maven_cmd": redact_absolute_paths(dto.maven_cmd),
            "proof_level": dto.proof_level,
            "skip_endpoint_smoke": dto.skip_endpoint_smoke,
            "migration_flags": dto.migration_flags,
            "setup_checksum": dto.setup_checksum,
            "created_at": dto.created_at,
        }

    def preflight_to_dict(self, dto: PreflightDto) -> dict[str, Any]:
        return {
            "preflight_id": dto.preflight_id,
            "setup_id": dto.setup_id,
            "setup_checksum": dto.setup_checksum,
            "all_ready": dto.all_ready,
            "legacy_app_exists": dto.legacy_app_exists,
            "legacy_app_has_project_file": dto.legacy_app_has_project_file,
            "legacy_app_not_in_output_parent": dto.legacy_app_not_in_output_parent,
            "output_parent_writable": dto.output_parent_writable,
            "ai_hub_root_exists": dto.ai_hub_root_exists,
            "ai_hub_profiles_ready": dto.ai_hub_profiles_ready,
            "ai_hub_catalogs_ready": dto.ai_hub_catalogs_ready,
            "ai_hub_policies_ready": dto.ai_hub_policies_ready,
            "jdk11_ready": dto.jdk11_ready,
            "jdk17_ready": dto.jdk17_ready,
            "jdk21_ready": dto.jdk21_ready,
            "maven_ready": dto.maven_ready,
            "pipeline_route_ready": dto.pipeline_route_ready,
            "legacy_marker_ready": dto.legacy_marker_ready,
            "output_parent_gate_ready": dto.output_parent_gate_ready,
            "readiness": dto.readiness,
            "warnings": list(dto.warnings),
            "errors": list(dto.errors),
            "checked_at": dto.checked_at,
        }

    def readiness_to_dict(self, readiness: PreflightReadiness | None) -> dict[str, Any]:
        if readiness is None:
            return {"ready": False, "setup_checksum": "", "preflight_checksum_match": False, "gates": {}}
        return {
            "ready": readiness.all_ready,
            "setup_checksum": readiness.setup_checksum,
            "preflight_checksum_match": readiness.preflight_checksum_match,
            "gates": readiness.gates,
        }

    # ── Internal ─────────────────────────────────────────────────

    def _compute_readiness(
        self,
        record: V2MigrationSetupRecord,
    ) -> tuple[dict[str, bool], list[str], list[str]]:
        """Compute deterministic readiness checks.

        In the current version, these are simulated checks that verify
        path existence and structure. Real subprocess checks (JDK version,
        Maven version) are added by A4/A7.
        """
        readiness: dict[str, bool] = {}
        warnings: list[str] = []
        errors: list[str] = []

        # Legacy app path
        legacy = Path(record.legacy_app_path)
        legacy_exists = legacy.exists()
        readiness["legacy_app_exists"] = legacy_exists
        if not legacy_exists:
            errors.append(f"Legacy app path does not exist: {record.legacy_app_path}")

        # Legacy app has pom.xml
        has_pom = legacy_exists and (legacy / "pom.xml").exists()
        has_gradle = legacy_exists and (legacy / "build.gradle").exists()
        has_project = has_pom or has_gradle
        readiness["legacy_app_has_project_file"] = has_project
        if not has_project and legacy_exists:
            warnings.append("No pom.xml or build.gradle found in legacy app path")

        # Legacy not inside output parent
        output = Path(record.output_parent_path)
        try:
            not_in_output = not str(legacy.resolve()).startswith(str(output.resolve()))
        except (ValueError, OSError):
            not_in_output = True
        readiness["legacy_app_not_in_output_parent"] = not_in_output
        if not not_in_output:
            errors.append("Legacy app path is inside output parent path")

        # Output parent writable
        output_parent_writable = True
        try:
            if not output.exists():
                output.mkdir(parents=True, exist_ok=True)
            output_parent_writable = output.exists() and os.access(str(output), os.W_OK)
        except (OSError, PermissionError):
            output_parent_writable = False
        readiness["output_parent_writable"] = output_parent_writable
        if not output_parent_writable:
            errors.append("Output parent path is not writable")

        # AI Hub
        hub = Path(record.ai_hub_path)
        hub_exists = hub.exists()
        readiness["ai_hub_root_exists"] = hub_exists
        if not hub_exists:
            warnings.append(f"AI Hub path does not exist: {record.ai_hub_path}")

        # Check AI Hub profiles
        profiles_ready = hub_exists and _check_ai_hub_profiles(hub)
        readiness["ai_hub_profiles_ready"] = profiles_ready
        if not profiles_ready and hub_exists:
            warnings.append("AI Hub profiles not complete")

        catalogs_ready = hub_exists and _check_ai_hub_catalogs(hub)
        readiness["ai_hub_catalogs_ready"] = catalogs_ready
        if not catalogs_ready and hub_exists:
            warnings.append("AI Hub catalogs not complete")

        policies_ready = hub_exists and _check_ai_hub_policies(hub)
        readiness["ai_hub_policies_ready"] = policies_ready
        if not policies_ready and hub_exists:
            warnings.append("AI Hub policies not complete")

        # JDK checks (simulated for now)
        readiness["jdk11_ready"] = _check_jdk_path(record.java11_home)
        readiness["jdk17_ready"] = _check_jdk_path(record.java17_home)
        readiness["jdk21_ready"] = _check_jdk_path(record.java21_home)

        if not readiness["jdk11_ready"]:
            errors.append(f"JAVA11_HOME path does not exist: {record.java11_home}")
        if not readiness["jdk17_ready"]:
            errors.append(f"JAVA17_HOME path does not exist: {record.java17_home}")
        if not readiness["jdk21_ready"]:
            errors.append(f"JAVA21_HOME path does not exist: {record.java21_home}")

        # Maven check (simulated for now)
        maven_ready = _check_maven_path(record.maven_cmd)
        readiness["maven_ready"] = maven_ready
        if not maven_ready:
            errors.append(f"Maven command path does not exist: {record.maven_cmd}")

        # Pipeline route (always ready for V2)
        readiness["pipeline_route_ready"] = True

        # Legacy marker (always ready for V2)
        readiness["legacy_marker_ready"] = True

        # Output parent gate
        readiness["output_parent_gate_ready"] = output_parent_writable

        # Azure model readiness is NOT a deterministic gate
        readiness["azure_model_ready"] = True  # Not blocking

        return readiness, warnings, errors

    def _record_to_dto(self, record: V2MigrationSetupRecord) -> SetupDto:
        try:
            flags = json.loads(record.migration_flags_json)
        except (json.JSONDecodeError, TypeError):
            flags = {}
        return SetupDto(
            setup_id=record.setup_id,
            run_name=record.run_name,
            legacy_app_path=record.legacy_app_path,
            output_parent_path=record.output_parent_path,
            ai_hub_path=record.ai_hub_path,
            java_homes={
                "java11": record.java11_home,
                "java17": record.java17_home,
                "java21": record.java21_home,
            },
            maven_cmd=record.maven_cmd,
            proof_level=record.proof_level,
            skip_endpoint_smoke=record.skip_endpoint_smoke,
            migration_flags=flags,
            setup_checksum=record.setup_checksum,
            created_at=record.created_at,
        )


# ── Internal helpers ────────────────────────────────────────────────


def _check_jdk_path(path: str) -> bool:
    """Check if a JDK home path exists."""
    return Path(path).exists()


def _check_maven_path(path: str) -> bool:
    """Check if a Maven command path exists."""
    return Path(path).exists()


def _check_ai_hub_profiles(hub: Path) -> bool:
    """Check for required AI Hub profiles."""
    profiles_dir = hub / "profiles"
    if not profiles_dir.exists():
        return False
    required = [
        "springboot-2.1.6-to-2.7-java11",
        "springboot-2.7-to-3.5-java17",
        "springboot-3.5-java17-to-java21",
    ]
    return any(p.name in required for p in profiles_dir.iterdir()) if profiles_dir.is_dir() else False


def _check_ai_hub_catalogs(hub: Path) -> bool:
    """Check for required AI Hub catalogs."""
    catalogs_dir = hub / "catalogs"
    if not catalogs_dir.exists():
        return False
    required = [
        "springboot-2.1.6-to-2.7-java11.yaml",
        "springboot-2.7-to-3.5-java17.yaml",
        "springboot-3.5-java17-to-java21.yaml",
    ]
    existing = [c.name for c in catalogs_dir.iterdir()] if catalogs_dir.is_dir() else []
    return all(req in existing for req in required)


def _check_ai_hub_policies(hub: Path) -> bool:
    """Check for required AI Hub policies."""
    policies_dir = hub / "policies"
    if not policies_dir.exists():
        return False
    required = ["planning", "safety", "transformation"]
    existing = [p.name for p in policies_dir.iterdir()] if policies_dir.is_dir() else []
    return any(req in existing for req in required)
