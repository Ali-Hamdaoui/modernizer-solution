# DEMO3 Sprint Documentation Index

DEMO3 is organized around F0-F5 as the product spine:

```text
F0 - Pre-feature codebase cleanup
F1 - Agent checkpoints and user decisions
F2 - Deterministic artifact + primary LLM + reviewer LLM
F3 - Target profile control
F4 - Start from current app state
F5 - Build/Test Repair Agent review loop
```

Old 01-18 implementation slices remain engineering details. They are not the product center.

## Product Direction

The product is a checkpoint-based, LLM-reviewed migration workflow where the user controls where migration starts, where it stops, which target profile is final, whether Analysis or Planning needs modification, and whether risky build/test-failure fixes are applied.

Core architecture:

```text
FastAPI backend
-> deterministic agents
-> primary LLM
-> reviewer LLM
-> final Markdown artifact
-> stored artifact/checkpoint
-> user approval or correction
-> next pipeline step
```

Core rule: a model reviews another model. For supported model-required outputs, the reviewer LLM is mandatory, not optional.

## Sprint Docs

- [ROADMAP.md](ROADMAP.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [RISKS.md](RISKS.md)
- [TASKS.md](TASKS.md)

## Feature Docs

- [F0 - Pre-feature codebase cleanup](00-pre-feature-cleanup/README.md)
- [F1 - Agent checkpoints and user decisions](01-agent-checkpoints/README.md)
- [F2 - Deterministic artifact + primary LLM + reviewer LLM](02-llm-review-chain/README.md)
- [F3 - Target profile control](03-profile-targeting/README.md)
- [F4 - Start from current app state](04-source-profile-start/README.md)
- [F5 - Build/Test Repair Agent review loop](05-build-test-repair-agent-review-loop/README.md)

## F0-F5 Mapping To Implementation Work

| Feature | Implementation work |
|---|---|
| F0 | Foundation cleanup, Copilot quarantine, TUI removal, CLI/runtime path cleanup, stale terminology cleanup |
| F1 | Stage checkpoint, stage attempt, retry/resume/fork, cockpit checkpoint UX |
| F2 | LLM candidate generator + independent reviewer, extended to Analysis and Planning |
| F3 | Profile targeting and stop-at-target behavior |
| F4 | Source profile detection, manual override, skipped-stage ledger, resume from checkpoint |
| F5 | Failure evidence, classifier, retrieval pack, repair mode, Repair Agent proposal, reviewer, backend validator, human approval, sandbox executor, validation runner, checkpoint promoter, cockpit recovery UX, e2e fixtures |

Stage 4/Jackson is a concrete F5 proof scenario, not the DEMO3 product frame.
