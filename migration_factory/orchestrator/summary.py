from __future__ import annotations

import json
import os
from pathlib import Path
import time
from typing import Any

from migration_factory.final_report import (
    CopilotAdapterStatus,
    detect_copilot_cli_status,
    generate_copilot_report,
    generate_final_migration_report,
    write_failed_copilot_report_response,
)
from migration_factory.agents.copilot_doc_agent import (
    generate_copilot_documentation_package,
)
from migration_factory.remediation import build_remediation_plan, load_llm_policy
from migration_factory.remediation.behavioral_context import (
    generate_behavioral_failure_context_pack,
    should_generate_behavioral_context,
)
from migration_factory.remediation.legacy_equivalence import (
    generate_legacy_behavior_equivalence_report,
)
from migration_factory.remediation.legacy_guided_patch_proposal import (
    generate_legacy_guided_patch_proposal,
)
from migration_factory.remediation.mockito_bean_placement import (
    generate_mockito_bean_placement_report,
)
from migration_factory.remediation.strategy_router import (
    generate_behavioral_remediation_strategy,
)
from migration_factory.remediation.test_context_repair import (
    generate_test_context_repair_proposal,
)
from migration_factory.orchestrator.api_contract_review import build_api_contract_review
from migration_factory.orchestrator.consumer_compatibility import (
    LIBRARY_PROJECT_KINDS,
    run_consumer_compatibility_validation,
)
from migration_factory.orchestrator.artifact_validation import (
    validate_successful_full_sandbox_orchestration,
)
from migration_factory.orchestrator.state import FULL_SANDBOX_MIGRATION_MODE
from migration_factory.orchestrator.state import MigrationState
from migration_factory.orchestrator.timing import record_phase_duration, write_timing_artifacts


EXECUTION_CLAIMS = {
    "transformation_executed": False,
    "openrewrite_apply_executed": False,
    "migrated_build_executed": False,
    "migrated_tests_executed": False,
    "final_migration_executed": False,
}
_COPILOT_REPORT_ENV = "AI_MIGRATION_ENABLE_COPILOT_REPORT"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def build_orchestration_summary(state: MigrationState) -> dict:
    execution_claims = _execution_claims(state)
    return {
        "run_id": state.get("run_id", ""),
        "mode": state.get("mode", ""),
        "resumed_from_mode": state.get("resumed_from_mode", ""),
        "resume_semantics": state.get("resume_semantics", ""),
        "final_status": _final_status(state),
        "current_phase": state.get("current_phase", state.get("current_unit", "")),
        "analysis_status": state.get("analysis_status", ""),
        "planning_status": state.get("planning_status", ""),
        "assessment_status": state.get("assessment_status", ""),
        "orchestration_status": state.get("orchestration_status", ""),
        "orchestration_artifacts_valid": state.get("orchestration_artifacts_valid"),
        "approval_status": state.get("approval_status", ""),
        "approval_decision": state.get("approval_decision"),
        "approved_by": state.get("approved_by", ""),
        "transform_status": state.get("transform_status", ""),
        "build_status": state.get("build_status", ""),
        "test_status": state.get("test_status", ""),
        "test_totals": dict(state.get("test_totals", {}) or {}),
        "test_report_path": state.get("test_report_path", ""),
        "test_summary_path": state.get("test_summary_path", ""),
        "test_log_path": state.get("test_log_path", ""),
        "test_phase": state.get("test_phase", ""),
        "sandbox_path": state.get("sandbox_path", ""),
        "log_path": state.get("transform_log_path", ""),
        "stop_reason": state.get("stop_reason"),
        "blockers": list(state.get("blockers", []) or []),
        "warnings": list(state.get("warnings", []) or []),
        "errors": list(state.get("errors", []) or []),
        "artifact_refs": dict(state.get("artifact_refs", {}) or {}),
        "timing": dict(state.get("timing", {}) or {}),
        **execution_claims,
    }


