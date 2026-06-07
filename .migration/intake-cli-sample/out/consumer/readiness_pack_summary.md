# Candidate Project Readiness Summary

- Project ID: consumer
- Readiness Status: READY_WITH_WARNINGS
- Human Review Required: false

## Coordinates

- groupId: com.example
- artifactId: consumer-app
- version: 1.0.0
- packaging: jar

## Detected Risks

- JAVA_VERSION_ALIGNMENT [LOW]: Detected Java version 11.
- SPRING_BOOT_VERSION_ALIGNMENT [LOW]: Detected Spring Boot version 2.1.6.RELEASE.
- SPRING_BOOT_MULTI_HOP_ROUTE [MEDIUM]: Boot 2.x candidate with Boot 3 target suggests multi-hop route.
- JDK_AWARE_ANALYSIS_PREVIEW [LOW]: Route likely needs JDK-aware analysis preview.
- JDK_AWARE_TRANSFORMATION_UNITS [LOW]: Route likely needs JDK-aware transformation units.

## Matching Capabilities

- JAVA_VERSION_ALIGNMENT: type=TRANSFORM
- SPRING_BOOT_VERSION_ALIGNMENT: type=TRANSFORM
- SPRING_BOOT_MULTI_HOP_ROUTE: type=DETECT
- JDK_AWARE_ANALYSIS_PREVIEW: type=DETECT
- JDK_AWARE_TRANSFORMATION_UNITS: type=DETECT

## Recommended Next Actions

- Run read-only assessment with target profile springboot-2.1-to-3.5-java17.
- Prepare downstream consumer validation for internal dependents after successful sandbox migration.
