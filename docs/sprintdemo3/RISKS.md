# DEMO3 Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Stage 4 branch divergence | Blind cherry-pick breaks current F15 behavior | Reconcile commits `3c11315`, `980c068`, `b48ae40`, and `1e06b32` behavior-by-behavior with current gates and focused tests. |
| Path/argv/env exposure | Frontend or chatbot influences execution | ID-only strict request schemas, `extra="forbid"`, backend resolution, and redacted public responses. |
| Provider ambiguity | Direct OpenAI, Copilot, fallback, or multi-provider behavior enters the product | Document and test one backend Azure AI Foundry adapter as the only DEMO3 provider path. |
| Frontend calls Foundry or receives credentials | Secret exposure and backend-policy bypass | No frontend provider client; backend-only invocation; recursively redact credentials and provider configuration from responses/events. |
| Excess model context | Source, logs, artifacts, or secrets leave the approved data boundary | Backend-selected controlled context packs with allowlists, bounds, redaction, source references, and checksums. |
| Legacy `copilot_*` names leak to clients | Client assumes Copilot licensing, org policy, or runtime availability is required | Treat names as internal legacy debt, remove them from product-facing docs/contracts, and track a later code naming audit. |
| Checkpoint confused with sandbox path | Mutable filesystem state becomes authority | Store immutable logical checkpoint identity, lineage, artifact checksums, and validation proof; never expose checkpoint storage paths. |
| Backend becomes a static repair catalog | Every new failure requires backend fix code | Registry selects modes and safety envelopes; generative modes accept exact reviewed LLM-authored diffs through generic validators. |
| LLM-authored patch is unsafe or wrong | Source damage or false recovery | Strict schema, exact bindings, independent review, backend policy, human approval, sandbox-only apply, rollback, deterministic validation. |
| Reviewer uses same model identity | Weak or circular review | Persist backend-resolved Azure AI Foundry deployment/model identities; fail closed on equality or unverifiable identity. |
| Patch touches forbidden files | Secrets, deployment, CI, or legacy source affected | Path normalization, traversal and symlink checks, forbidden prefixes, sandbox containment, touched-file allowlist, and actual-diff verification. |
| Stale checksum patch | Candidate applies to changed input | Bind baseline file and checkpoint checksums; reject before apply and before approval execution. |
| Unreviewed or unapproved patch | Governance bypass | Executor accepts only exact candidate revision with accepted review and human approval checksums. |
| Tests call live model or web | Nondeterminism, cost, data exposure | Fake Azure AI Foundry adapter responses and retrieval; no live model or web calls in focused or E2E fixtures. |
| Scope is too large | MVP-A delayed by intelligent recovery work | Enforce roadmap gates and complete checkpoint retry before MVP-B. |
| Duplicate orchestrator, repair loop, or artifact system | Conflicting state and proof | Wrap existing V2/F15 services; document explicit reuse and reject parallel subsystems during review. |
| Repair proposal differs from applied result | Audit cannot prove exact execution | Persist proposed candidate bytes, pre-apply checksum, application result, and actual sandbox diff separately. |
| Registry policy changes after review | Old approval changes meaning | Persist entry IDs, versions, and checksums with every classification, pack, candidate, review, and execution. |
