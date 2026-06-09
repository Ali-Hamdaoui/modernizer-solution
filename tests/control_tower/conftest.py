from __future__ import annotations

from pathlib import Path

import pytest

from migration_factory.control_tower.application.commands import (
    CreateMigrationJobCommand,
    RegisterPipelineDefinitionCommand,
    RegisterRunnerProfileCommand,
)
from migration_factory.control_tower.application.services import ControlTowerCommandService
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.connection import connect_control_tower
from migration_factory.control_tower.infrastructure.sqlite.migrations import apply_pending_migrations
from migration_factory.control_tower.infrastructure.sqlite.unit_of_work import (
    SqliteControlTowerUnitOfWork,
)
from migration_factory.control_tower.schemas.pipeline_definition import PipelineDefinition
from migration_factory.control_tower.schemas.run_configuration import RunPolicy
from migration_factory.control_tower.schemas.runner_profile import RunnerProfile


@pytest.fixture
def control_tower_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "control_tower.sqlite3"
    connection = connect_control_tower(db_path)
    try:
        apply_pending_migrations(connection)
    finally:
        connection.close()
    return db_path


def make_service(db_path: Path) -> ControlTowerCommandService:
    connection = connect_control_tower(db_path)
    return ControlTowerCommandService(lambda: SqliteControlTowerUnitOfWork(connection))


def register_default_definitions(
    service: ControlTowerCommandService,
    *,
    runner: RunnerProfile | None = None,
    pipeline: PipelineDefinition | None = None,
) -> tuple[RunnerProfile, PipelineDefinition]:
    runner = runner or make_runner_profile()
    pipeline = pipeline or make_pipeline_definition()
    service.register_runner_profile(RegisterRunnerProfileCommand(actor="tester", profile=runner))
    service.register_pipeline_definition(
        RegisterPipelineDefinitionCommand(actor="tester", pipeline=pipeline)
    )
    return runner, pipeline


def make_create_command(**overrides) -> CreateMigrationJobCommand:
    values = {
        "actor": "tester",
        "legacy_source_ref": "source-root",
        "output_root_ref": "output-root",
        "runner_profile_id": "runner-default",
        "runner_profile_version": "2026.06",
        "pipeline_id": "pipeline-default",
        "pipeline_version": "2026.06",
        "target_proof_level": TargetProofLevel.BUILD_TEST_VERIFIED,
        "enabled_gates": ("build", "test"),
        "policy": RunPolicy(
            continue_after_warning=False,
            enable_runtime_gate=False,
            enable_endpoint_gate=False,
            allow_ai_assistance=True,
            allow_ai_repair=False,
        ),
        "correlation_id": "corr-1",
    }
    values.update(overrides)
    return CreateMigrationJobCommand(**values)


def make_runner_profile(*, jdk_ids: tuple[str, ...] = ("jdk-17",)) -> RunnerProfile:
    return RunnerProfile.model_validate(
        {
            "schema_version": "1.0.0",
            "runner_profile_id": "runner-default",
            "runner_profile_version": "2026.06",
            "display_name": "Default runner",
            "filesystem_roots": (
                {"root_id": "source-root", "kind": "source", "path": "C:/workspace/source"},
                {"root_id": "output-root", "kind": "output", "path": "C:/workspace/output"},
            ),
            "maven": {"maven_id": "maven-3.9"},
            "jdk_inventory": tuple(
                {
                    "jdk_id": jdk_id,
                    "java_home": f"C:/jdks/{jdk_id}",
                    "major_version": 17,
                }
                for jdk_id in jdk_ids
            ),
            "network_policy": {"allow_outbound": False},
            "ai_profiles": (),
        }
    )


def make_pipeline_definition(
    *,
    stage_ids: tuple[str, ...] = ("analyze", "transform"),
    command_jdk: str = "jdk-17",
) -> PipelineDefinition:
    stages = []
    for index, stage_id in enumerate(stage_ids, start=1):
        input_source = (
            {"kind": "legacy_source"}
            if index == 1
            else {"kind": "previous_stage", "previous_stage_index": index - 1}
        )
        stages.append(
            {
                "stage_index": index,
                "stage_id": stage_id,
                "display_name": stage_id.title(),
                "input_source": input_source,
                "command_jdk": command_jdk,
            }
        )
    return PipelineDefinition.model_validate(
        {
            "schema_version": "1.0.0",
            "pipeline_id": "pipeline-default",
            "pipeline_version": "2026.06",
            "display_name": "Default pipeline",
            "graph_version": "1.0",
            "graph_state_schema_version": "1.0",
            "stages": tuple(stages),
        }
    )
