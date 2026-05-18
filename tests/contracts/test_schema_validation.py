import json
from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest

from migration_factory.contracts import (
    APPROVAL_DECISION_VALUES,
    COPILOT_STATUS_VALUES,
    RISK_VALUES,
    SCHEMA_VERSION,
    STATUS_VALUES,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "migration_factory" / "contracts" / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _validate(schema_name: str, payload: dict) -> None:
    jsonschema.validate(payload, _load_schema(schema_name))


def _base(status: str = "PASS") -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": "run-1",
        "status": status,
        "artifact_refs": {"self": "artifact.json"},
    }


VALID_PAYLOADS = {
    "analysis_report.schema.json": {**_base(), "risk": "LOW"},
    "rewrite_impact_summary.schema.json": {
        **_base(),
        "agent": "analysis_agent",
        "phase": "analysis",
        "overall_impact": "MEDIUM",
        "changed_files": ["src/main/java/A.java"],
        "high_risk_files": ["src/main/java/A.java"],
        "migration_signals": {
            "api_or_boot_upgrade": True,
            "javax_removed": True,
            "boot_2_to_3_gap": True,
            "java_11_to_17_gap": True,
            "javax_present": True,
            "security_config_touched": False,
            "datasource_config_touched": False,
        },
        "blocked_reasons": [],
        "source_modified": False,
    },
    "read_only_verification.schema.json": {
        **_base(),
        "agent": "analysis_agent",
        "phase": "analysis",
        "paths": {
            "legacy_root": "/workspace/legacy",
            "modernized_root": "/workspace/modernized",
            "artifact": ".migration/runs/run-1/analysis/read_only_verification.json",
        },
        "allowed_write_roots": [".migration/runs/run-1/analysis"],
        "checks": {
            "legacy_tree_unchanged": True,
            "modernized_source_unchanged": True,
            "ignored_generated_paths": ["target/"],
        },
        "violations": [],
        "source_modified": False,
    },
    "rewrite_plugin_plan.schema.json": {
        **_base("USED"),
        "profile_id": "springboot-2.7-to-3.5-java17",
        "catalog_path": "catalogs/openrewrite/springboot-3.5-java17.yaml",
        "catalog_id": "springboot-3.5-java17",
        "plugin": "org.openrewrite.maven:rewrite-maven-plugin:6.39.0",
        "recipe_artifacts": ["org.openrewrite.recipe:rewrite-spring:6.30.4"],
        "active_recipes": ["org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5"],
        "preview_goals": ["rewrite:dryRun"],
        "selected_preview_goal": "rewrite:dryRun",
        "apply_goals_forbidden": True,
    },
    "migration_plan.schema.json": {**_base(), "risk": "HIGH"},
    "migration_units.schema.json": {**_base(), "units": [{"id": "baseline"}]},
    "approval_request.schema.json": {
        **_base(),
        "agent": "planning_agent",
        "phase": "approval",
        "profile": "java17",
        "requires_human_approval": True,
        "decision_options": ["approved", "rejected", "replan_required"],
        "recommended_decision": None,
        "units_to_execute": ["baseline"],
        "blockers": [],
        "warnings": [],
    },
    "copilot_assist.schema.json": {
        **_base("USED"),
        "agent": "planning_agent",
        "phase": "planning",
        "provider": "github_copilot",
        "model": "gpt-test",
        "inputs_summary": {"units_count": 1},
        "advisory_summary": {"warning_count": 0},
        "warnings": [],
        "error": None,
        "can_modify_source": False,
        "can_modify_plan": False,
        "can_modify_blockers": False,
        "can_modify_executable": False,
        "can_modify_unit_order": False,
        "can_modify_approval_decision": False,
        "can_modify_tools": False,
    },
    "assessment_report.schema.json": {
        **_base(),
        "agent": "assessment",
        "phase": "assessment",
        "profile": "java17",
        "overall_risk": "UNKNOWN",
        "source_stack": {"build_tool": "maven", "java": "11", "spring_boot": "2.7"},
        "target_stack": {"build_tool": "maven", "java": "17", "spring_boot": "3.5.14"},
        "analysis": {"status": "PASS", "artifact_ref": "../analysis/analysis_report.json"},
        "planning": {
            "status": "PASS",
            "validation_status": "PASS",
            "executable": True,
            "artifact_ref": "../planning/migration_plan.yaml",
        },
        "openrewrite_dry_run": {
            "status": "PASS",
            "overall_impact": "LOW",
            "counts": {"changed_files": 0},
            "artifact_ref": "../analysis/rewrite_impact_summary.json",
        },
        "migration_units": {
            "count": 1,
            "units": [{"id": "baseline"}],
            "artifact_ref": "../planning/migration_units.yaml",
        },
        "blockers": [],
        "warnings": [],
        "copilot": {"status": "UNAVAILABLE", "artifact_ref": "../planning/copilot_assist.json"},
        "approval_readiness": {
            "status": "READY_FOR_REVIEW",
            "requires_human_approval": True,
            "recommended_decision": None,
            "artifact_ref": "../planning/approval_request.json",
        },
        "read_only_verification": {
            "status": "PASS",
            "source_modified": False,
            "artifact_ref": "../analysis/read_only_verification.json",
        },
        "next_recommended_phase": "human_approval",
        "execution_claims": {
            "transformation_executed": False,
            "openrewrite_apply_executed": False,
            "migrated_build_executed": False,
            "migrated_tests_executed": False,
            "final_migration_executed": False,
        },
    },
}


