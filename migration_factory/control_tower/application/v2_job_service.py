"""V2 migration job creation from ready setup."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.v2_setup_service import (
    is_ai_smoke_required,
    V2SetupService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
    V2MigrationJobRecord,
)


STAGE_INPUTS = {
    1: {"pipeline_stage": "Stage 1", "input_kind": "legacy_source"},
    2: {"pipeline_stage": "Stage 2", "input_kind": "stage_1_sandbox"},
    3: {"pipeline_stage": "Stage 3", "input_kind": "stage_2_sandbox"},
}

PIPELINE_ID = "springboot-216-to-356-java21-three-stage"


@dataclass(frozen=True)
class V2MigrationJobResult:
    job_id: str
    setup_id: str
    setup_checksum: str
    pipeline_id: str
    stages: tuple[dict[str, Any], ...]
    created_at: str


class V2MigrationJobService:
    """Create V2 parent migration jobs from ready setup snapshots.

    Requires:
    - Setup exists
    - Latest preflight for setup is READY (all_ready = True)
    - Preflight checksum matches current setup checksum
    """

    def __init__(
        self,
        setup_repo: SqliteV2SetupRepository,
        job_repo: SqliteV2JobRepository | None = None,
    ) -> None:
        self._setup_service = V2SetupService(setup_repo)
        self._job_repo = job_repo

    def create_job(self, setup_id: str) -> V2MigrationJobResult:
        """Create a V2 parent migration job from a ready setup.

        Validates that the setup exists, has a current preflight with
        all_ready=True, and the checksum matches.
        """
        setup = self._setup_service.get_setup(setup_id)
        if setup is None:
            raise ValueError(f"Setup {setup_id!r} not found")

        readiness = self._setup_service.get_readiness(setup_id)
        if readiness is None:
            raise ValueError(f"No preflight for setup {setup_id!r}. Run preflight first.")

        if not readiness.preflight_checksum_match:
            raise ValueError(
                f"Preflight checksum mismatch for setup {setup_id!r}. "
                f"Expected {setup.setup_checksum}, got {readiness.setup_checksum}. "
                "Run preflight again."
            )

        if not readiness.all_ready:
            blocked = [
                k
                for k, v in readiness.gates.items()
                if not v and (k != "azure_model_ready" or is_ai_smoke_required(setup.skip_endpoint_smoke))
            ]
            raise ValueError(
                f"Setup {setup_id!r} is not ready. Blocked gates: {blocked}"
            )

        # Create job
        job_id = uuid4().hex
        now = utc_now_text()

        stages = []
        for idx in (1, 2, 3):
            stage_info = STAGE_INPUTS[idx]
            stages.append({
                "stage_index": idx,
                "stage_run_id": uuid4().hex,
                "pipeline_stage": stage_info["pipeline_stage"],
                "input_source_kind": stage_info["input_kind"],
                "setup_checksum": setup.setup_checksum,
                "chain_status": "queued" if idx == 1 else "pending",
            })

        # Persist to database
        if self._job_repo is not None:
            record = V2MigrationJobRecord(
                job_id=job_id,
                setup_id=setup_id,
                setup_checksum=setup.setup_checksum,
                pipeline_id=PIPELINE_ID,
                stage_chain_json=json.dumps(stages, separators=(",", ":")),
                status="created",
                created_at=now,
                updated_at=now,
                correlation_id=setup.setup_id,
            )
            self._job_repo.save(record)

        return V2MigrationJobResult(
            job_id=job_id,
            setup_id=setup_id,
            setup_checksum=setup.setup_checksum,
            pipeline_id=PIPELINE_ID,
            stages=tuple(stages),
            created_at=now,
        )

    def get_job(self, job_id: str) -> V2MigrationJobResult | None:
        """Retrieve a persisted job by ID."""
        if self._job_repo is None:
            return None
        record = self._job_repo.get(job_id)
        if record is None:
            return None
        try:
            stages = json.loads(record.stage_chain_json)
        except (json.JSONDecodeError, TypeError):
            stages = []
        return V2MigrationJobResult(
            job_id=record.job_id,
            setup_id=record.setup_id,
            setup_checksum=record.setup_checksum,
            pipeline_id=record.pipeline_id,
            stages=tuple(stages),
            created_at=record.created_at,
        )

    def list_jobs(self) -> tuple[V2MigrationJobResult, ...]:
        """List all persisted jobs."""
        if self._job_repo is None:
            return ()
        records = self._job_repo.list()
        results = []
        for r in records:
            try:
                stages = json.loads(r.stage_chain_json)
            except (json.JSONDecodeError, TypeError):
                stages = []
            results.append(V2MigrationJobResult(
                job_id=r.job_id,
                setup_id=r.setup_id,
                setup_checksum=r.setup_checksum,
                pipeline_id=r.pipeline_id,
                stages=tuple(stages),
                created_at=r.created_at,
            ))
        return tuple(results)

    def result_to_dict(self, result: V2MigrationJobResult) -> dict[str, Any]:
        return {
            "job_id": result.job_id,
            "setup_id": result.setup_id,
            "setup_checksum": result.setup_checksum,
            "pipeline_id": result.pipeline_id,
            "stages": [
                {
                    "stage_index": s["stage_index"],
                    "stage_run_id": s["stage_run_id"],
                    "pipeline_stage": s["pipeline_stage"],
                    "input_source_kind": s["input_source_kind"],
                    "chain_status": s["chain_status"],
                }
                for s in result.stages
            ],
            "created_at": result.created_at,
        }
