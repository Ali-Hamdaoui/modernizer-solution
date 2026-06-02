# Known Gaps And Risks

This list separates current code behavior from missing factory capabilities.

## Build Success Is Not Enough

Current state:

- Build Agent can run build/startup or plan commands.
- Test Agent parses Surefire XML.
- Final validation requires `TEST_PASSED`.

Gap:

- A successful Maven build does not prove runtime behavior, endpoint health, security config readiness, SQL initialization compatibility, or environment-specific startup.

Needed:

- Runtime Smoke Agent with endpoint checks and structured startup evidence.

## Dependency Compatibility Scanner

Current state:

- Analysis can run Maven dependency tree.
- Assessment has text-based enterprise compatibility heuristics.

Gap:

- No compatibility matrix scanner for Spring Boot/Spring Framework/Jakarta/Hibernate/Zalando/Springfox/SQL Server/internal dependencies.

Needed:

- Dependency Compatibility Scanner that reads dependency graph, BOMs, properties, managed dependencies, and internal artifacts.

## Internal Artifact Resolver

Current state:

- Maven dependency tree may fail or omit private artifact internals.
- Internal dependencies are only flagged heuristically when strings match `internal`, `snapshot`, `com.company`, etc.

Gap:

- No resolver that can inspect internal JAR bytecode, POM metadata, transitive dependencies, or `javax.*` usage.

Needed:

- Internal Artifact Resolver with repository credentials supplied through redacted env, artifact download/cache policy, and source/JAR inspection.

## Tomcat 9 Override Detection For Boot 3

Current state:

- No dedicated rule found for Tomcat override compatibility.

Gap:

- Spring Boot 3 expects the Servlet/Jakarta stack aligned with Tomcat 10.x. A lingering Tomcat 9 override can compile in confusing ways or fail at runtime.

Needed:

- Rule scanning dependency management, properties, exclusions, and explicit Tomcat artifacts.

## `javax.*` Scanner In Internal JARs

Current state:

- `import_scanner.py` scans source `.java` imports only.

Gap:

- Internal JARs can still contain `javax.*` bytecode references.

Needed:

- JAR/bytecode scanner using `jdeps` or class constant pool inspection.

## Third-Party Compatibility Rules

Known high-risk libraries and stacks:

- Zalando `problem-spring-web`
- Springfox
- Hibernate/JPA
- SQL Server driver
- Spring Security
- Spring Cloud
- Custom starters
- Internal DTO/utils libraries

Current state:

- Assessment heuristics can flag Hibernate, security, old Maven plugins, internal dependencies, unsupported bytecode, missing tests.

Gap:

- No version-specific compatibility policy rules.

Needed:

- Rules that map dependency coordinates and versions to migration actions, blockers, warnings, and proof requirements.

Real evidence to encode:

- `problem-spring-web 0.29.1` worked in the observed Boot `3.5.14` migration.
- `common-utils 2.9.41-SNAPSHOT` worked.
- `msa-dto 3.3.22-SNAPSHOT` worked.

## SQL Init Analyzer

Current state:

- Config scanner detects datasource presence by text.

Gap:

- No analyzer for schema/data SQL scripts, `spring.sql.init.*`, Flyway/Liquibase, H2 overrides, or profile-specific datasource behavior.

Needed:

- SQL Init Analyzer to classify whether failures are migration blockers or environment warnings.

Real evidence:

- Runtime smoke used H2 override and `spring.sql.init.mode=never`.

## Security/Keystore Validation Classification

Current state:

- Assessment can flag security/auth warnings by text.
- Build Agent may classify missing beans/config as failure.

Gap:

- No explicit classification for keystore/JWT failures as security-environment warnings versus migration blockers.

Needed:

- Security Env Classifier that separates compile blockers, boot blockers, smoke blockers, and expected local-secret warnings.

Real evidence:

- Keystore/JWT errors remained security-env warnings, not migration compile blockers.

## Endpoint Smoke Checks

Current state:

- No endpoint checker.

Gap:

- Startup success alone does not prove controller mappings, actuator health, auth behavior, request/response serialization, or database-backed endpoints.

Needed:

- Endpoint Smoke Agent with required/optional endpoints, auth mode, expected status codes, and response assertions.

## IntelliJ Vs Maven Run Documentation

Current state:

- Maven CLI is the source of Build Agent validation.
- No artifact captures IntelliJ run configuration.

Gap:

- Field migrations often compare IntelliJ runtime success with Maven CLI results, but these can use different JDKs/env/profiles.

Needed:

- Operator runbook and artifact fields recording IDE run config details when cited as evidence.

## Final Report Proof Levels

Current state:

- Final report records statuses, artifacts, recipes, warnings, limitations.
- Report context records provenance.

Gap:

- No explicit proof level taxonomy.

Needed proof levels:

- `static_analysis_only`
- `dry_run_preview`
- `compiled`
- `unit_tests_passed`
- `runtime_started`
- `endpoint_smoked`
- `security_env_verified`
- `human_observed`
- `not_verified`

## Profile Guardrail Ambiguity

Current state:

- Profiles may set `production_allowed: false` and `sandbox_transform_allowed: true`.
- Transform override requires env `AI_MIGRATION_ALLOW_GUARDED_SANDBOX_TRANSFORM`.

Risk:

- Operators may expect `sandbox_transform_allowed: true` alone to permit transformation.

Needed:

- Run docs should always call out required env override for guarded sandbox transforms.

## Stage Evidence Is Not Yet First-Class

Current state:

- Profiles encode stages A/B/C.
- Final report can record target stack and recipes.

Gap:

- There is no multi-stage migration ledger linking Stage A, Stage B, and Stage C run ids and evidence.

Needed:

- Stage Chain Ledger with source/target stack per stage, evidence refs, and carry-forward dependency decisions.

## Copilot Provider `sdk`

Current state:

- `sdk` is listed as an allowed orchestrator provider.
- Actual provider selection falls back to deterministic unless provider is `cli`.

Risk:

- Operators may assume an SDK provider is implemented.

Needed:

- Either implement SDK provider or remove/mark it as planned in config docs.

## No Real Migration Should Be Run During Documentation

This documentation task did not run migrations or modify legacy apps. Validation is limited to repository tests requested by the operator.
