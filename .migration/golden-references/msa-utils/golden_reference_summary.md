# Golden Reference Summary

Project ID: msa-utils

## Version Shifts
- Java: 11 -> 21
- Spring Boot: 2.1.6.RELEASE -> 3.5.6

## Deterministic Candidates
- JAVA_VERSION_ALIGNMENT: Update Java version/tooling metadata.
- SPRING_BOOT_VERSION_ALIGNMENT: Align Spring Boot target version.
- JJWT_VERSION_ALIGNMENT: Align io.jsonwebtoken:jjwt-api version.
- JAKARTA_DEPENDENCY_ADDITION: Add Boot 3/Jakarta validation dependency.
- LOMBOK_VERSION_ALIGNMENT: Align org.projectlombok:lombok version.
- SLF4J_VERSION_ALIGNMENT: Align org.slf4j:slf4j-api version.
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA: Migrate import namespace javax.validation. to jakarta.validation..
- IMPORT_JAVAX_SERVLET_TO_JAKARTA: Migrate import namespace javax.servlet. to jakarta.servlet..
- SPRING_DATA_SORT_BY_MIGRATION: Apply deterministic pattern SPRING_DATA_SORT_BY_MIGRATION.
- MOCKBEAN_TO_MOCKITOBEAN: Apply deterministic pattern MOCKBEAN_TO_MOCKITOBEAN.
- INITMOCKS_TO_OPENMOCKS: Apply deterministic pattern INITMOCKS_TO_OPENMOCKS.

## Human Review
- SPRING_SECURITY_BEHAVIOR_REVIEW: Review Spring Security runtime behavior under Boot 3.
- AZURE_SDK_API_MIGRATION: Review Azure SDK coordinate and API migration.
- PUBLIC_API_SIGNATURE_CHANGE: Review public API signature changes against consumers.

## LLM Candidates
- UNMAPPED_SOURCE_TRANSFORMATION: Review localized code/test changes not covered by deterministic rules.

## Framework Signals
- JJWT: legacy=3 reference=3
- JUNEAU: legacy=4 reference=5
- POWERMOCK: legacy=2 reference=2
- AZURE_OLD_SDK: legacy=3 reference=1
- AZURE_NEW_SDK: legacy=0 reference=2
