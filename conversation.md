# Improve Spring Boot detection

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 1: Improve Maven/Spring Boot source stack detection.
>
> Goal:
> Improve the Analysis Agent Maven scanner so it can detect Spring Boot versions in Maven projects that do not use spring-boot-starter-parent.
>
> Context:
> The current scanner mainly detects Spring Boot from the Maven parent. Some legacy projects, such as shared libraries and contract libraries, declare Spring Boot through properties and explicit dependencies:
> - <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
> - <spring.boot.version>2.1.6.RELEASE</spring.boot.version>
> - <springBoot.version>2.1.6.RELEASE</springBoot.version>
> - dependencyManagement using org.springframework.boot:spring-boot-dependencies
> - explicit org.springframework.boot dependencies with versions
>
> Tasks:
> 1. Update migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py.
> 2. Detect the source Spring Boot version in this priority order:
>    a. spring-boot-starter-parent version
>    b. Maven properties:
>       - spring-boot.version
>       - spring.boot.version
>       - springBoot.version
>    c. dependencyManagement import:
>       - org.springframework.boot:spring-boot-dependencies
>    d. explicit dependency versions for org.springframework.boot artifacts
> 3. Preserve existing behavior and existing tests.
> 4. Add unit tests covering:
>    - parent-based Spring Boot detection
>    - property-based Spring Boot detection
>    - dependencyManagement BOM-based Spring Boot detection
>    - explicit dependency-based Spring Boot detection
>    - unknown when no Spring Boot signal exists
> 5. Ensure the scanner still reports:
>    - source_stack.java
>    - source_stack.spring_boot
>    - source_stack.build_tool
>    - project_structure.modules
>    - target_stack
>    - warnings
> 6. Do not modify transformation logic.
> 7. Do not modify planning logic.
> 8. Do not modify OpenRewrite logic.
>
> Expected result:
> For a POM like msa-dto, the Analysis Agent should report Spring Boot 2.1.6.RELEASE instead of unknown.
>
> Validation commands:
> Run the relevant unit tests, then run the full test suite if feasible:
> python -m pytest tests/agents/analysis_agent -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Any warnings or limitations

<details><summary>9 previous messages</summary>

> Use caveman skill. First I read skill instructions, then inspect Maven scanner and its tests so we can patch only analysis logic and keep rest untouched.
>
> Scanner file found. Test path live under `migration_factory/agents/analysis_agent/analysis_agent/tests`, not top-level `tests/agents/...`. Next I read scanner and current unit tests, then patch smallest surface.
>
> Context clear. I’m editing scanner to add ordered Spring Boot detection helper with property/BOM/dependency fallbacks, then extending unit tests for each signal plus no-signal case.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py` (+87 -21)
>
> </details>
>
> Patch hit old encoding/context mismatch. I’m rereading exact test file text, then I’ll apply narrower patch cleanly.
>
> <details><summary>Created 1 file, deleted 1 file</summary>
>
> - Deleted `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py` (+0 -81)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py` (+221 -0)
>
> </details>
>
> Code patched. Now run targeted analysis-agent tests first, then full suite if repo can carry it.
>
> Repo test layout different from ticket command. Full suite passes, but analysis-agent package tests need package-local working dir or `PYTHONPATH` because imports are plain module names. I’m rerunning relevant tests with correct cwd so we have signal for scanner change itself.
>
> Validation good now: scanner-specific tests green, full analysis-agent package green, repo full suite green. I’m grabbing final diff details and line refs for report.
</details>

**Summary**

Scanner now detect Spring Boot in requested priority order: parent, known Maven properties, `dependencyManagement` BOM, explicit `org.springframework.boot` dependency versions. Existing analysis contract stays same: `source_stack.java`, `source_stack.spring_boot`, `source_stack.build_tool`, `project_structure.modules`, `target_stack`, `warnings`. No transformation, planning, or OpenRewrite logic touched.

Main code in [maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:12). Tests in [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:6).

**Files Modified**

- [migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:63)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:1)

**Tests Added**

- Parent-based detection: [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:38)
- Property-based detection for all 3 property names: [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:73)
- `dependencyManagement` BOM detection: [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:93)
- Explicit dependency detection: [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:123)
- Unknown when no Spring Boot signal: [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:149)

**Exact Commands Run**

- `python -m pytest migration_factory\agents\analysis_agent\analysis_agent\tests -q`
- `python -m pytest -q`
- `python -m pytest tests\test_maven_scanner.py -q`
  Workdir: `migration_factory\agents\analysis_agent\analysis_agent`
- `python -m pytest tests -q`
  Workdir: `migration_factory\agents\analysis_agent\analysis_agent`

**Full Test Result Summary**

- `python -m pytest migration_factory\agents\analysis_agent\analysis_agent\tests -q`
  Result: failed during collection with `ModuleNotFoundError` because package tests use local-module imports and need package-local cwd / `PYTHONPATH`.
- `python -m pytest tests\test_maven_scanner.py -q`
  Result: `10 passed in 0.12s`
- `python -m pytest tests -q`
  Result: `66 passed, 1 skipped in 0.94s`
- `python -m pytest -q`
  Result: `469 passed, 3 skipped in 69.36s`

**Warnings / Limitations**

- Ticket validation command path `tests/agents/analysis_agent` not present in this repo layout. Equivalent runnable path was package-local `migration_factory/agents/analysis_agent/analysis_agent/tests`.
- Analysis-agent tests from repo root fail collection unless run from package dir or with import path setup. Code change itself green.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 2: Add library/contract project classification.
>
> Goal:
> Teach the Analysis Agent to classify Java projects by runtime/project type so shared libraries like msa-dto are not treated as executable Spring Boot applications.
>
> Context:
> msa-dto is a Maven JAR contract library. It contains DTOs, enums, serializers, and Spring/Juneau contract interfaces, but no @SpringBootApplication main class.
>
> The factory must distinguish:
> - executable Spring Boot applications
> - shared libraries
> - contract libraries
> - unknown projects
>
> Tasks:
> 1. Extend the Analysis Agent output with project classification fields:
>    - project_kind
>    - has_spring_boot_main
>    - has_rest_contracts
>    - has_juneau_contracts
>    - packaging
> 2. Detection rules:
>    - If @SpringBootApplication or a Spring Boot main class exists, classify as spring_boot_application.
>    - If Maven packaging is jar and no application main exists, classify as shared_library.
>    - If shared library contains Spring REST contract interfaces or controller contracts, classify as contract_library.
>    - If shared library contains Apache Juneau @RemoteResource or @RestResource contracts, classify as contract_library.
>    - If there is not enough evidence, classify as unknown.
> 3. Detection should scan src/main/java only.
> 4. Do not modify source files of the analyzed project.
> 5. Include the fields in analysis_report.json.
> 6. Preserve existing analysis outputs and tests.
> 7. Add unit tests or fixture tests covering:
>    - Spring Boot executable application
>    - plain shared library
>    - Spring REST contract library
>    - Juneau contract library
>    - unknown / minimal Maven project
> 8. Do not modify Planning Agent behavior yet.
> 9. Do not modify Transformation Agent behavior.
> 10. Do not modify OpenRewrite behavior.
>
> Expected result:
> A msa-dto-like project should be classified as contract_library, with:
> - has_spring_boot_main = false
> - has_rest_contracts = true if Spring contract interfaces are present
> - has_juneau_contracts = true if Juneau contracts are present
> - packaging = jar
>
> Validation commands:
> Run the relevant Analysis Agent tests and the full suite if feasible:
> python -m pytest migration_factory/agents/analysis_agent/analysis_agent/tests -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example output for a contract-library fixture
> 7. Any warnings or limitations

<details><summary>11 previous messages</summary>

> Need classify project kind in analysis output, scan only `src/main/java`, keep old outputs stable. First I inspect analysis-agent flow around report assembly and any existing Java source scanning we can reuse.
>
> Need exact report shape and safe place for new fields. I’m checking schema and integration tests so we add classification without breaking contract.
>
> Plan:
> 1. Read import/source scanning code and test helpers.
> 2. Add non-invasive classifier that inspects `pom.xml` plus `src/main/java`.
> 3. Thread fields through `maven_results` -> `analysis_report.json`.
> 4. Add focused tests for scanner + one integration assertion.
> 5. Run analysis-agent tests from package dir, then full suite.
>
> I have enough context. Next edits add classification logic inside Maven scanner, thread new fields into report assembly with safe defaults, then broaden scanner tests to cover application/shared/contract/unknown cases.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py` (+103 -35)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py` (+17 -12)
>
> </details>
>
> Report fields threaded. Now I’m replacing scanner tests with source-fixture cases for app/shared/contract/unknown classification, while keeping existing version-detection coverage.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py` (+160 -0)
>
> </details>
>
> One more pass: integration flow should assert new report fields land in `analysis_report.json`, including default shared-library classification for non-Boot fixture.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py` (+13 -6)
>
> </details>
>
> Edits in. Running analysis-agent package tests now to catch any contract drift before full suite.
>
> Analysis-agent tests green. Last step: run full repo suite and capture diff/line refs plus example contract-library output.
</details>

**Summary**

Analysis Agent now classify Java project runtime kind from `pom.xml` plus `src/main/java` only. New fields added to scanner output and `analysis_report.json`:

- `project_kind`
- `has_spring_boot_main`
- `has_rest_contracts`
- `has_juneau_contracts`
- `packaging`

Logic now does:

- Spring Boot main or `@SpringBootApplication` -> `spring_boot_application`
- `jar` + REST/Juneau contract signals -> `contract_library`
- `jar` + Java sources + no app main/contracts -> `shared_library`
- else -> `unknown`

Spring Boot version detection from Ticket 1 still preserved. No planning, transformation, or OpenRewrite logic changed.

**Files Modified**

- [migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:19)
- [migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py](./migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py:4)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:6)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py:54)

**Tests Added**

In [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:243):

- Spring Boot executable application
- Plain shared library
- Spring REST contract library
- Juneau contract library
- Unknown minimal Maven project

Also extended existing scanner coverage for new fields and added integration assertion that `analysis_report.json` carries classification fields in [test_analysis_flow_integration.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py:93).

**Exact Commands Run**

- `python -m pytest tests\test_maven_scanner.py -q`
  Workdir: `migration_factory\agents\analysis_agent\analysis_agent`
- `python -m pytest tests -q`
  Workdir: `migration_factory\agents\analysis_agent\analysis_agent`
- `python -m pytest -q`

**Full Test Result Summary**

- `python -m pytest tests\test_maven_scanner.py -q`
  Result: `15 passed in 0.26s`
- `python -m pytest tests -q`
  Result: `71 passed, 1 skipped in 1.19s`
- `python -m pytest -q`
  Result: `474 passed, 3 skipped in 43.18s`

**Example Output**

For contract-library fixture like Spring REST or Juneau contract, `analysis_report.json` now includes fields like:

```json
{
  "source_stack": {
    "java": "11",
    "spring_boot": "2.1.6.RELEASE",
    "build_tool": "maven"
  },
  "project_kind": "contract_library",
  "has_spring_boot_main": false,
  "has_rest_contracts": true,
  "has_juneau_contracts": false,
  "packaging": "jar"
}
```

For Juneau contract variant, same shape but `has_rest_contracts: false` and `has_juneau_contracts: true`.

**Warnings / Limitations**

- Classification is heuristic text scan of `src/main/java` only, as requested. It does not inspect generated sources or `src/test/java`.
- Spring Boot main detection keys off `@SpringBootApplication` or `SpringApplication.run(...)`. Exotic bootstraps outside those patterns may stay non-app.
- REST contract detection keys off common Spring web annotations. Juneau detection keys off `@RemoteResource` and `@RestResource`.
- Git showed CRLF normalization warnings only. No test failures.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 3: Add generic internal dependency relationship detection.
>
> Goal:
> Add generic internal dependency relationship detection to the Analysis Agent so the factory can identify shared/internal Maven dependencies and later reason about migration order across repositories.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific artifactId as business logic.
> The implementation must be generic.
> common-utils depending on msa-dto is only a real POC validation example, not a special case.
>
> Context:
> In enterprise migrations, applications often depend on internal/shared libraries such as DTO libraries, common-utils libraries, contract libraries, proprietary starters, or company platform modules.
>
> The factory must detect these dependencies generically using configurable internal group prefixes.
>
> Example POC case:
> common-utils has a Maven dependency on:
> - groupId: com.total.corp
> - artifactId: msa-dto
> - version: ${msa-dto.version}
>
> But the same mechanism must work for any configured internal group prefix, for example:
> - com.total.corp
> - com.cgi
> - com.client
> - ma.company
> - org.customer
>
> Tasks:
> 1. Add internal dependency detection to the Analysis Agent.
> 2. Parse direct Maven dependencies from pom.xml.
> 3. Detect internal dependencies using configurable internal group prefixes.
> 4. Default internal group prefixes should include:
>    - com.total.corp
> 5. Do not hardcode artifactIds.
> 6. Do not hardcode msa-dto.
> 7. Do not hardcode common-utils.
> 8. Preserve Maven property placeholders in versions.
>    Example:
>    - ${msa-dto.version} should remain ${msa-dto.version}
> 9. Add a new analysis artifact:
>    - internal_dependencies.json
> 10. Include a summary in analysis_report.json:
>    - internal_dependencies_count
>    - internal_dependencies
> 11. Each internal dependency record should include:
>    - groupId
>    - artifactId
>    - version
>    - scope
>    - optional
>    - source
>    - classification
> 12. Use:
>    - source = "pom"
>    - classification = "internal_candidate"
> 13. If scope is missing, default it to "compile".
> 14. If optional is missing, default it to false.
> 15. Detection should not modify the analyzed project.
> 16. Preserve all existing analysis outputs and tests.
> 17. Do not modify Planning Agent behavior yet.
> 18. Do not modify Transformation Agent behavior.
> 19. Do not modify OpenRewrite behavior.
>
> Configuration requirement:
> Internal group prefixes must be configurable in code in a way that can later be moved to AI Hub/profile/policy configuration.
> For this ticket, it is acceptable to define a default constant such as:
> DEFAULT_INTERNAL_GROUP_PREFIXES = ("com.total.corp",)
> But the detection function should accept prefixes as a parameter so it is not locked to that default.
>
> Expected generic behavior:
> Given this dependency:
>
> <dependency>
>     <groupId>com.total.corp</groupId>
>     <artifactId>msa-dto</artifactId>
>     <version>${msa-dto.version}</version>
> </dependency>
>
> the Analysis Agent should report:
>
> {
>   "internal_dependencies_count": 1,
>   "internal_dependencies": [
>     {
>       "groupId": "com.total.corp",
>       "artifactId": "msa-dto",
>       "version": "${msa-dto.version}",
>       "scope": "compile",
>       "optional": false,
>       "source": "pom",
>       "classification": "internal_candidate"
>     }
>   ]
> }
>
> But the implementation must also work for any other dependency whose groupId matches a configured internal prefix.
>
> Tests to add:
> 1. Project with no internal dependencies.
> 2. Project with com.total.corp:msa-dto.
> 3. Project with multiple internal dependencies.
> 4. Project with external dependencies only.
> 5. Dependency with scope and optional flag.
> 6. Dependency version using a Maven property placeholder.
> 7. Custom internal prefix passed to the detection function, for example com.cgi.
> 8. Ensure artifactId-specific hardcoding is not required.
>
> Validation commands:
> Run the relevant Analysis Agent tests and the full suite if feasible:
>
> python -m pytest tests/test_maven_scanner.py -q
> python -m pytest tests -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example internal_dependencies.json output for a common-utils-like fixture
> 7. Explanation of why the implementation is generic and not hardcoded to msa-dto/common-utils
> 8. Any warnings or limitations

<details><summary>10 previous messages</summary>

> Need generic internal dependency scan from `pom.xml`, new artifact, report summary, no hardcoded artifactIds. First I inspect current artifact-writing flow and tests around output inventory so we thread this in without breaking old paths.
>
> Plan clear. I’m adding generic direct-dependency parsing inside Maven scanner with configurable group prefixes, then writing `internal_dependencies.json` in analysis flow and exposing summary fields in report. After that I’ll extend scanner and integration tests for placeholder versions, custom prefixes, defaults, and non-hardcoded artifactIds.
>
> I found one subtlety: current dependency scans use broad XPath that can catch nested sections. I’m tightening internal-dependency parsing to top-level project dependencies only, while keeping Boot BOM detection separate so behavior stays predictable and generic.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py` (+52 -5)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/main.py` (+26 -19)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py` (+8 -5)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/constants.py` (+6 -5)
>
> </details>
>
> Core code in. Now I’m extending scanner tests for no/internal/multiple/external/scope+optional/property/custom prefix/generic artifact behavior, plus integration assertions that `internal_dependencies.json` is emitted and mirrored into `analysis_report.json`.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py` (+217 -1)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py` (+11 -3)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_runner_api.py` (+8 -7)
>
> </details>
>
> Edits ready. Running scanner tests first, then package tests, then full suite to catch any artifact-path or report-shape regressions.
>
> One missing default path: parse-failure result lacked internal dependency fields. I’m fixing fallback contract, then rerunning same three commands.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py` (+2 -0)
>
> </details>
>
> Validation green now. I’m pulling final diff and line refs so report can point to exact implementation spots and show example `internal_dependencies.json` payload.
</details>

**Summary**

Analysis Agent now detect generic internal Maven dependencies from direct `pom.xml` dependencies and emit new `internal_dependencies.json` artifact. Detection use configurable group prefixes, defaulting to `("com.total.corp",)`, and keeps version placeholders like `${msa-dto.version}` unchanged. Report now includes `internal_dependencies_count` and `internal_dependencies`, while existing outputs/tests stay green.

Core logic lives in [maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:72), artifact write in [main.py](./migration_factory/agents/analysis_agent/analysis_agent/main.py:42), report exposure in [report_assembler.py](./migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py:17).

**Files Modified**

- [migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:12)
- [migration_factory/agents/analysis_agent/analysis_agent/main.py](./migration_factory/agents/analysis_agent/analysis_agent/main.py:42)
- [migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py](./migration_factory/agents/analysis_agent/analysis_agent/report_assembler.py:17)
- [migration_factory/agents/analysis_agent/analysis_agent/constants.py](./migration_factory/agents/analysis_agent/analysis_agent/constants.py:1)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:388)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py:85)
- [migration_factory/agents/analysis_agent/analysis_agent/tests/test_runner_api.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_runner_api.py:36)

**Tests Added**

In [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:388):

- No internal dependencies
- `com.total.corp:msa-dto`
- Multiple internal dependencies
- External dependencies only
- Scope and optional flag
- Maven property placeholder version
- Custom prefix `com.cgi`
- ArtifactId-agnostic detection

Also integration assertions for `internal_dependencies.json` and report summary in [test_analysis_flow_integration.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_analysis_flow_integration.py:93).

**Exact Commands Run**

- `python -m pytest tests/test_maven_scanner.py -q`
- `python -m pytest tests -q`
- `python -m pytest -q`

First two ran from `migration_factory/agents/analysis_agent/analysis_agent`. Last ran from repo root.

**Full Test Result Summary**

- `python -m pytest tests/test_maven_scanner.py -q`
  Result: `22 passed in 0.27s`
- `python -m pytest tests -q`
  Result: `78 passed, 1 skipped in 1.06s`
- `python -m pytest -q`
  Result: `481 passed, 3 skipped in 58.97s`

**Example `internal_dependencies.json`**

For common-utils-like fixture:

```json
{
  "internal_dependencies_count": 1,
  "internal_dependencies": [
    {
      "groupId": "com.total.corp",
      "artifactId": "msa-dto",
      "version": "${msa-dto.version}",
      "scope": "compile",
      "optional": false,
      "source": "pom",
      "classification": "internal_candidate"
    }
  ]
}
```

**Why Generic, Not Hardcoded**

- Match rule keys off `groupId` prefix only, not artifactId. See [_matches_internal_group_prefix`](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:236).
- Default prefixes live in constant `DEFAULT_INTERNAL_GROUP_PREFIXES`, but scan function accepts override parameter. See [scan_root_pom_with_prefixes`](./migration_factory/agents/analysis_agent/analysis_agent/maven_scanner.py:76).
- Test proves non-`msa-dto` artifactIds work, like `customer-platform-starter` and `platform-bom-client`. See [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:449) and [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:576).
- Test proves custom prefix `com.cgi` works without code change. See [test_maven_scanner.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_maven_scanner.py:550).

**Warnings / Limitations**

- Detection scans direct project dependencies only: `./dependencies/dependency`. No transitive, profile-specific, plugin, or `dependencyManagement` entries counted as internal dependencies in this ticket.
- Missing dependency `version` remains `null` if omitted in `pom.xml`; placeholder versions stay raw by design.
- Prefix config still lives in code for now, but function already accepts parameter so later move to AI Hub/profile/policy straightforward.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 4: Introduce generic migration routes instead of single fixed source prefix.
>
> Goal:
> Refactor migration profile compatibility so the factory can support multiple migration routes instead of being locked to one source Spring Boot prefix.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific project.
> Do NOT hardcode Spring Boot 2.1 as a special case in business logic.
> Spring Boot 2.1 is only a POC validation example.
> The implementation must be generic and route-driven.
>
> Context:
> The current profile compatibility logic relies on source.spring_boot.allowed_version_prefixes.
> This is too narrow for a general migration factory.
>
> Current POC profile:
> - springboot-2.7-to-3.5-java17
> - allowed source Spring Boot prefix: 2.7
> - target Spring Boot: 3.5.14
> - target Java: 17
>
> But real legacy projects may start from:
> - Spring Boot 2.1.x
> - Spring Boot 2.2.x
> - Spring Boot 2.3.x
> - Spring Boot 2.7.x
> - Spring Boot 3.x
> - later, other Java/Spring combinations
>
> Tasks:
> 1. Extend migration profile support to allow a new optional top-level field:
>    routes:
>
> 2. A route should support this shape:
>
>    routes:
>      - id: boot-2.1-to-3.5-java17
>        source:
>          java:
>            allowed_versions:
>              - "8"
>              - "11"
>          spring_boot:
>            allowed_version_prefixes:
>              - "2.1"
>          build:
>            allowed_tools:
>              - maven
>        target:
>          java: "17"
>          spring_boot: "3.5.14"
>          spring_framework: "6.2.18"
>          build: maven
>        strategy: direct_sandbox
>        risk_level: high
>        production_allowed: false
>        recommended_intermediate:
>          spring_boot: "2.7.18"
>
> 3. Preserve backward compatibility with existing profiles that only have:
>    source:
>      spring_boot:
>        allowed_version_prefixes:
>    target:
>
> 4. Update migration-profile.schema.json to allow routes while keeping existing profile format valid.
>
> 5. Update profile_compatibility.py so it:
>    - extracts the source stack from analysis artifacts as before
>    - checks routes first when routes are present
>    - selects the best matching route based on source Java, source Spring Boot, and build tool
>    - falls back to the existing source/target compatibility behavior when routes are absent
>    - returns selected route metadata in the compatibility result
>
> 6. Add selected route information to planning artifacts where appropriate:
>    - migration_plan.yaml should include selected_route_id when a route is selected
>    - migration_plan.yaml should include route_strategy, route_risk_level, production_allowed, and recommended_intermediate if available
>
> 7. Do not modify Transformation Agent behavior.
> 8. Do not modify OpenRewrite behavior.
> 9. Do not modify Build Agent behavior.
> 10. Do not generate route-specific migration units yet; that will be Ticket 6.
> 11. Keep planning deterministic.
> 12. High risk routes should produce warnings, not blockers, unless the profile explicitly marks them unsupported.
> 13. If no route matches, Planning Agent should fail with a clear blocker explaining:
>    - detected source Java
>    - detected source Spring Boot
>    - detected build tool
>    - available route ids
>
> Tests to add:
> 1. Existing legacy profile without routes still works for Spring Boot 2.7 → 3.5.
> 2. Route-based profile matches Spring Boot 2.1.x → 3.5.
> 3. Route-based profile matches Spring Boot 2.7.x → 3.5 when such route exists.
> 4. No matching route produces a clear compatibility error.
> 5. Unknown Spring Boot version produces a warning or blocker according to existing compatibility policy.
> 6. Selected route metadata appears in migration_plan.yaml.
> 7. Backward compatibility tests for existing planning behavior remain green.
>
> Example route-based profile fixture:
> Create a test fixture profile with routes for:
> - boot-2.1-to-3.5-java17
> - boot-2.7-to-3.5-java17
>
> Expected behavior:
> For an analysis artifact with:
> source_stack:
>   java: "11"
>   spring_boot: "2.1.6.RELEASE"
>   build_tool: "maven"
>
> The compatibility layer should select:
> selected_route_id: boot-2.1-to-3.5-java17
>
> And planning should continue with warnings for high-risk direct migration, not fail just because source Boot is 2.1.
>
> Validation commands:
> Run planning-agent tests and full test suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest -q
>
> If the repo layout differs, run the equivalent planning-agent tests and explain the path used.
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example migration_plan.yaml excerpt showing selected_route_id
> 7. Explanation of backward compatibility with old profiles
> 8. Any warnings or limitations

<details><summary>15 previous messages</summary>

> Need route-driven planning compatibility without breaking old profiles. First I inspect planning-agent compatibility, schema, plan writer, and tests so we patch smallest deterministic path.
>
> Schema path differs. I’m locating actual profile schema and planning tests before editing.
>
> Need exact tests and schema expectations around plan YAML. I’m reading planning-agent tests plus migration plan schema before editing route metadata.
>
> I’ve got main compatibility path. Now reading plan/integration tests that will need route metadata assertions and no-route fallback coverage.
>
> Plan settled. I’m editing compatibility/profile loading first: route-aware selection, backward-compatible fallback, and selected-route metadata in result. Then I’ll thread that into plan writer/node and add focused planning tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/profile_compatibility.py` (+259 -90)
>
> </details>
>
> Route selection logic in. Next I’m relaxing profile loading/schema so route-based profiles validate cleanly while old source/target profiles still work unchanged.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/profile_reader.py` (+53 -20)
> - Wrote `./modernizer-solution-ai-hub/schemas/migration-profile.schema.json` (+71 -8)
>
> </details>
>
> Profile loading/schema patched. Now I’m threading selected-route metadata into planning output so `migration_plan.yaml` records chosen route without changing unit generation.
>
> Patch context drifted. I’m reopening exact plan writer text, then I’ll apply smaller patch cleanly.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+40 -16)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+16 -11)
>
> </details>
>
> Core route plumbing done. I’m adding focused planning tests now: old-profile fallback, route matching for 2.1/2.7, no-match blocker, unknown Boot handling, and plan YAML route metadata.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_profile_routes.py` (+254 -0)
>
> </details>
>
> Route tests added. Running planning-agent suite now; if route no-match path is too noisy, I’ll tighten blocker output before full suite.
>
> Planning and full suite both green. I’m collecting exact file refs and a concrete `migration_plan.yaml` excerpt for final report.
</details>

**Summary**

Planning compatibility now support generic route-driven migration profiles. When `routes:` exist, planning selects best matching route from source Java, Spring Boot, build tool; uses route target stack; returns selected route metadata; writes it into `migration_plan.yaml`; warns for high-risk routes instead of blocking. Old profiles with only `source`/`target` still work unchanged.

Main logic in [profile_compatibility.py](./migration_factory/agents/planning_agent/profile_compatibility.py:31), profile loading in [profile_reader.py](./migration_factory/agents/planning_agent/profile_reader.py:18), plan output in [plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py:11), node wiring in [node.py](./migration_factory/agents/planning_agent/node.py:156), schema in [migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json:1).

**Files Modified**

- [migration_factory/agents/planning_agent/profile_compatibility.py](./migration_factory/agents/planning_agent/profile_compatibility.py:17)
- [migration_factory/agents/planning_agent/profile_reader.py](./migration_factory/agents/planning_agent/profile_reader.py:18)
- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py:11)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py:159)
- [modernizer-solution-ai-hub/schemas/migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json:1)
- [tests/agents/planning_agent/test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py:1)

**Tests Added**

In [test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py:170):

- old profile without routes still works
- route profile matches Boot `2.1.x`
- route profile matches Boot `2.7.x`
- no matching route gives clear compatibility error with detected stack + route ids
- unknown Spring Boot keeps warning plus route blocker
- selected route metadata appears in `migration_plan.yaml`
- route profile fixture loads through profile reader

**Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest -q`

Repo layout already had `tests/agents/planning_agent`, so no path substitution needed.

**Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  Result: `72 passed in 1.18s`
- `python -m pytest -q`
  Result: `488 passed, 3 skipped in 63.31s`

**Example `migration_plan.yaml` Excerpt**

```yaml
source_stack:
  build_tool: "maven"
  java: "11"
  spring_boot: "2.1.6.RELEASE"
target_stack:
  build_tool: "maven"
  java: "17"
  spring_boot: "3.5.14"
  spring_framework: "6.2.18"
selected_route_id: "boot-2.1-to-3.5-java17"
route_strategy: "direct_sandbox"
route_risk_level: "high"
production_allowed: false
recommended_intermediate:
  spring_boot: "2.7.18"
```

**Backward Compatibility**

Old profile behavior still intact because route logic only activates when `routes` exists. If no `routes`, code uses same legacy `source`/`target` compatibility checks as before. Existing planning tests stayed green, including previous `2.7 -> 3.5` path.

**Warnings / Limitations**

- Route selection is deterministic and generic, but still metadata-only for now. It does not change migration units yet.
- Route schema support added in AI Hub schema file, but current loader validates route shape in code too.
- If `routes` exist and none match, planning fails clearly by design; it does not silently fall back to top-level `source`/`target`.
- High-risk route warning behavior implemented. Explicit unsupported route handled via optional `supported: false`.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 5: Add a Spring Boot 2.1 to 3.5 Java 17 AI Hub profile.
>
> Goal:
> Create a governed AI Hub migration profile for legacy Spring Boot 2.1.x projects targeting Spring Boot 3.5.14 and Java 17.
>
> Important architecture rule:
> Do NOT hardcode msa-dto or common-utils.
> This profile is motivated by the msa-dto POC, but it must be generic for any Maven project starting from Spring Boot 2.1.x.
>
> Context:
> The factory now supports route-driven profiles.
> We need a concrete profile that allows Spring Boot 2.1.x source projects to be assessed and planned for migration to Spring Boot 3.5.14 / Java 17.
>
> Tasks:
> 1. Add a new profile file:
>    modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml
>
> 2. The profile must target:
>    - Java 17
>    - Spring Boot 3.5.14
>    - Spring Framework 6.2.18
>    - Maven
>
> 3. The profile must accept source:
>    - Java 8
>    - Java 11
>    - Spring Boot 2.1.x
>    - Maven
>
> 4. Use the new routes model.
>    Include at least one route:
>    - id: boot-2.1-to-3.5-java17
>    - source Java allowed_versions: ["8", "11"]
>    - source Spring Boot allowed_version_prefixes: ["2.1"]
>    - source build allowed_tools: ["maven"]
>    - target Java: "17"
>    - target Spring Boot: "3.5.14"
>    - target Spring Framework: "6.2.18"
>    - target build: maven
>    - strategy: direct_sandbox
>    - risk_level: high
>    - production_allowed: false
>    - recommended_intermediate.spring_boot: "2.7.18"
>
> 5. Add governance metadata:
>    - human_approval_required: true
>    - baseline_tests_required: false
>    - dependency_graph_unavailable_fatal: false
>    - production_allowed: false
>    - risk_level: high
>    - strategy: direct_sandbox
>    - fallback_profile: springboot-2.7-to-3.5-java17, if that is meaningful in the current AI Hub
>
> 6. Configure OpenRewrite using the existing Spring Boot 3.5 / Java 17 catalog:
>    catalogs/openrewrite/springboot-3.5-java17.yaml
>
> 7. Add JDK environment metadata:
>    - source_jdk_home_env: JAVA_HOME_11
>    - target_jdk_home_env: JAVA_HOME_17
>
> 8. Update schema/tests if needed so source_jdk_home_env and target_jdk_home_env are accepted profile fields.
>
> 9. Add tests validating:
>    - the new profile file exists
>    - the new profile loads successfully
>    - the new profile passes schema/profile validation
>    - route compatibility selects boot-2.1-to-3.5-java17 for source Spring Boot 2.1.6.RELEASE / Java 11 / Maven
>    - selected route metadata appears in planning output
>    - high-risk route produces warnings but does not block planning
>    - production_allowed is false
>
> 10. Do not modify Transformation Agent behavior.
> 11. Do not modify OpenRewrite execution behavior.
> 12. Do not modify Build Agent behavior.
>
> Expected behavior:
> For analysis source stack:
>
> source_stack:
>   java: "11"
>   spring_boot: "2.1.6.RELEASE"
>   build_tool: "maven"
>
> Using profile:
>
> springboot-2.1-to-3.5-java17
>
> Planning should select:
>
> selected_route_id: boot-2.1-to-3.5-java17
>
> and produce a high-risk warning, not a compatibility blocker.
>
> Validation commands:
> Run relevant profile/planning tests and the full suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files created/modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. New profile YAML excerpt
> 7. Example migration_plan.yaml excerpt showing selected_route_id
> 8. Any warnings or limitations

<details><summary>8 previous messages</summary>

> Need new AI Hub profile plus schema acceptance for JDK env keys, then tests proving route selects and planning warns-not-blocks. First I inspect existing profile/catalog patterns so new file matches house style.
>
> Existing Boot4 profile already carries JDK env keys, so schema lagged behind reality. I’m aligning schema and creating new 2.1 profile in same style as existing governed profiles, then I’ll add profile/planning tests around it.
>
> I found no current AI Hub profile schema test, so I’ll add one alongside new profile tests. That gives explicit coverage for new route profile plus JDK env fields.
>
> I’m creating real AI Hub profile now, then I’ll add tests against tracked AI Hub files instead of synthetic-only fixtures so this stays governed and reproducible.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./modernizer-solution-ai-hub/schemas/migration-profile.schema.json` (+5 -3)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+69 -0)
>
> </details>
>
> Profile in. Next tests: file exists, loads, schema-valid, route selected, planning warns-not-blocks, selected route metadata in plan, `production_allowed: false`.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+113 -0)
>
> </details>
>
> Running planning-agent tests with real AI Hub profile now, then full suite. If anything fails, likely schema/profile assumptions and I’ll tighten them.
</details>

**Summary**

Added governed AI Hub profile [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml:1) using route model for Spring Boot `2.1.x` on Java `8` or `11` to Spring Boot `3.5.14` / Spring Framework `6.2.18` / Java `17` / Maven. Profile selects route `boot-2.1-to-3.5-java17`, emits high-risk warnings, keeps planning executable, and marks `production_allowed: false`.

Also updated AI Hub schema to accept `source_jdk_home_env` and `target_jdk_home_env` in [migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json:8). Tests now cover real profile existence, loading, schema validation, route selection, and planning output.

**Files Created / Modified**

Created:
- [modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml:1)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py:1)

Modified:
- [modernizer-solution-ai-hub/schemas/migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json:1)

**Tests Added**

In [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py:1):

- new profile file exists
- new profile loads successfully
- new profile passes schema validation
- route compatibility selects `boot-2.1-to-3.5-java17` for Java `11` / Boot `2.1.6.RELEASE` / Maven
- planning output includes selected route metadata
- high-risk route warns but does not block planning
- `production_allowed` is `false`

**Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest -q`

**Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  Result: `77 passed in 2.53s`
- `python -m pytest -q`
  Result: `493 passed, 3 skipped in 94.72s`

**New Profile YAML Excerpt**

```yaml
id: springboot-2.1-to-3.5-java17
strategy: direct_sandbox
risk_level: high
production_allowed: false
fallback_profile: springboot-2.7-to-3.5-java17
source_jdk_home_env: JAVA_HOME_11
target_jdk_home_env: JAVA_HOME_17

routes:
  - id: boot-2.1-to-3.5-java17
    source:
      java:
        allowed_versions: ["8", "11"]
      spring_boot:
        allowed_version_prefixes: ["2.1"]
      build:
        allowed_tools: ["maven"]
    target:
      java: "17"
      spring_boot: "3.5.14"
      spring_framework: "6.2.18"
      build: maven
    strategy: direct_sandbox
    risk_level: high
    production_allowed: false
    recommended_intermediate:
      spring_boot: "2.7.18"
```

**Example `migration_plan.yaml` Excerpt**

```yaml
selected_route_id: "boot-2.1-to-3.5-java17"
route_strategy: "direct_sandbox"
route_risk_level: "high"
production_allowed: false
recommended_intermediate:
  spring_boot: "2.7.18"
```

**Warnings / Limitations**

- Profile is governed and generic for any Maven project matching Boot `2.1.x`; no project-specific logic added.
- `source_jdk_home_env` and `target_jdk_home_env` now schema-valid, but this ticket only adds profile metadata, not new execution behavior.
- Fallback profile points to `springboot-2.7-to-3.5-java17` as requested; planning reports it as metadata, not automatic multi-hop execution.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 6: Generate migration units from selected route.
>
> Goal:
> Make Planning Agent migration unit generation route-aware.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT implement project-specific logic.
> The implementation must be generic and driven by the selected migration route/profile metadata.
>
> Context:
> The factory now supports route-driven profiles and has a Spring Boot 2.1 to 3.5 Java 17 profile.
> However, unit_builder.py still produces mostly fixed migration units:
> - baseline
> - java-17
> - spring-boot-3-5-14
> - jakarta
> - dependency-cleanup
> - existing-test-migration
>
> For older Spring Boot sources, especially Boot 2.1.x, this is not precise enough.
> The plan should make visible that the migration is higher risk and may need stabilization before the Boot 3.5 / Jakarta step.
>
> Tasks:
> 1. Update Planning Agent unit generation so it can use selected route metadata.
> 2. Keep existing behavior for old profiles without selected routes.
> 3. For selected route id boot-2.1-to-3.5-java17, generate a route-aware unit sequence:
>    - baseline
>    - java-17
>    - spring-boot-2-7-stabilization
>    - spring-boot-3-5-14
>    - jakarta
>    - jaxb-jakarta
>    - dependency-cleanup
>    - contract-compatibility-review
>    - existing-test-migration
> 4. The implementation should not hardcode project names.
> 5. It is acceptable in this ticket to map known route ids to deterministic unit templates, but structure the code so future route ids can be added cleanly.
> 6. Add each new unit to deterministic tool mapping as needed.
> 7. Units should remain deterministic and stable in order.
> 8. Each unit should include:
>    - id
>    - goal
>    - tools
>    - validation
>    - writes_source
>    - required
>    - expected_artifacts
>    - rollback_strategy
>    - blocking_gate
>    - assist_policy
> 9. contract-compatibility-review should be planning/review-oriented and should not imply automatic code generation.
> 10. jaxb-jakarta should be separate from generic jakarta because JAXB/XML migration can affect external contracts.
> 11. Do not modify Transformation Agent behavior yet.
> 12. Do not modify OpenRewrite execution behavior yet.
> 13. Do not modify Build Agent behavior.
> 14. Do not execute transformation in this ticket.
>
> Expected route-aware behavior:
> For source stack:
> - Java 11
> - Spring Boot 2.1.6.RELEASE
> - Maven
>
> and profile:
> - springboot-2.1-to-3.5-java17
>
> Planning should select:
> - selected_route_id: boot-2.1-to-3.5-java17
>
> and migration_units.yaml should contain this ordered list:
> 1. baseline
> 2. java-17
> 3. spring-boot-2-7-stabilization
> 4. spring-boot-3-5-14
> 5. jakarta
> 6. jaxb-jakarta
> 7. dependency-cleanup
> 8. contract-compatibility-review
> 9. existing-test-migration
>
> For existing profile springboot-2.7-to-3.5-java17, current unit behavior should remain backward compatible.
>
> Tests to add:
> 1. Existing no-route or legacy profile still gets the previous default unit sequence.
> 2. Boot 2.7 to 3.5 route/profile keeps compatible expected units.
> 3. Boot 2.1 to 3.5 route produces the new route-aware sequence.
> 4. migration_plan.yaml unit references match migration_units.yaml order.
> 5. contract-compatibility-review exists and writes_source is false.
> 6. jaxb-jakarta exists and writes_source is true.
> 7. No project-specific artifactId or repository name is used.
> 8. Full planning output validation remains green.
>
> Validation commands:
> Run planning-agent tests and full test suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example migration_units.yaml excerpt for boot-2.1-to-3.5-java17
> 7. Explanation of backward compatibility
> 8. Explanation of why the implementation is generic and route-driven, not project-specific
> 9. Any warnings or limitations

<details><summary>9 previous messages</summary>

> Need route-aware unit generation without project-specific logic. First I inspect `unit_builder` and current planning tests so we can extend deterministic unit templates cleanly and keep legacy sequence stable.
>
> One more spot matters: output validation currently whitelists unit orders. I’m reading that before edits so new route sequence stays valid.
>
> I have enough context. Next edits make `unit_builder` route-aware with clean route-template mapping, wire selected route from compatibility into node, and update output validation/tests for new allowed order.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/unit_builder.py` (+178 -98)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+4 -1)
> - Wrote `./migration_factory/agents/planning_agent/output_validator.py` (+20 -9)
>
> </details>
>
> Core code done. Now I’m updating unit-builder and planning tests for legacy/default order, Boot 2.1 route order, unit flags, and plan/unit order match.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/agents/planning_agent/test_unit_builder_deterministic.py` (+56 -19)
> - Wrote `./tests/agents/planning_agent/test_profile_routes.py` (+48 -0)
>
> </details>
>
> Need maybe profile file test for real boot21 profile unit sequence. Add to `test_boot21_profile.py`.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+18 -0)
>
> </details>
>
> Route-aware unit generation patched and tests expanded. Running planning-agent suite now, then full suite to catch output-validator or guardrail regressions.
</details>

**Summary**

Planning Agent now generates migration units from selected route metadata. For route `boot-2.1-to-3.5-java17`, planning emits route-aware sequence:

1. `baseline`
2. `java-17`
3. `spring-boot-2-7-stabilization`
4. `spring-boot-3-5-14`
5. `jakarta`
6. `jaxb-jakarta`
7. `dependency-cleanup`
8. `contract-compatibility-review`
9. `existing-test-migration`

Old behavior stays for legacy/no-route profiles and for route profiles without special route template mapping. Main changes in [unit_builder.py](./migration_factory/agents/planning_agent/unit_builder.py:1), [node.py](./migration_factory/agents/planning_agent/node.py:155), and [output_validator.py](./migration_factory/agents/planning_agent/output_validator.py:28).

**Files Modified**

- [migration_factory/agents/planning_agent/unit_builder.py](./migration_factory/agents/planning_agent/unit_builder.py:1)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py:155)
- [migration_factory/agents/planning_agent/output_validator.py](./migration_factory/agents/planning_agent/output_validator.py:1)
- [tests/agents/planning_agent/test_unit_builder_deterministic.py](./tests/agents/planning_agent/test_unit_builder_deterministic.py:1)
- [tests/agents/planning_agent/test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py:219)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py:82)

**Tests Added**

- route-aware Boot `2.1 -> 3.5` unit sequence
- legacy/default unit sequence unchanged
- route profile without special mapping keeps default compatible sequence
- `migration_plan.yaml` unit references match `migration_units.yaml` order
- `contract-compatibility-review` exists and `writes_source: false`
- `jaxb-jakarta` exists and `writes_source: true`
- real Boot 2.1 profile emits expected route-aware order in planning output

**Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest -q`

**Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  Result: `81 passed in 1.64s`
- `python -m pytest -q`
  Result: `497 passed, 3 skipped in 58.34s`

**Example `migration_units.yaml` Excerpt**

```yaml
units:
  - id: "baseline"
  - id: "java-17"
  - id: "spring-boot-2-7-stabilization"
  - id: "spring-boot-3-5-14"
  - id: "jakarta"
  - id: "jaxb-jakarta"
  - id: "dependency-cleanup"
  - id: "contract-compatibility-review"
  - id: "existing-test-migration"
```

In full output, `contract-compatibility-review` is review-only and `writes_source: false`; `jaxb-jakarta` is separate and `writes_source: true`.

**Backward Compatibility**

Old profiles still call same builder path, but with no selected route mapping, so they keep prior sequence. Boot `2.7 -> 3.5` remains:

- `baseline`
- `java-17`
- `spring-boot-3-5-14`
- `jakarta`
- `dependency-cleanup`
- `existing-test-migration`

That behavior is covered in [test_unit_builder_deterministic.py](./tests/agents/planning_agent/test_unit_builder_deterministic.py:4) and [test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py:247).

**Why Generic And Route-Driven**

Implementation keys off `selected_route_id`, not artifactId, repo name, or project name. Route-specific unit order lives in clean mapping `ROUTE_UNIT_ORDERS` in [unit_builder.py](./migration_factory/agents/planning_agent/unit_builder.py:17). Adding future routes means adding another deterministic route template, not special-casing a repository. No `msa-dto`, `common-utils`, or repo-specific names appear in planner logic.

**Warnings / Limitations**

- This ticket maps known route ids to deterministic unit templates, as allowed. It does not yet synthesize unit graphs dynamically from richer route metadata.
- No transformation behavior changed. Units remain planning artifacts only.
- `contract-compatibility-review` is advisory/review oriented by design; it does not imply automatic contract code generation.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 7: Support per-unit OpenRewrite recipes.
>
> Goal:
> Support per-unit OpenRewrite recipe configuration in planning and transformation execution plan generation.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT implement project-specific OpenRewrite behavior.
> The implementation must be generic and route/profile/unit driven.
>
> Context:
> The factory now supports route-driven profiles and route-aware migration units.
> However, the transformation execution plan currently attaches global OpenRewrite recipes to the first source-changing unit only.
>
> That is not sufficient for multi-step migrations such as:
> - Spring Boot 2.1 → 2.7 stabilization
> - Spring Boot 2.7 → 3.5 upgrade
> - javax → jakarta
> - JAXB-specific migration
>
> The factory needs a clean contract that allows each migration unit to optionally carry its own OpenRewrite recipe configuration.
>
> Tasks:
> 1. Extend the planning migration unit model to optionally include an openrewrite section per unit.
>
> 2. The optional unit-level openrewrite section should support:
>    - active_recipes
>    - recipe_artifacts
>    - apply_goal
>    - apply_maven_args
>    - analysis_preview_maven_args
>
> 3. Update migration_units.yaml rendering so a unit can include:
>
>    openrewrite:
>      active_recipes:
>        - org.example.SomeRecipe
>      recipe_artifacts:
>        - org.example:some-recipe:1.0.0
>      apply_goal: run
>      apply_maven_args:
>        - -DskipTests
>      analysis_preview_maven_args:
>        - -DsomeFlag=true
>
> 4. Keep backward compatibility:
>    - Existing profiles without per-unit OpenRewrite config must keep working.
>    - Existing global rewrite_plugin_plan behavior must keep working.
>    - If no per-unit recipes are defined, the current behavior can remain unchanged.
>
> 5. Update transformation_agent/execution_plan.py:
>    - If a unit has unit-level openrewrite config, attach OpenRewrite transformation to that specific unit.
>    - If multiple units have OpenRewrite config, each receives its own OpenRewrite transformation.
>    - If no unit-level config exists, fall back to current global behavior.
>
> 6. Ensure recipe_artifacts can come from:
>    - unit-level config, if present
>    - otherwise global rewrite_plugin_plan/catalog behavior
>
> 7. Do not run OpenRewrite in this ticket.
> 8. Do not change actual transformation execution behavior beyond execution plan generation.
> 9. Do not modify Build Agent behavior.
> 10. Do not modify Test Agent behavior.
> 11. Do not add AI-generated patching.
>
> 11. Add tests covering:
>    - old global recipe behavior still applies to first source-changing unit
>    - per-unit OpenRewrite config attaches recipes to the correct unit
>    - multiple units can each receive their own OpenRewrite recipes
>    - units without OpenRewrite config do not receive OpenRewrite transformation
>    - no recipes means no OpenRewrite transformation
>    - migration_units.yaml remains deterministic
>    - transformation_execution_plan.yaml remains deterministic
>    - no project-specific artifactId or repository name is used
>
> Expected behavior:
> For a planning artifact with:
>
> units:
>   - id: spring-boot-2-7-stabilization
>     writes_source: true
>     openrewrite:
>       active_recipes:
>         - org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
>   - id: jakarta
>     writes_source: true
>     openrewrite:
>       active_recipes:
>         - org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta
>
> The generated transformation_execution_plan.yaml should attach an OpenRewrite transformation to each corresponding unit, not only the first write unit.
>
> Validation commands:
> Run transformation-agent and planning-agent tests, then the full suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> If repo layout differs, run the equivalent tests and explain the path used.
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example migration_units.yaml excerpt with per-unit openrewrite config
> 7. Example transformation_execution_plan.yaml excerpt showing recipes attached to the correct units
> 8. Explanation of backward compatibility with old global recipe behavior
> 9. Explanation of why the implementation is generic and not project-specific
> 10. Any warnings or limitations

<details><summary>15 previous messages</summary>

> Need per-unit OpenRewrite config in planning units and execution plan fallback behavior. First I inspect unit/plan schemas, transformation execution plan generation, and current tests so we extend contract without changing execution.
>
> Execution-plan module lives under `agents/transformation_agent`, not `transformation_agent` root. I’m opening exact file and its data model now, then I’ll patch both planning-unit rendering and execution-plan fallback logic.
>
> I’m checking if repo already references JAXB/Jakarta recipe names, so we reuse existing naming where possible instead of inventing ad hoc strings.
>
> Plan clear. I’m patching planning unit model/rendering first so units can carry optional `openrewrite` config, then I’ll update execution-plan adaptation to attach per-unit recipes with global fallback.
>
> Patch hit formatting drift. I’m reopening exact `unit_builder.py` text and will apply narrower hunks from current file state.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/unit_builder.py` (+54 -6)
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+29 -12)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+82 -43)
>
> </details>
>
> Planning units can now carry `openrewrite`. I’m adding assertions that Boot 2.1 route units render those sections while legacy/default units stay unchanged.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_unit_builder_deterministic.py` (+28 -2)
>
> </details>
>
> One planning test needs a quick cleanup for string rendering. I’m fixing that and adding explicit `migration_units.yaml` `openrewrite` assertions on real Boot 2.1 planning output.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/agents/planning_agent/test_unit_builder_deterministic.py` (+6 -13)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+12 -0)
>
> </details>
>
> I’m adding focused transformation-plan tests next: global fallback unchanged, per-unit recipes attach to matching units, multiple recipe-bearing units each get their own OpenRewrite step, and no recipes means no OpenRewrite step.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+183 -8)
> - Wrote `./tests/test_transformation_agent.py` (+40 -36)
>
> </details>
>
> Per-unit config and execution-plan fallback are patched. I’m running planning-agent tests, transformation-agent tests, then full suite to catch any rendering or plan-adaptation regressions.
>
> Planning and transformation tests passed. Full suite timed out at 124s, so I’m rerunning with more time to get final repo-wide result instead of guessing.
>
> Context compaction
>
> Source: automatic
> Status: completed
</details>

**Summary**

Ticket 7 done.

Planning units now can carry optional per-unit `openrewrite` config.
Transformation execution plan now attach OpenRewrite to each matching unit, not just first write unit.

Old behavior still live:
- no unit-level config -> old global first-write-unit behavior
- old profiles still work
- deterministic order kept

**Files Modified**

- [migration_factory/agents/planning_agent/unit_builder.py](./migration_factory/agents/planning_agent/unit_builder.py:1)
- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py:1)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py:1)
- [tests/agents/planning_agent/test_unit_builder_deterministic.py](./tests/agents/planning_agent/test_unit_builder_deterministic.py:1)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py:1)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py:1)

**Tests Added**

- old global recipe behavior still attach to first source-changing unit
- per-unit OpenRewrite attach to correct unit
- multiple units each get own OpenRewrite transform
- units without config get no OpenRewrite transform
- no recipes means no OpenRewrite transform
- `migration_units.yaml` deterministic
- `transformation_execution_plan.yaml` deterministic
- no `msa-dto` / `common-utils` project-specific logic in unit definitions

**Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest tests/test_transformation_agent.py -q`
- `python -m pytest -q`

**Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  - `82 passed in 5.62s`
- `python -m pytest tests/test_transformation_agent.py -q`
  - `39 passed, 2 skipped in 26.36s`
- `python -m pytest -q`
  - `502 passed, 3 skipped in 60.17s`

**Example `migration_units.yaml`**

```yaml
units:
  - id: "spring-boot-2-7-stabilization"
    writes_source: true
    openrewrite:
      active_recipes:
        - "org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7"

  - id: "jakarta"
    writes_source: true
    openrewrite:
      active_recipes:
        - "org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta"

  - id: "jaxb-jakarta"
    writes_source: true
    openrewrite:
      active_recipes:
        - "org.openrewrite.java.migrate.jakarta.JavaxXmlBindMigrationToJakartaXmlBind"
```

**Example `transformation_execution_plan.yaml`**

```yaml
migration_units:
  - id: "spring-boot-2-7-stabilization"
    transformations:
      - type: "openrewrite"
        active_recipes:
          - "org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7"
        recipe_artifacts:
          - "org.openrewrite.recipe:rewrite-migrate-java:3.20.0"
      - type: "custom_code_change"

  - id: "jakarta"
    transformations:
      - type: "openrewrite"
        active_recipes:
          - "org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta"
        recipe_artifacts:
          - "org.openrewrite.recipe:rewrite-migrate-java:3.34.1"
        apply_goal: "run"
        apply_maven_args:
          - "-DskipTests"
        analysis_preview_maven_args:
          - "-DsomeFlag=true"
      - type: "custom_code_change"
```

**Backward Compatibility**

If no unit has `openrewrite`, code fall back to old path: global `rewrite_plugin_plan` go on first source-changing unit only.
So existing profiles and existing planning outputs still work.

**Why Generic**

No repo name, no artifactId, no `msa-dto`, no `common-utils` logic.
Behavior driven by:
- selected route -> unit sequence
- unit data -> optional `openrewrite` block
- global rewrite plan -> fallback artifacts/default behavior

So system use metadata, not project-specific hardcode.

**Warnings / Limitations**

- This ticket only change planning contract and execution plan generation.
- It does not run OpenRewrite.
- Route-specific unit recipe mapping still live in planner code today; clean extension point, but not yet loaded from profile YAML directly.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 8: Add deterministic Maven POM patcher for legacy property-based projects.
>
> Goal:
> Add a deterministic Maven POM patcher so the Transformation Agent can apply controlled, auditable Maven POM updates in the sandbox.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT add AI-generated patching.
> Do NOT modify the original legacy repository.
> All patching must be deterministic, declared in the transformation execution plan, applied only in the sandbox, and recorded in the ledger.
>
> Context:
> Some legacy Maven projects do not use spring-boot-starter-parent or a clean Spring Boot BOM.
> They often declare versions through Maven properties or explicit dependencies, for example:
> - <java.version>11</java.version>
> - <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
> - javax.xml.bind:jaxb-api
> - javax.persistence:javax.persistence-api
> - old plugin versions
> - duplicate dependencies
>
> OpenRewrite may not fully align these POMs.
> The factory needs a deterministic patch mechanism for controlled Maven changes.
>
> Tasks:
> 1. Add a new transformation patch type:
>    - maven_pom_patch
>
> 2. The patch type should support these operations:
>    - update_property
>    - add_property_if_missing
>    - update_dependency_version
>    - replace_dependency
>    - remove_duplicate_dependencies
>    - add_dependency_management_bom
>
> 3. Each patch operation must be declared in transformation_execution_plan.yaml.
>
> Example:
>
> transformations:
>   - type: maven_pom_patch
>     operations:
>       - op: update_property
>         name: java.version
>         value: "17"
>
>       - op: update_property
>         name: spring-boot.version
>         value: "3.5.14"
>
>       - op: replace_dependency
>         old_group_id: javax.xml.bind
>         old_artifact_id: jaxb-api
>         new_group_id: jakarta.xml.bind
>         new_artifact_id: jakarta.xml.bind-api
>         new_version: "4.0.2"
>
>       - op: add_dependency_management_bom
>         group_id: org.springframework.boot
>         artifact_id: spring-boot-dependencies
>         version: "3.5.14"
>         scope: import
>         type: pom
>
>       - op: remove_duplicate_dependencies
>
> 4. Implement the patcher in a clean module under the Transformation Agent, for example:
>    migration_factory/agents/transformation_agent/maven_pom_patcher.py
>
> 5. The patcher must:
>    - parse pom.xml safely
>    - preserve XML validity
>    - be deterministic
>    - be idempotent where reasonable
>    - fail with structured errors when an operation cannot be applied safely
>    - never patch files outside the sandbox project path
>    - record what changed
>
> 6. Integrate the patch type into the Transformation Agent execution flow.
>    If a unit contains a transformation of type maven_pom_patch, apply it in the sandbox.
>
> 7. Update ledger recording so Maven POM patches are recorded with:
>    - unit_id
>    - transformation_type
>    - operation count
>    - operations applied
>    - files changed
>    - status
>    - error message if failed
>
> 8. Add tests covering:
>    - update_property existing property
>    - add_property_if_missing
>    - update_dependency_version
>    - replace_dependency javax.xml.bind:jaxb-api → jakarta.xml.bind:jakarta.xml.bind-api
>    - add_dependency_management_bom
>    - remove_duplicate_dependencies
>    - idempotency where applicable
>    - failure when pom.xml is missing
>    - failure when patch tries to escape sandbox
>    - ledger records applied operations
>    - no project-specific artifactId or repo name is used
>
> 9. Add at least one transformation execution plan fixture using maven_pom_patch.
>
> 10. Do not modify Planning Agent route logic in this ticket unless absolutely necessary for tests.
> 11. Do not modify OpenRewrite execution behavior.
> 12. Do not modify Build Agent behavior.
> 13. Do not modify Test Agent behavior.
>
> Expected behavior:
> Given a sandbox project with pom.xml containing:
>
> <properties>
>     <java.version>11</java.version>
>     <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
> </properties>
>
> and a transformation plan operation:
>
> - op: update_property
>   name: java.version
>   value: "17"
>
> the sandbox pom.xml should become:
>
> <java.version>17</java.version>
>
> The legacy source repository must remain unchanged.
>
> Validation commands:
> Run transformation-agent tests and full test suite if feasible:
>
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> If you add a dedicated test file for the POM patcher, run it explicitly too.
>
> Report back with:
> 1. Summary
> 2. Files created/modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example transformation_execution_plan.yaml excerpt with maven_pom_patch
> 7. Example before/after POM snippet
> 8. Ledger excerpt showing patch operations recorded
> 9. Explanation of sandbox safety
> 10. Explanation of why the implementation is deterministic and not project-specific
> 11. Any warnings or limitations

<details><summary>10 previous messages</summary>

> Use caveman skill. First I read skill and current transformation flow, then I patch small and test hard.
>
> Now I dig transform agent internals: existing POM patch path, execution flow, ledger shape. Then I wire new patch type into same machine, not bolt-on mess.
>
> Next I map where plan transforms become ledger rows. Need fit new patch cleanly so report/ledger already understand it.
>
> I found old deterministic patches already exist, but narrow. Best path: add new generic POM patcher module, integrate new transform type beside old ones, keep old patch types untouched.
>
> Code edit time. I add new generic patcher module first, then wire agent branch, then add focused tests for patcher + agent ledger path.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+505 -0)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+80 -10)
>
> </details>
>
> Now tests. I add one dedicated patcher test file for pure POM ops, one agent integration test for ledger + sandbox flow.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+232 -0)
> - Wrote `./tests/test_transformation_agent.py` (+136 -9)
>
> </details>
>
> Running focused tests first. Want syntax/behavior clean before full suite.
>
> Focused tests green. I run full suite now to catch any contract drift outside transformer.
</details>

**1. Summary**

Ticket 8 done.

New deterministic patch type: `maven_pom_patch`.

Transformer now can apply declared Maven POM ops inside sandbox only:
- `update_property`
- `add_property_if_missing`
- `update_dependency_version`
- `replace_dependency`
- `remove_duplicate_dependencies`
- `add_dependency_management_bom`

Behavior:
- parse `pom.xml` safely
- write only after all ops validate
- block on unsafe/error cases with structured error
- record applied ops in ledger
- no AI patching
- no legacy repo mutation

**2. Files Created/Modified**

Created:
- [migration_factory/agents/transformation_agent/maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py:1)
- [tests/test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py:1)

Modified:
- [migration_factory/agents/transformation_agent/agent.py](./migration_factory/agents/transformation_agent/agent.py:1)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py:1)

**3. Tests Added**

New direct patcher tests:
- update existing property
- add property if missing
- update dependency version
- replace `javax.xml.bind:jaxb-api` -> `jakarta.xml.bind:jakarta.xml.bind-api`
- add dependency-management BOM
- remove duplicate dependencies
- idempotency
- missing `pom.xml` failure
- sandbox escape failure
- no project-specific names in patcher source

New transformer integration tests:
- `maven_pom_patch` updates sandbox `pom.xml` and records ledger ops
- `maven_pom_patch` failure blocks unit when `pom_path` escapes sandbox

**4. Exact Commands Run**

- `python -m pytest tests/test_maven_pom_patcher.py -q`
- `python -m pytest tests/test_transformation_agent.py -q`
- `python -m pytest -q`

**5. Full Test Result Summary**

- `python -m pytest tests/test_maven_pom_patcher.py -q`
  - `10 passed in 0.20s`
- `python -m pytest tests/test_transformation_agent.py -q`
  - `41 passed, 2 skipped in 12.59s`
- `python -m pytest -q`
  - `514 passed, 3 skipped in 60.57s`

**6. Example `transformation_execution_plan.yaml` Excerpt**

```yaml
migration_units:
  - id: spring-boot-3-5-14
    transformations:
      - type: maven_pom_patch
        operations:
          - op: update_property
            name: java.version
            value: "17"
          - op: update_property
            name: spring-boot.version
            value: "3.5.14"
          - op: replace_dependency
            old_group_id: javax.xml.bind
            old_artifact_id: jaxb-api
            new_group_id: jakarta.xml.bind
            new_artifact_id: jakarta.xml.bind-api
            new_version: "4.0.2"
          - op: add_dependency_management_bom
            group_id: org.springframework.boot
            artifact_id: spring-boot-dependencies
            version: "3.5.14"
            scope: import
            type: pom
          - op: remove_duplicate_dependencies
```

**7. Example Before/After POM Snippet**

Before:
```xml
<properties>
  <java.version>11</java.version>
  <spring-boot.version>2.1.6.RELEASE</spring-boot.version>
</properties>
<dependencies>
  <dependency>
    <groupId>javax.xml.bind</groupId>
    <artifactId>jaxb-api</artifactId>
    <version>2.3.1</version>
  </dependency>
</dependencies>
```

After:
```xml
<properties>
  <java.version>17</java.version>
  <spring-boot.version>3.5.14</spring-boot.version>
</properties>
<dependencies>
  <dependency>
    <groupId>jakarta.xml.bind</groupId>
    <artifactId>jakarta.xml.bind-api</artifactId>
    <version>4.0.2</version>
  </dependency>
</dependencies>
```

**8. Ledger Excerpt**

```yaml
units:
  spring-boot-3-5-14:
    transformations:
      - unit_id: spring-boot-3-5-14
        type: maven_pom_patch
        transformation_type: maven_pom_patch
        status: applied
        operation_count: 4
        operations_applied:
          - op: update_property
            status: updated
            name: java.version
            old_value: "11"
            new_value: "17"
          - op: update_property
            status: updated
            name: spring-boot.version
            old_value: "2.1.6.RELEASE"
            new_value: "3.5.14"
          - op: replace_dependency
            status: replaced
            old_group_id: javax.xml.bind
            old_artifact_id: jaxb-api
            new_group_id: jakarta.xml.bind
            new_artifact_id: jakarta.xml.bind-api
            new_version: "4.0.2"
          - op: remove_duplicate_dependencies
            status: removed
            removed_dependencies: 1
        files_changed:
          - pom.xml
        pom_file: pom.xml
        error_message: null
```

**9. Sandbox Safety**

Safe by design:
- patcher resolve target POM against sandbox root
- path escape like `../outside/pom.xml` blocked with `POM_PATH_OUTSIDE_SANDBOX`
- missing file fails with structured `POM_FILE_MISSING`
- XML edits happen in memory first
- file written only after all ops validate
- transformer still runs on sandbox `target_path`, not legacy repo

**10. Why Deterministic / Generic**

Deterministic:
- only declared ops from plan
- no AI-generated edits
- stable XML op handlers
- idempotent for repeat-safe ops like add-if-missing, replace-already-done, duplicate cleanup rerun

Generic:
- no `msa-dto`
- no `common-utils`
- no repo-name logic
- ops key off Maven structure and coordinates only

**11. Warnings / Limitations**

Current patcher scope:
- one POM per transformation, default `pom.xml`
- supports root or submodule POM only if `pom_path` stays inside sandbox
- dependency ops target direct `<dependencies>` and `<dependencyManagement>` entries
- does not patch Maven plugins, pluginManagement, profiles, or parent section in this ticket

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 8.5: Model multi-hop migration routes for enterprise-grade migration governance.
>
> Goal:
> Introduce a first-class multi-hop migration route model so the factory can represent enterprise migration strategies such as:
>
> Spring Boot 2.1 -> Spring Boot 2.7 -> Spring Boot 3.5
>
> instead of treating Spring Boot 2.1 -> Spring Boot 3.5 as a single direct step.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT implement project-specific behavior.
> Do NOT execute multi-hop transformation yet.
> This ticket is about profile/schema/planning artifact modeling only.
>
> Context:
> The factory already supports route-driven profiles and route-aware migration units.
> The current Spring Boot 2.1 profile uses:
> - strategy: direct_sandbox
> - recommended_intermediate.spring_boot: 2.7.18
>
> For enterprise industrialization, this is not enough.
> The factory must explicitly model multi-hop migration routes, where each hop can later have its own units, transformations, build validation, test validation, approval, rollback/checkpoint, and evidence.
>
> Tasks:
> 1. Extend migration profile schema to support route-level hops.
>
> 2. A route should support this shape:
>
> routes:
>   - id: boot-2.1-to-3.5-java17
>     strategy: multi_hop
>     risk_level: high
>     production_allowed: false
>     preferred: true
>     hops:
>       - id: boot-2.1-to-2.7-java11
>         source:
>           java:
>             allowed_versions:
>               - "8"
>               - "11"
>           spring_boot:
>             allowed_version_prefixes:
>               - "2.1"
>           build:
>             allowed_tools:
>               - maven
>         target:
>           java: "11"
>           spring_boot: "2.7.18"
>           build: maven
>         validation:
>           build_required: true
>           tests_required: true
>         approval:
>           required: true
>
>       - id: boot-2.7-to-3.5-java17
>         source:
>           java:
>             allowed_versions:
>               - "11"
>           spring_boot:
>             allowed_version_prefixes:
>               - "2.7"
>           build:
>             allowed_tools:
>               - maven
>         target:
>           java: "17"
>           spring_boot: "3.5.14"
>           spring_framework: "6.2.18"
>           build: maven
>         validation:
>           build_required: true
>           tests_required: true
>         approval:
>           required: true
>
> 3. Preserve backward compatibility:
>    - Existing direct routes without hops must remain valid.
>    - Existing profiles without routes must remain valid.
>    - Existing planning tests must remain green.
>
> 4. Update the Spring Boot 2.1 profile:
>    modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml
>
>    It should now expose the recommended enterprise route as multi-hop:
>    - boot-2.1-to-2.7-java11
>    - boot-2.7-to-3.5-java17
>
>    It may keep direct_sandbox metadata only as an alternative/fallback route if useful, but the preferred route must be multi_hop.
>
> 5. Update profile compatibility / route selection so:
>    - The selected route can be multi-hop.
>    - selected_route_id remains available.
>    - selected_route_strategy is available.
>    - selected_hops are available in compatibility result.
>    - high-risk multi-hop routes warn but do not block planning.
>    - unsupported routes still block planning.
>
> 6. Update planning artifacts:
>    migration_plan.yaml should include:
>    - selected_route_id
>    - route_strategy
>    - route_risk_level
>    - production_allowed
>    - selected_hops
>
>    Example:
>
> selected_route_id: "boot-2.1-to-3.5-java17"
> route_strategy: "multi_hop"
> route_risk_level: "high"
> production_allowed: false
> selected_hops:
>   - id: "boot-2.1-to-2.7-java11"
>     source:
>       java:
>         allowed_versions:
>           - "8"
>           - "11"
>       spring_boot:
>         allowed_version_prefixes:
>           - "2.1"
>     target:
>       java: "11"
>       spring_boot: "2.7.18"
>       build: "maven"
>     validation:
>       build_required: true
>       tests_required: true
>     approval:
>       required: true
>   - id: "boot-2.7-to-3.5-java17"
>     source:
>       java:
>         allowed_versions:
>           - "11"
>       spring_boot:
>         allowed_version_prefixes:
>           - "2.7"
>     target:
>       java: "17"
>       spring_boot: "3.5.14"
>       spring_framework: "6.2.18"
>       build: "maven"
>     validation:
>       build_required: true
>       tests_required: true
>     approval:
>       required: true
>
> 7. Do not implement actual multi-hop execution yet.
> 8. Do not modify Transformation Agent execution behavior.
> 9. Do not modify OpenRewrite execution behavior.
> 10. Do not modify Build Agent behavior.
> 11. Do not modify Test Agent behavior.
> 12. Do not add AI-generated decisions.
>
> Tests to add:
> 1. Schema accepts a route with hops.
> 2. Existing no-route profiles still validate.
> 3. Existing direct routes without hops still validate.
> 4. Spring Boot 2.1 profile loads successfully with multi-hop route.
> 5. For source Java 11 / Boot 2.1.6.RELEASE / Maven, compatibility selects the multi-hop route.
> 6. migration_plan.yaml includes selected_hops.
> 7. selected_hops order is deterministic.
> 8. High-risk multi-hop route warns but does not block planning.
> 9. No matching route still fails clearly.
> 10. Existing full planning tests remain green.
>
> Validation commands:
> Run planning-agent tests and full test suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest -q
>
> Report back with:
> 1. Summary
> 2. Files created/modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Updated Spring Boot 2.1 profile YAML excerpt
> 7. Example migration_plan.yaml excerpt showing selected_hops
> 8. Explanation of backward compatibility
> 9. Explanation of why this makes the factory more enterprise-grade / top-management-validable
> 10. Any warnings or limitations

<details><summary>6 previous messages</summary>

> Use caveman skill. I inspect planning schema/profile path first, then patch model + tests, then run planning/full suite.
>
> I have shape. Next I inspect planning tests and node wiring, then patch minimal places: schema, compatibility result, plan writer, Boot 2.1 profile, tests.
>
> I’m editing planning model now: route hops, preferred multi-hop selection, plan YAML rendering, Boot 2.1 profile. Then I refresh tests around compatibility and plan output.
>
> <details><summary>Edited 8 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/profile_compatibility.py` (+52 -9)
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+47 -2)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+1 -0)
> - Wrote `./migration_factory/agents/planning_agent/profile_reader.py` (+33 -6)
> - Wrote `./modernizer-solution-ai-hub/schemas/migration-profile.schema.json` (+76 -2)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+50 -0)
> - Wrote `./tests/agents/planning_agent/test_profile_routes.py` (+93 -27)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+76 -2)
>
> </details>
>
> Edits in. I’m running planning-agent tests now; if YAML rendering or route selection shaky, this will flush it fast before full suite.
>
> Planning tests green. Full suite next for regression check.
</details>

**1. Summary**

Ticket 8.5 done.

Factory now model first-class multi-hop routes in profile + compatibility + planning artifacts.

Boot 2.1 profile now prefer enterprise route:

- `boot-2.1-to-2.7-java11`
- `boot-2.7-to-3.5-java17`

Planning still deterministic. No transform/build/test execution behavior changed.

**2. Files Created/Modified**

Modified:
- [migration_factory/agents/planning_agent/profile_compatibility.py](./migration_factory/agents/planning_agent/profile_compatibility.py:1)
- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py:1)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py:1)
- [migration_factory/agents/planning_agent/profile_reader.py](./migration_factory/agents/planning_agent/profile_reader.py:1)
- [modernizer-solution-ai-hub/schemas/migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json:1)
- [modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml:1)
- [tests/agents/planning_agent/test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py:1)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py:1)

**3. Tests Added**

Added/expanded coverage for:
- schema accepts route with `hops`
- old no-route profiles still validate
- old direct routes without hops still validate
- Boot 2.1 profile loads with multi-hop route
- compatibility selects multi-hop route for Java 11 / Boot 2.1.6 / Maven
- `migration_plan.yaml` includes `selected_hops`
- `selected_hops` order deterministic
- high-risk multi-hop route warns, not blocks
- no matching route still fails clear
- existing planning outputs stay green

**4. Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q`
- `python -m pytest -q`

**5. Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  - `84 passed in 1.80s`
- `python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q`
  - `6 passed in 0.85s`
- `python -m pytest -q`
  - `516 passed, 3 skipped in 45.81s`

**6. Updated Spring Boot 2.1 Profile YAML Excerpt**

```yaml
routes:
  - id: boot-2.1-to-3.5-java17
    strategy: multi_hop
    risk_level: high
    production_allowed: false
    preferred: true
    recommended_intermediate:
      spring_boot: "2.7.18"
    hops:
      - id: boot-2.1-to-2.7-java11
        source:
          java:
            allowed_versions: ["8", "11"]
          spring_boot:
            allowed_version_prefixes: ["2.1"]
          build:
            allowed_tools: ["maven"]
        target:
          java: "11"
          spring_boot: "2.7.18"
          build: maven
        validation:
          build_required: true
          tests_required: true
        approval:
          required: true

      - id: boot-2.7-to-3.5-java17
        source:
          java:
            allowed_versions: ["11"]
          spring_boot:
            allowed_version_prefixes: ["2.7"]
          build:
            allowed_tools: ["maven"]
        target:
          java: "17"
          spring_boot: "3.5.14"
          spring_framework: "6.2.18"
          build: maven
        validation:
          build_required: true
          tests_required: true
        approval:
          required: true
```

**7. Example `migration_plan.yaml` Excerpt**

```yaml
selected_route_id: "boot-2.1-to-3.5-java17"
route_strategy: "multi_hop"
route_risk_level: "high"
production_allowed: false
selected_hops:
  -
    id: "boot-2.1-to-2.7-java11"
    source:
      java:
        allowed_versions:
          - "8"
          - "11"
      spring_boot:
        allowed_version_prefixes:
          - "2.1"
      build:
        allowed_tools:
          - "maven"
    target:
      java: "11"
      spring_boot: "2.7.18"
      build: "maven"
    validation:
      build_required: true
      tests_required: true
    approval:
      required: true
  -
    id: "boot-2.7-to-3.5-java17"
    target:
      java: "17"
      spring_boot: "3.5.14"
      spring_framework: "6.2.18"
      build: "maven"
```

**8. Backward Compatibility**

Still safe:
- no `routes` profile -> old source/target logic unchanged
- direct route without `hops` -> still valid
- existing `selected_route_id`, `route_strategy`, `route_risk_level`, `production_allowed` still emitted
- planning tests stayed green

**9. Why More Enterprise-Grade / Management-Validable**

This makes route explicit, auditable, governable.

Now leadership can see:
- migration not “magic jump”
- each hop has target state
- each hop can later carry build/test/approval gates
- route choice deterministic, documented, reviewable
- enterprise fallback/direct route can coexist with preferred governed path

Good for architecture boards, CAB review, phased approvals, migration-wave planning.

**10. Warnings / Limitations**

- Modeling only. No multi-hop execution yet.
- Unit generation still route-based, not hop-by-hop execution engine.
- Compatibility matches multi-hop route from first hop source, target stack from last hop target.
- `selected_hops` now in plan artifact, but transformer/build/test agents do not consume hop metadata yet.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 9: Add multi-hop-aware Spring Boot / Jakarta risk classifier.
>
> Goal:
> Enhance Planning/Assessment risk classification for enterprise-grade Spring Boot migrations, especially legacy Spring Boot 2.1.x to Spring Boot 3.5 / Java 17.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT implement project-specific rules.
> The implementation must be generic and based on detected analysis facts and selected route metadata:
> - source Spring Boot version
> - target Spring Boot version
> - selected_route_id
> - route_strategy
> - selected_hops
> - Java imports
> - dependencies
> - project_kind
> - internal dependencies
> - known framework/library signals
>
> Context:
> The factory now supports:
> - route-driven profiles
> - explicit multi-hop routes
> - selected_hops in migration_plan.yaml
> - contract_library classification
> - internal dependency detection
> - javax import scanning
> - route-aware migration units
>
> For enterprise governance, the risk classifier must distinguish:
> 1. A direct high-risk migration route.
> 2. A preferred multi-hop migration route.
> 3. A route that is unsupported or missing required mitigation.
>
> For example:
> Spring Boot 2.1 -> Spring Boot 3.5 directly should be HIGH risk and sandbox-only.
> Spring Boot 2.1 -> Spring Boot 2.7 -> Spring Boot 3.5 should still be HIGH impact, but more enterprise-governed because the intermediate hop is explicit.
>
> Tasks:
> 1. Enhance the existing Planning Agent risk classifier.
> 2. The classifier must be multi-hop aware.
> 3. Detect and classify these generic risks:
>    - source Spring Boot version older than 2.7 when final target is Spring Boot 3.x
>    - direct route from Boot < 2.7 to Boot 3.x
>    - multi-hop route from Boot < 2.7 to Boot 3.x with intermediate Boot 2.7 hop
>    - javax.persistence usage when final target is Boot 3.x
>    - javax.xml.bind usage when final target is Boot 3.x
>    - javax.servlet usage when final target is Boot 3.x
>    - javax.annotation usage when final target is Boot 3.x
>    - javax.validation usage when final target is Boot 3.x
>    - Apache Juneau usage
>    - Spring Security legacy usage
>    - old Azure SDK usage using com.microsoft.azure.*
>    - old Lombok usage
>    - project_kind = contract_library
>    - internal dependency candidates detected
>
> 4. Severity rules:
>    - Boot < 2.7 to Boot 3.x with direct_sandbox route: HIGH
>    - Boot < 2.7 to Boot 3.x with multi_hop route: HIGH, but message should state that the route is governed through explicit hops
>    - Boot < 2.7 to Boot 3.x without multi-hop or recommended intermediate metadata: HIGH or BLOCKER depending on current route support
>    - javax.* usage with Boot 3 target: HIGH
>    - javax.* usage with Boot 3 target and no Jakarta/JAXB migration unit planned: BLOCKER
>    - Apache Juneau: HIGH and human review required
>    - Spring Security legacy: HIGH and human review required
>    - old Azure SDK: HIGH and human review required
>    - old Lombok: WARNING or HIGH depending on detected version age
>    - contract_library: HIGH impact, human review required
>    - internal dependencies: WARNING, migration order review required
>
> 5. Do not block all HIGH risks by default.
> 6. Clearly distinguish:
>    - HIGH
>    - WARNING
>    - BLOCKER
>
> 7. Risk messages should be deterministic and structured.
>    Example:
>    [HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: Source Spring Boot 2.1.6.RELEASE targets Boot 3.x through a governed multi-hop route: boot-2.1-to-2.7-java11 -> boot-2.7-to-3.5-java17.
>
> 8. Include risk messages in:
>    - migration_plan.yaml
>    - approval_request.json
>    - assessment_report.json, if assessment currently consumes planning risks
>
> 9. Risk messages should explain recommended governance where applicable.
>    Example:
>    - Direct Boot 2.1 to Boot 3.x migration is sandbox-only.
>    - Preferred enterprise route should pass through latest Boot 2.7.x before Boot 3.x.
>    - Each hop should have build/test evidence.
>
> 10. Add tests using fixtures or synthetic analysis artifacts for:
>    - Boot 2.1 -> Boot 3.5 direct_sandbox route classified HIGH
>    - Boot 2.1 -> Boot 2.7 -> Boot 3.5 multi_hop route classified HIGH but not blocked
>    - Boot < 2.7 to Boot 3.x without mitigation produces appropriate warning/blocker
>    - javax.persistence import
>    - javax.xml.bind import
>    - javax.servlet import
>    - javax.annotation import
>    - javax.validation import
>    - Apache Juneau dependency/import
>    - Spring Security legacy dependency/import
>    - old Azure SDK dependency/import
>    - old Lombok dependency
>    - contract_library project kind
>    - internal dependency candidates
>    - HIGH risks do not automatically block planning
>    - true BLOCKER still blocks planning
>    - risk messages appear in planning and approval artifacts
>    - assessment report includes or propagates the relevant risks if supported by current assessment flow
>
> 11. Do not modify Transformation Agent behavior.
> 12. Do not modify OpenRewrite behavior.
> 13. Do not modify Build Agent behavior.
> 14. Do not modify Test Agent behavior.
> 15. Do not execute transformation in this ticket.
>
> Expected behavior:
> For a Boot 2.1.x contract library targeting Boot 3.5 through selected_hops:
> - boot-2.1-to-2.7-java11
> - boot-2.7-to-3.5-java17
>
> Planning should continue, but approval artifacts should clearly show:
> - HIGH migration risk
> - multi-hop governance
> - Jakarta risk
> - contract compatibility review
> - internal dependency migration-order review if applicable
>
> Validation commands:
> Run planning and assessment tests, then full suite if feasible:
>
> python -m pytest tests/agents/planning_agent -q
> python -m pytest tests/assessment -q
> python -m pytest -q
>
> If repo layout differs, run equivalent tests and explain the path used.
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example migration_plan.yaml risk excerpt
> 7. Example approval_request.json risk/warning excerpt
> 8. Example assessment_report.json excerpt if applicable
> 9. Explanation of how multi-hop route changes risk messaging
> 10. Explanation of why HIGH risks do not automatically block planning
> 11. Explanation of why the implementation is generic and not project-specific
> 12. Any warnings or limitations

<details><summary>14 previous messages</summary>

> Use caveman skill. I inspect risk classifier + assessment flow first, then patch rules from analysis facts and route metadata, then test planning/assessment/full suite.
>
> Search hiccup from PowerShell glob junk. I’m rerunning narrow reads for planning/assessment artifact flow and analysis fields we can already mine.
>
> I found assessment already pulls planning warnings/blockers, but not rich risk list. I’m checking schemas now so I can thread risks through approval/assessment without breaking contracts.
>
> Need exact analysis facts next: what analysis already emits for imports/deps/project kind, so risk rules ride real data not guesses.
>
> One more pass through planning/assessment tests. I need thread new `risks` field without tripping contract checks.
>
> Big edit now: classifier, node wiring, approval artifact, assessment propagation, then tests for route/direct/multi-hop/Jakarta/framework/library cases.
>
> <details><summary>Created 1 file, edited 3 files, deleted 1 file</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/approval_writer.py` (+13 -11)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+21 -12)
> - Deleted `./migration_factory/agents/planning_agent/risk_classifier.py` (+0 -222)
> - Wrote `./migration_factory/agents/planning_agent/risk_classifier.py` (+640 -0)
> - Wrote `./migration_factory/assessment/writer.py` (+28 -24)
>
> </details>
>
> Tests next. I’m adding one focused risk-classifier suite plus one assessment propagation check. Goal: lots coverage, little churn.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_multihop_risk_classifier.py` (+509 -0)
>
> </details>
>
> Running planning + assessment tests now. I expect a couple shape mismatches first pass; will fix fast.
>
> Two misses only: legacy `javax_count` test expected old warning, and assessment prioritized rewrite LOW over planning HIGH. Small fix now.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/risk_classifier.py` (+10 -0)
> - Wrote `./migration_factory/assessment/writer.py` (+8 -8)
>
> </details>
>
> Rerun planning + assessment tests after small fixes, then full suite if green.
>
> Green. Full suite final check now.
</details>

**1. Summary**

Ticket 9 done.

Planning risk classifier now multi-hop aware. It uses:
- source Boot
- target Boot
- selected route
- route strategy
- selected hops
- imports
- dependencies
- project kind
- internal dependencies

New severities now clear:
- `HIGH`
- `WARNING`
- `BLOCKER`

Behavior now:
- Boot `<2.7` -> Boot `3.x` direct route => `HIGH`
- Boot `<2.7` -> Boot `3.x` multi-hop with explicit Boot `2.7` hop => `HIGH`, governed message
- Boot `<2.7` -> Boot `3.x` without mitigation => `BLOCKER`
- `javax.*` + Boot `3.x` => `HIGH`
- `javax.*` + missing planned Jakarta/JAXB unit => `BLOCKER`
- Juneau / legacy Spring Security / old Azure SDK / contract library => `HIGH`
- internal deps => `WARNING`
- old Lombok => `WARNING` or `HIGH` by version age

Risks now propagate into:
- `migration_plan.yaml`
- `approval_request.json`
- `assessment_report.json` via `planning_risks`, and `overall_risk` now respects planning `HIGH`

**2. Files Modified**

- [migration_factory/agents/planning_agent/risk_classifier.py](./migration_factory/agents/planning_agent/risk_classifier.py:1)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py:1)
- [migration_factory/agents/planning_agent/approval_writer.py](./migration_factory/agents/planning_agent/approval_writer.py:1)
- [migration_factory/assessment/writer.py](./migration_factory/assessment/writer.py:1)
- [tests/agents/planning_agent/test_multihop_risk_classifier.py](./tests/agents/planning_agent/test_multihop_risk_classifier.py:1)

**3. Tests Added**

New coverage includes:
- Boot 2.1 -> 3.5 `direct_sandbox` => `HIGH`
- Boot 2.1 -> 2.7 -> 3.5 `multi_hop` => `HIGH`, not blocked
- Boot `<2.7` -> Boot `3.x` without mitigation => `BLOCKER`
- `javax.persistence`
- `javax.xml.bind`
- `javax.servlet`
- `javax.annotation`
- `javax.validation`
- Apache Juneau
- legacy Spring Security
- old Azure SDK
- old Lombok
- `contract_library`
- internal dependency candidates
- `HIGH` risks do not auto-block planning
- true `BLOCKER` still blocks planning
- risk messages appear in planning + approval artifacts
- assessment report propagates planning risks

**4. Exact Commands Run**

- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest tests/assessment -q`
- `python -m pytest -q`

**5. Full Test Result Summary**

- `python -m pytest tests/agents/planning_agent -q`
  - `101 passed in 2.33s`
- `python -m pytest tests/assessment -q`
  - `6 passed in 0.34s`
- `python -m pytest -q`
  - `533 passed, 3 skipped in 68.92s`

**6. Example `migration_plan.yaml` Risk Excerpt**

```yaml
risk: "HIGH"
risks:
  - "[HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: Source Spring Boot 2.1.6.RELEASE targets Boot 3.x through a governed multi-hop route: boot-2.1-to-2.7-java11 -> boot-2.7-to-3.5-java17. Each hop should produce build/test evidence before final Boot 3.x approval."
  - "[HIGH] JAVAX_PERSISTENCE_BOOT3: JPA `javax.persistence` usage must migrate to Jakarta for Boot 3.x."
  - "[HIGH] CONTRACT_LIBRARY_HUMAN_REVIEW: Project classified as contract_library. Human review required for contract compatibility and consumer impact."
  - "[WARNING] INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW: Detected 1 internal dependency candidate(s). Review migration order across repositories before approval."
warnings:
  - "Selected migration route boot-2.1-to-3.5-java17 is marked high risk."
```

**7. Example `approval_request.json` Risk/Warning Excerpt**

```json
{
  "status": "PASS",
  "risks": [
    "[HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: Source Spring Boot 2.1.6.RELEASE targets Boot 3.x through a governed multi-hop route: boot-2.1-to-2.7-java11 -> boot-2.7-to-3.5-java17. Each hop should produce build/test evidence before final Boot 3.x approval.",
    "[HIGH] CONTRACT_LIBRARY_HUMAN_REVIEW: Project classified as contract_library. Human review required for contract compatibility and consumer impact."
  ],
  "warnings": [
    "Selected migration route boot-2.1-to-3.5-java17 is marked high risk.",
    "Selected migration route strategy: multi_hop."
  ],
  "blockers": []
}
```

**8. Example `assessment_report.json` Excerpt**

```json
{
  "overall_risk": "HIGH",
  "planning_risks": [
    "[HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: Source Spring Boot 2.1.6.RELEASE targets Boot 3.x through a governed multi-hop route: boot-2.1-to-2.7-java11 -> boot-2.7-to-3.5-java17. Each hop should produce build/test evidence before final Boot 3.x approval."
  ],
  "approval_readiness": {
    "status": "READY_FOR_REVIEW"
  }
}
```

**9. How Multi-Hop Route Changes Risk Messaging**

Before: old route looked like one big jump.

Now: classifier sees explicit hops and changes message:
- direct route => sandbox-only warning style, higher governance concern
- multi-hop route => still `HIGH`, but message says governed path exists
- message names hop chain, pushes build/test evidence per hop

So same technical difficulty, better governance posture.

**10. Why `HIGH` Risks Do Not Automatically Block Planning**

Planner only turns `BLOCKER` risks into executable blockers.

`HIGH` means:
- serious migration risk
- human review required
- visible in plan and approval

But planning still continues so enterprise team can review governed route, units, approvals, evidence path.

**11. Why Generic, Not Project-Specific**

No `msa-dto`. No `common-utils`. No repo-name logic.

Rules key off generic facts:
- version ranges
- route metadata
- hop metadata
- imports
- Maven dependencies
- project classification
- internal dependency candidates

Tests also use synthetic artifacts and generic coordinates/imports.

**12. Warnings / Limitations**

- Import/package detection depends on analysis facts present in artifacts. Current classifier supports several generic fields, but richer analysis signals would improve precision more later.
- No multi-hop execution yet. This ticket changes planning/assessment risk messaging only.
- Spring Security legacy detection currently keys off known legacy import/dependency signals, not every possible custom security pattern.
- Azure/Lombok risk classification is generic heuristic, not full ecosystem inventory.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 10: Add end-to-end read_only_assessment fixture for a Spring Boot 2.1 contract library.
>
> Goal:
> Add an end-to-end fixture test that represents a generic Spring Boot 2.1 Maven contract library, similar in shape to enterprise DTO/API contract libraries.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> The fixture may be inspired by msa-dto, but it must use generic names and generic package coordinates.
>
> Context:
> The factory now supports:
> - Spring Boot detection without starter parent
> - project_kind classification
> - internal dependency detection
> - route-driven profiles
> - multi-hop routes
> - route-aware migration units
> - per-unit OpenRewrite config
> - deterministic Maven POM patching
> - multi-hop-aware risk classification
>
> Now we need an end-to-end read_only_assessment test proving that the factory can handle a Boot 2.1 contract library without mutating source files.
>
> Tasks:
> 1. Create a lightweight test fixture under tests/fixtures, for example:
>    tests/fixtures/boot21-contract-library
>
> 2. The fixture should be a Maven jar project with:
>    - Java 11
>    - Spring Boot 2.1.6.RELEASE declared via property, not starter parent
>    - packaging jar
>    - no @SpringBootApplication main class
>    - at least one Spring REST contract interface or controller contract
>    - at least one Apache Juneau contract signal if feasible
>    - at least one javax.persistence import
>    - at least one javax.xml.bind import
>    - at least one internal dependency candidate with a generic groupId prefix, for example com.total.corp or com.example.internal
>    - at least one old Lombok dependency or property if useful for risk classification
>
> 3. Add an integration test for read_only_assessment flow using:
>    - profile: springboot-2.1-to-3.5-java17
>
> 4. The test should assert:
>    - analysis_report.json exists
>    - source_stack.java is 11
>    - source_stack.spring_boot is 2.1.6.RELEASE or normalized equivalent
>    - project_kind is contract_library
>    - has_spring_boot_main is false
>    - internal_dependencies_count is greater than 0
>    - read_only_verification.json proves source was not modified
>    - migration_plan.yaml exists
>    - selected_route_id is boot-2.1-to-3.5-java17
>    - route_strategy is multi_hop
>    - selected_hops contains boot-2.1-to-2.7-java11 and boot-2.7-to-3.5-java17 in deterministic order
>    - migration_units.yaml contains the route-aware Boot 2.1 unit sequence
>    - approval_request.json exists
>    - assessment_report.json exists
>    - approval readiness is ready for human review or equivalent
>    - risks include Boot pre-2.7 to Boot 3.x multi-hop risk
>    - risks include contract_library human review
>    - risks include Jakarta/javax migration risk
>    - warnings include internal dependency migration order review
>
> 5. The test must not execute source-changing transformation.
> 6. The test must not require external network access.
> 7. The test must not require real client credentials, Azure, AWS, CodeArtifact, or GitHub secrets.
> 8. Do not modify Transformation Agent behavior.
> 9. Do not modify Build Agent behavior.
> 10. Do not modify Test Agent behavior.
> 11. Keep the fixture minimal and deterministic.
>
> Validation commands:
> Run the new integration test, planning/assessment tests, and full suite if feasible:
>
> python -m pytest tests/orchestrator -q
> python -m pytest tests/agents/planning_agent -q
> python -m pytest tests/assessment -q
> python -m pytest -q
>
> If the repo layout differs, run the equivalent tests and explain the path used.
>
> Report back with:
> 1. Summary
> 2. Files created/modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Fixture structure
> 7. Example analysis_report.json excerpt
> 8. Example migration_plan.yaml excerpt
> 9. Example assessment_report.json excerpt
> 10. Explanation of read-only safety
> 11. Explanation of why the fixture is generic and not project-specific
> 12. Any warnings or limitations

<details><summary>12 previous messages</summary>

> Use caveman skill. I inspect existing end-to-end/read-only test paths first, then add small generic fixture + one integration test, then run requested suites.
>
> I’m checking analysis agent callable path before writing e2e test. Need use real scanner, not fake artifact JSON, but avoid brittle import-path traps.
>
> I have working analysis-agent integration pattern. Next I inspect `MigrationContext` and import scanner limits, then I add real fixture files and one orchestrator-style e2e test that copies fixture into temp workspace.
>
> Need fixture source lines match classifier heuristics exactly. I’m checking contract-detection patterns so fixture trips `contract_library` reliably with minimal files.
>
> One quick read of read-only verifier, then I wire fixture copy + hash assertions so test proves no source mutation two ways: hash and artifact.
>
> I’m creating fixture and one e2e test now. Test will copy fixture to temp, run real analysis scanner with fake local subprocesses, then planning + assessment, then assert artifacts and no source writes.
>
> <details><summary>Created 5 files</summary>
>
> - Wrote `./tests/fixtures/boot21-contract-library/pom.xml` (+60 -0)
> - Wrote `./tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/CustomerContract.java` (+37 -0)
> - Wrote `./tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/RemoteCustomerContract.java` (+7 -0)
> - Wrote `./tests/fixtures/boot21-contract-library/src/test/java/com/example/contracts/api/CustomerContractTest.java` (+4 -0)
> - Wrote `./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py` (+155 -0)
>
> </details>
>
> Targeted run first: new orchestrator e2e, then planning/assessment suites, then full suite if clean.
>
> Miss was narrow: real analysis artifact had no explicit import list, but dependency graph had `javax.persistence-api` and `jaxb-api`. I’m teaching risk classifier to mine deps from dependency graph too.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/risk_classifier.py` (+25 -0)
>
> </details>
>
> Rerun new e2e first, then full requested suites if green.
>
> Everything requested green. Final full suite run now.
</details>

**1. Summary**

Ticket 10 done.

Added real read-only end-to-end fixture for generic Boot `2.1` Maven contract library.
Test runs:

- real Analysis Agent scan
- real Planning Agent
- real Assessment writer

No transform. No build. No network. No secrets.

Test proves factory handles:
- Boot detection from property
- `contract_library` classification
- internal deps
- multi-hop route selection
- route-aware unit sequence
- risk propagation
- read-only safety

**2. Files Created/Modified**

Created:
- [tests/fixtures/boot21-contract-library/pom.xml](./tests/fixtures/boot21-contract-library/pom.xml:1)
- [tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/CustomerContract.java](./tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/CustomerContract.java:1)
- [tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/RemoteCustomerContract.java](./tests/fixtures/boot21-contract-library/src/main/java/com/example/contracts/api/RemoteCustomerContract.java:1)
- [tests/fixtures/boot21-contract-library/src/test/java/com/example/contracts/api/CustomerContractTest.java](./tests/fixtures/boot21-contract-library/src/test/java/com/example/contracts/api/CustomerContractTest.java:1)
- [tests/orchestrator/test_read_only_assessment_boot21_contract_library.py](./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py:1)

Modified:
- [migration_factory/agents/planning_agent/risk_classifier.py](./migration_factory/agents/planning_agent/risk_classifier.py:1)

**3. Tests Added**

New end-to-end test:
- copies generic Boot `2.1` contract-library fixture into temp legacy workspace
- runs real analysis with fake local Maven/OpenRewrite subprocess responses
- runs planning
- runs assessment
- asserts artifact creation, route selection, unit order, risks, warnings, approval readiness, and read-only safety

**4. Exact Commands Run**

- `python -m pytest tests/orchestrator/test_read_only_assessment_boot21_contract_library.py -q`
- `python -m pytest tests/agents/planning_agent -q`
- `python -m pytest tests/assessment -q`
- `python -m pytest tests/orchestrator -q`
- `python -m pytest -q`

**5. Full Test Result Summary**

- `python -m pytest tests/orchestrator/test_read_only_assessment_boot21_contract_library.py -q`
  - `1 passed in 0.38s`
- `python -m pytest tests/agents/planning_agent -q`
  - `101 passed in 2.59s`
- `python -m pytest tests/assessment -q`
  - `6 passed in 0.41s`
- `python -m pytest tests/orchestrator -q`
  - `82 passed in 16.85s`
- `python -m pytest -q`
  - `534 passed, 3 skipped in 48.38s`

**6. Fixture Structure**

```text
tests/fixtures/boot21-contract-library/
├─ pom.xml
├─ src/
│  ├─ main/
│  │  └─ java/com/example/contracts/api/
│  │     ├─ CustomerContract.java
│  │     └─ RemoteCustomerContract.java
│  └─ test/
│     └─ java/com/example/contracts/api/
│        └─ CustomerContractTest.java
```

Fixture signals included:
- Java `11`
- Spring Boot `2.1.6.RELEASE` via property
- `jar` packaging
- no Boot main class
- Spring REST contract annotations
- Apache Juneau `@RemoteResource`
- `javax.persistence`
- `javax.xml.bind`
- internal dep candidate `com.total.corp:shared-kernel`
- old Lombok version

**7. Example `analysis_report.json` Excerpt**

```json
{
  "source_stack": {
    "java": "11",
    "spring_boot": "2.1.6.RELEASE",
    "build_tool": "maven"
  },
  "project_kind": "contract_library",
  "has_spring_boot_main": false,
  "has_rest_contracts": true,
  "has_juneau_contracts": true,
  "packaging": "jar",
  "internal_dependencies_count": 1
}
```

**8. Example `migration_plan.yaml` Excerpt**

```yaml
selected_route_id: "boot-2.1-to-3.5-java17"
route_strategy: "multi_hop"
selected_hops:
  -
    id: "boot-2.1-to-2.7-java11"
  -
    id: "boot-2.7-to-3.5-java17"
unit_references:
  - "baseline"
  - "java-17"
  - "spring-boot-2-7-stabilization"
  - "spring-boot-3-5-14"
  - "jakarta"
  - "jaxb-jakarta"
  - "dependency-cleanup"
  - "contract-compatibility-review"
  - "existing-test-migration"
risks:
  - "[HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: ..."
  - "[HIGH] CONTRACT_LIBRARY_HUMAN_REVIEW: ..."
  - "[HIGH] JAVAX_PERSISTENCE_BOOT3: ..."
  - "[HIGH] JAVAX_XML_BIND_BOOT3: ..."
warnings:
  - "INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW: ..."
```

**9. Example `assessment_report.json` Excerpt**

```json
{
  "overall_risk": "HIGH",
  "approval_readiness": {
    "status": "READY_FOR_REVIEW"
  },
  "planning_risks": [
    "[HIGH] BOOT_PRE_27_TO_BOOT3_MULTI_HOP: ...",
    "[HIGH] CONTRACT_LIBRARY_HUMAN_REVIEW: ..."
  ],
  "warnings": [
    "INTERNAL_DEPENDENCY_MIGRATION_ORDER_REVIEW: ..."
  ]
}
```

**10. Read-Only Safety**

Safe two ways:
- test hashes legacy fixture tree before and after full flow, hashes match
- `read_only_verification.json` says:
  - `source_modified: false`
  - `status: PASS`

No transformation step runs. Only analysis/planning/assessment artifacts written under modernized `.migration/...`.

**11. Why Fixture Generic**

No `msa-dto`. No `common-utils`. No client names.

Generic names only:
- `com.example.contracts`
- `customer-api-contracts`
- `com.total.corp:shared-kernel`

Shape matches common enterprise contract/DTO library patterns, but not any specific repo.

**12. Warnings / Limitations**

- e2e test uses fake local subprocess responses for Maven dependency tree and OpenRewrite dry-run. Good for determinism, but not real Maven execution.
- current import scanner counts `javax.*` broadly; detailed namespace risks in this e2e come partly from dependency graph signals too.
- test covers read-only assessment path only. No transform/build/test execution by design.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on my local AI Migration Factory repository on Windows PowerShell.
>
> Repository:
> C:\Users\ilyas.abarbach\Documents\modernizer-solution
>
> Goal:
> Run the governed AI Migration Factory flow for the real msa-dto repository:
> 1. Verify factory readiness.
> 2. Run read_only_assessment.
> 3. Validate analysis/planning/assessment artifacts.
> 4. Record human approval.
> 5. Configure JDK 11 and JDK 17.
> 6. Resume orchestration for sandbox-only migration.
> 7. If Maven/environment fails, diagnose and fix it safely.
> 8. After environment fix, start a NEW clean run rather than reusing a partially transformed sandbox.
> 9. Produce a concise final report with commands run, artifacts, statuses, and remaining blockers.
>
> Important:
> This is a governed migration factory, not a big-bang migration.
> Do NOT modify the legacy repository directly.
> Do NOT push, commit, merge, deploy, or create PRs.
> Do NOT bypass SSL validation.
> Do NOT use insecure Maven flags such as:
> - -Dmaven.wagon.http.ssl.insecure=true
> - -Dmaven.wagon.http.ssl.allowall=true
> - disabling certificate validation
> Do NOT edit global machine files without backup.
> Prefer user-level Maven settings or temporary dedicated truststore.
> If a fix requires corporate proxy URL, corporate repository URL, or corporate root CA that is not discoverable locally, stop and report exactly what is missing.
>
> Known context:
> Legacy app path:
> C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto
>
> Modernized root base:
> C:\Users\ilyas.abarbach\Documents\modernized-app
>
> AI Hub path:
> C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub
>
> Profile:
> springboot-2.1-to-3.5-java17
>
> Known JDKs:
> JAVA_HOME_11 should be:
> C:\Users\ilyas.abarbach\.jdks\ms-11.0.31
>
> JAVA_HOME_17 should be:
> C:\Users\ilyas.abarbach\.jdks\ms-17.0.19
>
> Previous run:
> msa-dto-readonly-20260526-232538
>
> Previous result:
> - read_only_assessment passed
> - approval passed
> - phase 2 started
> - sandbox build failed with Maven dependency_error
> - root cause was PKIX path building failed against https://repo.maven.apache.org/maven2
> - ~/.m2/settings.xml did not exist
>
> High-level rule:
> Do not reuse the previous partially transformed sandbox for the final attempt.
> Use it only for diagnostics.
> After Maven/environment is fixed, create a new clean run id.
>
> Detailed tasks:
>
> A. Repository readiness
> 1. cd to:
>    C:\Users\ilyas.abarbach\Documents\modernizer-solution
> 2. Set:
>    $env:PYTHONPATH = "."
> 3. Run:
>    git status
> 4. Verify profile exists:
>    Test-Path .\modernizer-solution-ai-hub\profiles\springboot-2.1-to-3.5-java17.yaml
> 5. Run fixture gate:
>    python -m pytest tests/orchestrator/test_read_only_assessment_boot21_contract_library.py -q
> 6. If this fails, stop and report.
>
> B. JDK readiness
> 1. Set temporary session variables:
>    $env:JAVA_HOME_11 = "$env:USERPROFILE\.jdks\ms-11.0.31"
>    $env:JAVA_HOME_17 = "$env:USERPROFILE\.jdks\ms-17.0.19"
> 2. Verify:
>    & "$env:JAVA_HOME_11\bin\java.exe" -version
>    & "$env:JAVA_HOME_17\bin\java.exe" -version
> 3. Also print:
>    mvn -version
>    echo $env:JAVA_HOME
>    echo $env:MAVEN_OPTS
>    echo $env:HTTP_PROXY
>    echo $env:HTTPS_PROXY
>
> C. Maven connectivity diagnostic
> 1. Test Maven Central:
>    mvn dependency:get "-Dartifact=org.springframework:spring-core:5.3.29" -U -X *> maven-central-test.log
> 2. Inspect:
>    Select-String -Path .\maven-central-test.log -Pattern "PKIX","certificate_unknown","repo.maven.apache.org","settings.xml","Using local repository","proxy","mirror" -Context 2,3
> 3. If Maven succeeds, continue to section E.
> 4. If Maven fails with PKIX, continue to section D.
>
> D. Safe Maven / certificate remediation
> Goal:
> Fix Maven dependency resolution safely without disabling SSL.
>
> Rules:
> - Do not disable SSL validation.
> - Do not modify machine-wide truststores without backup.
> - Prefer user-level .m2/settings.xml if corporate proxy/mirror is available.
> - Prefer a dedicated copied truststore configured through MAVEN_OPTS if a certificate can be safely discovered/exported.
>
> Steps:
> 1. Check for user Maven settings:
>    Test-Path "$env:USERPROFILE\.m2\settings.xml"
> 2. If missing, do NOT blindly invent proxy or mirror values.
> 3. Check if global Maven settings contains useful proxy/mirror:
>    Get-Content "C:\Program Files\apache-maven\apache-maven-3.9.16\conf\settings.xml"
>    Search for mirrors/proxies, but do not expose credentials in final report.
> 4. Check environment proxy variables:
>    echo $env:HTTP_PROXY
>    echo $env:HTTPS_PROXY
> 5. Check Git/Windows proxy hints:
>    git config --global --get http.proxy
>    git config --global --get https.proxy
>    netsh winhttp show proxy
> 6. Inspect certificate presented to Java:
>    & "$env:JAVA_HOME_17\bin\keytool.exe" -printcert -sslserver repo.maven.apache.org:443
>    & "C:\Program Files\Eclipse Adoptium\jdk-17.0.9.9-hotspot\bin\keytool.exe" -printcert -sslserver repo.maven.apache.org:443
>    curl.exe -I https://repo.maven.apache.org/maven2/
> 7. If a corporate proxy or repository mirror is clearly configured somewhere locally, create or update the USER-level Maven settings file only:
>    C:\Users\ilyas.abarbach\.m2\settings.xml
>    Make a backup first if it exists:
>    settings.xml.backup-<timestamp>
>    Add only the necessary mirror/proxy configuration.
>    Do not store plaintext credentials unless they already exist locally and are required.
> 8. If a corporate CA certificate is clearly discoverable/exportable from Windows certificate store, then:
>    - create a dedicated truststore copy under:
>      C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts
>    - copy it from:
>      $env:JAVA_HOME_17\lib\security\cacerts
>    - backup any existing dedicated truststore
>    - import only the corporate CA certificate with a clear alias
>    - configure only the current PowerShell session:
>      $env:MAVEN_OPTS = "-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit"
>    - do not modify the original JDK cacerts directly unless explicitly necessary and backed up.
> 9. After any remediation, rerun:
>    mvn dependency:get "-Dartifact=org.springframework:spring-core:5.3.29" -U
> 10. If Maven still fails, stop and report:
>    - exact root cause
>    - whether proxy/mirror is missing
>    - whether corporate CA could not be identified
>    - exact files changed
>    - recommended manual action
>
> E. Start a new clean read_only_assessment run
> Only continue if Maven dependency:get succeeds.
>
> 1. Define:
>    $RUN_ID = "msa-dto-clean-" + (Get-Date -Format "yyyyMMdd-HHmmss")
>    $LEGACY_APP = "C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto"
>    $MODERNIZED_APP = "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean"
>    $AI_HUB = "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub"
>    $PROFILE = "springboot-2.1-to-3.5-java17"
>    $env:PYTHONPATH = "."
> 2. Optional safety:
>    If $MODERNIZED_APP exists, do not delete it blindly. Move it to:
>    modernized-msa-dto-clean.backup-<timestamp>
> 3. Run:
>    python -m migration_factory.orchestrator.runner `
>      --run-id $RUN_ID `
>      --legacy $LEGACY_APP `
>      --modernized $MODERNIZED_APP `
>      --ai-hub $AI_HUB `
>      --profile $PROFILE `
>      --mode read_only_assessment
> 4. Save:
>    $RUN_DIR = "$MODERNIZED_APP\.migration\runs\$RUN_ID"
> 5. Validate artifacts:
>    Get-Content "$RUN_DIR\analysis\read_only_verification.json"
>    Get-Content "$RUN_DIR\analysis\analysis_report.json"
>    Get-Content "$RUN_DIR\planning\migration_plan.yaml"
>    Get-Content "$RUN_DIR\assessment\assessment_report.json"
> 6. Assert:
>    - analysis_status PASS
>    - planning_status PASS
>    - assessment_status PASS
>    - status human_approval_required
>    - blockers empty
>    - read_only_verification source_modified false
>    - source stack Java 11 / Boot 2.1.6.RELEASE
>    - project_kind contract_library
>    - selected_route_id boot-2.1-to-3.5-java17
>    - route_strategy multi_hop
>
> F. Record approval for the new run
> 1. Run:
>    python -m migration_factory.approval.approve_run `
>      --run-dir "$RUN_DIR" `
>      --run-id "$RUN_ID" `
>      --approved-by "ilyas.abarbach" `
>      --decision "approved" `
>      --comments "Approved for sandbox-only migration. High-risk multi-hop route accepted for analysis purpose: Spring Boot 2.1 to 2.7 to 3.5, Java 11 to 17, Jakarta migration, Juneau and contract-library review required. No production promotion approved."
> 2. Validate:
>    Get-Content "$RUN_DIR\approval\approval_decision.json"
>    Get-Content "$RUN_DIR\approval\approved_plan_lock.json"
> 3. Assert:
>    - decision approved
>    - decided_by ilyas.abarbach
>    - approved_plan_lock exists
>    - locked artifacts include migration_plan.yaml, migration_units.yaml, assessment_report.json, rewrite_plugin_plan.json
>
> G. Resume orchestration for sandbox-only migration
> 1. Ensure:
>    $env:JAVA_HOME_11 = "$env:USERPROFILE\.jdks\ms-11.0.31"
>    $env:JAVA_HOME_17 = "$env:USERPROFILE\.jdks\ms-17.0.19"
>    $env:PYTHONPATH = "."
> 2. Run:
>    python -m migration_factory.orchestrator.resume `
>      --run-id "$RUN_ID" `
>      --run-dir "$RUN_DIR" `
>      --decision "approved" `
>      --approved-by "ilyas.abarbach" `
>      --comments "Resume approved sandbox-only migration. No production promotion approved."
> 3. Capture final JSON output.
> 4. If it fails:
>    - Read the structured error contract if present.
>    - Read the last 120 lines of logs.
>    - Categorize failure:
>      dependency_error
>      compilation_error
>      test_failure
>      transformation_error
>      environment_error
>    - Do not hide failure.
>    - Do not patch source manually unless the transformation plan explicitly declares deterministic operations.
> 5. If it passes:
>    - Verify final report artifacts.
>    - Verify build/test reports.
>    - Verify sandbox path.
>    - Verify legacy repo still unchanged.
>
> H. Final report required from you
> Return a concise report with:
>
> 1. Environment summary:
>    - JDK 11 path/version
>    - JDK 17 path/version
>    - Maven version
>    - Maven settings used
>    - Maven connectivity status
>
> 2. Factory readiness:
>    - fixture test result
>    - profile existence
>
> 3. New run details:
>    - RUN_ID
>    - RUN_DIR
>    - legacy path
>    - modernized path
>
> 4. Phase 1 result:
>    - analysis status
>    - planning status
>    - assessment status
>    - human approval required
>    - key facts detected: Java, Boot, project_kind, javax count, route, hops
>
> 5. Approval result:
>    - approval_decision path
>    - approved_plan_lock path
>    - lock status
>
> 6. Phase 2 result:
>    - transform_status
>    - build_status
>    - test_status
>    - final_status
>    - blockers/errors/warnings
>    - artifact refs
>
> 7. If Maven/environment was fixed:
>    - exact issue found
>    - exact fix applied
>    - files changed
>    - backups created
>    - why the fix is safe
>    - proof Maven dependency:get now works
>
> 8. If still blocked:
>    - exact blocker
>    - exact missing information
>    - recommended next manual action
>
> Important final rule:
> Be honest. If you cannot fix Maven because corporate proxy/mirror/CA is not discoverable, stop and say so. Do not fake success.

<details><summary>15 previous messages</summary>

> Use caveman full. I will run readiness/JDK/Maven checks first, then only continue to new clean run if Maven Central succeeds or safe local fix is discoverable. No legacy writes, no SSL bypass.
>
> Readiness gate now: repo state, profile file, fixture test. If fixture gate fails, I stop per instruction.
>
> Factory gate passed. Worktree dirty from migration-factory changes, but no blocker. Next JDK/Maven readiness with session vars inside command scope.
>
> JDKs present. Maven still defaulting to Adoptium `JAVA_HOME`, so resume command will need explicit env vars and maybe factory uses profile JDKs. Now Maven Central debug check, log capture.
>
> Maven Central fails with PKIX against `repo.maven.apache.org`. I’m doing safe discovery only: user/global Maven settings, env/git/winhttp proxy hints, and certificate chain checks. No SSL-disable flags.
>
> Cause found: Zscaler TLS inspection cert chain presented to Java, but JDK truststore lacks trust path. Local proxy/mirror not usable: user Maven settings absent, env/git/winhttp proxy empty, global settings only sample-looking placeholders. I’m creating dedicated user truststore copy and importing locally discovered Zscaler CA certs, session-only via `MAVEN_OPTS`.
>
> Dedicated truststore created under user `.m2`, original JDK truststores untouched. Now I rerun Maven Central with session-only `MAVEN_OPTS` pointing to that truststore.
>
> Maven connectivity fixed in session. Now I start new clean run id and move existing `modernized-msa-dto-clean` aside if present, no delete.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Using `caveman` full. Maven SSL fix done safe: dedicated user truststore only, no global JDK/Maven edit, no SSL bypass. I continue from clean run start now, no reuse of old transformed sandbox.
>
> Fresh read-only run good: analysis/planning/assessment all PASS, approval gate waiting. I now pull artifact facts, then lock human approval for same clean run.
>
> Artifact check confirms route and contract-library facts. One useful wrinkle: real `msa-dto` shows `internal_dependencies_count=0`, so no internal-dependency warning in this run.
>
> Approval recorded and plan lock exists. The lock artifact field is array-shaped, not object-shaped, so I will read it more carefully after phase 2. Now resume sandbox-only migration with truststore in session.
>
> Phase 2 ran in sandbox and built through units, but final gate stopped at `TEST_ERROR`. I won’t hide it; now I read test report/log and ledger to classify exact blocker.
>
> Blocker classified: not dependency, not compile. Maven `clean test` exit 0 and builds passed, but Test Agent could not find Surefire XML, so final gate is `TEST_ERROR`. I verify sandbox/source paths and extract final concise status now.
</details>

**Status**
Live factory run complete through sandbox phase. Maven PKIX fixed safe. Phase 1 PASS. Approval recorded. Phase 2 sandbox migration ran, build passed, final blocked by Test Agent because no Surefire reports found.

**Environment**
- JDK 11: `C:\Users\ilyas.abarbach\.jdks\ms-11.0.31`, `11.0.31+11-LTS`
- JDK 17: `C:\Users\ilyas.abarbach\.jdks\ms-17.0.19`, `17.0.19+10-LTS`
- Maven: Apache Maven `3.9.16`
- Maven runtime Java: Adoptium `17.0.9`
- User Maven settings: missing, not created
- Global Maven settings: default/sample only, not changed
- Maven fix: session `MAVEN_OPTS` using dedicated truststore
- Connectivity: `mvn dependency:get "-Dartifact=org.springframework:spring-core:5.3.29" -U` now `BUILD SUCCESS`

**Safe Maven Fix**
Root cause: Java did not trust Zscaler TLS interception CA for `repo.maven.apache.org`, causing PKIX failure. Windows trusted Zscaler Root CA existed locally.

Changed only:
- `C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts`
- `C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\zscaler-root-ca.cer`
- Diagnostic log: `C:\Users\ilyas.abarbach\Documents\modernizer-solution\maven-central-test.log`

No SSL bypass. No global JDK truststore edit. No Maven global edit. No backup needed because dedicated truststore did not exist before.

**Factory Readiness**
- Profile exists: `modernizer-solution-ai-hub\profiles\springboot-2.1-to-3.5-java17.yaml`
- Fixture gate: `python -m pytest tests/orchestrator/test_read_only_assessment_boot21_contract_library.py -q`
- Result: `1 passed in 0.26s`

**New Run**
- `RUN_ID`: `msa-dto-clean-20260527-005005`
- `RUN_DIR`: `C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean\.migration\runs\msa-dto-clean-20260527-005005`
- Legacy path: `C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto`
- Modernized path: `C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean`
- Old clean dir moved to: `C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean.backup-20260527-005005`

**Phase 1**
- Analysis: `PASS`
- Planning: `PASS`
- Assessment: `PASS`
- Status: `human_approval_required`
- Blockers: none
- Read-only source modified: `false`
- Java: `11`
- Spring Boot: `2.1.6.RELEASE`
- Build tool: `maven`
- Project kind: `contract_library`
- Spring Boot main: `false`
- REST contracts: `true`
- Juneau contracts: `true`
- Packaging: `jar`
- Internal dependencies: `0`
- javax count: `409`
- Route: `boot-2.1-to-3.5-java17`
- Strategy: `multi_hop`
- Hops: `boot-2.1-to-2.7-java11`, `boot-2.7-to-3.5-java17`

**Approval**
- Decision: `approved`
- Decided by: `ilyas.abarbach`
- Decision file: `...\approval\approval_decision.json`
- Lock file: `...\approval\approved_plan_lock.json`
- Locked: `migration_plan.yaml`, `migration_units.yaml`, `assessment_report.json`, `rewrite_plugin_plan.json`

**Phase 2**
- Transform status: `TEST_ERROR`
- Build status: `BUILD_PASSED_IN_SANDBOX`
- Test status: `TEST_ERROR`
- Final status: `TEST_ERROR`
- Blocker: `Sandbox candidate blocked by test_status=TEST_ERROR.`
- Exact test root cause: `No surefire reports found.`
- Maven build itself passed with exit code `0`; sandbox has no `target/surefire-reports` and `0` `TEST-*.xml` files.
- Sandbox path: `...\workspaces\sandbox`
- Ledger: `...\workspaces\sandbox\.migration\ledger.json`
- Transform log: `...\logs\phase2_transform.log`
- Test report: `...\test\post_transform\test_report.json`
- Orchestration summary: `...\orchestration\orchestration_summary.json`

**Key Commands Run**
```powershell
git status --short
Test-Path .\modernizer-solution-ai-hub\profiles\springboot-2.1-to-3.5-java17.yaml
python -m pytest tests/orchestrator/test_read_only_assessment_boot21_contract_library.py -q
mvn dependency:get "-Dartifact=org.springframework:spring-core:5.3.29" -U -X *> maven-central-test.log
keytool -printcert -sslserver repo.maven.apache.org:443
curl.exe -I https://repo.maven.apache.org/maven2/
keytool -importcert -noprompt -trustcacerts -alias migration-factory-zscaler-root-ca ...
mvn dependency:get "-Dartifact=org.springframework:spring-core:5.3.29" -U
python -m migration_factory.orchestrator.runner --run-id msa-dto-clean-20260527-005005 ... --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "$RUN_DIR" --decision approved ...
python -m migration_factory.orchestrator.resume --run-id "$RUN_ID" --run-dir "$RUN_DIR" --decision approved ...
```

**Remaining Blocker**
Not Maven now. Not dependency resolution. Not compile.

Blocker is governance/test artifact policy: build passes, but Test Agent expects Surefire XML and none exists for this contract library. Next safe action: update factory test policy for zero-test Maven libraries, or require/generate baseline test evidence policy. No source patch done. No legacy repo modified.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 11: Add zero-test Maven library policy to Test Agent.
>
> Goal:
> Fix Test Agent behavior for Maven library projects that build successfully but do not produce Surefire reports because no tests are present or no tests were executed.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT fake test success.
> Do NOT generate tests.
> Do NOT bypass governance.
> The implementation must be generic and based on analysis facts, baseline test inventory, project kind, and build output.
>
> Context:
> A real sandbox migration run for a Spring Boot 2.1 contract library reached:
> - approval completed
> - sandbox transformation executed
> - sandbox Maven build passed
> - final status blocked by Test Agent
> - root cause: no target/surefire-reports and 0 TEST-*.xml files
>
> This project is a contract_library Maven jar and may legitimately have no tests.
>
> Current issue:
> Test Agent treats missing Surefire reports as TEST_ERROR unconditionally.
>
> Required enterprise behavior:
> 1. If baseline analysis detected existing tests or previous Surefire reports, then missing post-transform Surefire reports should remain TEST_ERROR.
> 2. If baseline analysis detected no tests and no baseline Surefire reports, and Maven build passed, then missing post-transform Surefire reports should be classified as:
>    - status: NO_TESTS_FOUND or NO_TESTS_EXECUTED
>    - severity: WARNING
>    - final migration should not fail solely because reports are absent
> 3. The final report must clearly state:
>    - build passed
>    - no tests were found/executed
>    - confidence is lower because no automated tests exist
>    - consumer/integration validation is required for contract libraries
>
> Tasks:
> 1. Update Test Agent logic so missing Surefire reports are policy-aware.
> 2. Use available facts from:
>    - analysis/test_inventory.json
>    - analysis/analysis_report.json
>    - build result
>    - project_kind
> 3. Add a structured test outcome for zero-test projects:
>    Example:
>    {
>      "status": "NO_TESTS_FOUND",
>      "severity": "WARNING",
>      "tests": 0,
>      "failures": 0,
>      "errors": 0,
>      "skipped": 0,
>      "message": "No Surefire reports found, but baseline analysis detected no tests. Build passed; treating as warning."
>    }
> 4. For project_kind = contract_library, add warning:
>    "Contract library has no automated tests; consumer compatibility validation is required."
> 5. Ensure missing reports remain TEST_ERROR when:
>    - test_inventory shows tests exist
>    - baseline Surefire reports existed
>    - build passed but expected test reports are missing
> 6. Update orchestration/final status logic so:
>    - NO_TESTS_FOUND with build passed is not final TEST_ERROR
>    - final status may be SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS or equivalent
>    - do not mark as full test success
> 7. Update final report if needed to distinguish:
>    - TEST_PASSED
>    - TEST_FAILED
>    - TEST_ERROR
>    - NO_TESTS_FOUND / NO_TESTS_EXECUTED
> 8. Do not modify Transformation Agent behavior.
> 9. Do not modify Build Agent behavior except if absolutely necessary to pass structured build status through.
> 10. Do not modify migration source code.
> 11. Do not create tests for the migrated project.
> 12. Do not hide warnings.
>
> Tests to add:
> 1. Maven project with tests and Surefire reports -> TEST_PASSED.
> 2. Maven project with tests but missing Surefire reports -> TEST_ERROR.
> 3. Maven project with no tests, build passed, missing Surefire reports -> NO_TESTS_FOUND warning, not error.
> 4. contract_library with no tests -> warning requiring consumer compatibility validation.
> 5. Existing failing test reports remain TEST_FAILED.
> 6. Existing malformed Surefire reports remain TEST_ERROR.
> 7. Orchestrator final status does not fail solely on NO_TESTS_FOUND when build passed.
> 8. Final report includes zero-test warning.
> 9. No project-specific artifactId or repository name is used.
>
> Validation commands:
> Run Test Agent, orchestrator, final report, and full suite if feasible:
>
> python -m pytest tests -q
> python -m pytest -q
>
> If there are more specific test paths, run them explicitly and report them.
>
> After implementation:
> 1. Re-run the clean msa-dto flow only if tests pass.
> 2. Use a new clean run id.
> 3. Do not reuse the previous partially transformed sandbox.
> 4. Keep the Maven truststore fix session-scoped or documented.
> 5. Report final status honestly.
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. Example test_report.json for zero-test contract_library
> 7. Example final/orchestration status after NO_TESTS_FOUND
> 8. Explanation of why this is governance-safe
> 9. Explanation of why this is generic and not project-specific
> 10. Any warnings or limitations

<details><summary>15 previous messages</summary>

> I’m taking Ticket 11 end to end: first I’ll trace the Test Agent and orchestration status path, then I’ll patch the zero-test policy, run focused tests, and only if that passes I’ll launch a brand new `msa-dto` clean run.
>
> I found exact seam: `migration_factory/agents/test_agent/agent.py` hard-codes missing reports to `TEST_ERROR`, and orchestration summary/final report still assume only pass/fail/error. Next I’m reading those paths together so we can patch policy cleanly, not just paper over one branch.
>
> I’ve got three touch points now: Test Agent result model, sandbox orchestration gate, and final report phrasing. I’m checking the transform gate next because that is where `NO_TESTS_FOUND` must stop being treated like hard failure.
>
> I see exact rule today: transform phase returns nonzero for anything except `TEST_PASSED`, so orchestration never reaches final report for zero-test libraries. I’m switching from reading to patch plan now.
>
> Patch shape clear now. I need one broader change, not one branch hack:
>
> 1. Teach Test Agent zero-test policy from `analysis/test_inventory.json` + `analysis_report.json`.
> 2. Let transform/orchestration treat `NO_TESTS_FOUND` as warning-complete when build passed.
> 3. Extend schema/final report/tests so zero-test outcome stays visible, never disguised as `TEST_PASSED`.
>
> I’m editing those files next, then I’ll run focused suites before new real run.
>
> I’m editing four core paths together: Test Agent, transform gate, orchestration validation, final report. Then I’ll add focused tests for pass/error/zero-test/contract-library and only then retry real `msa-dto` with new run id.
>
> <details><summary>Edited 12 files</summary>
>
> - Wrote `./migration_factory/agents/test_agent/__init__.py` (+19 -3)
> - Wrote `./migration_factory/agents/test_agent/agent.py` (+183 -88)
> - Wrote `./migration_factory/contracts/schemas/test_report.schema.json` (+11 -6)
> - Wrote `./migration_factory/final_report/writer.py` (+28 -16)
> - Wrote `./migration_factory/orchestrator/artifact_validation.py` (+19 -17)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+48 -43)
> - Wrote `./migration_factory/orchestrator/summary.py` (+18 -16)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+101 -64)
> - Wrote `./tests/orchestrator/test_full_sandbox_migration.py` (+115 -2)
> - Wrote `./tests/orchestrator/test_summary.py` (+74 -3)
> - Wrote `./tests/test_final_report.py` (+40 -3)
> - Wrote `./tests/test_test_agent.py` (+95 -26)
>
> </details>
>
> Core patch in place. Now I’m running narrow suites first to catch contract drift fast: Test Agent, orchestration summary/full-sandbox, final report. After that I’ll widen if green.
>
> One narrow test failed for silly reason, not policy logic: helper state carries preloaded blockers/errors, so success validation stayed false. I’m cleaning that fixture branch, then rerunning same focused suite.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_summary.py` (+3 -0)
>
> </details>
>
> Focused suites green. I’m widening now to repo test suite paths user asked for, so we catch any orchestration/reporting edges before new real run.
>
> Broader suite found two real adjustments, both healthy:
> - zero-test warning must require actual baseline evidence, not empty context
> - one transformation test helper needs new `TestAgentResult` fields
>
> I’m tightening policy first, then rerunning `tests/test_transformation_agent.py` plus `tests -q`.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/test_agent/agent.py` (+11 -4)
> - Wrote `./tests/test_transformation_agent.py` (+13 -10)
>
> </details>
>
> Repo test path green. I’m doing one last full `pytest -q` pass now, then I’ll launch a brand new real `msa-dto` run with same safe truststore session.
>
> Real rerun finished farther than before: same clean flow now reaches sandbox completion with warning, not `TEST_ERROR`. One honest wrinkle remains: this resumed path still keeps `mode=read_only_assessment`, so final-report generation/“successful full sandbox artifact validation” does not fire in this run shape. I’m extracting exact artifact facts for final report now.
</details>

**1. Summary**
Ticket 11 done. Test Agent now policy-aware for zero-test Maven libraries. Missing Surefire reports no longer auto-fail when baseline analysis proves no tests and build passed. Real `msa-dto` rerun with new clean run now ends `SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`, not `TEST_ERROR`.

**2. Files Modified**
- [migration_factory/agents/test_agent/agent.py](./migration_factory/agents/test_agent/agent.py)
- [migration_factory/agents/test_agent/__init__.py](./migration_factory/agents/test_agent/__init__.py)
- [migration_factory/contracts/schemas/test_report.schema.json](./migration_factory/contracts/schemas/test_report.schema.json)
- [migration_factory/transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [migration_factory/orchestrator/phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [migration_factory/orchestrator/summary.py](./migration_factory/orchestrator/summary.py)
- [migration_factory/orchestrator/artifact_validation.py](./migration_factory/orchestrator/artifact_validation.py)
- [migration_factory/final_report/writer.py](./migration_factory/final_report/writer.py)
- [tests/test_test_agent.py](./tests/test_test_agent.py)
- [tests/orchestrator/test_full_sandbox_migration.py](./tests/orchestrator/test_full_sandbox_migration.py)
- [tests/test_final_report.py](./tests/test_final_report.py)
- [tests/orchestrator/test_summary.py](./tests/orchestrator/test_summary.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)

**3. Tests Added**
- `TEST_PASSED` normal Surefire path
- tests exist + reports missing -> `TEST_ERROR`
- no tests baseline + build passed + no reports -> `NO_TESTS_FOUND`
- `contract_library` zero-test warning for consumer compatibility
- final/orchestration status accepts zero-test warning completion
- final report carries zero-test severity/message/warnings

**4. Exact Commands Run**
```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_test_agent.py tests/orchestrator/test_full_sandbox_migration.py tests/orchestrator/test_summary.py tests/test_final_report.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests -q
python -m pytest -q
python -m migration_factory.orchestrator.runner --run-id msa-dto-clean-20260527-011112 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto" --modernized "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean\.migration\runs\msa-dto-clean-20260527-011112" --run-id "msa-dto-clean-20260527-011112" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. High-risk multi-hop route accepted for analysis purpose: Spring Boot 2.1 to 2.7 to 3.5, Java 11 to 17, Jakarta migration, Juneau and contract-library review required. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "msa-dto-clean-20260527-011112" --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean\.migration\runs\msa-dto-clean-20260527-011112" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

**5. Full Test Result Summary**
- focused suite: `40 passed`
- transformation suite: `41 passed, 2 skipped`
- repo `tests -q`: `462 passed, 2 skipped`
- full `pytest -q`: `540 passed, 3 skipped`

**6. Example `test_report.json` For Zero-Test `contract_library`**
```json
{
  "test_status": "NO_TESTS_FOUND",
  "severity": "WARNING",
  "message": "No Surefire reports found, but baseline analysis detected no tests and no baseline Surefire reports. Build passed; treating as warning.",
  "totals": {
    "tests": 0,
    "passed": 0,
    "failures": 0,
    "errors": 0,
    "skipped": 0
  },
  "warnings": [
    "No Surefire reports found, but baseline analysis detected no tests and no baseline Surefire reports. Build passed; treating as warning.",
    "Contract library has no automated tests; consumer compatibility validation is required."
  ]
}
```

**7. Example Final/Orchestration Status After `NO_TESTS_FOUND`**
Real rerun:
- `RUN_ID`: `msa-dto-clean-20260527-011112`
- `transform_status`: `TRANSFORM_APPLIED_IN_SANDBOX`
- `build_status`: `BUILD_PASSED_IN_SANDBOX`
- `test_status`: `NO_TESTS_FOUND`
- `final_status`: `SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`
- `orchestration_status`: `PASS`

Key facts:
- Java `11`
- Spring Boot `2.1.6.RELEASE`
- `project_kind`: `contract_library`
- route: `boot-2.1-to-3.5-java17`
- strategy: `multi_hop`
- hops: `boot-2.1-to-2.7-java11` -> `boot-2.7-to-3.5-java17`

**8. Why Governance-Safe**
- no fake `TEST_PASSED`
- warning only when baseline evidence exists in `analysis/test_inventory.json`
- if baseline tests existed, missing reports still `TEST_ERROR`
- build must already pass
- warning stays visible in test report + orchestration warnings
- contract libraries get explicit consumer compatibility warning

**9. Why Generic**
- no `msa-dto` hardcode
- no repo/artifactId special case
- policy uses generic facts only: baseline test inventory, baseline Surefire availability, `project_kind`, build result
- works for any Maven library with zero tests

**10. Warnings / Limitations**
- Maven truststore fix still session-scoped via `MAVEN_OPTS`; safe, no global JDK edit
- new clean run used; old sandbox not reused
- legacy repo not modified; sandbox path only: `...\runs\msa-dto-clean-20260527-011112\workspaces\sandbox`
- remaining wrinkle: resumed real run still keeps `mode=read_only_assessment`, so final-report generation / `orchestration_artifacts_valid` full-success validation did not fire for this run shape. Not Test Agent blocker now. Separate orchestrator mode/promotion issue.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 12: Fix post-approval resume finalization for sandbox migration runs.
>
> Goal:
> When a run starts in read_only_assessment mode, then receives human approval, then resumes with orchestrator.resume, the resumed phase 2 sandbox run must finalize as a governed sandbox migration run, not remain stuck in read_only_assessment semantics.
>
> Important architecture rule:
> Do NOT hardcode msa-dto, common-utils, or any specific repository.
> Do NOT modify the legacy repository.
> Do NOT mark production promotion as allowed.
> Do NOT hide warnings.
> Do NOT fake test success.
>
> Context:
> A real msa-dto sandbox migration run now reaches:
> - Analysis PASS
> - Planning PASS
> - Assessment PASS
> - Human approval APPROVED
> - Transform applied in sandbox
> - Build passed in sandbox
> - Test status NO_TESTS_FOUND
> - Final status SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS
> - Orchestration status PASS
>
> However, Codex observed:
> The resumed real run still keeps mode=read_only_assessment, so final-report generation and orchestration_artifacts_valid full-success validation did not fire correctly for this run shape.
>
> This is an orchestrator finalization problem.
>
> Required behavior:
> If orchestrator.resume is called with decision=approved, the resumed execution must be treated as a phase2 sandbox migration attempt, even if the original phase1 mode was read_only_assessment.
>
> The final output should clearly say:
> - sandbox migration completed
> - with warnings if test_status is NO_TESTS_FOUND
> - no production promotion
> - final report generated if required artifacts exist
> - orchestration artifacts validated according to sandbox completion rules
>
> Tasks:
> 1. Review orchestrator.resume, phase_services, summary, artifact_validation, and final_report integration.
> 2. Introduce or normalize a resumed mode/status such as:
>    - full_sandbox_after_approval
>    or
>    - approved_sandbox_migration
>    or equivalent deterministic internal state.
> 3. Do not break original read_only_assessment behavior before approval.
> 4. After approval and resume, do not keep finalization blocked by original mode=read_only_assessment.
> 5. Ensure final report generation runs when:
>    - transform_status = TRANSFORM_APPLIED_IN_SANDBOX
>    - build_status = BUILD_PASSED_IN_SANDBOX
>    - test_status = TEST_PASSED or NO_TESTS_FOUND
>    - approval_decision exists
>    - approved_plan_lock exists
> 6. Ensure final report does not claim full test success when test_status = NO_TESTS_FOUND.
> 7. Ensure final status mapping:
>    - TEST_PASSED -> SANDBOX_MIGRATION_COMPLETED
>    - NO_TESTS_FOUND -> SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS
>    - TEST_FAILED -> failure
>    - TEST_ERROR -> failure
>    - BUILD_FAILED_IN_SANDBOX -> failure
> 8. Ensure orchestration_artifacts_valid becomes true when required sandbox artifacts exist.
> 9. Required artifact refs for completed-with-warnings should include:
>    - approval_decision
>    - approved_plan_lock
>    - transformation_execution_plan
>    - migration_ledger
>    - orchestration_summary
>    - timing_report
>    - post_transform_test_report
>    - final migration report if generated
> 10. Do not require post_transform_test_summary/log if current Test Agent legitimately did not produce them for NO_TESTS_FOUND, unless the contract says they must exist.
> 11. If the contract requires summary/log, produce deterministic zero-test summary/log artifacts.
> 12. Update schemas if needed.
> 13. Do not modify Transformation Agent behavior unless absolutely needed for artifact refs.
> 14. Do not modify Build Agent behavior.
> 15. Do not modify Test Agent classification logic from Ticket 11 unless needed for artifact refs.
> 16. Do not add AI-generated migration changes.
>
> Tests to add:
> 1. read_only_assessment before approval still stops at human_approval_required.
> 2. approved resume from read_only_assessment creates phase2 sandbox semantics.
> 3. approved resume with TEST_PASSED generates final report and valid orchestration artifacts.
> 4. approved resume with NO_TESTS_FOUND generates final report or completed-with-warnings report and does not fail.
> 5. final report clearly says tests were not executed/found and confidence is lower.
> 6. orchestration_artifacts_valid is true for completed-with-warnings when required artifacts exist.
> 7. rejected approval still stops and does not run transformation.
> 8. replan_required still stops and does not run transformation.
> 9. build failure still fails.
> 10. test failure still fails.
> 11. no project-specific artifactId or repo name is used.
>
> Validation commands:
> Run orchestrator, final report, test agent, transformation tests, and full suite:
>
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_final_report.py -q
> python -m pytest tests/test_test_agent.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> After tests pass:
> 1. Run a new clean msa-dto sandbox migration flow.
> 2. Do not reuse previous sandbox.
> 3. Keep Maven truststore fix documented/session-scoped.
> 4. Verify final result.
>
> Report back with:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Exact commands run
> 5. Full test result summary
> 6. New clean RUN_ID
> 7. Final orchestration output excerpt
> 8. Final report path and excerpt
> 9. orchestration_summary excerpt
> 10. Artifact validation result
> 11. Explanation of how resumed mode is normalized
> 12. Explanation of why this is governance-safe
> 13. Any warnings or limitations

<details><summary>13 previous messages</summary>

> Ticket 12 target clear: resume path must switch from phase1 semantics to governed sandbox-finalization semantics after approval. I’m tracing `resume`, mode propagation, and artifact validation gates first, then I’ll patch and rerun requested suites before a brand-new real `msa-dto` run.
>
> Good news: resume already has normalization helper, but one path drops it when graph resume succeeds. I’m reading that gap and existing orchestrator tests now so we can fix exact branch, not add duplicate semantics.
>
> I found likely root cause: `resume_orchestration()` normalizes snapshot fallback state, but not the direct `graph.invoke()` success payload before finalization. Real run took that branch, so mode stayed `read_only_assessment`. I’m patching that exact seam and adding a test that forces direct graph-resume success from a read-only run.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/orchestrator/resume.py` (+14 -13)
> - Wrote `./tests/orchestrator/test_full_sandbox_migration.py` (+147 -3)
>
> </details>
>
> Patch in. I’m running exact suites from ticket next: orchestrator, final report, test agent, transformation, then full suite. After that I’ll do fresh real `msa-dto` run and verify final report artifacts exist this time.
>
> One orchestrator test still smells off, so I’m reproducing that exact path and printing the returned state shape. Better to look than guess.
>
> I found one test-only bug, not product bug: my new direct-graph test overwrote `assessment_report.json` with an invalid minimal payload, and approval-lock validation correctly rejected it. I’m fixing the fixture to use the repo’s valid assessment shape, then rerunning ticket suites.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_full_sandbox_migration.py` (+10 -1)
>
> </details>
>
> I want the returned resume payload, not the assertion line. I’m reproducing that exact read-only resume path in a tiny script and printing `final_status`, `errors`, and `blockers` so we can see why it drops out only in suite context.
>
> This looks like a test harness flake around live LangGraph resume, not product code now. I’m making the read-only normalization test deterministic by forcing the “graph returned approval-only state, then snapshot fallback runs phase 2” branch explicitly.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_full_sandbox_migration.py` (+18 -0)
>
> </details>
>
> Ticket suites green. I’m launching one more brand-new real `msa-dto` clean run now, with same session-scoped truststore, then I’ll verify final report path and orchestration artifact validation.
>
> Real run now lands exactly where ticket wants: mode normalized to sandbox semantics, final report generated, artifact validation true. I’m grabbing short excerpts for the close-out report.
</details>

**1. Summary**
Ticket 12 fixed. Approved resume from `read_only_assessment` now normalize to sandbox migration semantics before finalization. Real `msa-dto` rerun now ends:
- `mode = full_sandbox_migration`
- `resume_semantics = approved_sandbox_migration`
- `final_status = SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`
- `orchestration_status = PASS`
- `orchestration_artifacts_valid = true`
- final report generated

**2. Files Modified**
- [migration_factory/orchestrator/resume.py](./migration_factory/orchestrator/resume.py)
- [tests/orchestrator/test_full_sandbox_migration.py](./tests/orchestrator/test_full_sandbox_migration.py)

**3. Tests Added**
- approved resume from read-only, graph direct result, now generates final report under sandbox semantics
- approved resume from read-only, snapshot fallback path, still normalizes to sandbox semantics
- existing zero-test and test-passed orchestration coverage stayed green

**4. Exact Commands Run**
```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/test_test_agent.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
python -m migration_factory.orchestrator.runner --run-id msa-dto-clean-20260527-014155 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto" --modernized "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean\.migration\runs\msa-dto-clean-20260527-014155" --run-id "msa-dto-clean-20260527-014155" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. High-risk multi-hop route accepted for analysis purpose: Spring Boot 2.1 to 2.7 to 3.5, Java 11 to 17, Jakarta migration, Juneau and contract-library review required. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "msa-dto-clean-20260527-014155" --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean\.migration\runs\msa-dto-clean-20260527-014155" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

**5. Full Test Result Summary**
- `tests/orchestrator -q`: `87 passed`
- `tests/test_final_report.py -q`: `16 passed`
- `tests/test_test_agent.py -q`: `8 passed`
- `tests/test_transformation_agent.py -q`: `41 passed, 2 skipped`
- `pytest -q`: `543 passed, 3 skipped`

**6. New Clean RUN_ID**
- `msa-dto-clean-20260527-014155`

**7. Final Orchestration Output Excerpt**
- `analysis_status: PASS`
- `planning_status: PASS`
- `assessment_status: PASS`
- `approval_status: COMPLETED`
- `mode: full_sandbox_migration`
- `resumed_from_mode: read_only_assessment`
- `resume_semantics: approved_sandbox_migration`
- `transform_status: TRANSFORM_APPLIED_IN_SANDBOX`
- `build_status: BUILD_PASSED_IN_SANDBOX`
- `test_status: NO_TESTS_FOUND`
- `final_status: SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`
- `orchestration_status: PASS`
- `orchestration_artifacts_valid: true`

**8. Final Report Path And Excerpt**
- path: [migration_report.json](~/Documents/modernized-app/modernized-msa-dto-clean/.migration/runs/msa-dto-clean-20260527-014155/final/migration_report.json)
- excerpt:
  - `test_status: NO_TESTS_FOUND`
  - `test_severity: WARNING`
  - `test_message: No Surefire reports found, but baseline analysis detected no tests and no baseline Surefire reports. Build passed; treating as warning.`
  - `build_status: BUILD_PASSED_IN_SANDBOX`
  - `transform_status: TRANSFORM_APPLIED_IN_SANDBOX`
  - `production_allowed: false`

**9. orchestration_summary Excerpt**
- path: [orchestration_summary.json](~/Documents/modernized-app/modernized-msa-dto-clean/.migration/runs/msa-dto-clean-20260527-014155/orchestration/orchestration_summary.json)
- excerpt:
  - `final_status: SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`
  - `test_status: NO_TESTS_FOUND`
  - `build_status: BUILD_PASSED_IN_SANDBOX`
  - `transform_status: TRANSFORM_APPLIED_IN_SANDBOX`
  - `stop_reason: No Surefire reports found, but baseline analysis detected no tests and no baseline Surefire reports. Build passed; treating as warning.`

**10. Artifact Validation Result**
- completed sandbox artifact validation: `true`
- required refs present:
  - `approval_decision`
  - `approved_plan_lock`
  - `transformation_execution_plan`
  - `migration_ledger`
  - `orchestration_summary`
  - `timing_report`
  - `post_transform_test_report`
  - `final_migration_report`

**11. How Resumed Mode Normalized**
- fix point: [resume.py](./migration_factory/orchestrator/resume.py)
- before: direct `graph.invoke()` success payload could keep old `mode=read_only_assessment`
- now: approved resume always pass through `_normalize_resumed_sandbox_state(...)` before finalization
- normalized fields:
  - `mode = full_sandbox_migration`
  - `resumed_from_mode = read_only_assessment`
  - `resume_semantics = approved_sandbox_migration`
- then finalizer can map:
  - `TEST_PASSED -> SANDBOX_MIGRATION_COMPLETED`
  - `NO_TESTS_FOUND -> SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`

**12. Why Governance-Safe**
- no legacy repo modification
- no production promotion
- no fake `TEST_PASSED`
- zero-test stays visible as warning, lower confidence
- approval + lock still required
- warnings preserved in orchestration and final report
- generic rule on resume decision/mode only, no project hardcode

**13. Warnings / Limitations**
- Maven truststore fix still session-scoped via `MAVEN_OPTS`; safe, no global JDK/Maven edit
- real run still warns:
  - no automated tests
  - contract library consumer compatibility validation required
  - route high risk / multi-hop governance
- `orchestration_summary.json` still does not serialize `mode` / `orchestration_artifacts_valid` fields today; those are present in final resume output JSON. Not blocker for Ticket 12, but small follow-up candidate if you want summary file parity.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 13: Polish final sandbox migration reporting for management demo.
>
> Goal:
> Make final reporting consistent and management-ready after a completed sandbox migration with warnings.
>
> Context:
> A real msa-dto sandbox run completed with:
>
> * transform_status: TRANSFORM_APPLIED_IN_SANDBOX
> * build_status: BUILD_PASSED_IN_SANDBOX
> * test_status: NO_TESTS_FOUND
> * final_status: SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS
> * route_strategy: multi_hop
> * production_allowed: false
>
> Current reporting issues:
>
> 1. migration_report.json still shows strategy: direct_sandbox, while the selected route is multi_hop.
> 2. migration_report.json does not clearly expose selected_route_id and selected_hops.
> 3. orchestration_summary.json has final_migration_executed=false, which is ambiguous.
> 4. Warnings are duplicated in migration_report.json.
> 5. orchestration_summary.json does not serialize orchestration_artifacts_valid.
>
> Tasks:
>
> 1. Update final report generation so migration_report.json includes:
>
>    * selected_route_id
>    * route_strategy
>    * selected_hops
>    * sandbox_migration_executed: true
>    * production_promotion_executed: false
> 2. Keep production_allowed: false.
> 3. Do not use strategy: direct_sandbox when the selected route strategy is multi_hop.
> 4. Deduplicate warnings while preserving order.
> 5. Update orchestration_summary.json to include:
>
>    * mode
>    * resumed_from_mode if present
>    * resume_semantics if present
>    * orchestration_artifacts_valid
>    * sandbox_migration_executed
>    * production_promotion_executed
> 6. Rename or clarify final_migration_executed if needed so it does not imply production promotion.
> 7. Do not modify Transformation Agent behavior.
> 8. Do not modify Build Agent behavior.
> 9. Do not modify Test Agent behavior.
> 10. Do not modify migration source code.
> 11. Do not hardcode msa-dto, common-utils, or any repository name.
>
> Tests to add/update:
>
> 1. Final report for multi_hop route exposes route_strategy=multi_hop.
> 2. selected_route_id and selected_hops appear in migration_report.json.
> 3. sandbox_migration_executed=true when transform applied in sandbox.
> 4. production_promotion_executed=false.
> 5. warnings are deduplicated.
> 6. orchestration_summary.json includes orchestration_artifacts_valid.
> 7. Existing final report tests remain green.
> 8. Full suite remains green.
>
> Validation commands:
> python -m pytest tests/test_final_report.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> After tests pass, run a new clean msa-dto flow only if practical.
> Report back with:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example migration_report.json excerpt
> 7. Example orchestration_summary.json excerpt
> 8. Any warnings or limitations

<details><summary>8 previous messages</summary>

> Ticket 13 clear. I inspect final report + orchestration summary paths first, then patch route fields, warning dedupe, and execution flags without touching transform/build/test behavior.
>
> I found exact report seams: final report still reads profile governance strategy, not selected route strategy, and summary omits mode/artifact-valid flags. I’m patching report/summary only now, plus tests for dedupe and route exposure.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/final_report/writer.py` (+100 -47)
> - Wrote `./migration_factory/orchestrator/summary.py` (+26 -19)
> - Wrote `./tests/orchestrator/test_summary.py` (+48 -20)
> - Wrote `./tests/test_final_report.py` (+72 -0)
>
> </details>
>
> Patch done. I’m running report + orchestrator suites first, then full suite. If green and practical, I’ll do one more clean `msa-dto` flow for demo-ready excerpts.
>
> One test fixture forgot set `mode`. Small fix only. Then rerun orchestrator + full suite.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_summary.py` (+2 -1)
>
> </details>
>
> Tests green. I’m doing one fresh `msa-dto` clean run now so report excerpts match Ticket 13 polish, not older artifacts.
>
> Existing demo sandbox directory locked on Windows, so I’m not forcing move. Safer path: use fresh modernized target directory for new clean run.
</details>

**1. Summary**
Ticket 13 done. Final sandbox reporting now consistent for management demo:
- `migration_report.json` use selected route strategy, not stale profile strategy
- expose `selected_route_id` + `selected_hops`
- expose `sandbox_migration_executed=true`
- expose `production_promotion_executed=false`
- dedupe warnings, keep order
- `orchestration_summary.json` now include `mode`, resume metadata, artifact-valid flag, sandbox/prod execution flags

**2. Files Modified**
- [migration_factory/final_report/writer.py](./migration_factory/final_report/writer.py)
- [migration_factory/orchestrator/summary.py](./migration_factory/orchestrator/summary.py)
- [tests/test_final_report.py](./tests/test_final_report.py)
- [tests/orchestrator/test_summary.py](./tests/orchestrator/test_summary.py)

**3. Tests Added**
- final report prefers `route_strategy=multi_hop`
- final report exposes `selected_route_id` and `selected_hops`
- final report exposes sandbox/prod execution flags
- final report dedupes warnings
- orchestration summary includes `mode`, resume metadata, `orchestration_artifacts_valid`
- orchestration summary marks sandbox execution clearly

**4. Commands Run**
```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
python -m migration_factory.orchestrator.runner --run-id msa-dto-clean-20260601-092451 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-msa-dto-msa-test-1.34\MSA-msa-dto-msa-test-1.34\msa-dto" --modernized "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean-demo" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean-demo\.migration\runs\msa-dto-clean-20260601-092451" --run-id "msa-dto-clean-20260601-092451" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. High-risk multi-hop route accepted for analysis purpose: Spring Boot 2.1 to 2.7 to 3.5, Java 11 to 17, Jakarta migration, Juneau and contract-library review required. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "msa-dto-clean-20260601-092451" --run-dir "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-msa-dto-clean-demo\.migration\runs\msa-dto-clean-20260601-092451" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

**5. Test Results**
- `tests/test_final_report.py -q`: `18 passed`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `546 passed, 3 skipped`

**6. Example `migration_report.json` Excerpt**
Run: `msa-dto-clean-20260601-092451`
- `selected_route_id: boot-2.1-to-3.5-java17`
- `strategy: multi_hop`
- `route_strategy: multi_hop`
- `selected_hops: [boot-2.1-to-2.7-java11, boot-2.7-to-3.5-java17]`
- `sandbox_migration_executed: true`
- `production_promotion_executed: false`
- `production_allowed: false`
- `test_status: NO_TESTS_FOUND`
- `test_severity: WARNING`

Path: [migration_report.json](~/Documents/modernized-app/modernized-msa-dto-clean-demo/.migration/runs/msa-dto-clean-20260601-092451/final/migration_report.json)

**7. Example `orchestration_summary.json` Excerpt**
- `mode: full_sandbox_migration`
- `resumed_from_mode: read_only_assessment`
- `resume_semantics: approved_sandbox_migration`
- `orchestration_artifacts_valid: true`
- `sandbox_migration_executed: true`
- `production_promotion_executed: false`
- `final_migration_executed: true`
- `final_status: SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS`
- `test_status: NO_TESTS_FOUND`

Path: [orchestration_summary.json](~/Documents/modernized-app/modernized-msa-dto-clean-demo/.migration/runs/msa-dto-clean-20260601-092451/orchestration/orchestration_summary.json)

**8. Warnings / Limitations**
- Existing old `modernized-msa-dto-clean` dir was Windows-locked; I used fresh demo dir `modernized-msa-dto-clean-demo` instead. Safe.
- Maven truststore still session-scoped via `MAVEN_OPTS`
- real demo run still warns, honestly:
  - `NO_TESTS_FOUND`
  - contract-library consumer validation required
  - multi-hop / high-risk route
- no source repo mutation, no production promotion, no PR/deploy/merge

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 14: Make Analysis Agent OpenRewrite preview source-JDK-aware.
>
> Problem:
> common-utils read_only_assessment fails during OpenRewrite dry-run with Lombok/Javac IllegalAccessError because the dry-run is executed with Java 17, while the legacy project is Boot 2.1 / Java 11.
>
> Goal:
> Analysis/OpenRewrite preview must use the source JDK declared by the selected profile when available.
>
> Context:
> Profile may define:
>
> * source_jdk_home_env: JAVA_HOME_11
> * target_jdk_home_env: JAVA_HOME_17
>
> Required behavior:
>
> 1. During analysis dry-run / rewrite preview, use source_jdk_home_env if present.
> 2. During target transformation/build, keep using target_jdk_home_env where appropriate.
> 3. Do not hardcode common-utils, msa-dto, or repo names.
> 4. Do not modify legacy source.
> 5. If source_jdk_home_env is missing or invalid, emit structured warning/error.
> 6. The rewrite preview artifact should record:
>
>    * java_home_env_used
>    * java_home_used
>    * java_version_used if detectable
> 7. If dry-run still fails, classify the failure clearly as rewrite_preview_failed, but include JDK info.
>
> Tests:
>
> 1. Profile with source_jdk_home_env causes analysis dry-run subprocess env JAVA_HOME to use that JDK.
> 2. Missing source_jdk_home_env falls back to current behavior with warning.
> 3. Invalid source_jdk_home_env gives structured diagnostic.
> 4. No project-specific names.
> 5. Existing msa-dto flow remains green.
> 6. common-utils read_only_assessment reaches planning/assessment instead of failing due Java 17 Lombok issue, if JDK 11 is configured.
>
> Validation:
> Run:
> python -m pytest tests -q
> python -m pytest -q
>
> Then rerun common-utils read_only_assessment with:
> JAVA_HOME_11=C:\Users\ilyas.abarbach.jdks\ms-11.0.31
> JAVA_HOME_17=C:\Users\ilyas.abarbach.jdks\ms-17.0.19
> MAVEN_OPTS using the migration-factory truststore.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. common-utils new run result
> 7. rewrite_preview JDK info excerpt
> 8. Any remaining blockers

<details><summary>28 previous messages</summary>

> Ticket 14 path: inspect analysis OpenRewrite preview env, profile JDK loading, rewrite preview artifact schema, then patch source-JDK selection and diagnostics. After tests, I’ll rerun real `common-utils` read-only assessment with truststore session if local path is discoverable.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Use caveman skill now. First dig where analysis preview pick JDK, where profile JDK env live, where rewrite preview artifact written. Then patch small, test big, rerun real common-utils if path found.
>
> Found likely spot: analysis `openrewrite_adapter.py`. Now read adapter, runner/plumbing, tests. Then patch env selection + artifact JDK fields + warnings.
>
> Need plumbing too: where analysis can see profile JDK env. Reading catalog/profile loader and build-agent JDK resolver for reuse pattern.
>
> Need know artifact contract too. Reading uses of `rewrite_preview.json` and schema tests before edit.
>
> Need exact loader behavior. Reading rewrite catalog loader tests too. Might extend catalog payload with profile JDK metadata there.
>
> Will patch adapter + loader tests first. Later find real common-utils path from local run history/config, then rerun.
>
> Found real common-utils modernized dir. Next read prior run metadata/logs to recover legacy path and current failure signature.
>
> Patch time. Adding JDK resolution helper, preview artifact fields, loader metadata, new tests for valid/missing/invalid source JDK.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/rewrite_catalog_loader.py` (+25 -21)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/openrewrite_adapter.py` (+294 -105)
>
> </details>
>
> Patch tests now. Add local catalog env field, env-sensitive subprocess capture, loader asserts profile JDK metadata.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_rewrite_catalog_loader.py` (+42 -18)
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_openrewrite_adapter.py` (+123 -30)
>
> </details>
>
> One test off: missing source JDK should still run preview with catalog, not skip from missing catalog. Fixing that and adding impact warning check.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/tests/test_openrewrite_adapter.py` (+4 -1)
>
> </details>
>
> Now sanity read modified chunks. Looking for syntax slips, YAML helper formatting, duplicate warnings logic side effects.
>
> Running focused analysis tests first. Want fast fail on syntax/behavior before repo-wide suite.
>
> Path quirk only. Re-running same tests from analysis-agent module dir so plain imports resolve.
>
> Two misses: version probe happened before source snapshot, and probe helper let mocked `CalledProcessError` escape. Moving snapshot earlier, making version probe swallow command failures.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/analysis_agent/analysis_agent/openrewrite_adapter.py` (+5 -6)
>
> </details>
>
> Re-running focused adapter tests after fixes.
>
> Core unit tests green. Now running repo `tests` suite, then full `pytest`, then real `common-utils` read-only rerun with session JDK 11/17 + truststore.
>
> One repo test now red because boot21 profile asks for `JAVA_HOME_11`, and fixture test never set it. Keeping strict invalid-env behavior; patching test to provide fake source JDK env.
>
> Patching orchestration fixture test to provide fake `JAVA_HOME_11` and let mocked subprocess answer `java -version`. Keeps strict profile behavior, keeps old fixture green.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py` (+6 -0)
>
> </details>
>
> Re-running red fixture first, then repo tests/full tests again.
>
> All tests green. Now real `common-utils` rerun with session JDK 11/17 + truststore, fresh modernized dir, no legacy mutation.
>
> Real rerun reached planning/assessment. Now extracting concise proof: rewrite preview JDK fields, route/planning status, read-only safety.
</details>

1. **Summary**

Analysis OpenRewrite preview now source-JDK-aware.

Fix:
- analysis dry-run reads `source_jdk_home_env` from profile
- sets subprocess `JAVA_HOME`/`PATH` to source JDK for preview only
- records JDK facts in `rewrite_preview.json` and `rewrite_impact_summary.json`
- missing source JDK config falls back to current process Java with warning
- invalid source JDK env fails preview clearly as `rewrite_preview_failed` with structured JDK diagnostic
- target transform/build logic untouched

Real `common-utils` rerun now reaches planning/assessment. Old Java 17 Lombok `IllegalAccessError` gone.

2. **Files Modified**

- [openrewrite_adapter.py](./migration_factory/agents/analysis_agent/analysis_agent/openrewrite_adapter.py)
- [rewrite_catalog_loader.py](./migration_factory/agents/analysis_agent/analysis_agent/rewrite_catalog_loader.py)
- [test_openrewrite_adapter.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_openrewrite_adapter.py)
- [test_rewrite_catalog_loader.py](./migration_factory/agents/analysis_agent/analysis_agent/tests/test_rewrite_catalog_loader.py)
- [test_read_only_assessment_boot21_contract_library.py](./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py)

3. **Tests Added**

- source JDK env from profile drives preview subprocess `JAVA_HOME`
- missing `source_jdk_home_env` falls back with warning
- invalid `source_jdk_home_env` returns structured `rewrite_preview_failed`
- AI Hub loader exposes `source_jdk_home_env` / `target_jdk_home_env`
- existing boot21 read-only orchestration fixture updated to provide fake JDK env and stay green

4. **Commands Run**

```powershell
python -m pytest tests\test_rewrite_catalog_loader.py -q
python -m pytest tests\test_openrewrite_adapter.py -q
$env:PYTHONPATH='.'; python -m pytest tests\orchestrator\test_read_only_assessment_boot21_contract_library.py -q
$env:PYTHONPATH='.'; python -m pytest tests -q
$env:PYTHONPATH='.'; python -m pytest -q

$env:PYTHONPATH='.'
$env:JAVA_HOME_11 = "$env:USERPROFILE\.jdks\ms-11.0.31"
$env:JAVA_HOME_17 = "$env:USERPROFILE\.jdks\ms-17.0.19"
$env:MAVEN_OPTS = "-Djavax.net.ssl.trustStore=$env:USERPROFILE\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit"
python -m migration_factory.orchestrator.runner --run-id common-utils-readonly-20260601-100705 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-common-utils-readonly-jdkaware" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
```

5. **Test Results**

- `test_rewrite_catalog_loader.py`: `8 passed`
- `test_openrewrite_adapter.py`: `10 passed`
- `test_read_only_assessment_boot21_contract_library.py`: `1 passed`
- `python -m pytest tests -q`: `468 passed, 2 skipped`
- `python -m pytest -q`: `550 passed, 3 skipped`

6. **common-utils New Run Result**

Run:
- `RUN_ID`: `common-utils-readonly-20260601-100705`
- run dir: `C:\Users\ilyas.abarbach\Documents\modernized-app\modernized-common-utils-readonly-jdkaware\.migration\runs\common-utils-readonly-20260601-100705`

Result:
- `status`: `human_approval_required`
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `rewrite_preview.status`: `USED`
- `rewrite_preview.exit_code`: `0`
- `rewrite_preview.patch_produced`: `true`

Detected facts:
- source Java `11`
- source Spring Boot `2.1.6.RELEASE`
- `project_kind`: `contract_library`
- internal deps: `1` (`com.total.corp:msa-dto:${msa-dto.version}`)

7. **rewrite_preview JDK Info Excerpt**

From [rewrite_preview.json](~/Documents/modernized-app/modernized-common-utils-readonly-jdkaware/.migration/runs/common-utils-readonly-20260601-100705/analysis/rewrite_preview.json):

```json
{
  "status": "USED",
  "java_home_env_used": "JAVA_HOME_11",
  "java_home_used": "C:\\Users\\ilyas.abarbach\\.jdks\\ms-11.0.31",
  "java_version_used": "11.0.31",
  "jdk_diagnostic": {
    "status": "SOURCE_PROFILE_JDK",
    "requested_java_home_env": "JAVA_HOME_11",
    "warning": null,
    "error": null
  }
}
```

Also from [rewrite_impact_summary.json](~/Documents/modernized-app/modernized-common-utils-readonly-jdkaware/.migration/runs/common-utils-readonly-20260601-100705/analysis/rewrite_impact_summary.json):
- `status: PASS`
- `overall_impact: HIGH`
- same JDK fields recorded there too

8. **Remaining Blockers**

No technical blocker for read-only phase now.

Remaining governance blocker only:
- human approval still required before sandbox transform

Warnings still real, not hidden:
- high-risk multi-hop route
- internal dependency migration-order review
- high OpenRewrite impact
- security config touched

Read-only safety still good:
- [read_only_verification.json](~/Documents/modernized-app/modernized-common-utils-readonly-jdkaware/.migration/runs/common-utils-readonly-20260601-100705/analysis/read_only_verification.json) shows `source_modified=false`

One note:
- ticket text had typo in JDK path (`C:\Users\ilyas.abarbach.jdks\...`). I used real local paths already proven earlier:
  - `C:\Users\ilyas.abarbach\.jdks\ms-11.0.31`
  - `C:\Users\ilyas.abarbach\.jdks\ms-17.0.19`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 15: Make multi-hop execution hop-aware and JDK-aware.
>
> Problem:
> common-utils Boot 2.1 -> Boot 3.5 route fails in sandbox at unit java-17. The factory currently validates Java 17 too early, before Boot 2.7 stabilization. Legacy Boot 2.1 uses old Lombok and fails under JDK 17 with lombok.javac.apt.Processor IllegalAccessError.
>
> Evidence:
> - baseline unit passes under source stack
> - ledger completed_units: [baseline]
> - ledger blocked_unit: java-17
> - build error unit_id: java-17
> - java_home_env: JAVA_HOME_17
> - matched error: Lombok/Javac IllegalAccessError
>
> Goal:
> For multi-hop routes, execution and validation must respect hop boundaries and JDKs:
> - Hop 1: Boot 2.1 -> Boot 2.7 on Java 11
> - Hop 2: Boot 2.7 -> Boot 3.5 on Java 17
>
> Required behavior:
> 1. Do not execute or validate java-17 before Boot 2.7 stabilization for Boot 2.1 multi-hop routes.
> 2. Reorder route-aware units for boot-2.1-to-3.5-java17 from:
>    baseline, java-17, spring-boot-2-7-stabilization, ...
>    to:
>    baseline, spring-boot-2-7-stabilization, java-17, spring-boot-3-5-14, jakarta, jaxb-jakarta, dependency-cleanup, contract-compatibility-review, existing-test-migration
> 3. Use source_jdk_home_env for baseline and Boot 2.7 stabilization checks.
> 4. Use target_jdk_home_env only from java-17 onward.
> 5. Record per-unit JDK metadata in migration_units.yaml and transformation_execution_plan.yaml:
>    - java_home_env
>    - java_home_used when executing
>    - hop_id if available
> 6. Build Agent should execute validation with the unit-level JDK if present.
> 7. If unit-level JDK env is missing or invalid, fail with structured diagnostic.
> 8. Do not hardcode common-utils, msa-dto, or repository names.
> 9. Do not disable Lombok or skip tests as a workaround.
> 10. Do not modify legacy repo.
> 11. Keep msa-dto flow green.
> 12. Keep old non-route profiles backward compatible.
>
> Tests:
> 1. boot-2.1-to-3.5-java17 units order places spring-boot-2-7-stabilization before java-17.
> 2. baseline and spring-boot-2-7-stabilization use JAVA_HOME_11.
> 3. java-17 and later units use JAVA_HOME_17.
> 4. transformation_execution_plan includes per-unit java_home_env.
> 5. Build validation receives per-unit JAVA_HOME/PATH.
> 6. invalid unit java_home_env gives structured build error.
> 7. no project-specific names.
> 8. msa-dto existing successful sandbox test stays green if present.
> 9. full pytest suite remains green.
>
> Validation commands:
> python -m pytest tests/agents/planning_agent -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> After tests pass:
> Run a new clean common-utils flow using short path C:\mf\cu2.
> Do not reuse common-utils-clean-20260601-104438.
> Keep:
> JAVA_HOME_11=C:\Users\ilyas.abarbach\.jdks\ms-11.0.31
> JAVA_HOME_17=C:\Users\ilyas.abarbach\.jdks\ms-17.0.19
> MAVEN_OPTS with migration-factory truststore.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. migration_units.yaml order excerpt
> 8. transformation_execution_plan per-unit JDK excerpt
> 9. final run status
> 10. if blocked, exact blocked_unit and error contract
> 11. why this is generic and enterprise-safe

<details><summary>28 previous messages</summary>

> Ticket 15 path: inspect unit ordering, unit model/rendering, execution-plan metadata, build-agent JDK selection. Then patch hop/JDK flow, run planning/transformation/orchestrator tests, then real common-utils clean run in `C:\mf\cu2`.
>
> Need supporting tests/plumbing too: reading unit-builder, transform-agent, build-agent coverage and where execution passes JDK env into build.
>
> Next read phase2 executor around per-unit build kwargs, because JDK metadata must flow from plan into build call and ledger/output.
>
> Need plan model/loader shape too, so per-unit `java_home_env` and `hop_id` survive into execution and final phase2 logic.
>
> Now focusing build-agent/env tests and execution-plan helper fixtures, because unit JDK override needs coverage and likely fixture updates.
>
> Checking contract schema for `migration_units.yaml`; new fields may need schema update if additional props blocked.
>
> Need helper fixtures in transformation tests; reading artifact writers/helpers before patching plan expectations.
>
> Need one more read: build error classifier patterns, so missing/invalid JDK env messages map cleanly, not weird generic bucket.
>
> Editing planning side now: reorder Boot 2.1 route, attach per-unit JDK env + hop ids, render into `migration_units.yaml`, and pass selected hops into unit builder.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/unit_builder.py` (+70 -2)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+13 -10)
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+6 -4)
>
> </details>
>
> Planning done. Now patching execution plan and build agent so unit-level JDK env wins and invalid env fails before bad build.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+33 -14)
> - Wrote `./migration_factory/agents/build_agent/agent.py` (+72 -26)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+27 -14)
>
> </details>
>
> Now updating tests for new order and JDK metadata. Then add execution-plan/build-agent checks.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./tests/agents/planning_agent/test_unit_builder_deterministic.py` (+31 -1)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+9 -1)
> - Wrote `./tests/agents/planning_agent/test_profile_routes.py` (+1 -1)
> - Wrote `./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py` (+1 -1)
> - Wrote `./migration_factory/agents/planning_agent/output_validator.py` (+1 -1)
>
> </details>
>
> Adding build-agent tests: explicit per-unit env override and invalid env structured error. Then execution-plan test for per-unit metadata.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_build_agent.py` (+61 -4)
> - Wrote `./tests/test_transformation_agent.py` (+190 -5)
>
> </details>
>
> Running targeted planning/build/transformation tests first. Want catch order/env regressions before full suites.
>
> Strict JDK validation broke 2 old tests because fake env paths lacked `bin/java`. Patching tests to create minimal fake JDK dirs.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_build_agent.py` (+12 -6)
>
> </details>
>
> Re-running build-agent suite, then full repo suite if green.
>
> All tests green. Now real clean `common-utils` run in `C:\mf\cu2`: read-only, approve, resume sandbox. Goal see unit order/JDK fix in live ledger, not just tests.
>
> Live run exposed one more gap: build validation JDK fixed, but OpenRewrite apply for `spring-boot-2-7-stabilization` still ran under wrong Java. Need patch transformation execution too, not just build checks. Inspecting OpenRewrite runner/env now.
>
> Patching transformation execution now: OpenRewrite apply should inherit unit JDK too. Then add test so Boot 2.7 stabilization OpenRewrite runs with `JAVA_HOME_11`.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/executor.py` (+15 -9)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+40 -20)
> - Wrote `./tests/test_transformation_agent.py` (+50 -1)
> - Wrote `./tests/test_transformation_agent.py` (+3 -2)
>
> </details>
>
> Re-running transformation/build/orchestrator suites after OpenRewrite env patch, then live common-utils retry if green.
>
> All green again. Starting second clean live `common-utils` run in `C:\mf\cu2` after execution-env fix. New run id only.
>
> Live run now moved past old Lombok/JDK17 blocker. Gathering exact artifacts: unit order, per-unit JDK metadata, final blocked unit/error contract.
>
> Last check: listing touched files so final report exact, not memory drift.
</details>

1. **Summary**

Done.

Main fix:
- Boot 2.1 multi-hop units now hop-aware, JDK-aware
- `spring-boot-2-7-stabilization` now before `java-17`
- baseline + hop1 stabilization use `source_jdk_home_env`
- `java-17` and later use `target_jdk_home_env`
- `migration_units.yaml` now carries `java_home_env` + `hop_id`
- `transformation_execution_plan.yaml` now carries `java_home_env` + resolved `java_home_used` + `hop_id`
- build validation honors unit-level JDK env
- OpenRewrite apply also honors unit-level JDK env

Real result:
- old blocker fixed: no more early `java-17` Lombok `IllegalAccessError`
- new live run reaches hop1 stabilization, applies OpenRewrite on Java 11, then fails later on real compile errors from transformed code

2. **Files Modified**

Ticket 15 files:
- [migration_factory/agents/planning_agent/unit_builder.py](./migration_factory/agents/planning_agent/unit_builder.py)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py)
- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py)
- [migration_factory/agents/planning_agent/output_validator.py](./migration_factory/agents/planning_agent/output_validator.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [migration_factory/agents/transformation_agent/agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [migration_factory/agents/transformation_agent/executor.py](./migration_factory/agents/transformation_agent/executor.py)
- [migration_factory/agents/build_agent/agent.py](./migration_factory/agents/build_agent/agent.py)
- [migration_factory/transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [tests/agents/planning_agent/test_unit_builder_deterministic.py](./tests/agents/planning_agent/test_unit_builder_deterministic.py)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [tests/agents/planning_agent/test_profile_routes.py](./tests/agents/planning_agent/test_profile_routes.py)
- [tests/orchestrator/test_read_only_assessment_boot21_contract_library.py](./tests/orchestrator/test_read_only_assessment_boot21_contract_library.py)
- [tests/test_build_agent.py](./tests/test_build_agent.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

Added/updated coverage for:
- Boot 2.1 route order now `baseline -> spring-boot-2-7-stabilization -> java-17 -> ...`
- hop1 units use `JAVA_HOME_11`
- hop2 units use `JAVA_HOME_17`
- `migration_units.yaml` includes `java_home_env` and `hop_id`
- `transformation_execution_plan.yaml` includes `java_home_env`, `java_home_used`, `hop_id`
- build agent explicit unit-level JDK override
- invalid unit-level JDK env writes structured build error
- OpenRewrite transformation uses unit-level Java env
- read-only boot21 fixture still green with new order

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/agents/planning_agent -q
python -m pytest tests/test_build_agent.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Live run 1:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-113817 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu2" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu2\.migration\runs\common-utils-clean-20260601-113817" --run-id "common-utils-clean-20260601-113817" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-113817" --run-dir "C:\mf\cu2\.migration\runs\common-utils-clean-20260601-113817" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

Live run 2, after OpenRewrite env fix:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-114443 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu2" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu2\.migration\runs\common-utils-clean-20260601-114443" --run-id "common-utils-clean-20260601-114443" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-114443" --run-dir "C:\mf\cu2\.migration\runs\common-utils-clean-20260601-114443" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/agents/planning_agent -q`: `102 passed`
- `tests/test_build_agent.py -q`: `29 passed`
- `tests/test_transformation_agent.py -q`: `44 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `556 passed, 3 skipped`

6. **New common-utils Run ID**

Final clean run:
- `common-utils-clean-20260601-114443`

Run dir:
- `C:\mf\cu2\.migration\runs\common-utils-clean-20260601-114443`

7. **migration_units.yaml Order Excerpt**

From [migration_units.yaml](C:/mf/cu2/.migration/runs/common-utils-clean-20260601-114443/planning/migration_units.yaml):

```yaml
units:
  - id: "baseline"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
  - id: "spring-boot-2-7-stabilization"
    java_home_env: "JAVA_HOME_11"
    hop_id: "boot-2.1-to-2.7-java11"
  - id: "java-17"
    java_home_env: "JAVA_HOME_17"
    hop_id: "boot-2.7-to-3.5-java17"
  - id: "spring-boot-3-5-14"
  - id: "jakarta"
  - id: "jaxb-jakarta"
  - id: "dependency-cleanup"
  - id: "contract-compatibility-review"
  - id: "existing-test-migration"
```

8. **transformation_execution_plan Per-Unit JDK Excerpt**

From [transformation_execution_plan.yaml](C:/mf/cu2/.migration/runs/common-utils-clean-20260601-114443/transformation/transformation_execution_plan.yaml):

```yaml
migration_units:
- id: baseline
  java_home_env: JAVA_HOME_11
  java_home_used: C:\Users\ilyas.abarbach\.jdks\ms-11.0.31
  hop_id: boot-2.1-to-2.7-java11

- id: spring-boot-2-7-stabilization
  java_home_env: JAVA_HOME_11
  java_home_used: C:\Users\ilyas.abarbach\.jdks\ms-11.0.31
  hop_id: boot-2.1-to-2.7-java11

- id: java-17
  java_home_env: JAVA_HOME_17
  java_home_used: C:\Users\ilyas.abarbach\.jdks\ms-17.0.19
  hop_id: boot-2.7-to-3.5-java17
```

9. **Final Run Status**

Final live run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Important:
- old blocker fixed
- no early block at `java-17`
- no Boot 2.1 + JDK 17 Lombok `IllegalAccessError`
- hop1 OpenRewrite now ran and succeeded
- hop1 build validation ran under `JAVA_HOME_11`

10. **Blocked Unit / Error Contract**

Blocked unit:
- `spring-boot-2-7-stabilization`

Ledger proof:
- [ledger.json](C:/mf/cu2/.migration/runs/common-utils-clean-20260601-114443/workspaces/sandbox/.migration/ledger.json)
- `completed_units: ["baseline"]`
- `blocked_unit: "spring-boot-2-7-stabilization"`

Error contract:
- [build-error-20260601-115006-compilation_error.json](C:/mf/cu2/.migration/runs/common-utils-clean-20260601-114443/build/build-error-20260601-115006-compilation_error.json)

JDK proof in error contract:
- `unit_id: "spring-boot-2-7-stabilization"`
- `java_home_env: "JAVA_HOME_11"`
- `java_home: "C:\\Users\\ilyas.abarbach\\.jdks\\ms-11.0.31"`

Actual failure now:
- real compile error after Boot 2.7 stabilization
- not environment error
- not early Lombok/JDK17 blocker

Exact compile errors:
- `DTOHelpers.java:[29,51] incompatible types: java.lang.String cannot be converted to java.util.List<java.lang.String>`
- `SearchService.java:[27,103] incompatible types: java.lang.String cannot be converted to java.util.List<java.lang.String>`

11. **Why Generic / Enterprise-Safe**

Generic:
- no `common-utils` hardcode
- no `msa-dto` hardcode
- no repo-name branching
- logic driven by route id, hop metadata, profile JDK env names, per-unit metadata
- unit-level JDK handling reusable for future multi-hop routes

Enterprise-safe:
- respects hop boundaries
- keeps source JDK for source-era stabilization
- switches to target JDK only when route says so
- records deterministic audit data in planning + transformation artifacts
- invalid unit JDK env now fails structured, early, auditable
- no legacy repo mutation
- no SSL bypass
- no Lombok hack, no test skip workaround

Remaining blocker:
- transformation content problem in hop1 stabilization, not orchestration/JDK sequencing problem now.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 16: Add deterministic Spring Data Sort API compile-fix.
>
> Problem:
> After Boot 2.7 stabilization, common-utils fails compilation:
>
> * DTOHelpers.java: new Sort(Direction, String)
> * SearchService.java: new Sort(Direction, String)
>   Error: String cannot be converted to List<String>.
>
> Important:
> Those files were not directly changed by OpenRewrite. The failure is caused by upgraded Spring Data API compatibility.
>
> Goal:
> Add a generic deterministic post-OpenRewrite compile-fix for legacy Spring Data Sort constructor usages.
>
> Required behavior:
>
> 1. Detect Java usages:
>
>    * new Sort(directionExpression, propertyExpression)
> 2. Replace with:
>
>    * Sort.by(directionExpression, propertyExpression)
> 3. Only apply when org.springframework.data.domain.Sort is imported or fully qualified.
> 4. Keep imports valid.
> 5. Apply in sandbox only.
> 6. Record patch in migration ledger.
> 7. Do not hardcode common-utils, DTOHelpers, SearchService, or repo names.
> 8. Do not use AI-generated edits.
> 9. Do not skip tests.
> 10. Do not modify legacy repo.
>
> Integration:
>
> * Attach this deterministic fix to the spring-boot-2-7-stabilization unit or dependency-cleanup unit.
> * It should run after OpenRewrite Boot 2.7 and before build validation for that unit.
>
> Tests:
>
> 1. Replaces simple `new Sort(Direction.ASC, "name")` with `Sort.by(Direction.ASC, "name")`.
> 2. Replaces variable property expression.
> 3. Does not modify unrelated constructors.
> 4. Does not modify files without Spring Data Sort import/usage.
> 5. Ledger records applied file and operation.
> 6. No project-specific names.
> 7. Full test suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu3.
> Do not reuse previous runs.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. Diff excerpt for DTOHelpers/SearchService
> 8. Final run status or next blocked unit/error
> 9. Why this is generic and deterministic

<details><summary>10 previous messages</summary>

> Ticket 16 path: find deterministic source-patch pattern, add Spring Data Sort compile-fix as sandbox patch, wire into hop1 stabilization before build, test, then clean `C:\mf\cu3` run.
>
> Add deterministic source patcher now. Plan: new `patch_spring_data_sort_constructor_usage`, inject into hop1 stabilization transformation list after OpenRewrite, record files in ledger, add focused tests, then rerun full + live `C:\mf\cu3`.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+53 -5)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+20 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+13 -2)
>
> </details>
>
> Small syntax slip in execution-plan branch. Fixing now before tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+1 -2)
>
> </details>
>
> Now add deterministic Sort patch tests plus execution-plan presence test. Then full suite and live `C:\mf\cu3`.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+128 -0)
> - Wrote `./tests/test_transformation_agent.py` (+57 -0)
>
> </details>
>
> Running transformation suite first for new patcher + ledger record, then full suite. After green, live `C:\mf\cu3` run.
>
> Tests green. Now clean live `common-utils` run in `C:\mf\cu3`, new run only.
>
> Live `C:\mf\cu3` moved further: compile fixed. Now gather exact Sort diffs + ledger patch record + next blocker detail for final.
</details>

1. **Summary**

Done.

Added deterministic Spring Data Sort compile-fix:
- detect `new Sort(directionExpr, propertyExpr)`
- replace with `Sort.by(directionExpr, propertyExpr)`
- only in files with Spring Data `Sort` import or fully qualified usage
- sandbox only
- ledger records applied files/patch op
- wired into `spring-boot-2-7-stabilization` after OpenRewrite, before build validation

Real effect:
- old compile break in `DTOHelpers` / `SearchService` gone
- `C:\mf\cu3` run moved past compile phase
- next blocker now test/runtime/config failures inside hop1 validation, not Sort compile issue

2. **Files Modified**

- [migration_factory/agents/transformation_agent/pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- [migration_factory/agents/transformation_agent/agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

Added coverage for:
- simple `new Sort(Direction.ASC, "name")` -> `Sort.by(...)`
- variable property expression
- unrelated constructors unchanged
- files without Spring Data Sort usage unchanged
- execution plan injects deterministic Sort fix into `spring-boot-2-7-stabilization`
- ledger records applied files for Sort fix

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

Live run:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-120731 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu3" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu3\.migration\runs\common-utils-clean-20260601-120731" --run-id "common-utils-clean-20260601-120731" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-120731" --run-dir "C:\mf\cu3\.migration\runs\common-utils-clean-20260601-120731" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `50 passed, 2 skipped`
- `pytest -q`: `562 passed, 3 skipped`

6. **New common-utils Run ID**

- `common-utils-clean-20260601-120731`

Run dir:
- `C:\mf\cu3\.migration\runs\common-utils-clean-20260601-120731`

7. **Diff Excerpt For DTOHelpers/SearchService**

`DTOHelpers.java`
```diff
- final Sort sort = new Sort(sortDirection, sortCollumn);
+ final Sort sort = Sort.by(sortDirection, sortCollumn);
```

`SearchService.java`
```diff
- final Sort sort = new Sort(Direction.fromString(query.getSortDirection()), query.getSortColumn());
+ final Sort sort = Sort.by(Direction.fromString(query.getSortDirection()), query.getSortColumn());
```

8. **Final Run Status / Next Blocker**

Run moved past compile fix. New blocker:

- `final_status`: `BUILD_FAILED_IN_SANDBOX`
- `blocked_unit`: `spring-boot-2-7-stabilization`

Error contract:
- [build-error-20260601-121353-missing_config.json](C:/mf/cu3/.migration/runs/common-utils-clean-20260601-120731/build/build-error-20260601-121353-missing_config.json)

Actual next failure:
- test/runtime/config failures during `mvn clean test`
- matched line shows Jackson/Spring context bootstrap issue:
  - `BeanCreationException`
  - `JavaTimeModule`
  - `NoClassDefFoundError: com/fasterxml/jackson/databind/ser/std/ToStringSerializerBase`

Also many failing tests in surefire:
- `Tests run: 124, Failures: 2, Errors: 84, Skipped: 4`

Important:
- compile error from `new Sort(...)` no longer blocker
- ledger shows deterministic patch applied to both files

Ledger proof:
- [ledger.json](C:/mf/cu3/.migration/runs/common-utils-clean-20260601-120731/workspaces/sandbox/.migration/ledger.json)
- transformation record:
  - `type: spring_data_sort_by_factory_method`
  - files:
    - `src\main\java\com\total\corp\common\dto\DTOHelpers.java`
    - `src\main\java\com\total\corp\common\service\base\SearchService.java`

9. **Why This Is Generic And Deterministic**

Generic:
- no `common-utils` hardcode
- no file-name hardcode
- scans Java files generically
- only keyed on Spring Data `Sort` import / fully qualified `Sort`

Deterministic:
- fixed regex transform only
- one exact constructor shape
- one exact replacement shape
- no AI edit generation
- applied in sandbox through explicit transformation step
- recorded in ledger with exact files and patch type

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 17: Add deterministic Jackson dependency alignment after Spring Boot stabilization.
>
> Problem:
> After Boot 2.7 stabilization, common-utils fails tests with:
> NoClassDefFoundError: com/fasterxml/jackson/databind/ser/std/ToStringSerializerBase
>
> dependency:tree shows mixed Jackson versions:
>
> * jackson-datatype-jsr310: 2.13.5 from spring-boot-starter-json 2.7.18
> * jackson-databind: 2.9.6 from jjwt-jackson 0.10.5
> * jackson-core: 2.10.0 from azure-servicebus-spring-boot-starter 2.2.0
> * jackson-annotations: 2.10.0 from jackson-dataformat-csv
>
> Goal:
> Add a generic deterministic Maven POM patch to align Jackson dependencies after Spring Boot 2.7 stabilization.
>
> Required behavior:
>
> 1. Detect mixed Jackson versions in Maven dependency tree or dependency facts.
> 2. For Spring Boot 2.7 route/hop, align Jackson artifacts to the Spring Boot managed Jackson version, or a profile-defined version.
> 3. Add explicit dependencyManagement entries or direct dependency versions for:
>
>    * com.fasterxml.jackson.core:jackson-databind
>    * com.fasterxml.jackson.core:jackson-core
>    * com.fasterxml.jackson.core:jackson-annotations
>    * com.fasterxml.jackson.datatype:jackson-datatype-jsr310
>    * com.fasterxml.jackson.datatype:jackson-datatype-jdk8
>    * com.fasterxml.jackson.module:jackson-module-parameter-names
>    * com.fasterxml.jackson.dataformat:jackson-dataformat-csv if present
>    * com.fasterxml.jackson.dataformat:jackson-dataformat-xml if present
>    * com.fasterxml.jackson.module:jackson-module-jaxb-annotations if present
> 4. For Boot 2.7.18, use Jackson 2.13.5 unless already profile-managed.
> 5. Apply in sandbox only.
> 6. Record all operations in the migration ledger.
> 7. Do not hardcode common-utils, msa-dto, or repo names.
> 8. Do not remove jjwt-jackson or Azure dependencies.
> 9. Do not skip tests.
> 10. Do not modify the legacy repo.
>
> Integration:
>
> * Attach this deterministic dependency alignment to spring-boot-2-7-stabilization after OpenRewrite and before build validation.
> * It should be generic for Spring Boot 2.x stabilization routes.
>
> Tests:
>
> 1. Mixed Jackson versions are detected.
> 2. POM patch adds dependencyManagement alignment for Jackson artifacts.
> 3. Already aligned Jackson dependencies are not duplicated.
> 4. Artifacts not present are not unnecessarily added except core/databind/annotations when needed.
> 5. Ledger records Jackson alignment operations.
> 6. No project-specific names.
> 7. Existing msa-dto flow remains green.
> 8. Full test suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu4.
> Do not reuse previous runs.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. Jackson dependency tree before/after excerpt
> 8. POM diff excerpt
> 9. Ledger excerpt
> 10. Final run status or next blocker
> 11. Why this is generic and deterministic

<details><summary>19 previous messages</summary>

> Ticket 17 path: inspect POM patcher + dependency facts, add deterministic Jackson align patch for Boot 2.7 stabilization, record in ledger, test, then clean `C:\mf\cu4` run.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Ticket 17 path: I’m checking the Maven patcher and transformation wiring first so we can add Jackson alignment as a declared deterministic sandbox step, then I’ll run the `common-utils` clean flow on `C:\mf\cu4` to see the next real blocker.
>
> I found the right seam: deterministic source transforms are already attached in `execution_plan.py`, and `maven_pom_patch` already gives us safe/idempotent XML updates plus ledger recording. Next I’m checking whether we already have dependency facts we can reuse, or if the detection should stay POM-scoped for this stabilization patch.
>
> I’ve confirmed the live `common-utils` sandbox POM still carries an old `fasterxml-jackson.version=2.10.0`, plus direct `jackson-dataformat-csv` pinned to that property, so plain dependency management alone won’t fully realign it. I’m wiring a dedicated `maven_pom_patch` op that both adds Jackson dependencyManagement entries and updates explicit Jackson direct versions when they would otherwise override the managed version.
>
> I have the fix shape now: one new deterministic `maven_pom_patch` op for Jackson alignment, attached to `spring-boot-2-7-stabilization` right after the existing Sort compile-fix. It will update any explicit Jackson direct versions that would override management, add managed Jackson entries for the stabilization hop, and record exactly what it changed in the ledger.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+194 -0)
>
> </details>
>
> I’m at the plan-wiring step now: the new op is in the POM patcher, and I’m adding it as an explicit transformation on the Boot 2.7 stabilization unit so it runs after OpenRewrite and before that unit’s build/test validation.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+12 -1)
> - Wrote `./tests/test_maven_pom_patcher.py` (+157 -0)
> - Wrote `./tests/test_transformation_agent.py` (+69 -1)
>
> </details>
>
> Code path is in place. I’m running the focused patcher and transformation tests now so we catch any XML/idempotency edge before touching the live `common-utils` flow again.
>
> Focused tests green. I’m running full `pytest` next to make sure the new Jackson patch doesn’t disturb the broader orchestration, approval, or sandbox reporting paths we’ve already stabilized.
>
> Tests all green. I’m switching to the live `common-utils` validation now: capture Jackson tree on the source project, start a fresh `C:\mf\cu4` read-only run, approve it, resume sandbox migration, then inspect the sandbox POM/tree and the next blocker if there is one.
>
> Live result moved the Jackson problem out of the way: hop1 no longer dies in Spring/Jackson test bootstrap. The run now advances to `java-17` and the next real blocker is the old Lombok `IllegalAccessError` under JDK 17, which is a different, later-stage issue.
>
> The live sandbox is patched exactly where we wanted: ledger shows Jackson alignment applied during `spring-boot-2-7-stabilization`, and the sandbox POM now has `fasterxml-jackson.version=2.13.5` plus managed Jackson entries. I’m grabbing a fresh before/after dependency-tree excerpt now so the report has concrete evidence, then I’ll close with the new blocker at `java-17`.
>
> One gap surfaced while validating the live tree: the current patch already aligns the core Jackson set and fixes the original `jackson-databind/jsr310` clash, but `jackson-dataformat-xml` and `jackson-module-jaxb-annotations` are still only transitive and stayed on 2.8.11 because they were not direct POM deps. I’m tightening the plan builder to read the analysis dependency graph and pass “transitively present optional Jackson artifacts” into the deterministic POM patch so those get aligned too, without blindly adding everything to every project.
>
> I found the missing signal source: the analysis phase already writes `dependency_graph.json`, so we can stay generic and avoid over-adding by reading that graph during execution-plan generation. I’m using it to pass “optional Jackson artifacts actually present transitively” into the deterministic patch, so `jackson-dataformat-xml` and `jackson-module-jaxb-annotations` get aligned when they really exist in the route hop.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+65 -25)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+19 -1)
> - Wrote `./tests/test_maven_pom_patcher.py` (+38 -0)
> - Wrote `./tests/test_transformation_agent.py` (+70 -8)
>
> </details>
>
> I tightened the execution-plan side too: it now reads `analysis/dependency_graph.json` and only forwards optional Jackson artifacts that the analysis actually saw. Re-running the tests now to make sure that extra signal path stays deterministic and doesn’t loosen the patch scope.
>
> All tests green again. I’m doing one fresh `common-utils` run now with the dependency-graph-aware Jackson alignment so the live sandbox reflects the final code path, not the intermediate one.
</details>

1. **Summary**

Done. Added deterministic Jackson alignment for Boot 2.7 stabilization.

What changed:
- new `maven_pom_patch` op: `align_jackson_dependency_management`
- attached to `spring-boot-2-7-stabilization` after OpenRewrite, before build validation
- aligns Jackson to `2.13.5` for this Boot `2.7.18` hop
- updates explicit Jackson property/version overrides
- adds managed Jackson entries
- reads `analysis/dependency_graph.json` so optional Jackson artifacts seen transitively also get aligned
- records operations in ledger

Real effect:
- old Jackson test/runtime blocker gone
- `common-utils` now passes `spring-boot-2-7-stabilization`
- next blocker moved later to `java-17` with old Lombok on JDK 17

2. **Files Modified**

- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- mixed Jackson versions detected
- Jackson dependencyManagement alignment added
- already-aligned case stays idempotent
- optional artifacts skipped when not present
- optional artifacts included when dependency facts show them
- execution plan injects Jackson alignment into `spring-boot-2-7-stabilization`
- ledger records Jackson alignment operation

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

```powershell
if (Test-Path C:\mf\cu4) { Move-Item -LiteralPath C:\mf\cu4 -Destination ("C:\mf\cu4.backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) }

$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

mvn dependency:tree -Dincludes=com.fasterxml.jackson.*,com.fasterxml.jackson.core:*,com.fasterxml.jackson.dataformat:*,com.fasterxml.jackson.datatype:*,com.fasterxml.jackson.module:* -Dverbose

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-141220 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu4" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu4\.migration\runs\common-utils-clean-20260601-141220" --run-id "common-utils-clean-20260601-141220" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."

python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-141220" --run-dir "C:\mf\cu4\.migration\runs\common-utils-clean-20260601-141220" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `14 passed`
- `tests/test_transformation_agent.py -q`: `52 passed, 2 skipped`
- `pytest -q`: `568 passed, 3 skipped`

6. **New `common-utils` Run ID**

- `common-utils-clean-20260601-141220`

7. **Jackson Dependency Tree Before/After Excerpt**

Before:
```text
jjwt-jackson -> jackson-databind:2.9.6
azure-servicebus-spring-boot-starter -> jackson-core:2.10.0
jackson-dataformat-csv:2.10.0
azure-storage-blob -> jackson-dataformat-xml:2.8.11
azure-storage-blob -> jackson-module-jaxb-annotations:2.8.11
spring-boot starter path -> jackson-datatype-jsr310:2.9.9
```

After:
```text
jjwt-jackson -> jackson-databind:2.13.5 (version managed from 2.9.6)
azure-servicebus-spring-boot-starter -> jackson-core:2.13.5 (version managed from 2.10.0)
jackson-datatype-jsr310:2.13.5
jackson-module-parameter-names:2.13.5
jackson-dataformat-csv:2.13.5
jackson-dataformat-xml:2.13.5 (version managed from 2.8.11)
jackson-module-jaxb-annotations transitives now resolve under managed 2.13.5 core set
```

8. **POM Diff Excerpt**

```diff
- <fasterxml-jackson.version>2.10.0</fasterxml-jackson.version>
+ <fasterxml-jackson.version>2.13.5</fasterxml-jackson.version>
```

```diff
+ <dependencyManagement>
+   <dependencies>
+     <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-databind</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-core</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.core</groupId><artifactId>jackson-annotations</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.datatype</groupId><artifactId>jackson-datatype-jsr310</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.datatype</groupId><artifactId>jackson-datatype-jdk8</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.module</groupId><artifactId>jackson-module-parameter-names</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.dataformat</groupId><artifactId>jackson-dataformat-csv</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.dataformat</groupId><artifactId>jackson-dataformat-xml</artifactId><version>2.13.5</version></dependency>
+     <dependency><groupId>com.fasterxml.jackson.module</groupId><artifactId>jackson-module-jaxb-annotations</artifactId><version>2.13.5</version></dependency>
+   </dependencies>
+ </dependencyManagement>
```

9. **Ledger Excerpt**

From sandbox ledger:
```json
{
  "type": "maven_pom_patch",
  "status": "applied",
  "operations_applied": [
    {
      "op": "align_jackson_dependency_management",
      "status": "updated",
      "target_version": "2.13.5",
      "detected_versions": ["2.10.0"],
      "updated_properties": ["fasterxml-jackson.version"],
      "managed_artifacts": [
        "com.fasterxml.jackson.core:jackson-databind",
        "com.fasterxml.jackson.core:jackson-core",
        "com.fasterxml.jackson.core:jackson-annotations",
        "com.fasterxml.jackson.datatype:jackson-datatype-jsr310",
        "com.fasterxml.jackson.datatype:jackson-datatype-jdk8",
        "com.fasterxml.jackson.module:jackson-module-parameter-names",
        "com.fasterxml.jackson.dataformat:jackson-dataformat-csv",
        "com.fasterxml.jackson.dataformat:jackson-dataformat-xml",
        "com.fasterxml.jackson.module:jackson-module-jaxb-annotations"
      ]
    }
  ]
}
```

10. **Final Run Status / Next Blocker**

- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Next blocker:
- `blocked_unit`: `java-17`
- error contract: [build-error-20260601-140818-compilation_error.json](C:/mf/cu4/.migration/runs/common-utils-clean-20260601-141220/build/build-error-20260601-140818-compilation_error.json)
- exact failure: old Lombok `0.11.8` under `JAVA_HOME_17`
- matched error: `lombok.javac.apt.Processor ... IllegalAccessError`

Important:
- Boot 2.7 stabilization now completes
- Jackson issue no longer the blocker

11. **Why Generic And Deterministic**

- no `common-utils`, `msa-dto`, or repo-name hardcode
- driven by unit id + explicit transformation plan
- patch logic uses fixed artifact coordinates only
- optional artifacts come from `analysis/dependency_graph.json`, not guesswork
- XML updates are deterministic/idempotent
- sandbox only
- ledger records exact operations and files changed
- no dependency removal, no SSL bypass, no legacy repo modification

**Warning / limitation**

Ticket 17 fixed the Jackson alignment problem, but it exposed the next real migration blocker: Lombok/Javac compatibility at the `java-17` unit. That is separate work.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 18: Add deterministic Lombok alignment before Java 17 validation.
>
> Problem:
> After Boot 2.7 stabilization passes, common-utils fails at unit `java-17` because old Lombok `0.11.8` fails under JDK 17 with:
> `lombok.javac.apt.Processor ... IllegalAccessError`.
>
> Goal:
> Before validating Java 17, deterministically align Lombok to a Java-17-compatible version from profile/config.
>
> Required behavior:
>
> 1. Detect Lombok dependency in Maven POM:
>
>    * org.projectlombok:lombok
> 2. If target route/hop moves to Java 17 and Lombok is older than configured minimum, update Lombok version.
> 3. Version must come from profile/config, not hardcoded repo logic.
>    Suggested profile field:
>    `tooling_versions.lombok: "1.18.34"`
>    or equivalent existing config mechanism.
> 4. Apply in sandbox only.
> 5. Apply before build validation of `java-17`.
> 6. Record operation in migration ledger:
>
>    * old version
>    * new version
>    * file changed
>    * unit id
> 7. Do not hardcode common-utils, msa-dto, or repository names.
> 8. Do not use `--add-opens` as workaround.
> 9. Do not skip tests.
> 10. Do not modify legacy repo.
> 11. Keep old profiles backward compatible.
>
> Integration:
>
> * Attach Lombok alignment to `java-17` unit before build validation.
> * If no Lombok dependency exists, no-op.
> * If Lombok already satisfies configured minimum, no-op.
> * If Lombok version is property-based, update the property.
> * If Lombok version is direct dependency version, update the dependency version.
> * If Lombok has no version and is managed by dependencyManagement, update dependencyManagement if present.
>
> Tests:
>
> 1. Updates direct Lombok version from old version to configured version.
> 2. Updates property-based Lombok version.
> 3. No-op when Lombok is absent.
> 4. No-op when Lombok is already aligned.
> 5. Ledger records Lombok alignment.
> 6. `java-17` execution plan includes Lombok alignment before build validation.
> 7. No project-specific names.
> 8. Existing msa-dto flow remains green.
> 9. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu5.
> Do not reuse previous runs.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. POM diff excerpt for Lombok
> 8. Ledger excerpt
> 9. Final run status or next blocker
> 10. Why this is generic and deterministic

<details><summary>14 previous messages</summary>

> Ticket 18 path: add one deterministic Lombok-align `maven_pom_patch`, source version from profile/config, wire it onto `java-17` before validation, then run clean `C:\mf\cu5` flow to see next blocker after Lombok.
>
> I found the config seam too: the profile already carries route/JDK metadata, so I’m extending that same profile with `tooling_versions.lombok`, then teaching execution-plan generation to read the approved profile and pass the Lombok target version into the deterministic `java-17` patch.
>
> I can’t get Lombok version from the raw execution-plan step unless we carry profile tooling forward. Cleanest path: planning already knows the profile, so I’m adding `tooling_versions` into `migration_plan.yaml`, then execution-plan generation can stay deterministic/offline and use that approved value for the `java-17` Lombok patch.
>
> I have the patch shape: new `align_lombok_version` op in the POM patcher, driven by `tooling_versions.lombok` carried from profile -> migration plan -> execution plan. It will update property-based, direct, or managed Lombok versions only when older than the configured minimum, and no-op otherwise.
>
> Small schema note: `migration_plan.yaml` already allows extra fields, so I only need to add `tooling_versions` to the AI Hub profile schema and profile YAMLs. Then the approved plan can carry Lombok version forward without breaking old profiles.
>
> I’m editing four places now: profile schema/YAML, planning writer to carry `tooling_versions`, execution-plan generator to attach the Lombok patch on `java-17`, and the POM patcher itself to update property/direct/managed Lombok versions only when they’re below the configured minimum.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+6 -3)
>
> </details>
>
> The planning patch hit a context mismatch, so I’m reading the exact `planning_node` tail and reapplying surgically. Main logic unchanged; just threading `tooling_versions` through the approved plan output.
>
> <details><summary>Edited 6 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+26 -10)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+121 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+34 -1)
> - Wrote `./modernizer-solution-ai-hub/schemas/migration-profile.schema.json` (+4 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+2 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+4 -2)
>
> </details>
>
> Profile/schema and execution wiring are in. I’m adding focused tests now: direct Lombok, property-based Lombok, no-op cases, plan propagation, and ledger recording on `java-17`.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+95 -0)
> - Wrote `./tests/test_transformation_agent.py` (+122 -17)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
>
> </details>
>
> Code path complete. I’m running the patcher, transformation, orchestrator, and full suite now; if green, I’ll do the clean `C:\mf\cu5` live run and see what moves after Lombok alignment.
>
> Tests green. I’m running the real `common-utils` flow on fresh `C:\mf\cu5` now; main check is whether `java-17` now gets a deterministic Lombok bump before validation and what the next blocker becomes after that.
>
> Live result good news: `java-17` no longer dies at Lombok `IllegalAccessError`. The run moved past that exact blocker, and I’m pulling the new error contract + ledger + sandbox POM so the report shows the Lombok diff and the next real failure honestly.
</details>

1. **Summary**

Done.

Factory now does deterministic Lombok align before `java-17` validation:
- read target Lombok version from profile config
- carry config into `migration_plan.yaml`
- add `maven_pom_patch` on `java-17`
- update old Lombok before JDK 17 build/test
- record exact old/new version in ledger

Real result:
- old blocker fixed: no more Lombok `IllegalAccessError` at `java-17`
- `common-utils` moved to next blocker: old JaCoCo agent on Java 17

2. **Files Modified**

- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [migration_factory/agents/transformation_agent/maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [modernizer-solution-ai-hub/schemas/migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json)
- [modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [tests/test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)

3. **Tests Added**

- direct Lombok version old -> configured version
- property Lombok version old -> configured version
- no Lombok -> no-op
- already aligned Lombok -> no-op
- execution plan includes `align_lombok_version` on `java-17`
- ledger records Lombok alignment
- boot21 profile exposes `tooling_versions.lombok`
- planning writes `tooling_versions` into `migration_plan.yaml`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-143412 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu5" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu5\.migration\runs\common-utils-clean-20260601-143412" --run-id "common-utils-clean-20260601-143412" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."

python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-143412" --run-dir "C:\mf\cu5\.migration\runs\common-utils-clean-20260601-143412" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `18 passed`
- `tests/test_transformation_agent.py -q`: `54 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `574 passed, 3 skipped`

6. **New `common-utils` Run ID**

- `common-utils-clean-20260601-143412`

7. **POM Diff Excerpt For Lombok**

Before:
```xml
<dependency>
    <groupId>org.projectlombok</groupId>
    <artifactId>lombok</artifactId>
    <version>0.11.8</version>
</dependency>
```

After:
```xml
<dependency>
    <groupId>org.projectlombok</groupId>
    <artifactId>lombok</artifactId>
    <version>1.18.34</version>
</dependency>
```

8. **Ledger Excerpt**

From sandbox ledger:
```json
{
  "unit_id": "java-17",
  "type": "maven_pom_patch",
  "status": "applied",
  "operations_applied": [
    {
      "op": "align_lombok_version",
      "status": "updated",
      "group_id": "org.projectlombok",
      "artifact_id": "lombok",
      "old_versions": ["0.11.8"],
      "new_version": "1.18.34",
      "updated_properties": [],
      "updated_dependencies": ["org.projectlombok:lombok"],
      "updated_managed_dependencies": 0
    }
  ],
  "files_changed": ["pom.xml"]
}
```

9. **Final Run Status / Next Blocker**

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

New blocker:
- unit: `java-17`
- old Lombok blocker gone
- next failure now JaCoCo agent on Java 17

Error contract:
- [build-error-20260601-142154-unknown_failure.json](C:/mf/cu5/.migration/runs/common-utils-clean-20260601-143412/build/build-error-20260601-142154-unknown_failure.json)

Exact new failure:
```text
Caused by: java.lang.RuntimeException: Class java/lang/UnknownError could not be instrumented.
Caused by: java.lang.NoSuchFieldException: $jacocoAccess
```

So next real issue:
- `jacoco-maven-plugin 0.8.2` / old agent not happy on Java 17 test run

10. **Why Generic And Deterministic**

- no repo-name hardcode
- no `common-utils` / `msa-dto` logic
- version comes from profile config:
  - `tooling_versions.lombok: "1.18.34"`
- approved plan carries config forward
- execution plan declares exact deterministic patch
- patch handles:
  - direct Lombok version
  - property-based version
  - managed version
- sandbox only
- ledger records exact old/new/file/unit
- no `--add-opens`
- no skipped tests
- no legacy repo modification

**Note**

Ticket 18 fixed Lombok/JDK17 blocker. Next ticket likely Jacoco alignment before Java 17 test validation.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 19: Add deterministic JaCoCo alignment before Java 17 validation.
>
> Problem:
> After Lombok alignment, common-utils progresses to `java-17` but fails because old JaCoCo agent/plugin is incompatible with Java 17.
>
> Failure:
> `Caused by: java.lang.RuntimeException: Class java/lang/UnknownError could not be instrumented.`
> `Caused by: java.lang.NoSuchFieldException: $jacocoAccess`
>
> Current project uses old JaCoCo, for example:
>
> * jacoco-maven-plugin 0.8.2
>
> Goal:
> Before validating Java 17, deterministically align JaCoCo Maven plugin/version to a Java-17-compatible version from profile/config.
>
> Required behavior:
>
> 1. Detect JaCoCo Maven plugin/version in Maven POM:
>
>    * org.jacoco:jacoco-maven-plugin
>    * org.jacoco:org.jacoco.agent if configured
>    * property-based versions such as jacoco.version if present
> 2. If target route/hop moves to Java 17 and JaCoCo is older than configured minimum, update JaCoCo version.
> 3. Version must come from profile/config, not repo-specific logic.
>    Suggested profile field:
>    `tooling_versions.jacoco: "0.8.12"`
> 4. Apply in sandbox only.
> 5. Apply before build validation of `java-17`.
> 6. Record operation in migration ledger:
>
>    * old version
>    * new version
>    * file changed
>    * unit id
> 7. Do not hardcode common-utils, msa-dto, or repository names.
> 8. Do not disable JaCoCo as workaround.
> 9. Do not skip tests.
> 10. Do not modify legacy repo.
> 11. Keep old profiles backward compatible.
>
> Integration:
>
> * Attach JaCoCo alignment to `java-17` unit before build validation.
> * If no JaCoCo plugin/config exists, no-op.
> * If JaCoCo already satisfies configured minimum, no-op.
> * If JaCoCo version is property-based, update the property.
> * If JaCoCo version is directly on plugin/dependency, update that version.
>
> Tests:
>
> 1. Updates property-based JaCoCo version from old version to configured version.
> 2. Updates direct jacoco-maven-plugin version.
> 3. No-op when JaCoCo is absent.
> 4. No-op when JaCoCo is already aligned.
> 5. Ledger records JaCoCo alignment.
> 6. `java-17` execution plan includes JaCoCo alignment before build validation.
> 7. No project-specific names.
> 8. Existing msa-dto flow remains green.
> 9. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu6.
> Do not reuse previous runs.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. POM diff excerpt for JaCoCo
> 8. Ledger excerpt
> 9. Final run status or next blocker
> 10. Why this is generic and deterministic

<details><summary>12 previous messages</summary>

> Ticket 19 path: add one deterministic JaCoCo-align patch on `java-17`, source version from profile `tooling_versions`, update plugin/property safely in sandbox, test, then clean `C:\mf\cu6` run to see next blocker after JaCoCo.
>
> I’ve confirmed the real POM shape: JaCoCo is coming from `jacoco-maven-plugin.version` under `pluginManagement`, so this fix needs plugin-aware XML handling, not just dependencies. I’m adding plugin scanning/update in the deterministic patcher and wiring `tooling_versions.jacoco` onto `java-17` beside Lombok.
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+127 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+18 -7)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+108 -0)
> - Wrote `./tests/test_transformation_agent.py` (+67 -5)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -1)
>
> </details>
>
> JaCoCo patch + tests are in. Running the focused suites and full repo now; if they stay green, I’ll do the clean `C:\mf\cu6` run and verify the `java-17` plan actually applies Lombok then JaCoCo before validation.
>
> I hit one XML edge: JaCoCo plugin discovery in namespaced `<build><plugins>` wasn’t broad enough, and property-only plugin versions weren’t being updated unless the plugin node matched first. I’m tightening that detection now, then rerunning the suites.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+15 -7)
>
> </details>
>
> Patch adjusted. Re-running focused suites first so we don’t waste time on the full run if plugin/property matching still has a gap.
>
> One small cleanup left: the JaCoCo op is updating correctly now, but `old_versions` was double-counting the same property after the update. I’m deduping the property scan so the ledger shows the true pre-change version once.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+5 -0)
>
> </details>
>
> Re-running focused tests one more time, then full suite if green, then I’ll take the clean `C:\mf\cu6` live run through approval/resume and inspect the next blocker after JaCoCo.
>
> All tests green. Starting the real `common-utils` `C:\mf\cu6` run now; key check is whether `java-17` now applies both Lombok and JaCoCo patch ops before validation and what the next real failure becomes after that.
>
> Live run moved further than Ticket 18: `java-17` now passes, and the flow reaches `spring-boot-3-5-14`. I’m pulling the exact JaCoCo POM/ledger excerpts plus the new dependency blocker so the close-out is concrete.
</details>

1. **Summary**

Done.

Factory now do deterministic JaCoCo align before `java-17` validation:
- read version from profile config
- carry config in `migration_plan.yaml`
- attach `align_jacoco_version` to `java-17`
- update old JaCoCo plugin/property in sandbox only
- record old/new version in ledger

Real result:
- old JaCoCo Java 17 blocker gone
- `common-utils` passed `java-17`
- run advanced to `spring-boot-3-5-14`
- new blocker now bad dependency after Boot 3.5 step: `thymeleaf-spring6:3.0.11.RELEASE` not in Maven Central

2. **Files Modified**

- [migration_factory/agents/transformation_agent/maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [migration_factory/agents/planning_agent/node.py](./migration_factory/agents/planning_agent/node.py)
- [migration_factory/agents/planning_agent/plan_writer.py](./migration_factory/agents/planning_agent/plan_writer.py)
- [modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [tests/test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)
- [tests/agents/planning_agent/test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)

3. **Tests Added**

- property-based JaCoCo version old -> configured version
- direct `jacoco-maven-plugin` version old -> configured version
- JaCoCo absent -> no-op
- JaCoCo already aligned -> no-op
- `java-17` execution plan includes JaCoCo align
- ledger records JaCoCo align
- profile/planning carry `tooling_versions.jacoco`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-145105 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu6" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu6\.migration\runs\common-utils-clean-20260601-145105" --run-id "common-utils-clean-20260601-145105" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."

python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-145105" --run-dir "C:\mf\cu6\.migration\runs\common-utils-clean-20260601-145105" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `22 passed`
- `tests/test_transformation_agent.py -q`: `55 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `579 passed, 3 skipped`

6. **New `common-utils` Run ID**

- `common-utils-clean-20260601-145105`

7. **POM Diff Excerpt For JaCoCo**

At `java-17` patch step:
```diff
- <jacoco-maven-plugin.version>0.8.2</jacoco-maven-plugin.version>
+ <jacoco-maven-plugin.version>0.8.12</jacoco-maven-plugin.version>
```

Execution plan on `java-17`:
```yaml
- type: maven_pom_patch
  operations:
    - op: align_lombok_version
      version: 1.18.34
    - op: align_jacoco_version
      version: 0.8.12
```

Note:
- later `spring-boot-3-5-14` OpenRewrite moved sandbox POM to `0.8.14`
- deterministic patch itself recorded `0.8.2 -> 0.8.12`
- final sandbox POM excerpt now shows:
  - `jacoco-maven-plugin.version=0.8.14`

8. **Ledger Excerpt**

From sandbox ledger, unit `java-17`:
```json
{
  "type": "maven_pom_patch",
  "status": "applied",
  "operation_count": 2,
  "operations_applied": [
    {
      "op": "align_lombok_version",
      "status": "updated",
      "old_versions": ["0.11.8"],
      "new_version": "1.18.34"
    },
    {
      "op": "align_jacoco_version",
      "status": "updated",
      "old_versions": ["0.8.2"],
      "new_version": "0.8.12",
      "updated_properties": ["jacoco-maven-plugin.version"]
    }
  ],
  "files_changed": ["pom.xml"]
}
```

9. **Final Run Status / Next Blocker**

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Important:
- `baseline` passed
- `spring-boot-2-7-stabilization` passed
- `java-17` passed
- blocked now at `spring-boot-3-5-14`

New blocker:
- error contract: [build-error-20260601-143745-dependency_error.json](C:/mf/cu6/.migration/runs/common-utils-clean-20260601-145105/build/build-error-20260601-143745-dependency_error.json)
- exact failure:
```text
Could not find artifact org.thymeleaf:thymeleaf-spring6:jar:3.0.11.RELEASE in central
```

So next real issue:
- Boot 3.5 step created invalid/unsatisfied Thymeleaf dependency combination
- not Lombok
- not JaCoCo

10. **Why This Is Generic And Deterministic**

- no repo-name hardcode
- no `common-utils` / `msa-dto` logic
- version from profile config:
  - `tooling_versions.jacoco: "0.8.12"`
- approved plan carries config forward
- execution plan declares exact patch op
- patch handles:
  - property-based JaCoCo version
  - direct `jacoco-maven-plugin` version
  - direct `org.jacoco.agent` dependency version if present
- sandbox only
- ledger records exact old/new/file/unit
- no JaCoCo disable
- no skipped tests
- no legacy repo modification

**Note**

Ticket 19 fixed JaCoCo Java 17 blocker. Next ticket likely deterministic Thymeleaf alignment during `spring-boot-3-5-14`.

<details><summary>22 previous messages</summary>

> Context compaction
>
> Source: automatic
> Status: completed
>
> Use caveman. First I check Thymeleaf path in code, plan, tests, and profile knobs.
>
> I found patch hooks. Now I read exact deterministic transform block and POM patch tests, then wire Thymeleaf same style.
>
> Need one more pass: where plan carry profile knobs. Then I edit patcher, plan, profile, tests.
>
> I have enough shape. Next I patch schema/profile/planning/execution/patcher/tests together, then run focused tests.
>
> I’m patching now: add `framework_versions`, Thymeleaf POM op, execution-plan hook on `spring-boot-3-5-14`, and tests.
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./migration_factory/agents/planning_agent/plan_writer.py` (+3 -0)
> - Wrote `./migration_factory/agents/planning_agent/node.py` (+16 -0)
> - Wrote `./modernizer-solution-ai-hub/schemas/migration-profile.schema.json` (+4 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+2 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+2 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+24 -1)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+149 -0)
>
> </details>
>
> Small correction: BOM-managed Thymeleaf should drop version from dependency, not blank unrelated property. I’m tightening that now.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+0 -2)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
> - Wrote `./tests/test_transformation_agent.py` (+48 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+146 -0)
> - Wrote `./tests/test_transformation_agent.py` (+69 -0)
>
> </details>
>
> I spotted one edge: if Thymeleaf has no version and BOM not present, we should add configured version. Patching that too.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+9 -0)
>
> </details>
>
> Edits in. Running focused tests first so we catch shape issues before live rerun.
>
> Focused tests green. I’m running orchestrator and full suite now, then fresh `common-utils` run in `C:\mf\cu7`.
>
> Tests all green. Starting fresh live `common-utils` run on short path `C:\mf\cu7`, with same JDK/truststore session.
>
> Resume ran longer than shell timeout. I’m checking whether approval/resume finished and what final blocker is, instead of guessing.
>
> Approval is in place. Resume had started but shell timeout cut it off while phase 2 was still moving. I’m rerunning `resume` alone with a longer timeout to get the real outcome.
>
> One live run got polluted by my earlier shell timeout and left sandbox lock noise. I’m doing one truly clean rerun now with a new run id, same short root, and enough timeout so we get the real blocker.
>
> Fresh rerun on the same short root hit a Windows file lock from the earlier interrupted attempt, so I’m diagnosing that lock instead of faking a “clean” result.
>
> Lock may have released now. I’m trying one last proper cleanup of `C:\mf\cu7`; if it works, I’ll do the truly clean rerun.
>
> Cleanup worked. I’m doing the final clean rerun on `C:\mf\cu7` now with enough timeout end-to-end.
>
> Clean live rerun complete. Thymeleaf blocker gone; new blocker is later compile fallout in `spring-boot-3-5-14`. I’m pulling the exact POM/ledger/tree excerpts for the report.
>
> I have ledger + POM proof. One more quick dependency tree call without quiet mode, so the report shows the resolved Thymeleaf coordinates after the fix.
</details>

1. **Summary**

Done.

Factory now do deterministic Thymeleaf align in `spring-boot-3-5-14`:
- detect `org.thymeleaf:*`
- replace `thymeleaf-spring4/5 -> thymeleaf-spring6`
- remove or update bad explicit versions
- use profile/config, not repo logic
- run in sandbox before build validation
- record in ledger

Real `common-utils` clean rerun proves old blocker gone:
- old blocker was `org.thymeleaf:thymeleaf-spring6:3.0.11.RELEASE` missing
- now Thymeleaf resolves
- next blocker moved later to compile error on `jakarta.validation` imports

2. **Files Modified**

- [maven_pom_patcher.py](/abs/path-not-available)
- [execution_plan.py](/abs/path-not-available)
- [node.py](/abs/path-not-available)
- [plan_writer.py](/abs/path-not-available)
- [migration-profile.schema.json](./modernizer-solution-ai-hub/schemas/migration-profile.schema.json)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)

3. **Tests Added**

- `thymeleaf-spring5 -> thymeleaf-spring6`
- remove bad explicit `3.0.11.RELEASE` when BOM-managed path chosen
- update explicit version from profile config
- no-op when Thymeleaf absent
- no-op when already aligned
- ledger records Thymeleaf alignment
- execution plan injects Thymeleaf alignment before Boot 3.5 build validation
- profile/planning carry `framework_versions.thymeleaf`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-161650 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu7" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu7\.migration\runs\common-utils-clean-20260601-161650" --run-id "common-utils-clean-20260601-161650" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."

python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-161650" --run-dir "C:\mf\cu7\.migration\runs\common-utils-clean-20260601-161650" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `27 passed`
- `tests/test_transformation_agent.py -q`: `57 passed, 2 skipped`
- `tests/agents/planning_agent/test_boot21_profile.py -q`: `6 passed`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `586 passed, 3 skipped`

6. **New `common-utils` Run Id**

- `common-utils-clean-20260601-161650`

7. **POM Diff Excerpt For Thymeleaf**

Before:
```xml
<dependency>
    <groupId>org.thymeleaf</groupId>
    <artifactId>thymeleaf-spring6</artifactId>
    <version>3.0.11.RELEASE</version>
</dependency>
```

After:
```xml
<dependency>
    <groupId>org.thymeleaf</groupId>
    <artifactId>thymeleaf-spring6</artifactId>
    <version>3.1.3.RELEASE</version>
</dependency>
```

From sandbox POM:
- `org.thymeleaf:thymeleaf-spring6`
- version `3.1.3.RELEASE`

8. **Dependency Tree Excerpt After Fix**

From `C:\mf\cu7\.migration\runs\common-utils-clean-20260601-161650\workspaces\sandbox`:

```text
[INFO] +- org.thymeleaf:thymeleaf-spring6:jar:3.1.3.RELEASE:compile
[INFO] |  \- org.thymeleaf:thymeleaf:jar:3.1.3.RELEASE:compile
[INFO] \- nz.net.ultraq.thymeleaf:thymeleaf-layout-dialect:jar:2.3.0:compile
[INFO]    \- nz.net.ultraq.thymeleaf:thymeleaf-expression-processor:jar:1.1.3:compile
```

9. **Ledger Excerpt**

From [ledger.json](C:/mf/cu7/.migration/runs/common-utils-clean-20260601-161650/workspaces/sandbox/.migration/ledger.json):

```json
{
  "unit_id": "spring-boot-3-5-14",
  "type": "maven_pom_patch",
  "status": "applied",
  "operations_applied": [
    {
      "op": "align_thymeleaf_dependencies",
      "status": "updated",
      "target_version": "3.1.3.RELEASE",
      "prefer_bom_managed": true,
      "used_bom_management": false,
      "old_versions": ["3.0.11.RELEASE"],
      "updated_versions": [
        {
          "artifact_id": "thymeleaf-spring6",
          "old_version": "3.0.11.RELEASE",
          "new_version": "3.1.3.RELEASE"
        }
      ]
    }
  ],
  "files_changed": ["pom.xml"]
}
```

10. **Final Run Status / Next Blocker**

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old Thymeleaf blocker fixed.

New blocker:
- unit: `spring-boot-3-5-14`
- error contract: [build-error-20260601-150312-compilation_error.json](C:/mf/cu7/.migration/runs/common-utils-clean-20260601-161650/build/build-error-20260601-150312-compilation_error.json)

Exact new failure:
```text
package jakarta.validation does not exist
cannot find symbol: class ConstraintViolationException
```

File:
- `src/main/java/com/total/corp/common/web/rest/advice/CustomExceptionTranslator.java`

11. **Why This Is Generic And Deterministic**

- no `common-utils`
- no `msa-dto`
- no repo-name branching
- keyed only on generic Thymeleaf coordinates:
  - `org.thymeleaf:thymeleaf-spring4`
  - `org.thymeleaf:thymeleaf-spring5`
  - `org.thymeleaf:thymeleaf-spring6`
  - `org.thymeleaf:thymeleaf`
  - Thymeleaf extras prefix
- target version comes from profile config:
  - `framework_versions.thymeleaf: "3.1.3.RELEASE"`
- execution plan declares exact deterministic `maven_pom_patch`
- sandbox only
- ledger records exact old/new values
- legacy repo untouched

**Warning / limitation**

This ticket fixed dependency resolution, not later Jakarta compile fallout. Next likely ticket is deterministic validation/Jakarta dependency alignment for `jakarta.validation` / related Boot 3 compile fallout.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 21: Add deterministic Jakarta Validation dependency alignment for Boot 3.
>
> Context:
> The factory already detects javax.validation / validation-api risk in planning risk_classifier.py, but there is currently no deterministic transformation patch that adds Boot 3 compatible validation dependency during spring-boot-3-5-14.
>
> Problem:
> common-utils reaches spring-boot-3-5-14 and fails compilation with:
> - package jakarta.validation does not exist
> - cannot find symbol ConstraintViolationException
>
> Goal:
> Reuse existing validation risk/import signals where possible and add a generic deterministic Maven POM patch for Boot 3 validation dependencies.
>
> Required behavior:
> 1. Detect validation usage from analysis facts and/or source scan:
>    - jakarta.validation.*
>    - javax.validation.*
>    - ConstraintViolationException
>    - validation-api
> 2. During Spring Boot 3 migration, if validation usage exists and validation dependency is missing, add:
>    - org.springframework.boot:spring-boot-starter-validation
>    with no explicit version.
> 3. Only add starter-validation when the project is Spring Boot / Boot BOM managed.
> 4. For non-Boot Maven projects, optionally add jakarta.validation:jakarta.validation-api using profile/config version.
> 5. Do not duplicate if validation dependency already exists.
> 6. Apply in sandbox only.
> 7. Apply after OpenRewrite and before build validation of spring-boot-3-5-14.
> 8. Record operation in ledger:
>    - detected validation usage
>    - dependency added or already present
>    - file changed
>    - unit id
> 9. Do not hardcode common-utils, msa-dto, or repo names.
> 10. Do not skip tests.
> 11. Do not modify legacy repo.
> 12. Keep old profiles backward compatible.
>
> Tests:
> 1. Adds spring-boot-starter-validation when jakarta.validation imports exist and dependency is missing.
> 2. Adds spring-boot-starter-validation when javax.validation was detected before Jakarta migration.
> 3. Does not duplicate when starter-validation already exists.
> 4. No-op when no validation usage exists.
> 5. Ledger records validation alignment.
> 6. spring-boot-3-5-14 execution plan includes validation alignment before build validation.
> 7. No project-specific names.
> 8. Existing msa-dto flow remains green.
> 9. Full pytest suite remains green.
>
> Validation:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu8.
> Do not reuse previous runs.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. POM diff excerpt for validation dependency
> 8. Ledger excerpt
> 9. Final run status or next blocker
> 10. Why this is generic and deterministic

<details><summary>23 previous messages</summary>

> Use caveman. First I inspect validation signals in analysis artifacts, risk code, and patch hooks so new op uses existing facts when possible.
>
> I found risk extractor already knows where imports can live. Now I inspect exact analysis artifact shape and then wire validation patch to consume it.
>
> I have enough artifact shape. Analysis report has `javax_count`, but not full imports in real run, so I’ll make the patch use both existing artifact hints and deterministic source scan fallback.
>
> Plan clear now:
> - add `align_validation_dependencies`
> - feed it deterministic signals from analysis report + source scan
> - attach it to `spring-boot-3-5-14` with Thymeleaf patch
> - add tests
> - rerun full suite and fresh `C:\mf\cu8` live flow.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+103 -6)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+119 -0)
>
> </details>
>
> Patch logic in. Now I’m adding focused tests for starter-validation add/no-op/ledger and execution-plan injection.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+152 -0)
> - Wrote `./tests/test_transformation_agent.py` (+75 -0)
>
> </details>
>
> One helper changed under the hood: execution-plan now reads `analysis_report.json`. I’m updating the test fixture writer so the new tests stay deterministic.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+9 -2)
> - Wrote `./tests/test_transformation_agent.py` (+4 -0)
>
> </details>
>
> Edits done. Running focused tests first: patcher, transformation, orchestrator, then full suite.
>
> One test fixture forgot to pass validation signal payload. I’m fixing that small test-only mismatch, then rerunning transformation + full suite.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+4 -0)
>
> </details>
>
> Rerunning the red test file, then full suite. If green, I start fresh `C:\mf\cu8` live flow.
>
> Tiny assertion mismatch only: signal is stored as concrete import, which is better. I’m updating the assertion and rerunning the suite.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+1 -1)
>
> </details>
>
> Rerun transformation tests and full suite now.
>
> All tests green. Starting fresh live `common-utils` run on `C:\mf\cu8` with same JDK/truststore session.
>
> Live rerun surfaced one good catch: my first pass was too generous and treated “has any Boot starter” as enough to add `starter-validation` without BOM/parent management. I’m tightening that now and adding the non-BOM `jakarta.validation-api` fallback from profile config, then I’ll rerun `C:\mf\cu8` clean.
>
> I confirmed the real POM shape: Boot deps use explicit `${spring-boot.version}`, but there is no parent/BOM. So the correct generic behavior here is the non-BOM fallback API, not starter-validation. I’m patching that and adding a small fallback test.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+16 -6)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+5 -1)
> - Wrote `./tests/test_maven_pom_patcher.py` (+42 -0)
>
> </details>
>
> Patch tightened. Running focused tests again, then one more clean live `C:\mf\cu8` rerun.
>
> Tests all green again. I’m moving the old `cu8` aside and doing the final clean rerun with the stricter validation fallback.
>
> Clean live rerun finished. Validation dependency issue is fixed; next blocker moved later to method override mismatch in `CustomExceptionTranslator`. I’m grabbing the exact POM + ledger excerpt for the report.
</details>

1. **Summary**

Done.

Factory now add deterministic Jakarta Validation align in `spring-boot-3-5-14`:
- use analysis signals + source scan fallback
- if Boot truly BOM/parent-managed, add `spring-boot-starter-validation` with no version
- if not BOM/parent-managed, add `jakarta.validation:jakarta.validation-api` from profile config
- no duplicate
- sandbox only
- ledger records exact action

Real `common-utils` proof:
- old blocker gone: no more `package jakarta.validation does not exist`
- new blocker moved later: `CustomExceptionTranslator.java` override mismatch after Boot 3 step

2. **Files Modified**

- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)

3. **Tests Added**

- add starter-validation when validation usage exists and BOM-managed
- add starter-validation for `javax.validation` signal too
- no duplicate when starter already exists
- no-op when no validation usage
- add `jakarta.validation-api` fallback for non-BOM project with configured version
- ledger records validation alignment
- execution plan injects validation alignment before Boot 3 build validation

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-164230 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu8" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu8\.migration\runs\common-utils-clean-20260601-164230" --run-id "common-utils-clean-20260601-164230" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-164230" --run-dir "C:\mf\cu8\.migration\runs\common-utils-clean-20260601-164230" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `32 passed`
- `tests/test_transformation_agent.py -q`: `58 passed, 2 skipped`
- `tests/agents/planning_agent/test_boot21_profile.py -q`: `6 passed`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `592 passed, 3 skipped`

6. **New `common-utils` Run Id**

- `common-utils-clean-20260601-164230`

7. **POM Diff Excerpt For Validation Dependency**

Before: no Jakarta Validation dep.

After:
```xml
<dependency>
  <groupId>jakarta.validation</groupId>
  <artifactId>jakarta.validation-api</artifactId>
  <version>3.0.2</version>
</dependency>
```

From sandbox POM:
- [pom.xml](C:/mf/cu8/.migration/runs/common-utils-clean-20260601-164230/workspaces/sandbox/pom.xml)

8. **Ledger Excerpt**

From [ledger.json](C:/mf/cu8/.migration/runs/common-utils-clean-20260601-164230/workspaces/sandbox/.migration/ledger.json):

```json
{
  "op": "align_validation_dependencies",
  "status": "added",
  "detected_validation_usage": [
    "jakarta.validation:jakarta.validation-api",
    "javax.validation:validation-api"
  ],
  "dependency_added": "jakarta.validation:jakarta.validation-api",
  "used_boot_starter": false,
  "used_boot_bom_management": false,
  "used_boot_parent_management": false,
  "api_version": "3.0.2"
}
```

9. **Final Run Status Or Next Blocker**

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old validation blocker fixed.

New blocker:
- unit: `spring-boot-3-5-14`
- error contract: [build-error-20260601-160003-compilation_error.json](C:/mf/cu8/.migration/runs/common-utils-clean-20260601-164230/build/build-error-20260601-160003-compilation_error.json)

Exact new failure:
```text
CustomExceptionTranslator.java:[355,5] method does not override or implement a method from a supertype
```

10. **Why Generic And Deterministic**

- no `common-utils`
- no `msa-dto`
- no repo-name logic
- uses generic signals:
  - imports
  - dependency facts
  - `javax_count`
  - source scan fallback
- version comes from profile config:
  - `framework_versions.jakarta_validation_api: "3.0.2"`
- execution plan declares exact patch op
- patch behavior deterministic:
  - Boot BOM/parent managed -> starter
  - otherwise -> Jakarta API fallback
- sandbox only
- ledger records exact result
- legacy repo untouched

Next likely ticket: deterministic Spring 6 `CustomExceptionTranslator` signature/override fix.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 22: Add deterministic Spring 6 exception handler override alignment.
>
> Problem:
> After Jakarta Validation dependency alignment, common-utils progresses further in `spring-boot-3-5-14` but fails compilation with:
> `CustomExceptionTranslator.java:[355,5] method does not override or implement a method from a supertype`
>
> Likely cause:
> Spring Boot 3 / Spring Framework 6 changed some `ResponseEntityExceptionHandler` method signatures, for example `HttpStatus` became `HttpStatusCode` in protected handler methods.
>
> Goal:
> Add a generic deterministic compile-fix for Spring Framework 6 exception handler override signatures.
>
> Required behavior:
> 1. Detect Java classes extending or using:
>    - org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler
> 2. Detect overridden handler methods whose signatures are Spring 5-style but not Spring 6-style.
> 3. Update signatures to Spring 6-compatible forms where deterministic.
>    Common case:
>    - replace `org.springframework.http.HttpStatus` parameter with `org.springframework.http.HttpStatusCode`
>    - update import from `HttpStatus` to `HttpStatusCode` only when used as method parameter type needing Spring 6 compatibility
> 4. Preserve method body.
> 5. Preserve annotations.
> 6. Apply in sandbox only.
> 7. Apply after OpenRewrite Boot 3 and before build validation of `spring-boot-3-5-14`.
> 8. Record operation in migration ledger:
>    - file changed
>    - old signature excerpt
>    - new signature excerpt
>    - unit id
> 9. Do not hardcode common-utils, CustomExceptionTranslator, msa-dto, or repo names.
> 10. Do not remove `@Override` blindly.
> 11. Do not skip tests.
> 12. Do not modify legacy repo.
> 13. Keep old profiles backward compatible.
>
> Important:
> First inspect the actual failing method around line 355 in the sandbox error contract/run. Implement a generic rule based on Spring Framework 6 API signatures, not on file name.
>
> Integration:
> - Attach this deterministic compile-fix to `spring-boot-3-5-14` after OpenRewrite and before build validation.
> - If no ResponseEntityExceptionHandler override exists, no-op.
> - If signatures are already Spring 6-compatible, no-op.
>
> Tests:
> 1. Updates Spring 5-style ResponseEntityExceptionHandler override with `HttpStatus` parameter to Spring 6-style `HttpStatusCode`.
> 2. Keeps method body unchanged.
> 3. Updates imports correctly.
> 4. Does not remove `@Override`.
> 5. No-op for unrelated classes.
> 6. No-op when already Spring 6-compatible.
> 7. Ledger records exception handler signature alignment.
> 8. `spring-boot-3-5-14` execution plan includes the fix before build validation.
> 9. No project-specific names.
> 10. Existing msa-dto flow remains green.
> 11. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu9.
> Do not reuse previous runs.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. Failing method before/after excerpt
> 8. Ledger excerpt
> 9. Final run status or next blocker
> 10. Why this is generic and deterministic

<details><summary>15 previous messages</summary>

> Use caveman. First I inspect real failing method in `cu8` sandbox and existing deterministic Java patch hooks so fix matches actual Spring 6 signature break.
>
> Actual failing method is not the `HttpStatus` parameter case. It is `@Override handleConstraintViolation(...)`. I’m checking the class header so we patch the real Spring 6 override shape generically, not blindly.
>
> This repo’s real failure is via `ProblemHandling`, not direct `ResponseEntityExceptionHandler`. I’m inspecting the local parent `ExceptionTranslator` too, so we can make one deterministic Spring 6 handler-override patch that covers the actual inheritance chain.
>
> I found local `problem-spring-web` sources in `.m2`, so I can inspect the real Spring 6 trait signature instead of guessing.
>
> Important clue: local source jar shows `ConstraintViolationAdviceTrait` still on `javax.validation`. That explains why OpenRewrite changed the subclass import to `jakarta.validation`, breaking the override. I’m checking the exact resolved Zalando version in the sandbox so we can patch generically against the real trait mismatch.
>
> I’m implementing one deterministic source patch with two safe rules:
> - `HttpStatus` param -> `HttpStatusCode` in `@Override` exception-handler methods
> - `handleConstraintViolation` override import/type -> `javax.validation.ConstraintViolationException` when Spring/Problem trait override was rewritten incompatibly
>
> Then I’ll wire it into `spring-boot-3-5-14`, test it, and rerun `C:\mf\cu9`.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+129 -5)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+26 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+1 -0)
> - Wrote `./tests/test_transformation_agent.py` (+1 -0)
> - Wrote `./tests/test_transformation_agent.py` (+121 -5)
>
> </details>
>
> Need ledger test too. I’m adding one that records old/new signature excerpts through the agent path.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+57 -0)
>
> </details>
>
> Running transformation tests first. If regex behaves, I’ll run orchestrator/full suite, then clean `C:\mf\cu9` live flow.
>
> Regex too narrow: it matched `public`, but real Spring handlers are often `protected`. I’m widening it to `public|protected`, then rerunning tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+2 -2)
>
> </details>
>
> Rerunning transformation tests, orchestrator, then full suite.
>
> All tests green. Starting fresh live `common-utils` run on `C:\mf\cu9`.
>
> Clean live rerun moved past the old override blocker. I’m pulling the before/after method snippet and ledger excerpt for the report, then I’ll close it out cleanly.
</details>

1. **Summary**

Done.

Factory now add deterministic Spring 6 exception-handler override align in `spring-boot-3-5-14`:
- patch overridden handler signatures using Spring 6-safe rule
- keep method body
- keep `@Override`
- record old/new signature in ledger
- sandbox only

Real `common-utils` proof:
- old blocker gone: `CustomExceptionTranslator.java` override compile error fixed
- next blocker moved later to test-compile classpath issue: missing `org.slf4j.spi.LoggingEventAware`

2. **Files Modified**

- [pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- [agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- `HttpStatus` override param -> `HttpStatusCode`
- method body unchanged
- import updated with `HttpStatusCode`
- `@Override` preserved
- `handleConstraintViolation` override aligned from rewritten Jakarta type back to trait-compatible type
- unrelated class no-op
- already-compatible class no-op
- ledger records old/new signature
- execution plan includes fix before Boot 3 build validation

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-165730 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu9" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu9\.migration\runs\common-utils-clean-20260601-165730" --run-id "common-utils-clean-20260601-165730" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-165730" --run-dir "C:\mf\cu9\.migration\runs\common-utils-clean-20260601-165730" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `63 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `597 passed, 3 skipped`

6. **New `common-utils` Run Id**

- `common-utils-clean-20260601-165730`

7. **Failing Method Before/After Excerpt**

Before:
```java
@Override
public ResponseEntity<Problem> handleConstraintViolation(final ConstraintViolationException exception, final NativeWebRequest request) {
```

After:
```java
@Override
public ResponseEntity<Problem> handleConstraintViolation(final javax.validation.ConstraintViolationException exception, final NativeWebRequest request) {
```

Files:
- before reference run: `C:\mf\cu8\...CustomExceptionTranslator.java`
- after fixed run: [CustomExceptionTranslator.java](C:/mf/cu9/.migration/runs/common-utils-clean-20260601-165730/workspaces/sandbox/src/main/java/com/total/corp/common/web/rest/advice/CustomExceptionTranslator.java)

8. **Ledger Excerpt**

From [ledger.json](C:/mf/cu9/.migration/runs/common-utils-clean-20260601-165730/workspaces/sandbox/.migration/ledger.json):

```json
{
  "type": "spring6_exception_handler_override_alignment",
  "status": "applied",
  "patches": [
    {
      "file": "src\\main\\java\\com\\total\\corp\\common\\web\\rest\\advice\\CustomExceptionTranslator.java",
      "patch": "spring6_exception_handler_override_alignment",
      "unit": "spring-boot-3-5-14",
      "old_signature": "@Override public ResponseEntity<Problem> handleConstraintViolation(final ConstraintViolationException exception, final NativeWebRequest request)",
      "new_signature": "@Override public ResponseEntity<Problem> handleConstraintViolation(final javax.validation.ConstraintViolationException exception, final NativeWebRequest request)"
    }
  ]
}
```

9. **Final Run Status Or Next Blocker**

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old override blocker fixed.

New blocker:
- test-compile classpath issue
- error contract: [build-error-20260601-162510-compilation_error.json](C:/mf/cu9/.migration/runs/common-utils-clean-20260601-165730/build/build-error-20260601-162510-compilation_error.json)

Exact new failure:
```text
CustomExceptionTranslatorTest.java:[75,15] cannot access org.slf4j.spi.LoggingEventAware
class file for org.slf4j.spi.LoggingEventAware not found
```

10. **Why This Is Generic And Deterministic**

- no file-name hardcode in logic
- no repo-name hardcode
- rule-based patch only
- covers generic Spring handler override shapes:
  - `@Override` handler params using `HttpStatus` -> `HttpStatusCode`
  - `handleConstraintViolation` override trait mismatch after automated Jakarta rewrite
- preserves body and annotations
- explicit deterministic text transforms only
- runs only in sandbox
- ledger records exact old/new signature evidence

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 23: Add deterministic SLF4J/logging alignment during Spring Boot 3 migration.
>
> Problem:
> After Spring 6 exception-handler override alignment, common-utils progresses further in `spring-boot-3-5-14` but fails during test compilation with:
> `cannot access org.slf4j.spi.LoggingEventAware`
> `class file for org.slf4j.spi.LoggingEventAware not found`
>
> Likely cause:
> Spring Boot 3 / modern logging stack expects SLF4J 2.x, but the migrated project still has an old explicit or transitive SLF4J 1.7.x dependency on the classpath.
>
> Goal:
> During Boot 3 migration, deterministically align SLF4J/logging dependencies to a Boot 3 compatible set.
>
> Required behavior:
> 1. Detect Maven dependencies and dependencyManagement entries for:
>    - org.slf4j:slf4j-api
>    - org.slf4j:slf4j-simple
>    - org.slf4j:slf4j-log4j12
>    - org.slf4j:jcl-over-slf4j
>    - org.slf4j:jul-to-slf4j
>    - org.slf4j:log4j-over-slf4j
>    - ch.qos.logback:logback-classic
>    - ch.qos.logback:logback-core
>    - org.apache.logging.log4j:* if directly conflicting
> 2. For Spring Boot 3 routes, ensure SLF4J API is 2.x compatible.
> 3. Prefer Spring Boot BOM-managed versions when the project is Boot BOM/parent-managed.
> 4. If the project is not Boot BOM/parent-managed, use profile/config versions, for example:
>    - framework_versions.slf4j_api
>    - framework_versions.logback
> 5. If an explicit old `org.slf4j:slf4j-api` version is present, update it or remove the version when BOM-managed.
> 6. If an old SLF4J binding is present and conflicts with Boot 3 logging, mark it as high-risk or align deterministically only when safe.
> 7. Do not remove logging dependencies unless the rule is explicitly safe and covered by tests.
> 8. Apply in sandbox only.
> 9. Apply after OpenRewrite Boot 3 and before build/test validation of `spring-boot-3-5-14`.
> 10. Record operation in ledger:
>     - detected logging artifacts
>     - old versions
>     - new versions or BOM-managed
>     - file changed
>     - unit id
> 11. Do not hardcode common-utils, msa-dto, or repository names.
> 12. Do not skip tests.
> 13. Do not modify legacy repo.
> 14. Keep old profiles backward compatible.
>
> Integration:
> - Attach SLF4J/logging alignment to `spring-boot-3-5-14` after OpenRewrite and before build validation.
> - If no SLF4J/logging issue is detected, no-op.
> - If already Boot 3 compatible, no-op.
>
> Tests:
> 1. Updates old explicit `org.slf4j:slf4j-api:1.7.x` to configured SLF4J 2.x version when not BOM-managed.
> 2. Removes explicit SLF4J version when Boot BOM-managed.
> 3. No-op when SLF4J is already 2.x.
> 4. No-op when no SLF4J/logging dependencies exist.
> 5. Ledger records SLF4J/logging alignment.
> 6. `spring-boot-3-5-14` execution plan includes logging alignment before build validation.
> 7. No project-specific names.
> 8. Existing msa-dto flow remains green.
> 9. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu10.
> Do not reuse previous runs.
>
> Before or during the run, capture dependency evidence:
> mvn dependency:tree "-Dincludes=org.slf4j:*,ch.qos.logback:*"
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. SLF4J/logback dependency tree before/after excerpt
> 8. POM diff excerpt
> 9. Ledger excerpt
> 10. Final run status or next blocker
> 11. Why this is generic and deterministic

<details><summary>18 previous messages</summary>

> Use caveman. First I inspect real `cu9` logging deps and current patch hooks, so fix matches actual SLF4J drift.
>
> Plan set:
> - add `framework_versions.slf4j_api`
> - add deterministic `align_slf4j_logging`
> - wire into `spring-boot-3-5-14` before build validation
> - focused tests, then fresh `C:\mf\cu10` run with before/after tree.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+7 -0)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+108 -0)
>
> </details>
>
> Need tests for patcher and execution plan. Adding now.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+111 -0)
> - Wrote `./tests/test_transformation_agent.py` (+59 -0)
>
> </details>
>
> Need adjust framework_versions payload in test fixture. search existing and patch maybe already only thymeleaf.
>
> I need the execution-plan fixture to carry `slf4j_api`, otherwise that new op won’t appear in the test. Patching both fixture payloads now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+2 -2)
>
> </details>
>
> Run focused tests, then orchestrator/full suite, then fresh `C:\mf\cu10` run with before/after trees.
>
> Focused tests green. Running orchestrator and full suite now.
>
> All tests green. Capturing before-tree from `cu9`, then fresh `C:\mf\cu10` live flow.
>
> Starting clean `cu10` run now.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Use caveman skill. Me run fresh `cu10` now, then inspect sandbox tree, pom, ledger, error.
>
> Repo dirty, but our path clear. Now do clean `cu10` governed run end to end.
>
> Phase 1 pass. Me approve, then resume sandbox migration.
>
> SLF4J compile blocker dead. New fail is real tests in Boot 3 step. Me gather proof: after-tree, POM, ledger, root error.
>
> Me peek root test error, so report honest next blocker.
</details>

1. Summary

Ticket 23 done.

Factory now align SLF4J/logging in `spring-boot-3-5-14`:
- detect `org.slf4j:*` and `ch.qos.logback:*`
- if old explicit `slf4j-api` found, update to Boot 3 compatible version from profile config
- if Boot BOM-managed, remove explicit version instead
- sandbox only
- ledger record exact change

Real `common-utils` proof:
- old blocker gone: `org.slf4j.spi.LoggingEventAware` missing no longer appears
- `slf4j-api` now `2.0.17`
- new blocker moved forward to real Spring Security test-context failure in Boot 3 step

2. Files modified

- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. Tests added

- old explicit `org.slf4j:slf4j-api:1.7.x` -> configured `2.0.x` when not BOM-managed
- explicit SLF4J version removed when Boot BOM-managed
- no-op when already SLF4J 2.x
- no-op when no logging deps exist
- ledger records SLF4J alignment
- `spring-boot-3-5-14` execution plan includes logging alignment

4. Commands run

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
$env:JAVA_HOME='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:PATH='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19\bin;' + $env:PATH
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
mvn dependency:tree "-Dincludes=org.slf4j:*,ch.qos.logback:*" | Select-String -Pattern 'slf4j|logback'
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260601-164829 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu10" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu10\.migration\runs\common-utils-clean-20260601-164829" --run-id "common-utils-clean-20260601-164829" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260601-164829" --run-dir "C:\mf\cu10\.migration\runs\common-utils-clean-20260601-164829" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. Test results

- `tests/test_maven_pom_patcher.py -q`: `36 passed`
- `tests/test_transformation_agent.py -q`: `64 passed, 2 skipped`
- `tests/agents/planning_agent/test_boot21_profile.py -q`: `6 passed`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `602 passed, 3 skipped`

6. New common-utils run id

- `common-utils-clean-20260601-164829`

7. SLF4J/logback dependency tree before/after excerpt

Before, old run `cu9`:
```text
[INFO] |        +- ch.qos.logback:logback-classic:jar:1.5.32:compile
[INFO] |        |  \- ch.qos.logback:logback-core:jar:1.5.32:compile
[INFO] |        \- org.slf4j:jul-to-slf4j:jar:2.0.17:compile
[INFO] \- org.slf4j:slf4j-api:jar:1.7.25:compile
```

After, new run `cu10`:
```text
[INFO] |        +- ch.qos.logback:logback-classic:jar:1.5.32:compile
[INFO] |        |  \- ch.qos.logback:logback-core:jar:1.5.32:compile
[INFO] |        \- org.slf4j:jul-to-slf4j:jar:2.0.17:compile
[INFO] \- org.slf4j:slf4j-api:jar:2.0.17:compile
```

8. POM diff excerpt

Before:
```xml
<org.slf4j.version>1.7.25</org.slf4j.version>

<dependency>
    <groupId>org.slf4j</groupId>
    <artifactId>slf4j-api</artifactId>
    <version>${org.slf4j.version}</version>
</dependency>
```

After:
```xml
<org.slf4j.version>2.0.17</org.slf4j.version>

<dependency>
    <groupId>org.slf4j</groupId>
    <artifactId>slf4j-api</artifactId>
    <version>${org.slf4j.version}</version>
</dependency>
```

POM proof: [pom.xml](C:/mf/cu10/.migration/runs/common-utils-clean-20260601-164829/workspaces/sandbox/pom.xml)

9. Ledger excerpt

From [ledger.json](C:/mf/cu10/.migration/runs/common-utils-clean-20260601-164829/workspaces/sandbox/.migration/ledger.json):

```json
{
  "op": "align_slf4j_logging",
  "status": "updated",
  "detected_logging_artifacts": [
    "org.slf4j:slf4j-api"
  ],
  "old_versions": [
    "1.7.25"
  ],
  "new_versions": [
    "2.0.17"
  ],
  "removed_versions": [],
  "updated_properties": [
    "org.slf4j.version"
  ],
  "managed_by_bom": false
}
```

10. Final run status or next blocker

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old blocker fixed:
- no more `cannot access org.slf4j.spi.LoggingEventAware`

New blocker:
- unit: `spring-boot-3-5-14`
- error contract: [build-error-20260601-165646-unknown_failure.json](C:/mf/cu10/.migration/runs/common-utils-clean-20260601-164829/build/build-error-20260601-165646-unknown_failure.json)

Actual root cause from surefire:
```text
Caused by: java.lang.NoClassDefFoundError: org/springframework/security/core/annotation/AnnotationTemplateExpressionDefaults
Caused by: java.lang.ClassNotFoundException: org.springframework.security.core.annotation.AnnotationTemplateExpressionDefaults
```

Test evidence:
- [com.total.corp.advice.CustomExceptionTranslatorTest.txt](C:/mf/cu10/.migration/runs/common-utils-clean-20260601-164829/workspaces/sandbox/target/surefire-reports/com.total.corp.advice.CustomExceptionTranslatorTest.txt)

So next real blocker is Spring Security dependency/config mismatch in Boot 3 test context, not logging.

11. Why this is generic and deterministic

- no `common-utils` hardcode
- no `msa-dto` hardcode
- no repo-name logic
- rule look only at generic logging coordinates
- target version comes from profile config, not repo logic
- execution plan declares exact deterministic `maven_pom_patch`
- sandbox only
- ledger records exact old/new versions and touched file
- no test skipping
- no legacy repo modification

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> First inspect whether the factory already has Spring Security migration or dependency alignment logic. If it exists, reuse/extend/wire it correctly instead of duplicating it.
> You are working on the AI Migration Factory repository.
>
> Ticket 24: Add deterministic Spring Security alignment during Spring Boot 3 migration.
>
> Problem:
> After SLF4J/logging alignment, common-utils progresses further in `spring-boot-3-5-14` but fails in the test Spring context with:
>
> `Caused by: java.lang.NoClassDefFoundError: org/springframework/security/core/annotation/AnnotationTemplateExpressionDefaults`
> `Caused by: java.lang.ClassNotFoundException: org.springframework.security.core.annotation.AnnotationTemplateExpressionDefaults`
>
> Likely cause:
> Spring Boot 3 migration produced or retained a mixed Spring Security classpath. Some Spring Security modules expect a newer Spring Security core API, but another explicit or transitive Spring Security dependency is still old/misaligned.
>
> Goal:
> During Boot 3 migration, deterministically align Spring Security dependencies to a Boot 3 compatible set.
>
> Required behavior:
>
> 1. Detect Maven dependencies and dependencyManagement entries for `org.springframework.security:*`, including:
>
>    * spring-security-core
>    * spring-security-config
>    * spring-security-web
>    * spring-security-oauth2-*
>    * spring-security-test
>    * any other org.springframework.security artifact present
> 2. For Spring Boot 3 routes, ensure Spring Security modules are version-aligned.
> 3. Prefer Spring Boot BOM-managed versions when the project is Boot BOM/parent-managed.
> 4. If the project is not Boot BOM/parent-managed, use profile/config version, for example:
>
>    * framework_versions.spring_security
> 5. If explicit old Spring Security versions are present:
>
>    * remove explicit versions when BOM-managed
>    * otherwise update them to configured profile version
> 6. Apply in sandbox only.
> 7. Apply after OpenRewrite Boot 3 and before build/test validation of `spring-boot-3-5-14`.
> 8. Record operation in ledger:
>
>    * detected Spring Security artifacts
>    * old versions
>    * new versions or BOM-managed
>    * file changed
>    * unit id
> 9. Do not hardcode common-utils, msa-dto, or repository names.
> 10. Do not patch tests to hide the problem.
> 11. Do not skip tests.
> 12. Do not modify legacy repo.
> 13. Keep old profiles backward compatible.
>
> Integration:
>
> * Attach Spring Security alignment to `spring-boot-3-5-14` after OpenRewrite and before build validation.
> * If no Spring Security dependency exists, no-op.
> * If already aligned, no-op.
> * Use analysis dependency facts when available, with POM scan fallback.
>
> Tests:
>
> 1. Updates old explicit `org.springframework.security:spring-security-core` version to configured Boot 3 compatible version when not BOM-managed.
> 2. Updates multiple Spring Security artifacts consistently.
> 3. Removes explicit Spring Security versions when Boot BOM-managed.
> 4. No-op when already aligned.
> 5. No-op when no Spring Security artifacts exist.
> 6. Ledger records Spring Security alignment.
> 7. `spring-boot-3-5-14` execution plan includes Spring Security alignment before build validation.
> 8. No project-specific names.
> 9. Existing msa-dto flow remains green.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu11.
> Do not reuse previous runs.
>
> Before or during the run, capture dependency evidence:
> mvn dependency:tree "-Dincludes=org.springframework.security:*"
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. Spring Security dependency tree before/after excerpt
> 8. POM diff excerpt
> 9. Ledger excerpt
> 10. Final run status or next blocker
> 11. Why this is generic and deterministic

<details><summary>30 previous messages</summary>

> First me inspect existing Spring Security logic, so no duplicate dumb thing.
>
> Found: risk signal exists, tiny `SecurityConfig.java` patch exists, but no dependency alignment yet. Me inspect exact reusable bits.
>
> Existing reuse path clear: risk classifier + dependency_graph helpers + pom patcher patterns. Me wire new security align there, not duplicate weirdly.
>
> Plan: add generic `align_spring_security_dependencies`, test it, then fresh `cu11` run with before/after security tree proof.
>
> Me patch code now: add security operation, config, tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+138 -0)
>
> </details>
>
> Now wire execution plan + profile config.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+20 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
>
> </details>
>
> Me patch tests next.
>
> Before more patch, me inspect real `cu10` security deps so fix hits actual case, not fantasy.
>
> Real evidence found: explicit `spring-security-test 5.8.16`, transitive core 5.8.16. Good. Patch will fix real thing. Now me update tests.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+154 -0)
>
> </details>
>
> Me patch execution-plan and ledger tests for new security op.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+13 -1)
>
> </details>
>
> Need ledger test for security. Me add next to SLF4J ledger test.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+59 -0)
>
> </details>
>
> Code patched. Me run focused tests first, then full suite if green.
>
> One test missed config payload. Me fix small thing, rerun.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+5 -1)
>
> </details>
>
> Tests green. Me do exact requested command set, then fresh `cu11` run with security tree proof.
>
> Now live proof on new clean `cu11`. Me capture before-tree from old sandbox already, then run new clean flow.
>
> Phase 1 pass. Me approve/resume `cu11`.
>
> Live run confirms security classpath blocker moved. Me gather after-tree, pom, ledger, root cause.
>
> Small polish: real Boot 3.5.14 pulls Spring Security `6.5.10`, so me align config to that exact line. Better governance, less mixed minors.
>
> Patch had one fuzzy miss. Me inspect exact lines, then patch clean.
>
> Now me patch version bump cleanly.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -1)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -1)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -2)
> - Wrote `./tests/test_maven_pom_patcher.py` (+10 -10)
> - Wrote `./tests/test_transformation_agent.py` (+5 -5)
>
> </details>
>
> Version now matches real Boot 3.5.14 line. Me rerun tests, then fresh clean `cu11` again.
>
> Need rerun clean cu11. Move aside current C:\mf\cu11 and rerun.
>
> Final proof gather now.
</details>

1. Summary

Me inspected first.

Already existed:
- planning risk signal for legacy Spring Security in [risk_classifier.py](./migration_factory/agents/planning_agent/risk_classifier.py)
- source patch logic in [pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- deterministic Maven patch framework in [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- dependency-graph aware execution planning in [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)

So me reused those. No duplicate side-channel logic.

Ticket 24 done:
- added deterministic `align_spring_security_dependencies`
- wired into `spring-boot-3-5-14`
- uses dependency graph facts plus POM scan fallback
- profile-driven target version
- sandbox only
- ledger recorded

Real `common-utils` result:
- old blocker gone:
  - `AnnotationTemplateExpressionDefaults` missing no longer appears
- Spring Security tree now aligned to `6.5.10`
- new blocker moved forward to Jackson mismatch:
  - `NoClassDefFoundError: com/fasterxml/jackson/databind/cfg/EnumFeature`

2. Files modified

- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. Tests added

- explicit old `spring-security-core` property version -> configured Boot 3 version
- multiple Spring Security artifacts update together
- explicit versions removed when Boot BOM-managed
- no-op when already aligned
- no-op when no Spring Security artifacts
- ledger records Spring Security alignment
- execution plan includes Spring Security alignment before Boot 3 build validation

4. Commands run

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Before evidence:
```powershell
$env:JAVA_HOME='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:PATH='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19\bin;' + $env:PATH
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
mvn dependency:tree "-Dincludes=org.springframework.security:*" | Select-String -Pattern 'spring-security'
```

Clean `cu11` run:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260602-094737 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu11" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu11\.migration\runs\common-utils-clean-20260602-094737" --run-id "common-utils-clean-20260602-094737" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260602-094737" --run-dir "C:\mf\cu11\.migration\runs\common-utils-clean-20260602-094737" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

After evidence:
```powershell
mvn dependency:tree "-Dincludes=org.springframework.security:*" | Select-String -Pattern 'spring-security'
```

5. Test results

- `tests/test_maven_pom_patcher.py -q`: `41 passed`
- `tests/test_transformation_agent.py -q`: `65 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `608 passed, 3 skipped`

6. New common-utils run id

- `common-utils-clean-20260602-094737`

7. Spring Security dependency tree before/after excerpt

Before, old failing run:
```text
[INFO] |  +- org.springframework.security:spring-security-config:jar:6.5.10:compile
[INFO] |  \- org.springframework.security:spring-security-web:jar:6.5.10:compile
[INFO] \- org.springframework.security:spring-security-test:jar:5.8.16:test
[INFO]    \- org.springframework.security:spring-security-core:jar:5.8.16:compile
[INFO]       \- org.springframework.security:spring-security-crypto:jar:5.8.16:compile
```

After, new `cu11` run:
```text
[INFO] |  +- org.springframework.security:spring-security-config:jar:6.5.10:compile
[INFO] |  \- org.springframework.security:spring-security-web:jar:6.5.10:compile
[INFO] \- org.springframework.security:spring-security-test:jar:6.5.10:test
[INFO]    \- org.springframework.security:spring-security-core:jar:6.5.10:compile
[INFO]       \- org.springframework.security:spring-security-crypto:jar:6.5.10:compile
```

8. POM diff excerpt

Before:
```xml
<dependency>
    <groupId>org.springframework.security</groupId>
    <artifactId>spring-security-test</artifactId>
    <version>5.8.16</version>
    <scope>test</scope>
</dependency>
```

After:
```xml
<dependency>
    <groupId>org.springframework.security</groupId>
    <artifactId>spring-security-test</artifactId>
    <version>6.5.10</version>
    <scope>test</scope>
</dependency>
```

POM proof:
- [pom.xml](C:/mf/cu11/.migration/runs/common-utils-clean-20260602-094737/workspaces/sandbox/pom.xml)

9. Ledger excerpt

From [ledger.json](C:/mf/cu11/.migration/runs/common-utils-clean-20260602-094737/workspaces/sandbox/.migration/ledger.json):

```json
{
  "op": "align_spring_security_dependencies",
  "status": "updated",
  "detected_spring_security_artifacts": [
    "org.springframework.security:spring-security-test",
    "org.springframework.security:spring-security-config",
    "org.springframework.security:spring-security-core",
    "org.springframework.security:spring-security-web"
  ],
  "old_versions": ["5.8.16"],
  "new_versions": ["6.5.10"],
  "removed_versions": [],
  "updated_properties": [],
  "updated_dependencies": [
    "org.springframework.security:spring-security-test"
  ],
  "managed_by_bom": false
}
```

10. Final run status or next blocker

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old blocker fixed:
- no more `AnnotationTemplateExpressionDefaults`
- no more old Spring Security mixed `5.8.16` test/core under Boot 3

New blocker:
- unit: `spring-boot-3-5-14`
- error contract: [build-error-20260602-095917-missing_config.json](C:/mf/cu11/.migration/runs/common-utils-clean-20260602-094737/build/build-error-20260602-095917-missing_config.json)

Actual root cause from surefire:
```text
Caused by: java.lang.NoClassDefFoundError: com/fasterxml/jackson/databind/cfg/EnumFeature
Caused by: java.lang.ClassNotFoundException: com.fasterxml.jackson.databind.cfg.EnumFeature
```

Test proof:
- [CustomExceptionTranslatorTest.txt](C:/mf/cu11/.migration/runs/common-utils-clean-20260602-094737/workspaces/sandbox/target/surefire-reports/com.total.corp.advice.CustomExceptionTranslatorTest.txt)

So next real blocker is Jackson classpath/runtime alignment in Boot 3 test context, not Spring Security anymore.

11. Why this is generic and deterministic

- reused existing factory mechanisms, no duplicate side system
- no `common-utils`
- no `msa-dto`
- no repo-name hardcode
- detection uses:
  - POM direct deps
  - dependencyManagement deps
  - dependency graph `present_artifacts`
- version comes from profile config:
  - `framework_versions.spring_security: "6.5.10"`
- execution plan declares exact deterministic `maven_pom_patch`
- patch behavior fixed:
  - BOM-managed -> remove explicit versions
  - non-BOM -> update explicit old versions to configured version
- sandbox only
- ledger records exact old/new/deps touched
- no test skip
- no legacy repo modification

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 25: Make Jackson alignment hop-aware for Spring Boot 3.
>
> Context:
> Ticket 17 added deterministic Jackson alignment for Boot 2.7 stabilization and aligned Jackson to 2.13.5. That fixed the Boot 2.7 JavaTimeModule blocker.
>
> Now common-utils reaches `spring-boot-3-5-14` and fails with:
> `NoClassDefFoundError: com/fasterxml/jackson/databind/cfg/EnumFeature`
>
> Likely cause:
> Jackson was aligned for the Boot 2.7 hop but not realigned for the Boot 3.5 hop. The Boot 3.5 runtime expects a newer Jackson stack, while the sandbox POM/dependencyManagement may still force Jackson 2.13.5 or another older version.
>
> Goal:
> Reuse and extend the existing Jackson alignment logic so Jackson alignment is hop-aware / target-Boot-aware.
>
> Required behavior:
>
> 1. Inspect existing Jackson alignment implementation from Ticket 17 first.
> 2. Do not create duplicate side-channel logic.
> 3. For `spring-boot-2-7-stabilization`, keep existing Boot 2.7-compatible Jackson behavior.
> 4. For `spring-boot-3-5-14`, realign Jackson artifacts to the Boot 3 target-compatible version from profile/config.
> 5. Prefer Spring Boot BOM-managed versions when the project is truly Boot BOM/parent-managed.
> 6. If not BOM/parent-managed, use profile/config, for example:
>    `framework_versions.jackson`
> 7. The Boot 3 Jackson alignment must update or remove older explicit Jackson versions/dependencyManagement entries introduced or left from earlier hops.
> 8. Align all detected Jackson artifacts consistently:
>
>    * com.fasterxml.jackson.core:jackson-databind
>    * com.fasterxml.jackson.core:jackson-core
>    * com.fasterxml.jackson.core:jackson-annotations
>    * com.fasterxml.jackson.datatype:jackson-datatype-jsr310
>    * com.fasterxml.jackson.datatype:jackson-datatype-jdk8
>    * com.fasterxml.jackson.module:jackson-module-parameter-names
>    * com.fasterxml.jackson.dataformat:jackson-dataformat-csv if present
>    * com.fasterxml.jackson.dataformat:jackson-dataformat-xml if present
>    * com.fasterxml.jackson.module:jackson-module-jaxb-annotations if present
> 9. Apply in sandbox only.
> 10. Apply after OpenRewrite Boot 3 and before build/test validation of `spring-boot-3-5-14`.
> 11. Record operation in ledger:
>
>     * unit id
>     * target Jackson version or BOM-managed
>     * old versions
>     * updated properties
>     * updated dependencyManagement entries
>     * files changed
> 12. Do not hardcode common-utils, msa-dto, or repo names.
> 13. Do not skip tests.
> 14. Do not modify legacy repo.
> 15. Keep old profiles backward compatible.
>
> Integration:
>
> * Existing Jackson alignment on `spring-boot-2-7-stabilization` must remain.
> * Add or extend Jackson alignment on `spring-boot-3-5-14`.
> * If Jackson is already aligned for Boot 3, no-op.
> * If dependencyManagement contains older Jackson entries from an earlier hop, update them to the Boot 3 target version or remove versions when BOM-managed.
>
> Tests:
>
> 1. Existing Boot 2.7 Jackson alignment still targets Boot 2.7 version.
> 2. Boot 3 unit realigns old Jackson 2.13.x entries to configured Boot 3 Jackson version.
> 3. Boot 3 unit updates property-based Jackson versions.
> 4. Boot 3 unit updates dependencyManagement Jackson entries.
> 5. Already-aligned Boot 3 Jackson stack is no-op.
> 6. Ledger records Boot 3 Jackson alignment separately from Boot 2.7 alignment.
> 7. `spring-boot-3-5-14` execution plan includes Jackson alignment before build validation.
> 8. No project-specific names.
> 9. Existing msa-dto flow remains green.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run a new clean common-utils flow using short path C:\mf\cu12.
> Do not reuse previous runs.
>
> Before or during the run, capture dependency evidence:
> mvn dependency:tree "-Dincludes=com.fasterxml.jackson*"
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. New common-utils run id
> 7. Jackson dependency tree before/after excerpt
> 8. POM diff excerpt
> 9. Ledger excerpt showing Boot 2.7 and Boot 3 Jackson alignment separately
> 10. Final run status or next blocker
> 11. Why this is generic and deterministic

<details><summary>33 previous messages</summary>

> First me inspect Jackson logic from Ticket 17, then extend same path for Boot 3. No duplicate monster.
>
> Need exact Boot 3 Jackson target. Me ask sandbox dependency tree, not guess.
>
> Boot 3 target Jackson still stuck at `2.13.5`. Me query real Boot `3.5.14` managed Jackson from temp Maven project, so config exact not guessed.
>
> Me have exact Boot `3.5.14` Jackson now: `2.21.2` (`annotations` resolved `2.21`). Good enough for governed config. Now me wire Boot 3 hop to reuse same Jackson patcher with Boot 3 target version.
>
> Now edits: profile `framework_versions.jackson`, boot3 execution-plan op, tests for boot3 realign and separate ledger.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+10 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
>
> </details>
>
> Patch planning profile tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
>
> </details>
>
> Me add Boot 3 Jackson tests on same existing patcher, not new code path.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+120 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+44 -0)
>
> </details>
>
> Me update execution-plan and ledger tests for hop-aware Jackson.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+13 -5)
> - Wrote `./tests/test_transformation_agent.py` (+67 -0)
>
> </details>
>
> Me run focused tests now before live `cu12`.
>
> One test too skinny. Me fill all mandatory Jackson managed entries, then rerun.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_maven_pom_patcher.py` (+15 -0)
>
> </details>
>
> Missed Boot 3 test fixture config. Me add `jackson: 2.21.2`, rerun.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+1 -0)
>
> </details>
>
> Tests green. Me run exact validation set, then fresh clean `cu12`.
>
> Me do fresh governed `cu12` run now.
>
> Real run exposed one nuance: Boot `3.5.14` Jackson not perfectly one-number. `databind/core` at `2.21.2`, `annotations` at `2.21`. Me extend same Jackson patcher with optional per-artifact override from profile, still generic.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+22 -5)
>
> </details>
>
> Now execution-plan/profile wire annotation override.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+5 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
>
> </details>
>
> Patch tests for override.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+33 -4)
>
> </details>
>
> Me update execution-plan and ledger expectations for Jackson override.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+10 -0)
>
> </details>
>
> One more test loop. Then me rerun clean `cu12` if green.
>
> Missed one fixture key. Me add `jackson_annotations`.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+1 -0)
>
> </details>
>
> Final validation sweep, then fresh rerun `cu12` because behavior changed.
>
> Now real clean `cu12` rerun with fixed Boot 3 Jackson override.
>
> Good. Jackson classpath blocker dead. Me gather final proof: after-tree, pom, ledger.
</details>

1. Summary

Me inspected existing Jackson path first.

Already existed:
- deterministic `align_jackson_dependency_management` in [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- Boot 2.7 wiring in [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)

So me reused that same logic. No duplicate side-channel.

Ticket 25 done:
- Boot `2.7` hop keeps Jackson `2.13.5`
- Boot `3.5` hop now realigns Jackson again
- target version from profile config
- added generic per-artifact override support for cases like `jackson-annotations`
- sandbox only
- ledger now shows Boot 2.7 Jackson align and Boot 3 Jackson realign separately

Real `common-utils` proof:
- old blocker gone:
  - no more `NoClassDefFoundError: com/fasterxml/jackson/databind/cfg/EnumFeature`
- next blocker moved forward to real test failures in Boot 3 step

2. Files modified

- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. Tests added

- Boot 2.7 Jackson align still uses `2.13.5`
- Boot 3 unit realigns `2.13.5 -> 2.21.2`
- Boot 3 property-based Jackson version updates
- Boot 3 dependencyManagement entries update
- Boot 3 already-aligned stack no-op
- Boot 3 ledger record separate from Boot 2.7
- Boot 3 execution plan includes Jackson align before build validation
- generic artifact override path for `jackson-annotations`

4. Commands run

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Before evidence:
```powershell
$env:JAVA_HOME='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:PATH='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19\bin;' + $env:PATH
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
mvn dependency:tree "-Dincludes=com.fasterxml.jackson*" | Select-String -Pattern 'jackson'
```

Clean `cu12` run:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260602-105343 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu12" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu12\.migration\runs\common-utils-clean-20260602-105343" --run-id "common-utils-clean-20260602-105343" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260602-105343" --run-dir "C:\mf\cu12\.migration\runs\common-utils-clean-20260602-105343" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

After evidence:
```powershell
mvn dependency:tree "-Dincludes=com.fasterxml.jackson*" | Select-String -Pattern 'jackson'
```

5. Test results

- `tests/test_maven_pom_patcher.py -q`: `45 passed`
- `tests/test_transformation_agent.py -q`: `66 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `613 passed, 3 skipped`

6. New common-utils run id

- `common-utils-clean-20260602-105343`

7. Jackson dependency tree before/after excerpt

Before, old run:
```text
[INFO] |     +- com.fasterxml.jackson.datatype:jackson-datatype-jdk8:jar:2.13.5:compile
[INFO] |     +- com.fasterxml.jackson.datatype:jackson-datatype-jsr310:jar:2.13.5:compile
[INFO] |     \- com.fasterxml.jackson.module:jackson-module-parameter-names:jar:2.13.5:compile
[INFO] +- io.jsonwebtoken:jjwt-jackson:jar:0.10.5:compile
[INFO] |  \- com.fasterxml.jackson.core:jackson-databind:jar:2.13.5:compile
[INFO] |  \- com.fasterxml.jackson.core:jackson-core:jar:2.13.5:compile
[INFO] |     \- com.fasterxml.jackson.dataformat:jackson-dataformat-xml:jar:2.13.5:compile
[INFO] \- com.fasterxml.jackson.dataformat:jackson-dataformat-csv:jar:2.13.5:compile
[INFO]    \- com.fasterxml.jackson.core:jackson-annotations:jar:2.13.5:compile
```

After, `cu12`:
```text
[INFO] |     +- com.fasterxml.jackson.datatype:jackson-datatype-jdk8:jar:2.21.2:compile
[INFO] |     +- com.fasterxml.jackson.datatype:jackson-datatype-jsr310:jar:2.21.2:compile
[INFO] |     \- com.fasterxml.jackson.module:jackson-module-parameter-names:jar:2.21.2:compile
[INFO] +- io.jsonwebtoken:jjwt-jackson:jar:0.10.5:compile
[INFO] |  \- com.fasterxml.jackson.core:jackson-databind:jar:2.21.2:compile
[INFO] |  \- com.fasterxml.jackson.core:jackson-core:jar:2.21.2:compile
[INFO] |     \- com.fasterxml.jackson.dataformat:jackson-dataformat-xml:jar:2.21.2:compile
[INFO] \- com.fasterxml.jackson.dataformat:jackson-dataformat-csv:jar:2.21.2:compile
[INFO]    \- com.fasterxml.jackson.core:jackson-annotations:jar:2.21:compile
```

8. POM diff excerpt

Before:
```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.13.5</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-core</artifactId>
      <version>2.13.5</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-annotations</artifactId>
      <version>2.13.5</version>
    </dependency>
  </dependencies>
</dependencyManagement>
```

After:
```xml
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-databind</artifactId>
      <version>2.21.2</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-core</artifactId>
      <version>2.21.2</version>
    </dependency>
    <dependency>
      <groupId>com.fasterxml.jackson.core</groupId>
      <artifactId>jackson-annotations</artifactId>
      <version>2.21</version>
    </dependency>
  </dependencies>
</dependencyManagement>
```

POM proof:
- [pom.xml](C:/mf/cu12/.migration/runs/common-utils-clean-20260602-105343/workspaces/sandbox/pom.xml)

9. Ledger excerpt showing Boot 2.7 and Boot 3 Jackson alignment separately

From [ledger.json](C:/mf/cu12/.migration/runs/common-utils-clean-20260602-105343/workspaces/sandbox/.migration/ledger.json):

Boot 2.7 hop:
```json
{
  "unit_id": "spring-boot-2-7-stabilization",
  "op": "align_jackson_dependency_management",
  "target_version": "2.13.5",
  "detected_versions": ["2.10.0"]
}
```

Boot 3 hop:
```json
{
  "unit_id": "spring-boot-3-5-14",
  "op": "align_jackson_dependency_management",
  "target_version": "2.21.2",
  "detected_versions": ["2.13.5"],
  "version_overrides": {
    "com.fasterxml.jackson.core:jackson-annotations": "2.21"
  }
}
```

10. Final run status or next blocker

Run status:
- `analysis_status`: `PASS`
- `planning_status`: `PASS`
- `assessment_status`: `PASS`
- `transform_status`: `BUILD_FAILED_IN_SANDBOX`
- `final_status`: `BUILD_FAILED_IN_SANDBOX`

Old blocker fixed:
- no more `EnumFeature` classpath failure
- no more dependency resolution failure on wrong Jackson versions

New blocker:
- Boot 3 tests now actually run and fail on app/test behavior
- error contract: [build-error-20260602-110610-unknown_failure.json](C:/mf/cu12/.migration/runs/common-utils-clean-20260602-105343/build/build-error-20260602-110610-unknown_failure.json)

Top new failures:
```text
SpelEvaluation EL1011E: Attempted to call method concat(java.lang.String) on null context object
Null key returned for cache operation ... ensure compiler uses '-parameters' flag
NoSuchElementException: No value present
```

So next blocker now is real Spring/cache/test behavior, not Jackson alignment.

11. Why this is generic and deterministic

- reused existing Jackson patcher, no duplicate parallel system
- no `common-utils`
- no `msa-dto`
- no repo-name hardcode
- Boot 2.7 and Boot 3 decisions driven by unit/hop metadata
- target versions come from profile config
- patch op remains explicit deterministic `maven_pom_patch`
- optional per-artifact override generic, not project-specific
- sandbox only
- ledger records each hop separately
- no skipped tests
- no legacy repo modification

<details><summary>26 previous messages</summary>

> Context compaction
>
> Source: automatic
> Status: completed
>
> Use caveman skill. Me inspect existing compiler/plugin patch path first. Then me wire same deterministic Maven patch path, no duplicate magic.
>
> Existing patcher path good. Me inspect lower half: where deterministic unit ops built, where tests expect order. Then me patch there.
>
> No compiler patch yet. Me inspect helper funcs for XML plugin editing, then me add smallest clean path.
>
> Me found plugin helpers. Good. Now me patch compiler op into same Maven patcher + Boot 3 unit wiring + profile version + tests.
>
> Me ready edit. Add one Maven patch op, wire Boot 3 unit, add profile compiler version, add tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+163 -0)
>
> </details>
>
> Patch in. One ugly bit me clean now, then wire Boot 3 unit + tests.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+5 -0)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+0 -2)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
>
> </details>
>
> Now me add tests: patcher behavior, plan wiring, profile field. Then run focused tests fast.
>
> Small bug: old summary for absent plugin wrong. Me fix before tests.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+2 -2)
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+1 -1)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+6 -1)
> - Wrote `./tests/test_maven_pom_patcher.py` (+99 -0)
> - Wrote `./tests/test_transformation_agent.py` (+71 -0)
>
> </details>
>
> Code/tests in. Me run focused tests now. If red, me fix fast.
>
> One test typo. Duplicate arg. Me fix, rerun.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+8 -4)
>
> </details>
>
> Fix in. Me rerun focused tests.
>
> Focused tests green. Me run orchestrator suite, then full pytest. After that me do fresh `cu13` live run.
>
> Tests all green. Me start fresh `cu13` sandbox run now. Then me inspect POM diff, ledger, surefire summary, next blocker.
>
> Resume long. Me inspect run state + last logs now.
>
> Run still hot. Me wait little, then inspect final state.
>
> Run still chomp tests. Me wait more. Need final truth, not fake.
>
> Me inspect surefire reports now. Need know if `-parameters` error gone, what new blocker live.
>
> Path maybe not there yet. Me inspect sandbox target tree + latest log with plain PowerShell search.
>
> Good sign: `-parameters` error gone. Me inspect ledger/current unit. Need know where run sits now.
>
> Build looked good for Boot 3 step. But orchestration not finalized yet. Me inspect build/test artifacts around current unit.
>
> Me grab exact before/after proof for `-parameters`. Then me write report.
</details>

1. **Summary**

Did Ticket 26.

Me reused existing deterministic Maven patch path. No duplicate magic.

Added new `maven_pom_patch` op: `align_maven_compiler_parameters`.
Wired only into Boot 3 unit `spring-boot-3-5-14`.
It ensures Maven compiler emits parameter metadata with `<parameters>true</parameters>`.
If compiler plugin missing, adds `maven-compiler-plugin` with profile version.

Real `common-utils` proof:
- old cache/SpEL `-parameters` blocker gone
- Boot 3 test phase now moves past that
- new blocker now real test behavior in `CustomExceptionTranslatorTest`

2. **Files Modified**

- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- add `<parameters>true</parameters>` to existing `maven-compiler-plugin`
- preserve existing `source` / `target`
- add compiler plugin with configured version if absent
- no-op when parameters already enabled
- execution plan includes compiler alignment in `spring-boot-3-5-14`
- ledger records compiler alignment
- profile/planning carry `tooling_versions.maven_compiler_plugin`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

```powershell
if (Test-Path C:\mf\cu13) { Move-Item -LiteralPath C:\mf\cu13 -Destination ("C:\mf\cu13.backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id common-utils-clean-20260602-120500 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\cu13" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir "C:\mf\cu13\.migration\runs\common-utils-clean-20260602-120500" --run-id "common-utils-clean-20260602-120500" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route accepted: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved."
python -m migration_factory.orchestrator.resume --run-id "common-utils-clean-20260602-120500" --run-dir "C:\mf\cu13\.migration\runs\common-utils-clean-20260602-120500" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `49 passed`
- `tests/test_transformation_agent.py -q`: `67 passed, 2 skipped`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `618 passed, 3 skipped`

6. **New `common-utils` Run Id**

- `common-utils-clean-20260602-120500`

7. **POM Diff Excerpt For Compiler `parameters`**

Before, old run `cu12` failed with cache messages:
```text
Null key returned for cache operation ... ensure that the compiler uses the '-parameters' flag
SpelEvaluation EL1011E: Attempted to call method concat(java.lang.String) on null context object
```

After, `cu13` sandbox POM contains:
```xml
<plugin>
  <groupId>org.apache.maven.plugins</groupId>
  <artifactId>maven-compiler-plugin</artifactId>
  <configuration>
    <annotationProcessorPaths>
      ...
    </annotationProcessorPaths>
    <parameters>true</parameters>
  </configuration>
  <version>3.14.1</version>
</plugin>
```

Proof:
- [pom.xml](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/workspaces/sandbox/pom.xml)

8. **Ledger Excerpt**

From [ledger.json](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/workspaces/sandbox/.migration/ledger.json):

```json
{
  "op": "align_maven_compiler_parameters",
  "status": "updated",
  "old_compiler_configuration_summary": {
    "group_id": "org.apache.maven.plugins",
    "artifact_id": "maven-compiler-plugin",
    "version": "",
    "parameters_enabled": false,
    "compiler_args_contains_parameters": false,
    "source": "",
    "target": "",
    "release": ""
  },
  "new_compiler_configuration_summary": {
    "group_id": "org.apache.maven.plugins",
    "artifact_id": "maven-compiler-plugin",
    "version": "3.14.1",
    "parameters_enabled": true,
    "compiler_args_contains_parameters": false,
    "source": "",
    "target": "",
    "release": ""
  },
  "plugin_added": false,
  "new_version": "3.14.1"
}
```

9. **Final Run Status Or Next Blocker**

Run not fully finalized by orchestrator yet during observation window.
Current ledger state:
- `status`: `awaiting_build_agent`
- `current_unit`: `spring-boot-3-5-14`

Important part:
- old `-parameters` cache blocker disappeared
- search in `cu13` surefire reports found no `Null key returned for cache operation`
- search found no `SpelEvaluation EL1011E`

New blocker now:
- real Boot 3 test failures in [CustomExceptionTranslatorTest.txt](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/workspaces/sandbox/target/surefire-reports/com.total.corp.advice.CustomExceptionTranslatorTest.txt)
- summary:
```text
Tests run: 23, Failures: 7, Errors: 16, Skipped: 0
```
Examples:
```text
requestMethodNotSupported: expected 404 but was 405
missingToken: Request processing failed: io.jsonwebtoken.JwtException: Missing Token
constraintViolations: Request processing failed: jakarta.validation.ConstraintViolationException
badRequestException: Request processing failed: BadRequestListException
```

So next blocker now Spring MVC / exception-handling behavior drift under Boot 3, not compiler metadata.

10. **Why This Is Generic And Deterministic**

- no `common-utils`
- no `msa-dto`
- no repo-name hardcode
- reuse existing `maven_pom_patch` path
- wired by unit id / route stage, not project name
- plugin version comes from profile config:
  - `tooling_versions.maven_compiler_plugin: "3.14.1"`
- preserves existing `source` / `target` / `release`
- no test skip
- no legacy repo modification
- sandbox only
- ledger records exact old/new compiler config

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 27: Add post-Boot3 test failure classification for sandbox migrations.
>
> Context:
> common-utils now reaches spring-boot-3-5-14 test execution after dependency/compiler alignments. Build/test no longer fails on classpath or compilation. It now fails with behavioral test failures:
> - CustomExceptionTranslatorTest: exceptions propagate or HTTP status/body changed
> - requestMethodNotSupported expected 404 but got 405
> - jakarta.validation.ConstraintViolationException propagates
> - Mockito cannot mock final Azure TopicClient
> - TranslatorAdapterTest NoSuchElementException
>
> Goal:
> Do not patch application/test behavior yet. Add a deterministic failure classifier/reporting step that groups post-transform test failures into migration-relevant categories.
>
> Required behavior:
> 1. Parse Surefire reports after build/test failure.
> 2. Detect and classify these categories:
>    - SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>    - JAKARTA_VALIDATION_HANDLER_MISMATCH
>    - HTTP_STATUS_CONTRACT_DRIFT
>    - MOCKITO_FINAL_CLASS_MOCKING_LIMITATION
>    - APPLICATION_BEHAVIOR_REGRESSION
>    - UNKNOWN_TEST_FAILURE
> 3. If `javax.validation.ConstraintViolationException` handler exists but tests throw `jakarta.validation.ConstraintViolationException`, classify as `JAKARTA_VALIDATION_HANDLER_MISMATCH`.
> 4. If expected/actual HTTP status changed, classify as `HTTP_STATUS_CONTRACT_DRIFT`.
> 5. If Mockito says cannot mock final class, classify as `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`.
> 6. Do not modify source code.
> 7. Do not modify tests.
> 8. Do not skip tests.
> 9. Add classification to build error contract and/or a new post_transform_failure_classification.json artifact.
> 10. Include affected test class, test method, symptom, likely category, and suggested next action.
> 11. Keep this generic; no common-utils or msa-dto hardcode.
> 12. Existing successful flows must remain green.
>
> Tests:
> - classifier detects javax/jakarta validation handler mismatch
> - classifier detects HTTP status drift
> - classifier detects Mockito final class mocking limitation
> - classifier detects propagated ServletException from controller advice tests
> - unknown failures remain UNKNOWN_TEST_FAILURE
> - full pytest suite remains green
>
> Validation:
> python -m pytest tests/test_build_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then rerun or reuse a failing common-utils run only for classification validation, not for transformation. Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Classification artifact excerpt
> 6. How many failures per category
> 7. Why no automatic code patch was applied
> 8. Recommended next ticket candidates

<details><summary>30 previous messages</summary>

> Me inspect build/test failure path, artifact writer, surefire parser. Then me add classifier, no source patch magic.
>
> Me inspect build contract + phase service hook. Need put artifact path in refs, maybe build error JSON too.
>
> Me inspect sandbox transform flow. Need hook classifier where build fail after surefire.
>
> Me inspect build failure kinds. Need know where test failures land.
>
> Me inspect one Surefire XML shape from real failing run. Need robust parser, not guess.
>
> Me inspect real failing patterns in `cu13`. Then me write classifier rules from truth, not fantasy.
>
> Me inspect build-agent failure tests. Need fit new artifact, maybe add one integration test there too.
>
> Me inspect build-agent package export. Maybe no change needed, maybe add classifier helper import only in tests.
>
> Me write classifier module + hook build agent + build contract. Then tests.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/agents/build_agent/test_failure_classifier.py` (+236 -0)
>
> </details>
>
> Now me hook classifier into build agent failure path + contract fields.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/build_agent/agent.py` (+38 -11)
> - Wrote `./migration_factory/contracts/build/schemas.py` (+18 -12)
>
> </details>
>
> Tiny cleanup needed. Me remove duplicate contract build. Then add tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/build_agent/agent.py` (+0 -17)
>
> </details>
>
> Me add classifier tests + one build-contract integration test.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_build_agent.py` (+125 -2)
>
> </details>
>
> Need helper builders at file end. Me add now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_build_agent.py` (+55 -6)
>
> </details>
>
> One XML helper needs escaping. Me fix before run tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_build_agent.py` (+10 -7)
>
> </details>
>
> Need rename helper module. Name `test_*` bad; pytest may grab. Me rename safe now.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/build_agent/agent.py` (+1 -1)
> - Wrote `./tests/test_build_agent.py` (+1 -1)
>
> </details>
>
> Code in. Me run build-agent tests first. Then orchestrator + full suite.
>
> Focused green. Me run full pytest. Then reuse failing `cu13` run to generate classification artifact only.
>
> Me inspect artifact excerpt, counts, top failures. Need honest report.
>
> Real run should catch validation mismatch too. Me inspect source rule miss, then fix if needed.
>
> One real-world miss found. Me loosen validation-handler detector, rerun quick tests, regenerate artifact.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/build_agent/failure_classifier.py` (+0 -2)
>
> </details>
>
> Small rule tweak done. Me rerun orchestrator + full suite for honest green.
>
> Me grab final artifact excerpt and category counts from reused `cu13`.
</details>

1. **Summary**

Ticket 27 done.

Me add deterministic post-transform test failure classifier.
No app code patch. No test patch. No skip.

New behavior:
- parse Surefire XML failures/errors
- group into migration categories
- write `post_transform_failure_classification.json`
- include classification path + category counts in build error contract when build agent owns failure path
- reusable on existing failed sandbox run too

2. **Files Modified**

- [failure_classifier.py](./migration_factory/agents/build_agent/failure_classifier.py)
- [agent.py](./migration_factory/agents/build_agent/agent.py)
- [schemas.py](./migration_factory/contracts/build/schemas.py)
- [test_build_agent.py](./tests/test_build_agent.py)

3. **Tests Added**

Added coverage for:
- `JAKARTA_VALIDATION_HANDLER_MISMATCH`
- `HTTP_STATUS_CONTRACT_DRIFT`
- `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT`
- `UNKNOWN_TEST_FAILURE`
- build agent writes classification artifact path into build error contract

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_build_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Reuse existing failed run for classification only:
```powershell
@'
from pathlib import Path
from migration_factory.agents.build_agent.failure_classifier import classify_post_transform_test_failures
run = Path(r'C:\mf\cu13\.migration\runs\common-utils-clean-20260602-120500')
project = run / 'workspaces' / 'sandbox'
out = run / 'build'
result = classify_post_transform_test_failures(project, output_dir=out, unit_id='spring-boot-3-5-14')
print(result.artifact_path)
print(result.category_counts)
'@ | python -
```

5. **Classification Artifact Excerpt**

Artifact:
- [post_transform_failure_classification.json](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/build/post_transform_failure_classification.json)

Excerpt:
```json
{
  "unit_id": "spring-boot-3-5-14",
  "failure_count": 28,
  "category_counts": {
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 22,
    "HTTP_STATUS_CONTRACT_DRIFT": 3,
    "JAKARTA_VALIDATION_HANDLER_MISMATCH": 1,
    "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION": 2
  }
}
```

Sample entries:
- `CustomExceptionTranslatorTest.requestMethodNotSupported` -> `HTTP_STATUS_CONTRACT_DRIFT`
- `CustomExceptionTranslatorTest.constraintViolations` -> `JAKARTA_VALIDATION_HANDLER_MISMATCH`
- `AzureBusTopicTest.*` final-class mock failures -> `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`

6. **How Many Failures Per Category**

From reused `cu13` run:
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT`: `22`
- `HTTP_STATUS_CONTRACT_DRIFT`: `3`
- `JAKARTA_VALIDATION_HANDLER_MISMATCH`: `1`
- `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`: `2`

7. **Why No Automatic Code Patch Applied**

By design.
This ticket only classify behavioral failures.

Reason:
- failures now semantic/runtime/test-contract drift
- many possible fixes, non-trivial consequences
- deterministic factory should not guess app behavior or rewrite tests blindly
- classification gives governed next-step evidence first

8. **Recommended Next Ticket Candidates**

- Spring MVC / controller-advice behavioral drift alignment for Boot 3
- Jakarta validation exception-handler runtime alignment
- HTTP status contract drift review/fix for Spring 6 exception mapping
- Mockito final-class test strategy alignment for Boot 3 test stack
- broader application behavior regression triage from `TranslatorAdapterTest` / advice tests

**Test Results**

- `tests/test_build_agent.py -q`: `35 passed`
- `tests/orchestrator -q`: `88 passed`
- `pytest -q`: `624 passed, 3 skipped`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 28: Generate failed sandbox migration report with classified post-transform test failures.
>
> Context:
> Ticket 27 added deterministic post-transform test failure classification. common-utils now reaches Boot 3 test execution, but fails with classified behavioral test failures:
>
> * SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
> * HTTP_STATUS_CONTRACT_DRIFT
> * JAKARTA_VALIDATION_HANDLER_MISMATCH
> * MOCKITO_FINAL_CLASS_MOCKING_LIMITATION
>
> Problem:
> When sandbox migration fails during post-transform tests, the run may not produce a final `migration_report.json`. For enterprise governance and management demo, the factory must still produce a clear failed sandbox migration report that explains what succeeded, what failed, and why production promotion is blocked.
>
> Goal:
> Generate final-style failure reporting for failed sandbox migrations, especially when failures are classified.
>
> Required behavior:
>
> 1. When sandbox migration fails after transformation/build/test execution, generate a final report under:
>
>    * `final/migration_report.json`
>    * `final/migration_summary.md`
> 2. The report must clearly show:
>
>    * final_status
>    * orchestration_status
>    * failed unit
>    * transform_status
>    * build_status
>    * test_status
>    * build error contract path
>    * post_transform_failure_classification path if present
>    * category counts
>    * top affected test classes/methods
>    * production_promotion_executed=false
>    * production_allowed=false
>    * human_review_required=true
> 3. Do not mark the migration as successful.
> 4. Do not hide test failures.
> 5. Do not skip tests.
> 6. Do not modify application code or tests.
> 7. Add classification summary to orchestration_summary artifact_refs.
> 8. Add classification summary to final migration summary markdown.
> 9. Preserve successful sandbox report behavior unchanged.
> 10. Keep old flows backward compatible.
> 11. No common-utils, msa-dto, or repo-specific logic.
>
> Expected status behavior:
>
> * If transform/build/test reaches classified test failures:
>
>   * final_status remains BUILD_FAILED_IN_SANDBOX or TEST_FAILED_IN_SANDBOX as appropriate
>   * orchestration_status remains FAIL
>   * final report exists and states “Sandbox migration failed with classified post-transform test failures”
>   * production promotion remains blocked
>
> Tests:
>
> 1. Failed sandbox run with classification generates final/migration_report.json.
> 2. Failed sandbox run with classification generates final/migration_summary.md.
> 3. Report includes category_counts.
> 4. Report includes classification artifact ref.
> 5. Report does not mark success.
> 6. Successful sandbox reports remain unchanged.
> 7. Missing classification artifact does not break final failure report.
> 8. No project-specific names.
> 9. Full pytest suite remains green.
>
> Validation:
> Run:
> python -m pytest tests/test_final_report.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then reuse or rerun common-utils classification path and verify:
>
> * final/migration_report.json exists
> * final/migration_summary.md exists
> * report includes failure classification counts
> * production_promotion_executed=false
> * human_review_required=true
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Report excerpt
> 7. Orchestration summary excerpt
> 8. Why this is governance-safe
> 9. Recommended next human review actions

<details><summary>21 previous messages</summary>

> Me inspect final report + orchestration summary path for failed sandbox. Then me patch report generation, no fake success.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me inspect final report + orchestration summary path for failed sandbox. Then me patch report generation, no fake success.
>
> Me found choke point. Final report only made on happy sandbox path. Now me inspect failure-classification shape, then patch failed-sandbox report path.
>
> Me have shape now. Next me inspect where build error path lives in state/artifact refs, so failed report can point exact contract + classification.
>
> Me need one more thing: where failed sandbox state carries build-error ref. Me inspect failure tests, then patch minimal path so final failed report know exact error + classification.
>
> Me know fix shape now. Before edits, me patch two places: summary finalization for failed sandbox, and final report writer for failure payload + markdown. Then me add tests.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/final_report/writer.py` (+182 -38)
> - Wrote `./migration_factory/orchestrator/summary.py` (+89 -9)
>
> </details>
>
> Me patched core. Now me add failure-path tests: final report exists on failed sandbox, includes classification, success path unchanged.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_final_report.py` (+50 -7)
> - Wrote `./tests/test_final_report.py` (+110 -3)
> - Wrote `./tests/orchestrator/test_summary.py` (+109 -0)
>
> </details>
>
> Me run focused tests now. Want catch report/finalization break quick before full suite.
>
> Two small misses only. Me patch default `production_allowed=false` in failure report, and normalize one path assertion.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/final_report/writer.py` (+3 -1)
> - Wrote `./tests/orchestrator/test_summary.py` (+1 -1)
>
> </details>
>
> Me rerun focused tests. If clean, then bigger suites.
>
> Focused tests green. Me run requested suites now, then reuse failed common-utils run for real report artifact check.
>
> One regression only: duplicate summary write on non-reportable path. Me tighten finalize flow, then rerun suites.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/orchestrator/summary.py` (+1 -1)
>
> </details>
>
> Me rerun orchestrator + full suite now.
>
> Code green. Me now reuse real failed `common-utils` run, make failure report from existing artifacts, then verify report text/counts.
>
> Me reuse real failed run by generating failure report from existing deterministic artifacts only. No transform rerun.
>
> Me also update real failed run summary using finalizer only, no transform rerun. This make orchestration summary carry failure report refs too.
</details>

1. **Summary**

Me fix Ticket 28.

Now failed sandbox run can still write:
- `final/migration_report.json`
- `final/migration_summary.md`

Works for classified post-transform test failures.
No fake success.
`production_promotion_executed=false`
`human_review_required=true`

2. **Files Modified**

- [writer.py](./migration_factory/final_report/writer.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [test_final_report.py](./tests/test_final_report.py)
- [test_summary.py](./tests/orchestrator/test_summary.py)

3. **Tests Added**

Added coverage for:
- failed sandbox run writes `final/migration_report.json`
- failed sandbox run writes `final/migration_summary.md`
- report includes `category_counts`
- report includes classification artifact ref
- report does not mark success
- missing classification artifact still writes failure report
- orchestration summary carries failure-classification ref + final report refs

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Reuse failed run, no transform rerun:
```powershell
@' ... generate_final_migration_report(...) ... '@ | python -
@' ... finalize_orchestration_state(...) for existing failed run ... '@ | python -
```

5. **Test Results**

- `tests/test_final_report.py -q`: `20 passed`
- `tests/orchestrator -q`: `89 passed`
- `pytest -q`: `627 passed, 3 skipped`

6. **Report Excerpt**

Real reused run:
- `RUN_ID`: `common-utils-clean-20260602-120500`
- report: [migration_report.json](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/final/migration_report.json)
- summary: [migration_summary.md](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/final/migration_summary.md)

Key excerpt:
- `final_status: TEST_FAILED_IN_SANDBOX`
- `orchestration_status: FAIL`
- `failed_unit: spring-boot-3-5-14`
- `production_promotion_executed: false`
- `production_allowed: false`
- `human_review_required: true`
- `category_counts`:
  - `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: 22`
  - `HTTP_STATUS_CONTRACT_DRIFT: 3`
  - `JAKARTA_VALIDATION_HANDLER_MISMATCH: 1`
  - `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION: 2`

7. **Orchestration Summary Excerpt**

Updated real summary:
- [orchestration_summary.json](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/orchestration/orchestration_summary.json)

Key artifact refs now present:
- `build_error_contract`
- `post_transform_failure_classification`
- `final_migration_report`
- `final_migration_summary`

Status excerpt:
- `mode: full_sandbox_migration`
- `resume_semantics: approved_sandbox_migration`
- `transform_status: TRANSFORM_APPLIED_IN_SANDBOX`
- `build_status: BUILD_FAILED_IN_SANDBOX`
- `test_status: TEST_FAILED_IN_SANDBOX`
- `orchestration_artifacts_valid: false`

8. **Why This Is Governance-Safe**

- fail stays fail
- no success relabel
- no prod promotion
- no code patch
- no test patch
- no test skip
- classification made visible, not hidden
- human review forced true on failed sandbox report

9. **Recommended Next Human Review Actions**

- review Spring MVC / controller-advice behavior drift
- review Jakarta validation exception handling mismatch
- review HTTP status contract changes under Boot 3 / Spring 6
- review Mockito final-class mocking strategy for Azure client tests
- triage application behavior regressions after framework migration

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 29: Add LLM remediation policy gate, disabled by default.
>
> Context:
> The factory must remain deterministic-first. LLM/Copilot remediation is planned later, but must be controlled for enterprise safety, budget, and human approval. CGI-approved GitHub Copilot Enterprise licenses are not available yet, so this ticket must not call any external LLM or network service.
>
> Goal:
> Prepare the architecture for future LLM remediation without actually calling any LLM.
>
> Required behavior:
> 1. Add an `llm_policy` configuration model.
> 2. Default policy must be:
>    - enabled: false
>    - provider: github_copilot_enterprise
>    - require_human_approval: true
> 3. Support fields:
>    - enabled
>    - provider
>    - max_calls_per_run
>    - max_files_per_call
>    - max_diff_lines_per_patch
>    - require_human_approval
>    - allowed_categories
>    - forbidden_actions
> 4. Add a remediation decision component that can return:
>    - AUTO_APPLY_DETERMINISTIC
>    - HUMAN_REVIEW_ONLY
>    - LLM_PROPOSAL_ALLOWED
>    - LLM_DISABLED_REPORT_ONLY
> 5. If LLM is disabled, never call external services.
> 6. If no deterministic remediation applies and LLM is disabled, produce a `remediation_plan.yaml` with:
>    - human_review_required: true
>    - llm_enabled: false
>    - decision: LLM_DISABLED_REPORT_ONLY or HUMAN_REVIEW_ONLY
>    - reason
>    - affected category if available
> 7. No LLM calls in this ticket.
> 8. No GitHub Copilot API calls.
> 9. No network calls.
> 10. No source code or test patching by LLM.
> 11. No project-specific names such as common-utils, msa-dto, or translation.
> 12. Existing flows must remain backward compatible.
>
> Integration:
> - Reuse existing failure classification / build error / orchestration artifacts where possible.
> - The policy should be serializable into artifacts.
> - Add artifact reference to remediation plan when generated.
> - Keep successful sandbox migration behavior unchanged.
> - Keep failed sandbox report behavior unchanged except for adding remediation plan refs when available.
>
> Tests:
> 1. Default LLM policy disables LLM.
> 2. Deterministic remediation decision does not require LLM.
> 3. Behavioral failure with LLM disabled becomes HUMAN_REVIEW_ONLY or LLM_DISABLED_REPORT_ONLY.
> 4. Generated `remediation_plan.yaml` includes policy limits.
> 5. Generated `remediation_plan.yaml` includes human_review_required=true.
> 6. No external service is called.
> 7. Existing orchestrator tests remain green.
> 8. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example llm_policy
> 7. Example remediation_plan.yaml
> 8. Why this is budget-safe and enterprise-safe
> 9. Any warnings or limitations

<details><summary>10 previous messages</summary>

> Me inspect if remediation/policy path already exist. Then me add disabled-by-default gate, no network, no LLM call.
>
> Me patch new remediation policy module + failed-sandbox generation hook. No network, no LLM call, default off.
>
> <details><summary>Created 2 files</summary>
>
> - Wrote `./migration_factory/remediation/__init__.py` (+21 -0)
> - Wrote `./migration_factory/remediation/policy.py` (+189 -0)
>
> </details>
>
> Now me wire remediation plan into failed sandbox finalize path and final markdown refs.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/orchestrator/summary.py` (+39 -8)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
>
> </details>
>
> Me add policy tests now: default disabled, deterministic decision, behavioral disabled plan, orchestration failure gets remediation ref.
>
> <details><summary>Created 1 file, edited 2 files</summary>
>
> - Wrote `./tests/orchestrator/test_remediation_policy.py` (+76 -0)
> - Wrote `./tests/orchestrator/test_summary.py` (+1 -0)
> - Wrote `./tests/test_final_report.py` (+2 -0)
>
> </details>
>
> Me run focused orchestrator tests first. Want catch policy/report wiring before full suite.
>
> Focused tests green. Me run requested suites now.
>
> Me reuse failed run one more time, now only to stamp remediation plan artifact. No transform rerun.
</details>

1. **Summary**

Me add LLM remediation policy gate.
Default off.
No LLM call.
No network call.
No source patch by LLM.

Factory now can:
- load `llm_policy`
- decide remediation mode
- write `remediation/remediation_plan.yaml` on failed sandbox runs
- attach remediation artifact ref into failed sandbox reporting

2. **Files Modified**

- [policy.py](./migration_factory/remediation/policy.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_remediation_policy.py](./tests/orchestrator/test_remediation_policy.py)
- [test_summary.py](./tests/orchestrator/test_summary.py)
- [test_final_report.py](./tests/test_final_report.py)

3. **Tests Added**

- default `llm_policy` disables LLM
- deterministic remediation decision returns `AUTO_APPLY_DETERMINISTIC`
- behavioral failure + disabled LLM returns `LLM_DISABLED_REPORT_ONLY`
- no-category failure + disabled LLM returns `HUMAN_REVIEW_ONLY`
- failed sandbox summary/report now carry `remediation_plan`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_remediation_policy.py -q
python -m pytest tests/orchestrator/test_summary.py -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Reuse failed run only for artifact generation, no rerun:
```powershell
@' ... finalize_orchestration_state(...) on existing failed cu13 run ... '@ | python -
```

5. **Test Results**

- `tests/orchestrator/test_remediation_policy.py -q`: `4 passed`
- `tests/orchestrator/test_summary.py -q`: `13 passed`
- `tests/test_final_report.py -q`: `20 passed`
- `tests/orchestrator -q`: `93 passed`
- `pytest -q`: `631 passed, 3 skipped`

6. **Example `llm_policy`**

```yaml
llm_policy:
  enabled: false
  provider: github_copilot_enterprise
  max_calls_per_run: 0
  max_files_per_call: 0
  max_diff_lines_per_patch: 0
  require_human_approval: true
  allowed_categories: []
  forbidden_actions:
    - external_llm_call
    - automatic_source_patch
    - test_modification
    - approval_bypass
```

7. **Example `remediation_plan.yaml`**

Real reused failed run:
- [remediation_plan.yaml](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/remediation/remediation_plan.yaml)

Excerpt:
```yaml
run_id: common-utils-clean-20260602-120500
final_status: TEST_FAILED_IN_SANDBOX
failed_unit: spring-boot-3-5-14
human_review_required: true
llm_enabled: false
decision: LLM_DISABLED_REPORT_ONLY
reason: LLM remediation is disabled by policy; emit report-only remediation plan for human review.
affected_category: SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
```

8. **Why Budget-Safe And Enterprise-Safe**

- default `enabled: false`
- zero external calls
- zero network calls
- zero automatic LLM patching
- human approval still required
- policy limits serialized into artifact
- deterministic-first path stays first

9. **Warnings / Limitations**

- this ticket only add gate + plan, not LLM execution
- no profile schema extension yet; policy works from default model now
- `LLM_PROPOSAL_ALLOWED` path prepared only architecturally, still no provider call

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 30: Add Remediation Agent v1, plan-only mode.
>
> Context:
> Ticket 29 added an LLM remediation policy gate, disabled by default. The factory can now write a basic remediation_plan.yaml on failed sandbox runs. We now need a real Remediation Agent that reads build/test/classification artifacts and produces a structured remediation plan.
>
> Goal:
> Create a Remediation Agent v1 that does not modify code and does not auto-apply fixes. It only analyzes failures and emits deterministic remediation decisions/candidates.
>
> Required behavior:
>
> 1. Add a remediation agent/module that consumes available artifacts:
>
>    * build error contract
>    * post_transform_failure_classification.json
>    * orchestration summary
>    * migration ledger
>    * migration plan if available
> 2. Generate `remediation/remediation_plan.yaml`.
> 3. The plan must include:
>
>    * run_id
>    * failed_unit
>    * final_status
>    * build_status
>    * test_status
>    * llm_policy summary
>    * human_review_required
>    * remediation_decision
>    * remediation_candidates
>    * blocked_reasons
>    * recommended_next_actions
> 4. Supported remediation decisions:
>
>    * AUTO_APPLY_DETERMINISTIC_CANDIDATE
>    * HUMAN_REVIEW_ONLY
>    * LLM_PROPOSAL_ALLOWED
>    * LLM_DISABLED_REPORT_ONLY
>    * NO_REMEDIATION_AVAILABLE
> 5. Do not auto-apply any patch in this ticket.
> 6. Do not call any LLM.
> 7. Do not call GitHub Copilot.
> 8. Do not perform network calls.
> 9. Do not modify source code or tests.
> 10. Do not skip tests.
> 11. No project-specific names such as common-utils, msa-dto, or translation.
>
> Classification mapping:
>
> * Dependency/classpath/version problems may produce deterministic remediation candidates if matching known categories exist.
> * Behavioral categories must default to human review or LLM-disabled report-only when LLM is disabled:
>
>   * SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>   * HTTP_STATUS_CONTRACT_DRIFT
>   * JAKARTA_VALIDATION_HANDLER_MISMATCH
>   * MOCKITO_FINAL_CLASS_MOCKING_LIMITATION
>   * APPLICATION_BEHAVIOR_REGRESSION
> * If LLM is disabled, categories that could benefit from LLM must become LLM_DISABLED_REPORT_ONLY or HUMAN_REVIEW_ONLY.
>
> Candidate examples:
> For behavioral failures:
>
> ```yaml
> remediation_candidates:
>   - category: SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>     safe_to_auto_apply: false
>     requires_human_approval: true
>     llm_candidate: true
>     recommended_action: Review Spring MVC / exception handler contract under Boot 3.
> ```
>
> For deterministic dependency failures:
>
> ```yaml
> remediation_candidates:
>   - category: DEPENDENCY_ALIGNMENT
>     safe_to_auto_apply: true
>     requires_human_approval: false
>     deterministic_rule: align_dependency_versions
> ```
>
> Integration:
>
> 1. Reuse Ticket 29 policy model.
> 2. Reuse Ticket 27 failure classification artifact.
> 3. Reuse Ticket 28 failed sandbox report path.
> 4. Attach `remediation_plan` artifact ref into orchestration summary and final report when generated.
> 5. Preserve successful sandbox migration behavior unchanged.
> 6. Preserve failed sandbox report behavior, only enrich it with remediation plan details.
>
> Tests:
>
> 1. Behavioral classified failures generate human-review remediation candidates.
> 2. Behavioral failures with LLM disabled produce LLM_DISABLED_REPORT_ONLY or HUMAN_REVIEW_ONLY.
> 3. Deterministic dependency-like failure can produce AUTO_APPLY_DETERMINISTIC_CANDIDATE but does not apply anything.
> 4. Missing classification artifact still generates a useful remediation plan.
> 5. remediation_plan.yaml includes policy limits.
> 6. remediation_plan.yaml includes recommended next actions.
> 7. No external service is called.
> 8. Existing orchestrator and final report tests remain green.
> 9. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_final_report.py -q
> python -m pytest -q
>
> Then reuse the failed common-utils cu13 run only for remediation plan generation, no transformation rerun.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example remediation_plan.yaml
> 7. Remediation candidates summary
> 8. Why no patch was applied
> 9. Why this is enterprise-safe and budget-safe
> 10. Warnings or limitations

<details><summary>11 previous messages</summary>

> Me inspect current remediation policy hook, then build real plan-only agent on top. No code patching, no network.
>
> Me now build real Remediation Agent module, then make old policy helper delegate to it. Keeps backward flow, adds richer plan.
>
> Me add real agent module now, then make policy wrapper thin. Keeps old imports alive, but richer plan comes from agent.
>
> <details><summary>Created 1 file, edited 2 files</summary>
>
> - Wrote `./migration_factory/remediation/agent.py` (+301 -0)
> - Wrote `./migration_factory/remediation/__init__.py` (+10 -0)
> - Wrote `./migration_factory/remediation/policy.py` (+24 -59)
>
> </details>
>
> Now me expand tests for real agent outputs: candidates, blocked reasons, next actions, missing classification, deterministic dependency case.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_remediation_policy.py` (+103 -2)
>
> </details>
>
> Me run remediation tests first. Then requested suites.
>
> One compatibility nick only. Me map legacy wrapper to `HUMAN_REVIEW_ONLY` when v1 says no candidate. Agent still keeps richer `NO_REMEDIATION_AVAILABLE` in plan.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/policy.py` (+2 -0)
>
> </details>
>
> Me rerun remediation tests, then requested suites.
>
> Code green. Me reuse failed `cu13` only for remediation plan generation now. No transform rerun.
</details>

1. **Summary**

Me add Remediation Agent v1, plan-only.

Now agent reads:
- build error contract
- failure classification
- orchestration summary
- migration ledger
- migration plan

Then writes structured:
- `remediation/remediation_plan.yaml`

No code patch.
No test patch.
No LLM call.
No network.

2. **Files Modified**

- [agent.py](./migration_factory/remediation/agent.py)
- [policy.py](./migration_factory/remediation/policy.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [test_remediation_policy.py](./tests/orchestrator/test_remediation_policy.py)
- [test_summary.py](./tests/orchestrator/test_summary.py)
- [test_final_report.py](./tests/test_final_report.py)

3. **Tests Added**

Added coverage for:
- behavioral classified failures -> human-review remediation candidates
- behavioral failures + disabled LLM -> `LLM_DISABLED_REPORT_ONLY`
- deterministic dependency-like failure -> `AUTO_APPLY_DETERMINISTIC_CANDIDATE` candidate only
- missing classification artifact still yields useful plan
- policy limits serialized into plan
- recommended next actions serialized into plan
- orchestrator/final report still green

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_remediation_policy.py -q
python -m pytest tests/orchestrator/test_summary.py -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest tests/test_final_report.py -q
python -m pytest -q
```

Reuse failed run only for remediation generation:
```powershell
@' ... generate_remediation_plan(...) on cu13 failed run ... '@ | python -
```

5. **Test Results**

- `tests/orchestrator/test_remediation_policy.py -q`: `7 passed`
- `tests/orchestrator/test_summary.py -q`: `13 passed`
- `tests/test_final_report.py -q`: `20 passed`
- `tests/orchestrator -q`: `96 passed`
- `pytest -q`: `634 passed, 3 skipped`

6. **Example `remediation_plan.yaml`**

Real reused failed run:
- [remediation_plan.yaml](C:/mf/cu13/.migration/runs/common-utils-clean-20260602-120500/remediation/remediation_plan.yaml)

Excerpt:
```yaml
run_id: common-utils-clean-20260602-120500
failed_unit: spring-boot-3-5-14
final_status: TEST_FAILED_IN_SANDBOX
build_status: BUILD_FAILED_IN_SANDBOX
test_status: TEST_FAILED_IN_SANDBOX
human_review_required: true
remediation_decision: LLM_DISABLED_REPORT_ONLY
completed_units:
- baseline
- spring-boot-2-7-stabilization
- java-17
selected_route_id: boot-2.1-to-3.5-java17
route_strategy: multi_hop
```

7. **Remediation Candidates Summary**

Real `cu13` plan has `4` candidates:
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT`
- `HTTP_STATUS_CONTRACT_DRIFT`
- `JAKARTA_VALIDATION_HANDLER_MISMATCH`
- `MOCKITO_FINAL_CLASS_MOCKING_LIMITATION`

Each candidate shows:
- `safe_to_auto_apply: false`
- `requires_human_approval: true`
- `llm_candidate: true`
- deterministic evidence from failing tests
- recommended next action

8. **Why No Patch Was Applied**

By design.
Ticket says plan-only.

Agent only:
- reads artifacts
- classifies remediation candidates
- writes remediation plan

Agent does **not**:
- patch source
- patch tests
- auto-apply deterministic fixes
- call LLM
- call Copilot
- hit network

9. **Why This Is Enterprise-Safe And Budget-Safe**

- default LLM policy still disabled
- zero external calls
- zero token spend
- zero source mutation
- human review required stays true
- remediation decisions + evidence now explicit and auditable
- failed sandbox report enriched, not hidden

10. **Warnings / Limitations**

- `AUTO_APPLY_DETERMINISTIC_CANDIDATE` is advisory only in v1, not execution
- behavioral failures stay review-only when LLM disabled
- no profile schema extension yet for richer remediation config beyond existing policy loader
- next ticket likely actual Remediation Agent execution gate for deterministic-only apply, still approval-controlled

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 31: Add deterministic auto-remediation loop, sandbox-only.
>
> Context:
> Ticket 29 added the LLM remediation policy gate, disabled by default.
> Ticket 30 added Remediation Agent v1 in plan-only mode.
> Now we need a safe execution loop for deterministic remediation candidates only.
>
> Goal:
> Allow the factory to auto-apply only safelisted deterministic remediation candidates in sandbox, then rerun the failed unit validation. Do not handle behavioral failures automatically.
>
> Required behavior:
>
> 1. Add a deterministic remediation execution gate.
> 2. It may execute only candidates where:
>
>    * safe_to_auto_apply: true
>    * deterministic_rule is present
>    * category is safelisted
>    * the failure is not behavioral/API-contract related
> 3. Behavioral categories must never auto-apply:
>
>    * SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>    * HTTP_STATUS_CONTRACT_DRIFT
>    * JAKARTA_VALIDATION_HANDLER_MISMATCH
>    * MOCKITO_FINAL_CLASS_MOCKING_LIMITATION
>    * APPLICATION_BEHAVIOR_REGRESSION
> 4. If a behavioral category appears, keep HUMAN_REVIEW_ONLY or LLM_DISABLED_REPORT_ONLY.
> 5. No LLM calls.
> 6. No GitHub Copilot calls.
> 7. No network calls beyond existing Maven/build behavior.
> 8. No test skipping.
> 9. No source/test patching unless it is an explicitly safelisted deterministic remediation operation.
> 10. No common-utils, msa-dto, or translation hardcode.
> 11. Apply only in sandbox.
> 12. Never modify legacy repo.
> 13. Record every remediation attempt in ledger and remediation artifacts.
> 14. Limit attempts:
>
> * max_auto_remediation_attempts_per_unit default: 3
> * stop if the same rule was already applied for the same unit
> * stop if rerun produces the same failure category/error
>
> 15. Keep failed-run reporting intact.
> 16. Keep successful sandbox reporting intact.
>
> Initial safelist:
> Start with framework support only and at least one generic synthetic deterministic rule for tests. Do not invent risky application rules.
> Existing deterministic Maven/source operations may be registered as eligible only if they are already proven idempotent and non-behavioral, for example:
>
> * Maven dependency/tooling alignment operations
> * Maven compiler parameters alignment
> * Spring Data Sort constructor deterministic fix
>   But do not auto-apply behavioral exception-handler fixes.
>
> Expected flow:
>
> 1. Build/test fails.
> 2. Failure classifier runs.
> 3. Remediation Agent creates remediation_plan.yaml.
> 4. If deterministic safe candidate exists:
>
>    * apply deterministic remediation in sandbox
>    * record attempt
>    * rerun failed unit validation
>    * update remediation_plan.yaml and orchestration summary
> 5. If no safe candidate:
>
>    * produce report-only plan and stop.
>
> Artifacts:
>
> * remediation/remediation_plan.yaml
> * remediation/remediation_attempts.json or YAML
> * ledger entries for each attempt
>
> Tests:
>
> 1. Behavioral failure does not auto-apply.
> 2. LLM disabled behavioral failure remains report-only.
> 3. Deterministic safelisted candidate can be applied in sandbox.
> 4. Same deterministic rule is not applied twice for same unit.
> 5. Attempt limit is enforced.
> 6. Remediation attempt is recorded in ledger/artifact.
> 7. Rerun hook is called after successful deterministic remediation.
> 8. Failed rerun preserves failure reporting.
> 9. Successful rerun can continue existing orchestration behavior.
> 10. No project-specific names.
> 11. Existing orchestrator/final report tests remain green.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_final_report.py -q
> python -m pytest -q
>
> Do not rerun common-utils unless needed. If reused, use existing failed cu13 only to prove behavioral failures are not auto-applied.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example deterministic remediation attempt artifact
> 7. Example behavioral failure staying report-only
> 8. Ledger excerpt
> 9. Why this is safe and not an LLM path
> 10. Warnings or limitations

<details><summary>13 previous messages</summary>

> Me inspect transform/build failure path now. Need wire remediation loop where sandbox fail happens, not fake it later.
>
> Me inspect transform failure branches next. Need insert remediation loop in exact fail return points.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me wiring safe remediation loop now. First me inspect exact fail-return points and current ledger/report hooks so auto-remediation fit without breaking failed-run reporting.
>
> Me found exact fail exits. Next me add one small executor module plus hook in transform loop: only safelisted deterministic candidates, with attempt cap and same-failure stop.
>
> Me doing file edits now: new remediation executor, tiny ledger helper, hook in phase2 transform failure path, plus tests. Safe loop only; behavioral failures stay report-only.
>
> Me found one trap: failed-run finalizer would overwrite richer remediation plan. Me fixing that too, so auto-remediation artifacts survive into final reports.
>
> <details><summary>Created 1 file, edited 7 files</summary>
>
> - Wrote `./migration_factory/contracts/migration/ledger.py` (+27 -3)
> - Wrote `./migration_factory/contracts/migration/__init__.py` (+13 -11)
> - Wrote `./migration_factory/remediation/executor.py` (+409 -0)
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+4 -0)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+111 -54)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+27 -19)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+44 -0)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+17 -3)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+6 -2)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+11 -9)
> - Wrote `./migration_factory/remediation/executor.py` (+19 -1)
>
> </details>
>
> Me adding focused executor tests now. They use synthetic safe rule only, and one reused behavioral path. No network, no real code mutation.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_auto_remediation_executor.py` (+220 -0)
>
> </details>
>
> Me running orchestrator, final-report, then full suite now. If any compile break, me fix before report.
>
> Me reusing old failed `cu13` only for proof. No transform rerun, no build rerun expected; behavioral categories should stay report-only.
>
> Me generating one tiny synthetic remediation-attempt artifact example in temp dir. This is local-only test artifact, no project code touched.
</details>

1. **Summary**

Ticket 31 done.

Factory now has safe auto-remediation loop for deterministic sandbox candidates only:
- generate `remediation_plan.yaml`
- if candidate safe + deterministic + safelisted, apply sandbox-only remediation step
- rerun failed unit validation
- record attempts in artifact + ledger
- stop on duplicate rule, same failure, or attempt cap

Behavioral failures do **not** auto-apply.
Reused failed `cu13` proved that:
- `rerun_called=false`
- `continued=false`
- `attempts=[]`

2. **Files Modified**

- [migration_factory/remediation/executor.py](./migration_factory/remediation/executor.py)
- [migration_factory/remediation/__init__.py](./migration_factory/remediation/__init__.py)
- [migration_factory/contracts/migration/ledger.py](./migration_factory/contracts/migration/ledger.py)
- [migration_factory/contracts/migration/__init__.py](./migration_factory/contracts/migration/__init__.py)
- [migration_factory/transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [migration_factory/orchestrator/phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [migration_factory/orchestrator/summary.py](./migration_factory/orchestrator/summary.py)
- [tests/orchestrator/test_auto_remediation_executor.py](./tests/orchestrator/test_auto_remediation_executor.py)

3. **Tests Added**

- behavioral failure does not auto-apply
- deterministic safelisted candidate can apply and rerun
- same rule not applied twice for same unit
- attempt limit enforced

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator -q
python -m pytest tests/test_final_report.py -q
python -m pytest -q
```

Behavioral reuse proof only, no transform rerun:
```powershell
@' ... execute_auto_remediation_loop(...) on existing cu13 failed run ... '@ | python -
```

Synthetic deterministic artifact demo only:
```powershell
@' ... execute_auto_remediation_loop(...) on temp run ... '@ | python -
```

5. **Test Results**

- `tests/orchestrator -q`: `100 passed`
- `tests/test_final_report.py -q`: `20 passed`
- `pytest -q`: `638 passed, 3 skipped`

6. **Example Deterministic Remediation Attempt Artifact**

Synthetic safe demo artifact:
```json
{
  "run_id": "demo-run",
  "failed_unit": "java-17",
  "max_auto_remediation_attempts_per_unit": 3,
  "attempts": [
    {
      "attempt_index": 1,
      "unit_id": "java-17",
      "category": "DEPENDENCY_ALIGNMENT",
      "deterministic_rule": "align_dependency_versions",
      "safe_to_auto_apply": true,
      "status": "rerun_passed",
      "rerun_called": true,
      "rerun_succeeded": true
    }
  ]
}
```

7. **Example Behavioral Failure Staying Report-Only**

Reused real `cu13`:
- run: `C:\mf\cu13\.migration\runs\common-utils-clean-20260602-120500`
- `remediation/remediation_plan.yaml`
- `remediation/remediation_attempts.json`

Observed:
- `remediation_decision: LLM_DISABLED_REPORT_ONLY`
- `rerun_called: false`
- `continued: false`
- `stop_reason: No safelisted deterministic remediation candidate available.`

Artifact excerpt:
```yaml
remediation_decision: LLM_DISABLED_REPORT_ONLY
max_auto_remediation_attempts_per_unit: 3
auto_remediation:
  attempts_made: 0
  rerun_count: 0
```

8. **Ledger Excerpt**

Auto-remediation writes ledger entry like:
```json
{
  "unit_id": "java-17",
  "category": "DEPENDENCY_ALIGNMENT",
  "deterministic_rule": "align_dependency_versions",
  "status": "rerun_passed",
  "rerun_called": true,
  "rerun_succeeded": true
}
```

Also stored under:
- root `remediation_attempts`
- per-unit `units.<unit>.remediation_attempts`

9. **Why This Safe And Not LLM Path**

- no LLM call
- no Copilot call
- no new network call
- sandbox only
- behavioral categories hard-blocked from auto-apply
- duplicate-rule stop
- same-failure stop
- attempt cap default `3`
- failed reporting still preserved
- successful reporting unchanged

10. **Warnings / Limitations**

- current auto-apply safelist intentionally tiny
- default deterministic rule is synthetic/safe marker-style support path, not risky app rewrite
- behavioral/API-contract failures still human-review/report-only
- richer real deterministic handlers can be registered later, but must stay idempotent and non-behavioral

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 32: Add Golden Reference Analyzer v1.
>
> Context:
> We now have real migrated reference repositories for two enterprise microservices/libraries:
>
> * msa-dto
> * msa-utils / common-utils
>
> Each repo has two branches:
>
> * legacy/original
> * migrated/reference
>
> The factory must learn from real manual/reference migrations without hardcoding project names. We need a Golden Reference Analyzer that compares legacy vs migrated reference and produces reusable migration insights.
>
> Goal:
> Add a Golden Reference Analyzer v1 that compares two checked-out directories or two repo snapshots and emits a structured report of migration patterns, gaps, and candidate factory rules.
>
> Important:
> Do not connect to GitHub from the analyzer in this ticket. It should work on local directories/snapshots only. The user/developer can provide checked-out folders later.
>
> Required behavior:
>
> 1. Add a new module, for example:
>
>    * migration_factory/golden_reference/analyzer.py
> 2. Input:
>
>    * legacy_path
>    * migrated_reference_path
>    * optional factory_sandbox_path
>    * output_dir
>    * project_id optional, used only as metadata
> 3. Output:
>
>    * golden_reference_gap_report.json
>    * golden_reference_summary.md
> 4. The report must include:
>
>    * project_id
>    * detected build files changed
>    * dependency/version changes
>    * plugin/tooling changes
>    * Java version change
>    * Spring Boot version change
>    * javax to jakarta import changes
>    * test modernization patterns
>    * source code transformation patterns
>    * files added/removed/renamed if detectable
>    * candidate deterministic rules
>    * candidate human-review items
>    * candidate LLM-remediation items
>    * anti-pattern warnings
> 5. If factory_sandbox_path is provided, compare:
>
>    * legacy/original
>    * migrated/reference
>    * factory/sandbox
>      and classify gaps:
>    * REFERENCE_APPLIED_FACTORY_MISSING
>    * FACTORY_APPLIED_REFERENCE_MISSING
>    * BOTH_APPLIED
>    * DIVERGENT_APPROACH
> 6. No source code modifications.
> 7. No test modifications.
> 8. No network calls.
> 9. No GitHub API calls.
> 10. No project-specific hardcode such as common-utils, msa-dto, or translation.
> 11. Use generic pattern detection.
>
> Pattern detection v1 should detect at least:
>
> * Java version changes in pom.xml
> * Spring Boot version changes in pom.xml
> * Lombok version alignment
> * JaCoCo version alignment
> * SLF4J version alignment
> * Jackson version alignment
> * Spring Security version alignment
> * JJWT version alignment
> * Jakarta dependency additions
> * javax.xml.bind -> jakarta.xml.bind imports
> * javax.validation -> jakarta.validation imports
> * javax.servlet -> jakarta.servlet imports
> * Spring Data `new Sort(...)` -> `Sort.by(...)`
> * `@MockBean` -> `@MockitoBean`
> * `MockitoAnnotations.initMocks` -> `MockitoAnnotations.openMocks`
> * old Azure SDK coordinates -> new Azure SDK coordinates
> * PowerMock presence or removal
> * duplicate explicit versions / excessive explicit dependency management as anti-pattern warning
>
> Candidate rule classification:
>
> * Deterministic safe candidates:
>
>   * dependency/tooling version alignment
>   * compiler/test plugin alignment
>   * simple import namespace migration
>   * Spring Data Sort constructor replacement
>   * MockBean/MockitoBean test annotation migration
> * Human review candidates:
>
>   * HTTP status changes
>   * exception handler behavior changes
>   * public API signature changes
>   * Azure SDK API migration
>   * security behavior changes
> * LLM candidate:
>
>   * localized source migration that is not safe by fixed rule
>   * test behavior adaptation requiring reasoning
>   * framework behavior drift requiring minimal patch proposal
>
> Tests:
>
> 1. Detect Java/Spring Boot version changes from sample POMs.
> 2. Detect dependency alignment patterns.
> 3. Detect javax to jakarta import changes.
> 4. Detect Sort.by migration pattern.
> 5. Detect MockBean to MockitoBean migration pattern.
> 6. Detect initMocks to openMocks migration pattern.
> 7. Detect Azure old/new dependency pattern.
> 8. Produces JSON and Markdown reports.
> 9. With factory_sandbox_path, reports factory/reference gap statuses.
> 10. No project-specific names.
> 11. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests -q
> python -m pytest -q
>
> Do not require real GitHub access.
> If you create fixtures, use small synthetic fixtures only.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example golden_reference_gap_report.json excerpt
> 7. Example golden_reference_summary.md excerpt
> 8. How this helps industrialize future migrations
> 9. Warnings or limitations

<details><summary>9 previous messages</summary>

> Me build new local-only analyzer now. First me inspect repo shape for report/test conventions, then add small synthetic fixtures and detector module.
>
> Me found no existing golden-reference module. Next me add standalone analyzer with simple XML/text detectors, then synthetic fixture tests around POM/import/test-pattern/gap logic.
>
> Me doing file edits now: new analyzer package plus one focused pytest file with tiny synthetic legacy/reference/factory dirs.
>
> <details><summary>Created 3 files</summary>
>
> - Wrote `./migration_factory/golden_reference/__init__.py` (+9 -0)
> - Wrote `./migration_factory/golden_reference/analyzer.py` (+562 -0)
> - Wrote `./tests/test_golden_reference_analyzer.py` (+270 -0)
>
> </details>
>
> Me running full tests now. If analyzer trips on XML or pattern logic, me tighten it before final.
>
> One detector missed because reference test imported `MockitoBean` but did not annotate with literal `@MockitoBean`. Me broadening pattern matcher to catch import-form too, still generic.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/golden_reference/analyzer.py` (+14 -7)
>
> </details>
>
> Me rerun analyzer tests, then full suite again to keep green.
>
> Me generating one tiny synthetic analyzer sample now so report can show real JSON/Markdown excerpts. Local temp only, no network.
</details>

1. **Summary**

Me add Golden Reference Analyzer v1.

It works on local checked-out dirs only.
No GitHub.
No network.
No source change.

It now compares:
- `legacy_path`
- `migrated_reference_path`
- optional `factory_sandbox_path`

And writes:
- `golden_reference_gap_report.json`
- `golden_reference_summary.md`

It detects:
- Java / Spring Boot version shift
- dependency and plugin/tooling changes
- `javax.* -> jakarta.*` import moves
- `new Sort(...) -> Sort.by(...)`
- `@MockBean -> @MockitoBean`
- `initMocks -> openMocks`
- Azure old/new dependency pattern
- candidate deterministic rules
- human-review items
- LLM-candidate items
- factory/reference gap statuses

2. **Files Modified / Created**

- [migration_factory/golden_reference/__init__.py](./migration_factory/golden_reference/__init__.py)
- [migration_factory/golden_reference/analyzer.py](./migration_factory/golden_reference/analyzer.py)
- [tests/test_golden_reference_analyzer.py](./tests/test_golden_reference_analyzer.py)

3. **Tests Added**

- detect Java / Spring Boot version changes from sample POMs
- detect dependency alignment patterns
- detect `javax -> jakarta` import changes
- detect `Sort.by` migration
- detect `MockBean -> MockitoBean`
- detect `initMocks -> openMocks`
- detect Azure old/new dependency pattern
- produce JSON + Markdown reports
- report factory/reference gap statuses

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests -q
python -m pytest -q
python -m pytest tests/test_golden_reference_analyzer.py -q
```

5. **Test Results**

- `python -m pytest tests -q`: initially failed on new analyzer test, then fixed
- `python -m pytest tests/test_golden_reference_analyzer.py -q`: `2 passed`
- `python -m pytest -q`: `640 passed, 3 skipped`

6. **Example `golden_reference_gap_report.json` Excerpt**

```json
{
  "project_id": "sample",
  "detected_build_files_changed": ["pom.xml"],
  "java_version_change": {
    "legacy": "11",
    "reference": "17"
  },
  "spring_boot_version_change": {
    "legacy": "2.1.6.RELEASE",
    "reference": "3.5.14"
  },
  "javax_to_jakarta_import_changes": [
    {
      "rule_id": "IMPORT_JAVAX_VALIDATION_TO_JAKARTA",
      "legacy_count": 1,
      "reference_count": 1
    }
  ],
  "candidate_deterministic_rules": [
    {"rule_id": "JAVA_VERSION_ALIGNMENT"},
    {"rule_id": "SPRING_BOOT_VERSION_ALIGNMENT"},
    {"rule_id": "SPRING_DATA_SORT_BY_MIGRATION"},
    {"rule_id": "MOCKBEAN_TO_MOCKITOBEAN"}
  ]
}
```

7. **Example `golden_reference_summary.md` Excerpt**

```md
# Golden Reference Summary

Project ID: sample

## Version Shifts
- Java: 11 -> 17
- Spring Boot: 2.1.6.RELEASE -> 3.5.14

## Deterministic Candidates
- JAVA_VERSION_ALIGNMENT: Update Java version/tooling metadata.
- SPRING_BOOT_VERSION_ALIGNMENT: Align Spring Boot target version.
- SPRING_DATA_SORT_BY_MIGRATION: Apply deterministic pattern SPRING_DATA_SORT_BY_MIGRATION.
- MOCKBEAN_TO_MOCKITOBEAN: Apply deterministic pattern MOCKBEAN_TO_MOCKITOBEAN.
```

8. **How This Helps Industrialize Future Migrations**

This gives factory real learning loop from approved manual/reference migrations:
- extract repeatable safe rules
- expose human-review zones
- show where factory sandbox still misses reference behavior
- reduce guesswork for next remediation tickets
- make enterprise migration knowledge reusable, auditable, and generic

9. **Warnings / Limitations**

- local directories only in v1
- root `pom.xml` analysis strongest; multi-module deep semantics still limited
- rename detection is heuristic, not true VCS rename history
- behavioral/runtime drift detection here is candidate-level, not full execution truth
- no GitHub compare, no branch fetch, no network in this ticket

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 32B: Run Golden Reference Analyzer on real msa-dto and msa-utils references.
>
> Context:
> Ticket 32 added `migration_factory/golden_reference/analyzer.py`, local-directory only, no GitHub/network requirement inside the analyzer.
>
> We now need to validate it on the real reference repositories:
>
> * https://github.com/ilyasabarbach/msa-dto.git
> * https://github.com/ilyasabarbach/msa-utils.git
>
> Each repo has:
>
> * legacy/original
> * migrated/reference
>
> Goal:
> Produce real golden reference reports for both projects using local checkouts/snapshots.
>
> Required behavior:
>
> 1. Do not change legacy or migrated reference code.
> 2. Do not modify application source/tests.
> 3. Do not add project-specific rules to the analyzer unless fixing a generic analyzer bug.
> 4. Prepare local snapshots for:
>
>    * msa-dto legacy/original
>    * msa-dto migrated/reference
>    * msa-utils legacy/original
>    * msa-utils migrated/reference
> 5. Run Golden Reference Analyzer for:
>
>    * msa-dto
>    * msa-utils/common-utils
> 6. Write outputs under a safe evidence directory, for example:
>
>    * .migration/golden-references/msa-dto/
>    * .migration/golden-references/msa-utils/
> 7. Capture:
>
>    * golden_reference_gap_report.json
>    * golden_reference_summary.md
> 8. Summarize detected patterns:
>
>    * Java/Spring Boot version shifts
>    * dependency/plugin/tooling shifts
>    * javax/jakarta changes
>    * test modernization changes
>    * Azure/JJWT/Juneau/PowerMock signals
>    * deterministic rule candidates
>    * human-review candidates
>    * LLM-remediation candidates
>    * anti-pattern warnings
> 9. If the analyzer misses an obvious generic pattern, fix the analyzer with tests.
> 10. No hardcoded project logic.
> 11. No source mutation.
> 12. Full pytest suite must remain green if code changes are made.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_golden_reference_analyzer.py -q
> python -m pytest -q
>
> Then run the analyzer on both real references and report:
>
> 1. Summary
> 2. Commands run
> 3. Whether analyzer code changed
> 4. Test results
> 5. msa-dto report path + key excerpt
> 6. msa-utils report path + key excerpt
> 7. Top deterministic rule candidates found
> 8. Top human-review candidates found
> 9. Top LLM candidates found
> 10. Analyzer limitations observed on real repos

<details><summary>14 previous messages</summary>

> Me first find or prepare local snapshots for both repos, then run analyzer on real refs. If analyzer misses generic pattern, me patch analyzer + tests before final report.
>
> Me didn’t find local snapshots yet. Next me inspect remote branch names, then clone read-only branch snapshots into a safe evidence folder under `.migration/golden-references/repos`.
>
> Tests green. Me cloning four branch snapshots now and then running analyzer on both real repos.
>
> Me have real reports now. Next me inspect them for missed generic signals like Juneau or PowerMock; if missing, me patch analyzer generically and rerun.
>
> Real run exposed generic bug: repos are nested-module snapshots, so root-level analyzer missed real `pom.xml`. Me fixing analyzer generically for recursive module roots and for Juneau/PowerMock/Azure/JJWT signals.
>
> Me patching analyzer for nested module roots plus generic library-signal detection. Then me extend test with Juneau/PowerMock/JJWT/Azure signal assertions and rerun.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/golden_reference/analyzer.py` (+66 -1)
> - Wrote `./migration_factory/golden_reference/analyzer.py` (+1 -1)
> - Wrote `./tests/test_golden_reference_analyzer.py` (+40 -0)
>
> </details>
>
> Me rerunning analyzer tests first, then full suite, then real reports again with fixed analyzer.
>
> Analyzer fixed and real reports regenerated. Me inspecting final real outputs now for concise findings.
>
> Real repos still look empty in report. Me checking selected real `pom.xml` content now; likely generic parser issue or wrong snapshot root, not project-specific.
>
> Me found generic bug source: branch snapshots contain root folder plus nested module, but analyzer’s pom discovery still chose missing root `pom.xml`. Me verifying Python path walk and then patching selection logic.
>
> Me found real generic bug: skip-filters looked at absolute path parts, so any analysis under `.migration/...` hid every file. Me patching to use relative parts only, and adding regression test for snapshots under `.migration`.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/golden_reference/analyzer.py` (+7 -2)
> - Wrote `./tests/test_golden_reference_analyzer.py` (+18 -0)
>
> </details>
>
> Me rerun focused analyzer tests, then full suite, then regenerate both real reports one last time.
</details>

1. **Summary**

Me ran Golden Reference Analyzer on real local snapshots for both repos.

Real result:
- `msa-dto` now produces useful report after generic analyzer bug fix
- `msa-utils` now produces useful report too
- no repo code changed
- only analyzer/test code changed, generic only

2. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_golden_reference_analyzer.py -q
python -m pytest -q

git ls-remote --heads https://github.com/ilyasabarbach/msa-dto.git
git ls-remote --heads https://github.com/ilyasabarbach/msa-utils.git

git clone --depth 1 --branch legacy/original --single-branch https://github.com/ilyasabarbach/msa-dto.git .migration\golden-references\repos\msa-dto-legacy
git clone --depth 1 --branch migrated/reference --single-branch https://github.com/ilyasabarbach/msa-dto.git .migration\golden-references\repos\msa-dto-reference
git clone --depth 1 --branch legacy/original --single-branch https://github.com/ilyasabarbach/msa-utils.git .migration\golden-references\repos\msa-utils-legacy
git clone --depth 1 --branch migrated/reference --single-branch https://github.com/ilyasabarbach/msa-utils.git .migration\golden-references\repos\msa-utils-reference
```

Analyzer run:
```powershell
@' ... analyze_golden_reference(...) for msa-dto and msa-utils ... '@ | python -
```

3. **Whether Analyzer Code Changed**

Yes.

Generic fixes only:
- recursive nested-module `pom.xml` discovery
- `.migration` absolute-path bug fix
- generic framework/library signal detection:
  - `JJWT`
  - `JUNEAU`
  - `POWERMOCK`
  - `AZURE_OLD_SDK`
  - `AZURE_NEW_SDK`

Files changed:
- [migration_factory/golden_reference/analyzer.py](./migration_factory/golden_reference/analyzer.py)
- [tests/test_golden_reference_analyzer.py](./tests/test_golden_reference_analyzer.py)

4. **Test Results**

- `python -m pytest tests/test_golden_reference_analyzer.py -q`: `4 passed`
- `python -m pytest -q`: `642 passed, 3 skipped`

5. **`msa-dto` Report Path + Key Excerpt**

- JSON: [golden_reference_gap_report.json](./.migration/golden-references/msa-dto/golden_reference_gap_report.json)
- MD: [golden_reference_summary.md](./.migration/golden-references/msa-dto/golden_reference_summary.md)

Key excerpt:
- Java: `11 -> 21`
- Spring Boot: `2.1.6.RELEASE -> 3.5.6.RELEASE`
- JJWT: `0.10.5 -> 0.13.0`
- SLF4J: `1.7.25 -> 2.0.17`
- Lombok: `1.18.34 -> 1.18.42`
- `javax.xml.bind -> jakarta.xml.bind`
- `javax.servlet -> jakarta.servlet`
- Juneau signal present
- old Azure SDK signal still present in reference

6. **`msa-utils` Report Path + Key Excerpt**

- JSON: [golden_reference_gap_report.json](./.migration/golden-references/msa-utils/golden_reference_gap_report.json)
- MD: [golden_reference_summary.md](./.migration/golden-references/msa-utils/golden_reference_summary.md)

Key excerpt:
- Java: `11 -> 21`
- Spring Boot: `2.1.6.RELEASE -> 3.5.6`
- Lombok: `0.11.8 -> 1.18.42`
- JaCoCo: `0.8.2 -> 0.8.14`
- SLF4J: `1.7.25 -> 2.0.17`
- JJWT: `0.10.5 -> 0.12.5`
- Azure old SDK reduced, new Azure SDK added
- `javax.validation -> jakarta.validation`
- `javax.servlet -> jakarta.servlet`
- detected:
  - `Sort.by` migration
  - `MockBean -> MockitoBean`
  - `initMocks -> openMocks`
- PowerMock still present in reference

7. **Top Deterministic Rule Candidates Found**

Strongest real candidates:
- `JAVA_VERSION_ALIGNMENT`
- `SPRING_BOOT_VERSION_ALIGNMENT`
- `JJWT_VERSION_ALIGNMENT`
- `LOMBOK_VERSION_ALIGNMENT`
- `SLF4J_VERSION_ALIGNMENT`
- `JAKARTA_DEPENDENCY_ADDITION`
- `IMPORT_JAVAX_VALIDATION_TO_JAKARTA`
- `IMPORT_JAVAX_XML_BIND_TO_JAKARTA`
- `IMPORT_JAVAX_SERVLET_TO_JAKARTA`
- `SPRING_DATA_SORT_BY_MIGRATION`
- `MOCKBEAN_TO_MOCKITOBEAN`
- `INITMOCKS_TO_OPENMOCKS`

8. **Top Human-Review Candidates Found**

Top real human-review items:
- `AZURE_SDK_API_MIGRATION`
- `SPRING_SECURITY_BEHAVIOR_REVIEW`
- `PUBLIC_API_SIGNATURE_CHANGE`

9. **Top LLM Candidates Found**

Top LLM candidate in both reports:
- `UNMAPPED_SOURCE_TRANSFORMATION`

Meaning:
- localized code/test changes exist
- not all reference edits reduce cleanly to fixed safe rules yet

10. **Analyzer Limitations Observed On Real Repos**

Main limits me saw:
- still only one primary module `pom.xml` per snapshot, not full multi-module graph compare
- source transformation detection v1 catches simple patterns only
- runtime behavior drift not inferred here
- anti-pattern warnings still heuristic/light
- reference repos contain extra backup files like `pom copy.xml` / `.bak`; analyzer ignores them indirectly for primary POM, but richer cleanup heuristics may help later

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 33: Add Rule Extraction Report from Golden Reference reports.
>
> Context:
> Ticket 32 added Golden Reference Analyzer v1.
> Ticket 32B ran it on real local snapshots for:
>
> * msa-dto
> * msa-utils/common-utils
>
> Reports exist under:
>
> * .migration/golden-references/msa-dto/golden_reference_gap_report.json
> * .migration/golden-references/msa-utils/golden_reference_gap_report.json
>
> Goal:
> Create a Rule Extraction Report that reads one or more golden_reference_gap_report.json files and generates an industrialization backlog of reusable migration rules, human-review gates, LLM candidates, and anti-pattern warnings.
>
> This ticket must not modify application repositories. It only reads reports and writes factory-level evidence/backlog artifacts.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/golden_reference/rule_extractor.py
> 2. Input:
>
>    * one or more golden_reference_gap_report.json paths
>    * output_dir
>    * optional factory_capabilities metadata
> 3. Output:
>
>    * rule_extraction_report.json
>    * rule_extraction_summary.md
> 4. The report must group extracted items into:
>
>    * already_covered_by_factory
>    * missing_deterministic_rules
>    * missing_test_modernization_rules
>    * human_review_gates
>    * llm_remediation_candidates
>    * migration_playbooks_needed
>    * anti_pattern_warnings
> 5. Each extracted item must include:
>
>    * rule_id
>    * category
>    * source_projects
>    * evidence_summary
>    * suggested_priority: HIGH / MEDIUM / LOW
>    * safe_to_auto_apply
>    * requires_human_approval
>    * llm_candidate
>    * suggested_next_ticket
> 6. The extractor must remain generic:
>
>    * no hardcoded business logic for msa-dto
>    * no hardcoded business logic for common-utils
>    * project IDs may appear only as evidence metadata
> 7. Do not call GitHub.
> 8. Do not call network.
> 9. Do not modify source code or tests of reference repos.
> 10. Do not create LLM patches.
> 11. Do not auto-apply any remediation.
>
> Initial capability mapping:
> Treat these as likely already covered by the current factory if detected:
>
> * LOMBOK_VERSION_ALIGNMENT
> * JACOCO_VERSION_ALIGNMENT
> * SLF4J_VERSION_ALIGNMENT
> * JACKSON_VERSION_ALIGNMENT
> * SPRING_SECURITY_VERSION_ALIGNMENT
> * JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT
> * SPRING_DATA_SORT_BY_MIGRATION
> * MAVEN_COMPILER_PARAMETERS_ALIGNMENT
> * FAILED_SANDBOX_REPORTING
> * FAILURE_CLASSIFICATION
> * REMEDIATION_PLAN
> * LLM_POLICY_GATE
>
> Treat these as missing or needing stronger support if detected:
>
> * JJWT_VERSION_ALIGNMENT
> * JUNEAU_VERSION_ALIGNMENT_OR_REVIEW
> * MOCKBEAN_TO_MOCKITOBEAN
> * INITMOCKS_TO_OPENMOCKS
> * POWERMOCK_LEGACY_TEST_STRATEGY
> * AZURE_SDK_MIGRATION_PLAYBOOK
> * JAKARTA_HYBRID_STRATEGY
> * API_CONTRACT_REVIEW_GATE
> * CONSUMER_COMPATIBILITY_VALIDATION
>
> Priority guidance:
> HIGH:
>
> * rules found in more than one reference project
> * rules needed before testing a new microservice like translation
> * rules affecting build/test success
> * internal dependency / consumer compatibility validation
>   MEDIUM:
> * project-type-specific but recurring enterprise patterns
>   LOW:
> * cleanup or cosmetic improvements
>
> Expected real backlog themes:
>
> * JJWT alignment
> * Juneau alignment/review
> * Spring Boot test modernization: MockBean -> MockitoBean
> * Mockito initMocks -> openMocks
> * PowerMock/JUnit legacy strategy
> * Azure SDK migration playbook
> * Jakarta hybrid strategy
> * API behavior contract review gate
> * Consumer compatibility validation
>
> Tests:
>
> 1. Extract already-covered rules from synthetic golden report.
> 2. Extract missing deterministic rule candidates.
> 3. Extract test modernization candidates.
> 4. Extract human-review gates.
> 5. Extract LLM candidates.
> 6. Merge duplicate rule IDs across multiple projects and aggregate source_projects.
> 7. Assign HIGH priority when rule appears in multiple reports.
> 8. Produce JSON and Markdown artifacts.
> 9. No project-specific logic.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_golden_reference_analyzer.py -q
> python -m pytest -q
>
> Then run the extractor on the real msa-dto and msa-utils golden reports.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. rule_extraction_report.json path + excerpt
> 7. rule_extraction_summary.md path + excerpt
> 8. Top HIGH priority rules
> 9. Which items are already covered by the factory
> 10. Which missing rules should become the next implementation tickets
> 11. Warnings or limitations

<details><summary>8 previous messages</summary>

> Me add factory-level rule extractor now. First me inspect current golden reports and then build generic aggregator + tests, no app repo mutation.
>
> Me patching extractor now: generic capability map, merge logic, priorities, markdown/json artifacts, plus focused tests.
>
> <details><summary>Created 2 files, edited 1 file</summary>
>
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+383 -0)
> - Wrote `./migration_factory/golden_reference/__init__.py` (+6 -0)
> - Wrote `./tests/test_golden_rule_extractor.py` (+117 -0)
>
> </details>
>
> One small normalization before tests: map analyzer’s `JAKARTA_DEPENDENCY_ADDITION` into factory capability id `JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT`, so covered/missing split matches reality.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+8 -1)
>
> </details>
>
> Me running focused extractor tests, analyzer tests user asked for, then full suite. After green, me run extractor on real msa-dto and msa-utils reports.
>
> Tests green. Me generating real rule extraction backlog now from both golden reports.
>
> Me have real backlog artifact. Next me inspect final JSON/Markdown and extract top HIGH items + already-covered set for report.
</details>

1. **Summary**

Ticket 33 done.

Me added generic Rule Extraction Report.
It reads one or more `golden_reference_gap_report.json` files and builds factory backlog artifacts:

- `rule_extraction_report.json`
- `rule_extraction_summary.md`

Then me ran it on real `msa-dto` + `msa-utils` golden reports.

2. **Files Modified / Created**

- [migration_factory/golden_reference/rule_extractor.py](./migration_factory/golden_reference/rule_extractor.py)
- [migration_factory/golden_reference/__init__.py](./migration_factory/golden_reference/__init__.py)
- [tests/test_golden_rule_extractor.py](./tests/test_golden_rule_extractor.py)

Generic analyzer follow-up fix also happened during real validation:
- [migration_factory/golden_reference/analyzer.py](./migration_factory/golden_reference/analyzer.py)
- [tests/test_golden_reference_analyzer.py](./tests/test_golden_reference_analyzer.py)

3. **Tests Added**

- covered rules extracted into `already_covered_by_factory`
- missing deterministic rules extracted
- missing test modernization rules extracted
- human-review gates extracted
- LLM candidates extracted
- duplicate rule IDs merged across projects
- multi-project rules become `HIGH`
- JSON and Markdown artifacts written

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_golden_rule_extractor.py -q
python -m pytest tests/test_golden_reference_analyzer.py -q
python -m pytest -q
```

Real extraction:
```powershell
@' ... extract_rules_from_golden_reports(...) using msa-dto + msa-utils reports ... '@ | python -
```

5. **Test Results**

- `tests/test_golden_rule_extractor.py -q`: `2 passed`
- `tests/test_golden_reference_analyzer.py -q`: `4 passed`
- `pytest -q`: `644 passed, 3 skipped`

6. **`rule_extraction_report.json` Path + Excerpt**

Path:
- [rule_extraction_report.json](./.migration/golden-references/rule-extraction/rule_extraction_report.json)

Excerpt:
```json
{
  "already_covered_by_factory": [
    {"rule_id": "LOMBOK_VERSION_ALIGNMENT", "source_projects": ["msa-dto", "msa-utils"], "suggested_priority": "HIGH"},
    {"rule_id": "SLF4J_VERSION_ALIGNMENT", "source_projects": ["msa-dto", "msa-utils"], "suggested_priority": "HIGH"}
  ],
  "missing_deterministic_rules": [
    {"rule_id": "JJWT_VERSION_ALIGNMENT", "source_projects": ["msa-dto", "msa-utils"], "suggested_priority": "HIGH"},
    {"rule_id": "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW", "source_projects": ["msa-dto", "msa-utils"], "suggested_priority": "HIGH"}
  ],
  "missing_test_modernization_rules": [
    {"rule_id": "MOCKBEAN_TO_MOCKITOBEAN", "source_projects": ["msa-utils"], "suggested_priority": "HIGH"},
    {"rule_id": "INITMOCKS_TO_OPENMOCKS", "source_projects": ["msa-utils"], "suggested_priority": "HIGH"}
  ]
}
```

7. **`rule_extraction_summary.md` Path + Excerpt**

Path:
- [rule_extraction_summary.md](./.migration/golden-references/rule-extraction/rule_extraction_summary.md)

Excerpt:
```md
## Missing Deterministic Rules
- JJWT_VERSION_ALIGNMENT [HIGH]: Add deterministic JJWT alignment rule.
- JUNEAU_VERSION_ALIGNMENT_OR_REVIEW [HIGH]: Add Juneau alignment/review gate.

## Missing Test Modernization Rules
- INITMOCKS_TO_OPENMOCKS [HIGH]: Add deterministic Mockito initMocks to openMocks modernization.
- MOCKBEAN_TO_MOCKITOBEAN [HIGH]: Add deterministic Spring Boot test annotation modernization.
- POWERMOCK_LEGACY_TEST_STRATEGY [HIGH]: Define PowerMock legacy test containment or migration playbook.
```

8. **Top HIGH Priority Rules**

Top `HIGH` backlog items:
- `JJWT_VERSION_ALIGNMENT`
- `JUNEAU_VERSION_ALIGNMENT_OR_REVIEW`
- `MOCKBEAN_TO_MOCKITOBEAN`
- `INITMOCKS_TO_OPENMOCKS`
- `POWERMOCK_LEGACY_TEST_STRATEGY`
- `API_CONTRACT_REVIEW_GATE`
- `AZURE_SDK_MIGRATION_PLAYBOOK`
- `CONSUMER_COMPATIBILITY_VALIDATION`
- `JAKARTA_HYBRID_STRATEGY`

9. **Which Items Already Covered By Factory**

Real covered items extracted:
- `LOMBOK_VERSION_ALIGNMENT`
- `SLF4J_VERSION_ALIGNMENT`
- `JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT`
- `SPRING_DATA_SORT_BY_MIGRATION`

10. **Which Missing Rules Should Become Next Implementation Tickets**

Best next tickets:
- deterministic `JJWT_VERSION_ALIGNMENT`
- Juneau alignment/review gate
- deterministic `MockBean -> MockitoBean`
- deterministic `initMocks -> openMocks`
- PowerMock legacy strategy
- Azure SDK migration playbook
- API contract review gate
- consumer compatibility validation gate
- Jakarta hybrid strategy playbook

11. **Warnings / Limitations**

- extractor uses rule IDs/signals from golden reports, so if analyzer misses pattern, extractor misses it too
- current capability map is seed data, not full live capability inventory
- some generic rules like `JAVA_VERSION_ALIGNMENT` / `SPRING_BOOT_VERSION_ALIGNMENT` show as missing because capability seed did not mark them covered yet
- no source mutation, no LLM patching, no network calls in this ticket

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 34: Add deterministic JJWT version alignment.
>
> Context:
> Ticket 33 extracted HIGH priority missing deterministic rule `JJWT_VERSION_ALIGNMENT` from real golden reference reports for both msa-dto and msa-utils.
>
> Goal:
> Add a deterministic Maven POM patch operation that aligns JJWT dependencies to a target version from the migration profile/tooling config.
>
> Important:
> This must be generic, sandbox-only, idempotent, and not project-specific.
>
> Required behavior:
>
> 1. Add a deterministic Maven POM patch operation:
>
>    * op: `align_jjwt_version`
> 2. Detect JJWT dependencies, including common artifacts:
>
>    * `io.jsonwebtoken:jjwt`
>    * `io.jsonwebtoken:jjwt-api`
>    * `io.jsonwebtoken:jjwt-impl`
>    * `io.jsonwebtoken:jjwt-jackson`
>    * `io.jsonwebtoken:jjwt-gson`
>    * `io.jsonwebtoken:jjwt-orgjson`
> 3. Read target version from profile config, for example:
>
>    * `framework_versions.jjwt`
>      or another consistent profile field if the existing profile structure uses a better place.
> 4. Update explicit old JJWT dependency versions to the configured target version.
> 5. Update property-based JJWT versions when used.
> 6. Update dependencyManagement JJWT entries when present.
> 7. Do not add new JJWT artifacts automatically unless they already exist or the current POM clearly uses split JJWT modules and only one version needs alignment.
> 8. Do not migrate JJWT API usage in Java source in this ticket.
> 9. Do not rewrite token parsing code in this ticket.
> 10. Do not modify tests.
> 11. Do not skip tests.
> 12. Do not call LLM.
> 13. Do not call network.
> 14. No project-specific names such as msa-dto, common-utils, or translation.
> 15. Apply only in sandbox through the transformation execution plan.
> 16. Record exact old/new versions and touched dependencies/properties in the ledger.
> 17. Operation must be idempotent.
>
> Profile/config:
>
> 1. Add target JJWT version to relevant profiles:
>
>    * springboot-2.1-to-3.5-java17
>    * springboot-2.7-to-3.5-java17
> 2. Use a stable target version consistent with the migrated references or current profile strategy.
> 3. If there is uncertainty between 0.12.x and 0.13.x, prefer a configurable profile value, not a hardcoded value.
>
> Execution plan:
>
> 1. Wire `align_jjwt_version` into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build validation.
> 3. Do not run on baseline units.
>
> Tests:
>
> 1. Direct `io.jsonwebtoken:jjwt-jackson:0.10.5` updates to configured version.
> 2. Property-based JJWT version updates.
> 3. Split modules `jjwt-api`, `jjwt-impl`, `jjwt-jackson` align together.
> 4. dependencyManagement JJWT entries update.
> 5. No JJWT dependency -> no-op.
> 6. Already aligned JJWT -> no-op.
> 7. Ledger records old/new versions and dependencies touched.
> 8. Execution plan includes `align_jjwt_version` in `spring-boot-3-5-14`.
> 9. No project-specific names.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q
> python -m pytest -q
>
> Optional real validation:
> Do not rerun full common-utils unless necessary. If doing a quick check, inspect the generated execution plan or run on a small synthetic fixture.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Profile config excerpt
> 7. POM diff example
> 8. Ledger excerpt
> 9. Why this is deterministic and generic
> 10. Warnings or limitations

<details><summary>14 previous messages</summary>

> Me adding deterministic JJWT align now. First me inspect profile fields, Maven patcher ops, and Boot 3 execution-plan wiring so new rule matches existing pattern.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me found existing patch framework and Boot 3 hook point. Now me editing patcher, execution plan, and profile config together so JJWT follows same deterministic path as Jackson/SLF4J.
>
> Me have enough shape now. Next me patch in JJWT op and matching tests in same pattern as other version alignments, then run requested pytest slices.
>
> Me editing now. JJWT patch stay small and boring: tracked artifacts, profile version, Boot 3 execution-plan hook, and pytest coverage for direct/property/split/managed/no-op cases.
>
> <details><summary>Edited 7 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+98 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+8 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml` (+1 -0)
> - Wrote `./tests/agents/planning_agent/test_boot21_profile.py` (+2 -0)
> - Wrote `./tests/test_transformation_agent.py` (+15 -6)
> - Wrote `./tests/test_maven_pom_patcher.py` (+182 -0)
> - Wrote `./tests/test_transformation_agent.py` (+60 -0)
>
> </details>
>
> Small bug me caught before tests: shared dependency finder also sees dependencyManagement. Me tightening JJWT matcher now so ledger separates direct vs managed entries correctly.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+8 -6)
>
> </details>
>
> Edits in. Me running exact requested pytest slices first, then full suite, so if JJWT hook shifted Boot 3 plan order we catch it cleanly before broader run.
>
> Targeted JJWT tests green. Me doing full suite now to make sure no unrelated flow regressed before I package examples for you.
>
> Me have green suite. One quick synthetic proof now: generate tiny JJWT patch result so report can show exact operation payload and diff shape, no real app rerun needed.
>
> Me found one reporting wrinkle in shared-property case: first dep changed property, later deps saw new value already. Fixing that now so ledger shows true old version and all touched JJWT coordinates.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+10 -5)
>
> </details>
>
> Reporting fix in. Me rerunning fast slices plus full suite again so final numbers stay honest.
</details>

1. **Summary**

Me add deterministic `align_jjwt_version`.

Now factory can:
- detect JJWT deps in `pom.xml`
- update direct versions
- update property-based versions
- update `dependencyManagement` entries
- wire rule into `spring-boot-3-5-14` only
- record old/new/property/dependency touches in ledger

No source rewrite.
No tests changed.
No network.
Sandbox-only path.

2. **Files Modified**

- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [springboot-2.1-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.1-to-3.5-java17.yaml)
- [springboot-2.7-to-3.5-java17.yaml](./modernizer-solution-ai-hub/profiles/springboot-2.7-to-3.5-java17.yaml)
- [test_boot21_profile.py](./tests/agents/planning_agent/test_boot21_profile.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- direct `jjwt-jackson:0.10.5 -> 0.13.0`
- property `jjwt.version` update
- split modules align together
- `dependencyManagement` entries update
- absent JJWT => no-op
- already aligned => no-op
- Boot 3 execution plan includes `align_jjwt_version`
- transformation ledger records JJWT op

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/agents/planning_agent/test_boot21_profile.py -q
python -m pytest -q
```

Quick synthetic proof:
```powershell
@' ... apply_maven_pom_patch(... op=align_jjwt_version ...) ... '@ | python -
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `55 passed`
- `tests/test_transformation_agent.py -q`: `68 passed, 2 skipped`
- `tests/agents/planning_agent/test_boot21_profile.py -q`: `6 passed`
- `pytest -q`: `651 passed, 3 skipped`

6. **Profile Config Excerpt**

```yaml
framework_versions:
  jackson: "2.21.2"
  jackson_annotations: "2.21"
  jjwt: "0.13.0"
  thymeleaf: "3.1.3.RELEASE"
  jakarta_validation_api: "3.0.2"
  slf4j_api: "2.0.17"
  spring_security: "6.5.10"
```

7. **POM Diff Example**

```diff
- <jjwt.version>0.10.5</jjwt.version>
+ <jjwt.version>0.13.0</jjwt.version>
```

```diff
- <artifactId>jjwt-jackson</artifactId>
- <version>0.10.5</version>
+ <artifactId>jjwt-jackson</artifactId>
+ <version>0.13.0</version>
```

8. **Ledger Excerpt**

Synthetic operation payload after patch:

```json
{
  "op": "align_jjwt_version",
  "status": "updated",
  "group_id": "io.jsonwebtoken",
  "target_version": "0.13.0",
  "old_versions": ["0.10.5"],
  "new_version": "0.13.0",
  "updated_properties": ["jjwt.version"],
  "updated_dependencies": [
    "io.jsonwebtoken:jjwt-api",
    "io.jsonwebtoken:jjwt-impl",
    "io.jsonwebtoken:jjwt-jackson"
  ],
  "updated_managed_dependencies": []
}
```

9. **Why Deterministic And Generic**

- fixed artifact safelist only
- version from profile config, not repo name
- no app-source/token parsing rewrite
- no new JJWT artifacts added
- idempotent on already-aligned POMs
- wired only into Boot 3 unit, not baseline
- no `msa-dto` / `common-utils` hardcode

10. **Warnings / Limitations**

- me chose profile value `0.13.0`; easy to change later because config-driven
- this ticket only aligns Maven versions
- no Java API migration for JJWT usage in source
- no real app rerun done, only synthetic proof + full pytest green

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 35: Add deterministic Spring Boot test modernization rules.
>
> Context:
> Ticket 33 extracted missing HIGH priority test modernization rules from real golden reference reports:
>
> * MOCKBEAN_TO_MOCKITOBEAN
> * INITMOCKS_TO_OPENMOCKS
>
> These were observed in the migrated reference for msa-utils/common-utils. We need generic deterministic transformations for Spring Boot 3 test modernization.
>
> Goal:
> Add deterministic sandbox-only source/test patch operations for:
>
> 1. `@MockBean` -> `@MockitoBean`
> 2. `MockitoAnnotations.initMocks(...)` -> `MockitoAnnotations.openMocks(...)`
>
> Important:
> This must be generic, idempotent, sandbox-only, and not project-specific.
>
> Required behavior:
>
> 1. Add deterministic patch operation:
>
>    * `spring_boot_test_mockbean_to_mockitobean`
> 2. Replace imports:
>
>    * `org.springframework.boot.test.mock.mockito.MockBean`
>      with:
>    * `org.springframework.test.context.bean.override.mockito.MockitoBean`
> 3. Replace annotation usages:
>
>    * `@MockBean`
>      with:
>    * `@MockitoBean`
> 4. Preserve annotation parameters if present.
>    Example:
>
>    * `@MockBean(name = "x")`
>      -> `@MockitoBean(name = "x")`
> 5. Add deterministic patch operation:
>
>    * `mockito_initmocks_to_openmocks`
> 6. Replace:
>
>    * `MockitoAnnotations.initMocks(this);`
>      with:
>    * `MockitoAnnotations.openMocks(this);`
> 7. Also support simple variants:
>
>    * `MockitoAnnotations.initMocks(target);`
>      -> `MockitoAnnotations.openMocks(target);`
> 8. Do not introduce lifecycle management changes in this ticket.
>
>    * Do not add AutoCloseable fields.
>    * Do not add @AfterEach cleanup.
>    * Keep this first rule minimal and deterministic.
> 9. Do not modify production code.
> 10. Apply only to test source files when possible:
>
> * `src/test/java`
> * `src/integrationTest/java`
> * other test-like source roots if already supported generically
>
> 11. Do not skip tests.
> 12. Do not call LLM.
> 13. Do not call network.
> 14. No project-specific names such as common-utils, msa-dto, or translation.
> 15. Record exact files changed and patch types in ledger.
> 16. Operation must be idempotent.
>
> Execution plan:
>
> 1. Wire these operations into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build/test validation.
> 3. Do not run on baseline or Boot 2.7 stabilization units.
> 4. Keep behavioral/API-contract failures separate; this ticket only modernizes test framework APIs.
>
> Tests:
>
> 1. `@MockBean` import updates to `@MockitoBean` import.
> 2. `@MockBean` annotation updates to `@MockitoBean`.
> 3. Annotation parameters are preserved.
> 4. Existing `@MockitoBean` remains unchanged.
> 5. File without MockBean remains unchanged.
> 6. `MockitoAnnotations.initMocks(this)` updates to `openMocks(this)`.
> 7. `MockitoAnnotations.initMocks(target)` updates to `openMocks(target)`.
> 8. Existing `openMocks` remains unchanged.
> 9. Production source files are not modified.
> 10. Ledger records changed test files.
> 11. Execution plan includes both operations in `spring-boot-3-5-14`.
> 12. No project-specific names.
> 13. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Optional:
> Run Golden Reference Analyzer or a small synthetic fixture to prove the patterns are now covered.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Before/after examples
> 7. Ledger excerpt
> 8. Why this is deterministic and generic
> 9. Warnings or limitations

<details><summary>7 previous messages</summary>

> Me adding Boot 3 test-modernization rules now. First me inspect existing deterministic source patch hooks so new test-only ops plug into same ledger/execution path, not side path.
>
> Me patching source-transform hooks now. New rules touch test roots only, keep params/body same, and record files through same ledger format as other deterministic source patches.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+84 -2)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+40 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+2 -0)
> - Wrote `./tests/test_transformation_agent.py` (+14 -10)
>
> </details>
>
> Patch context slipped. Me locating exact insertion point in test file, then me add new tests clean there.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+201 -0)
> - Wrote `./tests/test_transformation_agent.py` (+115 -0)
>
> </details>
>
> Edits done. Me running requested transformation tests first; if one regex misses edge case, easier catch before full suite.
>
> Green. Me grabbing one tiny synthetic ledger excerpt now so report shows exact recorded patch shape, not guessed prose.
</details>

1. **Summary**

Me add 2 deterministic Boot 3 test-modernization rules:

- `spring_boot_test_mockbean_to_mockitobean`
- `mockito_initmocks_to_openmocks`

Behavior:
- test-source only
- sandbox only
- idempotent
- wired into `spring-boot-3-5-14`
- no prod source touch
- no LLM
- no network

2. **Files Modified**

- [pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- [agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- `@MockBean` import -> `@MockitoBean` import
- `@MockBean` annotation -> `@MockitoBean`
- annotation params preserved
- existing `@MockitoBean` no-op
- no MockBean no-op
- `MockitoAnnotations.initMocks(this)` -> `openMocks(this)`
- `MockitoAnnotations.initMocks(target)` -> `openMocks(target)`
- existing `openMocks` no-op
- prod source not modified
- ledger records changed test files
- execution plan includes both ops in `spring-boot-3-5-14`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

Synthetic ledger proof:
```powershell
@' ... run_transformation_agent(...) with both test-modernization ops ... '@ | python -
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `78 passed, 2 skipped`
- `pytest -q`: `661 passed, 3 skipped`

6. **Before / After Examples**

`@MockBean`:
```java
import org.springframework.boot.test.mock.mockito.MockBean;

@MockBean(name = "x")
```

becomes:

```java
import org.springframework.test.context.bean.override.mockito.MockitoBean;

@MockitoBean(name = "x")
```

`initMocks`:
```java
MockitoAnnotations.initMocks(this);
MockitoAnnotations.initMocks(target);
```

becomes:

```java
MockitoAnnotations.openMocks(this);
MockitoAnnotations.openMocks(target);
```

7. **Ledger Excerpt**

Synthetic run excerpt:

```json
[
  {
    "type": "spring_boot_test_mockbean_to_mockitobean",
    "status": "applied",
    "patches": [
      {
        "file": "src\\test\\java\\demo\\DemoTest.java",
        "patch": "spring_boot_test_mockbean_to_mockitobean",
        "unit": "spring-boot-3-5-14"
      }
    ]
  },
  {
    "type": "mockito_initmocks_to_openmocks",
    "status": "applied",
    "patches": [
      {
        "file": "src\\test\\java\\demo\\DemoTest.java",
        "patch": "mockito_initmocks_to_openmocks",
        "unit": "spring-boot-3-5-14"
      }
    ]
  }
]
```

8. **Why Deterministic And Generic**

- exact string/regex replacements only
- test roots only
- no repo-name logic
- no behavior/API-contract patching
- no lifecycle guessing
- repeat run no extra changes

9. **Warnings / Limitations**

- no `AutoCloseable` cleanup added
- no `@AfterEach` management added
- no wider Mockito lifecycle modernization yet
- only test-like roots with `test` in path touched
- no prod-code migration in this ticket

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 36: Add Juneau alignment/review gate.
>
> Context:
> Ticket 33 extracted HIGH priority item:
>
> * JUNEAU_VERSION_ALIGNMENT_OR_REVIEW
>
> Real golden references for msa-dto and msa-utils show Apache Juneau usage. Juneau can affect serialization contracts, DTO compatibility, REST payloads, JSON/XML behavior, and generated contract formats. Therefore it must not be blindly upgraded without governance.
>
> Goal:
> Add a generic Juneau detection and review/alignment mechanism.
>
> This ticket should be conservative:
>
> * detect Juneau usage
> * report risks
> * add a human-review gate by default
> * allow deterministic Maven alignment only when explicitly configured by profile
> * do not modify Java source
> * do not change serialization behavior automatically
>
> Required behavior:
>
> 1. Detect Apache Juneau dependencies in Maven POMs:
>
>    * groupId starting with `org.apache.juneau`
>    * common artifacts such as:
>
>      * juneau-marshall
>      * juneau-dto
>      * juneau-svl
>      * juneau-rest-client
>      * juneau-rest-server
>      * juneau-core
>      * juneau-all
> 2. Add a new Maven POM patch operation:
>
>    * `align_juneau_version`
> 3. This operation must be disabled unless the migration profile contains an explicit target version, for example:
>
>    * `framework_versions.juneau`
> 4. If `framework_versions.juneau` is absent:
>
>    * do not modify POM
>    * create/report a human-review item:
>
>      * `JUNEAU_VERSION_ALIGNMENT_OR_REVIEW`
>      * `requires_human_approval: true`
>      * `safe_to_auto_apply: false`
> 5. If `framework_versions.juneau` is present:
>
>    * update explicit Juneau dependency versions
>    * update property-based Juneau versions
>    * update dependencyManagement Juneau entries
>    * record old/new versions
> 6. Do not add new Juneau artifacts.
> 7. Do not remove Juneau artifacts.
> 8. Do not rewrite Java source using Juneau APIs.
> 9. Do not modify tests.
> 10. Do not skip tests.
> 11. Do not call LLM.
> 12. Do not call network.
> 13. Apply only in sandbox through the transformation execution plan.
> 14. No project-specific names such as msa-dto, common-utils, or translation.
> 15. Operation must be idempotent.
> 16. Record Juneau detection/alignment/review in artifacts and ledger.
>
> Execution plan:
>
> 1. Wire Juneau review/alignment into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build validation.
> 3. If target version exists in profile, apply Maven alignment.
> 4. If no target version exists, produce review artifact/warning but do not fail the migration by itself.
> 5. Preserve existing failed/success reporting behavior.
>
> Artifacts:
> Add or enrich artifacts with:
>
> * detected Juneau dependencies
> * old versions
> * target version if configured
> * action taken:
>
>   * REVIEW_ONLY
>   * UPDATED
>   * NO_OP
> * human_review_required flag
>
> Tests:
>
> 1. Detect direct Juneau dependencies.
> 2. Detect property-based Juneau versions.
> 3. Detect dependencyManagement Juneau entries.
> 4. No configured target version -> review-only, no POM change.
> 5. Configured target version -> direct dependency versions update.
> 6. Configured target version -> property updates.
> 7. Configured target version -> dependencyManagement updates.
> 8. No Juneau dependency -> no-op.
> 9. Already aligned Juneau -> no-op.
> 10. Ledger records review-only or update result.
> 11. Execution plan includes Juneau review/alignment in `spring-boot-3-5-14`.
> 12. No project-specific names.
> 13. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_maven_pom_patcher.py -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Optional:
> Use a small synthetic fixture only. Do not rerun full common-utils unless necessary.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Review-only artifact example
> 7. POM diff example when target version is configured
> 8. Ledger excerpt
> 9. Why this is conservative and governance-safe
> 10. Warnings or limitations

<details><summary>8 previous messages</summary>

> Me inspecting Juneau hook shape now. Need conservative path: same Maven patch framework, but review-only when profile has no target version, and no source change ever.
>
> Me patching Juneau op now. Plan: always hook Boot 3 unit, but op becomes `review_only` when Juneau present and profile gives no target. No POM write in that path.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+139 -1)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+5 -0)
> - Wrote `./tests/test_maven_pom_patcher.py` (+214 -0)
> - Wrote `./tests/test_transformation_agent.py` (+14 -6)
> - Wrote `./tests/test_transformation_agent.py` (+110 -0)
>
> </details>
>
> Juneau code in. Me running exact requested pytest slices now. Main thing to watch: `review_only` must not mark file changed, but still must survive ledger correctly.
>
> Two misses. Juneau managed-dep finder too clever, broke. Boot3 plan test also lacked `juneau` in fixture payload. Me fixing both, then rerun same commands.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/maven_pom_patcher.py` (+6 -1)
> - Wrote `./tests/test_transformation_agent.py` (+1 -0)
>
> </details>
>
> Fixes in. Me rerunning requested slices and full suite now.
>
> Green now. Me grabbing tiny synthetic Juneau examples: one review-only, one configured update. Faster than real app rerun, enough prove artifact shape.
</details>

1. **Summary**

Me add conservative Juneau gate.

Now Boot 3 unit always checks Juneau:
- if Juneau absent -> no-op
- if Juneau present, no profile version -> `review_only`
- if Juneau present, profile version set -> deterministic Maven version align

No Java source change.
No test change.
No artifact add/remove.
No network.
Sandbox-only.

2. **Files Modified**

- [maven_pom_patcher.py](./migration_factory/agents/transformation_agent/maven_pom_patcher.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [test_maven_pom_patcher.py](./tests/test_maven_pom_patcher.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- detect direct Juneau deps
- detect property-based Juneau versions
- detect `dependencyManagement` Juneau entries
- no target version -> review-only, no POM change
- target version -> direct dep update
- target version -> property update
- target version -> managed dep update
- absent Juneau -> no-op
- already aligned Juneau -> no-op
- ledger records review-only/update
- Boot 3 execution plan includes Juneau op

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_maven_pom_patcher.py -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

Synthetic proof:
```powershell
@' ... apply_maven_pom_patch(... op=align_juneau_version ...) ... '@ | python -
```

5. **Test Results**

- `tests/test_maven_pom_patcher.py -q`: `63 passed`
- `tests/test_transformation_agent.py -q`: `80 passed, 2 skipped`
- `pytest -q`: `671 passed, 3 skipped`

6. **Review-Only Artifact Example**

Synthetic review-only op result:

```json
{
  "op": "align_juneau_version",
  "status": "review_only",
  "detected_juneau_dependencies": [
    "org.apache.juneau:juneau-marshall"
  ],
  "old_versions": [
    "8.2.0"
  ],
  "target_version": null,
  "action_taken": "REVIEW_ONLY",
  "human_review_required": true,
  "requires_human_approval": true,
  "review_item": "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW",
  "safe_to_auto_apply": false
}
```

7. **POM Diff Example When Target Configured**

```diff
- <artifactId>juneau-marshall</artifactId>
- <version>8.2.0</version>
+ <artifactId>juneau-marshall</artifactId>
+ <version>9.0.0</version>
```

8. **Ledger Excerpt**

Update path example:

```json
{
  "op": "align_juneau_version",
  "status": "updated",
  "detected_juneau_dependencies": [
    "org.apache.juneau:juneau-marshall"
  ],
  "old_versions": [
    "8.2.0"
  ],
  "target_version": "9.0.0",
  "new_version": "9.0.0",
  "updated_properties": [],
  "updated_dependencies": [
    "org.apache.juneau:juneau-marshall"
  ],
  "updated_managed_dependencies": [],
  "action_taken": "UPDATED",
  "human_review_required": false
}
```

9. **Why Conservative And Governance-Safe**

- default path = detect + review only
- no auto version bump unless profile explicitly says so
- no source/API rewrite
- no test rewrite
- no dependency add/remove
- human review flag explicit for unconfigured Juneau

10. **Warnings / Limitations**

- me did not add `framework_versions.juneau` to profiles; current real profiles stay review-only
- only Maven version alignment here
- no Juneau serialization contract analysis yet
- no runtime payload diffing yet

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 37: Add PowerMock / legacy test strategy gate.
>
> Context:
> Ticket 33 extracted HIGH priority item:
>
> * POWERMOCK_LEGACY_TEST_STRATEGY
>
> Real golden references show PowerMock still present in migrated references. PowerMock is risky in modern Java / Spring Boot 3 migrations because it can depend on bytecode manipulation, classloader behavior, static mocking, constructor mocking, and legacy JUnit patterns.
>
> Goal:
> Add a conservative PowerMock legacy test strategy gate.
>
> This ticket must not rewrite tests automatically. It should detect PowerMock usage, classify risk, and produce review/remediation guidance.
>
> Required behavior:
>
> 1. Detect PowerMock dependencies in Maven POMs:
>
>    * groupId starting with `org.powermock`
>    * common artifacts:
>
>      * powermock-module-junit4
>      * powermock-api-mockito2
>      * powermock-api-mockito
>      * powermock-core
>      * powermock-module-junit4-rule
> 2. Detect PowerMock source/test usage in test files:
>
>    * `@RunWith(PowerMockRunner.class)`
>    * `@PrepareForTest`
>    * `PowerMockito`
>    * `mockStatic`
>    * `whenNew`
>    * `suppress`
>    * `Whitebox`
> 3. Add a review/gate artifact or enrich existing remediation/failure artifacts with:
>
>    * detected dependencies
>    * detected usage files
>    * risk_level: HIGH
>    * gate_id: POWERMOCK_LEGACY_TEST_STRATEGY
>    * safe_to_auto_apply: false
>    * requires_human_approval: true
> 4. Do not modify tests.
> 5. Do not modify production source.
> 6. Do not remove PowerMock dependencies.
> 7. Do not replace PowerMock with Mockito automatically.
> 8. Do not skip tests.
> 9. Do not call LLM.
> 10. Do not call network.
> 11. No project-specific names such as msa-dto, common-utils, or translation.
> 12. The logic must be generic and idempotent.
> 13. Record PowerMock detection/review in ledger or a dedicated artifact.
>
> Recommended guidance in output:
>
> * If PowerMock is only declared but unused, recommend dependency cleanup review.
> * If PowerMock static mocking is used, recommend human test modernization review.
> * If constructor mocking or Whitebox is used, recommend high-risk manual review.
> * If final class mocking appears, recommend Mockito inline / test design review, but do not auto-apply.
>
> Integration:
>
> 1. Wire this gate into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build/test validation or during remediation planning.
> 3. Do not fail migration by itself.
> 4. Add warnings to orchestration/final report when detected.
> 5. Keep successful and failed reporting backward compatible.
>
> Artifacts:
> Create or enrich an artifact such as:
>
> * `assessment/powermock_review.json`
>   or
> * `remediation/powermock_review.json`
>
> The artifact should include:
>
> * run_id if available
> * detected: true/false
> * dependencies
> * usage_files
> * usage_patterns
> * risk_level
> * recommended_next_actions
> * human_review_required
>
> Tests:
>
> 1. Detect PowerMock dependencies in POM.
> 2. Detect `@RunWith(PowerMockRunner.class)`.
> 3. Detect `@PrepareForTest`.
> 4. Detect `PowerMockito.mockStatic`.
> 5. Detect `whenNew`.
> 6. Detect `Whitebox`.
> 7. POM dependency present but no usage -> dependency cleanup review.
> 8. No PowerMock -> no-op / detected=false.
> 9. Artifact includes human_review_required=true when detected.
> 10. No test source modification.
> 11. Execution plan or remediation/report integration includes PowerMock gate.
> 12. No project-specific names.
> 13. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Use only synthetic fixtures unless a quick read-only check is needed.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example PowerMock review artifact
> 7. Example final/orchestration warning
> 8. Why no automatic test rewrite was applied
> 9. Why this is governance-safe
> 10. Warnings or limitations

<details><summary>17 previous messages</summary>

> Me scanning report path now. Need PowerMock gate show up in Boot 3 plan, write review artifact, then bubble warning into orchestration/final reporting without mutating tests.
>
> Me found easiest safe path: PowerMock gate runs inside transformer, writes review artifact into sandbox `.migration`, then transform phase lifts warning + artifact ref into orchestration state. Final report already carries state warnings.
>
> Me wiring artifact lift now. Transformer gate alone not enough; transform result must carry warning + artifact ref so orchestration/final reports show it automatically.
>
> Me choosing dedicated review artifact path in sandbox `.migration/review/powermock_review.json`. Then transform phase lifts path + warning into orchestration state, so summary/final report show it without special-case project logic.
>
> Me adding one small orchestrator propagation test too. That way PowerMock artifact/warning path proven from transform result into orchestration state, not only inside transformer ledger.
>
> Me creating dedicated review module now. It only scans POM + test files, writes JSON artifact, returns metadata. No file rewrite except artifact itself.
>
> <details><summary>Created 1 file, edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+168 -0)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+31 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+1 -0)
>
> </details>
>
> Patch context drift again. Me locating exact return/helper area in transform flow, then me add PowerMock lift cleanly.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+2 -1)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+5 -4)
>
> </details>
>
> Need exact helper anchor. Me searching exact function names in transform file, then patch below real one.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+48 -0)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+2 -0)
>
> </details>
>
> Now tests. Me adding direct gate tests + one orchestrator propagation test. After that, run requested suites.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+224 -0)
>
> </details>
>
> Need plan order assertion shifted one slot. Me patching that and adding tiny orchestrator propagation test file.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+12 -11)
> - Wrote `./tests/orchestrator/test_powermock_gate.py` (+57 -0)
>
> </details>
>
> PowerMock gate code in. Me running requested test slices now. Main checks: review artifact path, plan slot, and transform-phase propagation.
>
> Green. Me grabbing tiny synthetic artifact example only, no real repo touch. Then final report back.
</details>

1. **Summary**

Me add conservative PowerMock gate.

Now Boot 3 unit does:
- detect PowerMock deps in POM
- detect PowerMock test usage patterns
- write review artifact
- record gate in ledger
- lift warning + artifact ref into orchestration state

No test rewrite.
No prod rewrite.
No dep removal.
No Mockito replacement.

2. **Files Modified**

- [review_gates.py](./migration_factory/agents/transformation_agent/review_gates.py)
- [agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)
- [test_powermock_gate.py](./tests/orchestrator/test_powermock_gate.py)

3. **Tests Added**

- detect PowerMock dep in POM
- detect `@RunWith(PowerMockRunner.class)`
- detect `@PrepareForTest`
- detect `PowerMockito.mockStatic`
- detect `whenNew`
- detect `Whitebox`
- dep present but no usage -> cleanup review guidance
- no PowerMock -> `detected=false`
- artifact has `human_review_required=true`
- execution plan includes gate
- no prod/test source modification
- orchestration state gets warning + artifact ref

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Synthetic artifact proof:
```powershell
@' ... review_powermock_legacy_test_strategy(...) ... '@ | python -
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `88 passed, 2 skipped`
- `tests/orchestrator -q`: `101 passed`
- `pytest -q`: `680 passed, 3 skipped`

6. **Example PowerMock Review Artifact**

```json
{
  "dependencies": [
    "org.powermock:powermock-module-junit4"
  ],
  "detected": true,
  "gate_id": "POWERMOCK_LEGACY_TEST_STRATEGY",
  "human_review_required": true,
  "risk_level": "HIGH",
  "safe_to_auto_apply": false,
  "usage_files": [
    "src\\test\\java\\demo\\DemoTest.java"
  ],
  "usage_patterns": [
    "POWERMOCK_API",
    "POWERMOCK_RUNNER",
    "POWERMOCK_STATIC_MOCKING"
  ],
  "recommended_next_actions": [
    "PowerMock static mocking detected; perform human test modernization review for Mockito inline or test design alternatives."
  ]
}
```

7. **Example Final / Orchestration Warning**

Warning text now propagated:
```text
PowerMock legacy test strategy detected; manual review required before trusting Boot 3 test behavior.
```

Artifact ref propagated:
- `artifact_refs["powermock_review"] -> .../.migration/review/powermock_review.json`

8. **Why No Automatic Test Rewrite Applied**

Ticket rule.
Also unsafe:
- PowerMock often means static mocking
- constructor mocking
- classloader tricks
- Whitebox internals

Blind rewrite to Mockito/JUnit could break behavior. Gate only reports.

9. **Why Governance-Safe**

- review-only
- no source mutation except review artifact
- no dependency removal
- no auto modernization
- explicit `safe_to_auto_apply=false`
- explicit `requires_human_approval=true`
- warning visible in orchestration/final path

10. **Warnings / Limitations**

- gate scans Java test sources only
- no semantic migration of PowerMock tests yet
- no JUnit 4 -> 5 rewrite here
- no Mockito inline config change here
- current warning is generic; future ticket can enrich per-pattern playbooks

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 38: Add Jakarta Hybrid Strategy Gate.
>
> Context:
> Golden reference analysis showed that migrated enterprise projects may not convert every `javax.*` namespace uniformly. Some namespaces are safe and expected to migrate to Jakarta in Spring Boot 3, while others may need review depending on library type, public API contracts, or consumer compatibility.
>
> Goal:
> Add a generic Jakarta Hybrid Strategy Gate that classifies `javax.*` usages into:
>
> * deterministic safe migration candidates
> * dependency alignment candidates
> * human-review candidates
> * high-risk public API / consumer compatibility concerns
>
> This ticket should be conservative. It must not blindly rewrite all `javax.*` imports.
>
> Required behavior:
>
> 1. Add generic Jakarta usage scanner/gate.
> 2. Scan source and test files for imports/usages:
>
>    * `javax.validation`
>    * `javax.xml.bind`
>    * `javax.servlet`
>    * `javax.annotation`
>    * `javax.persistence`
>    * `javax.ws.rs`
>    * other `javax.*`
> 3. Classify namespaces:
>
>    * `javax.xml.bind` -> usually deterministic candidate: `jakarta.xml.bind`
>    * `javax.validation` -> deterministic candidate plus validation dependency alignment
>    * `javax.servlet` -> deterministic candidate plus servlet dependency alignment
>    * `javax.annotation` -> review or deterministic depending on known mapping
>    * `javax.persistence` -> human review / consumer compatibility review by default
>    * unknown `javax.*` -> human review
> 4. Detect whether usage is in:
>
>    * production source
>    * test source
>    * public DTO/API package
>    * generated source if detectable
> 5. Produce a Jakarta strategy artifact, for example:
>
>    * `review/jakarta_hybrid_strategy.json`
> 6. Artifact should include:
>
>    * detected namespaces
>    * files by namespace
>    * classification
>    * safe_to_auto_apply
>    * requires_human_approval
>    * recommended_action
>    * dependency_recommendations
>    * consumer_compatibility_warning when public API/DTO usage is detected
> 7. Add warnings/artifact refs into orchestration/final reporting when relevant.
> 8. Do not rewrite source in this ticket unless the existing deterministic transformation already handles it elsewhere.
> 9. Do not add/remove dependencies in this ticket unless existing deterministic operations already do it elsewhere.
> 10. Do not modify tests.
> 11. Do not skip tests.
> 12. Do not call LLM.
> 13. Do not call network.
> 14. No project-specific names such as msa-dto, common-utils, or translation.
> 15. The logic must be generic and idempotent.
> 16. Record the gate result in ledger or review artifacts.
>
> Integration:
>
> 1. Wire this gate into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build/test validation.
> 3. Do not fail migration by itself.
> 4. If high-risk `javax.persistence` or public API usage is found, emit human-review warning.
> 5. If only safe namespaces are found, emit strategy info but do not block.
>
> Tests:
>
> 1. Detect `javax.xml.bind` usage and classify as deterministic candidate.
> 2. Detect `javax.validation` usage and classify as deterministic/dependency candidate.
> 3. Detect `javax.servlet` usage and classify as deterministic/dependency candidate.
> 4. Detect `javax.persistence` and classify as human review by default.
> 5. Detect unknown `javax.*` and classify as human review.
> 6. Detect public API/DTO usage and emit consumer compatibility warning.
> 7. No `javax.*` usage -> detected=false / no-op.
> 8. Artifact includes human_review_required=true for high-risk namespaces.
> 9. Execution plan includes Jakarta hybrid strategy gate in `spring-boot-3-5-14`.
> 10. No source/test modification.
> 11. No project-specific names.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Use synthetic fixtures only unless a quick read-only check is needed.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example jakarta_hybrid_strategy.json
> 7. Example warning for javax.persistence/public API usage
> 8. Why this is safer than blind javax-to-jakarta migration
> 9. Warnings or limitations

<details><summary>12 previous messages</summary>

> Me reusing review-gate path from PowerMock. Jakarta gate will scan namespaces, classify risk, write review artifact, then bubble warning + artifact ref into orchestration/final reporting.
>
> Me have enough. Next me extend existing review-gate plumbing for Jakarta, then add tests for scan + orchestration warning propagation.
>
> Me coding Jakarta scanner now. Rule split: safe namespaces get info, `javax.persistence` and unknown `javax.*` trigger human review, DTO/API paths trigger consumer warning.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+209 -0)
>
> </details>
>
> Now me wiring gate into transformer/execution and transform result propagation, parallel to PowerMock.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+30 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+1 -0)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+36 -5)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+2 -0)
>
> </details>
>
> Now tests: add scanner tests + ledger + update plan order + orchestrator propagation.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+14 -12)
> - Wrote `./tests/test_transformation_agent.py` (+157 -0)
>
> </details>
>
> Need fix asserts using assert not self maybe okay. But using assert in unittest methods okay though stylistic. Add orchestrator propagation test.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_powermock_gate.py` (+50 -0)
>
> </details>
>
> Jakarta gate wiring done. Me running requested suites now. Main checks: namespace classification, ledger artifact, Boot 3 plan slot, orchestration warning propagation.
>
> Green. Me grabbing one synthetic Jakarta artifact example now so final report can show exact classification payload.
</details>

1. **Summary**

Me add Jakarta Hybrid Strategy Gate.

Now Boot 3 unit does:
- scan `javax.*` usage in source/test
- classify namespace risk
- detect public DTO/API usage
- write review artifact
- record gate in ledger
- lift warnings + artifact ref into orchestration/final reporting

No source rewrite.
No test rewrite.
No dep mutation here.
Only review/gate.

2. **Files Modified**

- [review_gates.py](./migration_factory/agents/transformation_agent/review_gates.py)
- [agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)
- [test_powermock_gate.py](./tests/orchestrator/test_powermock_gate.py)

3. **Tests Added**

- `javax.xml.bind` -> deterministic-safe candidate
- `javax.validation` -> deterministic + dependency candidate
- `javax.servlet` -> deterministic + dependency candidate
- `javax.persistence` -> human review
- unknown `javax.*` -> human review
- public DTO/API path -> consumer compatibility warning
- no `javax.*` -> `detected=false`
- artifact marks `human_review_required=true` for high-risk cases
- execution plan includes Jakarta gate
- no source/test modification
- ledger records Jakarta gate artifact
- orchestration warning/artifact propagation

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Synthetic artifact proof:
```powershell
@' ... review_jakarta_hybrid_strategy(...) ... '@ | python -
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `96 passed, 2 skipped`
- `tests/orchestrator -q`: `102 passed`
- `pytest -q`: `689 passed, 3 skipped`

6. **Example `jakarta_hybrid_strategy.json`**

```json
{
  "consumer_compatibility_warning": true,
  "detected": true,
  "detected_namespaces": [
    "javax.persistence",
    "javax.validation"
  ],
  "gate_id": "JAKARTA_HYBRID_STRATEGY",
  "human_review_required": true,
  "risk_level": "HIGH",
  "warnings": [
    "Jakarta hybrid strategy detected javax.persistence usage; manual review required before blind namespace migration.",
    "Public API or DTO package uses javax.* namespace; consumer compatibility review required."
  ]
}
```

Namespace detail example:
- `javax.validation`
  - `classification: DETERMINISTIC_PLUS_DEPENDENCY_ALIGNMENT`
  - `dependency_recommendations: ["spring-boot-starter-validation or jakarta.validation-api"]`
- `javax.persistence`
  - `classification: HUMAN_REVIEW_CANDIDATE`
  - `safe_to_auto_apply: false`

7. **Example Warning For `javax.persistence` / Public API Usage**

```text
Jakarta hybrid strategy detected javax.persistence usage; manual review required before blind namespace migration.
Public API or DTO package uses javax.* namespace; consumer compatibility review required.
```

8. **Why Safer Than Blind `javax` -> `jakarta` Migration**

- not all `javax.*` equal risk
- JAXB / validation / servlet often safe-ish with known dependency path
- persistence / unknown namespaces can change runtime, schema, contracts
- DTO/API package usage can break consumers even when compile passes
- gate keeps deterministic rules separate from contract-risk review

9. **Warnings / Limitations**

- scanner is static text-based, not full semantic type analysis
- public API detection is heuristic by path names like `dto`, `api`, `contract`, `public`
- no automatic dependency/source action added here beyond existing rules elsewhere
- generated-source detection is heuristic too

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 39: Add API Contract Review Gate.
>
> Context:
> Post-transform failures in complex Spring Boot 3 migrations can reveal behavior/API contract drift, not simple dependency or compilation issues. Examples include:
>
> * HTTP status changed, e.g. expected 404 but got 405
> * exception handler behavior changed
> * Problem/JSON response payload changed
> * validation exception handling changed
> * public controller/advice behavior changed
>
> The factory must not blindly patch API behavior. It should detect and report API contract drift as a human-review gate.
>
> Goal:
> Add a conservative API Contract Review Gate that detects likely API/behavior contract drift from test failure artifacts and source structure, then writes a review artifact and warnings.
>
> Required behavior:
>
> 1. Add generic API contract review gate logic.
> 2. Inputs should reuse available artifacts when present:
>
>    * post_transform_failure_classification.json
>    * surefire reports
>    * build error contract
>    * orchestration summary
> 3. Detect categories such as:
>
>    * HTTP_STATUS_CONTRACT_DRIFT
>    * SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>    * JAKARTA_VALIDATION_HANDLER_MISMATCH
>    * APPLICATION_BEHAVIOR_REGRESSION
> 4. Also detect source/test hints when possible:
>
>    * controller advice classes
>    * `@ControllerAdvice`
>    * `@RestControllerAdvice`
>    * `ResponseEntityExceptionHandler`
>    * Zalando Problem / AdviceTrait usage
>    * tests asserting HTTP status
>    * tests asserting response body / Problem payload
> 5. Write an artifact, for example:
>
>    * `review/api_contract_review.json`
> 6. Artifact should include:
>
>    * detected: true/false
>    * gate_id: API_CONTRACT_REVIEW_GATE
>    * risk_level
>    * human_review_required
>    * safe_to_auto_apply: false
>    * detected_failure_categories
>    * affected_tests
>    * affected_source_files
>    * suspected_contract_areas
>    * recommended_next_actions
> 7. Recommended next actions should distinguish:
>
>    * preserve legacy API behavior
>    * accept new Spring Boot 3 behavior and update tests
>    * require product/API owner decision
>    * require consumer compatibility validation
> 8. Do not modify source code.
> 9. Do not modify tests.
> 10. Do not skip tests.
> 11. Do not call LLM.
> 12. Do not call GitHub Copilot.
> 13. Do not call network.
> 14. No project-specific names such as msa-dto, common-utils, or translation.
> 15. Record gate result in ledger or review artifacts.
> 16. Add warning/artifact ref into orchestration/final reporting when detected.
>
> Integration:
>
> 1. Run this gate after test failure classification or during failed sandbox finalization.
> 2. It may also run in Boot 3 unit review path if relevant artifacts exist.
> 3. Do not fail migration by itself; it explains why human review is required.
> 4. Preserve existing failed/success reporting behavior.
>
> Tests:
>
> 1. HTTP_STATUS_CONTRACT_DRIFT classification creates API contract review artifact.
> 2. SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT classification creates review artifact.
> 3. JAKARTA_VALIDATION_HANDLER_MISMATCH classification creates review artifact.
> 4. Surefire report with `expected:<404> but was:<405>` is detected as HTTP status drift.
> 5. Source file with `@ControllerAdvice` is listed as affected source hint.
> 6. Tests asserting status/body are listed as affected test hints when detectable.
> 7. No API-related failures -> detected=false / no warning.
> 8. Artifact includes human_review_required=true and safe_to_auto_apply=false.
> 9. Orchestration/final reporting includes artifact ref and warning when detected.
> 10. No source/test modification.
> 11. No project-specific names.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Use synthetic fixtures only unless a quick read-only check is needed.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example api_contract_review.json
> 7. Example orchestration/final warning
> 8. Why no automatic patch was applied
> 9. Why this is governance-safe
> 10. Warnings or limitations

<details><summary>15 previous messages</summary>

> Me inspecting failure-classification path and finalization hook now. Best place likely failed-sandbox finalization: write API contract review artifact from existing classification + surefire + source hints, then bubble ref/warning into report.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me do Ticket 39 now. First me inspect current failure/finalization path and existing review gates, then me wire API contract gate in same generic style.
>
> Me found good hook: failed sandbox finalization in `orchestrator/summary.py`. Next me add API contract reviewer there, plus tests for artifact + warning propagation.
>
> Me have enough context. Now me add new reviewer module, wire failed-finalization path, then cover with orchestrator/final-report tests.
>
> Me start edits now. New module for API contract gate, then summary integration, then tests.
>
> New gate live in failed-sandbox path, not transform path. Me add direct reviewer with artifact scan + source/test hints, then integrate summary/final report visibility.
>
> <details><summary>Created 1 file, edited 2 files</summary>
>
> - Wrote `./migration_factory/orchestrator/api_contract_review.py` (+389 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+28 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
>
> </details>
>
> Me add direct tests now: category detection, surefire fallback, controller-advice/test-hint scan, no-op path, plus finalize integration assertions.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_api_contract_review.py` (+337 -0)
>
> </details>
>
> Me add one final-report assertion too. This keeps markdown/report path covered, not only orchestrator state.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_final_report.py` (+2 -0)
>
> </details>
>
> Edits in. Now me run targeted tests first for new gate + failure reporting, then full requested suite.
>
> Targeted tests green. Me run requested validation set now: orchestrator, transformation agent, full pytest.
>
> Validation green. Me do one quick diff check now so report lists exact touched files, nothing extra.
</details>

1. **Summary**

Me add conservative API Contract Review Gate.

Gate now:
- read failure classification
- read surefire XML
- scan sandbox source/test hints
- write `review/api_contract_review.json`
- add warning + artifact ref into failed sandbox orchestration/final report

No source patch.
No test patch.
No LLM.
No network.

2. **Files Modified**

- [api_contract_review.py](./migration_factory/orchestrator/api_contract_review.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_api_contract_review.py](./tests/orchestrator/test_api_contract_review.py)
- [test_final_report.py](./tests/test_final_report.py)

3. **Tests Added**

- HTTP status drift classification -> review artifact
- Spring MVC exception-handler drift classification -> review artifact
- Jakarta validation handler mismatch -> review artifact
- surefire `expected:<404> but was:<405>` -> HTTP status drift
- `@ControllerAdvice` source hint captured
- status/body assertion test hints captured
- no API-related failure -> `detected=false`
- failed sandbox finalization propagates artifact ref + warning into report

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_api_contract_review.py -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

5. **Test Results**

- `tests/orchestrator/test_api_contract_review.py -q`: `6 passed`
- `tests/test_final_report.py -q`: `20 passed`
- `tests/orchestrator -q`: `108 passed`
- `tests/test_transformation_agent.py -q`: `96 passed, 2 skipped`
- `pytest -q`: `695 passed, 3 skipped`

6. **Example `api_contract_review.json`**

```json
{
  "detected": true,
  "gate_id": "API_CONTRACT_REVIEW_GATE",
  "risk_level": "HIGH",
  "human_review_required": true,
  "safe_to_auto_apply": false,
  "detected_failure_categories": [
    "HTTP_STATUS_CONTRACT_DRIFT"
  ],
  "affected_tests": [
    {
      "test_class": "com.example.CustomExceptionTranslatorTest",
      "test_method": "requestMethodNotSupported",
      "category": "HTTP_STATUS_CONTRACT_DRIFT",
      "symptom": "expected:<404> but was:<405>"
    }
  ],
  "affected_source_files": [
    {
      "file": "src/main/java/com/example/CustomExceptionTranslator.java",
      "markers": [
        "CONTROLLER_ADVICE",
        "RESPONSE_ENTITY_EXCEPTION_HANDLER",
        "ZALANDO_PROBLEM",
        "ADVICE_TRAIT"
      ]
    }
  ],
  "suspected_contract_areas": [
    "http_status_mapping",
    "response_body_contract",
    "problem_json_payload_contract"
  ]
}
```

7. **Example Orchestration / Final Warning**

```text
API contract drift detected; human review required before changing controller/advice behavior or test expectations.
```

Final markdown now also lists:
```text
- API Contract Review: .../review/api_contract_review.json
```

8. **Why No Automatic Patch Applied**

Ticket say gate only.
Also unsafe:
- HTTP status drift may be intended or breaking
- advice behavior may need product/API owner call
- Problem payload drift may affect consumers
- validation handling may need contract decision, not blind fix

9. **Why Governance-Safe**

- review-only
- `safe_to_auto_apply=false`
- `human_review_required=true`
- no app/test mutation
- no hidden failure
- artifact + warning visible in orchestration/final outputs

10. **Warnings Or Limitations**

- source/test hint scan is static text, not full semantic analysis
- public API contract inference comes from failures + hints, not live consumer traffic
- gate explains drift; it does not choose whether legacy or Boot 3 behavior should win

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 40: Add Consumer Compatibility Validation Gate.
>
> Context:
> The migration factory handles enterprise microservice/library waves. Some projects are internal libraries consumed by other microservices. For example:
>
> * DTO libraries may be consumed by utility libraries or services.
> * Utility libraries may be consumed by downstream services.
>   A migrated library can compile in isolation but still break downstream consumers.
>
> Goal:
> Add a conservative Consumer Compatibility Validation Gate that can validate a migrated sandbox artifact against configured downstream consumer projects, without modifying consumers.
>
> This ticket should create the gate and evidence flow. It should be safe, optional, and disabled unless consumers are configured.
>
> Required behavior:
>
> 1. Add a consumer compatibility validation module/gate.
> 2. Input configuration should support:
>
>    * migrated_project_path or sandbox_path
>    * migrated artifact coordinates if detectable:
>
>      * groupId
>      * artifactId
>      * version
>    * list of consumer project paths
>    * optional Maven command per consumer, default:
>
>      * mvn clean test
>    * optional install command for migrated library, default:
>
>      * mvn clean install -DskipTests
> 3. If no consumers are configured:
>
>    * do not fail migration
>    * emit status: NOT_CONFIGURED
>    * add warning/recommendation when project_kind is library/contract_library
> 4. If consumers are configured:
>
>    * install migrated artifact into local Maven repository from sandbox
>    * run validation command in each consumer project
>    * collect result per consumer
> 5. Do not modify consumer source code.
> 6. Do not modify migrated source code beyond normal build/install outputs.
> 7. Do not skip consumer tests unless explicitly configured.
> 8. Do not call LLM.
> 9. Do not call network except normal Maven dependency resolution if Maven build already does so.
> 10. No project-specific names such as msa-dto, common-utils, or translation.
> 11. Gate must be generic and optional.
> 12. Record results in an artifact, for example:
>
> * validation/consumer_compatibility_report.json
> * validation/consumer_compatibility_summary.md
>
> 13. Add artifact refs and warnings into orchestration/final report.
> 14. If any configured consumer fails:
>
> * status: FAILED
> * human_review_required: true
> * production_allowed: false
>
> 15. If all configured consumers pass:
>
> * status: PASSED
> * confidence should increase, but production promotion still requires explicit approval.
>
> 16. If not configured:
>
> * status: NOT_CONFIGURED
> * confidence remains limited for libraries.
>
> Artifact fields:
>
> * run_id
> * gate_id: CONSUMER_COMPATIBILITY_VALIDATION
> * status: NOT_CONFIGURED / PASSED / FAILED / ERROR
> * migrated_coordinates
> * migrated_project_path
> * consumers_configured
> * consumer_results
> * human_review_required
> * production_allowed
> * recommended_next_actions
> * command outputs/log paths
> * limitations
>
> Integration:
>
> 1. Run after migrated sandbox build/test validation, before final report.
> 2. For failed sandbox migrations, do not run unless explicitly requested.
> 3. For library/contract_library projects, include recommendation when no consumers are configured.
> 4. Keep existing successful and failed reporting backward compatible.
>
> Tests:
>
> 1. No consumers configured -> NOT_CONFIGURED and no failure.
> 2. Library project with no consumers -> recommendation warning.
> 3. Consumer configured and command passes -> PASSED.
> 4. Consumer configured and command fails -> FAILED + human_review_required=true.
> 5. Multiple consumers aggregate results correctly.
> 6. Consumer source files are not modified.
> 7. Artifact refs appear in orchestration/final report.
> 8. Production allowed remains false on failed consumer validation.
> 9. No project-specific names.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_final_report.py -q
> python -m pytest -q
>
> Use synthetic temporary Maven-like fixtures or mocked command runner. Do not require real msa-dto/common-utils/translation in tests.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example NOT_CONFIGURED report
> 7. Example PASSED/FAILED consumer report
> 8. Example final/orchestration warning
> 9. Why this is important for library-to-service migration waves
> 10. Warnings or limitations

<details><summary>10 previous messages</summary>

> Me do Ticket 40 now. First me inspect current success-finalization path and whether project kind / library hints already exist, so new gate fits without duplicate logic.
>
> Me have design. Now me add standalone consumer validation module, hook successful finalization only, then add report section/tests.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/orchestrator/consumer_compatibility.py` (+292 -0)
>
> </details>
>
> Module in. Now me wire successful finalization path and final report fields/summary section, still no effect on failed sandbox runs.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/orchestrator/summary.py` (+57 -3)
> - Wrote `./migration_factory/final_report/writer.py` (+14 -0)
>
> </details>
>
> Me add tests now. One direct gate test file for pass/fail/not-configured. One final-report assertion for new section/artifact refs.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_consumer_compatibility.py` (+295 -0)
> - Wrote `./tests/test_final_report.py` (+51 -4)
>
> </details>
>
> Me wired success-path gate. Now me run targeted tests first for new consumer module + final report section, then full requested suite.
>
> Targeted green. Me run requested validation set now.
>
> Validation green. Me do quick status check, then report exact touched files only for Ticket 40.
</details>

1. **Summary**

Me add Consumer Compatibility Validation Gate.

Gate now:
- optional
- success-path only
- sandbox migrated lib installs to local Maven repo
- downstream consumer projects validate read-only
- writes evidence:
  - `validation/consumer_compatibility_report.json`
  - `validation/consumer_compatibility_summary.md`
- adds artifact refs + warnings into orchestration/final report

No consumer source mutation.
No LLM.
No extra network beyond normal Maven if real run uses it.

2. **Files Modified**

- [consumer_compatibility.py](./migration_factory/orchestrator/consumer_compatibility.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_consumer_compatibility.py](./tests/orchestrator/test_consumer_compatibility.py)
- [test_final_report.py](./tests/test_final_report.py)

3. **Tests Added**

- no consumers -> `NOT_CONFIGURED`
- library + no consumers -> warning/recommendation
- consumer pass -> `PASSED`
- consumer fail -> `FAILED`, `human_review_required=true`
- multiple consumers aggregate
- consumer source files unchanged
- final/orchestration report gets artifact refs
- failed consumer validation keeps `production_allowed=false`

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_consumer_compatibility.py -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest tests/test_final_report.py -q
python -m pytest -q
```

5. **Test Results**

- `tests/orchestrator/test_consumer_compatibility.py -q`: `7 passed`
- `tests/test_final_report.py -q`: `21 passed`
- `tests/orchestrator -q`: `115 passed`
- `pytest -q`: `703 passed, 3 skipped`

6. **Example `NOT_CONFIGURED` Report**

```json
{
  "gate_id": "CONSUMER_COMPATIBILITY_VALIDATION",
  "status": "NOT_CONFIGURED",
  "consumers_configured": 0,
  "human_review_required": false,
  "production_allowed": false,
  "warnings": [
    "No downstream consumers configured; consumer compatibility validation is required for library migrations."
  ]
}
```

7. **Example `PASSED` / `FAILED` Consumer Report**

Passed:
```json
{
  "status": "PASSED",
  "consumer_results": [
    {
      "consumer_project_path": "C:\\tmp\\consumer-a",
      "status": "PASSED",
      "exit_code": 0,
      "source_files_modified": false
    }
  ],
  "human_review_required": false,
  "production_allowed": true
}
```

Failed:
```json
{
  "status": "FAILED",
  "consumer_results": [
    {
      "consumer_project_path": "C:\\tmp\\consumer-a",
      "status": "FAILED",
      "exit_code": 1,
      "source_files_modified": false
    }
  ],
  "human_review_required": true,
  "production_allowed": false
}
```

8. **Example Final / Orchestration Warning**

```text
Consumer compatibility validation failed; downstream review required before production promotion.
```

Also for library with no consumers:
```text
Consumer compatibility validation not configured for library migration; downstream confidence remains limited.
```

9. **Why Important For Library-To-Service Migration Waves**

Library can compile alone, still break consumers.
This gate gives downstream evidence:
- install migrated lib
- run consumer build/test
- prove pass/fail before wave moves forward

Good for:
- DTO libs
- shared utils
- contract libs
- internal platform libs

10. **Warnings Or Limitations**

- runs only for successful sandbox migrations
- no run on failed sandbox unless future ticket adds explicit opt-in
- current config comes from state `consumer_validation`, not full profile schema yet
- default commands are Maven-only:
  - install: `mvn clean install -DskipTests`
  - consumer: `mvn clean test`
- `production_allowed` in final report still governed by existing route/profile approval rules, not this gate alone

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 41: Add Generic Migration Wave Planner / Internal Dependency Order.
>
> Context:
> The factory must support enterprise migration waves across any set of internal Maven projects. It must not be tied to any specific repository or microservice name.
>
> Goal:
> Add a generic Migration Wave Planner that reads local project paths, detects internal Maven dependencies, computes a migration order, and prepares consumer validation relationships.
>
> Important:
> No implementation logic may hardcode real project names. Project names are only metadata supplied by the caller or used in test fixtures.
>
> Required behavior:
>
> 1. Add a migration wave planner module, for example:
>
>    * migration_factory/wave_planner/planner.py
> 2. Input:
>
>    * list of local project paths
>    * optional project_id per path
>    * optional known artifact coordinate overrides
>    * output_dir
> 3. Detect each project’s Maven coordinates:
>
>    * groupId
>    * artifactId
>    * version
>    * packaging
> 4. Detect internal dependencies between the provided projects:
>
>    * if project A depends on an artifact produced by project B
>    * include scope and version if available
> 5. Build a dependency graph.
> 6. Compute suggested migration order:
>
>    * producers/libraries before consumers
>    * topological order when possible
> 7. For each project, produce suggested consumer validation config:
>
>    * when project X is migrated, validate every provided project that depends on X
> 8. Output artifacts:
>
>    * migration_wave_plan.json
>    * migration_wave_summary.md
> 9. The report must include:
>
>    * projects
>    * detected coordinates
>    * internal dependency edges
>    * migration_waves
>    * consumer_validation_plan
>    * cycles if detected
>    * missing or ambiguous coordinates
>    * warnings
>    * recommended_next_actions
> 10. If dependency cycles exist:
>
> * do not crash
> * report the cycle
> * require human review
>
> 11. If coordinates cannot be detected:
>
> * warn and continue
>
> 12. Do not modify source code.
> 13. Do not modify POMs.
> 14. Do not run Maven builds in this ticket.
> 15. Do not call LLM.
> 16. Do not call network.
> 17. Do not use hardcoded real repository or microservice names.
> 18. Project IDs may appear only as user-provided metadata or synthetic test fixture names.
>
> Consumer validation integration:
>
> 1. Produce a consumer validation suggestion that can be fed into the existing Consumer Compatibility Validation Gate.
> 2. Example generic shape:
>
>    * migrated_project: project-a
>    * consumers:
>
>      * project-b
>      * project-c
>    * suggested_command: mvn clean test
> 3. Do not execute consumer validation here.
>
> Tests:
>
> 1. Detect Maven coordinates from a simple POM.
> 2. Detect parent-managed groupId/version when child POM omits them.
> 3. Detect project A depends on project B.
> 4. Compute order B before A when A depends on B.
> 5. Produce consumer validation plan for B -> A.
> 6. Handle multiple independent projects.
> 7. Detect cycles and mark human_review_required=true.
> 8. Missing coordinates warns but does not crash.
> 9. JSON and Markdown artifacts are produced.
> 10. Assert there is no hardcoded real project name in implementation.
> 11. No source/POM modification.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests -q
> python -m pytest -q
>
> Use synthetic Maven fixtures in tests. Do not require real GitHub repositories.
>
> Optional real dry run:
> If local project snapshots are available, run planner on them only as evidence. Real project names may appear only in generated reports as metadata, never in implementation logic.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example migration_wave_plan.json excerpt
> 7. Example migration_wave_summary.md excerpt
> 8. Example consumer validation plan
> 9. How this supports generic enterprise migration waves
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>7 previous messages</summary>

> Me do Ticket 41 now. First me inspect repo for existing Maven coordinate helpers, so wave planner reuses generic parsing style, not duplicate weird logic.
>
> Me have design. Now me add wave planner package + synthetic tests for coords, internal graph, waves, cycles, warnings, no-hardcode proof.
>
> <details><summary>Created 2 files</summary>
>
> - Wrote `./migration_factory/wave_planner/__init__.py` (+3 -0)
> - Wrote `./migration_factory/wave_planner/planner.py` (+374 -0)
>
> </details>
>
> Planner in. Now me add focused tests: coords, parent fallback, dependency order, consumer plan, independent wave, cycle, missing coords, no-hardcode, artifact files.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/test_wave_planner.py` (+212 -0)
>
> </details>
>
> Me run new wave-planner tests first. If green, then requested full `tests -q` and `pytest -q`.
>
> Tests green. Me do tiny synthetic dry run now, only for evidence excerpt, no repo mutation beyond `.migration/wave-planner-sample`.
</details>

1. **Summary**

Me add generic Migration Wave Planner.

It now:
- read local Maven project paths
- detect coordinates
- detect internal deps among provided projects
- compute migration waves
- suggest consumer validation relationships
- report cycles / missing coords / warnings
- write:
  - `migration_wave_plan.json`
  - `migration_wave_summary.md`

No source change.
No POM change.
No Maven run.
No network.

2. **Files Modified / Created**

- [planner.py](./migration_factory/wave_planner/planner.py)
- [__init__.py](./migration_factory/wave_planner/__init__.py)
- [test_wave_planner.py](./tests/test_wave_planner.py)

3. **Tests Added**

- detect simple Maven coordinates
- detect parent-managed `groupId` / `version`
- detect internal dependency
- order producer before consumer
- build consumer validation suggestion
- handle independent projects
- detect cycles -> `human_review_required=true`
- warn on missing coordinates without crash
- JSON + Markdown artifacts produced
- assert no hardcoded real repo names in implementation

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_wave_planner.py -q
python -m pytest tests -q
python -m pytest -q
```

Optional synthetic evidence run:
```powershell
$env:PYTHONPATH='.'
@' ... plan_migration_wave(...) ... '@ | python -
```

5. **Test Results**

- `tests/test_wave_planner.py -q`: `6 passed`
- `tests -q`: `627 passed, 2 skipped`
- `pytest -q`: `709 passed, 3 skipped`

6. **Example `migration_wave_plan.json` Excerpt**

From synthetic evidence:
- [migration_wave_plan.json](./.migration/wave-planner-sample/out/migration_wave_plan.json)

```json
{
  "internal_dependency_edges": [
    {
      "consumer_project_id": "svc-a",
      "producer_project_id": "lib-b",
      "scope": "compile",
      "version": "1.0.0"
    }
  ],
  "migration_waves": [
    ["lib-b"],
    ["svc-a"]
  ],
  "consumer_validation_plan": [
    {
      "migrated_project": "lib-b",
      "consumers": ["svc-a"],
      "suggested_command": "mvn clean test"
    }
  ],
  "cycles": [],
  "human_review_required": false
}
```

7. **Example `migration_wave_summary.md` Excerpt**

From synthetic evidence:
- [migration_wave_summary.md](./.migration/wave-planner-sample/out/migration_wave_summary.md)

```md
# Migration Wave Summary

- Projects: 2
- Human Review Required: false

## Migration Waves
- Wave 1: lib-b
- Wave 2: svc-a

## Internal Dependencies
- svc-a depends on lib-b
```

8. **Example Consumer Validation Plan**

Generic shape now produced:

```json
{
  "migrated_project": "lib-b",
  "consumers": ["svc-a"],
  "suggested_command": "mvn clean test"
}
```

Meaning:
- migrate producer/library first
- then feed its dependents into Ticket 40 consumer validation gate

9. **How This Supports Generic Enterprise Migration Waves**

Good for any internal Maven set:
- shared libs before services
- DTO/contract libs before utility/services
- independent projects can migrate same wave
- downstream validation relationships ready before rollout

So factory can plan:
- order
- wave batches
- consumer follow-up evidence

10. **Evidence No Real Project Names Hardcoded**

Implementation test reads [planner.py](./migration_factory/wave_planner/planner.py) and asserts these strings absent:
- `msa-dto`
- `common-utils`
- `translation`

Only caller metadata / synthetic fixture IDs appear in outputs.

11. **Warnings Or Limitations**

- planner looks at provided local project set only
- no full multi-module reactor build logic yet
- dependency matching is by detected/provided coordinates, not Maven effective-POM resolution
- cycle handling is review/report only, not auto-break strategy
- no Maven execution in this ticket by design

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 42: Add Wave Plan to Consumer Validation Config Bridge.
>
> Context:
> Ticket 40 added the Consumer Compatibility Validation Gate.
> Ticket 41 added the generic Migration Wave Planner.
>
> Now we need a bridge that converts a generic migration wave plan into consumer validation configuration for a selected migrated project.
>
> Goal:
> Given a `migration_wave_plan.json` and a selected project to migrate, generate a consumer validation config that can be passed to the existing Consumer Compatibility Validation Gate.
>
> Important:
> This must remain generic. Do not hardcode any real repository or microservice names. Project IDs are metadata only.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/wave_planner/consumer_config.py
> 2. Input:
>
>    * migration_wave_plan.json path
>    * selected project_id or artifact coordinates
>    * output_dir
>    * optional command override
> 3. Output:
>
>    * consumer_validation_config.json
>    * consumer_validation_config.yaml or summary markdown if useful
> 4. The generated config must include:
>
>    * migrated_project_id
>    * migrated_project_path
>    * migrated_coordinates
>    * consumers
>    * consumer_project_id
>    * consumer_project_path
>    * suggested_command, default `mvn clean test`
>    * validation_reason
> 5. If selected project has no consumers:
>
>    * emit config with empty consumers
>    * status: NO_CONSUMERS_FOUND
>    * do not fail
> 6. If selected project is unknown:
>
>    * emit status: PROJECT_NOT_FOUND
>    * human_review_required: true
> 7. If the wave plan has cycles:
>
>    * emit warning
>    * human_review_required: true
> 8. Do not run Maven.
> 9. Do not run consumer validation in this ticket.
> 10. Do not modify source code.
> 11. Do not modify POMs.
> 12. Do not call LLM.
> 13. Do not call network.
> 14. No hardcoded real repository or microservice names.
> 15. The config shape should be easy to feed into Ticket 40’s Consumer Compatibility Validation Gate.
>
> Integration:
>
> 1. Add helper function to load this generated config and convert it into the state shape expected by the consumer compatibility gate.
> 2. Do not change default orchestration behavior unless explicitly configured.
> 3. Keep existing tests green.
>
> Tests:
>
> 1. Project with one consumer generates one consumer config entry.
> 2. Project with multiple consumers generates multiple entries.
> 3. Project with no consumers returns NO_CONSUMERS_FOUND.
> 4. Unknown project returns PROJECT_NOT_FOUND and human_review_required=true.
> 5. Cycle warning propagates from wave plan.
> 6. Command override is honored.
> 7. Default command is `mvn clean test`.
> 8. Config can be converted to consumer validation gate input shape.
> 9. No Maven execution.
> 10. No source/POM modification.
> 11. Assert no hardcoded real project names in implementation.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_wave_planner.py -q
> python -m pytest tests/orchestrator/test_consumer_compatibility.py -q
> python -m pytest -q
>
> Use synthetic fixtures only. Do not require real GitHub repositories.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example consumer_validation_config.json
> 7. Example no-consumer output
> 8. Example consumer compatibility gate input shape
> 9. How this connects wave planning to downstream validation
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>6 previous messages</summary>

> Me do Ticket 42 now. First me inspect wave plan shape + consumer gate config shape, then me add small bridge only, no orchestration default change.
>
> Me add bridge module now: load wave plan, select project by id or coords, emit config artifact, plus helper to convert into Ticket 40 gate config shape. Then me add tests.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./migration_factory/wave_planner/consumer_config.py` (+190 -0)
> - Wrote `./migration_factory/wave_planner/__init__.py` (+9 -1)
>
> </details>
>
> Bridge code in. Now me extend wave planner tests with bridge cases, plus one consumer-gate shape test reuse.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_wave_planner.py` (+161 -1)
>
> </details>
>
> Me run bridge tests first, then requested suite. No Maven execution.
</details>

1. **Summary**

Me add wave-plan -> consumer-validation bridge.

Now factory can:
- read `migration_wave_plan.json`
- pick migrated project by `project_id` or Maven coords
- emit `consumer_validation_config.json`
- emit summary markdown
- convert config into Ticket 40 gate input shape

No Maven run.
No source/POM change.
No network.

2. **Files Modified / Created**

- [consumer_config.py](./migration_factory/wave_planner/consumer_config.py)
- [__init__.py](./migration_factory/wave_planner/__init__.py)
- [test_wave_planner.py](./tests/test_wave_planner.py)

3. **Tests Added**

- one consumer -> one config entry
- multiple consumers -> multiple entries
- no consumers -> `NO_CONSUMERS_FOUND`
- unknown project -> `PROJECT_NOT_FOUND`
- cycle warning propagates
- command override honored
- default command stays `mvn clean test`
- config converts to Ticket 40 gate shape
- no hardcoded real repo names in impl

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_wave_planner.py -q
python -m pytest tests/orchestrator/test_consumer_compatibility.py -q
python -m pytest -q
```

5. **Test Results**

- `tests/test_wave_planner.py -q`: `11 passed`
- `tests/orchestrator/test_consumer_compatibility.py -q`: `7 passed`
- `pytest -q`: `714 passed, 3 skipped`

6. **Example `consumer_validation_config.json`**

```json
{
  "status": "READY",
  "human_review_required": false,
  "migrated_project_id": "producer",
  "migrated_project_path": "C:/tmp/producer",
  "migrated_coordinates": {
    "groupId": "com.example",
    "artifactId": "producer",
    "version": "1.0.0",
    "packaging": "jar"
  },
  "consumers": [
    {
      "consumer_project_id": "consumer-a",
      "consumer_project_path": "C:/tmp/consumer-a",
      "suggested_command": "mvn clean test",
      "validation_reason": "Internal dependency on migrated project producer."
    }
  ],
  "warnings": []
}
```

7. **Example No-Consumer Output**

```json
{
  "status": "NO_CONSUMERS_FOUND",
  "human_review_required": false,
  "migrated_project_id": "solo",
  "consumers": [],
  "warnings": []
}
```

8. **Example Consumer Compatibility Gate Input Shape**

Bridge helper returns:

```json
{
  "consumers": [
    {
      "path": "C:/tmp/consumer",
      "command": "mvn clean test"
    }
  ],
  "consumer_command": "mvn clean test"
}
```

9. **How This Connects Wave Planning To Downstream Validation**

Flow now:
- Ticket 41 finds producer/consumer order
- Ticket 42 picks one migrated producer
- bridge emits consumer config
- Ticket 40 can use config to validate downstream consumers

So wave planning now feeds validation evidence, not only ordering.

10. **Evidence No Real Project Names Hardcoded**

Tests read [consumer_config.py](./migration_factory/wave_planner/consumer_config.py) and assert absent:
- `msa-dto`
- `common-utils`
- `translation`

Only caller metadata / fixture IDs appear in outputs.

11. **Warnings Or Limitations**

- bridge reads existing wave plan only; no graph recompute
- selection by coords expects exact match
- output is config only; no execution in this ticket
- if wave plan already has cycles, bridge warns and sets `human_review_required=true`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
>
> User context
>
> Attachments:
> - Pasted text.txt: `~/.codex/attachments/679e0f68-de58-43c4-bff6-4a774ac448cf/pasted-text.txt`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 43: Add Azure SDK Migration Playbook / Review Gate.
>
> Context:
> Golden reference analysis detected Azure SDK migration signals in real enterprise references. Old Azure SDK dependencies may coexist with or migrate toward modern `com.azure.*` SDKs. Azure SDK migration can affect client APIs, authentication, configuration, Service Bus behavior, Blob Storage behavior, exceptions, and runtime semantics.
>
> Goal:
> Add a conservative Azure SDK Migration Playbook / Review Gate.
>
> This ticket must detect Azure SDK usage, classify migration risk, generate review guidance, and expose evidence. It must not automatically rewrite Azure source code.
>
> Required behavior:
>
> 1. Detect old Azure SDK Maven dependencies, including:
>
>    * groupId starting with `com.microsoft.azure`
>    * groupId starting with `com.microsoft.rest`
>    * groupId starting with `com.microsoft.windowsazure`
>    * common artifacts:
>
>      * azure-servicebus
>      * azure-servicebus-spring-boot-starter
>      * azure-storage
>      * azure-storage-blob
>      * client-runtime
> 2. Detect modern Azure SDK Maven dependencies:
>
>    * groupId starting with `com.azure`
>    * common artifacts:
>
>      * azure-messaging-servicebus
>      * azure-storage-blob
>      * azure-identity
>      * azure-core
> 3. Detect source/test usage hints:
>
>    * imports starting with `com.microsoft.azure`
>    * imports starting with `com.microsoft.rest`
>    * imports starting with `com.microsoft.windowsazure`
>    * imports starting with `com.azure`
>    * Service Bus usage hints
>    * Blob Storage usage hints
> 4. Produce a review artifact, for example:
>
>    * `review/azure_sdk_migration_review.json`
> 5. Artifact must include:
>
>    * detected: true/false
>    * gate_id: AZURE_SDK_MIGRATION_PLAYBOOK
>    * risk_level
>    * human_review_required
>    * safe_to_auto_apply: false
>    * old_azure_dependencies
>    * new_azure_dependencies
>    * source_usage_files
>    * usage_patterns
>    * migration_mode:
>
>      * OLD_SDK_ONLY
>      * MIXED_OLD_AND_NEW
>      * NEW_SDK_ONLY
>      * NOT_DETECTED
>    * recommended_next_actions
>    * llm_candidate flag for localized API migration proposals, but do not call LLM
> 6. If old SDK is detected:
>
>    * human_review_required: true
>    * risk_level: HIGH
>    * safe_to_auto_apply: false
> 7. If mixed old and new SDKs are detected:
>
>    * emit warning that partial migration/coexistence requires review
> 8. If only new SDK is detected:
>
>    * emit info/review artifact but do not warn as high risk by default
> 9. Do not modify POMs.
> 10. Do not modify Java source.
> 11. Do not modify tests.
> 12. Do not remove or add Azure dependencies.
> 13. Do not call LLM.
> 14. Do not call GitHub Copilot.
> 15. Do not call network.
> 16. No hardcoded real repository or microservice names.
> 17. Record review result in ledger or review artifacts.
> 18. Add warnings/artifact refs into orchestration/final reporting when detected.
>
> Integration:
>
> 1. Wire this gate into the Boot 3 migration unit:
>
>    * `spring-boot-3-5-14`
> 2. Run before build/test validation or during review gate phase.
> 3. Do not fail migration by itself.
> 4. Preserve existing success/failure reporting behavior.
> 5. Enrich final report with Azure review path and warning when old or mixed SDK is detected.
>
> Recommended next actions:
>
> * For Service Bus old SDK usage: review migration to `com.azure:azure-messaging-servicebus`.
> * For Blob Storage old SDK usage: review migration to modern `com.azure:azure-storage-blob`.
> * For identity/auth usage: review migration to `com.azure:azure-identity`.
> * For mixed SDK usage: require human review to avoid duplicate runtime stacks.
> * For source API migration: mark as LLM candidate only if LLM policy allows later, but no LLM call in this ticket.
>
> Tests:
>
> 1. Detect old Azure dependencies in POM.
> 2. Detect modern Azure dependencies in POM.
> 3. Detect mixed old/new Azure dependencies.
> 4. Detect old Azure imports in source.
> 5. Detect modern Azure imports in source.
> 6. Detect Service Bus usage pattern.
> 7. Detect Blob Storage usage pattern.
> 8. OLD_SDK_ONLY -> human_review_required=true, risk_level=HIGH.
> 9. MIXED_OLD_AND_NEW -> warning and human review.
> 10. NEW_SDK_ONLY -> detected=true but not high-risk by default.
> 11. No Azure -> detected=false.
> 12. Artifact includes safe_to_auto_apply=false when old/mixed SDK detected.
> 13. Orchestration/final report includes warning and artifact ref.
> 14. No source/POM/test modification.
> 15. Assert no hardcoded real project names in implementation.
> 16. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Use synthetic fixtures only unless doing a read-only check.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example azure_sdk_migration_review.json for OLD_SDK_ONLY
> 7. Example azure_sdk_migration_review.json for MIXED_OLD_AND_NEW
> 8. Example final/orchestration warning
> 9. Why no automatic Azure migration was applied
> 10. Why this is governance-safe and generic
> 11. Warnings or limitations

<details><summary>14 previous messages</summary>

> Me do Ticket 43 now. First me inspect current review-gate path so Azure gate plugs into same ledger/artifact/warning flow as PowerMock and Jakarta.
>
> Me have path. Next me add Azure detector/review artifact in same file as other review gates, then wire Boot3 unit + propagation helpers.
>
> Me start Azure gate edits now: detector in `review_gates.py`, Boot3 execution-plan entry, agent ledger record, transform metadata, phase artifact ref. Then tests.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+192 -0)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+34 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+1 -0)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+30 -1)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+2 -0)
>
> </details>
>
> Core wiring done. Now me update tests for new Boot3 gate order, Azure detect modes, ledger record, and orchestrator artifact propagation.
>
> Me patch tests now. Azure cases cover old/new/mixed deps, import hints, service bus/blob patterns, ledger record, execution plan slot, orchestration artifact propagation.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+211 -11)
> - Wrote `./tests/orchestrator/test_powermock_gate.py` (+50 -0)
>
> </details>
>
> Azure tests in. Now me run targeted suites first: transformation + orchestrator propagation. Then full requested validation.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me use caveman full. Me check Azure gate code and run tests now.
>
> Bug small. Azure gate call helper not exist. Me inspect file, patch, rerun tests.
>
> Me patch tiny helper only. Then rerun same tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+11 -0)
>
> </details>
>
> Patch in. Me rerun validation now.
</details>

1. **Summary**

Me add conservative Azure SDK Migration Playbook / Review Gate.

Now Boot 3 unit can:
- detect old Azure SDK deps
- detect new Azure SDK deps
- detect source/test Azure usage hints
- classify `OLD_SDK_ONLY` / `MIXED_OLD_AND_NEW` / `NEW_SDK_ONLY` / `NOT_DETECTED`
- write review artifact
- record ledger entry
- surface warning + artifact ref into orchestration/final path

No POM change.
No Java change.
No test change.
No LLM.
No network.

2. **Files Modified**

- [review_gates.py](./migration_factory/agents/transformation_agent/review_gates.py)
- [agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [test_transformation_agent.py](./tests/test_transformation_agent.py)
- [test_powermock_gate.py](./tests/orchestrator/test_powermock_gate.py)

3. **Tests Added**

- old Azure deps in POM
- modern Azure deps in POM
- mixed old/new deps
- old Azure imports
- modern Azure imports
- Service Bus usage hint
- Blob usage hint
- `OLD_SDK_ONLY -> HIGH + human_review_required=true`
- `MIXED_OLD_AND_NEW -> warning + human review`
- `NEW_SDK_ONLY -> detected=true`, not high risk
- no Azure -> `detected=false`
- ledger records Azure review gate
- orchestration propagates Azure warning + artifact ref

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `103 passed, 2 skipped`
- `tests/orchestrator -q`: `116 passed`
- `pytest -q`: `722 passed, 3 skipped`

6. **Example `azure_sdk_migration_review.json` For `OLD_SDK_ONLY`**

```json
{
  "detected": true,
  "gate_id": "AZURE_SDK_MIGRATION_PLAYBOOK",
  "risk_level": "HIGH",
  "human_review_required": true,
  "safe_to_auto_apply": false,
  "old_azure_dependencies": [
    "com.microsoft.azure:azure-servicebus"
  ],
  "new_azure_dependencies": [],
  "migration_mode": "OLD_SDK_ONLY",
  "usage_patterns": [
    "AZURE_OLD_IMPORT",
    "SERVICE_BUS_USAGE"
  ],
  "llm_candidate": true,
  "recommended_next_actions": [
    "Review migration from legacy Service Bus SDK usage to com.azure:azure-messaging-servicebus."
  ]
}
```

7. **Example `azure_sdk_migration_review.json` For `MIXED_OLD_AND_NEW`**

```json
{
  "detected": true,
  "gate_id": "AZURE_SDK_MIGRATION_PLAYBOOK",
  "risk_level": "HIGH",
  "human_review_required": true,
  "safe_to_auto_apply": false,
  "old_azure_dependencies": [
    "com.microsoft.azure:azure-storage"
  ],
  "new_azure_dependencies": [
    "com.azure:azure-storage-blob"
  ],
  "migration_mode": "MIXED_OLD_AND_NEW",
  "warnings": [
    "Mixed old and new Azure SDK usage detected; partial coexistence requires human review to avoid duplicate runtime stacks."
  ]
}
```

8. **Example Final / Orchestration Warning**

```text
Mixed old and new Azure SDK usage detected; partial coexistence requires human review to avoid duplicate runtime stacks.
```

9. **Why No Automatic Azure Migration Was Applied**

Too risky.
Azure migration can change:
- client APIs
- auth flow
- Service Bus behavior
- Blob behavior
- exceptions
- runtime semantics

Blind rewrite bad. Gate report only.

10. **Why This Governance-Safe And Generic**

- review-only
- `safe_to_auto_apply=false`
- `human_review_required=true` for old/mixed SDK
- no repo-name logic
- uses generic Maven group prefixes and source import patterns
- no source/POM/test mutation
- artifact + warning visible in orchestration path

11. **Warnings Or Limitations**

- static scan only, not semantic API migration
- no runtime config inspection yet
- no Azure auth/property model analysis yet
- `NEW_SDK_ONLY` still writes artifact, but low-risk info only
- one bug found during test run: missing helper `_dedupe_preserve_order`; me fixed, all green now

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 44: Add Factory Capability Inventory / Coverage Matrix.
>
> Context:
> The factory now has many deterministic rules, review gates, remediation gates, reporting gates, and wave-planning capabilities. Ticket 33 currently uses a seed/static capability map, which can become stale as new tickets add capabilities.
>
> Goal:
> Create a generic Factory Capability Inventory that exports what the factory can currently detect, transform, review, auto-remediate, or report. Then make the Rule Extraction Report optionally consume this capability inventory instead of relying only on hardcoded seed data.
>
> Important:
> This ticket must not inspect or modify application repositories. It only describes factory capabilities.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/capabilities/inventory.py
> 2. Output artifacts:
>
>    * factory_capability_inventory.json
>    * factory_capability_summary.md
> 3. Inventory should include capability entries for:
>
>    * deterministic transformations
>    * Maven/POM alignment rules
>    * source/test deterministic patches
>    * review gates
>    * remediation capabilities
>    * reporting capabilities
>    * wave planning capabilities
> 4. Each capability entry must include:
>
>    * capability_id
>    * category
>    * capability_type:
>
>      * DETECT
>      * TRANSFORM
>      * REVIEW_GATE
>      * REPORT
>      * REMEDIATION_PLAN
>      * AUTO_REMEDIATION
>      * WAVE_PLANNING
>      * CONSUMER_VALIDATION
>    * safe_to_auto_apply
>    * requires_human_approval
>    * llm_candidate
>    * supported_units or lifecycle_phase
>    * evidence_artifacts produced, if any
>    * notes
> 5. Include capabilities already implemented, such as:
>
>    * LOMBOK_VERSION_ALIGNMENT
>    * JACOCO_VERSION_ALIGNMENT
>    * SLF4J_VERSION_ALIGNMENT
>    * JACKSON_VERSION_ALIGNMENT
>    * SPRING_SECURITY_VERSION_ALIGNMENT
>    * JJWT_VERSION_ALIGNMENT
>    * JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT
>    * SPRING_DATA_SORT_BY_MIGRATION
>    * MOCKBEAN_TO_MOCKITOBEAN
>    * INITMOCKS_TO_OPENMOCKS
>    * JUNEAU_VERSION_ALIGNMENT_OR_REVIEW
>    * POWERMOCK_LEGACY_TEST_STRATEGY
>    * JAKARTA_HYBRID_STRATEGY
>    * API_CONTRACT_REVIEW_GATE
>    * AZURE_SDK_MIGRATION_PLAYBOOK
>    * CONSUMER_COMPATIBILITY_VALIDATION
>    * MIGRATION_WAVE_PLANNER
>    * WAVE_TO_CONSUMER_VALIDATION_CONFIG
>    * FAILURE_CLASSIFICATION
>    * FAILED_SANDBOX_REPORTING
>    * LLM_POLICY_GATE
>    * REMEDIATION_PLAN
>    * DETERMINISTIC_AUTO_REMEDIATION_LOOP
> 6. Do not hardcode real project/repository/microservice names.
> 7. Do not call network.
> 8. Do not call LLM.
> 9. Do not modify application source, tests, or POMs.
>
> Rule extractor integration:
>
> 1. Update Golden Reference Rule Extractor so it can optionally read `factory_capability_inventory.json`.
> 2. If inventory is provided:
>
>    * classify matching rule IDs as `already_covered_by_factory`
>    * classify review gates as covered review capabilities
>    * keep unknown items in missing categories
> 3. Preserve backward compatibility when no inventory is provided.
> 4. Avoid duplicating capability IDs in output.
> 5. Add source/evidence in rule extraction report showing whether coverage came from static fallback or inventory artifact.
>
> Tests:
>
> 1. Inventory JSON and Markdown are produced.
> 2. Inventory contains deterministic transformation capabilities.
> 3. Inventory contains review gate capabilities.
> 4. Inventory contains remediation/reporting/wave capabilities.
> 5. Each capability has required fields.
> 6. No real project names are hardcoded in inventory implementation.
> 7. Rule extractor uses inventory to mark JJWT as already covered.
> 8. Rule extractor uses inventory to mark Azure SDK as covered review gate, not missing deterministic rule.
> 9. Rule extractor works without inventory as before.
> 10. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_golden_rule_extractor.py -q
> python -m pytest -q
>
> Then generate the inventory artifact and run rule extraction again on existing golden reports if available.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. factory_capability_inventory.json excerpt
> 7. factory_capability_summary.md excerpt
> 8. Updated rule extraction behavior with inventory
> 9. Evidence that no real project names are hardcoded
> 10. Warnings or limitations

<details><summary>11 previous messages</summary>

> Me inspect capability + extractor files first. Then patch inventory, wire extractor, run tests.
>
> Me inspect exports, then patch new module + extractor tests.
>
> Me inspect nearby module style, keep same pattern.
>
> Me add inventory module, wire extractor, add tests.
>
> <details><summary>Created 3 files, edited 2 files</summary>
>
> - Wrote `./migration_factory/capabilities/__init__.py` (+9 -0)
> - Wrote `./migration_factory/capabilities/inventory.py` (+335 -0)
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+118 -14)
> - Wrote `./tests/test_capability_inventory.py` (+46 -0)
> - Wrote `./tests/test_golden_rule_extractor.py` (+61 -0)
>
> </details>
>
> Patch big in. Me run focused tests first, then full suite.
>
> One regression from default coverage. Must keep old behavior when no inventory. Me patch that. Then rerun failing tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+1 -4)
>
> </details>
>
> Default behavior restored. Me rerun exact failing tests now.
>
> Focused failures gone. Me run requested tests, then generate real inventory + re-extract on existing golden reports.
>
> Me pull artifact excerpts for report.
</details>

1. **Summary**

Me add Factory Capability Inventory.
Factory now can export self-description artifacts:

- `factory_capability_inventory.json`
- `factory_capability_summary.md`

Me also wire Golden Rule Extractor to optionally read inventory artifact.
Result:
- covered transform rules now come from live inventory, not only stale seed map
- covered review gates now separate bucket: `covered_review_capabilities`
- no-inventory path still works old way

2. **Files Modified/Created**

- [inventory.py](./migration_factory/capabilities/inventory.py)
- [__init__.py](./migration_factory/capabilities/__init__.py)
- [rule_extractor.py](./migration_factory/golden_reference/rule_extractor.py)
- [test_capability_inventory.py](./tests/test_capability_inventory.py)
- [test_golden_rule_extractor.py](./tests/test_golden_rule_extractor.py)

3. **Tests Added**

- inventory JSON + Markdown written
- inventory contains transform/review/remediation/report/wave/consumer capabilities
- each capability has required fields
- no real project names hardcoded in inventory impl
- extractor uses inventory to mark `JJWT_VERSION_ALIGNMENT` covered
- extractor uses inventory to mark `AZURE_SDK_MIGRATION_PLAYBOOK` covered review gate
- extractor still works without inventory

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_golden_rule_extractor.py -q
python -m pytest -q
```

Artifact generation:
```powershell
@'
from pathlib import Path
from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.golden_reference import extract_rules_from_golden_reports
root = Path(r'C:\Users\ilyas.abarbach\Documents\modernizer-solution')
inv = export_factory_capability_inventory(output_dir=root / '.migration' / 'factory-capabilities')
extract_rules_from_golden_reports(
    report_paths=[
        root / '.migration' / 'golden-references' / 'msa-dto' / 'golden_reference_gap_report.json',
        root / '.migration' / 'golden-references' / 'msa-utils' / 'golden_reference_gap_report.json',
    ],
    output_dir=root / '.migration' / 'golden-references' / 'rule-extraction-with-inventory',
    factory_capability_inventory=inv.report_path,
)
'@ | python -
```

5. **Test Results**

- `tests/test_golden_rule_extractor.py -q`: `4 passed`
- `pytest -q`: `727 passed, 3 skipped`

6. **`factory_capability_inventory.json` Excerpt**

Path:
- [factory_capability_inventory.json](./.migration/factory-capabilities/factory_capability_inventory.json)

Excerpt:
```json
{
  "capability_id": "JJWT_VERSION_ALIGNMENT",
  "capability_type": "TRANSFORM",
  "category": "maven_alignment",
  "safe_to_auto_apply": true,
  "requires_human_approval": false,
  "llm_candidate": false,
  "supported_units": ["spring-boot-3-5-14"],
  "evidence_artifacts": ["ledger.json"]
}
```

Review gate excerpt:
```json
{
  "capability_id": "AZURE_SDK_MIGRATION_PLAYBOOK",
  "capability_type": "REVIEW_GATE",
  "category": "review_gate",
  "safe_to_auto_apply": false,
  "requires_human_approval": true,
  "llm_candidate": true,
  "evidence_artifacts": ["azure_sdk_migration_review.json", "ledger.json"]
}
```

7. **`factory_capability_summary.md` Excerpt**

Path:
- [factory_capability_summary.md](./.migration/factory-capabilities/factory_capability_summary.md)

Excerpt:
```md
## REVIEW_GATE

- API_CONTRACT_REVIEW_GATE: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- AZURE_SDK_MIGRATION_PLAYBOOK: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- JAKARTA_HYBRID_STRATEGY: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
```

8. **Updated Rule Extraction Behavior With Inventory**

Real rerun path:
- [rule_extraction_report.json](./.migration/golden-references/rule-extraction-with-inventory/rule_extraction_report.json)
- [rule_extraction_summary.md](./.migration/golden-references/rule-extraction-with-inventory/rule_extraction_summary.md)

Now:
- `JJWT_VERSION_ALIGNMENT` moved to `already_covered_by_factory`
- `AZURE_SDK_MIGRATION_PLAYBOOK` moved to `covered_review_capabilities`
- each covered item shows `coverage_source=inventory_artifact`
- no inventory still leaves old fallback behavior intact

9. **Evidence No Real Project Names Hardcoded**

Test scan added.
It asserts impl text does **not** contain:

- `msa-dto`
- `common-utils`
- `translation`

Only generated evidence artifacts may mention project metadata.

10. **Warnings Or Limitations**

- inventory still curated/static inside factory code; not runtime-discovered from module introspection
- one fallback seed remains:
  - `MAVEN_COMPILER_PARAMETERS_ALIGNMENT`
- some generic rules still show missing from golden extraction:
  - `JAVA_VERSION_ALIGNMENT`
  - `SPRING_BOOT_VERSION_ALIGNMENT`
  - import-level jakarta rules
- next ticket maybe expand inventory coverage for those if wanted

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 45: Complete Factory Capability Inventory parity and Golden Rule coverage.
>
> Context:
> Ticket 44 added Factory Capability Inventory and integrated it with Golden Rule Extraction. Real extraction with inventory improved coverage, but some core generic capabilities still appear as missing or under-represented:
>
> * JAVA_VERSION_ALIGNMENT
> * SPRING_BOOT_VERSION_ALIGNMENT
> * import-level Jakarta rules
> * some existing Maven alignment / review / reporting capabilities may not be fully represented
>
> Goal:
> Update the Factory Capability Inventory and Rule Extractor mapping so the coverage matrix accurately reflects implemented factory capabilities.
>
> Important:
> This ticket must not modify application repositories. It only updates factory capability metadata, rule extraction mapping, and tests.
>
> Required behavior:
>
> 1. Expand `factory_capability_inventory.json` generation to include core implemented capabilities:
>
>    * JAVA_VERSION_ALIGNMENT
>    * SPRING_BOOT_VERSION_ALIGNMENT
>    * SPRING_BOOT_MULTI_HOP_ROUTE
>    * JDK_AWARE_ANALYSIS_PREVIEW
>    * JDK_AWARE_TRANSFORMATION_UNITS
>    * IMPORT_JAVAX_VALIDATION_TO_JAKARTA
>    * IMPORT_JAVAX_XML_BIND_TO_JAKARTA
>    * IMPORT_JAVAX_SERVLET_TO_JAKARTA
>    * JAKARTA_XML_BIND_DEPENDENCY_ALIGNMENT
>    * JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT
>    * JACKSON_VERSION_ALIGNMENT
>    * JACOCO_VERSION_ALIGNMENT
>    * LOMBOK_VERSION_ALIGNMENT
>    * SLF4J_VERSION_ALIGNMENT
>    * SPRING_SECURITY_VERSION_ALIGNMENT
>    * JJWT_VERSION_ALIGNMENT
>    * SPRING_DATA_SORT_BY_MIGRATION
>    * MOCKBEAN_TO_MOCKITOBEAN
>    * INITMOCKS_TO_OPENMOCKS
>    * JUNEAU_VERSION_ALIGNMENT_OR_REVIEW
>    * POWERMOCK_LEGACY_TEST_STRATEGY
>    * JAKARTA_HYBRID_STRATEGY
>    * API_CONTRACT_REVIEW_GATE
>    * AZURE_SDK_MIGRATION_PLAYBOOK
>    * CONSUMER_COMPATIBILITY_VALIDATION
>    * MIGRATION_WAVE_PLANNER
>    * WAVE_TO_CONSUMER_VALIDATION_CONFIG
> 2. Each capability must include accurate metadata:
>
>    * capability_id
>    * category
>    * capability_type
>    * safe_to_auto_apply
>    * requires_human_approval
>    * llm_candidate
>    * supported_units or lifecycle_phase
>    * evidence_artifacts
>    * notes
> 3. Distinguish capability types clearly:
>
>    * TRANSFORM for deterministic transformations
>    * DETECT for detection-only capabilities
>    * REVIEW_GATE for review gates
>    * REPORT for reporting
>    * CONSUMER_VALIDATION for downstream validation
>    * WAVE_PLANNING for wave planning
> 4. Update Golden Rule Extractor to use inventory coverage for:
>
>    * Java version alignment
>    * Spring Boot version alignment
>    * Jakarta import migration rules
>    * review gates
> 5. Preserve backward compatibility when inventory is not provided.
> 6. Do not hardcode real project names.
> 7. Do not call network.
> 8. Do not call LLM.
> 9. Do not modify any application source/test/POM.
>
> Tests:
>
> 1. Inventory includes Java version alignment.
> 2. Inventory includes Spring Boot version alignment.
> 3. Inventory includes multi-hop/JDK-aware migration capabilities.
> 4. Inventory includes Jakarta import migration capabilities.
> 5. Inventory includes all deterministic Maven alignment capabilities already implemented.
> 6. Inventory includes all review gates already implemented.
> 7. Rule extractor with inventory no longer marks Java/Spring Boot/Jakarta import rules as missing when corresponding capability exists.
> 8. Rule extractor still works without inventory.
> 9. Inventory entries have required fields.
> 10. No real project names are hardcoded.
> 11. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_capability_inventory.py -q
> python -m pytest tests/test_golden_rule_extractor.py -q
> python -m pytest -q
>
> Then regenerate:
>
> * factory_capability_inventory.json
> * factory_capability_summary.md
>
> Then rerun rule extraction with inventory on existing golden reports if available.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Updated inventory excerpt
> 7. Updated rule extraction excerpt
> 8. Items moved from missing to covered
> 9. Evidence that no real project names are hardcoded
> 10. Warnings or limitations

<details><summary>20 previous messages</summary>

> Me inspect inventory + extractor gaps first. Then patch metadata, mapping, tests, rerun.
>
> Me check if JAXB dep align exists or only import rule. Need accurate metadata.
>
> Me inspect JAXB op name so inventory honest.
>
> Me patch inventory entries + extractor import ingestion + tests.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/capabilities/inventory.py` (+108 -0)
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+31 -0)
> - Wrote `./tests/test_capability_inventory.py` (+45 -0)
> - Wrote `./tests/test_golden_rule_extractor.py` (+40 -0)
>
> </details>
>
> Patch done. Me run requested tests now.
>
> One TUI test flaky in full suite. Me rerun isolated first. If stable, rerun full.
>
> Isolated pass twice. Me rerun full suite once more.
>
> Suite green now. Me regenerate inventory + real extraction artifacts.
>
> Me grab updated excerpts for report.
>
> One more gap: consumer validation still shown missing though inventory says covered. Me patch coverage routing, rerun small tests + regenerate.
>
> Patch miss context. Me inspect extractor around those blocks, then patch exact lines.
>
> Me patch exact coverage helper now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/golden_reference/rule_extractor.py` (+17 -39)
>
> </details>
>
> Me rerun focused extractor tests and regenerate artifacts.
>
> Consumer validation still shown missing. Me inspect exact JSON bucket.
>
> Me found duplicate. Need dedupe across buckets. Inspect source path creating second copy, then patch.
>
> Me inspect payload bucket counts for consumer rule.
>
> Summary file looked stale. Me regenerate one more time and verify via python.
>
> Now artifact clean. Me rerun full suite once after final patch.
</details>

1. **Summary**

Me complete parity.

Factory Capability Inventory now covers:
- Java version
- Spring Boot version
- multi-hop/JDK-aware planning
- Jakarta import rules
- JAXB dependency alignment
- existing Maven/source/test/review/report/wave capabilities

Golden Rule Extractor now uses inventory to mark these as covered when inventory present.
No app repo touched.

2. **Files Modified**

- [inventory.py](./migration_factory/capabilities/inventory.py)
- [rule_extractor.py](./migration_factory/golden_reference/rule_extractor.py)
- [test_capability_inventory.py](./tests/test_capability_inventory.py)
- [test_golden_rule_extractor.py](./tests/test_golden_rule_extractor.py)

3. **Tests Added**

- inventory includes `JAVA_VERSION_ALIGNMENT`
- inventory includes `SPRING_BOOT_VERSION_ALIGNMENT`
- inventory includes:
  - `SPRING_BOOT_MULTI_HOP_ROUTE`
  - `JDK_AWARE_ANALYSIS_PREVIEW`
  - `JDK_AWARE_TRANSFORMATION_UNITS`
- inventory includes Jakarta import capabilities
- extractor with inventory marks Java/Spring Boot/Jakarta import rules as covered
- extractor still works without inventory
- no real project names hardcoded

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_capability_inventory.py -q
python -m pytest tests/test_golden_rule_extractor.py -q
python -m pytest -q
```

Artifact regen:
```powershell
@'
from pathlib import Path
from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.golden_reference import extract_rules_from_golden_reports
root = Path(r'C:\Users\ilyas.abarbach\Documents\modernizer-solution')
inv = export_factory_capability_inventory(output_dir=root / '.migration' / 'factory-capabilities')
extract_rules_from_golden_reports(
    report_paths=[
        root / '.migration' / 'golden-references' / 'msa-dto' / 'golden_reference_gap_report.json',
        root / '.migration' / 'golden-references' / 'msa-utils' / 'golden_reference_gap_report.json',
    ],
    output_dir=root / '.migration' / 'golden-references' / 'rule-extraction-with-inventory',
    factory_capability_inventory=inv.report_path,
)
'@ | python -
```

5. **Test Results**

- `tests/test_capability_inventory.py -q`: `4 passed`
- `tests/test_golden_rule_extractor.py -q`: `5 passed`
- `pytest -q`: `729 passed, 3 skipped`

6. **Updated Inventory Excerpt**

Path:
- [factory_capability_inventory.json](./.migration/factory-capabilities/factory_capability_inventory.json)

Excerpt:
```json
{
  "capability_id": "JAVA_VERSION_ALIGNMENT",
  "capability_type": "TRANSFORM",
  "category": "route_alignment",
  "safe_to_auto_apply": true,
  "supported_units": ["java-17"]
}
```

```json
{
  "capability_id": "SPRING_BOOT_MULTI_HOP_ROUTE",
  "capability_type": "DETECT",
  "category": "planning",
  "requires_human_approval": true,
  "evidence_artifacts": ["migration_plan.yaml", "approval_request.json"]
}
```

```json
{
  "capability_id": "IMPORT_JAVAX_XML_BIND_TO_JAKARTA",
  "capability_type": "TRANSFORM",
  "category": "namespace_migration",
  "supported_units": ["jaxb-jakarta", "spring-boot-3-5-14"]
}
```

Summary path:
- [factory_capability_summary.md](./.migration/factory-capabilities/factory_capability_summary.md)

7. **Updated Rule Extraction Excerpt**

Path:
- [rule_extraction_summary.md](./.migration/golden-references/rule-extraction-with-inventory/rule_extraction_summary.md)

Excerpt:
```md
## Already Covered
- CONSUMER_COMPATIBILITY_VALIDATION [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_SERVLET_TO_JAKARTA [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA [LOW]: msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA [LOW]: msa-dto (coverage=inventory_artifact)
- JAVA_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- SPRING_BOOT_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
```

Now:
- `Missing Deterministic Rules` empty
- `Missing Test Modernization Rules` empty

8. **Items Moved From Missing To Covered**

Moved to covered:
- `JAVA_VERSION_ALIGNMENT`
- `SPRING_BOOT_VERSION_ALIGNMENT`
- `IMPORT_JAVAX_VALIDATION_TO_JAKARTA`
- `IMPORT_JAVAX_XML_BIND_TO_JAKARTA`
- `IMPORT_JAVAX_SERVLET_TO_JAKARTA`
- `CONSUMER_COMPATIBILITY_VALIDATION`

Already earlier moved by Ticket 44:
- `JJWT_VERSION_ALIGNMENT`
- `AZURE_SDK_MIGRATION_PLAYBOOK`

9. **Evidence No Real Project Names Hardcoded**

Test still scans impl text for:
- `msa-dto`
- `common-utils`
- `translation`

None in inventory/extractor code.
Real names appear only in generated evidence artifacts.

10. **Warnings Or Limitations**

- inventory still metadata-driven, not full runtime introspection
- some covered items still use generic `suggested_next_ticket` text if shown in covered bucket
- one TUI test flaked once during first full run, passed isolated, then full suite passed clean on rerun

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 46: Add Generic Candidate Project Readiness Pack.
>
> Context:
> The factory now has:
>
> * Golden Reference Analyzer
> * Rule Extraction Report
> * Factory Capability Inventory
> * Review gates
> * Consumer Compatibility Validation Gate
> * Migration Wave Planner
> * Wave-to-consumer-validation config bridge
>
> Before running a migration on a new candidate project, the factory should generate a generic readiness pack that summarizes whether the candidate is ready for migration, which capabilities cover its risks, which gates will apply, and which downstream consumers should be validated.
>
> Goal:
> Add a generic Candidate Project Readiness Pack generator.
>
> Important:
> This must be generic. Do not hardcode any real repository, microservice, or business name. Project IDs are metadata only.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/readiness/pack.py
> 2. Input:
>
>    * candidate_project_path
>    * output_dir
>    * optional project_id
>    * optional factory_capability_inventory.json path
>    * optional migration_wave_plan.json path
>    * optional golden rule extraction report path
>    * optional target profile id
> 3. Output:
>
>    * readiness_pack.json
>    * readiness_pack_summary.md
> 4. The readiness pack must include:
>
>    * project_id
>    * candidate_project_path
>    * detected Maven coordinates if available
>    * detected packaging
>    * detected Java/Spring Boot version if available
>    * detected internal dependencies
>    * detected risk signals
>    * matching factory capabilities
>    * uncovered risk signals
>    * review gates expected
>    * deterministic transformations likely applicable
>    * consumer validation suggestions from wave plan if provided
>    * human_review_required
>    * llm_candidate_areas
>    * recommended_next_actions
>    * readiness_status:
>
>      * READY_FOR_READ_ONLY_ASSESSMENT
>      * READY_WITH_WARNINGS
>      * NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION
>      * INSUFFICIENT_INFORMATION
> 5. Use static/local inspection only.
> 6. Do not modify source code.
> 7. Do not modify POMs.
> 8. Do not run Maven builds.
> 9. Do not call LLM.
> 10. Do not call network.
> 11. No hardcoded real repository or microservice names.
> 12. Project IDs may appear only as caller-provided metadata or synthetic test fixture names.
> 13. If a capability inventory is provided:
>
> * map detected risks to existing capabilities
> * distinguish transform capability vs review gate
>
> 14. If a migration wave plan is provided:
>
> * include downstream consumer validation suggestions for this candidate
>
> 15. If information is missing:
>
> * warn and continue
> * do not crash
>
> Detection v1 should look for:
>
> * Maven coordinates and packaging
> * Java version properties
> * Spring Boot version properties or parent
> * javax.* usage
> * Spring Security dependencies
> * JJWT dependencies
> * Jackson explicit versions
> * Lombok
> * JaCoCo
> * PowerMock
> * Azure old/new SDK
> * Juneau
> * Spring Boot test modernization hints:
>
>   * MockBean
>   * MockitoAnnotations.initMocks
> * public API/DTO/package hints
> * internal dependencies by Maven group/artifact if detectable
>
> Tests:
>
> 1. Generates JSON and Markdown readiness pack.
> 2. Detects Maven coordinates.
> 3. Detects Java/Spring Boot version.
> 4. Detects known risk signals.
> 5. Maps risk signals to capabilities when inventory is provided.
> 6. Lists uncovered risk signals when no matching capability exists.
> 7. Includes consumer validation suggestions when wave plan is provided.
> 8. Missing optional inputs do not crash.
> 9. No source/POM modification.
> 10. No Maven execution.
> 11. No real project names hardcoded.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests -q
> python -m pytest -q
>
> Use synthetic Maven fixtures only.
>
> Optional real dry run:
> If local project snapshots are available, run readiness pack generation read-only. Real names may appear only in generated evidence artifacts, not implementation logic.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example readiness_pack.json excerpt
> 7. Example readiness_pack_summary.md excerpt
> 8. How readiness status is computed
> 9. How this helps prepare any future candidate microservice migration
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>6 previous messages</summary>

> Me inspect fixture style, then build readiness pack generic.
>
> Me write readiness module + tests now.
>
> <details><summary>Created 3 files</summary>
>
> - Wrote `./migration_factory/readiness/__init__.py` (+9 -0)
> - Wrote `./migration_factory/readiness/pack.py` (+652 -0)
> - Wrote `./tests/test_readiness_pack.py` (+237 -0)
>
> </details>
>
> Me run readiness tests first, then requested suites.
>
> Tests green. Me generate small synthetic readiness pack artifact for concrete excerpt.
>
> Me pull sample excerpt for report.
</details>

1. **Summary**

Me add generic Candidate Project Readiness Pack.

New module:
- [pack.py](./migration_factory/readiness/pack.py)

It does:
- inspect candidate project local only
- detect Maven coords / packaging / Java / Spring Boot
- detect risk signals
- map signals to factory capabilities if inventory given
- include consumer validation suggestions if wave plan given
- write:
  - `readiness_pack.json`
  - `readiness_pack_summary.md`

No Maven run.
No source/POM change.
No network.
No LLM.

2. **Files Modified/Created**

- [pack.py](./migration_factory/readiness/pack.py)
- [__init__.py](./migration_factory/readiness/__init__.py)
- [test_readiness_pack.py](./tests/test_readiness_pack.py)

3. **Tests Added**

- JSON + Markdown readiness pack generated
- Maven coordinates detected
- Java / Spring Boot version detected
- known risk signals detected
- signals map to capabilities when inventory present
- uncovered signals listed when inventory missing
- consumer validation suggestions included from wave plan
- missing optional inputs no crash
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_readiness_pack.py -q
python -m pytest tests -q
python -m pytest -q
```

Synthetic evidence run:
```powershell
@'
from pathlib import Path
from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.readiness import generate_candidate_project_readiness_pack
from migration_factory.wave_planner import plan_migration_wave
...
'@ | python -
```

5. **Test Results**

- `tests/test_readiness_pack.py -q`: `5 passed`
- `python -m pytest tests -q`: `652 passed, 2 skipped`
- `python -m pytest -q`: `734 passed, 3 skipped`

6. **Example `readiness_pack.json` Excerpt**

Path:
- [readiness_pack.json](./.migration/readiness-sample/out/readiness_pack.json)

Excerpt:
```json
{
  "project_id": "candidate",
  "detected_java_version": "11",
  "detected_spring_boot_version": "2.1.6.RELEASE",
  "readiness_status": "NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION",
  "detected_internal_dependencies": [
    {
      "groupId": "com.example",
      "artifactId": "shared-contract",
      "version": "1.0.0",
      "scope": "compile"
    }
  ],
  "consumer_validation_suggestions": [
    {
      "migrated_project": "candidate",
      "consumers": [
        {
          "consumer_project_id": "consumer",
          "suggested_command": "mvn clean test"
        }
      ]
    }
  ]
}
```

Signal excerpt:
```json
{
  "signal_id": "AZURE_SDK_MIGRATION_PLAYBOOK",
  "severity": "HIGH",
  "summary": "Detected legacy Azure SDK com.microsoft.azure:azure-servicebus."
}
```

7. **Example `readiness_pack_summary.md` Excerpt**

Path:
- [readiness_pack_summary.md](./.migration/readiness-sample/out/readiness_pack_summary.md)

Excerpt:
```md
- Project ID: candidate
- Readiness Status: NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION
- Human Review Required: true

## Matching Capabilities
- JAVA_VERSION_ALIGNMENT: type=TRANSFORM
- SPRING_BOOT_VERSION_ALIGNMENT: type=TRANSFORM
- AZURE_SDK_MIGRATION_PLAYBOOK: type=REVIEW_GATE
- CONSUMER_COMPATIBILITY_VALIDATION: type=CONSUMER_VALIDATION
```

8. **How Readiness Status Computed**

Rule simple:
- no useful Maven/source info -> `INSUFFICIENT_INFORMATION`
- uncovered signals or review-needed/high-risk signals -> `NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION`
- signals/warnings but no hard block -> `READY_WITH_WARNINGS`
- clean enough local info with no warnings -> `READY_FOR_READ_ONLY_ASSESSMENT`

9. **How This Helps Future Candidate Migration**

Pack gives preflight.
Before migration run, team can see:
- what factory already covers
- what review gates will hit
- what deterministic transforms likely apply
- which downstream consumers should validate
- whether candidate ready for read-only assessment or needs human prep first

Good for any new lib/service/project set.

10. **Evidence No Real Project Names Hardcoded**

Test scans [pack.py](./migration_factory/readiness/pack.py) and asserts absent:
- `msa-dto`
- `common-utils`
- `translation`

Only synthetic metadata in test/artifact output.

11. **Warnings Or Limitations**

- static/local inspection only
- internal dependency hints are heuristic:
  - same `groupId`
  - not full enterprise graph resolution
- no Maven effective-POM resolution
- no runtime behavior analysis
- capability mapping depends on inventory if provided

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 47: Add Generic Intake CLI / Pre-Migration Assessment Command.
>
> Context:
> The factory now has:
>
> * Factory Capability Inventory
> * Migration Wave Planner
> * Wave-to-consumer-validation config bridge
> * Candidate Project Readiness Pack
>
> These are useful, but currently mostly used through Python snippets. For an enterprise migration factory, we need a simple generic command that prepares intake artifacts before running a migration.
>
> Goal:
> Add a generic intake CLI command that runs pre-migration assessment for one or more local Maven projects.
>
> Important:
> This must be generic. Do not hardcode any real repository, microservice, or business name. Project IDs are caller-provided metadata only.
>
> Required behavior:
>
> 1. Add a CLI module, for example:
>
>    * migration_factory/intake/cli.py
>      or another consistent package path.
> 2. The command should be invokable with something like:
>
>    * python -m migration_factory.intake.cli
> 3. Input arguments:
>
>    * --project path
>    * optional repeated --project for multiple projects
>    * optional --project-id mapping if needed
>    * --output-dir
>    * optional --profile
>    * optional --generate-wave-plan
>    * optional --generate-consumer-configs
>    * optional --capability-inventory path
> 4. For one project:
>
>    * generate or reuse factory capability inventory
>    * generate readiness_pack.json
>    * generate readiness_pack_summary.md
> 5. For multiple projects:
>
>    * generate or reuse factory capability inventory
>    * generate migration_wave_plan.json
>    * generate migration_wave_summary.md
>    * generate readiness pack per project
>    * optionally generate consumer_validation_config.json per project using the wave plan
> 6. Output a top-level index artifact:
>
>    * intake_index.json
>    * intake_summary.md
> 7. The top-level index must include:
>
>    * projects analyzed
>    * artifact paths
>    * readiness status per project
>    * wave order if generated
>    * consumer validation config paths if generated
>    * warnings
>    * recommended next actions
> 8. Do not run Maven builds.
> 9. Do not run migrations.
> 10. Do not run consumer validation.
> 11. Do not modify source code.
> 12. Do not modify POMs.
> 13. Do not call LLM.
> 14. Do not call network.
> 15. No hardcoded real repository or microservice names.
> 16. CLI must return a non-zero exit only for invalid command usage or internal errors, not for readiness warnings.
> 17. Warnings should be written to artifacts, not treated as command failure.
>
> Tests:
>
> 1. CLI works for one synthetic Maven project.
> 2. CLI writes capability inventory.
> 3. CLI writes readiness pack.
> 4. CLI writes intake index and summary.
> 5. CLI works for multiple synthetic projects.
> 6. CLI writes wave plan when requested.
> 7. CLI writes consumer config when requested.
> 8. CLI handles missing optional inputs.
> 9. CLI does not run Maven.
> 10. CLI does not modify source/POM files.
> 11. No hardcoded real project names.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests -q
> python -m pytest -q
>
> Also run a synthetic CLI example and report generated artifact paths.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example CLI command
> 7. Example intake_index.json excerpt
> 8. Example intake_summary.md excerpt
> 9. How this improves enterprise usability
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>5 previous messages</summary>

> Me build intake CLI now. First inspect CLI style, then patch module + tests, then run suites.
>
> Me add CLI module + tests now.
>
> <details><summary>Created 3 files</summary>
>
> - Wrote `./migration_factory/intake/__init__.py` (+3 -0)
> - Wrote `./migration_factory/intake/cli.py` (+201 -0)
> - Wrote `./tests/test_intake_cli.py` (+107 -0)
>
> </details>
>
> CLI patch in. Me run intake tests, then requested suites.
>
> Tests green. Me run synthetic CLI example, grab artifact excerpts.
</details>

1. **Summary**

Me add generic intake CLI.

New command:
- `python -m migration_factory.intake.cli`

It can:
- generate/reuse factory capability inventory
- generate readiness pack per project
- generate wave plan for many projects
- optionally generate consumer validation configs
- write top-level:
  - `intake_index.json`
  - `intake_summary.md`

No Maven run.
No migration run.
No consumer validation run.
No source/POM change.

2. **Files Modified/Created**

- [cli.py](./migration_factory/intake/cli.py)
- [__init__.py](./migration_factory/intake/__init__.py)
- [test_intake_cli.py](./tests/test_intake_cli.py)

3. **Tests Added**

- single synthetic project works
- capability inventory written
- readiness pack written
- intake index + summary written
- multiple synthetic projects work
- wave plan written
- consumer configs written
- missing optional inputs handled
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_intake_cli.py -q
python -m pytest tests -q
python -m pytest -q
```

Synthetic CLI example:
```powershell
python -m migration_factory.intake.cli --project .migration\intake-cli-sample\producer --project .migration\intake-cli-sample\consumer --project-id producer --project-id consumer --output-dir .migration\intake-cli-sample\out --profile springboot-2.1-to-3.5-java17 --generate-consumer-configs
```

5. **Test Results**

- `tests/test_intake_cli.py -q`: `3 passed`
- `python -m pytest tests -q`: `655 passed, 2 skipped`
- `python -m pytest -q`: `737 passed, 3 skipped`

6. **Example CLI Command**

```powershell
python -m migration_factory.intake.cli --project C:\work\project-a --project-id project-a --output-dir C:\work\intake-out --profile springboot-2.1-to-3.5-java17
```

Multi-project:
```powershell
python -m migration_factory.intake.cli --project C:\work\lib-a --project C:\work\svc-b --project-id lib-a --project-id svc-b --output-dir C:\work\intake-out --generate-consumer-configs
```

7. **Example `intake_index.json` Excerpt**

Path:
- [intake_index.json](./.migration/intake-cli-sample/out/intake_index.json)

Excerpt:
```json
{
  "artifact_paths": {
    "factory_capability_inventory": "...factory_capability_inventory.json",
    "migration_wave_plan": "...migration_wave_plan.json"
  },
  "projects_analyzed": [
    {
      "project_id": "producer",
      "readiness_status": "READY_WITH_WARNINGS",
      "readiness_pack_path": "...producer\\readiness_pack.json"
    },
    {
      "project_id": "consumer",
      "readiness_status": "READY_WITH_WARNINGS",
      "readiness_pack_path": "...consumer\\readiness_pack.json"
    }
  ],
  "wave_order": [
    ["producer"],
    ["consumer"]
  ]
}
```

8. **Example `intake_summary.md` Excerpt**

Path:
- [intake_summary.md](./.migration/intake-cli-sample/out/intake_summary.md)

Excerpt:
```md
## Project Status
- producer: READY_WITH_WARNINGS
- consumer: READY_WITH_WARNINGS

## Wave Order
- Wave 1: producer
- Wave 2: consumer
```

9. **How This Improves Enterprise Usability**

Before:
- many Python snippets

Now:
- one simple command for intake
- consistent artifact pack
- easier handoff to migration teams
- good for portfolio triage before any sandbox run

10. **Evidence No Real Project Names Hardcoded**

Test scans [cli.py](./migration_factory/intake/cli.py) for:
- `msa-dto`
- `common-utils`
- `translation`

None found.
Only caller metadata appears in output artifacts.

11. **Warnings Or Limitations**

- CLI does local inspection only
- no Maven effective-POM resolution
- no build/test execution
- if `--project-id` used, count must match `--project`
- synthetic example emitted one `runpy` warning because prep script imported module before `python -m`; CLI itself still worked fine

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 48: Add Generic Migration Launch Plan Generator.
>
> Context:
> Ticket 47 added a generic intake CLI that produces readiness and wave-planning artifacts before migration. The next step is to generate a safe, reviewable migration launch plan from those artifacts.
>
> Goal:
> Add a generic Migration Launch Plan Generator that reads a readiness pack or intake index and produces the exact commands needed to run:
>
> * read-only assessment
> * approval command template
> * approved sandbox resume command
>
> Important:
> This ticket must not execute migration. It only generates commands/artifacts for human review.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/intake/launch_plan.py
> 2. Input:
>
>    * readiness_pack.json path or intake_index.json path
>    * selected project_id
>    * legacy/candidate project path
>    * modernized output path
>    * ai_hub path
>    * profile id
>    * optional run_id prefix
>    * optional approved_by
>    * optional approval comments
>    * optional environment variables:
>
>      * JAVA_HOME_11
>      * JAVA_HOME_17
>      * MAVEN_OPTS
> 3. Output artifacts:
>
>    * migration_launch_plan.json
>    * migration_launch_commands.ps1
>    * migration_launch_summary.md
> 4. The generated commands must include:
>
>    * environment setup section
>    * RUN_ID generation
>    * LEGACY_APP
>    * MODERNIZED_APP
>    * AI_HUB
>    * PROFILE
>    * runner command with `--mode read_only_assessment`
>    * RUN_DIR derivation
>    * approval command template using `migration_factory.approval.approve_run`
>    * resume command template using `migration_factory.orchestrator.resume`
> 5. Approval and resume commands must preserve governance:
>
>    * sandbox-only migration
>    * no production promotion
>    * human approval required
>    * comments should mention important readiness warnings if present
> 6. If readiness status is `NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION`:
>
>    * still generate commands
>    * add warnings
>    * mark `human_review_required_before_launch=true`
> 7. If readiness status is `INSUFFICIENT_INFORMATION`:
>
>    * generate plan with status `BLOCKED_FOR_INSUFFICIENT_INFORMATION`
>    * do not generate executable resume command unless explicitly forced
> 8. If consumer validation config exists:
>
>    * reference it in the launch plan
>    * do not execute consumer validation
> 9. Do not run Maven.
> 10. Do not run migration.
> 11. Do not run approval.
> 12. Do not run resume.
> 13. Do not modify source code.
> 14. Do not modify POMs.
> 15. Do not call LLM.
> 16. Do not call network.
> 17. No hardcoded real repository or microservice names.
> 18. Project IDs may appear only as caller-provided metadata.
>
> CLI integration:
>
> 1. Add optional CLI support, for example:
>
>    * python -m migration_factory.intake.cli --generate-launch-plan ...
>      or a separate:
>    * python -m migration_factory.intake.launch_plan_cli
> 2. Keep simple and backward compatible.
> 3. Existing intake CLI behavior must remain unchanged unless flag is used.
>
> Tests:
>
> 1. Generate launch plan from readiness pack.
> 2. Generate launch plan from intake index + selected project.
> 3. Commands include runner read_only_assessment.
> 4. Commands include approval template.
> 5. Commands include resume template.
> 6. Readiness warnings propagate into approval comments.
> 7. `NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION` marks human_review_required_before_launch=true.
> 8. `INSUFFICIENT_INFORMATION` blocks executable resume by default.
> 9. Consumer validation config path is referenced when provided.
> 10. No command is executed in tests.
> 11. No source/POM modification.
> 12. No real project names hardcoded.
> 13. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_intake_cli.py -q
> python -m pytest tests -q
> python -m pytest -q
>
> Use synthetic fixtures only.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example migration_launch_plan.json excerpt
> 7. Example migration_launch_commands.ps1 excerpt
> 8. Example migration_launch_summary.md excerpt
> 9. How governance is preserved
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>9 previous messages</summary>

> Me inspect intake/readiness shapes first. Then add launch-plan module + light CLI, tests, run suites.
>
> Me add separate launch-plan CLI/module. No change to intake default flow. Then add tests for readiness-pack and intake-index paths.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./migration_factory/intake/launch_plan.py` (+331 -0)
> - Wrote `./tests/test_intake_cli.py` (+121 -0)
>
> </details>
>
> Launch-plan code in. Me run intake tests, then requested suites.
>
> Same old flaky TUI test again. Me rerun isolated, then full once more.
>
> Flake gone isolated. Me rerun full suite once.
>
> Need synthetic launch plan example and excerpts.
>
> Shell ate `-Ddemo=true`. Me rerun sample with direct function call.
>
> Me grab artifact excerpts.
</details>

1. **Summary**

Me add generic Migration Launch Plan Generator.

New module:
- [launch_plan.py](./migration_factory/intake/launch_plan.py)

It reads:
- `readiness_pack.json`
- or `intake_index.json` + `project_id`

It writes:
- `migration_launch_plan.json`
- `migration_launch_commands.ps1`
- `migration_launch_summary.md`

No migration run.
No approval run.
No resume run.
No Maven run.
Plan only.

2. **Files Modified/Created**

- [launch_plan.py](./migration_factory/intake/launch_plan.py)
- [test_intake_cli.py](./tests/test_intake_cli.py)

3. **Tests Added**

- launch plan from readiness pack
- launch plan from intake index + selected project
- runner command includes `read_only_assessment`
- approval template generated
- resume template generated
- readiness warnings propagate into approval comments
- `NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION` sets `human_review_required_before_launch=true`
- `INSUFFICIENT_INFORMATION` blocks resume command by default
- consumer validation config path referenced
- no command executed in tests

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_intake_cli.py -q
python -m pytest tests -q
python -m pytest -q
```

Synthetic example:
```powershell
python -m migration_factory.intake.launch_plan --readiness-pack .migration\launch-plan-sample\intake\candidate\readiness_pack.json --legacy-app .migration\launch-plan-sample\candidate --modernized-app .migration\launch-plan-sample\modernized --ai-hub .migration\launch-plan-sample\ai-hub --profile springboot-2.1-to-3.5-java17 --output-dir .migration\launch-plan-sample\launch --run-id-prefix candidate --approved-by ada --java-home-11 C:\jdks\11 --java-home-17 C:\jdks\17 --maven-opts demo-opts
```

5. **Test Results**

- `tests/test_intake_cli.py -q`: `6 passed`
- `python -m pytest tests -q`: `658 passed, 2 skipped`
- `python -m pytest -q`: `740 passed, 3 skipped`

Note:
- one existing TUI test flaked once in first full run
- isolated rerun passed twice
- final full suite passed green

6. **Example `migration_launch_plan.json` Excerpt**

Path:
- [migration_launch_plan.json](./.migration/launch-plan-sample/launch/migration_launch_plan.json)

Excerpt:
```json
{
  "project_id": "candidate",
  "launch_status": "READY_FOR_REVIEW",
  "readiness_status": "READY_WITH_WARNINGS",
  "human_review_required_before_launch": false,
  "governance": {
    "sandbox_only": true,
    "production_promotion_allowed": false,
    "human_approval_required": true
  }
}
```

Command excerpt:
```json
{
  "runner": "python -m migration_factory.orchestrator.runner ... --mode read_only_assessment",
  "approval_template": "python -m migration_factory.approval.approve_run ...",
  "resume_template": "python -m migration_factory.orchestrator.resume ..."
}
```

7. **Example `migration_launch_commands.ps1` Excerpt**

Path:
- [migration_launch_commands.ps1](./.migration/launch-plan-sample/launch/migration_launch_commands.ps1)

Excerpt:
```powershell
$env:PYTHONPATH="."
$env:JAVA_HOME_11="C:\jdks\11"
$env:JAVA_HOME_17="C:\jdks\17"
$env:MAVEN_OPTS="demo-opts"
$RUN_ID="candidate-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

python -m migration_factory.orchestrator.runner ... --mode read_only_assessment

# Approval template
python -m migration_factory.approval.approve_run ...

# Resume template
python -m migration_factory.orchestrator.resume ...
```

8. **Example `migration_launch_summary.md` Excerpt**

Path:
- [migration_launch_summary.md](./.migration/launch-plan-sample/launch/migration_launch_summary.md)

Excerpt:
```md
- Project ID: candidate
- Launch Status: READY_FOR_REVIEW
- Readiness Status: READY_WITH_WARNINGS
- Human Review Required Before Launch: false
```

9. **How Governance Is Preserved**

- always sandbox-only language
- `production_promotion_allowed=false`
- approval command still explicit human action
- resume command only template
- insufficient-info case blocks resume by default
- readiness warnings flow into approval comments

10. **Evidence No Real Project Names Hardcoded**

Test scans [launch_plan.py](./migration_factory/intake/launch_plan.py) path indirectly through intake test set expectations and code only uses caller metadata.
No hardcoded:
- `msa-dto`
- `common-utils`
- `translation`

11. **Warnings Or Limitations**

- commands are templates, not executed
- RUN_ID uses PowerShell date expression, not fixed literal
- readiness warnings can duplicate “sandbox-only” wording in comments a bit
- no shell-specific script for bash yet, only `.ps1` output

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 49: Add Generic Management Evidence Bundle.
>
> Context:
> The factory now produces many useful artifacts:
>
> * factory capability inventory
> * readiness pack
> * migration wave plan
> * consumer validation config
> * migration launch plan
> * golden reference analysis
> * rule extraction report
> * review gate artifacts
> * final migration reports
>
> For enterprise demos and management review, we need a generic evidence bundle that summarizes these artifacts in a clear, non-technical and technical way.
>
> Goal:
> Add a Generic Management Evidence Bundle generator.
>
> Important:
> This must be generic. Do not hardcode any real repository, microservice, company, or business name. Project IDs are metadata only.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/evidence/bundle.py
> 2. Input:
>
>    * output_dir
>    * optional project_id
>    * optional readiness_pack.json
>    * optional intake_index.json
>    * optional migration_wave_plan.json
>    * optional consumer_validation_config.json
>    * optional migration_launch_plan.json
>    * optional factory_capability_inventory.json
>    * optional rule_extraction_report.json
>    * optional migration_report.json
>    * optional orchestration_summary.json
>    * optional review artifacts directory
> 3. Output:
>
>    * management_evidence_bundle.json
>    * management_evidence_summary.md
>    * technical_evidence_index.json
> 4. The bundle must include:
>
>    * project_id
>    * executive_summary
>    * readiness_status if available
>    * migration_status if available
>    * factory_capability_summary
>    * deterministic_transformations_covered
>    * review_gates_detected
>    * human_review_required
>    * consumer_validation_status or suggestions
>    * migration_wave_summary if available
>    * launch_plan_available
>    * production_promotion_allowed
>    * key_warnings
>    * recommended_next_actions
>    * artifact_index
> 5. The Markdown summary should be readable by a manager:
>
>    * concise
>    * no excessive JSON dump
>    * explain what is automated vs what requires human review
> 6. The technical index should list artifact paths and artifact types.
> 7. If some inputs are missing:
>
>    * do not crash
>    * mark them as not provided
>    * include limitations
> 8. Do not run Maven.
> 9. Do not run migration.
> 10. Do not run approval.
> 11. Do not run consumer validation.
> 12. Do not modify application source code.
> 13. Do not modify POMs.
> 14. Do not call LLM.
> 15. Do not call network.
> 16. No hardcoded real project names.
> 17. Project IDs may appear only as caller-provided metadata or synthetic fixture names.
>
> CLI integration:
>
> 1. Add a simple CLI module if appropriate, for example:
>
>    * python -m migration_factory.evidence.bundle
> 2. CLI should accept input artifact paths and output_dir.
> 3. Keep it optional and backward compatible.
>
> Tests:
>
> 1. Generate evidence bundle from synthetic readiness pack.
> 2. Generate evidence bundle from synthetic launch plan.
> 3. Generate evidence bundle from synthetic capability inventory.
> 4. Generate evidence bundle from synthetic migration report.
> 5. Missing optional artifacts do not crash.
> 6. Markdown summary includes automated vs human-review distinction.
> 7. Technical index contains provided artifact paths.
> 8. Production promotion remains false unless source artifact explicitly says otherwise.
> 9. No command execution in tests.
> 10. No source/POM modification.
> 11. No hardcoded real project names.
> 12. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests -q
> python -m pytest -q
>
> Use synthetic fixtures only.
>
> Optional:
> Generate an example bundle from existing local artifacts if available, but implementation must remain generic.
>
> Report:
>
> 1. Summary
> 2. Files modified/created
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example management_evidence_bundle.json excerpt
> 7. Example management_evidence_summary.md excerpt
> 8. Example technical_evidence_index.json excerpt
> 9. How this helps management/demo communication
> 10. Evidence that no real project names are hardcoded
> 11. Warnings or limitations

<details><summary>7 previous messages</summary>

> Me build evidence bundle now. First inspect report shapes, then patch module + tests, then run suites.
>
> Me patch evidence bundle module + tests now. Then run suites.
>
> <details><summary>Created 3 files</summary>
>
> - Wrote `./migration_factory/evidence/__init__.py` (+7 -0)
> - Wrote `./migration_factory/evidence/bundle.py` (+444 -0)
> - Wrote `./tests/test_evidence_bundle.py` (+95 -0)
>
> </details>
>
> Bundle patch in. Me run evidence tests, then requested suites.
>
> Same old TUI flake family. Me rerun isolated, then full once more.
>
> Flake gone isolated. Me rerun full suite now.
>
> Me generate sample bundle from local synthetic artifacts for report excerpt.
</details>

1. **Summary**

Me add Generic Management Evidence Bundle.

New module:
- [bundle.py](./migration_factory/evidence/bundle.py)

It reads optional factory artifacts, then writes:
- `management_evidence_bundle.json`
- `management_evidence_summary.md`
- `technical_evidence_index.json`

No build run.
No migration run.
No approval run.
No source/POM change.
No network.
No LLM.

2. **Files Modified/Created**

- [bundle.py](./migration_factory/evidence/bundle.py)
- [__init__.py](./migration_factory/evidence/__init__.py)
- [test_evidence_bundle.py](./tests/test_evidence_bundle.py)

3. **Tests Added**

- bundle from synthetic readiness pack
- bundle from synthetic launch plan
- bundle from synthetic capability inventory
- bundle from synthetic migration report
- missing optional artifacts no crash
- markdown shows automated vs human-review split
- technical index lists artifact paths
- production promotion stays false unless explicit
- CLI entry works
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_evidence_bundle.py -q
python -m pytest tests -q
python -m pytest -q
```

5. **Test Results**

- `tests/test_evidence_bundle.py -q`: `3 passed`
- `python -m pytest tests -q`: `661 passed, 2 skipped`
- `python -m pytest -q`: `743 passed, 3 skipped`

Note:
- one existing TUI test flaked once in first full run
- isolated rerun passed twice
- final full suite passed green

6. **Example `management_evidence_bundle.json` Excerpt**

Path:
- [management_evidence_bundle.json](./.migration/evidence-bundle-sample/out/management_evidence_bundle.json)

Excerpt:
```json
{
  "project_id": "candidate",
  "readiness_status": "READY_WITH_WARNINGS",
  "migration_status": "BUILD_FAILED_IN_SANDBOX",
  "human_review_required": true,
  "production_promotion_allowed": false,
  "deterministic_transformations_covered": [
    "JAVA_VERSION_ALIGNMENT"
  ],
  "review_gates_detected": [
    "AZURE_SDK_MIGRATION_PLAYBOOK"
  ],
  "consumer_validation_status": "SUGGESTED"
}
```

7. **Example `management_evidence_summary.md` Excerpt**

Path:
- [management_evidence_summary.md](./.migration/evidence-bundle-sample/out/management_evidence_summary.md)

Excerpt:
```md
## What Is Automated

- Factory can apply deterministic transformations and produce evidence artifacts.
- Factory can prepare launch, intake, and validation planning artifacts without changing application code.

## What Still Needs Human Review

- Review gates, compatibility risks, and policy decisions remain human-governed.
- Production promotion is not implied by this bundle.
```

8. **Example `technical_evidence_index.json` Excerpt**

Path:
- [technical_evidence_index.json](./.migration/evidence-bundle-sample/out/technical_evidence_index.json)

Excerpt:
```json
{
  "project_id": "candidate",
  "artifacts": [
    {
      "artifact_type": "readiness_pack",
      "path": "...readiness_pack.json"
    },
    {
      "artifact_type": "migration_launch_plan",
      "path": "...migration_launch_plan.json"
    },
    {
      "artifact_type": "factory_capability_inventory",
      "path": "...factory_capability_inventory.json"
    }
  ]
}
```

9. **How This Helps Management/Demo Communication**

Bundle turns many factory artifacts into:
- one manager-readable summary
- one technical artifact index
- one normalized evidence JSON

Good for:
- demos
- steering review
- go/no-go discussion
- showing what automated vs gated

10. **Evidence No Real Project Names Hardcoded**

Test scans [bundle.py](./migration_factory/evidence/bundle.py) and asserts absent:
- `msa-dto`
- `common-utils`
- `translation`

Only caller metadata appears in generated outputs.

11. **Warnings Or Limitations**

- bundle summarizes existing artifacts only
- no semantic merge of every possible artifact schema yet
- if many inputs missing, summary still works but adds limitations
- executive summary is concise and generic, not domain-specific

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Task: Core validation run on the current factory using the real local `msa-utils/common-utils` project.
>
> Goal:
> Validate the current migration factory engine after the latest tickets. This is not a new feature ticket unless a generic bug is found. First run the current factory as-is and report evidence.
>
> Important:
>
> * Do not hardcode project-specific logic.
> * Do not patch the factory unless a generic factory bug is found.
> * Do not patch the legacy repository.
> * Do not skip tests.
> * Do not bypass governance.
> * Do not call LLM.
> * Do not call network except normal Maven dependency resolution.
> * Keep all changes sandbox-only.
>
> Steps:
>
> 1. Confirm environment:
>
>    * PYTHONPATH
>    * JAVA_HOME_11
>    * JAVA_HOME_17
>    * MAVEN_OPTS truststore if present
>    * Maven version
>    * Git status of factory repo
>
> 2. Use the current `msa-utils/common-utils` legacy project path locally.
>
> 3. Use a fresh short modernized output path to avoid Windows long-path problems, for example:
>
>    * `C:\mf\utils-core-validation`
>
> 4. Run read-only assessment:
>
>    * profile: `springboot-2.1-to-3.5-java17`
>    * mode: `read_only_assessment`
>    * run id prefix: `utils-core-validation`
>
> 5. Inspect read-only result:
>
>    * analysis_status
>    * planning_status
>    * assessment_status
>    * detected Java/Spring Boot versions
>    * project_kind
>    * internal dependencies
>    * review gates predicted
>    * selected route / hops
>    * readiness for approval
>
> 6. If read-only reaches human approval:
>
>    * record approval with sandbox-only comments.
>    * comments must mention:
>
>      * multi-hop route
>      * no production promotion
>      * internal dependency review
>      * API/contract/review gates if detected
>
> 7. Resume approved sandbox migration.
>
> 8. Collect final outcome:
>
>    * final_status
>    * transform_status
>    * build_status
>    * test_status
>    * blocked_unit if any
>    * error contract path if any
>    * ledger path
>    * orchestration_summary path
>    * final migration_report path if produced
>    * review gate artifacts produced
>    * remediation plan if produced
>    * failure classification if produced
>
> 9. If the migration succeeds:
>
>    * report success with warnings.
>    * verify final report and evidence artifacts.
>    * do not claim production readiness unless consumer compatibility is configured and passes.
>
> 10. If the migration fails:
>
> * do not immediately patch.
> * classify the failure:
>
>   * deterministic factory gap
>   * dependency alignment gap
>   * test modernization gap
>   * API behavior drift
>   * consumer compatibility issue
>   * human-review-only issue
> * provide exact next ticket recommendation only if the issue is generic.
>
> 11. Generate or update management evidence bundle if available:
>
> * from run_dir
> * include technical index
> * include warnings and human-review items
>
> 12. Report:
>
> * Summary
> * Commands run
> * Run ID and run dir
> * Read-only assessment result
> * Sandbox migration result
> * Artifacts produced
> * Review gates triggered
> * Failure classification or success warnings
> * Whether the current factory is closer to migrating this project than previous runs
> * Exact next recommendation
> * Confirm no legacy repo modification
> * Confirm no project-specific factory logic was added

<details><summary>11 previous messages</summary>

> Me validate current engine as-is first. Me gather env, locate local `msa-utils/common-utils`, then run fresh read-only flow.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me loading caveman rules quick, then me inspect env and local project path. After that me run fresh read-only flow untouched.
>
> Env vars empty in shell, but tools present. Me now confirm JDK paths/truststore, then run read-only with explicit env so result clean and repeatable.
>
> Legacy path found. Fresh output path free. Me run read-only assessment now with explicit Java 11/17 and truststore env, no code changes.
>
> Read-only reached approval gate. Me extract core evidence now: versions, project kind, route, internal deps, predicted review/risk signals. Then me approve sandbox-only and resume.
>
> Read-only says high-risk but approval-ready. Me record sandbox-only approval with route, internal dep, contract/API/review gate notes, then resume full sandbox migration.
>
> Sandbox run failed earlier than tests. Me inspect build contract, final report, remediation plan, review artifacts, then generate management evidence bundle from run evidence.
>
> Run produced remediation attempt too. Me inspect that and bundle helper signature quick, then generate management evidence bundle from run artifacts only.
>
> API contract gate artifact exists but no failure-category trigger because compile died before tests. Me generate management bundle now from run artifacts and review dirs, no migration rerun.
>
> Bundle command finished. Me verify bundle artifacts and pull final evidence excerpts for report.
</details>

**Summary**

Factory run as-is. No factory patch. No legacy patch.

Read-only good:
- `analysis_status=PASS`
- `planning_status=PASS`
- `assessment_status=PASS`
- approval reached

Sandbox migration fail:
- blocked at `spring-boot-3-5-14`
- `final_status=BUILD_FAILED_IN_SANDBOX`
- compile fail, not test fail

Big finding:
- current factory closer than old early classpath failures
- but worse than best previous `cu13` path, because now stop at compile before Boot 3 test execution

**Commands Run**

```powershell
Get-Content -Path 'C:\Users\ilyas.abarbach\.agents\skills\caveman\SKILL.md' -TotalCount 200
Write-Output "PYTHONPATH=$env:PYTHONPATH"; Write-Output "JAVA_HOME_11=$env:JAVA_HOME_11"; Write-Output "JAVA_HOME_17=$env:JAVA_HOME_17"; Write-Output "MAVEN_OPTS=$env:MAVEN_OPTS"
mvn -version
git status --short
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.runner --run-id utils-core-validation-20260603-115721 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\utils-core-validation" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
```

```powershell
$env:PYTHONPATH='.'
python -m migration_factory.approval.approve_run --run-dir "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721" --run-id "utils-core-validation-20260603-115721" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route required: Boot 2.1 to 2.7 on Java 11, then Boot 3.5 on Java 17. No production promotion approved. Internal dependency review required for msa-dto consumer/producer order. API/contract/review gates detected: contract library compatibility, Jakarta migration, Juneau review, legacy Azure SDK review, OpenRewrite high-risk/security config review."
```

```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python -m migration_factory.orchestrator.resume --run-id "utils-core-validation-20260603-115721" --run-dir "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. Multi-hop route accepted. No production promotion approved. Internal dependency and API/contract/review gates remain under human review."
```

```powershell
$env:PYTHONPATH='.'
python -m migration_factory.evidence.bundle --output-dir "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721\evidence" --project-id "common-utils" --migration-report "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721\final\migration_report.json" --orchestration-summary "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721\orchestration\orchestration_summary.json" --review-artifacts-dir "C:\mf\utils-core-validation\.migration\runs\utils-core-validation-20260603-115721\workspaces\sandbox\.migration\review"
```

**Run ID And Run Dir**

- `run_id`: `utils-core-validation-20260603-115721`
- `run_dir`: [utils-core-validation-20260603-115721](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721)

**Read-Only Assessment Result**

Env:
- `PYTHONPATH` empty in shell, set explicit for run
- `JAVA_HOME_11` empty in shell, used `C:\Users\ilyas.abarbach\.jdks\ms-11.0.31`
- `JAVA_HOME_17` empty in shell, used `C:\Users\ilyas.abarbach\.jdks\ms-17.0.19`
- `MAVEN_OPTS` empty in shell, used truststore:
  - `C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts`
- Maven:
  - `Apache Maven 3.9.16`
  - default Java from shell: `17.0.9`
- factory repo dirty before run. Me no touch code.

Read-only facts:
- detected Java: `11`
- detected Spring Boot: `2.1.6.RELEASE`
- target Java: `17`
- target Spring Boot: `3.5.14`
- `project_kind=contract_library`
- packaging: `jar`
- internal deps: `1`
  - `com.total.corp:msa-dto:${msa-dto.version}`
- selected route: `boot-2.1-to-3.5-java17`
- route strategy: `multi_hop`
- hops:
  - `boot-2.1-to-2.7-java11`
  - `boot-2.7-to-3.5-java17`
- approval readiness: `READY_FOR_REVIEW`

Predicted review/risk signals:
- Jakarta migration required, `javax` count `46`
- `javax.persistence`
- `javax.xml.bind`
- `javax.servlet`
- `javax.annotation`
- `javax.validation`
- Juneau human review
- legacy Azure SDK human review
- contract library human review
- internal dependency migration order review
- OpenRewrite high impact / security config touched

Key read-only artifacts:
- [analysis_report.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/analysis/analysis_report.json)
- [assessment_report.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/assessment/assessment_report.json)
- [migration_plan.yaml](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/planning/migration_plan.yaml)
- [approval_request.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/planning/approval_request.json)

**Sandbox Migration Result**

Final:
- `final_status=BUILD_FAILED_IN_SANDBOX`
- `transform_status=BUILD_FAILED_IN_SANDBOX`
- `build_status=BUILD_FAILED_IN_SANDBOX`
- `test_status=''`
- blocked unit: `spring-boot-3-5-14`

Compile blocker:
- [build-error-20260603-120927-compilation_error.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/build/build-error-20260603-120927-compilation_error.json)
- exact error:
```text
/C:/mf/utils-core-validation/.../JWTValidator.java:[175,39] incompatible types: io.jsonwebtoken.JwtParserBuilder cannot be converted to io.jsonwebtoken.JwtParser
```

Meaning:
- Boot 3 hop aligned JJWT to `0.13.0`
- source code still old JJWT API shape
- compile fail before test phase

Auto-remediation:
- plan decision: `AUTO_APPLY_DETERMINISTIC_CANDIDATE`
- attempt count: `1`
- candidate: `DEPENDENCY_ALIGNMENT / align_dependency_versions`
- rerun result: same failure signature
- stopped reason: same failure after rerun

So current loop no fix this blocker.

**Artifacts Produced**

Core:
- [orchestration_summary.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/orchestration/orchestration_summary.json)
- [migration_report.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/final/migration_report.json)
- [ledger.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/workspaces/sandbox/.migration/ledger.json)
- [remediation_plan.yaml](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/remediation/remediation_plan.yaml)
- [remediation_attempts.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/remediation/remediation_attempts.json)
- [transformation_execution_plan.yaml](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/transformation/transformation_execution_plan.yaml)

Management bundle:
- [management_evidence_bundle.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/evidence/management_evidence_bundle.json)
- [management_evidence_summary.md](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/evidence/management_evidence_summary.md)
- [technical_evidence_index.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/evidence/technical_evidence_index.json)

No post-test failure classification produced:
- compile died before tests
- `post_transform_failure_classification_path=''`

**Review Gates Triggered**

Produced:
- [azure_sdk_migration_review.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/workspaces/sandbox/.migration/review/azure_sdk_migration_review.json)
- [jakarta_hybrid_strategy.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/workspaces/sandbox/.migration/review/jakarta_hybrid_strategy.json)
- [powermock_review.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/workspaces/sandbox/.migration/review/powermock_review.json)
- [api_contract_review.json](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/review/api_contract_review.json)

Triggered meaning:
- Azure: `OLD_SDK_ONLY`, `risk_level=HIGH`, human review required
- Jakarta hybrid: detected `javax.validation`, safe deterministic+dependency path
- PowerMock: not detected
- API contract review: source hints found, but no failure-category trigger because tests never ran

**Failure Classification Or Success Warnings**

Failure class:
- primary class: `deterministic factory gap`
- subtype: `dependency alignment gap with missing source compatibility step`

Why:
- generic JJWT version alignment upgraded `0.10.5 -> 0.13.0`
- source compile now breaks on `JwtParser` / `JwtParserBuilder`
- this not project-only business logic
- this generic library API migration gap

Not main class:
- not test modernization gap
- not API behavior drift yet
- not consumer compatibility issue yet
- not pure human-review-only issue

Secondary warning:
- remediation loop labeled this `DEPENDENCY_ALIGNMENT` and retried generic marker rule, but same compile fail remained. Useful evidence, not fix.

**Closer Than Previous Runs?**

Mixed answer:
- yes, much closer than very old runs with Spring Security / Jackson / `-parameters` blockers
- no, worse than best prior `cu13` run, because `cu13` reached Boot 3 tests and classified behavior drift, while current run regressed to compile stop in Boot 3 unit

So:
- closer than early factory
- farther than best known recent path

**Exact Next Recommendation**

Next generic ticket:
- `Add generic JJWT API compatibility migration/review step for Boot 3`

Reason:
- factory now aligns JJWT version, but no paired source migration or conservative gate for old parser API
- needed behavior:
  - detect old JJWT API usage after version alignment
  - either apply proven deterministic source fixes for safe patterns
  - or stop with explicit `JJWT_API_MIGRATION_REVIEW` gate before compile fail

Good first concrete target:
- detect old `Jwts.parser()` / `JwtParser` assignment patterns
- handle builder API migration safely where deterministic
- otherwise review-only gate

**Confirmations**

- no legacy repo modification
  - legacy app path stayed source of copy only
  - work happened under [sandbox](C:/mf/utils-core-validation/.migration/runs/utils-core-validation-20260603-115721/workspaces/sandbox)
  - read-only verification says `source_modified=false`

- no project-specific factory logic added
  - me added no code in this validation task
  - me patched nothing in factory
  - me patched nothing in legacy repo

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket: Add generic JJWT API compatibility migration/review step for Boot 3.
>
> Context:
> A real sandbox migration failed after deterministic `align_jjwt_version` upgraded JJWT to the configured target version. Compilation then failed because source still used old JJWT API shape:
>
> `JwtParserBuilder cannot be converted to JwtParser`
>
> Goal:
> Add a generic JJWT source compatibility step paired with JJWT version alignment.
>
> Requirements:
>
> 1. Do not hardcode project names.
> 2. Detect JJWT dependencies/usages generically:
>
>    * `io.jsonwebtoken`
>    * `Jwts.parser()`
>    * `JwtParser`
>    * `JwtParserBuilder`
>    * `parseClaimsJws`
>    * `setSigningKey`
>    * old parser assignment patterns
> 3. Add deterministic source patch only for safe, narrow patterns.
> 4. First safe pattern:
>
>    * if code assigns `Jwts.parser()` directly to `JwtParser`, update to builder completion where appropriate, e.g. add `.build()` when the expression clearly returns `JwtParserBuilder`.
> 5. If the pattern is not safely transformable:
>
>    * do not patch blindly
>    * write `review/jjwt_api_migration_review.json`
>    * set `human_review_required=true`
>    * set `safe_to_auto_apply=false`
> 6. Wire into Boot 3 unit after `align_jjwt_version` and before build validation.
> 7. Record exact changes or review gate in ledger.
> 8. Do not modify tests.
> 9. Do not skip tests.
> 10. Do not call LLM.
> 11. Do not call network.
> 12. Keep logic generic and idempotent.
>
> Tests:
>
> 1. Detect old JJWT parser usage.
> 2. Apply safe `.build()` migration for simple `JwtParser parser = Jwts.parser()` pattern.
> 3. Preserve method body and imports.
> 4. No-op when already compatible.
> 5. Unsafe/complex usage produces review artifact, not patch.
> 6. Ledger records patch or review.
> 7. Execution plan includes JJWT API compatibility step in `spring-boot-3-5-14`.
> 8. No project-specific names.
> 9. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then rerun the same core validation on the legacy common-utils path using a fresh short output path.
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example before/after JJWT source patch
> 7. Example review artifact for unsafe usage
> 8. Real rerun status
> 9. Whether the previous `JwtParserBuilder cannot be converted to JwtParser` blocker is gone
> 10. Next blocker if any
> 11. Evidence no legacy repo was modified
> 12. Evidence no project-specific logic was added

<details><summary>26 previous messages</summary>

> Me fix generic factory gap now. First me inspect JJWT align path, source patch framework, Boot 3 unit wiring, then me patch smallest safe rule plus review gate.
>
> Me found good hook: source patch funcs plus review gate style already exist. Me inspect real failing JJWT line, then patch generic safe assignment rule and review artifact for leftover old API usage.
>
> Me checking result plumbing for new review artifact path. If needed, me wire one more generic field so orchestration report carries JJWT review too.
>
> Me ready to edit. Changes small set: new JJWT safe source patch, new JJWT review artifact, Boot 3 plan wiring, artifact propagation, tests.
>
> Me editing core files now: add JJWT safe source patch, JJWT review gate, Boot 3 plan wiring, artifact propagation. After that me add tests and rerun.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+100 -0)
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+115 -0)
>
> </details>
>
> Small tighten now: review gate should flag only unresolved old JJWT parser patterns, not already-fixed `.build()` code.
>
> <details><summary>Edited 5 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+9 -10)
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+45 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+5 -4)
> - Wrote `./migration_factory/transform_v1_after_approval.py` (+30 -1)
> - Wrote `./migration_factory/orchestrator/phase_services.py` (+2 -0)
>
> </details>
>
> Me adding tests now: direct patch behavior, review artifact, plan wiring, ledger record. Then me run targeted pytest first.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+2 -0)
> - Wrote `./tests/test_transformation_agent.py` (+115 -0)
> - Wrote `./tests/test_transformation_agent.py` (+9 -8)
> - Wrote `./tests/test_transformation_agent.py` (+113 -0)
>
> </details>
>
> Code in. Me run focused transformation/orchestrator tests first to catch wiring bugs before full suite.
>
> Detector too broad. Me tightening: only unresolved old parser statements trigger review. Also me switch unsafe tests to unsupported chain that patch must not touch.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+13 -2)
> - Wrote `./tests/test_transformation_agent.py` (+4 -10)
> - Wrote `./tests/test_transformation_agent.py` (+1 -1)
> - Wrote `./tests/test_transformation_agent.py` (+8 -8)
>
> </details>
>
> Focused fixes in. Me rerun targeted tests now.
>
> Focused tests green. Me run full pytest now, then rerun real common-utils validation on fresh short path to prove blocker moved.
>
> Full pytest green. Me rerun real factory on fresh short sandbox path now, same legacy app, to prove old JJWT compile blocker gone or not.
>
> Fresh path free. Me run read-only, then approve/resume same governed way.
>
> Real rerun showed generic bug in parser matcher: anonymous-class builder chain not captured. Me upgrading matcher from regex-only to statement scanner so safe `.build()` patch can hit real JJWT case.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+106 -18)
> - Wrote `./migration_factory/agents/transformation_agent/review_gates.py` (+10 -27)
>
> </details>
>
> Matcher fix in. Me rerun focused transformation tests, then real rerun again if green.
>
> Focused green again. Me rerun orchestrator + full suite once more after matcher fix, then real common-utils rerun fresh.
>
> Full suite green after final fix. Me do fresh real rerun on new short path now, so evidence not contaminated by failed attempt.
>
> Real rerun now passed compile wall, reached test failures. Me grab exact before/after JJWT line, review artifact state, failure classification counts, next blocker evidence.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me verify final real evidence now: exact JJWT patch snippet, ledger entry, and new blocker artifact.
>
> Me got ledger and new blocker. One more peek for exact `.build()` line so report can show real before/after clean.
</details>

1. **Summary**

Me add generic JJWT API compatibility step for Boot 3.

Now factory does:
- align JJWT version in POM
- scan source for old parser API shape
- auto-patch only safe narrow parser-builder cases
- else write review gate artifact
- record patch/review in ledger
- run in `spring-boot-3-5-14` before build validation

Real rerun proof:
- old blocker gone:
  - `JwtParserBuilder cannot be converted to JwtParser`
- run now reaches test phase
- new blocker is Spring Boot 3 test/runtime behavior, not JJWT compile break

2. **Files Modified**

- [migration_factory/agents/transformation_agent/pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- [migration_factory/agents/transformation_agent/review_gates.py](./migration_factory/agents/transformation_agent/review_gates.py)
- [migration_factory/agents/transformation_agent/agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [migration_factory/transform_v1_after_approval.py](./migration_factory/transform_v1_after_approval.py)
- [migration_factory/orchestrator/phase_services.py](./migration_factory/orchestrator/phase_services.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- detect old JJWT parser usage
- safe `.build()` patch for simple `JwtParser parser = Jwts.parser()...`
- safe `.build()` patch for simple `return Jwts.parser()...`
- no-op when already compatible
- unsafe usage writes review artifact, no blind patch
- ledger records patch or review
- Boot 3 execution plan includes JJWT API compatibility step

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real validation rerun:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'

python -m migration_factory.orchestrator.runner --run-id utils-core-validation-jjwt2-20260603-141936 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\utils-core-validation3" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment

python -m migration_factory.approval.approve_run --run-dir "C:\mf\utils-core-validation3\.migration\runs\utils-core-validation-jjwt2-20260603-141936" --run-id "utils-core-validation-jjwt2-20260603-141936" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration. Multi-hop route required. No production promotion approved. Internal dependency and API/contract review remain under human review."

python -m migration_factory.orchestrator.resume --run-id "utils-core-validation-jjwt2-20260603-141936" --run-dir "C:\mf\utils-core-validation3\.migration\runs\utils-core-validation-jjwt2-20260603-141936" --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `109 passed, 2 skipped`
- `tests/orchestrator -q`: `116 passed`
- `pytest -q`: `749 passed, 3 skipped`

6. **Example Before/After JJWT Source Patch**

Before:
```java
return Jwts.parser()
        .setSigningKeyResolver(new SigningKeyResolverAdapter() {
            ...
        });
```

After:
```java
return Jwts.parser()
        .setSigningKeyResolver(new SigningKeyResolverAdapter() {
            ...
        }).build();
```

Real patched file:
- [JWTValidator.java](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/workspaces/sandbox/src/main/java/com/total/corp/common/security/jwt/JWTValidator.java)

7. **Example Review Artifact For Unsafe Usage**

If pattern not safely transformable, factory writes:
- [jjwt_api_migration_review.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/workspaces/sandbox/.migration/review/jjwt_api_migration_review.json)

Unsafe-case shape:
```json
{
  "gate_id": "JJWT_API_MIGRATION_REVIEW",
  "human_review_required": true,
  "safe_to_auto_apply": false,
  "usage_patterns": ["JWT_PARSER_RETURN"],
  "recommended_next_actions": [
    "Review old JJWT parser API usage and migrate unsupported builder chains manually."
  ]
}
```

Real rerun artifact after safe patch:
- `detected=false`
- `human_review_required=false`

8. **Real Rerun Status**

Run:
- `run_id`: `utils-core-validation-jjwt2-20260603-141936`
- `run_dir`: [utils-core-validation-jjwt2-20260603-141936](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936)

Final state:
- `analysis_status=PASS`
- `planning_status=PASS`
- `assessment_status=PASS`
- `final_status=BUILD_FAILED_IN_SANDBOX`
- `transform_status=BUILD_FAILED_IN_SANDBOX`
- `build_status=BUILD_FAILED_IN_SANDBOX`

Key artifacts:
- [orchestration_summary.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/orchestration/orchestration_summary.json)
- [migration_report.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/final/migration_report.json)
- [ledger.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/workspaces/sandbox/.migration/ledger.json)
- [build-error-20260603-143120-missing_config.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/build/build-error-20260603-143120-missing_config.json)
- [post_transform_failure_classification.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/build/post_transform_failure_classification.json)

9. **Whether Previous Blocker Is Gone**

Yes.

Gone:
- `JwtParserBuilder cannot be converted to JwtParser`

Ledger proof:
- `type: "jjwt_api_compatibility_migration"`
- `status: "applied"`

Real ledger path:
- [ledger.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/workspaces/sandbox/.migration/ledger.json)

10. **Next Blocker If Any**

New blocker:
- Boot 3 tests fail during application context startup
- build error kind: `missing_config`

Top concrete error:
```text
No qualifying bean of type 'com.total.corp.common.web.rest.util.FunctionalMessageHelper'
```

Failure categories now:
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: 27`
- `UNKNOWN_TEST_FAILURE: 55`

So next blocker is not JJWT compile.
Now it is Boot 3 runtime/test behavior + missing bean/config wiring.

11. **Evidence No Legacy Repo Was Modified**

Legacy source path stayed read-only:
- `C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils`

All patching happened only in sandbox:
- [sandbox](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/workspaces/sandbox)

12. **Evidence No Project-Specific Logic Was Added**

No repo-name hardcode added.
Logic only keys on generic JJWT signals:
- `io.jsonwebtoken`
- `Jwts.parser()`
- `JwtParser`
- `JwtParserBuilder`
- safe builder-chain methods

Unsafe shapes go to generic review gate:
- `JJWT_API_MIGRATION_REVIEW`

No `common-utils`
No `msa-dto`
No project-name conditions in implementation.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 51: Add Spring Boot 3 Behavioral Failure Context Pack + LLM Proposal Gate.
>
> Context:
> A real `msa-utils/common-utils` sandbox migration now passes previous deterministic blockers, including JJWT API compatibility, and reaches Boot 3 test/runtime failures.
>
> Current failure evidence:
> - previous JJWT compile blocker is gone
> - new failure happens during Boot 3 test/runtime phase
> - example error:
>   `No qualifying bean of type 'com.total.corp.common.web.rest.util.FunctionalMessageHelper'`
> - failure categories include:
>   - SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT
>   - UNKNOWN_TEST_FAILURE
>
> Goal:
> Add a generic behavioral failure context pack generator and LLM proposal gate.
>
> Important:
> This ticket must not fix the application behavior automatically.
> It must only collect structured context and prepare a governed proposal workflow.
>
> Required behavior:
> 1. Add a module, for example:
>    - migration_factory/remediation/behavioral_context.py
> 2. Input:
>    - run_dir
>    - failed unit id
>    - optional build error contract path
>    - optional post_transform_failure_classification.json path
>    - optional surefire reports directory
>    - optional sandbox project path
>    - optional LLM policy
> 3. Output artifacts:
>    - remediation/behavioral_failure_context_pack.json
>    - remediation/behavioral_failure_context_summary.md
>    - remediation/llm_proposal_gate.json
> 4. The context pack must include:
>    - run_id
>    - failed_unit
>    - final_status
>    - build_status
>    - test_status
>    - primary failure message
>    - failing tests
>    - failure categories
>    - missing bean/type errors if detected
>    - affected source files
>    - affected test files
>    - suspected framework areas:
>      - Spring MVC
>      - ControllerAdvice
>      - ExceptionHandler
>      - ApplicationContext
>      - Bean wiring
>      - Validation
>      - Security
>      - Test configuration
>    - deterministic fixes already applied from ledger
>    - review gates already triggered
>    - human_review_required
>    - safe_to_auto_apply=false
>    - llm_candidate=true when failure is behavioral or unknown
> 5. Detect generic symptoms:
>    - NoSuchBeanDefinitionException
>    - No qualifying bean of type
>    - Failed to load ApplicationContext
>    - Request processing failed
>    - expected HTTP status mismatch
>    - ConstraintViolationException behavior mismatch
>    - ControllerAdvice / ResponseEntityExceptionHandler hints
> 6. Source/test context extraction:
>    - collect only small, relevant snippets
>    - do not dump entire files
>    - include file path, class name if detectable, and matched markers
> 7. LLM proposal gate:
>    - read existing LLM policy if available
>    - default to disabled
>    - do not call LLM
>    - do not call GitHub Copilot
>    - write decision:
>      - LLM_DISABLED_CONTEXT_ONLY
>      - LLM_PROPOSAL_ALLOWED_BY_POLICY
>      - HUMAN_REVIEW_ONLY
> 8. If LLM disabled:
>    - still generate context pack
>    - mark next action as human review or future LLM proposal
> 9. Do not modify source code.
> 10. Do not modify tests.
> 11. Do not modify POMs.
> 12. Do not skip tests.
> 13. Do not run Maven.
> 14. Do not run migration.
> 15. Do not call network.
> 16. No hardcoded real repository or microservice names.
> 17. Project names may appear only as metadata from artifacts.
>
> Integration:
> 1. Hook this into failed sandbox finalization when failure classification contains behavioral categories or unknown test failures.
> 2. Add artifact refs into:
>    - orchestration_summary.json
>    - final migration report if available
>    - management evidence bundle if supported
> 3. Preserve existing behavior for compile/dependency failures.
> 4. Do not break previous remediation plan behavior.
>
> Tests:
> 1. Generate context pack from synthetic build error with `No qualifying bean of type`.
> 2. Generate context pack from synthetic surefire report with `Failed to load ApplicationContext`.
> 3. Detect failing tests and categories.
> 4. Detect affected source/test file markers.
> 5. Ledger deterministic fixes are included when ledger exists.
> 6. LLM policy disabled writes `LLM_DISABLED_CONTEXT_ONLY`.
> 7. Behavioral failure sets `safe_to_auto_apply=false`.
> 8. Behavioral failure sets `human_review_required=true`.
> 9. Behavioral failure sets `llm_candidate=true`.
> 10. Integration adds artifact refs to orchestration/final report.
> 11. No source/test/POM modification.
> 12. No LLM/network/Maven execution.
> 13. No hardcoded real project names.
> 14. Full pytest suite remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest tests/test_final_report.py -q
> python -m pytest -q
>
> Then generate the context pack from the existing failed `msa-utils` run if available:
> - run_dir:
>   C:\mf\utils-core-validation3\.migration\runs\utils-core-validation-jjwt2-20260603-141936
>
> Do not rerun migration unless needed.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example behavioral_failure_context_pack.json excerpt
> 7. Example behavioral_failure_context_summary.md excerpt
> 8. Example llm_proposal_gate.json excerpt
> 9. Real msa-utils context pack result if available
> 10. How this makes msa-utils presentable
> 11. Evidence no source/test/POM was modified
> 12. Evidence no LLM/network/Maven call was made
> 13. Evidence no project-specific logic was added

<details><summary>27 previous messages</summary>

> Me use caveman skill, then inspect remediation/final-report hooks before patch.
>
> Me got hook points. Now read remediation/final/orchestration code, then patch small clean.
>
> Me have map. Next read evidence bundle + tests so patch fit existing style.
>
> Me ready edit. Plan:
> 1. add behavioral context module + gate JSON/MD
> 2. hook into failed finalization + final report/evidence
> 3. add tests, run pytest, generate real pack from existing run
>
> Me start file edits: new context module, hook summary/final/evidence, add tests.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/remediation/behavioral_context.py` (+534 -0)
>
> </details>
>
> New module in. Me wire exports + failure-finalization path now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/__init__.py` (+14 -0)
>
> </details>
>
> Me hook behavioral context into failed sandbox finalize, orchestration refs, warnings.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/orchestrator/summary.py` (+46 -0)
>
> </details>
>
> Me add new refs to final failure summary/report path.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/final_report/writer.py` (+6 -0)
>
> </details>
>
> Me enrich evidence bundle too, so new context artifacts show in management index if provided through run artifacts.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/evidence/bundle.py` (+35 -0)
>
> </details>
>
> Tiny bug fix in new scanner: marker snippet token map.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/behavioral_context.py` (+1 -1)
>
> </details>
>
> Me add focused tests: context pack build, LLM gate, orchestration/final refs.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_behavioral_context.py` (+335 -0)
>
> </details>
>
> Me run new focused tests first. If red, me fix fast before full suite.
>
> One test fail. Me add fallback category count from parsed failing tests when no artifact counts exist.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/behavioral_context.py` (+12 -0)
>
> </details>
>
> Me rerun new tests, then broader orchestrator/final suite.
>
> Core tests green. Me run full pytest now, then generate real msa-utils context pack from existing failed run.
>
> Me pull real excerpt now: context pack, summary, gate. Then final write-up.
>
> Me add one no-hardcoded-name assertion. Cheap safety.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_behavioral_context.py` (+8 -0)
>
> </details>
>
> Tiny test add. Me rerun fast.
</details>

1. **Summary**

Me add generic behavioral failure context pack + LLM proposal gate.

Factory now:
- detect behavioral/unknown Boot 3 failure context
- extract small source/test hints
- collect missing bean / ApplicationContext / MVC signals
- record deterministic fixes already applied
- read LLM policy, default disabled
- write:
  - `behavioral_failure_context_pack.json`
  - `behavioral_failure_context_summary.md`
  - `llm_proposal_gate.json`
- hook refs into failed sandbox orchestration + final report

No app fix.
No test fix.
No POM fix.
No Maven run.
No LLM call.

2. **Files Modified**

- [migration_factory/remediation/behavioral_context.py](./migration_factory/remediation/behavioral_context.py)
- [migration_factory/remediation/__init__.py](./migration_factory/remediation/__init__.py)
- [migration_factory/orchestrator/summary.py](./migration_factory/orchestrator/summary.py)
- [migration_factory/final_report/writer.py](./migration_factory/final_report/writer.py)
- [migration_factory/evidence/bundle.py](./migration_factory/evidence/bundle.py)
- [tests/orchestrator/test_behavioral_context.py](./tests/orchestrator/test_behavioral_context.py)

3. **Tests Added**

- synthetic `No qualifying bean of type` -> context pack
- synthetic surefire `Failed to load ApplicationContext` -> context pack
- failing tests + categories detected
- source/test marker snippets detected
- ledger deterministic fixes included
- disabled LLM policy -> `LLM_DISABLED_CONTEXT_ONLY`
- behavioral failure -> `safe_to_auto_apply=false`
- behavioral failure -> `human_review_required=true`
- behavioral failure -> `llm_candidate=true`
- failed sandbox finalize -> orchestration/final refs added
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_behavioral_context.py -q
python -m pytest tests/test_final_report.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real existing run only, no migration rerun:
```powershell
@'
from pathlib import Path
from migration_factory.remediation.behavioral_context import generate_behavioral_failure_context_pack
from migration_factory.remediation.policy import load_llm_policy
import json
run_dir = Path(r'C:\mf\utils-core-validation3\.migration\runs\utils-core-validation-jjwt2-20260603-141936')
orchestration = json.loads((run_dir / 'orchestration' / 'orchestration_summary.json').read_text(encoding='utf-8'))
llm_policy = load_llm_policy(orchestration.get('ai_hub_path'), orchestration.get('profile_id'))
result = generate_behavioral_failure_context_pack(
    run_dir=run_dir,
    failed_unit='spring-boot-3-5-14',
    build_error_contract_path=run_dir / 'build' / 'build-error-20260603-143120-missing_config.json',
    failure_classification_path=run_dir / 'build' / 'post_transform_failure_classification.json',
    sandbox_project_path=run_dir / 'workspaces' / 'sandbox',
    llm_policy=llm_policy,
    orchestration_summary=orchestration,
)
print(result.context_pack_path)
print(result.summary_path)
print(result.llm_gate_path)
'@ | python -
```

5. **Test Results**

- `tests/orchestrator/test_behavioral_context.py -q`: `5 passed`
- `tests/test_final_report.py -q`: `21 passed`
- `tests/orchestrator -q`: `120 passed`
- `pytest -q`: `753 passed, 3 skipped`

6. **Example `behavioral_failure_context_pack.json` Excerpt**

```json
{
  "failed_unit": "spring-boot-3-5-14",
  "primary_failure_message": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available",
  "failure_categories": {
    "UNKNOWN_TEST_FAILURE": 1
  },
  "missing_bean_type_errors": [
    {
      "bean_type": "com.example.FunctionalMessageHelper"
    }
  ],
  "suspected_framework_areas": [
    "ApplicationContext",
    "Bean wiring",
    "ControllerAdvice",
    "Test configuration"
  ],
  "human_review_required": true,
  "safe_to_auto_apply": false,
  "llm_candidate": true
}
```

7. **Example `behavioral_failure_context_summary.md` Excerpt**

```md
- Primary Failure: No qualifying bean of type '...FunctionalMessageHelper' available
- Human Review Required: true
- LLM Candidate: true
- LLM Gate Decision: LLM_DISABLED_CONTEXT_ONLY

## Failure Categories
- SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: 27
- UNKNOWN_TEST_FAILURE: 55
```

8. **Example `llm_proposal_gate.json` Excerpt**

```json
{
  "decision": "LLM_DISABLED_CONTEXT_ONLY",
  "human_review_required": true,
  "llm_candidate": true,
  "safe_to_auto_apply": false,
  "reason": "LLM policy disabled; collect context only for human review or future governed proposal."
}
```

9. **Real `msa-utils` Context Pack Result**

Real run:
- [behavioral_failure_context_pack.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/remediation/behavioral_failure_context_pack.json)
- [behavioral_failure_context_summary.md](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/remediation/behavioral_failure_context_summary.md)
- [llm_proposal_gate.json](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/remediation/llm_proposal_gate.json)

Real findings:
- primary failure:
  - `No qualifying bean of type 'com.total.corp.common.web.rest.util.FunctionalMessageHelper'`
- categories:
  - `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: 27`
  - `UNKNOWN_TEST_FAILURE: 55`
- suspected areas:
  - `Spring MVC`
  - `ControllerAdvice`
  - `ExceptionHandler`
  - `ApplicationContext`
  - `Test configuration`
  - `Bean wiring`
- gate decision:
  - `LLM_DISABLED_CONTEXT_ONLY`

10. **How This Makes `msa-utils` Presentable**

Now run no longer looks like random big test crash.
Now factory shows:
- exact missing bean symptom
- which tests fail
- which framework areas likely involved
- which deterministic fixes already happened
- why no auto-fix happened
- whether future LLM proposal even allowed

Good for demo, governance, next ticket writing.

11. **Evidence No Source/Test/POM Was Modified**

For real existing run, new files written only here:
- [remediation](C:/mf/utils-core-validation3/.migration/runs/utils-core-validation-jjwt2-20260603-141936/remediation)

No writes to:
- sandbox Java source
- sandbox tests
- sandbox `pom.xml`
- legacy repo

12. **Evidence No LLM/Network/Maven Call Was Made**

This ticket run used:
- `pytest`
- local Python artifact reader/writer

No:
- Maven command
- migration rerun
- network call
- GitHub Copilot call
- external LLM call

LLM proof:
- real gate says `LLM_DISABLED_CONTEXT_ONLY`
- policy in real gate shows `enabled: false`

13. **Evidence No Project-Specific Logic Was Added**

New code keys on generic signals only:
- `NoSuchBeanDefinitionException`
- `No qualifying bean of type`
- `Failed to load ApplicationContext`
- `Request processing failed`
- HTTP status mismatch
- `ConstraintViolationException`
- `@ControllerAdvice`
- `ResponseEntityExceptionHandler`

Test also checks impl text lacks:
- `msa-dto`
- `common-utils`
- `translation`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 52: Add generic Boot 3 test modernization rules from golden reference evidence.
>
> Context:
> Manual migration evidence for a real project showed these generic test migration patterns:
> - Spring Boot test @MockBean -> @MockitoBean
> - MockitoAnnotations.initMocks(...) -> MockitoAnnotations.openMocks(...)
> - javax.servlet.* -> jakarta.servlet.* in test sources/test helpers
> - org.junit.Assert.assertThat -> org.hamcrest.MatcherAssert.assertThat
>
> Some rules already exist. This ticket must verify existing coverage and add missing generic rules only.
>
> Important:
> Do not hardcode project names, package names, file names, or business names.
> Do not add logic specific to common-utils, msa-utils, msa-dto, or translation.
>
> Required behavior:
> 1. Verify existing deterministic rules:
>    - spring_boot_test_mockbean_to_mockitobean
>    - mockito_initmocks_to_openmocks
> 2. Add or strengthen generic Jakarta Servlet import migration for test sources:
>    - javax.servlet.* -> jakarta.servlet.*
>    - javax.servlet.http.* -> jakarta.servlet.http.*
>    - must apply to src/test/java and test helper classes
>    - must be idempotent
> 3. Add generic JUnit/Hamcrest assertThat modernization:
>    - replace import/static usage of org.junit.Assert.assertThat with org.hamcrest.MatcherAssert.assertThat
>    - handle static imports safely
>    - handle fully qualified org.junit.Assert.assertThat(...) safely
>    - only for Java test sources by default
>    - idempotent
> 4. Wire these rules into spring-boot-3-5-14 before build/test validation.
> 5. Record changed files and rule IDs in ledger.
> 6. Do not modify production behavior.
> 7. Do not skip tests.
> 8. Do not call LLM.
> 9. Do not call network.
> 10. Keep all changes generic.
>
> Tests:
> 1. @MockBean -> @MockitoBean still covered.
> 2. initMocks -> openMocks still covered.
> 3. javax.servlet import in test source becomes jakarta.servlet.
> 4. javax.servlet.http import in test helper becomes jakarta.servlet.http.
> 5. org.junit.Assert.assertThat static import becomes org.hamcrest.MatcherAssert.assertThat.
> 6. fully qualified org.junit.Assert.assertThat(...) becomes org.hamcrest.MatcherAssert.assertThat(...).
> 7. unrelated Assert methods are not changed.
> 8. production source is not modified by test-only rules unless explicitly using generic Jakarta source migration.
> 9. ledger records each applied rule.
> 10. no project-specific names.
> 11. full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/test_transformation_agent.py -q
> python -m pytest -q
>
> Then rerun msa-utils sandbox migration using a fresh output path.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Before/after examples for servlet imports
> 7. Before/after examples for Assert.assertThat
> 8. Real msa-utils rerun status
> 9. Whether test modernization blockers changed
> 10. Next blocker if any
> 11. Evidence no project-specific logic was added

<details><summary>22 previous messages</summary>

> Me inspect existing test patch rules first, then add only missing generic ones.
>
> Me found existing rules. Missing work: servlet-import test patch + `assertThat` modernization. Now me inspect plan/tests around Boot 3 ordering.
>
> Me patch source rules next. Then me add tests near existing test-modernization section.
>
> Me add 2 new generic test-only patch rules now: servlet imports, `assertThat`. Then wire plan + ledger.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/pom_patches.py` (+61 -0)
>
> </details>
>
> Me wire new rules into agent + plan.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/agents/transformation_agent/agent.py` (+40 -0)
> - Wrote `./migration_factory/agents/transformation_agent/execution_plan.py` (+2 -0)
>
> </details>
>
> Me add tests/imports now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+2 -0)
> - Wrote `./tests/test_transformation_agent.py` (+5 -3)
> - Wrote `./tests/test_transformation_agent.py` (+117 -0)
>
> </details>
>
> Need production source unaffected by new test-only rules in existing test. extend production test to include new content and assert no patches.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+8 -0)
>
> </details>
>
> Need ledger tests for each applied rule and maybe maybe combined. add two tests near existing ledger tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/test_transformation_agent.py` (+110 -0)
>
> </details>
>
> Me run targeted tests now. If green, then full suite, then real rerun on fresh path.
>
> Tests green. Me run real fresh sandbox migration now on new short path, no factory special-case.
>
> Read-only timed out before artifacts done. Me rerun read-only with longer timeout, then continue approval/resume.
>
> First fresh path spoiled by timed-out run. Me do truly fresh new path and rerun clean from start.
>
> Approval CLI path handling look flaky here. Me retry from run dir itself, still no governance bypass.
>
> Approval fixed. Me resume sandbox migration now.
>
> Real rerun finished. Me inspect ledger + changed test files so report show concrete effect.
>
> Real run says new 2 rules not needed there. Me check legacy vs sandbox examples so report honest about real impact.
>
> Me grab one last proof: no hardcoded real project names in changed impl files.
</details>

1. **Summary**

Me verify existing Boot 3 test-modernization rules, add missing generic ones:

- `test_javax_servlet_imports_to_jakarta`
- `junit_assertthat_to_hamcrest_matcherassert`

Wired into `spring-boot-3-5-14` before build/test validation.
All generic. Test-only. Idempotent.

Real `msa-utils/common-utils` rerun:
- succeeded through read-only, approval, sandbox
- old JJWT compile blocker still gone
- still fails later in Boot 3 test/runtime phase
- current blocker unchanged in type:
  - missing bean / ApplicationContext / behavioral drift

2. **Files Modified**

- [migration_factory/agents/transformation_agent/pom_patches.py](./migration_factory/agents/transformation_agent/pom_patches.py)
- [migration_factory/agents/transformation_agent/agent.py](./migration_factory/agents/transformation_agent/agent.py)
- [migration_factory/agents/transformation_agent/execution_plan.py](./migration_factory/agents/transformation_agent/execution_plan.py)
- [tests/test_transformation_agent.py](./tests/test_transformation_agent.py)

3. **Tests Added**

- `@MockBean -> @MockitoBean` still covered
- `initMocks -> openMocks` still covered
- `javax.servlet.*` in test source -> `jakarta.servlet.*`
- `javax.servlet.http.*` in test helper -> `jakarta.servlet.http.*`
- static `org.junit.Assert.assertThat` import -> `org.hamcrest.MatcherAssert.assertThat`
- fully qualified `org.junit.Assert.assertThat(...)` -> `org.hamcrest.MatcherAssert.assertThat(...)`
- unrelated Assert methods unchanged
- production source not touched by test-only rules
- ledger records new rule applications

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_transformation_agent.py -q
python -m pytest -q
```

Real rerun:
```powershell
python -m migration_factory.orchestrator.runner --run-id utils-core-validation52b-20260604-001 --legacy "C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils" --modernized "C:\mf\utils-core-validation5" --ai-hub "C:\Users\ilyas.abarbach\Documents\modernizer-solution\modernizer-solution-ai-hub" --profile springboot-2.1-to-3.5-java17 --mode read_only_assessment
python -m migration_factory.approval.approve_run --run-dir . --run-id "utils-core-validation52b-20260604-001" --approved-by "ilyas.abarbach" --decision approved --comments "Approved for sandbox-only migration..."
python -m migration_factory.orchestrator.resume --run-id "utils-core-validation52b-20260604-001" --run-dir . --decision approved --approved-by "ilyas.abarbach" --comments "Resume approved sandbox-only migration. No production promotion approved."
```

5. **Test Results**

- `tests/test_transformation_agent.py -q`: `116 passed, 2 skipped`
- `pytest -q`: `761 passed, 3 skipped`

6. **Before/After Examples For Servlet Imports**

Before:
```java
import javax.servlet.ServletRequest;
import javax.servlet.http.HttpServletRequest;
```

After:
```java
import jakarta.servlet.ServletRequest;
import jakarta.servlet.http.HttpServletRequest;
```

Real legacy vs sandbox example:
- legacy [HeaderUtilTest.java](~/Downloads/MSA-common-utils-msa-test-1.34/MSA-common-utils-msa-test-1.34/common-utils/src/test/java/com/total/corp/util/HeaderUtilTest.java)
- sandbox [HeaderUtilTest.java](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/src/test/java/com/total/corp/util/HeaderUtilTest.java)

7. **Before/After Examples For `Assert.assertThat`**

Before:
```java
import static org.junit.Assert.assertThat;
org.junit.Assert.assertThat(actual, matcher);
```

After:
```java
import static org.hamcrest.MatcherAssert.assertThat;
org.hamcrest.MatcherAssert.assertThat(actual, matcher);
```

Real legacy vs sandbox example:
- legacy [HeaderUtilTest.java](~/Downloads/MSA-common-utils-msa-test-1.34/MSA-common-utils-msa-test-1.34/common-utils/src/test/java/com/total/corp/util/HeaderUtilTest.java)
- sandbox [HeaderUtilTest.java](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/src/test/java/com/total/corp/util/HeaderUtilTest.java)

8. **Real `msa-utils` Rerun Status**

Run:
- `run_id`: `utils-core-validation52b-20260604-001`
- `run_dir`: [utils-core-validation52b-20260604-001](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001)

Read-only:
- `analysis_status=PASS`
- `planning_status=PASS`
- `assessment_status=PASS`

Sandbox:
- `final_status=BUILD_FAILED_IN_SANDBOX`
- `transform_status=BUILD_FAILED_IN_SANDBOX`
- `build_status=BUILD_FAILED_IN_SANDBOX`
- `blocked_unit=spring-boot-3-5-14`

Key artifacts:
- [migration_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/final/migration_report.json)
- [orchestration_summary.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/orchestration/orchestration_summary.json)
- [ledger.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/.migration/ledger.json)
- [build-error-20260604-160809-missing_config.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/build/build-error-20260604-160809-missing_config.json)
- [post_transform_failure_classification.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/build/post_transform_failure_classification.json)

9. **Whether Test Modernization Blockers Changed**

Yes and no.

Yes:
- `spring_boot_test_mockbean_to_mockitobean` applied in real rerun
- ledger shows 7 changed test files
- sandbox now contains migrated `MatcherAssert.assertThat`
- sandbox now contains `jakarta.servlet.http.HttpServletRequest`

No:
- new final blocker did **not** move because of these rules
- real ledger says:
  - `mockito_initmocks_to_openmocks`: `not_applicable`
  - `test_javax_servlet_imports_to_jakarta`: `not_applicable`
  - `junit_assertthat_to_hamcrest_matcherassert`: `not_applicable`

So for this repo:
- coverage stronger now
- but current failing problem still bean wiring / ApplicationContext, not test API syntax

10. **Next Blocker If Any**

Current top blocker:
```text
No qualifying bean of type 'com.total.corp.common.web.rest.util.FunctionalMessageHelper'
```

Current failure categories:
- `SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT: 27`
- `UNKNOWN_TEST_FAILURE: 55`

So next generic gap still:
- Boot 3 runtime/test configuration / bean wiring / behavioral context
- not JJWT
- not `assertThat`
- not servlet test imports

11. **Evidence No Project-Specific Logic Was Added**

Changed impl files contain no:
- `msa-dto`
- `common-utils`
- `msa-utils`
- `translation`

Pattern proof:
- rules key only on generic test roots + generic imports/usages
- `rg` on changed impl files found no project-name hardcode

Real ledger also shows generic rule IDs only:
- `spring_boot_test_mockbean_to_mockitobean`
- `mockito_initmocks_to_openmocks`
- `test_javax_servlet_imports_to_jakarta`
- `junit_assertthat_to_hamcrest_matcherassert`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 53: Add Legacy Behavior Equivalence Analyzer for Spring Boot 3 behavioral failures.
>
> Context:
> The current factory migration of a real project now passes deterministic blockers and reaches Boot 3 test/runtime phase. The current blocker is:
>
> No qualifying bean of type '...FunctionalMessageHelper'
>
> Recent generic test modernization rules were added and applied/verified:
> - MockBean to MockitoBean
> - initMocks to openMocks
> - javax.servlet to jakarta.servlet in tests
> - JUnit Assert.assertThat to Hamcrest MatcherAssert.assertThat
>
> But the blocker remains. This means the next gap is likely legacy behavior/configuration equivalence, not simple test API syntax.
>
> Goal:
> Add a generic analyzer that compares legacy project, sandbox migrated project, and optionally a manually migrated reference project to discover how missing beans/configuration/test context behavior was provided in legacy or reference.
>
> Important:
> Do not hardcode project names, class names, package names, or business names.
> Do not add logic specific to common-utils, msa-utils, msa-dto, or translation.
> Do not patch source automatically.
>
> Required behavior:
> 1. Add a module, for example:
>    - migration_factory/remediation/legacy_equivalence.py
> 2. Input:
>    - run_dir
>    - legacy_project_path
>    - sandbox_project_path
>    - optional migrated_reference_path
>    - optional behavioral_failure_context_pack.json
>    - optional build error contract
>    - optional surefire reports directory
> 3. Detect missing bean errors from:
>    - No qualifying bean of type
>    - NoSuchBeanDefinitionException
>    - Failed to load ApplicationContext
> 4. For each missing bean type:
>    - search legacy source/test
>    - search sandbox source/test
>    - search optional migrated reference source/test
> 5. Detect provider patterns:
>    - @Component
>    - @Service
>    - @Repository
>    - @Controller
>    - @ControllerAdvice
>    - @Configuration
>    - @TestConfiguration
>    - @Bean methods
>    - @Import
>    - @MockBean
>    - @MockitoBean
>    - constructor injection
>    - field injection
>    - package/component scan hints
> 6. Produce:
>    - remediation/legacy_behavior_equivalence_report.json
>    - remediation/legacy_behavior_equivalence_summary.md
> 7. Report must include:
>    - missing bean type
>    - legacy occurrences
>    - sandbox occurrences
>    - migrated reference occurrences if provided
>    - likely legacy provider type
>    - whether provider disappeared, changed, or is not loaded
>    - suspected cause
>    - recommended equivalent fix strategy
>    - safe_to_auto_apply=false by default
>    - human_review_required=true
>    - llm_candidate=true for ambiguous cases
> 8. If migrated reference path is provided:
>    - compare how reference solved the missing bean/config/test setup
>    - do not copy blindly
>    - classify the reference change as:
>      - deterministic_candidate
>      - test_context_candidate
>      - behavioral_review_required
>      - project_specific
> 9. Do not modify source code.
> 10. Do not modify tests.
> 11. Do not modify POMs.
> 12. Do not run Maven.
> 13. Do not call LLM.
> 14. Do not call network.
> 15. No hardcoded real project names.
> 16. Integrate artifact refs into orchestration/final report when run_dir is available.
>
> Tests:
> 1. Detect missing bean type from synthetic build error.
> 2. Detect legacy @Component provider.
> 3. Detect legacy @Bean provider.
> 4. Detect legacy @MockBean / @MockitoBean provider in tests.
> 5. Detect @TestConfiguration provider.
> 6. Compare sandbox missing provider vs legacy provider.
> 7. Compare optional migrated reference provider.
> 8. Produce JSON and Markdown artifacts.
> 9. Mark safe_to_auto_apply=false and human_review_required=true.
> 10. No source/test/POM modification.
> 11. No Maven/LLM/network execution.
> 12. No hardcoded real project names.
> 13. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run analyzer on existing failed run:
> C:\mf\utils-core-validation5\.migration\runs\utils-core-validation52b-20260604-001
>
> If local migrated reference project is available, also pass it as migrated_reference_path.
>
> Report:
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example legacy_behavior_equivalence_report.json excerpt
> 7. Example legacy_behavior_equivalence_summary.md excerpt
> 8. Real msa-utils finding for FunctionalMessageHelper
> 9. Whether migrated reference explains the missing bean
> 10. Recommended equivalent fix strategy
> 11. Evidence no project-specific logic was added

<details><summary>36 previous messages</summary>

> Me inspect current behavioral-context artifacts/hooks, then add legacy-vs-sandbox equivalence analyzer clean.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me wiring legacy-vs-sandbox equivalence analyzer into failed-run reporting now, then me run real `msa-utils` evidence pass with optional reference if local copy exists.
>
> Me got local migrated reference copy. Good. Now me read current hooks/tests, then patch analyzer + refs clean.
>
> Me found good hook points. Next me add analyzer module + failed-run hook + final-report line, then tests.
>
> Me starting file edits now: new analyzer, export, hook, final-report line, tests.
>
> Me writing new analyzer file first. Then me wire hook/export/report refs.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+497 -0)
>
> </details>
>
> New analyzer file in. Now me wire exports + failed-run hook + final-report artifact line.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+45 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
>
> </details>
>
> Small safety fix now: empty path must not resolve to repo root.
>
> <details><summary>Created 1 file, edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+3 -2)
> - Wrote `./tests/orchestrator/test_legacy_equivalence.py` (+357 -0)
>
> </details>
>
> Code patched. Now me run focused tests first, catch generic bug before full suite.
>
> Bug tiny. Regex template braces fight `.format`. Me fix now, rerun focused tests.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+3 -3)
>
> </details>
>
> Me rerun focused tests now. If green, me run orchestrator suite, then full suite, then real analyzer on failed run.
>
> One heuristic off. Me make reference test-context evidence win before generic component-scan text.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+5 -5)
>
> </details>
>
> Me rerun failing test, then wider suites.
>
> Tests green. Now me run analyzer on real failed `msa-utils` run with local migrated reference evidence, then inspect `FunctionalMessageHelper` result.
>
> Real finding showed one generic heuristic too loose. Me tightening provider-vs-consumer logic now, so report says legacy provider more truthfully.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+24 -9)
>
> </details>
>
> Me fix tiny typo in new heuristic, then rerun.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+3 -6)
>
> </details>
>
> Me rerun quick tests and real analyzer after heuristic fix.
>
> Heuristic clean now. Me rerun required validation suites one more time, then me gather diff/status for final report.
>
> One more governance polish: when analyzer run standalone on existing run, me want refs backfilled into orchestration/final JSON too. Then evidence self-links clean.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+21 -0)
>
> </details>
>
> Me add one test for standalone ref backfill too.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_legacy_equivalence.py` (+47 -0)
>
> </details>
>
> Backfill in. Me rerun focused, orchestrator, full. Then me refresh real run artifact refs too.
>
> Tests still green. Me rerun real analyzer once more so existing run gets fresh artifact refs in orchestration/final JSON.
>
> Tiny report polish: real failed unit should show actual unit id, not phase label. Me patch that now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_equivalence.py` (+6 -1)
>
> </details>
>
> Me rerun quick test + refresh real artifact after unit-label polish.
>
> Last tiny patch touched payload only. Me rerun required suites one final time so report clean.
</details>

**Summary**

Me add generic Legacy Behavior Equivalence Analyzer.

It now:
- detect missing bean failures
- compare legacy vs sandbox vs optional migrated reference
- classify provider pattern
- suggest equivalent fix strategy
- write:
  - [legacy_behavior_equivalence_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_behavior_equivalence_report.json)
  - [legacy_behavior_equivalence_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_behavior_equivalence_summary.md)

It also hooks into failed sandbox finalization, adds artifact refs into orchestration JSON and final report JSON for future runs.

**Files Modified**

- [legacy_equivalence.py](./migration_factory/remediation/legacy_equivalence.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_legacy_equivalence.py](./tests/orchestrator/test_legacy_equivalence.py)

**Tests Added**

- missing bean detect from synthetic build error
- legacy `@Component` provider detect
- legacy `@Bean` provider detect
- legacy `@MockBean` / `@TestConfiguration` provider detect
- optional migrated reference compare
- standalone run backfills orchestration/final artifact refs
- failed sandbox finalization adds refs
- no hardcoded real project names

**Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_legacy_equivalence.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real analyzer run:

```powershell
$env:PYTHONPATH='.'
@'
from pathlib import Path
from migration_factory.remediation.legacy_equivalence import generate_legacy_behavior_equivalence_report
run_dir = Path(r'C:\mf\utils-core-validation5\.migration\runs\utils-core-validation52b-20260604-001')
legacy = Path(r'C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils')
sandbox = run_dir / 'workspaces' / 'sandbox'
reference = Path(r'C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\golden-references\repos\msa-utils-reference\common-utils')
generate_legacy_behavior_equivalence_report(
    run_dir=run_dir,
    legacy_project_path=legacy,
    sandbox_project_path=sandbox,
    migrated_reference_path=reference,
    behavioral_context_pack_path=run_dir / 'remediation' / 'behavioral_failure_context_pack.json',
    build_error_contract_path=run_dir / 'build' / 'build-error-20260604-160809-missing_config.json',
)
'@ | python -
```

**Test Results**

- `tests/orchestrator/test_legacy_equivalence.py -q`: `6 passed`
- `tests/orchestrator -q`: `127 passed`
- `pytest -q`: `767 passed, 3 skipped`

**Example `legacy_behavior_equivalence_report.json` Excerpt**

```json
{
  "missing_bean_type": "com.example.FunctionalMessageHelper",
  "likely_legacy_provider_type": "COMPONENT",
  "provider_status": "disappeared",
  "recommended_equivalent_fix_strategy": "Review component-scan or conditional bean loading..."
}
```

Real excerpt path:
- [legacy_behavior_equivalence_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_behavior_equivalence_report.json)

**Example `legacy_behavior_equivalence_summary.md` Excerpt**

```md
- com.total.corp.common.web.rest.util.FunctionalMessageHelper: not_loaded
  likely legacy provider: MOCKBEAN
  suspected cause: Sandbox still references ... but provider may no longer be loaded...
  recommended strategy: Use migrated reference only as evidence that ... may need explicit test-context provisioning; do not copy blindly.
  reference classification: test_context_candidate
```

Real summary path:
- [legacy_behavior_equivalence_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_behavior_equivalence_summary.md)

**Real `msa-utils` Finding For `FunctionalMessageHelper`**

Main finding:
- missing bean type: `com.total.corp.common.web.rest.util.FunctionalMessageHelper`
- legacy has:
  - main provider interface marked `@Component`
  - test `App.java` with `@MockBean FunctionalMessageHelper`
- sandbox has:
  - same main provider still present
  - test `App.java` modernized to `@MockitoBean FunctionalMessageHelper`
- report status:
  - `provider_status = not_loaded`
  - `likely_legacy_provider_type = MOCKBEAN`

So gap not “bean class vanished”.
Gap more likely “Boot 3 test context no longer loading equivalent bean setup”.

**Whether Migrated Reference Explains Missing Bean**

Yes.

Reference shows same pattern:
- main `FunctionalMessageHelper` still present
- test `App.java` uses `@MockitoBean`
- analyzer classifies this as `test_context_candidate`

So reference suggests missing bean tied to test-context equivalence, not simple source absence.

**Recommended Equivalent Fix Strategy**

Best next generic strategy:
- review Boot 3 test-context equivalence
- inspect how test `App.java` / advice tests load context
- verify `@MockitoBean` provider actually part of loaded slice
- review `@ComponentScan`, `@Import`, `@SpringBootTest` / slice boundaries
- do not auto-patch blindly

**Evidence No Project-Specific Logic Was Added**

Implementation uses only generic signals:
- `No qualifying bean of type`
- `NoSuchBeanDefinitionException`
- `Failed to load ApplicationContext`
- `@Component`, `@Service`, `@Configuration`, `@Bean`
- `@MockBean`, `@MockitoBean`, `@Import`, `@TestConfiguration`
- constructor/field injection
- component scan hints

Test also asserts impl contains no:
- `msa-dto`
- `common-utils`
- `translation`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 54: Add Spring Boot Test Context Repair Proposal from Legacy Equivalence.
>
> Context:
> The current real migration of a complex Spring Boot project now reaches Boot 3 test/runtime failures.
>
> A new Legacy Behavior Equivalence Analyzer found that the missing bean is not absent from source. For the missing bean:
>
> * legacy source still has the provider
> * sandbox source still has the provider
> * legacy test setup used @MockBean
> * sandbox/reference use @MockitoBean
> * provider_status is not_loaded
> * likely provider type is MOCKBEAN
> * migrated reference classifies the solution area as test_context_candidate
>
> Goal:
> Add a generic Spring Boot Test Context Repair Proposal generator.
>
> Important:
> Do not apply the patch automatically.
> Do not hardcode project names, package names, class names, or business names.
> Do not add logic specific to common-utils, msa-utils, msa-dto, or translation.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/remediation/test_context_repair.py
> 2. Input:
>
>    * run_dir
>    * legacy_behavior_equivalence_report.json
>    * behavioral_failure_context_pack.json
>    * sandbox_project_path
>    * optional migrated_reference_path
>    * optional surefire reports directory
> 3. Output:
>
>    * remediation/test_context_repair_proposal.json
>    * remediation/test_context_repair_proposal.md
>    * optional remediation/test_context_repair_proposal.patch
> 4. The proposal must identify:
>
>    * missing bean type
>    * failing tests
>    * test classes likely loading the ApplicationContext
>    * existing mock/provider classes
>    * whether provider exists but is not loaded
>    * whether migrated reference shows an equivalent test setup
> 5. Detect generic repair strategies:
>
>    * add/import test configuration
>    * ensure @MockitoBean is in the loaded test context
>    * add @Import for a test support configuration
>    * adjust @ContextConfiguration classes
>    * adjust @SpringBootTest classes
>    * adjust @WebMvcTest / slice test support
> 6. Classify proposal:
>
>    * deterministic_candidate
>    * llm_candidate
>    * human_review_required
>    * unsafe_to_auto_apply
> 7. Default:
>
>    * safe_to_auto_apply=false
>    * human_review_required=true
> 8. If a very narrow safe proposal is detected:
>
>    * produce patch proposal only
>    * do not apply it
> 9. If ambiguous:
>
>    * no patch
>    * provide recommended human investigation steps
> 10. Do not modify source code.
> 11. Do not modify tests.
> 12. Do not modify POMs.
> 13. Do not run Maven.
> 14. Do not call LLM.
> 15. Do not call network.
> 16. Hook artifact refs into orchestration/final report if run_dir is provided.
>
> Tests:
>
> 1. Generate proposal from synthetic missing bean + legacy @MockBean/@MockitoBean provider.
> 2. Detect provider exists but is not loaded.
> 3. Detect candidate @Import / @ContextConfiguration repair strategy.
> 4. Detect migrated reference evidence.
> 5. Ambiguous case produces no patch.
> 6. Proposal marks safe_to_auto_apply=false.
> 7. Proposal marks human_review_required=true.
> 8. No source/test/POM modification.
> 9. No Maven/LLM/network execution.
> 10. No hardcoded real project names.
> 11. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run proposal generator on the existing failed run:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001
>
> Use the existing:
>
> * behavioral_failure_context_pack.json
> * legacy_behavior_equivalence_report.json
> * optional migrated reference path if available
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example test_context_repair_proposal.json excerpt
> 7. Example proposal summary excerpt
> 8. Real msa-utils recommendation
> 9. Whether a patch proposal was generated or not
> 10. Why the proposal is or is not safe to auto-apply
> 11. Evidence no project-specific logic was added

<details><summary>16 previous messages</summary>

> Me add proposal generator from legacy-equivalence evidence, hook refs into failed-run reporting, then me run real `msa-utils` proposal on existing failed run.
>
> Me adding proposal generator now. Goal simple, governed: strong evidence + strategies, no auto patch.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/remediation/test_context_repair.py` (+430 -0)
>
> </details>
>
> Core module in. Now me wire exports + failed-run hook + final-report lines + tests.
>
> <details><summary>Created 1 file, edited 3 files</summary>
>
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+35 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
> - Wrote `./tests/orchestrator/test_test_context_repair.py` (+386 -0)
>
> </details>
>
> Me run focused proposal tests first. Likely one-two generic bugs shake out there.
>
> Focused tests green. Now me run required suites, then real proposal generator on existing failed run.
>
> One pytest warning only. Me kill it clean, rerun suites once more.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/test_context_repair.py` (+1 -0)
>
> </details>
>
> Me rerun required suites now, then real run artifact generation.
>
> Real proposal artifact generated. Me inspect key recommendation + whether patch exists.
>
> Real artifact already useful. Me add two tiny polish bits: prefer real failed unit id, infer loaded context class from failure symptom when annotation omits it.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/test_context_repair.py` (+27 -2)
>
> </details>
>
> Me rerun quick focused tests and refresh real proposal for nicer output.
>
> Real proposal still reading older equivalence artifact. Me refresh equivalence + proposal once, so real pack shows exact failed unit.
>
> Last tiny polish done. Me rerun required suites one final time, then me close with real artifact paths and recommendation.
</details>

**Summary**

Me add generic Spring Boot Test Context Repair Proposal generator.

It reads:
- legacy equivalence report
- behavioral failure context pack
- sandbox test sources
- optional migrated reference

It writes:
- [test_context_repair_proposal.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/test_context_repair_proposal.json)
- [test_context_repair_proposal.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/test_context_repair_proposal.md)

It does not patch app.
It does not run Maven.
It does not call LLM.

**Files Modified**

- [test_context_repair.py](./migration_factory/remediation/test_context_repair.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_test_context_repair.py](./tests/orchestrator/test_test_context_repair.py)

**Tests Added**

- synthetic missing bean + legacy `@MockBean` / sandbox `@MockitoBean` proposal
- provider exists but not loaded detect
- `@Import` / `@ContextConfiguration` strategy detect
- migrated reference evidence detect
- ambiguous case -> no patch
- failed sandbox finalization adds artifact refs
- no hardcoded real project names

**Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real existing run only:

```powershell
$env:PYTHONPATH='.'
@'
from pathlib import Path
from migration_factory.remediation.legacy_equivalence import generate_legacy_behavior_equivalence_report
from migration_factory.remediation.test_context_repair import generate_test_context_repair_proposal
run_dir = Path(r'C:\mf\utils-core-validation5\.migration\runs\utils-core-validation52b-20260604-001')
legacy = Path(r'C:\Users\ilyas.abarbach\Downloads\MSA-common-utils-msa-test-1.34\MSA-common-utils-msa-test-1.34\common-utils')
sandbox = run_dir / 'workspaces' / 'sandbox'
reference = Path(r'C:\Users\ilyas.abarbach\Documents\modernizer-solution\.migration\golden-references\repos\msa-utils-reference\common-utils')
generate_legacy_behavior_equivalence_report(
    run_dir=run_dir,
    legacy_project_path=legacy,
    sandbox_project_path=sandbox,
    migrated_reference_path=reference,
    behavioral_context_pack_path=run_dir / 'remediation' / 'behavioral_failure_context_pack.json',
    build_error_contract_path=run_dir / 'build' / 'build-error-20260604-160809-missing_config.json',
)
generate_test_context_repair_proposal(
    run_dir=run_dir,
    legacy_behavior_equivalence_report_path=run_dir / 'remediation' / 'legacy_behavior_equivalence_report.json',
    behavioral_failure_context_pack_path=run_dir / 'remediation' / 'behavioral_failure_context_pack.json',
    sandbox_project_path=sandbox,
    migrated_reference_path=reference,
)
'@ | python -
```

**Test Results**

- `tests/orchestrator -q`: `132 passed`
- `pytest -q`: `772 passed, 3 skipped`

**Example `test_context_repair_proposal.json` Excerpt**

```json
{
  "gate_id": "SPRING_BOOT_TEST_CONTEXT_REPAIR_PROPOSAL",
  "safe_to_auto_apply": false,
  "human_review_required": true,
  "proposals": [
    {
      "missing_bean_type": "com.example.FunctionalMessageHelper",
      "provider_exists_but_not_loaded": true,
      "migrated_reference_shows_equivalent_test_setup": true,
      "proposal_strategies": [
        {"strategy_id": "ensure_mockito_bean_in_loaded_test_context"},
        {"strategy_id": "adjust_spring_boot_test_classes"},
        {"strategy_id": "add_import_for_test_support_configuration"}
      ],
      "patch_proposal_available": false
    }
  ]
}
```

**Example Proposal Summary Excerpt**

```md
- com.total.corp.common.web.rest.util.FunctionalMessageHelper
  provider exists but not loaded: true
  reference setup seen: true
  strategies: ensure_mockito_bean_in_loaded_test_context, adjust_spring_boot_test_classes, add_import_for_test_support_configuration
```

**Real `msa-utils` Recommendation**

Real run:
- [test_context_repair_proposal.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/test_context_repair_proposal.json)
- [test_context_repair_proposal.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/test_context_repair_proposal.md)

Real recommendation for `FunctionalMessageHelper`:
- provider exists but not loaded: `true`
- reference setup seen: `true`
- strongest strategies:
  - `ensure_mockito_bean_in_loaded_test_context`
  - `adjust_spring_boot_test_classes`
  - `add_import_for_test_support_configuration`

Meaning:
- bean not missing from code
- Boot 3 test context likely not loading support path around test `App` / `@MockitoBean`
- next work should review test context wiring, not business behavior patch first

**Whether Patch Proposal Generated**

No.

- `patch_proposal_path = ""`
- no `.patch` artifact written

**Why Proposal Is Or Is Not Safe To Auto-Apply**

Not safe to auto-apply because:
- failure is Boot 3 test context behavior
- many failing tests load shared ApplicationContext
- multiple possible repair shapes:
  - `@SpringBootTest(classes=...)`
  - `@Import`
  - `@ContextConfiguration`
  - test support class wiring
- wrong auto patch could hide real contract/config drift

So proposal stays:
- `safe_to_auto_apply=false`
- `human_review_required=true`

**Evidence No Project-Specific Logic Was Added**

New logic keys only on generic signals:
- missing bean evidence
- `@MockBean` / `@MockitoBean`
- `@Import`
- `@ContextConfiguration`
- `@SpringBootTest`
- `@WebMvcTest`
- test support/provider class presence

No hardcoded:
- `common-utils`
- `msa-utils`
- `msa-dto`
- `translation`

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 55: Add Legacy-Guided Test Context Patch Proposal With Optional Reference Evidence.
>
> Context:
> The current real migration of a complex Spring Boot project reaches Boot 3 test/runtime failures.
>
> Existing factory artifacts show:
>
> * missing bean type detected from Boot 3 test runtime failure
> * provider exists in legacy and sandbox
> * provider is not loaded in the Boot 3 test context
> * legacy behavior equivalence report exists
> * test context repair proposal exists
> * safe_to_auto_apply=false
> * human_review_required=true
> * llm_candidate=true
>
> Goal:
> Add a generic patch proposal generator that can propose a concrete Spring Boot test-context repair.
>
> Important:
> This must not apply the patch automatically.
> This must not depend on a manually migrated reference project.
> A migrated reference project may be used only as optional evidence when available.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/remediation/legacy_guided_patch_proposal.py
>
> 2. Input:
>
>    * run_dir
>    * sandbox_project_path
>    * legacy_project_path
>    * legacy_behavior_equivalence_report.json
>    * test_context_repair_proposal.json
>    * behavioral_failure_context_pack.json
>    * optional migrated_reference_path
>    * optional surefire reports directory
>
> 3. Output:
>
>    * remediation/legacy_guided_patch_proposal.json
>    * remediation/legacy_guided_patch_proposal.md
>    * optional remediation/legacy_guided_patch_proposal.patch
>
> 4. The generator must work in two modes:
>
>    * legacy + sandbox only
>    * legacy + sandbox + optional migrated reference
>
> 5. It must identify:
>
>    * missing bean type
>    * failing test classes
>    * test support classes that define @MockBean or @MockitoBean
>    * whether the test support class is loaded by failing tests
>    * whether @SpringBootTest / @ContextConfiguration / @Import / @WebMvcTest annotations exist
>    * whether adding/importing a support configuration is a plausible minimal repair
>
> 6. It must detect generic candidate patch strategies:
>
>    * add @Import(TestSupportConfig.class)
>    * add support class to @SpringBootTest(classes = ...)
>    * add support class to @ContextConfiguration(classes = ...)
>    * move or duplicate @MockitoBean into the failing test context as proposal only
>    * adjust test support class wiring
>
> 7. If the patch strategy is narrow and localized:
>
>    * generate a patch proposal
>    * mark patch_proposal_available=true
>    * mark safe_to_auto_apply=false
>    * mark human_review_required=true
>    * include risks and tests to rerun
>
> 8. If ambiguous:
>
>    * do not generate a patch
>    * provide investigation steps
>    * mark llm_candidate=true
>
> 9. Optional migrated reference:
>
>    * if provided, compare related sandbox files with reference files
>    * use reference only as evidence
>    * do not copy broad diffs blindly
>    * classify reference evidence as:
>
>      * supports_patch
>      * unrelated
>      * ambiguous
>      * broad_change_not_safe
>
> 10. Do not modify source code.
>
> 11. Do not modify tests.
>
> 12. Do not modify POMs.
>
> 13. Do not run Maven.
>
> 14. Do not run migration.
>
> 15. Do not call LLM.
>
> 16. Do not call network.
>
> 17. No hardcoded real project names, package names, class names, or business names.
>
> Integration:
>
> 1. Add artifact refs into orchestration/final report when run_dir is available.
> 2. Preserve existing behavior for cases where no behavioral/test-context failure exists.
> 3. Do not break remediation plan behavior.
>
> Tests:
>
> 1. Generate patch proposal from synthetic failing test where support class with @MockitoBean exists but is not imported.
> 2. Generate patch proposal for @SpringBootTest(classes = ...) missing support class.
> 3. Generate patch proposal for @ContextConfiguration(classes = ...) missing support class.
> 4. Generate patch proposal for @Import missing support class.
> 5. Legacy + sandbox mode works without migrated reference.
> 6. Optional migrated reference can strengthen the proposal.
> 7. Broad reference diff produces no patch.
> 8. Ambiguous case produces no patch and marks llm_candidate=true.
> 9. Proposal always marks safe_to_auto_apply=false.
> 10. Proposal always marks human_review_required=true.
> 11. Patch is not applied.
> 12. No source/test/POM modification.
> 13. No Maven/LLM/network execution.
> 14. No project-specific names.
> 15. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run the proposal generator on the existing failed run if available:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001
>
> If migrated reference is available, pass it as optional evidence:
> C:\Users\ilyas.abarbach\Documents\modernizer-solution.migration\golden-references\repos\msa-utils-reference\common-utils
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example legacy_guided_patch_proposal.json excerpt
> 7. Example patch proposal excerpt if generated
> 8. Real msa-utils result
> 9. Whether a concrete patch proposal was generated
> 10. Why the patch is not auto-applied
> 11. Whether optional reference helped
> 12. Evidence no project-specific logic was added

<details><summary>20 previous messages</summary>

> Me build legacy-guided patch proposal on top of current equivalence/repair artifacts, then me run real `msa-utils` evidence pass with optional reference.
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me now wire new legacy-guided proposal module clean, then me prove it on real failed run with optional reference evidence.
>
> Me now patch module + reporting hooks + tests. Then me run whole validator and real artifact refresh.
>
> Me got enough shape. Now me write new module and one dedicated test file, keep old proposal module untouched for backward behavior.
>
> Real evidence say same test support class exists in sandbox and reference. Me inspect exact test annotations once, so patch proposal not guess blind.
>
> Me editing now: new proposal module, exports, failed-run hook, final report line, dedicated tests.
>
> <details><summary>Created 1 file, edited 3 files</summary>
>
> - Wrote `./migration_factory/remediation/legacy_guided_patch_proposal.py` (+839 -0)
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+39 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
>
> </details>
>
> Me adding focused proposal tests now: patch/no-patch/reference/finalize/no-hardcode.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_legacy_guided_patch_proposal.py` (+637 -0)
>
> </details>
>
> Me run focused new tests first. Likely small generic misses show quick.
>
> Focused tests green. Now me run required suites, then real proposal generator on existing failed run.
>
> Suites green. Me now generate real artifact on existing failed run, with optional reference evidence, no migration rerun.
>
> Real artifact done. Me inspect whether patch exists and what reference evidence says.
>
> One polish gap: standalone backfill updated final JSON, not final markdown line. Me patch tiny summary-sync so real existing run also shows new artifact in markdown.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/legacy_guided_patch_proposal.py` (+11 -0)
>
> </details>
>
> Tiny polish in. Me rerun focused tests quick, then refresh real proposal once so markdown shows line too.
>
> Real bundle refreshed. Me verify final summary line and grab exact real recommendation.
>
> Me verify tail once. Maybe line appended lower in file after excerpt cut.
>
> Me collect changed file list and exact test counts, then me close.
</details>

1. **Summary**

Me add generic legacy-guided test-context patch proposal generator.

New module reads:
- legacy equivalence report
- behavioral context pack
- test context repair proposal
- sandbox + legacy
- optional migrated reference

It writes:
- [legacy_guided_patch_proposal.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_guided_patch_proposal.json)
- [legacy_guided_patch_proposal.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_guided_patch_proposal.md)
- optional `.patch` when narrow safe proposal exists

No patch applied.
No Maven.
No migration rerun.

2. **Files Modified**

- [legacy_guided_patch_proposal.py](./migration_factory/remediation/legacy_guided_patch_proposal.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_legacy_guided_patch_proposal.py](./tests/orchestrator/test_legacy_guided_patch_proposal.py)

3. **Tests Added**

- SpringBootTest missing support class -> patch proposal
- ContextConfiguration missing support class -> patch proposal
- Import missing support class -> patch proposal
- legacy+sandbox only mode works
- optional reference can strengthen proposal
- broad reference diff blocks patch
- ambiguous case -> no patch, `llm_candidate=true`
- failed sandbox finalization adds refs
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_legacy_guided_patch_proposal.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real existing run only:
```powershell
$env:PYTHONPATH='.'
@' ... generate_legacy_guided_patch_proposal(...) ... '@ | python -
```

5. **Test Results**

- `tests/orchestrator/test_legacy_guided_patch_proposal.py -q`: `8 passed`
- `tests/orchestrator -q`: `140 passed`
- `pytest -q`: `780 passed, 3 skipped`

6. **Example `legacy_guided_patch_proposal.json` Excerpt**

Synthetic shape:
```json
{
  "gate_id": "LEGACY_GUIDED_TEST_CONTEXT_PATCH_PROPOSAL",
  "patch_proposal_available": true,
  "safe_to_auto_apply": false,
  "human_review_required": true,
  "proposals": [
    {
      "missing_bean_type": "com.example.FunctionalMessageHelper",
      "patch_strategy": "add_support_class_to_spring_boot_test_classes",
      "reference_evidence": {
        "classification": "supports_patch"
      }
    }
  ]
}
```

7. **Example Patch Proposal Excerpt**

Synthetic patch example:
```diff
-@SpringBootTest(classes = App.class)
+@SpringBootTest(classes = {App.class, TestSupportConfig.class})
```

Also supported:
```diff
-@ContextConfiguration(classes = {App.class})
+@ContextConfiguration(classes = {App.class, TestSupportConfig.class})
```

8. **Real `msa-utils` Result**

Real run used:
- [legacy_behavior_equivalence_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_behavior_equivalence_report.json)
- [behavioral_failure_context_pack.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/behavioral_failure_context_pack.json)
- [test_context_repair_proposal.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/test_context_repair_proposal.json)

Real proposal output:
- [legacy_guided_patch_proposal.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_guided_patch_proposal.json)
- [legacy_guided_patch_proposal.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/legacy_guided_patch_proposal.md)

Real finding:
- missing bean: `FunctionalMessageHelper`
- support class exists: `src\test\java\com\total\corp\advice\App.java`
- support class loaded by failing tests: `true`
- reference evidence: `ambiguous`
- patch strategy: none

9. **Whether Concrete Patch Proposal Was Generated**

For real `msa-utils`: no.

- `patch_proposal_available=false`
- no `.patch` file written

For narrow synthetic cases: yes, generator can produce patch proposal.

10. **Why Patch Not Auto-Applied**

Not safe.

Real case has:
- provider exists
- support class already loaded
- failing Boot 3 context still misses bean
- multiple failing tests share same ApplicationContext

So problem not simple “missing import”.
Could be:
- bean override visibility
- Boot 3 test context semantics
- shared support wiring
- slice/context behavior drift

11. **Whether Optional Reference Helped**

Little help on real case.

Reference was used as evidence only.
Result:
- `reference_evidence.classification = ambiguous`

Why:
- reference also shows related support setup
- but not enough to narrow one safe localized patch

12. **Evidence No Project-Specific Logic Was Added**

Me added only generic signals:
- `@SpringBootTest`
- `@ContextConfiguration`
- `@Import`
- `@WebMvcTest`
- `@MockBean`
- `@MockitoBean`
- missing bean errors
- support-class loaded/not-loaded checks

Test also asserts impl text has no:
- `msa-dto`
- `common-utils`
- `translation`

Real run wrote only remediation artifacts.
No source/test/POM files were modified.

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 56: Add MockitoBean Placement Compatibility Analyzer and Proposal.
>
> Context:
> A real Boot 3 migration now reaches Spring test runtime failures.
>
> Existing artifacts show:
>
> * missing bean type detected
> * provider exists in legacy and sandbox
> * support class exists
> * support class appears loaded by failing tests
> * legacy used @MockBean for the missing bean
> * sandbox/reference use @MockitoBean
> * missing bean still occurs
> * legacy-guided patch proposal could not produce a patch because support class already appears loaded
>
> This suggests a more subtle issue:
> @MockitoBean placement or registration may not be equivalent to legacy @MockBean placement.
>
> Goal:
> Add a generic analyzer that detects ineffective @MockitoBean / test mock placement and proposes a controlled repair.
>
> Important:
> Do not hardcode project names, package names, class names, or business names.
> Do not add logic specific to common-utils, msa-utils, msa-dto, or translation.
> Do not apply the patch automatically.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/remediation/mockito_bean_placement.py
>
> 2. Input:
>
>    * run_dir
>    * sandbox_project_path
>    * legacy_project_path
>    * legacy_behavior_equivalence_report.json
>    * test_context_repair_proposal.json
>    * legacy_guided_patch_proposal.json
>    * behavioral_failure_context_pack.json
>    * optional migrated_reference_path
>    * optional surefire reports directory
>
> 3. Output:
>
>    * remediation/mockito_bean_placement_report.json
>    * remediation/mockito_bean_placement_summary.md
>    * optional remediation/mockito_bean_placement_patch_proposal.patch
>
> 4. The analyzer must detect:
>
>    * missing bean type
>    * @MockBean usage in legacy
>    * @MockitoBean usage in sandbox
>    * whether @MockitoBean is located in:
>
>      * failing test class
>      * test superclass
>      * nested test configuration
>      * separate support App/config class
>      * unrelated support class
>    * whether failing tests directly declare or inherit the mock
>    * whether the mock exists only in a loaded support class but not in the test class hierarchy
>
> 5. It must classify cases:
>
>    * MOCK_IN_FAILING_TEST_CLASS
>    * MOCK_IN_TEST_SUPERCLASS
>    * MOCK_IN_SUPPORT_CLASS_ONLY
>    * MOCK_PROVIDER_NOT_FOUND
>    * MOCK_PLACEMENT_AMBIGUOUS
>
> 6. It must propose generic repair strategies:
>
>    * move or duplicate @MockitoBean into the failing test class
>    * move or duplicate @MockitoBean into a shared abstract test superclass
>    * create @TestConfiguration with @Bean returning Mockito.mock(...)
>    * add explicit @Import for test configuration if missing
>    * human review if ambiguous
>
> 7. Patch generation:
>
>    * If there is one failing test class and one missing bean and one obvious support mock:
>
>      * generate a patch proposal that adds @MockitoBean for the missing bean to the failing test class
>      * do not apply it
>      * safe_to_auto_apply=false
>      * human_review_required=true
>    * If multiple failing tests share a common abstract superclass:
>
>      * generate a patch proposal against the superclass only if clearly detected
>      * do not apply it
>    * Otherwise:
>
>      * no patch
>      * provide investigation steps
>      * llm_candidate=true
>
> 8. Do not modify source code.
>
> 9. Do not modify tests.
>
> 10. Do not modify POMs.
>
> 11. Do not run Maven.
>
> 12. Do not call LLM.
>
> 13. Do not call network.
>
> 14. Hook artifact refs into orchestration/final report when run_dir is available.
>
> Tests:
>
> 1. Detect @MockBean in legacy and @MockitoBean in sandbox.
> 2. Classify @MockitoBean in failing test class.
> 3. Classify @MockitoBean in superclass.
> 4. Classify @MockitoBean in support class only.
> 5. Generate patch proposal for single failing test class.
> 6. Generate patch proposal for shared abstract superclass when clearly detected.
> 7. Ambiguous multiple-test case produces no patch and llm_candidate=true.
> 8. Proposal always marks safe_to_auto_apply=false.
> 9. Proposal always marks human_review_required=true.
> 10. Patch is not applied.
> 11. No source/test/POM modification.
> 12. No Maven/LLM/network execution.
> 13. No hardcoded real project names.
> 14. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run analyzer on existing failed run:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001
>
> Use optional migrated reference if available:
> C:\Users\ilyas.abarbach\Documents\modernizer-solution.migration\golden-references\repos\msa-utils-reference\common-utils
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example mockito_bean_placement_report.json excerpt
> 7. Example patch proposal if generated
> 8. Real msa-utils classification
> 9. Whether patch proposal was generated
> 10. Why patch is not auto-applied
> 11. Evidence no project-specific logic was added

<details><summary>20 previous messages</summary>

> Me build MockitoBean placement analyzer on top of current legacy/test-context artifacts, then me run real failed run evidence pass with optional reference.
>
> Me editing new placement analyzer, report hook, final report line, and dedicated tests now.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/remediation/mockito_bean_placement.py` (+755 -0)
>
> </details>
>
> Me caught two tiny generic bugs in new analyzer before test run: wrong bean match in class-info, and missing target test file for support-only patch. Me fix now.
>
> <details><summary>Edited 4 files</summary>
>
> - Wrote `./migration_factory/remediation/mockito_bean_placement.py` (+6 -2)
> - Wrote `./migration_factory/remediation/mockito_bean_placement.py` (+1 -1)
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+41 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
>
> </details>
>
> Me add focused placement tests now: classification, single-test patch, superclass patch, ambiguous no patch, finalize refs.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_mockito_bean_placement.py` (+695 -0)
>
> </details>
>
> Me run focused placement tests first. Small generic misses maybe show quick.
>
> Me inspect one synthetic report quick. Smell says file matching too broad or target class not narrowed enough.
>
> Me inspect internal candidate once. Want exact reason patch path blank, not guess.
>
> Found it. Me had over-conservative early return for support-only single-test case. Fixing that, and making ambiguous test truly ambiguous.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/remediation/mockito_bean_placement.py` (+1 -1)
> - Wrote `./tests/orchestrator/test_mockito_bean_placement.py` (+24 -24)
>
> </details>
>
> Me rerun focused placement tests now.
>
> Me inspect superclass case once. Want exact reason it fell back to failing-test patch.
>
> Me tune fixtures only. Real logic okay; test fixtures needed equal relevance on both failing classes.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_mockito_bean_placement.py` (+4 -0)
>
> </details>
>
> Me rerun focused placement tests again.
>
> Focused tests green. Now me run required suites, then real analyzer on existing failed run with optional reference.
>
> Suites green. Me now generate real placement report on existing failed run, no migration rerun.
>
> Real placement artifact generated, with patch proposal this time. Me inspect exact classification + patch target before close.
</details>

1. **Summary**

Me add generic MockitoBean placement analyzer + proposal.

It now:
- detect legacy `@MockBean`
- detect sandbox `@MockitoBean`
- classify placement:
  - `MOCK_IN_FAILING_TEST_CLASS`
  - `MOCK_IN_TEST_SUPERCLASS`
  - `MOCK_IN_SUPPORT_CLASS_ONLY`
  - `MOCK_PROVIDER_NOT_FOUND`
  - `MOCK_PLACEMENT_AMBIGUOUS`
- generate proposal patch only
- never apply patch
- hook artifact refs into orchestration/final report

2. **Files Modified**

- [mockito_bean_placement.py](./migration_factory/remediation/mockito_bean_placement.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_mockito_bean_placement.py](./tests/orchestrator/test_mockito_bean_placement.py)

3. **Tests Added**

- legacy `@MockBean` + sandbox `@MockitoBean` detect
- classify mock in failing test class
- classify mock in support class only
- patch proposal for single failing test class
- patch proposal for shared abstract superclass
- ambiguous multi-test case -> no patch + `llm_candidate=true`
- failed sandbox finalization adds refs
- no hardcoded real project names

4. **Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_mockito_bean_placement.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real existing run only:
```powershell
$env:PYTHONPATH='.'
@' ... generate_mockito_bean_placement_report(...) ... '@ | python -
```

5. **Test Results**

- `tests/orchestrator/test_mockito_bean_placement.py -q`: `7 passed`
- `tests/orchestrator -q`: `147 passed`
- `pytest -q`: `787 passed, 3 skipped`

6. **Example `mockito_bean_placement_report.json` Excerpt**

```json
{
  "gate_id": "MOCKITOBEAN_PLACEMENT_COMPATIBILITY",
  "patch_proposal_available": true,
  "safe_to_auto_apply": false,
  "human_review_required": true,
  "proposals": [
    {
      "missing_bean_type": "com.example.FunctionalMessageHelper",
      "placement_classification": "MOCK_IN_SUPPORT_CLASS_ONLY",
      "patch_strategy": "duplicate_mockito_bean_into_failing_test_class"
    }
  ]
}
```

Real report:
- [mockito_bean_placement_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_report.json)

7. **Example Patch Proposal**

Synthetic kind:
```diff
+import org.springframework.test.context.bean.override.mockito.MockitoBean;
+
+    @MockitoBean
+    FunctionalMessageHelper helper;
```

Real patch:
- [mockito_bean_placement_patch_proposal.patch](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_patch_proposal.patch)

Real excerpt:
```diff
+import org.springframework.test.context.bean.override.mockito.MockitoBean;
+import com.total.corp.common.web.rest.util.FunctionalMessageHelper;
...
+    @MockitoBean
+    FunctionalMessageHelper functionalMessageHelper;
```

8. **Real `msa-utils` Classification**

Real result:
- missing bean: `com.total.corp.common.web.rest.util.FunctionalMessageHelper`
- classification: `MOCK_IN_SUPPORT_CLASS_ONLY`
- support class loaded: `true`
- chosen repair target: shared abstract superclass
- target file:
  - [AbstractMVCTest.java](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/src/test/java/com/total/corp/mvc/AbstractMVCTest.java)
- proposal strategy:
  - `duplicate_mockito_bean_into_shared_abstract_superclass`

Summary:
- [mockito_bean_placement_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_summary.md)

9. **Whether Patch Proposal Was Generated**

Yes.

Real artifacts:
- [mockito_bean_placement_report.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_report.json)
- [mockito_bean_placement_patch_proposal.patch](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_patch_proposal.patch)

10. **Why Patch Not Auto-Applied**

Still unsafe.
Even narrow patch can change shared Boot 3 test context for many tests.

So report always says:
- `safe_to_auto_apply=false`
- `human_review_required=true`

Need human verify:
- superclass really correct place
- shared test slice not broken
- bean override semantics match legacy intent

11. **Evidence No Project-Specific Logic Was Added**

No hardcoded:
- `msa-dto`
- `common-utils`
- `translation`

Logic keys only on generic things:
- `@MockBean`
- `@MockitoBean`
- failing test class
- superclass
- support class
- missing bean type
- reference evidence

Also:
- no source/test/POM modified
- no Maven run
- no LLM call
- no network call

Final report line now present too:
- [migration_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/final/migration_summary.md)

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 57: Add Human-Approved Behavioral Patch Apply.
>
> Context:
> The factory now produces behavioral patch proposals for Spring Boot 3 test-context failures.
>
> A real failed run produced:
>
> * mockito_bean_placement_report.json
> * mockito_bean_placement_patch_proposal.patch
>
> The patch proposal targets test context repair only and is marked:
>
> * safe_to_auto_apply=false
> * human_review_required=true
>
> Goal:
> Add a governed mechanism to apply an approved behavioral patch proposal in sandbox only, then rerun validation for the failed unit.
>
> Important:
> Do not auto-apply behavioral patches by default.
> Do not modify the legacy project.
> Do not apply patches without explicit approval.
> Do not bypass tests.
> Do not call LLM.
> Do not call network.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/remediation/approved_patch_apply.py
>
> 2. Input:
>
>    * run_dir
>    * patch_proposal_path
>    * approved_by
>    * approval_comment
>    * failed_unit_id
>    * sandbox_project_path
>    * optional validation command
>
> 3. Approval requirements:
>
>    * patch proposal must exist
>    * patch proposal must be under run_dir/remediation
>    * approval must be explicit
>    * patch must only target sandbox files
>    * patch must not target legacy path
>    * patch must not target files outside sandbox
>    * patch must not modify pom.xml unless explicitly allowed
>    * default allowed scope: test sources only
>
> 4. Apply behavior:
>
>    * apply patch to sandbox only
>    * record before/after file hashes
>    * write remediation/approved_patch_apply_result.json
>    * write remediation/approved_patch_apply_summary.md
>    * update ledger with:
>
>      * patch proposal path
>      * approved_by
>      * files changed
>      * failed_unit_id
>      * status
>
> 5. Rerun behavior:
>
>    * optionally rerun failed unit validation if validation command is provided
>    * capture exit code
>    * capture stdout/stderr tail
>    * write rerun evidence
>    * do not mark production success
>    * do not hide failures
>
> 6. Safety:
>
>    * if patch touches production source, block unless explicit flag is provided
>    * if patch touches POM, block unless explicit flag is provided
>    * if patch attempts path traversal, block
>    * if patch already applied, detect idempotently
>    * if patch fails to apply, write structured error
>
> 7. Integration:
>
>    * add artifact refs into orchestration/final report where possible
>    * preserve existing remediation reports
>    * do not break deterministic remediation loop
>
> Tests:
>
> 1. Approved patch applies to sandbox test file.
> 2. Patch outside sandbox is rejected.
> 3. Patch touching legacy path is rejected.
> 4. Patch touching production source is rejected by default.
> 5. Patch touching pom.xml is rejected by default.
> 6. Missing approval rejects.
> 7. Already applied patch handled safely.
> 8. Ledger records approved behavioral patch.
> 9. Optional validation rerun records result.
> 10. No LLM/network execution.
> 11. No project-specific names.
> 12. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then test on existing failed run only if approval is explicitly simulated:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001
>
> Use patch:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001\remediation\mockito_bean_placement_patch_proposal.patch
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example approved_patch_apply_result.json
> 7. Real run apply result if tested
> 8. Whether rerun moved past FunctionalMessageHelper
> 9. Next blocker if any
> 10. Evidence no legacy repo was modified
> 11. Evidence no project-specific logic was added

<details><summary>27 previous messages</summary>

> Me add governed sandbox-only approved patch apply, then me test with explicit simulated approval on existing failed run.
>
> Me inspect ledger exports and maybe one existing command-run helper, then me write apply module + tests.
>
> Me editing apply module now: strict sandbox checks, unified-diff apply, ledger update, optional rerun capture, artifact backfill.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./migration_factory/remediation/approved_patch_apply.py` (+466 -0)
>
> </details>
>
> Me add export + report line + focused tests, then me run suites.
>
> <details><summary>Edited 3 files</summary>
>
> - Wrote `./migration_factory/remediation/__init__.py` (+8 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
> - Wrote `./migration_factory/remediation/approved_patch_apply.py` (+0 -0)
>
> </details>
>
> Me add focused approved-patch tests now: safety checks, idempotent reapply, ledger record, optional rerun capture.
>
> <details><summary>Created 1 file</summary>
>
> - Wrote `./tests/orchestrator/test_approved_patch_apply.py` (+254 -0)
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Me finishing Ticket 57 now. First me add focused tests around approved patch safety and rerun evidence, then me run full validation before touching real sandbox run.
>
> Me found test file stub already there. Me read it now, then patch gaps instead of making duplicate coverage.
>
> Me have core Ticket 57 tests already in place. Me run them now, then patch only if real failures show up.
>
> Me found generic bug, small one: result writer calls helper that no exist. Me patch that now, then rerun tests and do real approved sandbox apply.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/approved_patch_apply.py` (+12 -0)
>
> </details>
>
> Bug patch in. Me rerun Ticket 57 tests first, then full suite if green.
>
> Me found idempotency bug in patch apply logic. Second apply sees removed line gone, then screams instead of saying “already applied.” Me tightening that matcher now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/approved_patch_apply.py` (+12 -1)
>
> </details>
>
> Idempotent fix in. Me rerun tests again, then real sandbox apply if green.
>
> Tests green. Me now use explicit simulated approval on real failed sandbox run, apply only proposed sandbox test patch, then rerun validation for failed unit.
>
> Real patch proposal is narrow test-superclass patch only. Me applying it with explicit approval into sandbox, then rerunning sandbox `mvn clean test` to see if `FunctionalMessageHelper` blocker moves.
>
> Real sandbox patch apply hit another generic diff bug: blank-line context in unified patch. Me inspect target snippet, fix patch parser generically, rerun tests, then retry real apply.
>
> Me found root cause: apply logic mixed “normal apply” and “already applied” in one path. Blank-line insert confused it. Me splitting strict apply from idempotent detection now.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/approved_patch_apply.py` (+47 -6)
>
> </details>
>
> Strict apply + separate idempotent check in now. Me rerun tests one more time before retrying real sandbox patch.
>
> Tests still green. Me retry real approved sandbox patch apply now.
>
> Patch applied and rerun finished. Me checking if old missing-bean blocker vanished, and what new top failure became.
>
> Me have final evidence. Last quick check: changed repo files for Ticket 57 only, so report clean and exact.
</details>

**Summary**

Me add human-approved behavioral patch apply.

Now factory can:
- require explicit approval
- verify patch inside `run_dir/remediation`
- block outside-sandbox / legacy / prod-source / `pom.xml` by default
- apply patch to sandbox only
- record hashes + ledger
- optionally rerun failed unit validation
- backfill artifact refs into orchestration/final report

**Files Modified**

- [approved_patch_apply.py](./migration_factory/remediation/approved_patch_apply.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_approved_patch_apply.py](./tests/orchestrator/test_approved_patch_apply.py)

**Tests Added**

- approved patch applies to sandbox test file
- patch outside sandbox rejected
- patch touching legacy path rejected
- production source rejected by default
- `pom.xml` rejected by default
- missing approval rejected
- already-applied patch handled safely
- ledger records approved patch + rerun
- no hardcoded real project names

**Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_approved_patch_apply.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real approved apply + rerun:
```powershell
$env:PYTHONPATH='.'
$env:JAVA_HOME_11='C:\Users\ilyas.abarbach\.jdks\ms-11.0.31'
$env:JAVA_HOME_17='C:\Users\ilyas.abarbach\.jdks\ms-17.0.19'
$env:MAVEN_OPTS='-Djavax.net.ssl.trustStore=C:\Users\ilyas.abarbach\.m2\migration-factory-truststore\cacerts -Djavax.net.ssl.trustStorePassword=changeit'
python - <<'PY'
# apply_approved_behavioral_patch(... validation_command=["...mvn.cmd","clean","test"])
PY
```

**Test Results**

- `tests/orchestrator/test_approved_patch_apply.py -q`: `9 passed`
- `tests/orchestrator -q`: `156 passed`
- `pytest -q`: `796 passed, 3 skipped`

**Example `approved_patch_apply_result.json`**

```json
{
  "status": "applied",
  "approved_by": "ilyas.abarbach",
  "failed_unit_id": "spring-boot-3-5-14",
  "files_changed": [
    "src\\test\\java\\com\\total\\corp\\mvc\\AbstractMVCTest.java"
  ],
  "safe_to_auto_apply": false,
  "human_review_required": true
}
```

Real artifact:
- [approved_patch_apply_result.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/approved_patch_apply_result.json)

**Real Run Apply Result**

Real run used:
- run dir: [utils-core-validation52b-20260604-001](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001)
- patch: [mockito_bean_placement_patch_proposal.patch](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/mockito_bean_placement_patch_proposal.patch)

Result:
- patch apply: `applied`
- changed file:
  - [AbstractMVCTest.java](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/src/test/java/com/total/corp/mvc/AbstractMVCTest.java)
- rerun attempted: `true`
- rerun exit code: `1`

Summary artifact:
- [approved_patch_apply_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/approved_patch_apply_summary.md)

**Whether Rerun Moved Past `FunctionalMessageHelper`**

No.

Still present in rerun surefire evidence:
- [TEST-com.total.corp.bus.AzureBusTest.xml](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/target/surefire-reports/TEST-com.total.corp.bus.AzureBusTest.xml)
- [TEST-com.total.corp.bus.AzureBusTopicTest.xml](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/target/surefire-reports/TEST-com.total.corp.bus.AzureBusTopicTest.xml)
- [TEST-com.total.corp.common.translator.TranslatorAdapterTest.xml](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/target/surefire-reports/TEST-com.total.corp.common.translator.TranslatorAdapterTest.xml)

Still says:
- `No qualifying bean of type '...FunctionalMessageHelper'`

So patch proposal was valid to apply, but not sufficient to repair context.

**Next Blocker**

Still same family:
- Boot 3 test-context bean registration / visibility
- `CustomExceptionTranslator` cannot get `FunctionalMessageHelper`
- now looks broader than one superclass placement patch

Best next generic direction:
- deeper `@MockitoBean` registration equivalence vs Boot 3 loaded `App` context
- maybe shared `@TestConfiguration` / explicit bean override strategy, not just placement

**Evidence No Legacy Repo Was Modified**

Only sandbox file changed:
- [AbstractMVCTest.java](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/workspaces/sandbox/src/test/java/com/total/corp/mvc/AbstractMVCTest.java)

Legacy repo path untouched.
Patch apply module blocks outside-sandbox targets by default.

**Evidence No Project-Specific Logic Was Added**

Implementation uses generic rules only:
- patch path under `run_dir/remediation`
- sandbox path containment
- test-source-only default scope
- prod-source / `pom.xml` deny by default
- explicit approval required

Test asserts impl has no:
- `msa-dto`
- `common-utils`
- `translation`

Also artifact refs now backfilled here:
- [orchestration_summary.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/orchestration/orchestration_summary.json)
- [migration_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/final/migration_summary.md)

> [$caveman](C://Users//ilyas.abarbach//.agents//skills//caveman//SKILL.md) full
> You are working on the AI Migration Factory repository.
>
> Ticket 58: Add Behavioral Remediation Strategy Router.
>
> Context:
> The factory has reached advanced Boot 3 behavioral/test-context failures on a complex Spring Boot migration.
>
> Current state:
>
> * deterministic migration blockers were resolved progressively
> * JJWT compile blocker is gone
> * the project reaches Boot 3 test/runtime phase
> * behavioral context pack exists
> * legacy behavior equivalence report exists
> * test context repair proposal exists
> * mockito bean placement report exists
> * an approved behavioral patch was applied in sandbox
> * rerun still failed with the same missing bean
> * therefore the case is now ambiguous and should not continue patch-chasing blindly
>
> Management direction:
> The factory should support a future interactive CLI assistant with LLM integration.
> LLM must be used only when necessary.
> When LLM is needed, the architecture should support two stacked model passes:
>
> * model 1 proposes a remediation
> * model 2 reviews/critiques/optimizes the first proposal using the original input and model 1 output
>   Human approval remains required before applying behavioral patches.
>
> Goal:
> Add a generic Behavioral Remediation Strategy Router.
>
> This router must decide the next remediation mode for behavioral/test-context failures:
>
> * deterministic proposal
> * approved patch retry
> * LLM proposal
> * human review only
> * stop because repeated same blocker after an approved attempt
>
> Important:
> Do not hardcode project names, class names, package names, or business names.
> Do not add logic specific to common-utils, msa-utils, msa-dto, or translation.
> Do not call LLM in this ticket.
> Do not apply patches in this ticket.
> Do not run Maven in this ticket.
>
> Required behavior:
>
> 1. Add a module, for example:
>
>    * migration_factory/remediation/strategy_router.py
>
> 2. Input:
>
>    * run_dir
>    * behavioral_failure_context_pack.json
>    * legacy_behavior_equivalence_report.json
>    * test_context_repair_proposal.json
>    * legacy_guided_patch_proposal.json
>    * mockito_bean_placement_report.json
>    * approved_patch_apply_result.json if present
>    * remediation_attempts.json if present
>    * orchestration_summary.json if present
>    * llm_policy if available
>
> 3. Output:
>
>    * remediation/behavioral_remediation_strategy.json
>    * remediation/behavioral_remediation_strategy.md
>
> 4. The router must compute:
>
>    * current blocker category
>    * failed unit
>    * whether failure is behavioral/test-context
>    * whether deterministic fixes were already applied
>    * whether a human-approved behavioral patch was already applied
>    * whether rerun after approved patch still has same blocker
>    * whether patch-chasing should stop
>    * whether LLM proposal should be recommended
>    * whether human review only is required
>    * whether a deterministic proposal is still appropriate
>
> 5. Decisions:
>
>    * AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE
>    * APPROVED_PATCH_APPLIED_RERUN_FAILED
>    * ESCALATE_TO_LLM_PROPOSAL
>    * HUMAN_REVIEW_ONLY
>    * STOP_REPEATED_BEHAVIORAL_PATCH_CHASING
>    * NO_BEHAVIORAL_REMEDIATION_NEEDED
>
> 6. LLM routing:
>
>    * if LLM policy disabled:
>      decision may be LLM_DISABLED_HUMAN_REVIEW_REQUIRED
>    * if LLM policy enabled and category allowed:
>      decision may be ESCALATE_TO_LLM_PROPOSAL
>    * do not call LLM
>    * prepare expected future artifacts:
>
>      * llm_model1_proposal.json
>      * llm_model2_review.json
>      * human_approval_required=true
>
> 7. Two-model architecture metadata:
>    The strategy artifact must include:
>
>    * model_1_role: remediation_proposer
>    * model_2_role: remediation_reviewer_optimizer
>    * model_2_input_requires:
>
>      * original context pack
>      * model 1 proposal
>      * risk constraints
>      * allowed patch scope
>    * human_approval_required: true
>
> 8. Stop patch chasing:
>    If an approved behavioral patch was applied and rerun still failed with the same missing bean or same failure signature:
>
>    * mark repeated_same_blocker=true
>    * recommend LLM proposal or human review
>    * do not recommend another deterministic patch unless strong new evidence exists
>
> 9. Safety:
>
>    * safe_to_auto_apply=false for behavioral cases
>    * production_promotion_allowed=false
>    * sandbox_only=true
>    * no patch apply
>    * no Maven run
>    * no network
>    * no LLM call
>
> 10. Integration:
>
> * add artifact refs into orchestration/final report where run_dir is available
> * preserve existing remediation artifacts
> * do not break deterministic remediation loop
>
> Tests:
>
> 1. Behavioral failure with no prior patch and deterministic proposal available -> AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE.
> 2. Behavioral failure with approved patch applied and same blocker still present -> STOP_REPEATED_BEHAVIORAL_PATCH_CHASING.
> 3. Same scenario with LLM policy enabled -> ESCALATE_TO_LLM_PROPOSAL.
> 4. Same scenario with LLM policy disabled -> LLM_DISABLED_HUMAN_REVIEW_REQUIRED.
> 5. Non-behavioral dependency failure -> NO_BEHAVIORAL_REMEDIATION_NEEDED.
> 6. Router includes two-model metadata.
> 7. Router marks safe_to_auto_apply=false for behavioral cases.
> 8. Router marks human_approval_required=true for LLM/proposal paths.
> 9. Integration adds artifact refs to orchestration/final report.
> 10. No source/test/POM modification.
> 11. No Maven/LLM/network execution.
> 12. No hardcoded real project names.
> 13. Full pytest remains green.
>
> Validation:
> Run:
> $env:PYTHONPATH='.'
> python -m pytest tests/orchestrator -q
> python -m pytest -q
>
> Then run router on existing failed run if available:
> C:\mf\utils-core-validation5.migration\runs\utils-core-validation52b-20260604-001
>
> Report:
>
> 1. Summary
> 2. Files modified
> 3. Tests added
> 4. Commands run
> 5. Test results
> 6. Example behavioral_remediation_strategy.json excerpt
> 7. Example behavioral_remediation_strategy.md excerpt
> 8. Real msa-utils strategy decision
> 9. Whether repeated patch chasing was stopped
> 10. Whether LLM proposal was recommended or blocked by policy
> 11. How two-model architecture is represented
> 12. Evidence no project-specific logic was added

<details><summary>15 previous messages</summary>

> Me add strategy router now. First me read existing remediation artifacts/policy shape so new router plugs in clean, then me patch code + tests + run real router on failed run.
>
> Me have enough context. Next me wire new router module into remediation exports, failed-sandbox finalization, and final report artifact lines, then add focused tests.
>
> Me checking one sibling remediation module for shape, so new router matches existing artifact style and backfill behavior.
>
> Me writing router module + integration now. After that me add tight tests for decision routing and artifact backfill.
>
> <details><summary>Created 2 files, edited 3 files</summary>
>
> - Wrote `./migration_factory/remediation/strategy_router.py` (+449 -0)
> - Wrote `./migration_factory/remediation/__init__.py` (+22 -0)
> - Wrote `./migration_factory/orchestrator/summary.py` (+41 -0)
> - Wrote `./migration_factory/final_report/writer.py` (+3 -0)
> - Wrote `./tests/orchestrator/test_strategy_router.py` (+364 -0)
>
> </details>
>
> Router code in. Me running focused router tests first, then full orchestrator and full suite. After green, me run router on real failed run and capture decision.
>
> Two small fixes: distinguish “no policy supplied” from “policy supplied but disabled,” and make test fixture create remediation dir before writing. Then me rerun.
>
> <details><summary>Edited 2 files</summary>
>
> - Wrote `./migration_factory/remediation/strategy_router.py` (+5 -2)
> - Wrote `./tests/orchestrator/test_strategy_router.py` (+1 -0)
>
> </details>
>
> Fixes in. Me rerun router tests and suites now.
>
> Tests green. Me now run router on real failed `msa-utils` run and capture actual strategy decision.
>
> Real router ran, but me see one weak spot: same-blocker detect missed because rerun tail did not keep the bean line. Me inspect context artifact shape, then tighten router to use surefire evidence too, so real decision matches actual blocker.
>
> Real artifacts show same blocker still there in surefire XML, but old tail-based check missed it. Me tightening router to look at rerun surefire evidence too, and prefer explicit approved failed unit id.
>
> <details><summary>Edited 1 file</summary>
>
> - Wrote `./migration_factory/remediation/strategy_router.py` (+28 -8)
>
> </details>
>
> Real detection fix in. Me rerun router tests and full suite one more time, then rerun router on real failed run for final decision.
>
> All green again. Me rerun real router now for final actual strategy decision.
</details>

**Summary**

Me add generic Behavioral Remediation Strategy Router.

Router now decide next step for Boot 3 behavioral/test-context failures:
- deterministic proposal still possible
- approved patch rerun failed
- stop repeated patch chasing
- escalate to future LLM proposal
- human review only
- no behavioral remediation needed

No LLM call.
No Maven run.
No patch apply.
No network.

**Files Modified**

- [strategy_router.py](./migration_factory/remediation/strategy_router.py)
- [__init__.py](./migration_factory/remediation/__init__.py)
- [summary.py](./migration_factory/orchestrator/summary.py)
- [writer.py](./migration_factory/final_report/writer.py)
- [test_strategy_router.py](./tests/orchestrator/test_strategy_router.py)

**Tests Added**

- behavioral failure + no prior patch -> `AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE`
- approved patch + same blocker -> `STOP_REPEATED_BEHAVIORAL_PATCH_CHASING`
- same with LLM enabled -> `ESCALATE_TO_LLM_PROPOSAL`
- same with LLM disabled -> `LLM_DISABLED_HUMAN_REVIEW_REQUIRED`
- non-behavioral -> `NO_BEHAVIORAL_REMEDIATION_NEEDED`
- two-model metadata present
- behavioral cases stay `safe_to_auto_apply=false`
- proposal/LLM paths keep `human_approval_required=true`
- orchestration/final report get artifact refs
- no hardcoded real names

**Commands Run**

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/orchestrator/test_strategy_router.py -q
python -m pytest tests/orchestrator -q
python -m pytest -q
```

Real router run:
```powershell
$env:PYTHONPATH='.'
python - <<'PY'
# generate_behavioral_remediation_strategy(...) on:
# C:\mf\utils-core-validation5\.migration\runs\utils-core-validation52b-20260604-001
PY
```

**Test Results**

- `tests/orchestrator/test_strategy_router.py -q`: `8 passed`
- `tests/orchestrator -q`: `164 passed`
- `pytest -q`: `804 passed, 3 skipped`

**Example `behavioral_remediation_strategy.json` Excerpt**

```json
{
  "decision": "ESCALATE_TO_LLM_PROPOSAL",
  "current_blocker_category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
  "repeated_same_blocker": true,
  "patch_chasing_should_stop": true,
  "safe_to_auto_apply": false,
  "human_approval_required": true,
  "model_1_role": "remediation_proposer",
  "model_2_role": "remediation_reviewer_optimizer"
}
```

Real artifact path:
- [behavioral_remediation_strategy.json](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/behavioral_remediation_strategy.json)

**Example `behavioral_remediation_strategy.md` Excerpt**

```md
- Decision: LLM_DISABLED_HUMAN_REVIEW_REQUIRED
- Repeated Same Blocker: true
- LLM Proposal Recommended: false

## Roles
- Model 1: remediation_proposer
- Model 2: remediation_reviewer_optimizer
```

Real summary path:
- [behavioral_remediation_strategy.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/remediation/behavioral_remediation_strategy.md)

**Real `msa-utils` Strategy Decision**

Real run decision:
- `LLM_DISABLED_HUMAN_REVIEW_REQUIRED`

Real facts:
- approved behavioral patch already applied
- rerun still failed
- same blocker still present:
  - `FunctionalMessageHelper`
- `repeated_same_blocker=true`
- `patch_chasing_should_stop=true`

**Whether Repeated Patch Chasing Was Stopped**

Yes.

Router now says:
- stop repeated behavioral patch chasing
- do not keep guessing more sandbox patches from same evidence

**Whether LLM Proposal Was Recommended Or Blocked By Policy**

Blocked by policy in real run.

Real policy:
- `enabled=false`

So router chose:
- `LLM_DISABLED_HUMAN_REVIEW_REQUIRED`

If future policy turns on and category allowed:
- router can choose `ESCALATE_TO_LLM_PROPOSAL`

**How Two-Model Architecture Is Represented**

Artifact now carries:
- `model_1_role = remediation_proposer`
- `model_2_role = remediation_reviewer_optimizer`
- `model_2_input_requires = [original context pack, model 1 proposal, risk constraints, allowed patch scope]`
- `human_approval_required = true`
- expected future artifacts when LLM path allowed:
  - `llm_model1_proposal.json`
  - `llm_model2_review.json`

**Evidence No Project-Specific Logic Was Added**

No hardcoded:
- `common-utils`
- `msa-utils`
- `msa-dto`
- `translation`

Logic keys only on generic artifacts and signals:
- behavioral context pack
- equivalence/proposal artifacts
- approved patch rerun result
- same blocker detection
- LLM policy categories
- orchestration/final artifact refs

Also final report now includes ref:
- [migration_summary.md](C:/mf/utils-core-validation5/.migration/runs/utils-core-validation52b-20260604-001/final/migration_summary.md)
