# DEMO3 Delivery Roadmap

## Delivery Rule

Foundation 0 must be completed before MVP-A or MVP-B. MVP-A must be completed before MVP-B. Do not start LLM-authored repair execution until checkpoint retry works. Do not implement retrieval or LLM repair before Stage 4, API hardening, checkpoints, attempts, and retry exist.

Provider rule for every phase: Azure AI Foundry is the only production model provider. All model calls are backend-owned; no phase may add a browser/provider call, direct OpenAI route, Copilot runtime dependency, multi-provider selection, or provider fallback.

## Foundation 0 - Foundry-only Cleanup and Copilot Quarantine

FND-01 Disable/quarantine Copilot runtime paths across Control Tower, orchestrator, repair, report, TUI, public API, and frontend runtime surfaces.

FND-02 Add the Azure AI Foundry adapter/config contract as the only model invocation boundary.

FND-03 Remove public provider/config leakage, including `provider_kind`, `azure_openai`, provider env refs, deployment refs, provider credentials, and fallback-provider details.

FND-04 Clean UI, report, TUI, and current docs terminology so product surfaces say Azure AI Foundry or provider-neutral AI.

FND-05 Enforce redacted, bounded, content-checksummed, policy-versioned context packs bound to model invocation records.

FND-06 Map legacy Copilot/Azure OpenAI names for internal compatibility only.

Exit condition: no DEMO3 implementation starts until Copilot is unreachable from product runtime paths, Foundry is the sole model boundary, public contracts leak no provider internals, and deterministic assistance cannot satisfy model-required operations.

## Phase 1 — Reconcile the Execution Spine

1. Reconcile Stage 4 behavior from historical commits against current F15 gates and artifact revisions.
2. Remove path, command, argv, env, sandbox, and patch-target control from public DEMO3 contracts.
3. Persist accepted `StageCheckpoint` records.
4. Persist every `StageAttempt`.
5. Prove retry from the same accepted checkpoint; then add resume and fork semantics.

Exit condition: a failed Stage 4 attempt preserves accepted Stage 3 output and can create another Stage 4 attempt without rerunning Stages 1–3.

## Phase 2 — Establish Grounded Recovery Inputs

6. Persist immutable evidence bound to attempt and checkpoint.
7. Classify through versioned deterministic signatures.
8. Build a provenance- and checksum-bound retrieval pack.
9. Select an allowlisted repair mode and safety envelope.

Exit condition: the backend can produce a complete, immutable recovery context without asking a model to classify authoritatively.

## Phase 3 — Govern Candidate Creation

10. Establish the backend Azure AI Foundry provider contract and controlled context-pack policy, then let the Foundry-backed proposer role author an exact candidate artifact.
11. Require a distinct Azure AI Foundry reviewer deployment identity to critique that exact revision.
12. Run generic backend policy validation before approval.
13. Bind human approval to the reviewed candidate checksum.

Exit condition: an approved candidate is exact, immutable, grounded, independently reviewed, policy-valid, and not executable through model or frontend authority.

## Phase 4 — Execute and Prove

14. Revalidate policy and stale state, then apply the exact approved bytes only in a backend-derived sandbox.
15. Run configured compile, focused tests, or other deterministic validation.
16. Promote validated output to a new accepted checkpoint.

Exit condition: failed validation rolls back and creates no checkpoint; successful validation produces immutable proof and a promoted checkpoint.

## Phase 5 — Expose and Prove the Product

17. Show safe lineage, candidate, review, approval, execution, and validation projections in the cockpit without exposing provider credentials or adding a frontend model client.
18. Prove the generic flow with both Jackson/OpenRewrite and non-Jackson/non-recipe fixtures using fake Azure AI Foundry adapter responses and fake retrieval.

No phase may introduce a duplicate orchestrator, repair loop, artifact store, event stream, validation subsystem, or proof ledger.
