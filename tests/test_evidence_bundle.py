from __future__ import annotations

import json
from pathlib import Path

from migration_factory.evidence.bundle import generate_management_evidence_bundle, main


def test_evidence_bundle_generates_from_synthetic_artifacts(tmp_path: Path) -> None:
    readiness = _write_json(
        tmp_path / "readiness_pack.json",
        {
            "project_id": "candidate",
            "readiness_status": "READY_WITH_WARNINGS",
            "human_review_required": True,
            "warnings": ["Legacy SDK detected."],
            "deterministic_transformations_likely_applicable": [{"capability_id": "JAVA_VERSION_ALIGNMENT"}],
            "review_gates_expected": [{"capability_id": "AZURE_SDK_MIGRATION_PLAYBOOK"}],
            "consumer_validation_suggestions": [{"consumers": [{"consumer_project_id": "consumer-a"}]}],
        },
    )
    launch = _write_json(
        tmp_path / "migration_launch_plan.json",
        {
            "launch_status": "READY_FOR_REVIEW",
            "governance": {"production_promotion_allowed": False},
            "warnings": ["Human review before launch."],
        },
    )
    inventory = _write_json(
        tmp_path / "factory_capability_inventory.json",
        {
            "capabilities": [
                {"capability_id": "JAVA_VERSION_ALIGNMENT", "capability_type": "TRANSFORM"},
                {"capability_id": "AZURE_SDK_MIGRATION_PLAYBOOK", "capability_type": "REVIEW_GATE"},
            ]
        },
    )
    migration_report = _write_json(
        tmp_path / "migration_report.json",
        {
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "human_review_required": True,
            "production_allowed": False,
            "warnings": ["Post-transform tests failed."],
        },
    )

    result = generate_management_evidence_bundle(
        output_dir=tmp_path / "out",
        project_id="candidate",
        readiness_pack_path=readiness,
        migration_launch_plan_path=launch,
        factory_capability_inventory_path=inventory,
        migration_report_path=migration_report,
    )

    payload = result["payload"]
    summary = Path(result["summary_path"]).read_text(encoding="utf-8")
    technical = json.loads(Path(result["technical_index_path"]).read_text(encoding="utf-8"))
    assert Path(result["bundle_path"]).is_file()
    assert payload["readiness_status"] == "READY_WITH_WARNINGS"
    assert payload["migration_status"] == "BUILD_FAILED_IN_SANDBOX"
    assert payload["production_promotion_allowed"] is False
    assert "JAVA_VERSION_ALIGNMENT" in payload["deterministic_transformations_covered"]
    assert "AZURE_SDK_MIGRATION_PLAYBOOK" in payload["review_gates_detected"]
    assert "What Is Automated" in summary
    assert "What Still Needs Human Review" in summary
    assert technical["artifacts"]


def test_evidence_bundle_missing_optional_artifacts_do_not_crash(tmp_path: Path) -> None:
    result = generate_management_evidence_bundle(output_dir=tmp_path / "out", project_id="candidate")

    payload = result["payload"]
    assert payload["readiness_status"] == "not_provided"
    assert payload["migration_status"] == "not_provided"
    assert payload["limitations"]


def test_evidence_bundle_cli_and_no_hardcoded_real_names(tmp_path: Path) -> None:
    readiness = _write_json(tmp_path / "readiness_pack.json", {"project_id": "candidate", "readiness_status": "READY_FOR_READ_ONLY_ASSESSMENT"})
    exit_code = main(["--output-dir", str(tmp_path / "out"), "--readiness-pack", str(readiness), "--project-id", "candidate"])
    implementation = Path("migration_factory/evidence/bundle.py").read_text(encoding="utf-8").lower()

    assert exit_code == 0
    assert (tmp_path / "out" / "management_evidence_bundle.json").is_file()
    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
