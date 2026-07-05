-- AMF-247: Allow Reviewer mechanical self-repair invocations in the governed LLM ledger.

ALTER TABLE v2_llm_invocations
RENAME TO v2_llm_invocations_old_0052;

DROP INDEX IF EXISTS ix_v2_llm_invocations_job_created;
DROP INDEX IF EXISTS ix_v2_llm_invocations_proposal;
DROP INDEX IF EXISTS ix_v2_llm_invocations_gate;
DROP INDEX IF EXISTS ix_v2_llm_invocations_role;
DROP INDEX IF EXISTS ix_v2_llm_invocations_status;
DROP TRIGGER IF EXISTS v2_llm_invocations_no_delete;

CREATE TABLE v2_llm_invocations (
    invocation_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    proposal_id TEXT,
    gate_id TEXT,
    role TEXT NOT NULL,
    responsibility TEXT NOT NULL,
    provider_alias TEXT,
    deployment_alias_hash TEXT,
    context_checksum TEXT,
    input_checksum TEXT,
    output_checksum TEXT,
    schema_name TEXT,
    status TEXT NOT NULL,
    fallback_used INTEGER DEFAULT 0,
    redacted_error TEXT,
    redacted_summary TEXT,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms INTEGER,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    CHECK (role IN ('main', 'reviewer', 'fallback')),
    CHECK (responsibility IN ('repair_proposal', 'repair_review', 'repair_review_self_repair', 'revision_proposal', 'revision_review', 'diagnosis', 'explanation')),
    CHECK (status IN ('started', 'completed', 'failed', 'fallback')),
    CHECK (fallback_used IN (0, 1))
);

INSERT INTO v2_llm_invocations (
    invocation_id, job_id, proposal_id, gate_id, role, responsibility,
    provider_alias, deployment_alias_hash, context_checksum, input_checksum,
    output_checksum, schema_name, status, fallback_used, redacted_error,
    redacted_summary, prompt_tokens, completion_tokens, total_tokens,
    latency_ms, created_at, completed_at
)
SELECT
    invocation_id, job_id, proposal_id, gate_id, role, responsibility,
    provider_alias, deployment_alias_hash, context_checksum, input_checksum,
    output_checksum, schema_name, status, fallback_used, redacted_error,
    redacted_summary, prompt_tokens, completion_tokens, total_tokens,
    latency_ms, created_at, completed_at
FROM v2_llm_invocations_old_0052;

CREATE INDEX ix_v2_llm_invocations_job_created
ON v2_llm_invocations(job_id, created_at);

CREATE INDEX ix_v2_llm_invocations_proposal
ON v2_llm_invocations(proposal_id);

CREATE INDEX ix_v2_llm_invocations_gate
ON v2_llm_invocations(gate_id);

CREATE INDEX ix_v2_llm_invocations_role
ON v2_llm_invocations(role);

CREATE INDEX ix_v2_llm_invocations_status
ON v2_llm_invocations(status);

CREATE TRIGGER v2_llm_invocations_no_delete
BEFORE DELETE ON v2_llm_invocations
BEGIN
    SELECT RAISE(ABORT, 'v2_llm_invocations is append-only');
END;

DROP TABLE v2_llm_invocations_old_0052;
