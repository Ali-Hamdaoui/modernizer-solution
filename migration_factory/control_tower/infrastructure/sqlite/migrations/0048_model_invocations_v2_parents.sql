-- R6N: allow model invocation audits to bind to V2 repair context.
--
-- job_id remains the legacy/V1 migration_jobs foreign key. V2 flows use
-- v2_job_id and v2_command_id so audit records are not orphaned and do not
-- violate the V1 FK.

ALTER TABLE v1_model_invocations ADD COLUMN v2_job_id TEXT
    REFERENCES v2_migration_jobs(job_id);

ALTER TABLE v1_model_invocations ADD COLUMN v2_command_id TEXT
    REFERENCES v2_stage_commands(command_id);

CREATE INDEX IF NOT EXISTS ix_v1_model_invocations_v2_job_id
ON v1_model_invocations(v2_job_id);

CREATE INDEX IF NOT EXISTS ix_v1_model_invocations_v2_command_id
ON v1_model_invocations(v2_command_id);
