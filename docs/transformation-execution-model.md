# Transformation Execution Model

This note traces what happens after an approved resume in AI Migration Factory. It is an investigation artifact only; no pipeline behavior is changed here.

## Short Answer

The sandbox transform is unit-by-unit for orchestration and validation, but not recipe-by-recipe for OpenRewrite.

The transformer walks migration units in the order written to `planning/migration_units.yaml`. After each unit it stops at an awaiting-build state, the build agent validates that unit, and the orchestrator resumes at the next unit. OpenRewrite recipes are grouped into one Maven OpenRewrite invocation on the first source-writing unit, not run one recipe at a time. Most later units are currently validation checkpoints with `custom_code_change` recorded as not executed unless profile-injected deterministic patch transformations are present.

## Approved Resume Path

1. `migration_factory/orchestrator/resume.py` records the explicit approval decision, invokes the LangGraph resume path, and falls back to `orchestration/approval_interrupt_state.json` if needed.
2. The graph routes approved `full_sandbox_migration` runs through `approval_record` and then `sandbox_transform`.
3. `migration_factory/orchestrator/phase_services.py` calls `apply_approved_sandbox_transform(...)`.
4. `migration_factory/transform_v1_after_approval.py` checks approval artifacts, writes the transformation execution plan, writes `openrewrite-plugin.xml`, applies profile transform settings, copies the legacy app into the sandbox workspace, forces the plan target to that sandbox, then runs the transformer/build/test loop.
5. The deterministic final report is generated later by `summary.py` only if approval, transform, build, tests, and final status all match the successful sandbox criteria.

## What A Migration Unit Is

A migration unit is a deterministic planning record with:

- `id`
- `goal` or `title`
- `writes_source`
- `validation`
- `expected_artifacts`
- rollback and blocking-gate metadata

Planning creates these in `migration_factory/agents/planning_agent/unit_builder.py`. The stable order is:

1. `baseline`
2. `java-<target>`
3. `spring-boot-<target>`
4. `jakarta`
5. `dependency-cleanup`
6. `existing-test-migration`

For example, the Java 17 / Spring Boot 3.5 profile produced:

```text
baseline -> java-17 -> spring-boot-3-5-14 -> jakarta -> dependency-cleanup -> existing-test-migration
```

## Where Units Come From

Planning writes `planning/migration_units.yaml`. Then `write_transformation_execution_plan(...)` adapts those planning units into `transformation/transformation_execution_plan.yaml`.

During adaptation:

- Each planning unit becomes one `migration_units[]` entry in the transform plan.
- Every unit receives a `custom_code_change` transformation record.
- If `analysis/rewrite_plugin_plan.json` has `active_recipes`, one `openrewrite` transformation is inserted on the first unit with `writes_source: true`.
- If no source-writing unit is found, OpenRewrite is inserted on the first unit.

So OpenRewrite is attached to the first write unit, not distributed across the semantic units named `java`, `spring-boot`, `jakarta`, and so on.

## How Order Is Decided

The order is the list order from `planning/migration_units.yaml`, which is produced by the deterministic `UNIT_ORDER` in the planning agent. The transformer loads `transformation_execution_plan.yaml` and iterates `plan.units` by index.

Resume is index-based by unit id:

- The transformer records `next_unit_index` in `.migration/ledger.json`.
- The orchestrator also computes `next_unit = _next_unit_after(plan, unit_id)`.
- The next transformer call passes `start_unit=next_unit`.

## Unit-By-Unit Or Grouped

Execution is unit-by-unit at the transformer loop level:

1. Run one unit's transformations.
2. Mark that unit `awaiting_build_agent`.
3. Run build validation for that unit.
4. If build passes, move to the next unit.
5. If the last unit passes build, parse final test reports.

Within a unit, transformations are grouped sequentially inside that unit. For OpenRewrite, all active recipes listed in the unit are passed to one Maven command:

