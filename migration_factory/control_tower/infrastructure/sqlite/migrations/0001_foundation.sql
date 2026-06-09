CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL,
    applied_utc TEXT NOT NULL,
    CONSTRAINT uq_schema_migrations_name UNIQUE (name),
    CONSTRAINT uq_schema_migrations_checksum UNIQUE (checksum_sha256)
);

CREATE TABLE runner_profiles (
    profile_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);

CREATE TABLE pipeline_definitions (
    pipeline_id TEXT PRIMARY KEY,
    pipeline_name TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    CONSTRAINT uq_pipeline_definitions_name_version UNIQUE (pipeline_name, pipeline_version)
);

CREATE TABLE migration_jobs (
    job_id TEXT PRIMARY KEY,
    pipeline_id TEXT NOT NULL,
    runner_profile_id TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    state TEXT NOT NULL,
    active_slot INTEGER NOT NULL DEFAULT 1,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    started_utc TEXT,
    finished_utc TEXT,
    CONSTRAINT fk_migration_jobs_pipeline
        FOREIGN KEY (pipeline_id) REFERENCES pipeline_definitions (pipeline_id),
    CONSTRAINT fk_migration_jobs_runner_profile
        FOREIGN KEY (runner_profile_id) REFERENCES runner_profiles (profile_id),
    CONSTRAINT ck_migration_jobs_state
        CHECK (
            state IN (
                'CREATED',
                'QUEUED',
                'STARTING',
                'RUNNING',
                'PAUSED_FOR_PLAN_APPROVAL',
                'PAUSED_FOR_REPAIR',
                'RESUMING',
                'CANCELLING',
                'ORPHANED',
                'RECOVERY_REQUIRED',
                'COMPLETED',
                'FAILED',
                'REJECTED',
                'CANCELLED'
            )
        ),
    CONSTRAINT ck_migration_jobs_active_slot
        CHECK (
            active_slot IN (0, 1)
            AND (
                (state IN ('COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED') AND active_slot = 0)
                OR
                (state NOT IN ('COMPLETED', 'FAILED', 'REJECTED', 'CANCELLED') AND active_slot = 1)
            )
        )
);

CREATE UNIQUE INDEX ux_migration_jobs_one_active_slot
    ON migration_jobs (active_slot)
    WHERE active_slot = 1;

CREATE INDEX ix_migration_jobs_state
    ON migration_jobs (state);

CREATE INDEX ix_migration_jobs_pipeline_id
    ON migration_jobs (pipeline_id);

CREATE TABLE run_configurations (
    configuration_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    target_proof_level TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    CONSTRAINT fk_run_configurations_job
        FOREIGN KEY (job_id) REFERENCES migration_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT uq_run_configurations_job UNIQUE (job_id),
    CONSTRAINT ck_run_configurations_target_proof_level
        CHECK (
            target_proof_level IN (
                'ANALYZED',
                'PLANNED',
                'TRANSFORMED',
                'BUILD_TEST_VERIFIED',
                'RUNTIME_VERIFIED',
                'ENDPOINT_VERIFIED'
            )
        )
);

CREATE TABLE stage_runs (
    stage_run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_name TEXT NOT NULL,
    state TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    started_utc TEXT,
    finished_utc TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT fk_stage_runs_job
        FOREIGN KEY (job_id) REFERENCES migration_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT uq_stage_runs_job_stage UNIQUE (job_id, stage_name),
    CONSTRAINT uq_stage_runs_job_ordinal UNIQUE (job_id, ordinal),
    CONSTRAINT ck_stage_runs_state
        CHECK (
            state IN (
                'PENDING',
                'READY',
                'RUNNING',
                'PAUSED',
                'PASSED',
                'PASSED_WITH_WARNINGS',
                'FAILED',
                'SKIPPED_BY_POLICY',
                'BLOCKED',
                'CANCELLED'
            )
        )
);

CREATE INDEX ix_stage_runs_job_id
    ON stage_runs (job_id);

CREATE INDEX ix_stage_runs_state
    ON stage_runs (state);

CREATE TABLE run_events (
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_run_id TEXT,
    event_type TEXT NOT NULL,
    event_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT fk_run_events_job
        FOREIGN KEY (job_id) REFERENCES migration_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_run_events_stage_run
        FOREIGN KEY (stage_run_id) REFERENCES stage_runs (stage_run_id) ON DELETE CASCADE
);

CREATE INDEX ix_run_events_job_id
    ON run_events (job_id, event_utc);

CREATE INDEX ix_run_events_stage_run_id
    ON run_events (stage_run_id, event_utc);

CREATE TABLE artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_run_id TEXT,
    artifact_kind TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CONSTRAINT fk_artifacts_job
        FOREIGN KEY (job_id) REFERENCES migration_jobs (job_id) ON DELETE CASCADE,
    CONSTRAINT fk_artifacts_stage_run
        FOREIGN KEY (stage_run_id) REFERENCES stage_runs (stage_run_id) ON DELETE CASCADE,
    CONSTRAINT uq_artifacts_job_path UNIQUE (job_id, relative_path)
);

CREATE INDEX ix_artifacts_job_id
    ON artifacts (job_id);

CREATE INDEX ix_artifacts_stage_run_id
    ON artifacts (stage_run_id);

CREATE TABLE audit_records (
    audit_record_id TEXT PRIMARY KEY,
    job_id TEXT,
    stage_run_id TEXT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    recorded_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    CONSTRAINT fk_audit_records_job
        FOREIGN KEY (job_id) REFERENCES migration_jobs (job_id) ON DELETE SET NULL,
    CONSTRAINT fk_audit_records_stage_run
        FOREIGN KEY (stage_run_id) REFERENCES stage_runs (stage_run_id) ON DELETE SET NULL
);

CREATE INDEX ix_audit_records_job_id
    ON audit_records (job_id, recorded_utc);

CREATE INDEX ix_audit_records_stage_run_id
    ON audit_records (stage_run_id, recorded_utc);

CREATE TRIGGER audit_records_prevent_update
BEFORE UPDATE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records is append-only');
END;

CREATE TRIGGER audit_records_prevent_delete
BEFORE DELETE ON audit_records
BEGIN
    SELECT RAISE(ABORT, 'audit_records is append-only');
END;