def write_orchestration_summary(state: MigrationState) -> Path:
    summary_path = Path(state["orchestration_dir"]) / "orchestration_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        json.dumps(
            _to_json_safe(build_orchestration_summary(state)),
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary_path


def finalize_orchestration_state(
    state: MigrationState,
    *,
    summary_writer=write_orchestration_summary,
) -> MigrationState:
    result = dict(state)
    summary_path = Path(str(result.get("orchestration_dir", ""))) / "orchestration_summary.json"
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    artifact_refs["orchestration_summary"] = str(summary_path)
    result["artifact_refs"] = artifact_refs

    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**result["artifact_refs"], **timing_refs}
    result = _normalize_completed_sandbox_state(result)  # type: ignore[assignment]
    result = _enrich_failure_artifact_refs(result)  # type: ignore[assignment]

    if not _is_successful_full_sandbox_migration(result):  # type: ignore[arg-type]
        result["orchestration_artifacts_valid"] = False
        if _is_reportable_failed_sandbox_migration(result):  # type: ignore[arg-type]
            result = _generate_remediation_plan_for_failure(result)  # type: ignore[assignment]
            result = _generate_api_contract_review_for_failure(result)  # type: ignore[assignment]
            result = _generate_behavioral_context_pack_for_failure(result)  # type: ignore[assignment]
            result = _generate_legacy_equivalence_report_for_failure(result)  # type: ignore[assignment]
            result = _generate_test_context_repair_proposal_for_failure(result)  # type: ignore[assignment]
            result = _generate_legacy_guided_patch_proposal_for_failure(result)  # type: ignore[assignment]
            result = _generate_mockito_bean_placement_report_for_failure(result)  # type: ignore[assignment]
            result = _generate_behavioral_remediation_strategy_for_failure(result)  # type: ignore[assignment]
            summary_writer(result)  # type: ignore[arg-type]
            final_report_started = time.monotonic()
            final_report = generate_final_migration_report(result)
            record_phase_duration(result, phase="final_report", duration_seconds=time.monotonic() - final_report_started)
            timing_refs = write_timing_artifacts(result)
            result["artifact_refs"] = {**dict(result.get("artifact_refs", {}) or {}), **timing_refs}
            if final_report.blockers:
                result["blockers"] = [
                    *list(result.get("blockers", []) or []),
                    *final_report.blockers,
                ]
            if final_report.warnings:
                result["warnings"] = [
                    *list(result.get("warnings", []) or []),
                    *final_report.warnings,
                ]
            if final_report.artifact_refs:
                result["artifact_refs"] = {
                    **dict(result.get("artifact_refs", {}) or {}),
                    **final_report.artifact_refs,
                }
            result = _enrich_failure_artifact_refs(result)  # type: ignore[assignment]
            summary_writer(result)  # type: ignore[arg-type]
            return result  # type: ignore[return-value]
        summary_writer(result)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]

    summary_writer(result)  # type: ignore[arg-type]
    result = _run_consumer_compatibility_validation_if_applicable(result)  # type: ignore[assignment]
    final_report_started = time.monotonic()
    final_report = generate_final_migration_report(result)
    record_phase_duration(result, phase="final_report", duration_seconds=time.monotonic() - final_report_started)
    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**dict(result.get("artifact_refs", {}) or {}), **timing_refs}
    if final_report.blockers:
        result["blockers"] = [
            *list(result.get("blockers", []) or []),
            *final_report.blockers,
        ]
        result["orchestration_status"] = "FAIL"
        result["final_status"] = "FAILED"
        result["orchestration_artifacts_valid"] = False
        summary_writer(result)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]
    if final_report.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *final_report.warnings,
        ]
    artifact_refs = {
        **dict(result.get("artifact_refs", {}) or {}),
        **final_report.artifact_refs,
    }
    result["artifact_refs"] = artifact_refs

    copilot_report = _generate_optional_copilot_final_report(result)
    if copilot_report["warnings"]:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *copilot_report["warnings"],
        ]
    if copilot_report["artifact_refs"]:
        result["artifact_refs"] = {
            **dict(result.get("artifact_refs", {}) or {}),
            **copilot_report["artifact_refs"],
        }

    copilot_docs_started = time.monotonic()
    copilot_docs = generate_copilot_documentation_package(result)
    record_phase_duration(
        result,
        phase="copilot_documentation",
        duration_seconds=time.monotonic() - copilot_docs_started,
    )
    if copilot_docs.blockers:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *[
                f"copilot documentation generation skipped: {blocker}"
                for blocker in copilot_docs.blockers
            ],
        ]
    if copilot_docs.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *copilot_docs.warnings,
        ]
    result["artifact_refs"] = {
        **dict(result.get("artifact_refs", {}) or {}),
        **copilot_docs.artifact_refs,
    }
    timing_refs = write_timing_artifacts(result)
    result["artifact_refs"] = {**dict(result.get("artifact_refs", {}) or {}), **timing_refs}
    summary_writer(result)  # type: ignore[arg-type]
    validation = validate_successful_full_sandbox_orchestration(result)  # type: ignore[arg-type]
    result["orchestration_artifacts_valid"] = validation.valid
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    result["artifact_refs"] = {
        **artifact_refs,
        **validation.artifact_refs,
    }
    if validation.blockers:
        result["blockers"] = [
            *list(result.get("blockers", []) or []),
            *validation.blockers,
        ]
    if validation.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *validation.warnings,
        ]
    summary_writer(result)  # type: ignore[arg-type]
    return result  # type: ignore[return-value]


