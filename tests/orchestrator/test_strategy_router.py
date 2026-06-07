from __future__ import annotations

import json
from pathlib import Path

from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE, build_initial_state
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.remediation.policy import LlmPolicy
from migration_factory.remediation.strategy_router import (
    AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE,
    ESCALATE_TO_LLM_PROPOSAL,
    LLM_DISABLED_HUMAN_REVIEW_REQUIRED,
    NO_BEHAVIORAL_REMEDIATION_NEEDED,
    STOP_REPEATED_BEHAVIORAL_PATCH_CHASING,
    generate_behavioral_remediation_strategy,
)


def test_behavioral_failure_without_prior_patch_routes_to_deterministic_proposal(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir)

    result = generate_behavioral_remediation_strategy(run_dir=run_dir)

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == AUTO_DETERMINISTIC_PROPOSAL_AVAILABLE
    assert payload["safe_to_auto_apply"] is False
    assert payload["human_approval_required"] is True


def test_behavioral_failure_with_same_blocker_after_approved_patch_stops_patch_chasing(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir)
    _write_approved_patch_result(run_dir, same_blocker=True)

    result = generate_behavioral_remediation_strategy(run_dir=run_dir, llm_policy=None)

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == STOP_REPEATED_BEHAVIORAL_PATCH_CHASING
    assert payload["repeated_same_blocker"] is True
    assert payload["patch_chasing_should_stop"] is True


