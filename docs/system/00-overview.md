# AI Migration Factory Overview

This package documents the AI Migration Factory implemented in this repository. It is based on the current code under `migration_factory/`, `modernizer-solution-ai-hub/`, and `tests/`.

The factory is a staged, artifact-driven migration system for Java/Spring applications. It separates read-only analysis and planning from source-changing sandbox transformation, uses human approval as a required control point, and treats Copilot as advisory/reporting only.

## Core Goals

- Analyze a legacy application without modifying source.
- Produce deterministic migration plans and approval artifacts.
- Pause for human review before any source-changing work.
- Resume approved runs into a sandbox workspace only.
- Apply transformation units and validate each source-changing unit through build checks.
- Parse post-transform test evidence.
- Generate deterministic final reports and optional Copilot advisory reports.

## Non-Goals And Safety Boundaries

- No production promotion.
- No automatic pull request creation.
- No deployment.
- No automatic merge.
- No source mutation during `read_only_assessment`.
- No legacy app mutation during sandbox transformation.
- Copilot cannot approve, transform, mutate source, change gates, override status, create PRs, or deploy.

These boundaries are enforced through code in:

- `migration_factory/agents/analysis_agent/analysis_agent/context_manager.py`
- `migration_factory/agents/analysis_agent/analysis_agent/readonly_verifier.py`
- `migration_factory/orchestrator/approval.py`
- `migration_factory/approval/artifacts.py`
- `migration_factory/transform_v1_after_approval.py`
- `migration_factory/agents/transformation_agent/workspace.py`
- `migration_factory/orchestrator/copilot_assist.py`
- `migration_factory/copilot_assist/`
- `migration_factory/final_report/context_builder.py`

## High-Level Architecture

```mermaid
flowchart LR
    Legacy[Legacy app<br/>read-only input] --> Analysis[Analysis Agent]
    AIHub[AI Hub<br/>profiles/catalogs/policies] --> Analysis
    AIHub --> Planning[Planning Agent]
    Analysis --> Planning
    Planning --> Assessment[Assessment Agent]
    Assessment --> Approval[Human Approval Gate]
    Approval -->|approved + full_sandbox_migration| Sandbox[Sandbox Workspace]
    Approval -->|rejected or replan_required| Stop[Stop with decision]
    Sandbox --> Transform[Transform Agent]
    Transform --> Build[Build Agent]
    Build --> Transform
    Transform --> Test[Test Agent]
    Test --> Final[Final Report]
    Final --> Copilot[Copilot advisory docs/report]

    Analysis --> Artifacts[(Run artifacts)]
    Planning --> Artifacts
    Assessment --> Artifacts
    Approval --> Artifacts
    Transform --> Artifacts
    Build --> Artifacts
    Test --> Artifacts
    Final --> Artifacts
    Copilot --> Artifacts
```

## Primary Run Modes

`read_only_assessment`

- Runs analysis, planning, assessment, and approval interrupt.
- Does not run sandbox transformation.
- Intended for review and feasibility assessment.

`full_sandbox_migration`

- Runs the same Phase 1 stages.
- Pauses at approval.
- On approved resume, records approval artifacts, locks approved inputs, creates a sandbox, transforms the sandbox, validates build/tests, and emits final reports.

## Real Migration Evidence Captured

The following field evidence should be preserved in reports and future agent prompts:

- Source app used Spring Boot `2.1.6.RELEASE` through BOM/property metadata.
- Stage A worked from Spring Boot `2.1.6.RELEASE` to Boot `2.7`.
- Stage B worked from Boot `2.7` to Boot `3.5.14`.
- Runtime eventually started on Java `21`.
- Internal dependency versions that worked:
  - `common-utils 2.9.41-SNAPSHOT`
  - `msa-dto 3.3.22-SNAPSHOT`
  - `problem-spring-web 0.29.1`
- Runtime smoke used an H2 override and `spring.sql.init.mode=never`.
- Keystore/JWT errors remain security-environment warnings, not migration compile blockers.

TODO/VERIFY: The current factory records build and parsed Surefire evidence, but it does not yet contain a dedicated runtime smoke agent that can encode all of this runtime evidence automatically.

## Documentation Index

- `docs/system/01-architecture.md` - component architecture and responsibilities.
- `docs/system/02-agent-workflow.md` - agent-by-agent technical details.
- `docs/system/03-orchestrator-flow.md` - LangGraph state flow, routing, resume, and finalization.
- `docs/system/04-profiles-ai-hub.md` - AI Hub profiles, staged Spring migration, and Java release/runtime handling.
- `docs/system/05-copilot-integration.md` - Copilot config, providers, artifacts, and safety boundaries.
- `docs/system/06-data-contracts-artifacts.md` - schemas, run directory layout, artifact refs, and report contracts.
- `docs/system/07-runtime-build-test-validation.md` - transformation, build, test, timing, and missing runtime smoke.
- `docs/system/08-known-gaps-and-risks.md` - current gaps and recommended future agents.
- `docs/system/09-how-to-run.md` - command examples and operational cautions.
- `docs/system/10-new-agent-handoff.md` - implementation handoff for a new agent.