@pytest.mark.parametrize("schema_name,payload", VALID_PAYLOADS.items())
def test_contract_schemas_accept_valid_payloads(schema_name: str, payload: dict) -> None:
    _validate(schema_name, payload)


def test_schema_enums_match_contract_constants() -> None:
    for schema_name in VALID_PAYLOADS:
        schema = _load_schema(schema_name)
        assert schema["properties"]["schema_version"]["enum"] == [SCHEMA_VERSION]

    assert _load_schema("analysis_report.schema.json")["properties"]["status"]["enum"] == list(
        STATUS_VALUES
    )
    assert _load_schema("migration_plan.schema.json")["properties"]["risk"]["enum"] == list(
        RISK_VALUES
    )
    assert _load_schema("assessment_report.schema.json")["properties"]["overall_risk"][
        "enum"
    ] == list(RISK_VALUES)
    assert _load_schema("approval_request.schema.json")["properties"]["decision_options"][
        "enum"
    ] == [list(APPROVAL_DECISION_VALUES)]
    assert _load_schema("copilot_assist.schema.json")["properties"]["status"]["enum"] == list(
        COPILOT_STATUS_VALUES
    )


@pytest.mark.parametrize("field", ["schema_version", "run_id"])
def test_analysis_report_rejects_missing_required_identity_fields(field: str) -> None:
    payload = deepcopy(VALID_PAYLOADS["analysis_report.schema.json"])
    payload.pop(field)

    with pytest.raises(jsonschema.ValidationError):
        _validate("analysis_report.schema.json", payload)


def test_analysis_report_rejects_unsupported_status() -> None:
    payload = deepcopy(VALID_PAYLOADS["analysis_report.schema.json"])
    payload["status"] = "COMPLETED"

    with pytest.raises(jsonschema.ValidationError):
        _validate("analysis_report.schema.json", payload)


def test_approval_request_rejects_approve_with_changes() -> None:
    payload = deepcopy(VALID_PAYLOADS["approval_request.schema.json"])
    payload["decision_options"] = ["approved", "approve_with_changes", "replan_required"]

    with pytest.raises(jsonschema.ValidationError):
        _validate("approval_request.schema.json", payload)


def test_approval_request_rejects_supported_options_in_wrong_order() -> None:
    payload = deepcopy(VALID_PAYLOADS["approval_request.schema.json"])
    payload["decision_options"] = ["rejected", "approved", "replan_required"]

    with pytest.raises(jsonschema.ValidationError):
        _validate("approval_request.schema.json", payload)


def test_approval_request_rejects_unsupported_decision() -> None:
    payload = deepcopy(VALID_PAYLOADS["approval_request.schema.json"])
    payload["decision"] = "approve_with_changes"

    with pytest.raises(jsonschema.ValidationError):
        _validate("approval_request.schema.json", payload)


def test_rewrite_impact_summary_rejects_impact_without_overall_impact() -> None:
    payload = deepcopy(VALID_PAYLOADS["rewrite_impact_summary.schema.json"])
    payload.pop("overall_impact")
    payload["impact"] = "LOW"

    with pytest.raises(jsonschema.ValidationError):
        _validate("rewrite_impact_summary.schema.json", payload)


def test_assessment_report_rejects_execution_claims() -> None:
    payload = deepcopy(VALID_PAYLOADS["assessment_report.schema.json"])
    payload["execution_claims"]["openrewrite_apply_executed"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validate("assessment_report.schema.json", payload)


def test_copilot_assist_rejects_advisory_flag_true() -> None:
    payload = deepcopy(VALID_PAYLOADS["copilot_assist.schema.json"])
    payload["can_modify_tools"] = True

    with pytest.raises(jsonschema.ValidationError):
        _validate("copilot_assist.schema.json", payload)