def _generate_optional_copilot_final_report(state: dict[str, Any]) -> dict[str, Any]:
    if not _copilot_report_enabled():
        return {"artifact_refs": {}, "warnings": []}

    run_dir = Path(str(state.get("run_dir") or ""))
    ai_hub_path = _resolve_ai_hub_path(state)
    context = {
        "application_name": state.get("application_name", ""),
        "profile_id": state.get("profile_id", ""),
        "mode": state.get("mode", ""),
        "legacy_app_path": state.get("legacy_app_path", ""),
        "sandbox_path": state.get("sandbox_path", ""),
        "final_verdict": state.get("final_status", ""),
        "orchestration_status": state.get("orchestration_status", ""),
        "preflight_status": state.get("preflight_status", ""),
        "analysis_status": state.get("analysis_status", ""),
        "planning_status": state.get("planning_status", ""),
        "assessment_status": state.get("assessment_status", ""),
        "final_conclusion": "Deterministic factory artifacts remain the source of truth.",
        "recommended_next_step": "manual review",
    }
    try:
        copilot_status = (
            detect_copilot_cli_status(timeout_seconds=15.0)
            if os.getenv("AI_MIGRATION_COPILOT_PROVIDER", "").strip().lower() == "copilot_cli"
            else CopilotAdapterStatus(
                model=os.getenv("AI_MIGRATION_COPILOT_MODEL", "").strip() or "gpt-5-mini",
                connectivity="not_configured",
                report_status="generated",
            )
        )
        return generate_copilot_report(
            run_dir,
            ai_hub_path,
            context=context,
            status=copilot_status,
        )
    except ValueError as exc:
        warning = f"copilot final report skipped: {exc}"
        try:
            response = write_failed_copilot_report_response(
                run_dir,
                ai_hub_path,
                warning=warning,
                report_status="skipped",
            )
        except Exception:
            return {"artifact_refs": {}, "warnings": [warning]}
        return {
            "artifact_refs": response.get("artifact_refs", {}),
            "warnings": [warning],
        }
    except Exception as exc:  # pragma: no cover - defensive safety net
        warning = f"copilot final report failed: {exc}"
        try:
            response = write_failed_copilot_report_response(
                run_dir,
                ai_hub_path,
                warning=warning,
            )
        except Exception:
            return {"artifact_refs": {}, "warnings": [warning]}
        return {
            "artifact_refs": response.get("artifact_refs", {}),
            "warnings": [warning],
        }


