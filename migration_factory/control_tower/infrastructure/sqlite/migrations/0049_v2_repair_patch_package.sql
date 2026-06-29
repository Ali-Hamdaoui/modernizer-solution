-- R6O: persist patch/evidence package for reviewer-actionable repair proposals.

ALTER TABLE v2_repair_proposals
ADD COLUMN patch_package_json TEXT NOT NULL DEFAULT '{}';
