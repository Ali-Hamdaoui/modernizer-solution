# Reviewer LLM Before Apply

## Goal

Require a reviewer critique for repair and POM proposals before they can be offered for human approval.

The reviewer must not stop the proposer from creating concrete migration proposals. The proposer creates actionable repair/POM intents; the reviewer checks proposal quality, risk, evidence coverage, affected paths, and policy fit before the backend prepares an approval card.

First scope:

```text
ReviewerCritique for repair_proposal
ReviewerCritique for pom_proposal
```

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/control_tower/application/v2_model_schemas.py`
  - `REVIEWER_CRITIQUE_SCHEMA` with `decision`, `reasoning`, `missing_evidence`, `unsafe_assumptions`.
- `migration_factory/control_tower/application/plan_reviews.py`
  - `PlanReviewService.record_review_decision()` validates expected checksum.
  - `get_review_status()` enforces review before downstream eligibility.
- `migration_factory/control_tower/application/v2_approval_mapping.py`
  - Approval cards and checksum-gated approval/resume.
- `migration_factory/control_tower/application/v2_repair_flow.py`
  - Repair proposals with statuses.

What already exists:

- Reviewer schema.
- Checksum pattern.
- Approval card pattern.
- Repair proposal status flow.

What must not be duplicated:

- Reviewer schema.
- Approval card system.
- Plan review checksum pattern.

## Proposed Implementation

1. Add reviewer request generation for `repair_proposal` and `pom_proposal`.
2. Use existing `ReviewerCritique` schema.
3. Reviewer prompt gets:
   - proposal payload
   - context pack checksum
   - evidence refs
   - sandbox binding checksum
   - safety policy
   - POM summary when relevant
4. Validate reviewer output.
5. Persist reviewer critique linked to proposal checksum.
6. Apply reviewer policy:
   - `accept` -> approval card can be prepared.
   - `revise` -> route back through chatbot/proposal revision.
   - `reject` -> close/reject the proposal.
7. Display reviewer verdict on approval card when approval preparation is allowed.

Reviewer `accept` is not human approval. It is a backend policy gate that allows an exact checksum approval card to be prepared for the human.

Do not build yet:

- Review every agent output.
- Review every final report claim.
- Review every planning detail.

## Data / Schema Changes

Add reviewer critique record:

```text
critique_id
proposal_id
proposal_type
proposal_checksum
context_pack_checksum
decision
reasoning
missing_evidence_json
unsafe_assumptions_json
model_invocation_id
created_at
```

Approval card payload should include:

- `reviewer_critique_id`
- `reviewer_decision`
- `reviewed_checksum`

Technical basis: reviewer output should remain schema-constrained with `additionalProperties: false`, matching OpenAI and Azure structured-output constraints: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Azure Structured Outputs](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/structured-outputs).

## Backend Flow

```text
RepairProposal/PomProposal draft
-> reviewer prompt router
-> ReviewerCritique strict output
-> persist critique
-> backend policy checks accept/revise/reject
-> approval card includes reviewer verdict when eligible
```

## UI / Cockpit Impact

Add Reviewer Verdict panel/card:

- decision
- reasoning
- missing evidence
- unsafe assumptions
- reviewed checksum

Attach verdict to the repair approval card rather than creating a separate approval flow.

## Human Supervision Point

The human sees reviewer verdict before approving. If reviewer says `accept`, the backend may prepare an approval card; if reviewer says `revise` or `reject`, the UI should push revision/rejection flow, not apply.

## Safety / Governance

- Sandbox only: reviewer creates critiques for concrete proposals; apply remains bridge-owned.
- No legacy mutation: reviewer checks affected paths and policy.
- Human approval boundary: reviewer critique is not a human approval.
- Backend-owned action gate: reviewer output controls approval-card eligibility, but cannot bypass human approval, apply, validation, rollback, ledger, or proof gates.
- Checksum/proof gates: reviewer verdict is bound to proposal checksum.

## Tests

Targeted tests:

- Extend `tests/control_tower/test_v2_model_schemas.py`.
- Extend `tests/control_tower/test_v2_approval_assistant_repair_repos.py`.
- Extend `tests/control_tower/test_v1_13_plan_review_gate.py` patterns if reused.
- Add `test_reviewer_critique_blocks_unreviewed_repair_approval`.
- Add `test_reviewer_verdict_attaches_to_approval_card`.
- Add `test_reviewer_checksum_mismatch_fails_closed`.

## Risks

- Treating reviewer `accept` as approval.
- Reviewing stale proposal payload after revision.
- Adding broad reviewer scope before repair/POM flow is stable.

## Open Questions

- Should reviewer critique use a separate Azure deployment/role from assistant/proposer?
- Is `revise` allowed to show an approval card, or must revision happen first?