def _copilot_report_enabled() -> bool:
    return os.getenv(_COPILOT_REPORT_ENV, "").strip().lower() in _TRUE_VALUES


def _resolve_ai_hub_path(state: dict[str, Any]) -> Path:
    configured = Path(str(state.get("ai_hub_path") or ""))
    if configured and (configured / "templates" / "reports" / "copilot_final_migration_report_v1.yaml").is_file():
        return configured
    return Path(__file__).resolve().parents[2] / "modernizer-solution-ai-hub"


def _final_status(state: MigrationState) -> str:
    if state.get("final_status"):
        return str(state.get("final_status"))
    if state.get("approval_status") == "FAILED":
        return "FAILED"
    if state.get("errors") or state.get("blockers"):
        return "FAILED"
    if any(
        state.get(status_key) == "FAIL"
        for status_key in ("analysis_status", "planning_status", "assessment_status")
    ):
        return "FAILED"
    if state.get("approval_status") == "INTERRUPTED":
        return "INTERRUPTED"
    if state.get("approval_status") == "COMPLETED":
        return "COMPLETED"
    return "COMPLETED"


def _is_successful_full_sandbox_migration(state: MigrationState) -> bool:
    accepted_test_statuses = {"TEST_PASSED", "NO_TESTS_FOUND", "NO_TESTS_EXECUTED"}
    accepted_final_statuses = {
        "TRANSFORM_APPLIED_IN_SANDBOX",
        "SANDBOX_MIGRATION_COMPLETED",
        "SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS",
    }
    return (
        state.get("mode") == FULL_SANDBOX_MIGRATION_MODE
        and state.get("approval_status") == "COMPLETED"
        and state.get("approval_decision") == "approved"
        and state.get("orchestration_status") == "PASS"
        and state.get("transform_status") == "TRANSFORM_APPLIED_IN_SANDBOX"
        and state.get("build_status") == "BUILD_PASSED_IN_SANDBOX"
        and state.get("test_status") in accepted_test_statuses
        and _final_status(state) in accepted_final_statuses
    )


def _is_reportable_failed_sandbox_migration(state: MigrationState) -> bool:
    return (
        state.get("mode") == FULL_SANDBOX_MIGRATION_MODE
        and state.get("approval_status") == "COMPLETED"
        and state.get("approval_decision") == "approved"
        and state.get("orchestration_status") == "FAIL"
        and any(
            str(state.get(key) or "")
            for key in ("transform_status", "build_status", "test_status")
        )
    )


def _execution_claims(state: MigrationState) -> dict[str, bool]:
    claims = dict(EXECUTION_CLAIMS)
    if state.get("transform_status") == "TRANSFORM_APPLIED_IN_SANDBOX":
        claims["transformation_executed"] = True
        claims["openrewrite_apply_executed"] = True
    if state.get("build_status") == "BUILD_PASSED_IN_SANDBOX":
        claims["migrated_build_executed"] = True
    if state.get("test_status") == "TEST_PASSED":
        claims["migrated_tests_executed"] = True
    claims["sandbox_migration_executed"] = claims["transformation_executed"] and claims["migrated_build_executed"]
    claims["production_promotion_executed"] = False
    claims["final_migration_executed"] = claims["sandbox_migration_executed"]
    return claims


def _enrich_failure_artifact_refs(state: MigrationState) -> MigrationState:
    result = dict(state)
    run_dir = Path(str(result.get("run_dir") or ""))
    if not run_dir:
        return result  # type: ignore[return-value]
    build_dir = run_dir / "build"
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    build_error_contract = artifact_refs.get("build_error_contract")
    if not build_error_contract:
        latest = _latest_build_error_contract(build_dir)
        if latest is not None:
            artifact_refs["build_error_contract"] = str(latest)
            build_error_contract = str(latest)
    if build_error_contract and not artifact_refs.get("post_transform_failure_classification"):
        classification = _failure_classification_ref(Path(str(build_error_contract)))
        if classification:
            artifact_refs["post_transform_failure_classification"] = classification
    result["artifact_refs"] = artifact_refs
    return result  # type: ignore[return-value]