```text
mvn org.openrewrite.maven:rewrite-maven-plugin:<version>:<goal> -Drewrite.activeRecipes=recipeA,recipeB,...
```

That means recipes do not get individual factory gates. They succeed or fail as one OpenRewrite command for that unit.

## OpenRewrite Selection And Application

Recipe selection comes from `analysis/rewrite_plugin_plan.json` when present. That artifact is generated from the AI Hub OpenRewrite catalog. If the run artifact does not provide plugin coordinates, transform code falls back to the profile's `openrewrite.catalog_path`.

The generated `openrewrite-plugin.xml` contains:

- the OpenRewrite Maven plugin coordinate
- recipe artifact dependencies

Current transform code uses that XML to resolve the plugin version and artifact metadata. The actual OpenRewrite apply command is assembled from:

- `active_recipes` in `transformation_execution_plan.yaml`
- optional recipe artifacts
- plugin version from `openrewrite-plugin.xml`
- profile/catalog `apply_goal`
- profile/catalog `apply_maven_args`

For the Java 17 / Boot 3.5 run inspected, the OpenRewrite command was recorded under the `java-17` unit as:

```text
mvn rewrite:run -Drewrite.activeRecipes=org.openrewrite.java.migrate.UpgradeToJava17,org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5
```

For the Boot 4 / Java 21 profile, the profile config supplies:

```text
apply_goal: runNoFork
apply_maven_args: -Denforcer.skip=true
```

Those settings are injected into the OpenRewrite transformation before execution.

## Deterministic Patches

Deterministic patches are profile-driven `post_apply_patches` or `post_openrewrite_patches`. The transform wrapper appends them immediately after the `openrewrite` transformation in the same unit.

Supported patch transformation types in the current transformer are:

- `maven_enforcer_java_version`
- `pom_property`
- `security_authorize_http_requests`
- `batch_flat_file_item_reader_constructor`

They run after OpenRewrite within the same unit. Required POM patches block the unit if no patch is applied. Source patches record `applied` or `not_applicable` in the ledger.

## Build And Test Timing

Build validation runs after every unit, including non-source-changing or no-op units such as `baseline` and later `custom_code_change` placeholders.

The build command is chosen in this order:

1. Unit-level `build_validation.command`, if present.
2. Unit `checks[].command`, usually `mvn clean test`.
3. Plan-level `build_validation.command`, if present.
4. Build agent default detection/startup behavior.

After the final unit's build passes, the test agent does not run a new command. It parses existing Surefire XML under the sandbox and writes the post-transform test artifacts.

## Failure Behavior

If an OpenRewrite command fails, the transformer marks the current unit blocked in the ledger and raises a transformer error. The orchestrator returns `TRANSFORM_FAILED_IN_SANDBOX`.

If a deterministic required patch fails to apply, the transformer marks the current unit blocked and raises a transformer error.

If build validation fails for a unit, the build agent marks the current unit blocked in the ledger. The orchestrator stops immediately with `BUILD_FAILED_IN_SANDBOX`; later units do not run.

If post-transform test parsing finds failures/errors or no usable reports, the transform returns `TEST_FAILED` or `TEST_ERROR`, and final deterministic migration report generation is not allowed.

## Artifact Map

- `transformation/transformation_execution_plan.yaml`: adapted unit list, sandbox target path, transformations per unit, checks per unit.
- `transformation/openrewrite-plugin.xml`: selected OpenRewrite plugin and recipe artifact dependencies.
- `logs/phase2_transform.log`: combined transformer, OpenRewrite, and build-agent output. It shows unit starts, OpenRewrite apply output, pending-build messages, and build/test command output.
- `workspaces/sandbox/.migration/ledger.json`: source of truth for unit status, current/blocked unit, completed units, command results, build validation, and post-transform test validation.
- `build/`: build error contracts when build validation fails.
- `test/post_transform/test_report.json`: parsed Surefire totals after final unit build.
- `test/post_transform/test_summary.md`: human-readable test summary.
- `test/post_transform/test_agent.log`: parser diagnostics, especially missing or malformed report details.
- `orchestration/orchestration_summary.json`: run-level transform/build/test statuses and artifact references.
- `performance/timing_report.json` and `performance/timing_summary.md`: per-unit transform timings and build/OpenRewrite command timings when available.

