from __future__ import annotations

import json
from pathlib import Path

from migration_factory.capabilities import export_factory_capability_inventory
from migration_factory.golden_reference import extract_rules_from_golden_reports


def test_rule_extractor_groups_covered_and_missing_rules(tmp_path: Path) -> None:
    report_a = _write_report(
        tmp_path / "a.json",
        {
            "project_id": "project-a",
            "candidate_deterministic_rules": [
                {"rule_id": "LOMBOK_VERSION_ALIGNMENT", "recommended_action": "Align lombok.", "safe_to_auto_apply": True},
                {"rule_id": "JJWT_VERSION_ALIGNMENT", "recommended_action": "Align jjwt.", "safe_to_auto_apply": True},
                {"rule_id": "MOCKBEAN_TO_MOCKITOBEAN", "recommended_action": "Modernize MockBean.", "safe_to_auto_apply": True},
            ],
            "candidate_human_review_items": [
                {"rule_id": "PUBLIC_API_SIGNATURE_CHANGE", "recommended_action": "Review public API."}
            ],
            "candidate_llm_remediation_items": [
                {"rule_id": "UNMAPPED_SOURCE_TRANSFORMATION", "recommended_action": "Review unmapped changes."}
            ],
            "framework_library_signals": [
                {"signal_id": "JUNEAU"},
                {"signal_id": "POWERMOCK"},
                {"signal_id": "AZURE_OLD_SDK"},
                {"signal_id": "AZURE_NEW_SDK"},
            ],
            "javax_to_jakarta_import_changes": [
                {"rule_id": "IMPORT_JAVAX_VALIDATION_TO_JAKARTA"},
                {"rule_id": "IMPORT_JAVAX_SERVLET_TO_JAKARTA"},
            ],
            "anti_pattern_warnings": ["Many explicit versions remain."],
        },
    )
    report_b = _write_report(
        tmp_path / "b.json",
        {
            "project_id": "project-b",
            "candidate_deterministic_rules": [
                {"rule_id": "JJWT_VERSION_ALIGNMENT", "recommended_action": "Align jjwt.", "safe_to_auto_apply": True},
                {"rule_id": "INITMOCKS_TO_OPENMOCKS", "recommended_action": "Modernize Mockito.", "safe_to_auto_apply": True},
            ],
            "candidate_human_review_items": [
                {"rule_id": "SPRING_SECURITY_BEHAVIOR_REVIEW", "recommended_action": "Review security drift."}
            ],
            "candidate_llm_remediation_items": [
                {"rule_id": "UNMAPPED_SOURCE_TRANSFORMATION", "recommended_action": "Review unmapped changes."}
            ],
            "framework_library_signals": [
                {"signal_id": "JJWT"},
            ],
            "javax_to_jakarta_import_changes": [],
            "anti_pattern_warnings": [],
        },
    )

    result = extract_rules_from_golden_reports(
        report_paths=[report_a, report_b],
        output_dir=tmp_path / "out",
    )

    payload = result.payload
    covered = {item["rule_id"]: item for item in payload["already_covered_by_factory"]}
    missing = {item["rule_id"]: item for item in payload["missing_deterministic_rules"]}
    test_rules = {item["rule_id"]: item for item in payload["missing_test_modernization_rules"]}
    human = {item["rule_id"]: item for item in payload["human_review_gates"]}
    llm = {item["rule_id"]: item for item in payload["llm_remediation_candidates"]}
    playbooks = {item["rule_id"]: item for item in payload["migration_playbooks_needed"]}
    anti = payload["anti_pattern_warnings"]

    assert "LOMBOK_VERSION_ALIGNMENT" in covered
    assert missing["JJWT_VERSION_ALIGNMENT"]["suggested_priority"] == "HIGH"
    assert sorted(missing["JJWT_VERSION_ALIGNMENT"]["source_projects"]) == ["project-a", "project-b"]
    assert "MOCKBEAN_TO_MOCKITOBEAN" in test_rules
    assert "INITMOCKS_TO_OPENMOCKS" in test_rules
    assert "API_CONTRACT_REVIEW_GATE" in human
    assert "SPRING_SECURITY_BEHAVIOR_REVIEW" in human
    assert "UNMAPPED_SOURCE_TRANSFORMATION" in llm
    assert "AZURE_SDK_MIGRATION_PLAYBOOK" in playbooks
    assert "JAKARTA_HYBRID_STRATEGY" in playbooks
    assert "CONSUMER_COMPATIBILITY_VALIDATION" in playbooks
    assert anti
    assert result.report_path.is_file()
    assert result.summary_path.is_file()


def test_rule_extractor_summary_and_json_artifacts_are_written(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "report.json",
        {
            "project_id": "project-a",
            "candidate_deterministic_rules": [
                {"rule_id": "JJWT_VERSION_ALIGNMENT", "recommended_action": "Align jjwt.", "safe_to_auto_apply": True}
            ],
            "candidate_human_review_items": [],
            "candidate_llm_remediation_items": [],
            "framework_library_signals": [],
            "javax_to_jakarta_import_changes": [],
            "anti_pattern_warnings": [],
        },
    )

    result = extract_rules_from_golden_reports(report_paths=[report], output_dir=tmp_path / "out")

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    summary = result.summary_path.read_text(encoding="utf-8")
    assert payload["missing_deterministic_rules"][0]["rule_id"] == "JJWT_VERSION_ALIGNMENT"
    assert "Rule Extraction Summary" in summary
    assert "Missing Deterministic Rules" in summary