def _generate_remediation_plan_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    llm_policy = load_llm_policy(result.get("ai_hub_path"), result.get("profile_id"))
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_plan = Path(str(artifact_refs.get("remediation_plan") or "")).expanduser()
    if str(artifact_refs.get("remediation_plan") or "").strip() and existing_plan.is_file():
        result["artifact_refs"] = artifact_refs
        return result  # type: ignore[return-value]
    build_error_contract = _read_optional_json(artifact_refs.get("build_error_contract"))
    failure_classification = _read_optional_json(artifact_refs.get("post_transform_failure_classification"))
    remediation_path = build_remediation_plan(
        state=result,
        output_dir=Path(str(result.get("run_dir") or "")) / "remediation",
        llm_policy=llm_policy,
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    )
    artifact_refs["remediation_plan"] = str(remediation_path)
    result["artifact_refs"] = artifact_refs
    return result  # type: ignore[return-value]


def _generate_api_contract_review_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_review = Path(str(artifact_refs.get("api_contract_review") or "")).expanduser()
    if str(artifact_refs.get("api_contract_review") or "").strip() and existing_review.is_file():
        return result  # type: ignore[return-value]
    run_dir = Path(str(result.get("run_dir") or ""))
    if not run_dir:
        return result  # type: ignore[return-value]
    review = build_api_contract_review(
        run_dir=run_dir,
        sandbox_path=Path(str(result.get("sandbox_path") or "")) if str(result.get("sandbox_path") or "").strip() else None,
        build_error_contract=_read_optional_json(artifact_refs.get("build_error_contract")),
        failure_classification=_read_optional_json(artifact_refs.get("post_transform_failure_classification")),
        orchestration_summary=build_orchestration_summary(result),
    )
    artifact_refs["api_contract_review"] = str(review.artifact_path)
    result["artifact_refs"] = artifact_refs
    if review.detected and review.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            review.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_behavioral_context_pack_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_context = Path(str(artifact_refs.get("behavioral_failure_context_pack") or "")).expanduser()
    existing_gate = Path(str(artifact_refs.get("llm_proposal_gate") or "")).expanduser()
    if (
        str(artifact_refs.get("behavioral_failure_context_pack") or "").strip()
        and existing_context.is_file()
        and str(artifact_refs.get("llm_proposal_gate") or "").strip()
        and existing_gate.is_file()
    ):
        return result  # type: ignore[return-value]
    build_error_contract = _read_optional_json(artifact_refs.get("build_error_contract"))
    failure_classification = _read_optional_json(artifact_refs.get("post_transform_failure_classification"))
    if not should_generate_behavioral_context(
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    ):
        return result  # type: ignore[return-value]
    llm_policy = load_llm_policy(result.get("ai_hub_path"), result.get("profile_id"))
    context = generate_behavioral_failure_context_pack(
        run_dir=Path(str(result.get("run_dir") or "")),
        failed_unit=str(result.get("current_unit") or result.get("current_phase") or ""),
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
        sandbox_project_path=result.get("sandbox_path"),
        llm_policy=llm_policy,
        orchestration_summary=build_orchestration_summary(result),
    )
    artifact_refs["behavioral_failure_context_pack"] = str(context.context_pack_path)
    artifact_refs["behavioral_failure_context_summary"] = str(context.summary_path)
    artifact_refs["llm_proposal_gate"] = str(context.llm_gate_path)
    result["artifact_refs"] = artifact_refs
    if context.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            context.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_legacy_equivalence_report_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("legacy_behavior_equivalence_report") or "")).expanduser()
    if str(artifact_refs.get("legacy_behavior_equivalence_report") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    run_dir = Path(str(result.get("run_dir") or ""))
    legacy_path = str(result.get("legacy_app_path") or "").strip()
    sandbox_path = str(result.get("sandbox_path") or "").strip()
    if not run_dir or not legacy_path or not sandbox_path:
        return result  # type: ignore[return-value]
    build_error_contract = _read_optional_json(artifact_refs.get("build_error_contract"))
    behavioral_context = _read_optional_json(artifact_refs.get("behavioral_failure_context_pack"))
    has_missing_bean = bool((behavioral_context or {}).get("missing_bean_type_errors"))
    if not has_missing_bean:
        message = " ".join(
            str((build_error_contract or {}).get(key) or "")
            for key in ("matched_line", "message")
        )
        has_missing_bean = "No qualifying bean of type" in message or "NoSuchBeanDefinitionException" in message
    if not has_missing_bean:
        return result  # type: ignore[return-value]
    equivalence = generate_legacy_behavior_equivalence_report(
        run_dir=run_dir,
        legacy_project_path=legacy_path,
        sandbox_project_path=sandbox_path,
        behavioral_context_pack=behavioral_context,
        build_error_contract=build_error_contract,
        orchestration_summary=build_orchestration_summary(result),
    )
    artifact_refs["legacy_behavior_equivalence_report"] = str(equivalence.report_path)
    artifact_refs["legacy_behavior_equivalence_summary"] = str(equivalence.summary_path)
    result["artifact_refs"] = artifact_refs
    if equivalence.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            equivalence.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_test_context_repair_proposal_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("test_context_repair_proposal") or "")).expanduser()
    if str(artifact_refs.get("test_context_repair_proposal") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    legacy_equivalence_ref = str(artifact_refs.get("legacy_behavior_equivalence_report") or "").strip()
    behavioral_context_ref = str(artifact_refs.get("behavioral_failure_context_pack") or "").strip()
    sandbox_path = str(result.get("sandbox_path") or "").strip()
    run_dir = Path(str(result.get("run_dir") or ""))
    if not legacy_equivalence_ref or not behavioral_context_ref or not sandbox_path or not run_dir:
        return result  # type: ignore[return-value]
    proposal = generate_test_context_repair_proposal(
        run_dir=run_dir,
        legacy_behavior_equivalence_report_path=legacy_equivalence_ref,
        behavioral_failure_context_pack_path=behavioral_context_ref,
        sandbox_project_path=sandbox_path,
    )
    artifact_refs["test_context_repair_proposal"] = str(proposal.report_path)
    artifact_refs["test_context_repair_proposal_summary"] = str(proposal.summary_path)
    if proposal.patch_path:
        artifact_refs["test_context_repair_proposal_patch"] = str(proposal.patch_path)
    result["artifact_refs"] = artifact_refs
    if proposal.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            proposal.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_legacy_guided_patch_proposal_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("legacy_guided_patch_proposal") or "")).expanduser()
    if str(artifact_refs.get("legacy_guided_patch_proposal") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    run_dir = Path(str(result.get("run_dir") or ""))
    sandbox_path = str(result.get("sandbox_path") or "").strip()
    legacy_path = str(result.get("legacy_app_path") or "").strip()
    equivalence_ref = str(artifact_refs.get("legacy_behavior_equivalence_report") or "").strip()
    repair_ref = str(artifact_refs.get("test_context_repair_proposal") or "").strip()
    behavioral_ref = str(artifact_refs.get("behavioral_failure_context_pack") or "").strip()
    if not run_dir or not sandbox_path or not legacy_path or not equivalence_ref or not repair_ref or not behavioral_ref:
        return result  # type: ignore[return-value]
    proposal = generate_legacy_guided_patch_proposal(
        run_dir=run_dir,
        sandbox_project_path=sandbox_path,
        legacy_project_path=legacy_path,
        legacy_behavior_equivalence_report_path=equivalence_ref,
        test_context_repair_proposal_path=repair_ref,
        behavioral_failure_context_pack_path=behavioral_ref,
    )
    artifact_refs["legacy_guided_patch_proposal"] = str(proposal.report_path)
    artifact_refs["legacy_guided_patch_proposal_summary"] = str(proposal.summary_path)
    if proposal.patch_path:
        artifact_refs["legacy_guided_patch_proposal_patch"] = str(proposal.patch_path)
    result["artifact_refs"] = artifact_refs
    if proposal.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            proposal.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_mockito_bean_placement_report_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("mockito_bean_placement_report") or "")).expanduser()
    if str(artifact_refs.get("mockito_bean_placement_report") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    run_dir = Path(str(result.get("run_dir") or ""))
    sandbox_path = str(result.get("sandbox_path") or "").strip()
    legacy_path = str(result.get("legacy_app_path") or "").strip()
    equivalence_ref = str(artifact_refs.get("legacy_behavior_equivalence_report") or "").strip()
    repair_ref = str(artifact_refs.get("test_context_repair_proposal") or "").strip()
    guided_ref = str(artifact_refs.get("legacy_guided_patch_proposal") or "").strip()
    behavioral_ref = str(artifact_refs.get("behavioral_failure_context_pack") or "").strip()
    if not run_dir or not sandbox_path or not legacy_path or not equivalence_ref or not repair_ref or not guided_ref or not behavioral_ref:
        return result  # type: ignore[return-value]
    report = generate_mockito_bean_placement_report(
        run_dir=run_dir,
        sandbox_project_path=sandbox_path,
        legacy_project_path=legacy_path,
        legacy_behavior_equivalence_report_path=equivalence_ref,
        test_context_repair_proposal_path=repair_ref,
        legacy_guided_patch_proposal_path=guided_ref,
        behavioral_failure_context_pack_path=behavioral_ref,
    )
    artifact_refs["mockito_bean_placement_report"] = str(report.report_path)
    artifact_refs["mockito_bean_placement_summary"] = str(report.summary_path)
    if report.patch_path:
        artifact_refs["mockito_bean_placement_patch_proposal"] = str(report.patch_path)
    result["artifact_refs"] = artifact_refs
    if report.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            report.warning,
        ]
    return result  # type: ignore[return-value]


