# Golden Reference Summary

Project ID: msa-dto

## Version Shifts
- Java: 11 -> 21
- Spring Boot: 2.1.6.RELEASE -> 3.5.6.RELEASE

## Deterministic Candidates
- JAVA_VERSION_ALIGNMENT: Update Java version/tooling metadata.
- SPRING_BOOT_VERSION_ALIGNMENT: Align Spring Boot target version.
- JJWT_VERSION_ALIGNMENT: Align io.jsonwebtoken:jjwt-api version.
- LOMBOK_VERSION_ALIGNMENT: Align org.projectlombok:lombok version.
- SLF4J_VERSION_ALIGNMENT: Align org.slf4j:slf4j-api version.
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA: Migrate import namespace javax.xml.bind. to jakarta.xml.bind..
- IMPORT_JAVAX_SERVLET_TO_JAKARTA: Migrate import namespace javax.servlet. to jakarta.servlet..

## Human Review
- AZURE_SDK_API_MIGRATION: Review Azure SDK coordinate and API migration.
- PUBLIC_API_SIGNATURE_CHANGE: Review public API signature changes against consumers.

## LLM Candidates
- UNMAPPED_SOURCE_TRANSFORMATION: Review localized code/test changes not covered by deterministic rules.

## Framework Signals
- JJWT: legacy=3 reference=3
- JUNEAU: legacy=4 reference=6
- AZURE_OLD_SDK: legacy=1 reference=1