def test_rule_extractor_uses_inventory_to_mark_jjwt_as_already_covered(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "report.json",
        {
            "project_id": "project-a",
            "candidate_deterministic_rules": [
                {"rule_id": "JJWT_VERSION_ALIGNMENT", "recommended_action": "Align jjwt.", "safe_to_auto_apply": True}
            ],
            "candidate_human_review_items": [],
            "candidate_llm_remediation_items": [],
            "framework_library_signals": [],
            "javax_to_jakarta_import_changes": [],
            "anti_pattern_warnings": [],
        },
    )
    inventory = export_factory_capability_inventory(output_dir=tmp_path / "inventory")

    result = extract_rules_from_golden_reports(
        report_paths=[report],
        output_dir=tmp_path / "out",
        factory_capability_inventory=inventory.report_path,
    )

    covered = {item["rule_id"]: item for item in result.payload["already_covered_by_factory"]}
    assert "JJWT_VERSION_ALIGNMENT" in covered
    assert covered["JJWT_VERSION_ALIGNMENT"]["coverage_source"] == "inventory_artifact"
    assert not result.payload["missing_deterministic_rules"]


def test_rule_extractor_uses_inventory_to_mark_azure_review_gate_as_covered(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "report.json",
        {
            "project_id": "project-a",
            "candidate_deterministic_rules": [],
            "candidate_human_review_items": [],
            "candidate_llm_remediation_items": [],
            "framework_library_signals": [
                {"signal_id": "AZURE_OLD_SDK"},
                {"signal_id": "AZURE_NEW_SDK"},
            ],
            "javax_to_jakarta_import_changes": [],
            "anti_pattern_warnings": [],
        },
    )
    inventory = export_factory_capability_inventory(output_dir=tmp_path / "inventory")

    result = extract_rules_from_golden_reports(
        report_paths=[report],
        output_dir=tmp_path / "out",
        factory_capability_inventory=inventory.payload,
    )

    covered_review = {item["rule_id"]: item for item in result.payload["covered_review_capabilities"]}
    playbooks = {item["rule_id"]: item for item in result.payload["migration_playbooks_needed"]}
    assert "AZURE_SDK_MIGRATION_PLAYBOOK" in covered_review
    assert "AZURE_SDK_MIGRATION_PLAYBOOK" not in playbooks
    assert covered_review["AZURE_SDK_MIGRATION_PLAYBOOK"]["coverage_source"] == "inventory_artifact"


def test_rule_extractor_uses_inventory_to_mark_java_spring_boot_and_jakarta_import_rules_as_covered(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "report.json",
        {
            "project_id": "project-a",
            "candidate_deterministic_rules": [
                {"rule_id": "JAVA_VERSION_ALIGNMENT", "recommended_action": "Align Java target.", "safe_to_auto_apply": True},
                {"rule_id": "SPRING_BOOT_VERSION_ALIGNMENT", "recommended_action": "Align Spring Boot target.", "safe_to_auto_apply": True},
            ],
            "candidate_human_review_items": [],
            "candidate_llm_remediation_items": [],
            "framework_library_signals": [],
            "javax_to_jakarta_import_changes": [
                {"rule_id": "IMPORT_JAVAX_VALIDATION_TO_JAKARTA"},
                {"rule_id": "IMPORT_JAVAX_XML_BIND_TO_JAKARTA"},
                {"rule_id": "IMPORT_JAVAX_SERVLET_TO_JAKARTA"},
            ],
            "anti_pattern_warnings": [],
        },
    )
    inventory = export_factory_capability_inventory(output_dir=tmp_path / "inventory")

    result = extract_rules_from_golden_reports(
        report_paths=[report],
        output_dir=tmp_path / "out",
        factory_capability_inventory=inventory.report_path,
    )

    covered = {item["rule_id"]: item for item in result.payload["already_covered_by_factory"]}
    missing = {item["rule_id"]: item for item in result.payload["missing_deterministic_rules"]}
    assert "JAVA_VERSION_ALIGNMENT" in covered
    assert "SPRING_BOOT_VERSION_ALIGNMENT" in covered
    assert "IMPORT_JAVAX_VALIDATION_TO_JAKARTA" in covered
    assert "IMPORT_JAVAX_XML_BIND_TO_JAKARTA" in covered
    assert "IMPORT_JAVAX_SERVLET_TO_JAKARTA" in covered
    assert "JAVA_VERSION_ALIGNMENT" not in missing
    assert "SPRING_BOOT_VERSION_ALIGNMENT" not in missing
    assert "IMPORT_JAVAX_VALIDATION_TO_JAKARTA" not in missing


def _write_report(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
