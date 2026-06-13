"""V2 worker stage execution — backend-owned Stage 1 command manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2MigrationSetupRecord,
)


STAGE_JDK_MAP = {
    1: {"jdk_id": "java11", "env_var": "JAVA11_HOME", "expected_major": 11},
    2: {"jdk_id": "java17", "env_var": "JAVA17_HOME", "expected_major": 17},
    3: {"jdk_id": "java21", "env_var": "JAVA21_HOME", "expected_major": 21},
}

PIPELINE_ID = "springboot-216-to-356-java21-three-stage"
RUNNER_MODULE = "migration_factory.orchestrator.runner"
RESUME_MODULE = "migration_factory.orchestrator.resume"


@dataclass(frozen=True)
class V2StageCommandResult:
    command_id: str
    job_id: str
    stage_index: int
    manifest_checksum: str
    argv: tuple[str, ...]
    created_at: str


class V2WorkerStageService:
    """Build Stage 1 command manifests from V2 setup data.

    The manifest argv/env are always backend-owned. Browser payloads
    cannot supply argv or env values.
    """

    def __init__(self, setup_repo: SqliteV2SetupRepository) -> None:
        self._setup_repo = setup_repo

    def build_stage1_manifest(
        self,
        job_id: str,
        setup_id: str,
        run_id: str | None = None,
    ) -> V2StageCommandResult:
        """Build a Stage 1 command manifest from a V2 setup.

        Does NOT start any process. Only builds and persists the manifest.
        """
        setup = self._setup_repo.get(setup_id)
        if setup is None:
            raise ValueError(f"Setup {setup_id!r} not found")

        command_id = uuid4().hex
        now = utc_now_text()
        effective_run_id = run_id or f"v2-{job_id[:8]}"

        # Build backend-owned argv for Stage 1
        stage_info = STAGE_JDK_MAP[1]
        jdk_home = _get_jdk_home(setup, stage_info["env_var"])

        argv = (
            "python",
            "-m",
            RUNNER_MODULE,
            "--run-id", effective_run_id,
            "--legacy", setup.legacy_app_path,
            "--modernized", setup.output_parent_path,
            "--ai-hub", setup.ai_hub_path,
            "--profile", "springboot-2.1.6-to-2.7-java11",
            "--mode", "full_sandbox_migration",
        )

        return V2StageCommandResult(
            command_id=command_id,
            job_id=job_id,
            stage_index=1,
            manifest_checksum="v2-stage1",  # Simplified for now
            argv=argv,
            created_at=now,
        )

    def result_to_dict(self, result: V2StageCommandResult) -> dict[str, Any]:
        return {
            "command_id": result.command_id,
            "job_id": result.job_id,
            "stage_index": result.stage_index,
            "manifest_checksum": result.manifest_checksum,
            "argv": list(result.argv),
            "created_at": result.created_at,
        }


def _get_jdk_home(setup: V2MigrationSetupRecord, env_var: str) -> str:
    mapping = {
        "JAVA11_HOME": setup.java11_home,
        "JAVA17_HOME": setup.java17_home,
        "JAVA21_HOME": setup.java21_home,
    }
    return mapping.get(env_var, "")
