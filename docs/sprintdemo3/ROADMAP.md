# DEMO3 Roadmap

The roadmap starts from stable baseline `0d9fa7b3b4c386aaebaa7287bebb3f3d2e3cb383` and the docs branch `docs/demo3-f0-f5-prd-stable-0d9fa7b`.

## Delivery Order

1. F0 cleanup.
2. Foundry/model boundary hardening if needed.
3. F1 checkpoint foundation.
4. F2 Analysis reviewer chain.
5. F2 Planning reviewer chain.
6. F3 target profile.
7. F4 source/current-state start.
8. F5 Repair Agent evidence and proposal.
9. F5 reviewer and user decision loop.
10. F5 sandbox apply, rerun, proof.
11. Stage 4/Jackson as concrete F5 proof scenario.

## Milestones

| Milestone | Verifiable outcome |
|---|---|
| F0 cleanup plan | Copilot/TUI/CLI/product-runtime inventory and cleanup report requirements are defined. |
| Boundary hardening | Public product docs forbid provider/model/deployment/env refs as API fields and forbid path/command execution inputs. |
| F1 checkpoint foundation | Analysis and Planning checkpoint states, decisions, stop conditions, and resume behavior are defined. |
| F2 Analysis chain | Analysis final Markdown is produced from deterministic artifact, primary LLM, and reviewer LLM. |
| F2 Planning chain | Planning final Markdown follows the same reviewed chain and becomes next-agent input. |
| F3 target profile | Pipeline route is bounded by validated source and target profile. |
| F4 current-state start | Already-modernized apps can skip older stages with a recorded explanation. |
| F5 evidence/proposal | Build/test failure context and deterministic failure artifact feed Repair Agent proposal. |
| F5 review/decision | Reviewer LLM validates the exact proposed diff and human decides with comments. |
| F5 proof | Backend applies only exact approved reviewed diff and reruns build/test for proof. |
| Stage 4/Jackson proof | OpenRewrite/Jackson strategy is used only as backend-allowlisted F5 proof. |

## Roadmap Guardrails

- Do not implement F0-F5 from this documentation update.
- Do not start Stage 4 implementation from this documentation update.
- Do not add frontend code from this documentation update.
- Do not create provider-selection UI/API.
- Do not expose provider/model/deployment/env refs, `sandbox_path`, argv, env, raw commands, or filesystem targets as product API fields.
