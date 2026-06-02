# New Agent Handoff

This handoff is for the next agent or engineer extending the AI Migration Factory.

## Current System In One Sentence

The factory is an artifact-driven LangGraph orchestration that analyzes and plans migrations read-only, pauses for human approval, then transforms only a sandbox and validates it through build/test/report contracts.

## Do Not Change Without Approval

- Do not mutate legacy apps.
- Do not run real migrations unless explicitly asked.
- Do not weaken approval or approved plan lock checks.
- Do not let Copilot mutate official state or source.
- Do not expose secret values.
- Do not convert security-env warnings into compile blockers without evidence.

## Most Important Code Paths

Start here:

- `migration_factory/orchestrator/runner.py`
- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/state.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/orchestrator/artifact_validation.py`
- `migration_factory/orchestrator/resume.py`
- `migration_factory/transform_v1_after_approval.py`

Agent paths:

- `migration_factory/agents/analysis_agent/analysis_agent/main.py`
- `migration_factory/agents/planning_agent/node.py`
- `migration_factory/assessment/writer.py`
- `migration_factory/approval/approve_run.py`
- `migration_factory/agents/transformation_agent/agent.py`
- `migration_factory/agents/build_agent/agent.py`
- `migration_factory/agents/test_agent/agent.py`
- `migration_factory/final_report/writer.py`
- `migration_factory/final_report/context_builder.py`
- `migration_factory/final_report/copilot.py`
- `migration_factory/agents/copilot_doc_agent/agent.py`

AI Hub:

- `modernizer-solution-ai-hub/hub.yaml`
- `modernizer-solution-ai-hub/profiles/`
- `modernizer-solution-ai-hub/catalogs/openrewrite/`
- `modernizer-solution-ai-hub/agents/`
- `modernizer-solution-ai-hub/templates/reports/`

## Real Migration Evidence To Carry Forward

Preserve this as operator evidence:

- Source app used Spring Boot `2.1.6.RELEASE` via BOM/property.
- Stage A worked to Boot `2.7`.
- Stage B worked to Boot `3.5.14`.
- Runtime eventually started on Java `21`.
- Working internal versions:
  - `common-utils 2.9.41-SNAPSHOT`
  - `msa-dto 3.3.22-SNAPSHOT`
  - `problem-spring-web 0.29.1`
- Runtime smoke used H2 override and `spring.sql.init.mode=never`.
- Keystore/JWT errors remain security-env warnings, not migration compile blockers.

## Best Next Agent To Build

Recommended: Runtime Smoke Agent.

Why:

- Current build/test success is not enough.
- The real migration required runtime proof with H2 override and SQL init disabled.
- Security-env classification needs structured evidence.

Suggested files:

- `migration_factory/agents/runtime_smoke_agent/__init__.py`
- `migration_factory/agents/runtime_smoke_agent/agent.py`
- `migration_factory/contracts/schemas/runtime_smoke_report.schema.json`
- `tests/test_runtime_smoke_agent.py`
- `tests/orchestrator/test_runtime_smoke_flow.py`

Suggested artifacts:

- `runtime/post_transform/runtime_smoke_report.json`
- `runtime/post_transform/runtime_smoke_summary.md`
- `runtime/post_transform/runtime_smoke.log`

Suggested status values:

- `RUNTIME_SMOKE_PASSED`
- `RUNTIME_SMOKE_FAILED`
- `RUNTIME_SMOKE_WARNING`
- `RUNTIME_SMOKE_SKIPPED`

## Runtime Smoke Agent Contract Draft

Inputs:

- sandbox path
- run dir
- run id
- build/test status
- target stack
- runtime JDK env or explicit `JAVA_HOME`
- smoke command
- active profiles
- property overrides
- endpoint list

Outputs:

- runtime smoke JSON report
- summary Markdown
- log

Classification:

- Compile errors are migration blockers.
- Startup failures are runtime blockers unless explicitly classified as expected env gaps.
- Keystore/JWT missing secrets are `SECURITY_ENV_WARNING` when smoke mode is allowed to bypass secured integrations.
- Endpoint failures are blockers only for required endpoints.
- SQL init failures should be classified separately from datasource availability.

## Other High-Value Agents

Dependency Compatibility Scanner:

- Scan dependency graph and POMs for Springfox, Zalando, Hibernate, SQL Server driver, Tomcat overrides, Spring Cloud, internal starters.
- Output compatibility blockers/warnings with version-specific rules.

Internal Artifact Resolver:

- Resolve internal JARs and inspect bytecode/POMs.
- Detect `javax.*` in internal artifacts.
- Record artifact repository source without exposing credentials.

SQL Init Analyzer:

- Scan `schema.sql`, `data.sql`, Flyway, Liquibase, and `spring.sql.init.*`.
- Explain when H2 override or `spring.sql.init.mode=never` is needed.

Security Env Classifier:

- Classify JWT, keystore, cert, OAuth, SSO, and secret failures.
- Distinguish compile blockers from environment warnings.

Endpoint Smoke Agent:

- Execute endpoint checks against started app.
- Record status codes, response excerpts, auth mode, and proof level.

## Tests To Run After Changes

Always run:

```powershell
py -m pytest -q
```

Targeted suites:

- Orchestrator changes: `py -m pytest -q tests/orchestrator`
- Planning/profile changes: `py -m pytest -q tests/agents/planning_agent`
- Analysis changes: `py -m pytest -q migration_factory/agents/analysis_agent/analysis_agent/tests`
- Build/test changes: `py -m pytest -q tests/test_build_agent.py tests/test_test_agent.py`
- Report/Copilot changes: `py -m pytest -q tests/test_final_report.py tests/reporting`

## Implementation Notes

- Prefer adding schemas before new artifacts.
- Add artifact refs into orchestration summary and final report only after files are actually written.
- Keep new agents fail-closed when they are authoritative, fail-open only when explicitly advisory.
- Preserve exact run dir boundaries.
- Use redaction helpers from `migration_factory/final_report/context_builder.py` when serializing context that could contain secrets.
- Extend `validate_successful_full_sandbox_orchestration()` only after deciding whether runtime smoke is required or optional.

## Open TODO/VERIFY Items

- Stage A/B JDK env fields are not currently specified in profiles.
- `sdk` Copilot provider is allowed in config but not implemented as a live provider.
- `read_only_verification.json` is optional in constants but required by orchestrator artifact validation.
- Transform wrapper accepts `PASS_WITH_WARNINGS`/`TESTS_NOT_FOUND`, while final success validation requires `TEST_PASSED`.
- No multi-stage run ledger links Stage A/B/C evidence.
