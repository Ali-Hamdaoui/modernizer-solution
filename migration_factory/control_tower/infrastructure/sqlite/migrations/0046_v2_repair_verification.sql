-- V2-P0-006: Repair verification status persistence
--
-- Adds verification fields to persisted sandbox actions so the governed
-- apply flow can expose post-apply verification evidence without inventing
-- a new uncontrolled runner.

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'not_available';

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_build_status TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_test_status TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_h2_status TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_artifact_refs_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE v2_sandbox_actions
ADD COLUMN verification_failure_classification_ref TEXT NOT NULL DEFAULT '';
