-- V2-P0-012: Allow patch candidates to capture governed apply outcomes

DROP TRIGGER IF EXISTS v2_patch_candidates_no_update;

ALTER TABLE v2_patch_candidates
ADD COLUMN result_summary TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_patch_candidates
ADD COLUMN validation_status TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_patch_candidates
ADD COLUMN rollback_status TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_patch_candidates
ADD COLUMN artifact_refs_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE v2_patch_candidates
ADD COLUMN applied_action_id TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_patch_candidates
ADD COLUMN operator_note TEXT NOT NULL DEFAULT '';
