from __future__ import annotations

from pathlib import Path

import yaml

from migration_factory.remediation import (
    AUTO_APPLY_DETERMINISTIC,
    AUTO_APPLY_DETERMINISTIC_CANDIDATE,
    HUMAN_REVIEW_ONLY,
    LLM_DISABLED_REPORT_ONLY,
    build_remediation_plan,
    decide_remediation,
    decide_remediation_v1,
    generate_remediation_plan,
    load_llm_policy,
    NO_REMEDIATION_AVAILABLE,
)


def test_default_llm_policy_disables_llm(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    assert policy.enabled is False
    assert policy.provider == "github_copilot_enterprise"
    assert policy.require_human_approval is True


def test_deterministic_remediation_decision_does_not_require_llm(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    decision = decide_remediation(
        state={"final_status": "BUILD_FAILED_IN_SANDBOX"},
        llm_policy=policy,
        build_error_contract={"result_kind": "compilation_error"},
        failure_classification=None,
    )

    assert decision.decision == AUTO_APPLY_DETERMINISTIC


def test_behavioral_failure_with_llm_disabled_generates_report_only_plan(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")
    output_dir = tmp_path / "remediation"
    plan_path = build_remediation_plan(
        state={
            "run_id": "run-001",
            "final_status": "TEST_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "current_unit": "spring-boot-3-5-14",
            "artifact_refs": {
                "build_error_contract": str(tmp_path / "build-error.json"),
                "post_transform_failure_classification": str(tmp_path / "classification.json"),
            },
        },
        output_dir=output_dir,
        llm_policy=policy,
        build_error_contract={"result_kind": "unknown_failure", "unit_id": "spring-boot-3-5-14"},
        failure_classification={"category_counts": {"HTTP_STATUS_CONTRACT_DRIFT": 2}},
    )

    payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))
    assert payload["remediation_decision"] == LLM_DISABLED_REPORT_ONLY
    assert payload["llm_policy"]["enabled"] is False
    assert payload["human_review_required"] is True
    assert payload["llm_policy"]["max_calls_per_run"] == 0
    assert payload["llm_policy"]["max_files_per_call"] == 0
    assert payload["llm_policy"]["max_diff_lines_per_patch"] == 0
    assert payload["blocked_reasons"]
    assert payload["recommended_next_actions"]
    assert payload["remediation_candidates"][0]["llm_candidate"] is True


def test_behavioral_failure_without_category_with_llm_disabled_becomes_human_review_only(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    decision = decide_remediation(
        state={"final_status": "BUILD_FAILED_IN_SANDBOX"},
        llm_policy=policy,
        build_error_contract={"result_kind": "unknown_failure"},
        failure_classification=None,
    )

    assert decision.decision == HUMAN_REVIEW_ONLY


def test_behavioral_classified_failures_generate_human_review_candidates(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    result = generate_remediation_plan(
        state={
            "run_id": "run-002",
            "final_status": "TEST_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "current_unit": "spring-boot-3-5-14",
            "artifact_refs": {},
        },
        output_dir=tmp_path / "remediation",
        llm_policy=policy,
        build_error_contract={"result_kind": "unknown_failure", "unit_id": "spring-boot-3-5-14"},
        failure_classification={
            "category_counts": {
                "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 2,
                "HTTP_STATUS_CONTRACT_DRIFT": 1,
            },
            "failures": [
                {
                    "test_class": "com.example.MvcTest",
                    "test_method": "requestMethodNotSupported",
                    "category": "HTTP_STATUS_CONTRACT_DRIFT",
                    "symptom": "expected 404 but was 405",
                }
            ],
        },
    )

    payload = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert payload["remediation_decision"] == LLM_DISABLED_REPORT_ONLY
    assert payload["remediation_candidates"][0]["safe_to_auto_apply"] is False
    assert payload["remediation_candidates"][0]["requires_human_approval"] is True
    assert payload["recommended_next_actions"]


def test_deterministic_dependency_failure_produces_auto_apply_candidate_without_applying(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    decision = decide_remediation_v1(
        llm_policy=policy,
        build_error_contract={"result_kind": "dependency_error", "message": "Could not resolve artifact"},
        failure_classification=None,
    )
    result = generate_remediation_plan(
        state={
            "run_id": "run-003",
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "",
            "current_unit": "spring-boot-3-5-14",
            "artifact_refs": {},
        },
        output_dir=tmp_path / "remediation",
        llm_policy=policy,
        build_error_contract={"result_kind": "dependency_error", "message": "Could not resolve artifact"},
        failure_classification=None,
    )

    payload = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert decision == AUTO_APPLY_DETERMINISTIC_CANDIDATE
    assert payload["remediation_decision"] == AUTO_APPLY_DETERMINISTIC_CANDIDATE
    assert payload["remediation_candidates"][0]["deterministic_rule"] == "align_dependency_versions"
    assert payload["remediation_candidates"][0]["safe_to_auto_apply"] is True


def test_missing_classification_still_generates_useful_remediation_plan(tmp_path: Path) -> None:
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")

    result = generate_remediation_plan(
        state={
            "run_id": "run-004",
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "",
            "current_unit": "spring-boot-3-5-14",
            "artifact_refs": {},
        },
        output_dir=tmp_path / "remediation",
        llm_policy=policy,
        build_error_contract={"result_kind": "unknown_failure", "message": "Application failed"},
        failure_classification=None,
    )

    payload = yaml.safe_load(result.path.read_text(encoding="utf-8"))
    assert payload["remediation_decision"] == NO_REMEDIATION_AVAILABLE
    assert payload["blocked_reasons"]
    assert payload["recommended_next_actions"]
