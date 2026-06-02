# Runtime, Build, Test, And Validation

The current factory has strong build/test artifact plumbing, but runtime smoke validation is still a known gap.

## Transformation Validation Model

Source-changing transformation is performed only inside:

```text
<run_dir>/workspaces/sandbox/
```

The high-level wrapper is `migration_factory/transform_v1_after_approval.py`.

Flow:

1. Validate approval decision and approved plan lock.
2. Validate run dir belongs to the modernized app/run id.
3. Validate AI Hub profile guardrails.
4. Write `transformation/transformation_execution_plan.yaml`.
5. Write `transformation/openrewrite-plugin.xml`.
6. Apply OpenRewrite apply settings from AI Hub profile/catalog.
7. Prepare sandbox workspace from legacy app.
8. Force the execution plan target to the sandbox path.
9. Run Transform Agent unit loop.
10. Run Build Agent at every `awaiting_build_agent` stop.
11. Run Test Agent after final transform completion.
12. Return a `TransformSandboxResult`.

## Build Agent Validation

Build Agent entry:

- `migration_factory/agents/build_agent/agent.py`

Command selection:

- Detects Maven when `pom.xml` exists.
- Detects Gradle when Gradle marker files exist.
- Prefers wrappers (`mvnw`, `gradlew`) when present.
- For Maven multi-module projects, can discover the module containing a Spring Boot main class.

Validation modes:

- `STARTUP`: run `spring-boot:run` or `bootRun` and stop after startup success.
- `PLAN_COMMAND`: run validation command from migration unit.
- `REACTOR_TEST`: for Maven reactor source-changing units, run full `clean test`.

Default timeouts:

- Startup: `120` seconds.
- Command/test: `300` seconds.

Failure categories:

- success
- compilation error
- dependency error
- Java version mismatch
- Java runtime mismatch
- port already in use
- main class not found
- missing config
- process exited
- command error
- timeout
- unknown failure

Environment gates:

- Java 21 target units check `java -version`.
- Spring Boot 4 units check Maven version, requiring at least `3.6.3`.

## Test Agent Validation

Test Agent entry:

- `migration_factory/agents/test_agent/agent.py`

It parses Surefire reports:

```text
**/target/surefire-reports/TEST-*.xml
```

Outputs:

- `test/post_transform/test_report.json`
- `test/post_transform/test_summary.md`
- `test/post_transform/test_agent.log`

Current behavior:

- If reports exist and all suites pass, status is `TEST_PASSED`.
- If failures/errors exist, status is `TEST_FAILED`.
- If XML parse fails, status is `TEST_ERROR`.
- If no reports exist after passed build and reports are not required, status may be `PASS_WITH_WARNINGS`.

## Final Success Criteria

The final full sandbox validation in `migration_factory/orchestrator/artifact_validation.py` requires:

- `approval_status = COMPLETED`
- `approval_decision = approved`
- `orchestration_status = PASS`
- `transform_status = TRANSFORM_APPLIED_IN_SANDBOX`
- `build_status = BUILD_PASSED_IN_SANDBOX`
- `test_status = TEST_PASSED`
- `final_status = TRANSFORM_APPLIED_IN_SANDBOX`
- No errors or blockers.
- Sandbox path exists.
- Required artifact refs exist and point to files.

## Timing Artifacts

`migration_factory/orchestrator/timing.py` writes:

- `performance/timing_report.json`
- `performance/timing_summary.md`

Transform wrapper records:

- sandbox copy duration
- per-unit transform durations
- OpenRewrite command durations
- build validation command durations
- test parse duration
- final report duration

## Java Release Vs Runtime Validation

For staged Spring migration:

- Stage A should keep Java release target at `11`.
- Stage B should target Java release `17`.
- Optional Stage C should validate runtime on Java `21` without implying source release changed to 21.

The Build Agent can use profile env fields:

- `source_jdk_home_env`
- `target_jdk_home_env`

For baseline unit, it uses source JDK. For later units, it uses target JDK.

TODO/VERIFY: Stage A and Stage B profiles currently do not define JDK env fields, so operators must document local `JAVA_HOME`/Maven configuration externally.

## Real Runtime Evidence To Preserve

Observed field evidence:

- Boot `3.5.14` runtime eventually started on Java `21`.
- Runtime smoke used H2 override.
- Runtime smoke set `spring.sql.init.mode=never`.
- Keystore/JWT errors remained security-environment warnings, not migration compile blockers.

Current factory handling:

- Build Agent can detect startup success from process logs.
- Test Agent can parse Surefire.
- Assessment can flag security/auth strings as enterprise compatibility warnings.
- Final report can preserve warnings and limitations.

Missing:

- No dedicated runtime smoke agent.
- No standard artifact recording runtime JDK, active profile, port, endpoint checks, H2 override, SQL init override, JWT/keystore classification, and smoke evidence.

## Recommended Runtime Smoke Agent Contract

Future artifact:

```text
runtime/post_transform/runtime_smoke_report.json
runtime/post_transform/runtime_smoke_summary.md
runtime/post_transform/runtime_smoke.log
```

Suggested fields:

- `schema_version`
- `run_id`
- `agent: runtime-smoke-agent`
- `phase: post_transform_runtime`
- `java_runtime.version`
- `java_runtime.home`
- `java_release_target`
- `spring_boot_version`
- `command`
- `cwd`
- `profiles`
- `overrides`
- `ports`
- `startup_status`
- `endpoint_checks`
- `datasource_mode`
- `sql_init_mode`
- `security_environment_warnings`
- `migration_compile_blockers`
- `result`
- `artifact_refs`

Security classification:

- Missing keystore/JWT secret should be `SECURITY_ENV_WARNING` unless it prevents application boot in the selected smoke mode.
- Compile failures remain blockers.
- Endpoint failures are smoke blockers when endpoint is declared required.

## IntelliJ Vs Maven Runs

Known operational distinction:

- IntelliJ may run with a different JDK, classpath, active profile, VM options, working directory, or environment from Maven CLI.
- Maven CLI is the current factory source of validation truth.

Recommended docs for each run:

- Maven command used.
- `JAVA_HOME`.
- `MAVEN_CMD` or wrapper path.
- IntelliJ project SDK and run configuration if IntelliJ evidence is cited.
- Active Spring profiles.
- Local overrides used for smoke tests.

TODO/VERIFY: There is no current artifact that captures IntelliJ run configuration.

## Tests Covering Validation

- `tests/test_build_agent.py`
- `tests/test_test_agent.py`
- `tests/test_transformation_agent.py`
- `tests/orchestrator/test_full_sandbox_migration.py`
- `tests/test_final_report.py`
