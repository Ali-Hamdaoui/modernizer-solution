from __future__ import annotations

from migration_factory.control_tower.application.v2_repair_learning_case import (
    build_repair_learning_case,
    build_rag_document_from_learning_case_data,
    compute_learning_reuse_signature,
)


def test_learning_case_created_for_unknown_failure() -> None:
    case = build_repair_learning_case(
        job_id="job-1",
        stage_index=2,
        microservice="msa-utils",
        family="UNKNOWN_FAILURE",
        subfamily="UNKNOWN_SUBFAMILY",
        evidence={"evidence_pack_checksum": "sha256:evidence"},
        case_status="observed",
        created_at="2026-07-04T00:00:00Z",
    )

    assert case["learning_case_id"].startswith("repair-learning-")
    assert case["case_status"] == "observed"
    assert case["family"] == "UNKNOWN_FAILURE"
    assert case["subfamily"] == "UNKNOWN_SUBFAMILY"
    assert case["rag_document"]["non_authoritative"] is True
    assert case["backend_gate"]["rag_can_apply"] is False
    assert case["backend_gate"]["rag_can_approve"] is False
    assert case["backend_gate"]["downstream_start_allowed"] is False


def test_learning_case_created_for_dry_run_recipe_plan() -> None:
    case = build_repair_learning_case(
        job_id="job-2",
        stage_index=2,
        microservice="msa-utils",
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_IMPORT_ONLY",
        recipe_plan={
            "recipe_id": "recipe-jakarta-import-only-v1",
            "recipe_status": "dry_run_only",
            "plan_status": "dry_run",
            "plan_checksum": "sha256:plan",
            "missing_evidence": [],
            "forbidden_patterns_matched": [],
        },
        case_status="dry_run_created",
        created_at="2026-07-04T00:00:00Z",
    )

    assert case["case_status"] == "dry_run_created"
    assert case["recipe_id"] == "recipe-jakarta-import-only-v1"
    assert case["recipe_plan_checksum"] == "sha256:plan"
    assert case["rag_document"]["recipe_status"] == "dry_run_only"
    assert "promote" in case["recommended_engineer_action"].lower()


def test_learning_case_created_for_human_refactor_powermock_constructor() -> None:
    case = build_repair_learning_case(
        job_id="job-3",
        stage_index=2,
        microservice="msa-utils",
        family="POWERMOCK_LEGACY_TEST_STRATEGY",
        subfamily="POWERMOCK_CONSTRUCTOR_MOCKING",
        recipe_plan={
            "recipe_id": "recipe-powermock-constructor-mocking-v1",
            "recipe_status": "human_refactor_required",
            "plan_status": "blocked",
            "plan_checksum": "sha256:plan",
            "forbidden_patterns_matched": ["PowerMockito.whenNew", "constructor mocking"],
        },
        case_status="human_refactor_required",
        created_at="2026-07-04T00:00:00Z",
    )

    assert case["case_status"] == "human_refactor_required"
    assert case["rag_document"]["risk_level"] == "high"
    assert case["rag_document"]["recipe_status"] == "human_refactor_required"
    assert "Engineer refactor required" in case["rag_document"]["resolution_summary"]
    assert "PowerMock migration may alter test behavior" in case["rag_document"]["do_not_apply_when"]


def test_successful_initmocks_repair_can_create_reusable_learning_case() -> None:
    case = build_repair_learning_case(
        job_id="job-4",
        stage_index=2,
        microservice="msa-utils",
        family="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
        subfamily="INITMOCKS_DIRECT_REPLACEMENT",
        recipe_id="recipe-initmocks-direct-replacement-v1",
        case_status="successful_repair",
        evidence={"evidence_pack_checksum": "sha256:evidence"},
        strategy_packet={"strategy_checksum": "sha256:strategy"},
        recipe_plan={"plan_checksum": "sha256:plan"},
        matched_patterns=["MockitoAnnotations.initMocks"],
        created_at="2026-07-04T00:00:00Z",
    )

    assert case["case_status"] == "successful_repair"
    assert case["reuse_signature"].startswith("sha256:")
    assert case["rag_document"]["recipe_status"] == "governed_success"
    assert case["rag_document"]["risk_level"] == "low"
    assert "Successful governed repair" in case["rag_document"]["summary"]
    assert case["rag_document"]["rag_can_apply"] is False


def test_learning_case_converts_to_rag_document() -> None:
    case_data = {
        "learning_case_id": "case-1",
        "family": "JAKARTA_NAMESPACE_MISMATCH",
        "subfamily": "JAKARTA_IMPORT_ONLY",
        "recipe_id": "recipe-jakarta-import-only-v1",
        "case_status": "dry_run_created",
        "reuse_signature": "sha256:reuse",
        "missing_evidence": ["compile proof"],
    }

    doc = build_rag_document_from_learning_case_data(case_data)

    assert doc["title"] == "JAKARTA_IMPORT_ONLY repair learning case"
    assert doc["problem_signature"] == "sha256:reuse"
    assert doc["recipe_status"] == "dry_run_only"
    assert doc["evidence_requirements"] == ["compile proof"]
    assert doc["non_authoritative"] is True
    assert doc["rag_can_apply"] is False


def test_reuse_signature_is_stable_for_same_case_shape() -> None:
    first = compute_learning_reuse_signature(
        microservice="msa-utils",
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_IMPORT_ONLY",
        recipe_id="recipe-jakarta-import-only-v1",
        root_cause="javax imports fail after boot 3 migration",
        matched_patterns=["javax.servlet", "javax.validation"],
    )
    second = compute_learning_reuse_signature(
        microservice="msa-utils",
        family="JAKARTA_NAMESPACE_MISMATCH",
        subfamily="JAKARTA_IMPORT_ONLY",
        recipe_id="recipe-jakarta-import-only-v1",
        root_cause="javax imports fail after boot 3 migration",
        matched_patterns=["javax.validation", "javax.servlet"],
    )

    assert first == second
    assert first.startswith("sha256:")