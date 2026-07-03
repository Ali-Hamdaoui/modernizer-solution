-- PR-G: Durable idempotency for repair chain attempts.
--
-- Records every chain attempt with a content-addressed key so that the
-- same (job_id, command_id, context_checksum, chain_kind) never creates
-- duplicate Main (PROPOSER) invocations — even across service restarts.
--
-- States:
--   started               Chain has begun; Main call is in flight (or will be)
--   main_schema_invalid   Main model returned schema-invalid output
--   main_empty_response   Main model returned empty response
--   main_provider_failed  Main model provider call failed
--   reviewer_failed       Reviewer model failed
--   materialized          Chain completed successfully; gate+proposal created
--   retry_requested       User or system requested a retry
--   revision_requested    User requested a revision of the proposal

CREATE TABLE v2_chain_attempts (
    chain_key         TEXT PRIMARY KEY,
    job_id            TEXT NOT NULL,
    command_id        TEXT NOT NULL,
    context_checksum  TEXT NOT NULL,
    chain_kind        TEXT NOT NULL,
    status            TEXT NOT NULL,
    failure_reason    TEXT,
    invocation_ids_json TEXT,
    attempt_number    INTEGER DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT,
    CHECK (status IN (
        'started',
        'main_schema_invalid',
        'main_empty_response',
        'main_provider_failed',
        'reviewer_failed',
        'materialized',
        'retry_requested',
        'revision_requested'
    ))
);

CREATE INDEX ix_v2_chain_attempts_job
ON v2_chain_attempts(job_id, created_at);

CREATE INDEX ix_v2_chain_attempts_status
ON v2_chain_attempts(status);

CREATE TRIGGER v2_chain_attempts_no_delete
BEFORE DELETE ON v2_chain_attempts
BEGIN
    SELECT RAISE(ABORT, 'v2_chain_attempts is append-only');
END;
