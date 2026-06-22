# Runtime Contract Analyzer

## Purpose

`migration_factory.tools.runtime_contract_analyzer` reads Java/Maven project and produces deterministic runtime contract JSON.

Goal:

* expose build/test/runtime environment assumptions before migration run fails
* capture evidence for missing Maven settings, JDK mismatch, private registry auth, missing config files, missing certs, or internal dependency order
* stay read-only and generic

Tool does not use LLM. Tool does not modify source.

## CLI Usage

Basic run:

```powershell
python -m migration_factory.tools.runtime_contract_analyzer `
  --project C:\path\to\project `
  --output C:\path\to\runtime-contract.json
```

With optional reference delta context:

```powershell
python -m migration_factory.tools.runtime_contract_analyzer `
  --project C:\path\to\project `
  --reference-delta C:\path\to\reference-delta.json `
  --output C:\path\to\runtime-contract.json
```

CLI behavior:

* validates input paths
* discovers main `pom.xml`, including nested projects
* writes JSON report
* prints short summary

## Report Sections

Top-level sections:

* `project`
* `build_tool`
* `jdk_requirements`
* `maven_requirements`
* `private_registry_requirements`
* `environment_variables`
* `configuration_files`
* `resource_access`
* `security_materials`
* `internal_dependencies`
* `workflow_indicators`
* `test_runtime_requirements`
* `detected_risks`
* `recommended_actions`

## What It Detects

JDK / Maven:

* Java version from POM properties and compiler plugin settings
* Maven wrapper
* workflow `actions/setup-java`
* workflow Java versions and JDK distributions reported separately
* Maven version hints in workflow
* hardcoded JDK or Maven path assumptions reported as matched path evidence
* `JAVA_HOME`, `JAVA_HOME_11`, `JAVA_HOME_17`, `JAVA_HOME_21`, and similar env var names

Private registry / settings:

* `settings.xml`
* `mvn -s` or `mvn --settings`
* private repository URLs in POM
* CodeArtifact-like hints
* env var names related to registry auth
* safe Maven settings argument evidence without secret values

Config / resource / security:

* YAML, properties, JSON config files
* `@Value`
* `Environment`
* `ResourceLoader`
* `FileSystemResource`
* `ClassPathResource`
* direct file access APIs
* keystore / truststore / certificate file paths

Test runtime:

* test config files
* JUnit 4 / JUnit 5
* Mockito / PowerMock
* `@SpringBootTest`
* active profiles

## How It Helps

Use report to explain migration failures like:

* build fails because internal dependency not built first
* tests fail because `settings.xml` missing
* project expects private registry auth
* CI assumes different JDK than local sandbox
* app/test needs YAML, properties, certificates, keystore, or profile config

## Future Use

Runtime contract is evidence artifact for future remediation/capability agents.

Examples:

* install internal dependencies first
* inject Maven settings safely
* set JDK env vars
* copy required config files into sandbox
* mount certs/keystores without exposing contents

Rules:

* no LLM behavior
* no transformer behavior
* no source changes
* no secret values or key contents in report
* no Java version/distribution mixing in workflow metadata
