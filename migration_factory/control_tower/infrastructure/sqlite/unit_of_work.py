"""SQLite unit of work for Control Tower application services."""

from __future__ import annotations

import sqlite3

from migration_factory.control_tower.infrastructure.sqlite.repositories import (
    SqliteArtifactRepository,
    SqliteAuditRecordRepository,
    SqliteCommandExecutionRepository,
    SqliteIdempotencyRepository,
    SqliteMigrationJobRepository,
    SqlitePipelineDefinitionRepository,
    SqliteRunConfigurationRepository,
    SqliteRunEventRepository,
    SqliteRunnerProfileRepository,
    SqliteStageChainLedgerRepository,
    SqliteStageRunRepository,
    SqliteV1ContextPackManifestRepository,
    SqliteV1FakeRepairProposalRepository,
    SqliteV1ModelInvocationRepository,
    SqliteV1PatchApplicationRepository,
    SqliteV1PatchMavenValidationRepository,
    SqliteV1PatchPolicyValidationRepository,
    SqliteV1PatchRollbackRepository,
    SqliteV1PlanAmendmentRepository,
    SqliteV1PlanReviewDecisionRepository,
    SqliteV1RepairClassificationRepository,
    SqliteV1PlanRevisionRepository,
    SqliteV1PrivilegedActionDecisionRepository,
    SqliteV1PrivilegedActionExecutionRepository,
    SqliteV1PrivilegedActionRepository,
    SqliteV1ProofReportGateRepository,
    SqliteV1ProofReportRepository,
    SqliteV1SandboxSnapshotRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v1_model_profile_repository import (
    SqliteV1ModelProfileEventRepository,
    SqliteV1ModelProfileRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v1_approval_repository import (
    SqliteV1ApprovalRepository,
    SqliteV1ApprovalResumeRepository,
)


class SqliteControlTowerUnitOfWork:
    def __init__(self, connection: sqlite3.Connection, *, close_connection: bool = False) -> None:
        self.connection = connection
        self._close_connection = close_connection
        self.runner_profiles = SqliteRunnerProfileRepository(connection)
        self.pipeline_definitions = SqlitePipelineDefinitionRepository(connection)
        self.migration_jobs = SqliteMigrationJobRepository(connection)
        self.run_configurations = SqliteRunConfigurationRepository(connection)
        self.stage_runs = SqliteStageRunRepository(connection)
        self.run_events = SqliteRunEventRepository(connection)
        self.artifacts = SqliteArtifactRepository(connection)
        self.audit_records = SqliteAuditRecordRepository(connection)
        self.command_executions = SqliteCommandExecutionRepository(connection)
        self.idempotency_records = SqliteIdempotencyRepository(connection)
        self.stage_chain_ledger = SqliteStageChainLedgerRepository(connection)
        self.v1_model_profiles = SqliteV1ModelProfileRepository(connection)
        self.v1_model_profile_events = SqliteV1ModelProfileEventRepository(connection)
        self.v1_approvals = SqliteV1ApprovalRepository(connection)
        self.v1_approval_resume = SqliteV1ApprovalResumeRepository(connection)
        self.v1_model_invocations = SqliteV1ModelInvocationRepository(connection)
        self.v1_context_pack_manifests = SqliteV1ContextPackManifestRepository(connection)
        self.v1_privileged_actions = SqliteV1PrivilegedActionRepository(connection)
        self.v1_plan_amendments = SqliteV1PlanAmendmentRepository(connection)
        self.v1_plan_revisions = SqliteV1PlanRevisionRepository(connection)
        self.v1_plan_review_decisions = SqliteV1PlanReviewDecisionRepository(connection)
        self.v1_repair_classifications = SqliteV1RepairClassificationRepository(connection)
        self.v1_fake_repair_proposals = SqliteV1FakeRepairProposalRepository(connection)
        self.v1_privileged_action_decisions = SqliteV1PrivilegedActionDecisionRepository(connection)
        self.v1_privileged_action_executions = SqliteV1PrivilegedActionExecutionRepository(connection)
        self.v1_patch_policy_validations = SqliteV1PatchPolicyValidationRepository(connection)
        self.v1_sandbox_snapshots = SqliteV1SandboxSnapshotRepository(connection)
        self.v1_patch_applications = SqliteV1PatchApplicationRepository(connection)
        self.v1_patch_maven_validations = SqliteV1PatchMavenValidationRepository(connection)
        self.v1_patch_rollbacks = SqliteV1PatchRollbackRepository(connection)
        self.v1_proof_reports = SqliteV1ProofReportRepository(connection)
        self.v1_proof_report_gates = SqliteV1ProofReportGateRepository(connection)

    def __enter__(self) -> "SqliteControlTowerUnitOfWork":
        self.connection.execute("BEGIN IMMEDIATE")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if exc_type is None:
            self.connection.execute("COMMIT")
        elif self.connection.in_transaction:
            self.connection.execute("ROLLBACK")
        if self._close_connection:
            self.connection.close()
        return None


SqliteUnitOfWork = SqliteControlTowerUnitOfWork
