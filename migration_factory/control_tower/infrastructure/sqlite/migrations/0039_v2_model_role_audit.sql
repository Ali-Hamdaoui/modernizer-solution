-- V2-P0-008: Public audit metadata for proposer/reviewer role separation

ALTER TABLE v2_repair_proposals
ADD COLUMN proposer_model_invocation_id TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN proposer_model_role TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN proposer_model_provider TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_repair_proposals
ADD COLUMN proposer_deployment_label TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_reviewer_critiques
ADD COLUMN model_role TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_reviewer_critiques
ADD COLUMN model_provider TEXT NOT NULL DEFAULT '';

ALTER TABLE v2_reviewer_critiques
ADD COLUMN deployment_label TEXT NOT NULL DEFAULT '';