## Simple Example Flow

For a Java 17 / Spring Boot 3.5 run:

1. `baseline`: no source transform; record placeholder; run `mvn clean test`; continue only if passed.
2. `java-17`: run one OpenRewrite command containing both Java 17 and Spring Boot 3.5 recipes; record command result; run `mvn clean test`; continue only if passed.
3. `spring-boot-3-5-14`: record placeholder; run `mvn clean test`; continue only if passed.
4. `jakarta`: record placeholder; run `mvn clean test`; continue only if passed.
5. `dependency-cleanup`: record placeholder; run `mvn clean test`; continue only if passed.
6. `existing-test-migration`: record placeholder; run `mvn clean test`; continue only if passed.
7. Parse Surefire XML already produced by the final build/test command.
8. If parsed tests pass, return `TRANSFORM_APPLIED_IN_SANDBOX`.

## Files And Artifacts Inspected

Code:

- `migration_factory/orchestrator/resume.py`
- `migration_factory/orchestrator/graph.py`
- `migration_factory/orchestrator/phase_services.py`
- `migration_factory/orchestrator/summary.py`
- `migration_factory/transform_v1_after_approval.py`
- `migration_factory/agents/transformation_agent/execution_plan.py`
- `migration_factory/agents/transformation_agent/plan.py`
- `migration_factory/agents/transformation_agent/agent.py`
- `migration_factory/agents/transformation_agent/executor.py`
- `migration_factory/agents/transformation_agent/rewrite.py`
- `migration_factory/agents/transformation_agent/pom_patches.py`
- `migration_factory/agents/build_agent/agent.py`
- `migration_factory/agents/test_agent/agent.py`
- `migration_factory/contracts/migration/ledger.py`
- `migration_factory/agents/planning_agent/unit_builder.py`
- `migration_factory/agents/planning_agent/plan_writer.py`
- `migration_factory/agents/planning_agent/node.py`

Profiles and catalogs:

- `modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml`
- `modernizer-solution-ai-hub/profiles/springboot-2-java8-to-boot4-java21.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-3.5-java17.yaml`
- `modernizer-solution-ai-hub/catalogs/openrewrite/springboot-4-java21-sandbox.yaml`

Generated artifacts:

- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\transformation\transformation_execution_plan.yaml`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\transformation\openrewrite-plugin.xml`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\logs\phase2_transform.log`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\workspaces\sandbox\.migration\ledger.json`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\test\post_transform\test_report.json`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-perf-001\orchestration\orchestration_summary.json`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-m5a-002\transformation\transformation_execution_plan.yaml`
- `C:\Users\abdelilah.mortaki\Desktop\modernized-app\.migration\runs\shoppoc-full-orch-m5a-002\workspaces\sandbox\.migration\ledger.json`

## Gaps, Risks, And Oddities

- The unit names imply staged semantic work, but current OpenRewrite application is concentrated into the first source-writing unit.
- `custom_code_change` does not execute code changes; it is recorded as `recorded_not_executed`.
- The `inject_rewrite_plugin(...)` helper exists, and inspected ledgers from older/generated runs include an `openrewrite_plugin.injected` record, but the current approved transform path searched here does not call that helper.
- Final post-transform tests are parsed from Surefire reports produced by the last build validation command; the test agent itself does not execute a fresh test command.
- Profile `openrewrite.apply_allowed: false` coexists with sandbox execution; the approved sandbox transform path still applies OpenRewrite in the sandbox after approval.
- If multiple source-writing units exist, only the first gets the OpenRewrite recipe bundle during execution-plan adaptation.
