# Current Problems and V2 Roadmap

## 1. What V1 validates

V1 validates a two-stage build/test-only migration proof:

- Stage 1: `springboot-2.1.6-to-2.7-java11`
- Stage 2: `springboot-2.7-to-3.5-java17`
- Stage 1 run id: `v1-stage1-216-to-27-watchonly-20260602-233409`
- Stage 2 run id: `v1-stage2-27-to-35-watchonly-20260602-233720`
- Both stages reached transform `TRANSFORM_APPLIED_IN_SANDBOX`, build `BUILD_PASSED_IN_SANDBOX`, and tests `PASS_WITH_WARNINGS`.
- Final Stage 2 sandbox `pom.xml` had Java `17` and Spring Boot `3.5.14`.
- Final manual verification passed with exit code `0`: `mvn clean test -DskipITs`.

V1 verdict: `V1 build/test proof: DONE`.

## 2. What V1 does not validate

V1 does not validate:

- Runtime/H2 startup.
- Endpoint smoke.
- SQL Server behavior.
- Security/keystore readiness.
- Production readiness.

Do not claim runtime compatibility from compile/test success alone.

## 3. Current known gaps

- No direct profile named `springboot-2.1.6-to-3.5-java17-v1-build-only`.
- `springboot-2.7-to-3.5-java17` cannot be applied directly to the original legacy app because the source app is Spring Boot `2.1.6.RELEASE`.
- No dedicated runtime smoke agent.
- No endpoint smoke agent.
- No SQL Server proof mode.
- No dependency compatibility scanner for Boot 3.5/Jakarta risks.
- No old `javax.*` dependency scanner for internal artifacts.
- No first-class multi-stage ledger connecting Stage 1 and Stage 2 evidence.

## 4. Runtime/H2 startup problem

Runtime/H2 investigation is V2 work:

- H2 smoke config injection with `spring.config.additional-location` worked after a path fix.
- H2 startup still fails due to `common-utils` runtime config.
- Exact missing cache key found in `common-utils`: `caching.time-out`.
- `CachingConfig` manually loads profile YAML with `YamlPropertiesFactoryBean`, not normal Spring Boot environment binding.
- `common-utils-test.yml` contains `caching.time-out: 15`.
- Running profile `test` fails earlier because `config/application-test.yml` contains invalid `spring.profiles.active` in a profile-specific resource.

V2 needs safe smoke-only config generation and common-utils-aware config handling.

## 5. Dependency risk problem

Spring Boot 3 requires Java 17 or newer, uses Spring Framework 6, and moves to Jakarta EE APIs. Source and compatible dependencies must move away from old `javax.*` APIs where applicable.

Known final Stage 2 sandbox caveats:

- `tomcat.version = 9.0.102` override still present.
- `org-zalando.version = 0.24.0` still present.
- `problem-spring-web` remains in `pom.xml`.
- `javax.*` search excluding `target` found 3 occurrences, all in `src/test/resources/logback.xml` logger names.
- `jakarta.*` exists as 5 imports in `Translation.java`, all `jakarta.persistence.*`.

V2 needs Tomcat 9 override detection/removal under Boot 3.5, Zalando `problem-spring-web` upgrade/detection, and old `javax.*` source/dependency scanning.

## 6. Profile/path problem

The final validated path is two-stage:

1. `springboot-2.1.6-to-2.7-java11`
2. `springboot-2.7-to-3.5-java17`

The missing direct profile should stay documented as missing unless it is intentionally added. The Boot 3.5 profile should continue to reject original Boot `2.1.6.RELEASE` inputs because it requires `2.7.*`.

## 7. Copilot/fallback behavior

- Copilot CLI available: `GitHub Copilot CLI 1.0.58`.
- Copilot repair/fallback foundation was validated earlier.
- Copilot is optional advisory.
- If Copilot returns invalid, prose-only, or schema-invalid output, deterministic fallback plan generation is used.
- For the final V1 two-stage run, Copilot was not invoked because build/test did not fail.
- Auto-apply remains disabled: `AI_MIGRATION_AUTO_APPLY_SAFE_REPAIRS=false`.

Copilot must not approve runs, mutate source, change gates, override status, create PRs, deploy, or claim production readiness.

## 8. V2 roadmap

- Add runtime/H2 proof mode.
- Fix or account for `common-utils` config handling.
- Fix or avoid invalid `application-test.yml` profile activation.
- Generate safe smoke-only config.
- Detect/remove Tomcat 9 overrides under Boot 3.5.
- Detect or upgrade old Zalando `problem-spring-web`.
- Add old `javax.*` dependency scanner.
- Add endpoint smoke later, after runtime startup proof is stable.
- Add proof-level reporting:
  - `build_test_verified`
  - `runtime_startup_verified`
  - `endpoint_smoke_verified`
  - `production_ready_not_claimed`

## 9. Acceptance criteria for V2

- Runtime/H2 startup proof is produced as a structured artifact and summary.
- Smoke config uses `spring.config.additional-location` safely and does not mutate source.
- `common-utils` cache configuration is satisfied or explicitly classified with evidence.
- Invalid profile-specific `spring.profiles.active` is avoided or remediated in smoke mode.
- Boot 3.5 dependency risks are reported, including Tomcat 9 override and old Zalando/problem dependency.
- Old `javax.*` references are scanned in source and dependency artifacts, with test logger names separated from runtime code risk.
- Final reports show proof level accurately and continue to state `production_ready_not_claimed`.
- Endpoint smoke remains optional until runtime startup proof is reliable.