def _generate_behavioral_remediation_strategy_for_failure(state: MigrationState) -> MigrationState:
    result = _enrich_failure_artifact_refs(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("behavioral_remediation_strategy") or "")).expanduser()
    if str(artifact_refs.get("behavioral_remediation_strategy") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    run_dir = Path(str(result.get("run_dir") or ""))
    behavioral_ref = str(artifact_refs.get("behavioral_failure_context_pack") or "").strip()
    equivalence_ref = str(artifact_refs.get("legacy_behavior_equivalence_report") or "").strip()
    repair_ref = str(artifact_refs.get("test_context_repair_proposal") or "").strip()
    guided_ref = str(artifact_refs.get("legacy_guided_patch_proposal") or "").strip()
    mockito_ref = str(artifact_refs.get("mockito_bean_placement_report") or "").strip()
    if not run_dir or not behavioral_ref or not equivalence_ref or not repair_ref or not guided_ref or not mockito_ref:
        return result  # type: ignore[return-value]
    strategy = generate_behavioral_remediation_strategy(
        run_dir=run_dir,
        behavioral_failure_context_pack_path=behavioral_ref,
        legacy_behavior_equivalence_report_path=equivalence_ref,
        test_context_repair_proposal_path=repair_ref,
        legacy_guided_patch_proposal_path=guided_ref,
        mockito_bean_placement_report_path=mockito_ref,
        approved_patch_apply_result_path=artifact_refs.get("approved_patch_apply_result"),
        remediation_attempts_path=artifact_refs.get("remediation_attempts"),
        orchestration_summary=build_orchestration_summary(result),
        llm_policy=load_llm_policy(result.get("ai_hub_path"), result.get("profile_id")),
    )
    artifact_refs["behavioral_remediation_strategy"] = str(strategy.report_path)
    artifact_refs["behavioral_remediation_strategy_summary"] = str(strategy.summary_path)
    result["artifact_refs"] = artifact_refs
    if strategy.warning:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            strategy.warning,
        ]
    return result  # type: ignore[return-value]


