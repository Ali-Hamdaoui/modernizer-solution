# Rule Extraction Summary

## Already Covered
- CONSUMER_COMPATIBILITY_VALIDATION [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_SERVLET_TO_JAKARTA [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA [LOW]: msa-utils (coverage=inventory_artifact)
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA [LOW]: msa-dto (coverage=inventory_artifact)
- INITMOCKS_TO_OPENMOCKS [HIGH]: msa-utils (coverage=inventory_artifact)
- JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT [LOW]: msa-utils (coverage=inventory_artifact)
- JAVA_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- JJWT_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- LOMBOK_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- MOCKBEAN_TO_MOCKITOBEAN [HIGH]: msa-utils (coverage=inventory_artifact)
- SLF4J_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- SPRING_BOOT_VERSION_ALIGNMENT [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- SPRING_DATA_SORT_BY_MIGRATION [LOW]: msa-utils (coverage=inventory_artifact)

## Covered Review Capabilities
- API_CONTRACT_REVIEW_GATE [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- AZURE_SDK_MIGRATION_PLAYBOOK [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- JAKARTA_HYBRID_STRATEGY [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- JUNEAU_VERSION_ALIGNMENT_OR_REVIEW [HIGH]: msa-dto, msa-utils (coverage=inventory_artifact)
- POWERMOCK_LEGACY_TEST_STRATEGY [HIGH]: msa-utils (coverage=inventory_artifact)

## Missing Deterministic Rules

## Missing Test Modernization Rules

## Human Review Gates
- AZURE_SDK_API_MIGRATION [HIGH]: msa-dto, msa-utils
- SPRING_SECURITY_BEHAVIOR_REVIEW [MEDIUM]: msa-utils

## LLM Candidates
- UNMAPPED_SOURCE_TRANSFORMATION [HIGH]: msa-dto, msa-utils

## Migration Playbooks Needed

## Anti-Pattern Warnings
- ANTI_PATTERN_WARNING: Migrated reference keeps many explicit versions; consider BOM-managed simplification.
