"""V2 stage auto-progression — Stage 2/3 from previous sandbox."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
    V2MigrationSetupRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
    V2StageCommandRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_artifact_revision_repository import (
    SqliteArtifactRevisionRepository,
)
from migration_factory.control_tower.schemas.run_configuration import StageContinuationPolicy


TERMINAL_STAGE_INDEX = 4

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
    4: {
        "profile": "springboot-3.5-java21-to-4.0-java21",
        "jdk_env": "JAVA21_HOME",
        "jdk_id": "java21",
        "expected_major": 21,
    },
}

RUNNER_MODULE = "migration_factory.orchestrator.runner"


def is_terminal_stage(stage_index: int) -> bool:
    return stage_index == TERMINAL_STAGE_INDEX


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
    command_id: str | None = None


class V2StageProgressionService:
    """Auto-queue Stage 2 and Stage 3 from previous stage sandbox."""

    def __init__(
        self,
        setup_repo: SqliteV2SetupRepository,
        command_repo: SqliteV2CommandRepository | None = None,
        artifact_revision_repo: SqliteArtifactRevisionRepository | None = None,
    ) -> None:
        self._setup_repo = setup_repo
        self._command_repo = command_repo
        self._artifact_revision_repo = artifact_revision_repo

    def queue_next_stage(
        self,
        job_id: str,
        setup_id: str,
        current_stage: int,
        sandbox_path: str,
        stage_continuation_policy: StageContinuationPolicy | str = StageContinuationPolicy.AUTO_ON_GREEN,
        gate_id: str | None = None,
        decision_id: str | None = None,
    ) -> StageContinuationResult:
        """Queue the next stage from the current stage sandbox.

        Args:
            job_id: The V2 job ID.
            setup_id: The setup ID to load paths from.
            current_stage: The completed stage (1 or 2).
            sandbox_path: The sandbox output path from the completed stage.
            stage_continuation_policy: Backend-owned policy from run configuration.
            gate_id: Optional gate ID that triggered this continuation.
            decision_id: Optional decision ID that resolved the gate.

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

        policy = _coerce_stage_continuation_policy(stage_continuation_policy)
        if next_stage == TERMINAL_STAGE_INDEX:
            self._validate_stage4_input(job_id, current_stage)

        if policy in (StageContinuationPolicy.MANUAL, StageContinuationPolicy.MANUAL_ON_WARNING_OR_FAILURE):
            reason = (
                "stage_continuation_policy_manual"
                if policy == StageContinuationPolicy.MANUAL
                else "stage_continuation_policy_warning_or_failure"
            )
            return StageContinuationResult(
                continuation_id=uuid4().hex,
                job_id=job_id,
                from_stage=current_stage,
                to_stage=next_stage,
                sandbox_path=sandbox_path,
                argv=(),
                status="blocked",
                reason=reason,
                command_id=None,
            )

        setup = self._setup_repo.get(setup_id)
        if setup is None:
            raise ValueError(f"Setup {setup_id!r} not found")

        config = STAGE_CONFIG[next_stage]

        # Build backend-owned argv for next stage
        jdk_home = _get_jdk_home(setup, config["jdk_env"])

        argv = (
            sys.executable,
            "-m",
            RUNNER_MODULE,
            "--run-id", f"v2-{job_id[:8]}-s{next_stage}",
            "--legacy", sandbox_path,
            "--modernized", setup.output_parent_path,
            "--ai-hub", setup.ai_hub_path,
            "--profile", config["profile"],
            "--mode", "full_sandbox_migration",
        )

        existing_command_id: str | None = None
        if self._command_repo is not None:
            existing = self._command_repo.list_by_job_and_stage(job_id, next_stage)
            if existing:
                existing_command_id = existing[0].command_id
                return StageContinuationResult(
                    continuation_id=uuid4().hex,
                    job_id=job_id,
                    from_stage=current_stage,
                    to_stage=next_stage,
                    sandbox_path=sandbox_path,
                    argv=argv,
                    status="queued",
                    reason="existing_next_stage_command",
                    command_id=existing_command_id,
                )

        # Persist the next stage command if repo available
        if self._command_repo is not None:
            command_id = uuid4().hex
            now = utc_now_text()
            command_record = V2StageCommandRecord(
                command_id=command_id,
                job_id=job_id,
                stage_index=next_stage,
                manifest_checksum=f"v2-stage{next_stage}",
                argv_json=json.dumps(list(argv), separators=(",", ":")),
                env_json=json.dumps({
                    "JAVA_HOME": jdk_home,
                    "JAVA11_HOME": setup.java11_home,
                    "JAVA17_HOME": setup.java17_home,
                    "JAVA21_HOME": setup.java21_home,
                    "MAVEN_CMD": setup.maven_cmd,
                    "PATH_PREPEND": f"{jdk_home}/bin",
                }, separators=(",", ":")),
                status="manifest_ready",
                created_at=now,
                updated_at=now,
                result_json=None,
                gate_id=gate_id,
                decision_id=decision_id,
            )
            self._command_repo.save(command_record)
            existing_command_id = command_id

        return StageContinuationResult(
            continuation_id=uuid4().hex,
            job_id=job_id,
            from_stage=current_stage,
            to_stage=next_stage,
            sandbox_path=sandbox_path,
            argv=argv,
            status="queued",
            command_id=existing_command_id,
        )

    # ── gate-driven queue (with gate/decision tracing) ───────────────

    def queue_next_stage_from_gate(
        self,
        job_id: str,
        setup_id: str,
        current_stage: int,
        sandbox_path: str,
        gate_id: str,
        decision_id: str,
        stage_continuation_policy: StageContinuationPolicy | str = StageContinuationPolicy.AUTO_ON_GREEN,
    ) -> StageContinuationResult:
        """Queue next stage tracking the gate decision that triggered it.

        Like queue_next_stage but requires gate_id and decision_id so
        the resulting command can be traced back to the gate resolution.

        For AUTO_ON_GREEN (no gate), callers should use queue_next_stage
        directly without gate/decision IDs (backward compatible).
        """
        return self.queue_next_stage(
            job_id=job_id,
            setup_id=setup_id,
            current_stage=current_stage,
            sandbox_path=sandbox_path,
            stage_continuation_policy=stage_continuation_policy,
            gate_id=gate_id,
            decision_id=decision_id,
        )

    def validate_stage_chain(
        self,
        job_id: str,
        current_stage: int,
        target_stage: int,
    ) -> tuple[bool, str]:
        """Validate that stage progression follows the required chain.

        Two rules:
        1. target_stage must be exactly current_stage + 1 (no skipping).
        2. All stages BEFORE current_stage must have completed output
           persisted in the command repository.

        Args:
            job_id: The V2 job ID.
            current_stage: The supposedly completed stage (1 or 2).
            target_stage: The desired next stage (current_stage + 1).

        Returns:
            Tuple of (is_valid, reason).
        """
        # Rule 1: No skipping — target must be exactly next
        if target_stage != current_stage + 1:
            return (
                False,
                f"Cannot skip from stage {current_stage} to stage {target_stage}: "
                f"must progress one stage at a time",
            )

        if current_stage < 1 or current_stage > TERMINAL_STAGE_INDEX:
            return (
                False,
                f"Current stage {current_stage} is out of range (1-{TERMINAL_STAGE_INDEX})",
            )

        if target_stage not in STAGE_CONFIG and target_stage not in (2, 3, 4):
            return (
                False,
                f"Target stage {target_stage} is not a valid migration stage",
            )

        # Rule 2: All stages before current_stage must have completed output
        for stage in range(1, current_stage):
            output = self.resolve_prior_stage_output(job_id, stage)
            if output is None:
                return (
                    False,
                    f"Stage {stage} has no completed output — "
                    f"cannot progress to stage {target_stage}",
                )

        return (True, "")

    def resolve_prior_stage_output(
        self,
        job_id: str,
        current_stage: int,
    ) -> str | None:
        """Resolve the sandbox output path from the prior stage's command result.

        First checks for an accepted stage_output artifact revision (F15 path).
        Falls back to extracting sandbox_path from the command record's result_json.

        This eliminates reliance on frontend/chatbot-supplied sandbox_path
        for F15 progression — the backend resolves prior-stage output
        from persisted command/event evidence.

        Args:
            job_id: The V2 job ID.
            current_stage: The completed stage (1 or 2) whose output
                is needed as input for the next stage.

        Returns:
            The sandbox output path string, or None if it cannot be
            resolved (no commands found, no result_json, or missing
            sandbox_path in result).
        """
        # F15 path: check accepted artifact revision first
        resolved = self._resolve_from_artifact_revision(job_id, current_stage)
        if resolved is not None:
            return resolved

        # Legacy path: check command result_json
        if self._command_repo is None:
            return None

        commands = self._command_repo.list_by_job_and_stage(job_id, current_stage)
        if not commands:
            return None

        # Most recent command for the stage
        last = commands[0]
        if last.result_json is None:
            return None

        try:
            result = json.loads(last.result_json)
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(result, dict):
            return None

        # Extract sandbox_path from result (same logic as orchestrator runner)
        sandbox_path = result.get("sandbox_path")
        if sandbox_path and isinstance(sandbox_path, str):
            return sandbox_path

        # Fallback: check artifact_refs sub-dict
        artifact_refs = result.get("artifact_refs")
        if isinstance(artifact_refs, dict):
            for key in ("sandbox", "sandbox_path", "modernized_app", "modernized_app_path"):
                val = artifact_refs.get(key)
                if val and isinstance(val, str):
                    return val

        return None

    def _resolve_from_artifact_revision(
        self,
        job_id: str,
        stage_index: int,
    ) -> str | None:
        if self._artifact_revision_repo is None:
            return None
        accepted = self._artifact_revision_repo.find_accepted(job_id, stage_index, "stage_output")
        if accepted is None:
            return None
        try:
            refs = json.loads(accepted.artifact_refs_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(refs, dict):
            return None
        sandbox = refs.get("sandbox") or refs.get("sandbox_path")
        if sandbox and isinstance(sandbox, str):
            return sandbox
        return None

    def queue_next_stage_from_persisted(
        self,
        job_id: str,
        setup_id: str,
        current_stage: int,
        stage_continuation_policy: StageContinuationPolicy | str = StageContinuationPolicy.AUTO_ON_GREEN,
    ) -> StageContinuationResult:
        """Queue next stage using persisted output from the prior stage.

        Resolves the sandbox_path from the prior stage's command result
        instead of requiring it as a parameter. This is the F15-safe
        entry point that does not accept frontend/chatbot-supplied paths.

        Args:
            job_id: The V2 job ID.
            setup_id: The setup ID to load paths from.
            current_stage: The completed stage (1 or 2).
            stage_continuation_policy: Backend-owned policy.

        Returns:
            StageContinuationResult with resolved sandbox_path, or
            status='blocked' with reason if output cannot be resolved.

        Raises:
            ValueError: If the stage cannot progress.
        """
        sandbox_path = self.resolve_prior_stage_output(job_id, current_stage)
        if sandbox_path is None:
            return StageContinuationResult(
                continuation_id=uuid4().hex,
                job_id=job_id,
                from_stage=current_stage,
                to_stage=current_stage + 1,
                sandbox_path="",
                argv=(),
                status="blocked",
                reason="prior_stage_output_not_resolved",
            )

        return self.queue_next_stage(
            job_id=job_id,
            setup_id=setup_id,
            current_stage=current_stage,
            sandbox_path=sandbox_path,
            stage_continuation_policy=stage_continuation_policy,
        )

    def _validate_stage4_input(
        self,
        job_id: str,
        current_stage: int,
    ) -> None:
        if current_stage != 3:
            raise ValueError(
                f"Cannot progress from stage {current_stage} to stage 4: "
                "must progress from stage 3"
            )

        if self._artifact_revision_repo is not None:
            accepted = self._artifact_revision_repo.find_accepted(
                job_id, 3, "stage_output"
            )
            if accepted is None:
                raise ValueError(
                    "Stage 4 requires an accepted Stage 3 artifact revision. "
                    "No accepted Stage 3 output revision found."
                )
            if accepted.revision_status != "accepted":
                raise ValueError(
                    f"Stage 4 requires an accepted Stage 3 artifact revision, "
                    f"but found status {accepted.revision_status!r}."
                )
            if accepted.superseded_by_revision_id is not None:
                raise ValueError(
                    "Stage 4 requires an accepted Stage 3 artifact revision "
                    "that has not been superseded."
                )
        else:
            stage3_output = self.resolve_prior_stage_output(job_id, 3)
            if stage3_output is None:
                raise ValueError(
                    "Stage 4 requires accepted Stage 3 output. "
                    "Stage 3 has no completed output."
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
            "command_id": result.command_id,
        }


def _get_jdk_home(setup: V2MigrationSetupRecord, env_var: str) -> str:
    mapping = {
        "JAVA11_HOME": setup.java11_home,
        "JAVA17_HOME": setup.java17_home,
        "JAVA21_HOME": setup.java21_home,
    }
    return mapping.get(env_var, "")


def _coerce_stage_continuation_policy(
    value: StageContinuationPolicy | str,
) -> StageContinuationPolicy:
    if isinstance(value, StageContinuationPolicy):
        return value
    return StageContinuationPolicy(value)