def _run_consumer_compatibility_validation_if_applicable(state: MigrationState) -> MigrationState:
    result = dict(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    existing_report = Path(str(artifact_refs.get("consumer_compatibility_report") or "")).expanduser()
    if str(artifact_refs.get("consumer_compatibility_report") or "").strip() and existing_report.is_file():
        return result  # type: ignore[return-value]
    sandbox_path = str(result.get("sandbox_path") or "").strip()
    run_dir = str(result.get("run_dir") or "").strip()
    if not sandbox_path or not run_dir:
        return result  # type: ignore[return-value]
    assessment_report = _read_optional_json(artifact_refs.get("assessment_report")) or _read_optional_json(
        Path(str(result.get("assessment_dir") or "")) / "assessment_report.json"
    )
    analysis_report = _read_optional_json(artifact_refs.get("analysis_report")) or _read_optional_json(
        Path(str(result.get("analysis_dir") or "")) / "analysis_report.json"
    )
    project_kind = str(
        (assessment_report or {}).get("project_kind")
        or (analysis_report or {}).get("project_kind")
        or ""
    )
    validation = run_consumer_compatibility_validation(
        run_id=str(result.get("run_id") or ""),
        migrated_project_path=Path(sandbox_path),
        output_dir=Path(run_dir) / "validation",
        config=dict(result.get("consumer_validation") or {}),
        project_kind=project_kind or None,
    )
    artifact_refs["consumer_compatibility_report"] = str(validation.report_path)
    artifact_refs["consumer_compatibility_summary"] = str(validation.summary_path)
    result["artifact_refs"] = artifact_refs
    if validation.warnings:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            *validation.warnings,
        ]
    if validation.status == "FAILED":
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            "Consumer compatibility validation failed; downstream review required before production promotion.",
        ]
    elif validation.status == "NOT_CONFIGURED" and project_kind in LIBRARY_PROJECT_KINDS:
        result["warnings"] = [
            *list(result.get("warnings", []) or []),
            "Consumer compatibility validation not configured for library migration; downstream confidence remains limited.",
        ]
    return result  # type: ignore[return-value]


