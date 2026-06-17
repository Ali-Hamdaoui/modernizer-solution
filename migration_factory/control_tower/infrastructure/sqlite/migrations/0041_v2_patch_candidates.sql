-- V2-P0-011: Persist preview-only patch candidates for approved repair proposals

CREATE TABLE v2_patch_candidates (
    patch_candidate_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    proposal_checksum TEXT NOT NULL,
    diagnosis_id TEXT NOT NULL,
    diagnosis_checksum TEXT NOT NULL,
    evidence_pack_checksum TEXT NOT NULL,
    context_pack_checksum TEXT NOT NULL,
    unified_diff TEXT NOT NULL DEFAULT '',
    patch_candidate_checksum TEXT NOT NULL,
    materialization_strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    gate_status TEXT NOT NULL,
    gate_reason TEXT NOT NULL DEFAULT '',
    touched_paths_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX ix_v2_patch_candidates_proposal
ON v2_patch_candidates(proposal_id, created_at DESC);

CREATE TRIGGER v2_patch_candidates_no_update
BEFORE UPDATE ON v2_patch_candidates
BEGIN
    SELECT RAISE(ABORT, 'v2_patch_candidates is append-only');
END;

CREATE TRIGGER v2_patch_candidates_no_delete
BEFORE DELETE ON v2_patch_candidates
BEGIN
    SELECT RAISE(ABORT, 'v2_patch_candidates is append-only');
END;
