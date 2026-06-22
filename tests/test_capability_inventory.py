from __future__ import annotations

import json
from pathlib import Path

from migration_factory.capabilities import export_factory_capability_inventory


def test_factory_capability_inventory_json_and_markdown_are_written(tmp_path: Path) -> None:
    result = export_factory_capability_inventory(output_dir=tmp_path)

    assert result.report_path.is_file()
    assert result.summary_path.is_file()
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    summary = result.summary_path.read_text(encoding="utf-8")
    assert payload["capabilities"]
    assert "Factory Capability Summary" in summary


def test_factory_capability_inventory_contains_expected_capability_types_and_fields(tmp_path: Path) -> None:
    result = export_factory_capability_inventory(output_dir=tmp_path)

    capabilities = {item["capability_id"]: item for item in result.payload["capabilities"]}
    assert capabilities["JJWT_VERSION_ALIGNMENT"]["capability_type"] == "TRANSFORM"
    assert capabilities["AZURE_SDK_MIGRATION_PLAYBOOK"]["capability_type"] == "REVIEW_GATE"
    assert capabilities["REMEDIATION_PLAN"]["capability_type"] == "REMEDIATION_PLAN"
    assert capabilities["FAILED_SANDBOX_REPORTING"]["capability_type"] == "REPORT"
    assert capabilities["MIGRATION_WAVE_PLANNER"]["capability_type"] == "WAVE_PLANNING"
    assert capabilities["CONSUMER_COMPATIBILITY_VALIDATION"]["capability_type"] == "CONSUMER_VALIDATION"
    assert capabilities["JAVA_VERSION_ALIGNMENT"]["capability_type"] == "TRANSFORM"
    assert capabilities["SPRING_BOOT_VERSION_ALIGNMENT"]["capability_type"] == "TRANSFORM"
    assert capabilities["SPRING_BOOT_MULTI_HOP_ROUTE"]["capability_type"] == "DETECT"
    assert capabilities["JDK_AWARE_ANALYSIS_PREVIEW"]["capability_type"] == "DETECT"
    assert capabilities["JDK_AWARE_TRANSFORMATION_UNITS"]["capability_type"] == "DETECT"
    assert capabilities["IMPORT_JAVAX_VALIDATION_TO_JAKARTA"]["capability_type"] == "TRANSFORM"
    assert capabilities["IMPORT_JAVAX_XML_BIND_TO_JAKARTA"]["capability_type"] == "TRANSFORM"
    assert capabilities["IMPORT_JAVAX_SERVLET_TO_JAKARTA"]["capability_type"] == "TRANSFORM"
    assert capabilities["JAKARTA_XML_BIND_DEPENDENCY_ALIGNMENT"]["capability_type"] == "TRANSFORM"
    for item in capabilities.values():
        assert set(item) >= {
            "capability_id",
            "category",
            "capability_type",
            "safe_to_auto_apply",
            "requires_human_approval",
            "llm_candidate",
            "evidence_artifacts",
            "notes",
        }


def test_factory_capability_inventory_includes_core_alignment_and_review_capabilities(tmp_path: Path) -> None:
    result = export_factory_capability_inventory(output_dir=tmp_path)

    capability_ids = {item["capability_id"] for item in result.payload["capabilities"]}
    expected = {
        "JAVA_VERSION_ALIGNMENT",
        "SPRING_BOOT_VERSION_ALIGNMENT",
        "SPRING_BOOT_MULTI_HOP_ROUTE",
        "JDK_AWARE_ANALYSIS_PREVIEW",
        "JDK_AWARE_TRANSFORMATION_UNITS",
        "IMPORT_JAVAX_VALIDATION_TO_JAKARTA",
        "IMPORT_JAVAX_XML_BIND_TO_JAKARTA",
        "IMPORT_JAVAX_SERVLET_TO_JAKARTA",
        "JAKARTA_XML_BIND_DEPENDENCY_ALIGNMENT",
        "JAKARTA_VALIDATION_DEPENDENCY_ALIGNMENT",
        "JACKSON_VERSION_ALIGNMENT",
        "JACOCO_VERSION_ALIGNMENT",
        "LOMBOK_VERSION_ALIGNMENT",
        "SLF4J_VERSION_ALIGNMENT",
        "SPRING_SECURITY_VERSION_ALIGNMENT",
        "JJWT_VERSION_ALIGNMENT",
        "SPRING_DATA_SORT_BY_MIGRATION",
        "MOCKBEAN_TO_MOCKITOBEAN",
        "INITMOCKS_TO_OPENMOCKS",
        "JUNEAU_VERSION_ALIGNMENT_OR_REVIEW",
        "POWERMOCK_LEGACY_TEST_STRATEGY",
        "JAKARTA_HYBRID_STRATEGY",
        "API_CONTRACT_REVIEW_GATE",
        "AZURE_SDK_MIGRATION_PLAYBOOK",
        "CONSUMER_COMPATIBILITY_VALIDATION",
        "MIGRATION_WAVE_PLANNER",
        "WAVE_TO_CONSUMER_VALIDATION_CONFIG",
    }
    assert expected.issubset(capability_ids)


def test_factory_capability_inventory_has_no_real_project_names_hardcoded() -> None:
    source = Path("migration_factory/capabilities/inventory.py").read_text(encoding="utf-8").lower()
    for forbidden in ("msa-dto", "common-utils", "translation"):
        assert forbidden not in source
