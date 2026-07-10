-- R11: Append-only operator-governed repair attempt, action, and decision ledger.
-- Existing proposal/candidate/apply tables remain the execution path. These
-- tables preserve every investigation attempt and authority decision.

CREATE TABLE v2_repair_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index BETWEEN 1 AND 4),
    command_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
    attempt_source TEXT NOT NULL CHECK (attempt_source IN ('llm', 'manual')),
    previous_attempt_id TEXT,
    repair_candidate_id TEXT,
    applicability_status TEXT NOT NULL CHECK (applicability_status IN ('applicable', 'blocked', 'invalid')),
    workflow_state TEXT NOT NULL,
    projection_json TEXT NOT NULL,
    internal_json TEXT NOT NULL,
    attempt_checksum TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (previous_attempt_id) REFERENCES v2_repair_attempts(attempt_id),
    UNIQUE (job_id, stage_index, attempt_number)
);

CREATE INDEX ix_v2_repair_attempts_job_stage
ON v2_repair_attempts(job_id, stage_index, attempt_number DESC);

CREATE TABLE v2_repair_operator_actions (
    action_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index BETWEEN 1 AND 4),
    action_type TEXT NOT NULL CHECK (action_type IN (
        'request_corrected_proposal',
        'provide_operator_guidance',
        'request_additional_context',
        'submit_manual_diff',
        'reject_current_attempt',
        'mark_manual_remediation_required',
        'resume_from_repair_checkpoint'
    )),
    payload_json TEXT NOT NULL,
    payload_checksum TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES v2_repair_attempts(attempt_id)
);

CREATE INDEX ix_v2_repair_operator_actions_attempt
ON v2_repair_operator_actions(attempt_id, created_at);

CREATE TABLE v2_repair_operator_decisions (
    decision_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    repair_candidate_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    stage_index INTEGER NOT NULL CHECK (stage_index BETWEEN 1 AND 4),
    approval_mode TEXT NOT NULL CHECK (approval_mode IN (
        'normal_approval',
        'acknowledged_risk_approval',
        'reviewer_override_approval'
    )),
    decision_status TEXT NOT NULL CHECK (decision_status IN ('approved', 'rejected')),
    operator_justification TEXT NOT NULL,
    acknowledged_risk_codes_json TEXT NOT NULL,
    reviewer_outcome TEXT NOT NULL,
    reviewer_output_checksum TEXT NOT NULL,
    reviewer_invocation_id TEXT NOT NULL,
    candidate_checksum TEXT NOT NULL,
    decision_checksum TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (attempt_id) REFERENCES v2_repair_attempts(attempt_id),
    UNIQUE (repair_candidate_id)
);

CREATE INDEX ix_v2_repair_operator_decisions_attempt
ON v2_repair_operator_decisions(attempt_id, created_at);
