# POM Intelligence Summary

## Goal

Create a bounded `PomContextSummary` from existing Maven/POM tools so the LLM can select and justify a governed POM repair path without becoming a free-form POM rewrite engine.

## Current State in Repo

Exact files/classes/functions found:

- `migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py`
  - `scan_root_pom()` detects source Java, Spring Boot version, modules, target stack, warnings.
  - `_detect_spring_boot_version()` handles parent, `spring-boot.version`, `spring.boot.version`, and Spring Boot BOM import.
- `migration_factory/agents/transformation_agent/pom_patches.py`
  - `patch_maven_enforcer_java_version()`.
  - `patch_pom_property()`.
  - `patch_spring_boot_version()`.
  - `detect_spring_boot_version()`, `SpringBootVersionDetection`, `SpringBootVersionPatch`, `PomPropertyPatch`.
- `migration_factory/agents/build_agent/detection.py`
  - `detect_java_project()`, `discover_maven_run_target()`, `full_validation_command()`, `plan_validation_command()`.
- `migration_factory/repair_loop/evidence_collector.py`
  - `_pom_excerpt()` already extracts a redacted POM excerpt from sandbox `pom.xml`.
- `migration_factory/repair_loop/rule_registry.py`
  - POM-only deterministic rules for validation starter, Tomcat override removal, servlet/validation coordinate replacement, H2 dependency, Zalando upgrade.

What already exists:

- POM scanning.
- Spring Boot version detection.
- POM patch helper functions.
- Build command detection.
- Deterministic allowlisted repair rules.

What must not be duplicated:

- New POM parser.
- New POM agent.
- New POM repair engine.
- Free-form POM rewrite.

## Proposed Implementation

Build `PomContextSummary` as a backend-owned artifact/context object:

```text
spring_boot_version
spring_boot_version_location
java_version_property
maven_compiler_release
maven_compiler_source
maven_compiler_target
target_stage_boot
target_stage_java
candidate_deterministic_patch
validation_command
```

Steps:

1. Resolve the failed command sandbox path through backend state.
2. Call existing POM scanner/detection helpers against sandbox `pom.xml`.
3. Use `pom_patches.detect_spring_boot_version()` for version location when available.
4. Use `build_agent/detection.py` to determine validation command, but keep command choice backend-owned.
5. Map observed issue to `rule_registry.ALLOWED_RULE_IDS`.
6. Persist `PomContextSummary` as an artifact ref and add `pom_summary_ref` to ContextPack metadata.
7. Allow the LLM to recommend a deterministic rule id or patch intent with rationale only.
8. Backend applies only allowlisted deterministic patch paths after approval and gate checks.

Operational POM repair flow:

```text
LLM receives PomContextSummary + failure evidence.
LLM identifies mismatch with target stage.
LLM proposes a deterministic rule id or patch intent.
Backend generates/validates patch in sandbox.
Human approves exact proposal checksum.
Repair loop applies.
Maven/test validation reruns.
```

Clarifications:

- The LLM can select and justify the repair path as a typed proposal object.
- The LLM must not free-rewrite full `pom.xml`.
- Backend should generate and validate deterministic POM patches where possible.
- Model-proposed POM intent must resolve to `rule_registry.ALLOWED_RULE_IDS` or a patch-gated proposal before apply.

## Data / Schema Changes

Add `PomContextSummary` as one of:

- A new schema in `v2_model_schemas.py` if it is exchanged with the model.
- A backend artifact JSON if it is only evidence.

Preferred first slice: backend artifact JSON, then cite `pom_summary_ref` in context pack metadata.

Maven/Spring technical basis:

- Maven dependency management centralizes versions in parent/BOM POMs: [Maven dependency mechanism](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html).
- Spring Boot starter parent/BOM manages common dependency versions and default compiler settings: [Spring Boot Maven plugin using guide](https://docs.spring.io/spring-boot/maven-plugin/using.html).
- OpenRewrite Boot 3.5 recipe already updates Spring Boot dependencies, BOM, plugin, and parent versions: [OpenRewrite UpgradeSpringBoot_3_5](https://docs.openrewrite.org/recipes/java/spring/boot3/upgradespringboot_3_5-community-edition).

## Backend Flow

```text
failed command
-> resolve sandbox
-> scan sandbox pom.xml
-> create PomContextSummary artifact
-> attach pom_summary_ref to ContextPack
-> LLM proposes deterministic rule id or POM patch intent
-> backend validates rule through patch_gate/rule_registry
```

## UI / Cockpit Impact

Add a POM Analysis panel only after backend artifact exists:

- Detected Spring Boot version and location.
- Java compiler settings.
- Target stage Java/Boot.
- Candidate deterministic rule.
- Validation command label.
- Artifact preview link.

## Human Supervision Point

The human can say "make it POM-only" or reject a source-changing proposal. Approval card must display paths, rule id, checksum, and reviewer verdict.

## Safety / Governance

- Sandbox only: scanner reads sandbox POM; patch applies only in sandbox.
- No legacy mutation: path resolution must reject legacy source.
- Human approval boundary: LLM recommends rule id or patch intent; human approval remains separate.
- Backend-owned action gate: chat can revise the POM proposal, but resolver, reviewer, approval, patch gate, apply, validation, and ledger stay backend-owned.
- Checksum/proof gates: POM patch must pass approval checksum, patch gate, validation rerun, and ledger.

## Tests

Targeted tests:

- Extend `migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py`.
- Extend tests for `pom_patches.py` if existing in transformation agent tests.
- Extend `tests/test_copilot_repair_loop.py`.
- Add `test_pom_context_summary_uses_existing_scanner`.
- Add `test_pom_context_summary_detects_boot_parent_bom_property`.
- Add `test_pom_context_summary_does_not_apply_patch`.

## Risks

- Treating the POM summary as authority to modify POM directly.
- Missing multi-module POM behavior.
- Producing a deterministic patch suggestion that no allowlisted rule supports.

## Open Questions

- Should the summary include child modules or only root POM for first demo?
- How should target stage Boot/Java be sourced: stage profile, setup, or command manifest?
- UNCERTAIN: `maven_scanner.DEFAULT_TARGET_STACK` still defaults to `3.5.14`; V2 source-of-truth targets must override this at runtime.
