# Factory Capability Summary

- Capabilities: 32

## AUTO_REMEDIATION

- DETERMINISTIC_AUTO_REMEDIATION_LOOP: category=remediation, safe_to_auto_apply=true, requires_human_approval=false

## CONSUMER_VALIDATION

- CONSUMER_COMPATIBILITY_VALIDATION: category=validation_gate, safe_to_auto_apply=false, requires_human_approval=true

## DETECT

- JDK_AWARE_ANALYSIS_PREVIEW: category=analysis, safe_to_auto_apply=false, requires_human_approval=false
- JDK_AWARE_TRANSFORMATION_UNITS: category=analysis, safe_to_auto_apply=false, requires_human_approval=false
- SPRING_BOOT_MULTI_HOP_ROUTE: category=planning, safe_to_auto_apply=false, requires_human_approval=true

## REMEDIATION_PLAN

- LLM_POLICY_GATE: category=remediation_policy, safe_to_auto_apply=false, requires_human_approval=true
- REMEDIATION_PLAN: category=remediation, safe_to_auto_apply=false, requires_human_approval=true

## REPORT

- FAILED_SANDBOX_REPORTING: category=reporting, safe_to_auto_apply=false, requires_human_approval=false
- FAILURE_CLASSIFICATION: category=reporting, safe_to_auto_apply=false, requires_human_approval=false

## REVIEW_GATE

- API_CONTRACT_REVIEW_GATE: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- AZURE_SDK_MIGRATION_PLAYBOOK: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- JAKARTA_HYBRID_STRATEGY: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- JUNEAU_VERSION_ALIGNMENT_OR_REVIEW: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true
- POWERMOCK_LEGACY_TEST_STRATEGY: category=review_gate, safe_to_auto_apply=false, requires_human_approval=true

## TRANSFORM

- IMPORT_JAVAX_SERVLET_TO_JAKARTA: category=namespace_migration, safe_to_auto_apply=true, requires_human_approval=false
- IMPORT_JAVAX_VALIDATION_TO_JAKARTA: category=namespace_migration, safe_to_auto_apply=true, requires_human_approval=false
- IMPORT_JAVAX_XML_BIND_TO_JAKARTA: category=namespace_migration, safe_to_auto_apply=true, requires_human_approval=false
- INITMOCKS_TO_OPENMOCKS: category=test_modernization, safe_to_auto_apply=true, requires_human_approval=false
- JACKSON_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- JACOCO_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- JAKARTA_XML_BIND_DEPENDENCY_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- JAVA_VERSION_ALIGNMENT: category=route_alignment, safe_to_auto_apply=true, requires_human_approval=false
- JJWT_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- LOMBOK_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- MOCKBEAN_TO_MOCKITOBEAN: category=test_modernization, safe_to_auto_apply=true, requires_human_approval=false
- SLF4J_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false
- SPRING_BOOT_VERSION_ALIGNMENT: category=route_alignment, safe_to_auto_apply=true, requires_human_approval=false
- SPRING_DATA_SORT_BY_MIGRATION: category=source_patch, safe_to_auto_apply=true, requires_human_approval=false
- SPRING_SECURITY_VERSION_ALIGNMENT: category=maven_alignment, safe_to_auto_apply=true, requires_human_approval=false

## WAVE_PLANNING

- MIGRATION_WAVE_PLANNER: category=wave_planning, safe_to_auto_apply=false, requires_human_approval=false
- WAVE_TO_CONSUMER_VALIDATION_CONFIG: category=wave_planning, safe_to_auto_apply=false, requires_human_approval=false
