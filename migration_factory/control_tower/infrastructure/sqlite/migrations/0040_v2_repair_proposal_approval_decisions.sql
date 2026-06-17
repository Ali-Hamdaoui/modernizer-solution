-- V2-P0-010: Human approval decisions for governed repair proposals
--
-- Stores append-only operator approve/reject decisions bound to
-- proposal and context checksums. Decisions never apply patches.

CREATE TABLE v2_repair_proposal_approval_decisions (
    decision_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    operator_decision TEXT NOT NULL CHECK (operator_decision IN ('approve', 'reject')),
    approval_checksum TEXT NOT NULL,
    proposal_checksum TEXT NOT NULL,
    context_pack_checksum TEXT NOT NULL,
    reviewer_gate_status TEXT NOT NULL,
    reviewer_critique_id TEXT,
    operator_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    correlation_id TEXT
);

CREATE INDEX ix_v2_repair_proposal_approval_decisions_proposal
ON v2_repair_proposal_approval_decisions(proposal_id, created_at DESC);

CREATE TRIGGER v2_repair_proposal_approval_decisions_no_update
BEFORE UPDATE ON v2_repair_proposal_approval_decisions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_proposal_approval_decisions is append-only');
END;

CREATE TRIGGER v2_repair_proposal_approval_decisions_no_delete
BEFORE DELETE ON v2_repair_proposal_approval_decisions
BEGIN
    SELECT RAISE(ABORT, 'v2_repair_proposal_approval_decisions is append-only');
END;
