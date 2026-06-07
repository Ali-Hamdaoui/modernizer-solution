# Reference Delta Analyzer

## Purpose

`migration_factory.tools.reference_delta_analyzer` compares:

* legacy Java/Maven project directory
* manually migrated reference directory

It writes structured JSON report with generic migration evidence:

* Java / Spring / Maven version changes
* dependency deltas
* source import/package migrations
* API migration indicators
* runtime environment indicators
* suspicious migration artifacts
* recommended generic capability packs

## Prepare Input Repositories

Clone same repo twice into separate working directories, or export two branches into separate folders.

Example flow:

```powershell
git clone <repo-url> legacy-copy
git clone <repo-url> reference-copy

git -C legacy-copy checkout <legacy-branch>
git -C reference-copy checkout <reference-branch>
```

For repos using legacy and migrated branches:

```powershell
git -C legacy-copy checkout legacy/original
git -C reference-copy checkout migrated/reference
```

## Run Analyzer

```powershell
python -m migration_factory.tools.reference_delta_analyzer `
  --legacy C:\path\to\legacy-copy `
  --reference C:\path\to\reference-copy `
  --output C:\path\to\report.json
```

CLI behavior:

* validates both paths exist
* discovers `pom.xml`, including nested module projects
* selects primary POM heuristically
* writes JSON report
* prints short summary

## Report Structure

Top-level report sections:

* `legacy`
* `reference`
* `pom_delta`
* `dependency_delta`
* `source_delta`
* `runtime_environment`
* `api_migration_indicators`
* `suspicious_artifacts`
* `recommended_capability_packs`

## How To Read Report

Start with:

* `pom_delta.java_version_change`
* `pom_delta.spring_boot_version_change`
* `pom_delta.parent_pom_change`
* `pom_delta.maven_plugin_version_changes`

Then inspect:

* `dependency_delta.added`
* `dependency_delta.removed`
* `dependency_delta.version_changed`

Then source evidence:

* `source_delta.javax_to_jakarta_imports`
* `source_delta.added_imports`
* `source_delta.removed_imports`
* `source_delta.changed_import_families`

Then ecosystem-specific generic heuristics:

* `api_migration_indicators.jjwt_parser_api`
* `api_migration_indicators.juneau_restclient_api`
* `api_migration_indicators.azure_sdk`
* `api_migration_indicators.spring_security_5_to_6`
* `api_migration_indicators.thymeleaf_spring_compatibility`

Then environmental constraints:

* `runtime_environment.workflow_files`
* `runtime_environment.detected_indicators`
* `runtime_environment.environment_variables`
* `runtime_environment.config_files`

Finally cleanup risk:

* `suspicious_artifacts`

## How Report Helps Future Capability Packs

Report is read-only evidence artifact. It can feed future generic remediation packs such as:

* `javax-to-jakarta`
* `spring-boot-2-to-3`
* `spring-security-5-to-6`
* `jjwt-modernization`
* `juneau-modernization`
* `runtime-environment-contract`
* `maven-build-environment`
* `internal-dependency-graph`
* `test-modernization`

Key rule:

* analyzer extracts generic patterns only
* future capability packs should stay generic too
* no project-specific names should be embedded in analyzer logic

## Optional Example Repos

Optional smoke examples:

* `msa-dto`
* `msa-utils`

Use them only as external evidence inputs. Do not copy project-specific rules into production analyzer logic.