def test_same_repeated_blocker_with_enabled_llm_policy_routes_to_llm_proposal(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir)
    _write_approved_patch_result(run_dir, same_blocker=True)

    result = generate_behavioral_remediation_strategy(
        run_dir=run_dir,
        llm_policy=LlmPolicy(enabled=True, allowed_categories=["SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT"]),
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == ESCALATE_TO_LLM_PROPOSAL
    assert payload["llm_proposal_recommended"] is True
    assert payload["expected_future_artifacts"] == [
        "llm_model1_proposal.json",
        "llm_model2_review.json",
        "human_approval_required=true",
    ]


def test_same_repeated_blocker_with_disabled_llm_policy_routes_to_human_review(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir)
    _write_approved_patch_result(run_dir, same_blocker=True)

    result = generate_behavioral_remediation_strategy(
        run_dir=run_dir,
        llm_policy=LlmPolicy(enabled=False, allowed_categories=["SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT"]),
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == LLM_DISABLED_HUMAN_REVIEW_REQUIRED
    assert payload["human_review_only_required"] is True


def test_non_behavioral_failure_routes_to_no_behavioral_remediation_needed(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir, behavioral=False)

    result = generate_behavioral_remediation_strategy(run_dir=run_dir)

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["decision"] == NO_BEHAVIORAL_REMEDIATION_NEEDED


def test_strategy_router_includes_two_model_metadata(tmp_path: Path) -> None:
    run_dir = _workspace(tmp_path)
    _write_behavioral_artifacts(run_dir)

    result = generate_behavioral_remediation_strategy(run_dir=run_dir)

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["model_1_role"] == "remediation_proposer"
    assert payload["model_2_role"] == "remediation_reviewer_optimizer"
    assert payload["model_2_input_requires"] == [
        "original context pack",
        "model 1 proposal",
        "risk constraints",
        "allowed patch scope",
    ]


def test_finalize_failed_sandbox_adds_behavioral_strategy_refs(tmp_path: Path) -> None:
    state = _failed_state(tmp_path)

    result = finalize_orchestration_state(state)
    summary = json.loads((Path(state["orchestration_dir"]) / "orchestration_summary.json").read_text(encoding="utf-8"))
    final_report = json.loads(Path(result["artifact_refs"]["final_migration_report"]).read_text(encoding="utf-8"))
    final_summary = Path(result["artifact_refs"]["final_migration_summary"]).read_text(encoding="utf-8")

    assert result["artifact_refs"]["behavioral_remediation_strategy"].endswith("behavioral_remediation_strategy.json")
    assert summary["artifact_refs"]["behavioral_remediation_strategy"].endswith("behavioral_remediation_strategy.json")
    assert final_report["artifact_refs"]["behavioral_remediation_strategy"].endswith("behavioral_remediation_strategy.json")
    assert "Behavioral Remediation Strategy:" in final_summary


def test_strategy_router_has_no_hardcoded_real_project_names() -> None:
    implementation = Path("migration_factory/remediation/strategy_router.py").read_text(encoding="utf-8").lower()

    assert "msa-dto" not in implementation
    assert "common-utils" not in implementation
    assert "translation" not in implementation


def _workspace(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    (run_dir / "remediation").mkdir(parents=True, exist_ok=True)
    (run_dir / "orchestration").mkdir(parents=True, exist_ok=True)
    (run_dir / "final").mkdir(parents=True, exist_ok=True)
    (run_dir / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"artifact_refs": {}, "warnings": [], "run_id": "run-001"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "final" / "migration_report.json").write_text(
        json.dumps({"artifact_refs": {}, "warnings": [], "run_id": "run-001"}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "final" / "migration_summary.md").write_text("# Migration Summary\n", encoding="utf-8")
    return run_dir


def _write_behavioral_artifacts(run_dir: Path, *, behavioral: bool = True) -> None:
    remediation = run_dir / "remediation"
    remediation.mkdir(parents=True, exist_ok=True)
    category = "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT" if behavioral else "DEPENDENCY_ALIGNMENT_GAP"
    llm_candidate = behavioral
    missing_bean = [{"bean_type": "com.example.FunctionalMessageHelper"}] if behavioral else []
    suspected = ["ApplicationContext", "Bean wiring"] if behavioral else []
    (remediation / "behavioral_failure_context_pack.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "primary_failure_message": (
                    "No qualifying bean of type 'com.example.FunctionalMessageHelper' available"
                    if behavioral
                    else "Dependency mismatch"
                ),
                "failure_categories": {category: 1},
                "missing_bean_type_errors": missing_bean,
                "suspected_framework_areas": suspected,
                "deterministic_fixes_already_applied": [{"type": "align_jjwt_version", "status": "updated"}],
                "llm_candidate": llm_candidate,
                "human_review_required": behavioral,
                "safe_to_auto_apply": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (remediation / "legacy_behavior_equivalence_report.json").write_text(
        json.dumps({"run_id": "run-001", "failed_unit": "spring-boot-3-5-14", "beans": []}) + "\n",
        encoding="utf-8",
    )
    (remediation / "test_context_repair_proposal.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "patch_proposal_available": False,
                "proposals": [{"missing_bean_type": "com.example.FunctionalMessageHelper", "provider_exists_but_not_loaded": behavioral}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (remediation / "legacy_guided_patch_proposal.json").write_text(
        json.dumps({"run_id": "run-001", "failed_unit": "spring-boot-3-5-14", "patch_proposal_available": False}) + "\n",
        encoding="utf-8",
    )
    (remediation / "mockito_bean_placement_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "failed_unit": "spring-boot-3-5-14",
                "patch_proposal_available": behavioral,
                "proposals": [
                    {
                        "missing_bean_type": "com.example.FunctionalMessageHelper",
                        "patch_proposal_available": behavioral,
                        "patch_strategy": "duplicate_mockito_bean_into_failing_test_class" if behavioral else "",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _write_approved_patch_result(run_dir: Path, *, same_blocker: bool) -> None:
    remediation = run_dir / "remediation"
    stdout_tail = [
        "Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException: No qualifying bean of type 'com.example.FunctionalMessageHelper' available"
        if same_blocker
        else "Caused by: another blocker"
    ]
    (remediation / "approved_patch_apply_result.json").write_text(
        json.dumps(
            {
                "status": "applied",
                "approved_by": "reviewer",
                "failed_unit_id": "spring-boot-3-5-14",
                "rerun": {
                    "attempted": True,
                    "exit_code": 1,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": [],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _failed_state(tmp_path: Path) -> dict:
    legacy = tmp_path / "legacy"
    modernized = tmp_path / "modernized"
    ai_hub = tmp_path / "ai-hub"
    legacy.mkdir()
    modernized.mkdir()
    (ai_hub / "profiles").mkdir(parents=True, exist_ok=True)
    (ai_hub / "profiles" / "java17.yaml").write_text("id: java17\n", encoding="utf-8")
    state = build_initial_state(
        run_id="run-001",
        legacy_app_path=str(legacy),
        modernized_app_path=str(modernized),
        ai_hub_path=str(ai_hub),
        profile_id="java17",
        mode=FULL_SANDBOX_MIGRATION_MODE,
    )
    run_dir = Path(state["run_dir"])
    sandbox = run_dir / "workspaces" / "sandbox"
    analysis_dir = Path(state["analysis_dir"])
    planning_dir = Path(state["planning_dir"])
    assessment_dir = Path(state["assessment_dir"])
    approval_dir = run_dir / "approval"
    transform_dir = run_dir / "transformation"
    test_dir = run_dir / "test" / "post_transform"
    logs_dir = run_dir / "logs"
    build_dir = run_dir / "build"
    for directory in (sandbox, analysis_dir, planning_dir, assessment_dir, approval_dir, transform_dir, test_dir, logs_dir, build_dir):
        directory.mkdir(parents=True, exist_ok=True)
    _write_behavioral_artifacts(run_dir)
    (analysis_dir / "analysis_report.json").write_text("{}\n", encoding="utf-8")
    (planning_dir / "migration_plan.yaml").write_text("status: PASS\nrequires_human_approval: true\n", encoding="utf-8")
    (assessment_dir / "assessment_report.json").write_text(json.dumps({"source_stack": {}, "target_stack": {}}) + "\n", encoding="utf-8")
    (approval_dir / "approval_decision.json").write_text(json.dumps({"decision": "approved"}) + "\n", encoding="utf-8")
    (approval_dir / "approved_plan_lock.json").write_text("{}\n", encoding="utf-8")
    (transform_dir / "transformation_execution_plan.yaml").write_text("recipes: []\n", encoding="utf-8")
    (sandbox / ".migration").mkdir(parents=True, exist_ok=True)
    (sandbox / ".migration" / "ledger.json").write_text("{}\n", encoding="utf-8")
    (logs_dir / "phase2_transform.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_agent.log").write_text("failed\n", encoding="utf-8")
    (test_dir / "test_summary.md").write_text("# failed\n", encoding="utf-8")
    (test_dir / "test_report.json").write_text(
        json.dumps(
            {
                "test_status": "TEST_FAILED_IN_SANDBOX",
                "severity": "ERROR",
                "message": "Failed to load ApplicationContext",
                "totals": {"tests": 1, "passed": 0, "failures": 0, "errors": 1, "skipped": 0},
                "test_log_path": str(test_dir / "test_agent.log"),
                "source_log_path": str(logs_dir / "phase2_transform.log"),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    classification_path = build_dir / "post_transform_failure_classification.json"
    classification_path.write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "failure_count": 1,
                "category_counts": {"SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1},
                "failures": [
                    {
                        "test_class": "com.example.CustomExceptionTranslatorTest",
                        "test_method": "missingBean",
                        "category": "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
                        "symptom": "Failed to load ApplicationContext",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    build_error = build_dir / "build-error-001-missing_config.json"
    build_error.write_text(
        json.dumps(
            {
                "unit_id": "spring-boot-3-5-14",
                "status": "failed",
                "result_kind": "missing_config",
                "message": "Application configuration is missing or invalid",
                "matched_line": "No qualifying bean of type 'com.example.FunctionalMessageHelper' available",
                "failure_classification_path": str(classification_path),
                "failure_categories": {"SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": "approved",
            "orchestration_status": "FAIL",
            "transform_status": "BUILD_FAILED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "test_status": "TEST_FAILED_IN_SANDBOX",
            "final_status": "BUILD_FAILED_IN_SANDBOX",
            "stop_reason": "Sandbox migration failed after tests.",
            "current_unit": "spring-boot-3-5-14",
            "sandbox_path": str(sandbox),
            "warnings": [],
            "errors": ["behavioral test failures"],
            "blockers": ["behavioral test failures"],
            "artifact_refs": {
                "analysis_report": str(analysis_dir / "analysis_report.json"),
                "migration_plan": str(planning_dir / "migration_plan.yaml"),
                "assessment_report": str(assessment_dir / "assessment_report.json"),
                "approval_decision": str(approval_dir / "approval_decision.json"),
                "approved_plan_lock": str(approval_dir / "approved_plan_lock.json"),
                "transformation_execution_plan": str(transform_dir / "transformation_execution_plan.yaml"),
                "migration_ledger": str(sandbox / ".migration" / "ledger.json"),
                "phase2_log": str(logs_dir / "phase2_transform.log"),
                "post_transform_test_report": str(test_dir / "test_report.json"),
                "post_transform_test_summary": str(test_dir / "test_summary.md"),
                "post_transform_test_log": str(test_dir / "test_agent.log"),
                "build_error_contract": str(build_error),
                "post_transform_failure_classification": str(classification_path),
            },
        }
    )
    return state
