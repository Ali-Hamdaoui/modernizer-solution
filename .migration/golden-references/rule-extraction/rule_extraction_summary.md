# Rule Extraction Summary

## Already Covered
- JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT [LOW]: msa-utils
- LOMBOK_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils
- SLF4J_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils
- SPRING_DATA_SORT_BY_MIGRATION [LOW]: msa-utils

## Missing Deterministic Rules
- IMPORT_JAVAX_SERVLET_TO_JAKARTA [HIGH]: Backlog IMPORT_JAVAX_SERVLET_TO_JAKARTA for industrialized migration support.
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA [LOW]: Backlog IMPORT_JAVAX_VALIDATION_TO_JAKARTA for industrialized migration support.
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA [LOW]: Backlog IMPORT_JAVAX_XML_BIND_TO_JAKARTA for industrialized migration support.
- JAVA_VERSION_ALIGNMENT [HIGH]: Backlog JAVA_VERSION_ALIGNMENT for industrialized migration support.
- JJWT_VERSION_ALIGNMENT [HIGH]: Add deterministic JJWT alignment rule.
- JUNEAU_VERSION_ALIGNMENT_OR_REVIEW [HIGH]: Add Juneau alignment/review gate.
- SPRING_BOOT_VERSION_ALIGNMENT [HIGH]: Backlog SPRING_BOOT_VERSION_ALIGNMENT for industrialized migration support.

## Missing Test Modernization Rules
- INITMOCKS_TO_OPENMOCKS [HIGH]: Add deterministic Mockito initMocks to openMocks modernization.
- MOCKBEAN_TO_MOCKITOBEAN [HIGH]: Add deterministic Spring Boot test annotation modernization.
- POWERMOCK_LEGACY_TEST_STRATEGY [HIGH]: Define PowerMock legacy test containment or migration playbook.

## Human Review Gates
- API_CONTRACT_REVIEW_GATE [HIGH]: msa-dto, msa-utils
- AZURE_SDK_API_MIGRATION [HIGH]: msa-dto, msa-utils
- SPRING_SECURITY_BEHAVIOR_REVIEW [MEDIUM]: msa-utils

## LLM Candidates
- UNMAPPED_SOURCE_TRANSFORMATION [HIGH]: msa-dto, msa-utils

## Migration Playbooks Needed
- AZURE_SDK_MIGRATION_PLAYBOOK [HIGH]: Create Azure SDK migration playbook and review gate.
- CONSUMER_COMPATIBILITY_VALIDATION [HIGH]: Add consumer compatibility validation evidence gate.
- JAKARTA_HYBRID_STRATEGY [HIGH]: Define Jakarta hybrid migration playbook for mixed namespaces.

## Anti-Pattern Warnings
- ANTI_PATTERN_WARNING: Migrated reference keeps many explicit versions; consider BOM-managed simplification.
