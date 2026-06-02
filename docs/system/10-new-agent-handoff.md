# New Agent Handoff

This handoff is for the next agent or engineer extending the AI Migration Factory.

## Current System In One Sentence

The factory is an artifact-driven LangGraph orchestration that analyzes and plans migrations read-only, pauses for human approval, then transforms only a sandbox and has V1 validation as a build/test-only migration proof.

Current verdict:

- `V1 build/test proof: DONE`
- `Runtime/H2 proof: V2`
- `Endpoint smoke: V2`
- `SQL Server: V2`
- `Production readiness: not claimed`

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

## V1 Migration Evidence To Carry Forward

Preserve this as operator evidence:

- Source app used Spring Boot `2.1.6.RELEASE` via BOM/property.
- Stage 1 profile: `springboot-2.1.6-to-2.7-java11`.
- Stage 1 run id: `v1-stage1-216-to-27-watchonly-20260602-233409`.
- Stage 1 result: transform `TRANSFORM_APPLIED_IN_SANDBOX`, build `BUILD_PASSED_IN_SANDBOX`, tests `PASS_WITH_WARNINGS`, Copilot `AVAILABLE`, Copilot invocation `SKIPPED`, fallback `false`.
- Stage 2 profile: `springboot-2.7-to-3.5-java17`.
- Stage 2 run id: `v1-stage2-27-to-35-watchonly-20260602-233720`.
- Stage 2 result: transform `TRANSFORM_APPLIED_IN_SANDBOX`, build `BUILD_PASSED_IN_SANDBOX`, tests `PASS_WITH_WARNINGS`, Copilot `AVAILABLE`, Copilot invocation `SKIPPED`, fallback `false`.
- Final sandbox `pom.xml` had Java `17` and Spring Boot `3.5.14`.
- Final manual verification passed: `mvn clean test -DskipITs`, exit code `0`.
- Direct profile `springboot-2.1.6-to-3.5-java17-v1-build-only` does not exist.
- Do not apply `springboot-2.7-to-3.5-java17` directly to the original app because it requires Spring Boot `2.7.*` source.

Known final Stage 2 caveats:

- `tomcat.version = 9.0.102` still present.
- `org-zalando.version = 0.24.0` and `problem-spring-web` still present.
- `javax.*` search excluding `target` found 3 occurrences, all logger names in `src/test/resources/logback.xml`.
- `Translation.java` has 5 `jakarta.persistence.*` imports.
- Runtime/H2 was intentionally not tested in V1.

## Best Next Agent To Build

Recommended: Runtime Smoke Agent.

Why:

- Current build/test success is not enough.
- Runtime/H2 proof is explicitly V2.
- Security-env classification needs structured evidence.

Runtime/H2 investigation to start from:

- H2 smoke config injection with `spring.config.additional-location` worked after a path fix.
- H2 startup still fails due to `common-utils` runtime config.
- Exact missing cache key found in `common-utils`: `caching.time-out`.
- `CachingConfig` manually loads profile YAML with `YamlPropertiesFactoryBean`, not normal Spring Boot environment binding.
- `common-utils-test.yml` contains `caching.time-out: 15`.
- Running profile `test` fails earlier because `config/application-test.yml` contains invalid `spring.profiles.active` in a profile-specific resource.

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
- Add V2 proof-level reporting: `build_test_verified`, `runtime_startup_verified`, `endpoint_smoke_verified`, `production_ready_not_claimed`.
