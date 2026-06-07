# Candidate Project Readiness Summary

- Project ID: candidate
- Readiness Status: NEEDS_HUMAN_REVIEW_BEFORE_MIGRATION
- Human Review Required: true

## Coordinates

- groupId: com.example
- artifactId: candidate-lib
- version: 1.0.0
- packaging: jar

## Detected Risks

- JAVA_VERSION_ALIGNMENT [LOW]: Detected Java version 11.
- SPRING_BOOT_VERSION_ALIGNMENT [LOW]: Detected Spring Boot version 2.1.6.RELEASE.
- SPRING_BOOT_MULTI_HOP_ROUTE [MEDIUM]: Boot 2.x candidate with Boot 3 target suggests multi-hop route.
- JDK_AWARE_ANALYSIS_PREVIEW [LOW]: Route likely needs JDK-aware analysis preview.
- JDK_AWARE_TRANSFORMATION_UNITS [LOW]: Route likely needs JDK-aware transformation units.
- JJWT_VERSION_ALIGNMENT [MEDIUM]: Detected io.jsonwebtoken:jjwt.
- AZURE_SDK_MIGRATION_PLAYBOOK [HIGH]: Detected legacy Azure SDK com.microsoft.azure:azure-servicebus.
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA [MEDIUM]: Detected javax.validation usage in source.
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA [MEDIUM]: Detected javax.xml.bind usage in source.
- IMPORT_JAVAX_SERVLET_TO_JAKARTA [MEDIUM]: Detected javax.servlet usage in source.
- INITMOCKS_TO_OPENMOCKS [LOW]: Detected INITMOCKS_TO_OPENMOCKS hint.
- CONSUMER_COMPATIBILITY_VALIDATION [MEDIUM]: Detected public API / DTO package hints.

## Matching Capabilities

- JAVA_VERSION_ALIGNMENT: type=TRANSFORM
- SPRING_BOOT_VERSION_ALIGNMENT: type=TRANSFORM
- SPRING_BOOT_MULTI_HOP_ROUTE: type=DETECT
- JDK_AWARE_ANALYSIS_PREVIEW: type=DETECT
- JDK_AWARE_TRANSFORMATION_UNITS: type=DETECT
- JJWT_VERSION_ALIGNMENT: type=TRANSFORM
- AZURE_SDK_MIGRATION_PLAYBOOK: type=REVIEW_GATE
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA: type=TRANSFORM
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA: type=TRANSFORM
- IMPORT_JAVAX_SERVLET_TO_JAKARTA: type=TRANSFORM
- INITMOCKS_TO_OPENMOCKS: type=TRANSFORM
- CONSUMER_COMPATIBILITY_VALIDATION: type=CONSUMER_VALIDATION

## Recommended Next Actions

- Run read-only assessment with target profile springboot-2.1-to-3.5-java17.
- Expect review gates during Boot 3 sandbox migration; prepare human approver coverage.
- Prepare downstream consumer validation for internal dependents after successful sandbox migration.
