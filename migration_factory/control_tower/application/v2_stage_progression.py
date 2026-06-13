"""V2 stage auto-progression — Stage 2/3 from previous sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2MigrationSetupRecord,
)


STAGE_CONFIG = {
    2: {
        "profile": "springboot-2.7-to-3.5-java17",
        "jdk_env": "JAVA17_HOME",
        "jdk_id": "java17",
        "expected_major": 17,
    },
    3: {
        "profile": "springboot-3.5-java17-to-java21",
        "jdk_env": "JAVA21_HOME",
        "jdk_id": "java21",
        "expected_major": 21,
    },
}

RUNNER_MODULE = "migration_factory.orchestrator.runner"


@dataclass(frozen=True)
class StageContinuationResult:
    continuation_id: str
    job_id: str
    from_stage: int
    to_stage: int
    sandbox_path: str
    argv: tuple[str, ...]
    status: str  # queued, blocked
    reason: str = ""


class V2StageProgressionService:
    """Auto-queue Stage 2 and Stage 3 from previous stage sandbox."""

    def __init__(self, setup_repo: SqliteV2SetupRepository) -> None:
        self._setup_repo = setup_repo

    def queue_next_stage(
        self,
        job_id: str,
        setup_id: str,
        current_stage: int,
        sandbox_path: str,
    ) -> StageContinuationResult:
        """Queue the next stage from the current stage sandbox.

        Args:
            job_id: The V2 job ID.
            setup_id: The setup ID to load paths from.
            current_stage: The completed stage (1 or 2).
            sandbox_path: The sandbox output path from the completed stage.

        Returns:
            StageContinuationResult with the next stage details.

        Raises:
            ValueError: If the stage cannot progress (invalid stage,
                        missing setup, sandbox path issues).
        """
        next_stage = current_stage + 1
        if next_stage not in STAGE_CONFIG:
            raise ValueError(
                f"Cannot progress from stage {current_stage}: "
                f"stage {next_stage} is not a valid target"
            )

        setup = self._setup_repo.get(setup_id)
        if setup is None:
            raise ValueError(f"Setup {setup_id!r} not found")

        config = STAGE_CONFIG[next_stage]

        # Build backend-owned argv for next stage
        argv = (
            "python",
            "-m",
            RUNNER_MODULE,
            "--run-id", f"v2-{job_id[:8]}-s{next_stage}",
            "--legacy", sandbox_path,
            "--modernized", setup.output_parent_path,
            "--ai-hub", setup.ai_hub_path,
            "--profile", config["profile"],
            "--mode", "full_sandbox_migration",
        )

        return StageContinuationResult(
            continuation_id=uuid4().hex,
            job_id=job_id,
            from_stage=current_stage,
            to_stage=next_stage,
            sandbox_path=sandbox_path,
            argv=argv,
            status="queued",
        )

    def continuation_to_dict(self, result: StageContinuationResult) -> dict[str, Any]:
        return {
            "continuation_id": result.continuation_id,
            "job_id": result.job_id,
            "from_stage": result.from_stage,
            "to_stage": result.to_stage,
            "sandbox_path": result.sandbox_path,
            "argv": list(result.argv),
            "status": result.status,
            "reason": result.reason,
        }