def _latest_build_error_contract(build_dir: Path) -> Path | None:
    candidates = sorted(build_dir.glob("build-error-*.json"))
    if not candidates:
        return None
    return candidates[-1]


def _failure_classification_ref(build_error_contract: Path) -> str:
    try:
        payload = json.loads(build_error_contract.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    ref = str(payload.get("failure_classification_path") or "").strip()
    if not ref:
        return ""
    return ref


def _read_optional_json(path_like: Any) -> dict[str, Any] | None:
    path_text = str(path_like or "").strip()
    if not path_text:
        return None
    try:
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_completed_sandbox_state(state: MigrationState) -> MigrationState:
    result = dict(state)
    if result.get("mode") != FULL_SANDBOX_MIGRATION_MODE:
        return result  # type: ignore[return-value]
    if result.get("approval_status") != "COMPLETED" or result.get("approval_decision") != "approved":
        return result  # type: ignore[return-value]
    if result.get("orchestration_status") != "PASS":
        return result  # type: ignore[return-value]
    if result.get("transform_status") != "TRANSFORM_APPLIED_IN_SANDBOX":
        return result  # type: ignore[return-value]
    if result.get("build_status") != "BUILD_PASSED_IN_SANDBOX":
        return result  # type: ignore[return-value]
    test_status = str(result.get("test_status") or "")
    if test_status == "TEST_PASSED":
        result["final_status"] = "SANDBOX_MIGRATION_COMPLETED"
        result["stop_reason"] = result.get("stop_reason") or "Sandbox migration completed."
    elif test_status in {"NO_TESTS_FOUND", "NO_TESTS_EXECUTED"}:
        result["final_status"] = "SANDBOX_MIGRATION_COMPLETED_WITH_WARNINGS"
        result["stop_reason"] = result.get("stop_reason") or "Sandbox migration completed with warnings."
    return result  # type: ignore[return-value]


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
