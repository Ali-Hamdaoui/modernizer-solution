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
from migration_factory.control_tower.domain.checksums import (
    canonical_json_text,
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import RunConfigurationRecord
from migration_factory.control_tower.domain.errors import StorageIntegrityError
from migration_factory.control_tower.domain.states import TargetProofLevel
from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqlitePipelineDefinitionRepository,
    SqliteRunConfigurationRepository,
    SqliteRunnerProfileRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
    V2MigrationJobRecord,
)
from migration_factory.control_tower.schemas.run_configuration import (
    RunConfiguration,
    RunPolicy,
    StageContinuationPolicy,
)


STAGE_INPUTS = {
    1: {"pipeline_stage": "Stage 1", "input_kind": "legacy_source"},
    2: {"pipeline_stage": "Stage 2", "input_kind": "stage_1_sandbox"},
    3: {"pipeline_stage": "Stage 3", "input_kind": "stage_2_sandbox"},
    4: {"pipeline_stage": "Stage 4", "input_kind": "stage_3_sandbox"},
}

PIPELINE_ID = "springboot-216-to-400-java21-four-stage"


@dataclass(frozen=True)
class V2MigrationJobResult:
    job_id: str
    setup_id: str
    setup_checksum: str
    pipeline_id: str
    stages: tuple[dict[str, Any], ...]
    created_at: str
    stage_continuation_policy: str = StageContinuationPolicy.AUTO_ON_GREEN.value
    run_configuration_id: str = ""


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
        run_config_repo: SqliteRunConfigurationRepository | None = None,
        runner_profile_repo: SqliteRunnerProfileRepository | None = None,
        pipeline_repo: SqlitePipelineDefinitionRepository | None = None,
    ) -> None:
        self._setup_service = V2SetupService(setup_repo)
        self._job_repo = job_repo
        self._run_config_repo = run_config_repo
        self._runner_profile_repo = runner_profile_repo
        self._pipeline_repo = pipeline_repo

    def create_job(self, setup_id: str, policy: RunPolicy | None = None) -> V2MigrationJobResult:
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
        effective_policy = policy if policy is not None else RunPolicy.f15_manual()

        stages = []
        for idx in (1, 2, 3, 4):
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
        run_configuration_id = f"run-config-{job_id}"
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

        if self._run_config_repo is not None:
            run_config_payload = RunConfiguration(
                schema_version="1.0.0",
                run_configuration_id=run_configuration_id,
                job_id=job_id,
                runner_profile_id="runner-default",
                runner_profile_version="2026.06",
                pipeline_id=PIPELINE_ID,
                pipeline_version="2026.06",
                target_proof_level=TargetProofLevel.BUILD_TEST_VERIFIED,
                enabled_gates=(),
                policy=effective_policy,
            )
            run_config_payload_json = canonical_json_text(run_config_payload)
            run_config_checksum = sha256_canonical_json(run_config_payload)

            run_config_record = RunConfigurationRecord(
                run_configuration_id=run_configuration_id,
                job_id=job_id,
                schema_version=run_config_payload.schema_version,
                runner_profile_id=run_config_payload.runner_profile_id,
                runner_profile_version=run_config_payload.runner_profile_version,
                pipeline_id=run_config_payload.pipeline_id,
                pipeline_version=run_config_payload.pipeline_version,
                target_proof_level=run_config_payload.target_proof_level,
                enabled_gates_json=canonical_json_text(run_config_payload.enabled_gates),
                policy_json=canonical_json_text(run_config_payload.policy),
                payload_json=run_config_payload_json,
                payload_checksum=run_config_checksum,
                created_at=now,
            )
            self._validate_run_configuration_dependencies(run_config_payload)
            try:
                self._run_config_repo.insert(run_config_record)
            except StorageIntegrityError as exc:
                raise ValueError(
                    "V2 run configuration could not be persisted because the required "
                    "runner profile or pipeline definition seed is missing."
                ) from exc

        return V2MigrationJobResult(
            job_id=job_id,
            setup_id=setup_id,
            setup_checksum=setup.setup_checksum,
            pipeline_id=PIPELINE_ID,
            stages=tuple(stages),
            created_at=now,
            stage_continuation_policy=effective_policy.stage_continuation_policy.value,
            run_configuration_id=run_configuration_id,
        )

    def _validate_run_configuration_dependencies(self, run_config: RunConfiguration) -> None:
        if self._runner_profile_repo is not None:
            runner_profile = self._runner_profile_repo.get_exact(
                run_config.runner_profile_id,
                run_config.runner_profile_version,
            )
            if runner_profile is None:
                raise ValueError(
                    "Required runner profile "
                    f"{run_config.runner_profile_id!r} version "
                    f"{run_config.runner_profile_version!r} is missing."
                )

        if self._pipeline_repo is not None:
            pipeline = self._pipeline_repo.get_exact(
                run_config.pipeline_id,
                run_config.pipeline_version,
            )
            if pipeline is None:
                raise ValueError(
                    "Required pipeline definition "
                    f"{run_config.pipeline_id!r} version "
                    f"{run_config.pipeline_version!r} is missing."
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
        policy_value = StageContinuationPolicy.AUTO_ON_GREEN.value
        run_cfg_id = ""
        if self._run_config_repo is not None:
            run_config = self._run_config_repo.get_for_job(job_id)
            if run_config is not None and run_config.policy_json:
                try:
                    policy_dict = json.loads(run_config.policy_json)
                    policy = RunPolicy(**policy_dict)
                    policy_value = policy.stage_continuation_policy.value
                    run_cfg_id = run_config.run_configuration_id
                except (json.JSONDecodeError, Exception):
                    pass
        return V2MigrationJobResult(
            job_id=record.job_id,
            setup_id=record.setup_id,
            setup_checksum=record.setup_checksum,
            pipeline_id=record.pipeline_id,
            stages=tuple(stages),
            created_at=record.created_at,
            stage_continuation_policy=policy_value,
            run_configuration_id=run_cfg_id,
        )

    def list_jobs(self) -> tuple[V2MigrationJobResult, ...]:
        """List all persisted jobs with actual stage_continuation_policy."""
        if self._job_repo is None:
            return ()
        records = self._job_repo.list()
        results = []
        for r in records:
            try:
                stages = json.loads(r.stage_chain_json)
            except (json.JSONDecodeError, TypeError):
                stages = []
            # Look up run_configuration for actual stage_continuation_policy
            policy = StageContinuationPolicy.AUTO_ON_GREEN.value
            run_config_id = ""
            if self._run_config_repo is not None:
                try:
                    rc = self._run_config_repo.get_for_job(r.job_id)
                    if rc is not None:
                        run_config_id = rc.run_configuration_id
                        rc_payload = json.loads(rc.payload_json)
                        policy = rc_payload.get(
                            "stage_continuation_policy",
                            StageContinuationPolicy.AUTO_ON_GREEN.value,
                        )
                except (json.JSONDecodeError, TypeError, Exception):
                    pass
            results.append(V2MigrationJobResult(
                job_id=r.job_id,
                setup_id=r.setup_id,
                setup_checksum=r.setup_checksum,
                pipeline_id=r.pipeline_id,
                stages=tuple(stages),
                created_at=r.created_at,
                stage_continuation_policy=policy,
                run_configuration_id=run_config_id,
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
            "stage_continuation_policy": result.stage_continuation_policy,
            "run_configuration_id": result.run_configuration_id,
        }
