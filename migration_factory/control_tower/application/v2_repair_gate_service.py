"""F15 V2 Repair Gate Service — repair_review gate creation, actions, and transitions.

Coordinates repair_review gate lifecycle:
  1. On build/test/transform failure → create repair_review gate with diagnosis binding.
  2. On repair_review gate action → approve/reject/revise via V2GateActionService.
  3. On repair validation result → route to stage_completion_review or new repair gate.
  4. Track attempt limits at gate layer.

Reuses:
  - V2PhaseGateService for gate creation/resolution
  - V2GateActionService for gate action execution
  - V2FailureDiagnosisService for diagnosis
  - V2RepairFlowService for proposal/patch flow
  - EvidencePackBuilder for failure evidence
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.v2_failure_diagnosis import (
    V2FailureDiagnosisService,
    FailureDiagnosisRecord,
)
from migration_factory.control_tower.application.v2_gate_action_service import (
    V2GateActionService,
    GateActionResult,
)
from migration_factory.control_tower.application.v2_phase_gate_service import (
    CreateGateRequest,
    V2PhaseGateService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    sha256_hex,
    utc_now_text,
)
from migration_factory.control_tower.domain.entities import ArtifactRevisionRecord
from migration_factory.control_tower.infrastructure.sqlite.v2_artifact_revision_repository import (
    SqliteArtifactRevisionRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    SqliteV2LLMInvocationRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_reviewer_repository import (
    SqliteV2ReviewerRepository,
    V2ReviewerCritiqueRecord,
)
from migration_factory.control_tower.schemas.phase_gate import GateDecision
from migration_factory.repair_loop.failure_evidence import (
    FailureEvidence,
    FailureSource,
    NormalizedCompilerError,
    NormalizedTestFailure,
)
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal
from migration_factory.repair_loop.patch_apply import validate_unified_diff_structure
from migration_factory.repair_loop.repair_context import RepairContextPack


# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_MAX_REPAIR_ATTEMPTS = 3


# ── Result types ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RepairGateCreationResult:
    """Result of creating a repair_review gate after failure."""

    gate_id: str
    gate_checksum: str
    diagnosis: FailureDiagnosisRecord | None
    status: str  # created, conflict, skipped
    existing_gate_id: str | None = None
    reason: str = ""
    revision_id: str = ""
    policy_validation_checksum: str = ""
    policy_status: str = ""


@dataclass(frozen=True)
class RepairValidationTransitionResult:
    """Result of a repair validation transition."""

    status: str  # stage_completion_gate_created, repair_gate_created, attempts_exhausted, no_action
    gate_id: str | None = None
    gate_checksum: str = ""
    remaining_attempts: int = 0
    reason: str = ""


# ── Repair Gate Service ─────────────────────────────────────────────


class V2RepairGateService:
    """Coordinates repair_review gate lifecycle.

    Composes V2PhaseGateService, V2GateActionService, V2RepairFlowService,
    and V2FailureDiagnosisService to implement the F15 repair gate flow.
    """

    def __init__(
        self,
        gate_service: V2PhaseGateService,
        gate_action_service: V2GateActionService | None = None,
        repair_flow: V2RepairFlowService | None = None,
        diagnosis_service: V2FailureDiagnosisService | None = None,
        revision_repo: SqliteArtifactRevisionRepository | None = None,
        repair_repo: SqliteV2RepairRepository | None = None,
        reviewer_repo: SqliteV2ReviewerRepository | None = None,
        llm_invocation_repo: SqliteV2LLMInvocationRepository | None = None,
        event_repo: Any | None = None,
        max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
    ) -> None:
        self._gate_service = gate_service
        self._gate_action_service = gate_action_service
        self._repair_flow = repair_flow
        self._diagnosis_service = diagnosis_service
        self._revision_repo = revision_repo
        self._repair_repo = repair_repo
        self._reviewer_repo = reviewer_repo
        self._llm_invocation_repo = llm_invocation_repo
        self._event_repo = event_repo
        self._max_repair_attempts = max_repair_attempts
        self._chain_attempt_repo = None

        # In-memory attempt tracking: {(job_id, stage_index): attempt_count}
        self._attempt_counts: dict[tuple[str, int], int] = {}
        # Idempotency guard: set of (job_id, stage_index, command_id) already attempted
        self._chain_attempted: set[tuple[str, int, str]] = set()

    def create_reviewed_repair_gate_on_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
        legacy_path: str,
        model_client: Any | None = None,
    ) -> RepairGateCreationResult:
        """Run the Azure reviewed repair chain for the first build/test failure.

        Idempotency guard: (job_id, stage_index, command_id) is tracked to prevent
        duplicate chain attempts from multiple failure notifications (e.g., both
        build_failed and test_failed for the same command).
        """
        chain_key = (job_id, stage_index, command_id)
        if chain_key in self._chain_attempted:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"duplicate repair chain attempt blocked for {command_id}",
            )
        self._chain_attempted.add(chain_key)

        existing_proposal = self._existing_open_repair_proposal(job_id=job_id, command_id=command_id)
        if existing_proposal is not None:
            return RepairGateCreationResult(
                gate_id=str(existing_proposal.gate_id or ""),
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"repair proposal already exists for command {command_id}",
            )

        from migration_factory.control_tower.application.v2_llm_invocation_ledger import (
            V2LLMInvocationLedger,
        )
        from migration_factory.orchestrator.repair_review_chain import (
            RepairReviewChainProductionError,
            produce_repair_review_chain,
        )

        required = (
            "_repair_failure_evidence_ref",
            "_repair_context_pack_ref",
            "_repair_run_dir",
            "_repair_sandbox_path",
            "_repair_failure_evidence_checksum",
            "_repair_context_pack_checksum",
            "_repair_base_repo_state_checksum",
        )
        missing = [key for key in required if not str(payload.get(key) or "").strip()]
        if missing:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"missing reviewed repair context: {', '.join(missing)}",
            )

        try:
            evidence = _failure_evidence_from_json(Path(str(payload["_repair_failure_evidence_ref"])))
            context_pack = _repair_context_from_json(Path(str(payload["_repair_context_pack_ref"])))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"reviewed repair context could not be loaded: {type(exc).__name__}",
            )

        run_dir = str(payload["_repair_run_dir"])
        output_dir = Path(run_dir) / "repair_chain"
        invocation_ledger = (
            V2LLMInvocationLedger(self._llm_invocation_repo)
            if self._llm_invocation_repo is not None
            else None
        )
        sandbox_path_for_chain = str(payload.get("_repair_sandbox_path", "")).strip() or None
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=context_pack.source_profile,
                target_profile=context_pack.target_profile,
                model_client=model_client,
                invocation_ledger=invocation_ledger,
                sandbox_path=sandbox_path_for_chain,
            )
        except Exception as exc:
            schema_diagnostics: dict[str, Any] | None = None
            if isinstance(exc, RepairReviewChainProductionError):
                schema_diagnostics = exc.schema_diagnostics
            reason_code = _reviewed_repair_unavailable_reason(exc)
            if reason_code == "duplicate_main_blocked":
                reason_code = self._prior_main_schema_invalid_reason(
                    job_id=job_id,
                    context_checksum=str(payload["_repair_context_pack_checksum"]),
                ) or reason_code
            self._emit_reviewed_repair_unavailable(
                job_id=job_id,
                stage_index=stage_index,
                context_checksum=str(payload["_repair_context_pack_checksum"]),
                reason_code=reason_code,
                schema_diagnostics=schema_diagnostics,
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"reviewed repair chain failed closed: {type(exc).__name__}",
            )

        primary = _read_json_ref(chain_result["review_chain"].get("primary_output_ref"))
        deterministic_rule_id = str(primary.get("deterministic_rule_id") or "no_safe_rule")
        gate_result = self.create_repair_gate_from_reviewed_chain(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            review_chain_result=chain_result,
            failure_evidence_checksum=str(payload["_repair_failure_evidence_checksum"]),
            context_pack_checksum=str(payload["_repair_context_pack_checksum"]),
            base_repo_state_checksum=str(payload["_repair_base_repo_state_checksum"]),
            sandbox_path=str(payload["_repair_sandbox_path"]),
            run_dir=run_dir,
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            h2_required=_truthy(payload.get("_repair_h2_required")),
        )
        if gate_result.status != "created":
            if not _is_structural_materialization_failure(gate_result.reason):
                self._emit_reviewed_repair_materialization_failed(
                    job_id=job_id,
                    stage_index=stage_index,
                    context_checksum=str(payload["_repair_context_pack_checksum"]),
                    reason_code=_materialization_reason_code(gate_result.reason),
                    chain=chain_result.get("review_chain"),
                    detail=gate_result.reason or "",
                )
            return gate_result
        try:
            proposal_id = self._persist_reviewed_repair_proposal(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                event_type=event_type,
                failure_evidence=evidence,
                context_pack=context_pack,
                chain_result=chain_result,
                gate_id=gate_result.gate_id,
                policy_validation_checksum=gate_result.policy_validation_checksum,
                failure_evidence_ref=str(payload["_repair_failure_evidence_ref"]),
                repair_context_ref=str(payload["_repair_context_pack_ref"]),
            )
        except Exception as exc:
            self._emit_reviewed_repair_materialization_failed(
                job_id=job_id,
                stage_index=stage_index,
                context_checksum=str(payload["_repair_context_pack_checksum"]),
                reason_code="proposal_persistence_failed",
                chain=chain_result.get("review_chain"),
                detail=str(type(exc).__name__),
            )
            return RepairGateCreationResult(
                gate_id=gate_result.gate_id,
                gate_checksum=gate_result.gate_checksum,
                diagnosis=None,
                status="skipped",
                reason=f"reviewed repair proposal persistence failed: {type(exc).__name__}",
                policy_validation_checksum=gate_result.policy_validation_checksum,
            )
        try:
            self._bind_llm_invocations(
                chain=chain_result["review_chain"],
                proposal_id=proposal_id,
                gate_id=gate_result.gate_id,
            )
        except Exception as exc:
            self._emit_reviewed_repair_materialization_failed(
                job_id=job_id,
                stage_index=stage_index,
                context_checksum=str(payload["_repair_context_pack_checksum"]),
                reason_code="llm_binding_failed",
                chain=chain_result.get("review_chain"),
                detail=str(type(exc).__name__),
            )
            return RepairGateCreationResult(
                gate_id=gate_result.gate_id,
                gate_checksum=gate_result.gate_checksum,
                diagnosis=None,
                status="skipped",
                reason=f"reviewed repair LLM binding failed: {type(exc).__name__}",
                policy_validation_checksum=gate_result.policy_validation_checksum,
            )
        self._emit_reviewed_repair_materialized(
            job_id=job_id,
            stage_index=stage_index,
            context_checksum=str(payload["_repair_context_pack_checksum"]),
            gate_id=gate_result.gate_id,
            proposal_id=proposal_id,
            chain=chain_result.get("review_chain"),
            policy_validation_checksum=gate_result.policy_validation_checksum,
            diff_normalized=_normalized_flag(chain_result.get("review_chain")),
        )
        return gate_result

    def _emit_reviewed_repair_unavailable(
        self,
        *,
        job_id: str,
        stage_index: int,
        context_checksum: str,
        reason_code: str,
        invocation_id: str | None = None,
        schema_diagnostics: dict[str, Any] | None = None,
    ) -> None:
        if self._event_repo is None:
            return
        main_invocation_id = invocation_id or ""
        reviewer_invocation_id = ""
        main_schema_failure = reason_code in {"main_schema_invalid", "proposer_schema_invalid"}
        if self._llm_invocation_repo is not None:
            for record in self._llm_invocation_repo.list_by_job(job_id):
                if context_checksum and str(getattr(record, "context_checksum", "") or "") != context_checksum:
                    continue
                responsibility = str(getattr(record, "responsibility", "") or "")
                if not main_invocation_id and responsibility == "repair_proposal":
                    main_invocation_id = str(record.invocation_id)
                if not main_schema_failure and not reviewer_invocation_id and responsibility == "repair_review":
                    reviewer_invocation_id = str(record.invocation_id)

        event_type = "reviewed_repair_unavailable"
        if main_schema_failure:
            event_type = "repair_primary_schema_invalid"

        message = (
            "Reviewer model output failed schema validation."
            if reason_code == "reviewer_schema_invalid"
            else "No independent reviewer completed, so no reviewed diff was materialized."
        )
        schema_name = "RepairPrimaryOutput"
        if schema_diagnostics and str(schema_diagnostics.get("schema_name") or "").strip():
            schema_name = str(schema_diagnostics.get("schema_name") or "").strip()
        payload: dict[str, Any] = {
            "job_id": job_id,
            "stage_index": stage_index,
            "context_checksum": context_checksum,
            "main_invocation_id": main_invocation_id,
            "reviewer_invocation_id": reviewer_invocation_id,
            "reason_code": reason_code,
            "schema_name": schema_name,
            "message": message,
        }
        if schema_diagnostics:
            for key in ("role", "stage"):
                value = str(schema_diagnostics.get(key) or "").strip()
                if value:
                    payload[key] = value
        if schema_diagnostics:
            safe_diag = {
                k: v for k, v in schema_diagnostics.items()
                if k in (
                    "parse_failure_category", "missing_fields", "wrong_field_types",
                    "wrong_field_names", "invalid_fields", "extra_fields",
                    "has_proposed_diff", "proposed_diff_parse_status",
                    "output_checksum", "response_format_requested",
                    "response_format_used", "deployment_alias_hash", "reason_code",
                    "schema_name",
                )
            }
            payload["schema_diagnostics"] = safe_diag

        self._event_repo.save(
            job_id=job_id,
            stage=stage_index,
            event_type=event_type,
            status="blocked",
            message=message,
            payload=payload,
        )

    def _prior_main_schema_invalid_reason(self, *, job_id: str, context_checksum: str) -> str | None:
        if self._llm_invocation_repo is not None:
            for record in self._llm_invocation_repo.list_by_job(job_id):
                if context_checksum and str(getattr(record, "context_checksum", "") or "") != context_checksum:
                    continue
                responsibility = str(getattr(record, "responsibility", "") or "")
                if responsibility != "repair_proposal":
                    continue
                combined = " ".join(
                    str(value or "").lower()
                    for value in (
                        getattr(record, "status", ""),
                        getattr(record, "redacted_error", ""),
                        getattr(record, "redacted_summary", ""),
                    )
                )
                if "schema_invalid" in combined or "schema validation" in combined:
                    return "proposer_schema_invalid"

        list_by_job = getattr(self._event_repo, "list_by_job", None)
        if callable(list_by_job):
            try:
                events = list_by_job(job_id)
            except Exception:
                events = ()
            for event in events:
                event_type = str(getattr(event, "event_type", "") or "")
                payload = getattr(event, "payload", {}) or {}
                if not isinstance(payload, dict):
                    continue
                if context_checksum and str(payload.get("context_checksum") or "") != context_checksum:
                    continue
                reason = str(payload.get("reason_code") or "").lower()
                if event_type == "repair_primary_schema_invalid" or reason in {"main_schema_invalid", "proposer_schema_invalid"}:
                    return "proposer_schema_invalid"
        return None

    def _emit_reviewed_repair_materialization_failed(
        self,
        *,
        job_id: str,
        stage_index: int,
        context_checksum: str,
        reason_code: str,
        chain: dict[str, Any] | None = None,
        detail: str = "",
        policy_result: Any = None,
    ) -> None:
        if self._event_repo is None:
            return
        chain = chain or {}
        main_invocation_id = str(chain.get("proposer_invocation_id") or "")
        reviewer_invocation_id = str(chain.get("reviewer_invocation_id") or "")
        if not main_invocation_id and self._llm_invocation_repo is not None:
            for record in self._llm_invocation_repo.list_by_job(job_id):
                responsibility = str(getattr(record, "responsibility", "") or "")
                if not main_invocation_id and responsibility == "repair_proposal":
                    main_invocation_id = str(record.invocation_id)
                if not reviewer_invocation_id and responsibility == "repair_review":
                    reviewer_invocation_id = str(record.invocation_id)

        reason_code = _materialization_reason_code(reason_code)
        struct_issue = _extract_struct_issue(detail)
        policy_reason_code = ""
        changed_files: list[str] = []
        proposed_diff_checksum = str(chain.get("proposed_diff_checksum") or "")
        reviewed_diff_checksum = proposed_diff_checksum
        final_diff_checksum = ""
        final_diff_exists = False
        final_diff_ref = str(chain.get("final_diff_ref") or "")
        if final_diff_ref:
            try:
                final_diff_path = Path(final_diff_ref)
                final_diff_exists = final_diff_path.is_file()
                if final_diff_exists:
                    final_diff_checksum = sha256_hex(final_diff_path.read_bytes())
            except OSError:
                final_diff_exists = False
        if policy_result is not None:
            policy_reason_code = str(getattr(policy_result, "reason_code", "") or "")
            changed_files = list(getattr(policy_result, "touched_paths", ()))

        if reason_code == "MALFORMED_DIFF":
            fallback_message = "Reviewed repair diff failed structural validation before user approval."
        elif reason_code == "PATCH_POLICY_REJECTED":
            fallback_message = "Reviewer accepted, but backend patch policy rejected the reviewed diff."
        else:
            fallback_message = "Backend could not materialize a reviewed diff for user approval."
        message = fallback_message

        payload: dict[str, Any] = {
            "job_id": job_id,
            "stage_index": stage_index,
            "context_checksum": context_checksum,
            "main_invocation_id": main_invocation_id,
            "reviewer_invocation_id": reviewer_invocation_id,
            "reason_code": reason_code,
            "struct_issue": struct_issue,
            "policy_reason_code": policy_reason_code,
            "detail": detail,
            "changed_files": changed_files,
            "proposed_diff_checksum": proposed_diff_checksum,
            "reviewed_diff_checksum": reviewed_diff_checksum,
            "final_diff_checksum": final_diff_checksum,
            "final_diff_exists": final_diff_exists,
            "policy_ran": policy_result is not None,
            "gate_created": False,
            "proposal_created": False,
            "schema_name": "RepairPrimaryOutput",
            "message": message,
            "retry_status": "retry_required" if reason_code == "MALFORMED_DIFF" else "",
        }
        if self._llm_invocation_repo is not None:
            for record in self._llm_invocation_repo.list_by_job(job_id):
                invocation_id = str(getattr(record, "invocation_id", "") or "")
                if invocation_id not in {main_invocation_id, reviewer_invocation_id}:
                    continue
                if not payload.get("provider_alias"):
                    payload["provider_alias"] = str(getattr(record, "provider_alias", "") or "")
                if not payload.get("deployment_alias_hash"):
                    payload["deployment_alias_hash"] = str(getattr(record, "deployment_alias_hash", "") or "")
        self._event_repo.save(
            job_id=job_id,
            stage=stage_index,
            event_type="reviewed_repair_materialization_failed",
            status="failed",
            message=message,
            payload=payload,
        )

    def _emit_reviewed_repair_materialized(
        self,
        *,
        job_id: str,
        stage_index: int,
        context_checksum: str,
        gate_id: str,
        proposal_id: str,
        chain: dict[str, Any] | None = None,
        policy_validation_checksum: str = "",
        diff_normalized: bool = False,
    ) -> None:
        if self._event_repo is None:
            return
        chain = chain or {}
        main_invocation_id = str(chain.get("proposer_invocation_id") or "")
        reviewer_invocation_id = str(chain.get("reviewer_invocation_id") or "")
        payload: dict[str, Any] = {
            "job_id": job_id,
            "stage_index": stage_index,
            "context_checksum": context_checksum,
            "gate_id": gate_id,
            "proposal_id": proposal_id,
            "main_invocation_id": main_invocation_id,
            "reviewer_invocation_id": reviewer_invocation_id,
            "policy_validation_checksum": policy_validation_checksum,
            "diff_normalized": diff_normalized,
            "message": "Reviewed repair diff materialized successfully.",
        }
        self._event_repo.save(
            job_id=job_id,
            stage=stage_index,
            event_type="repair_diff_materialized",
            status="completed",
            message="Reviewed repair diff materialized and passed backend patch policy.",
            payload=payload,
        )

    def _persist_reviewed_repair_proposal(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        failure_evidence: FailureEvidence,
        context_pack: RepairContextPack,
        chain_result: dict[str, Any],
        gate_id: str,
        policy_validation_checksum: str,
        failure_evidence_ref: str,
        repair_context_ref: str,
    ) -> str:
        chain = dict(chain_result.get("review_chain") or {})
        primary = _read_json_ref(chain.get("primary_output_ref"))
        reviewer = _read_json_ref(chain.get("reviewer_output_ref"))
        final_artifact = _read_json_ref(chain.get("final_artifact_ref"))
        final_diff_ref = str(chain.get("final_diff_ref") or "")
        diff_bytes = Path(final_diff_ref).read_bytes()
        public_diff_checksum = sha256_hex(diff_bytes)
        changed_files = tuple(
            str(item)
            for item in primary.get("changed_files", failure_evidence.changed_files)
            if str(item).strip()
        )
        proposal_id = uuid4().hex
        critique_id = uuid4().hex
        proposal_checksum = str(chain.get("final_artifact_checksum") or "")
        reviewer_notes = reviewer.get("notes") if isinstance(reviewer.get("notes"), list) else []
        reasoning = "\n".join(str(note) for note in reviewer_notes if str(note).strip())
        if not reasoning:
            reasoning = "Reviewer accepted the repair proposal."
        policy_concerns = reviewer.get("policy_concerns") if isinstance(reviewer.get("policy_concerns"), list) else []
        risks = reviewer.get("risks") if isinstance(reviewer.get("risks"), list) else []

        if self._repair_repo is not None:
            self._repair_repo.save_proposal(
                V2RepairProposalRecord(
                    proposal_id=proposal_id,
                    command_id=command_id,
                    failure_summary=failure_evidence.failure_summary,
                    hypothesis=str(primary.get("root_cause") or final_artifact.get("root_cause") or ""),
                    patch_summary=str(primary.get("fix_strategy") or final_artifact.get("fix_strategy") or ""),
                    affected_paths_json=json.dumps(list(changed_files), separators=(",", ":")),
                    status="user_review_required",
                    approval_checksum=None,
                    created_at=utc_now_text(),
                    proposal_checksum=proposal_checksum,
                    context_pack_checksum=context_pack.context_pack_checksum,
                    job_id=job_id,
                    route_step_index=stage_index,
                    attempt_number=1,
                    failure_evidence_ref=failure_evidence_ref,
                    repair_context_ref=repair_context_ref,
                    diagnosis_ref=f"{event_type}:{failure_evidence.failure_source.value}",
                    repair_plan_ref=str(chain.get("final_artifact_ref") or ""),
                    diff_ref=final_diff_ref,
                    diff_checksum=public_diff_checksum,
                    safe_diff_preview_ref=Path(final_diff_ref).name,
                    reviewer_verdict_id=critique_id,
                    reviewer_verdict_ref=str(chain.get("reviewer_output_ref") or ""),
                    reviewer_output_checksum=str(chain.get("reviewer_output_checksum") or ""),
                    policy_validation_checksum=policy_validation_checksum,
                    gate_id=gate_id,
                    status_reason="reviewed repair proposal ready for user approval",
                    reviewer_decision=str(chain.get("reviewer_decision") or "accept"),
                )
            )
        if self._reviewer_repo is not None:
            self._reviewer_repo.save_critique(
                V2ReviewerCritiqueRecord(
                    critique_id=critique_id,
                    proposal_id=proposal_id,
                    proposal_type="repair",
                    proposal_checksum=proposal_checksum,
                    context_pack_checksum=context_pack.context_pack_checksum,
                    decision=str(chain.get("reviewer_decision") or "accept"),
                    reasoning=reasoning,
                    missing_evidence_json=json.dumps(
                        list(reviewer.get("missing_evidence") or ()),
                        separators=(",", ":"),
                    ),
                    unsafe_assumptions_json=json.dumps(
                        [str(item) for item in (*risks, *policy_concerns)],
                        separators=(",", ":"),
                    ),
                    model_invocation_id=str(chain.get("reviewer_invocation_id") or "") or None,
                    created_at=utc_now_text(),
                )
            )
        return proposal_id

    def _bind_llm_invocations(
        self,
        *,
        chain: dict[str, Any],
        proposal_id: str,
        gate_id: str,
    ) -> None:
        if self._llm_invocation_repo is None:
            return
        for key in ("proposer_invocation_id", "reviewer_invocation_id"):
            invocation_id = str(chain.get(key) or "")
            if invocation_id:
                self._llm_invocation_repo.update_bindings(
                    invocation_id,
                    proposal_id=proposal_id,
                    gate_id=gate_id,
                )

    def create_repair_gate_from_reviewed_chain(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        review_chain_result: dict[str, Any],
        failure_evidence_checksum: str,
        context_pack_checksum: str,
        base_repo_state_checksum: str,
        sandbox_path: str,
        run_dir: str,
        legacy_path: str,
        deterministic_rule_id: str,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Open a repair_review gate only from an accepted reviewed repair chain."""
        chain = review_chain_result.get("review_chain")
        if not isinstance(chain, dict):
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="missing review_chain metadata",
            )
        if str(chain.get("reviewer_decision") or "") != "accept":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewer did not accept repair chain",
            )

        primary_ref = str(chain.get("primary_output_ref") or "")
        final_diff_ref = str(chain.get("final_diff_ref") or "")
        final_artifact_ref = str(chain.get("final_artifact_ref") or "")
        if not primary_ref or not final_diff_ref or not final_artifact_ref:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewed repair chain missing artifact refs",
            )

        primary = json.loads(open(primary_ref, encoding="utf-8").read())
        reviewed_diff = open(final_diff_ref, encoding="utf-8").read()
        final_diff_bytes = Path(final_diff_ref).read_bytes()
        final_diff_sha256_hex = sha256_hex(final_diff_bytes)

        struct_issue = validate_unified_diff_structure(reviewed_diff)
        if struct_issue is not None:
            self._emit_reviewed_repair_materialization_failed(
                job_id=job_id,
                stage_index=stage_index,
                context_checksum=context_pack_checksum,
                reason_code="MALFORMED_DIFF",
                chain=chain,
                detail=f"Diff structure validation failed: {struct_issue}",
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"Diff structure validation failed: {struct_issue}",
                policy_validation_checksum="",
            )

        policy_result = evaluate_patch_proposal(
            proposal={
                "deterministic_rule_id": deterministic_rule_id,
                "risk": str(primary.get("risk") or "LOW"),
                "requires_human_review": False,
                "unified_diff": reviewed_diff,
            },
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            h2_required=h2_required,
        )
        policy_payload = {
            "status": policy_result.status.lower(),
            "reason": policy_result.reason,
            "rule_id": policy_result.rule_id,
            "risk": policy_result.risk,
            "touched_paths": list(policy_result.touched_paths),
            "human_review_required": policy_result.human_review_required,
            "reason_code": policy_result.reason_code,
        }
        policy_checksum = sha256_canonical_json(policy_payload)
        policy_path = Path(run_dir) / "repairs" / "repair_policy_validation.json"
        policy_path.parent.mkdir(parents=True, exist_ok=True)
        policy_path.write_text(
            json.dumps({**policy_payload, "policy_validation_checksum": policy_checksum}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if policy_result.status not in {"ALLOWED", "HUMAN_REVIEW_REQUIRED"}:
            self._emit_reviewed_repair_materialization_failed(
                job_id=job_id,
                stage_index=stage_index,
                context_checksum=context_pack_checksum,
                reason_code=f"repair policy validation failed: {policy_result.status}",
                chain=chain,
                detail=policy_result.reason,
                policy_result=policy_result,
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason=f"repair policy validation failed: {policy_result.status}",
                policy_validation_checksum=policy_checksum,
            )

        required_binding = {
            "failure_evidence_checksum": failure_evidence_checksum,
            "context_pack_checksum": context_pack_checksum,
            "primary_output_checksum": str(chain.get("primary_output_checksum") or ""),
            "reviewer_output_checksum": str(chain.get("reviewer_output_checksum") or ""),
            "final_reviewed_diff_checksum": str(chain.get("proposed_diff_checksum") or ""),
            "final_reviewed_diff_sha256_hex": final_diff_sha256_hex,
            "policy_validation_checksum": policy_checksum,
            "base_repo_state_checksum": base_repo_state_checksum,
            "final_artifact_checksum": str(chain.get("final_artifact_checksum") or ""),
        }
        if any(not value for value in required_binding.values()):
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewed repair gate missing required checksum binding",
                policy_validation_checksum=policy_checksum,
            )
        source_checksum = sha256_canonical_json(required_binding)
        refs = tuple(sorted({
            str(chain.get("deterministic_artifact_ref") or ""),
            primary_ref,
            str(chain.get("reviewer_output_ref") or ""),
            final_artifact_ref,
            final_diff_ref,
            str(chain.get("review_chain_metadata_ref") or ""),
            str(policy_path),
            *[f"{key}:{value}" for key, value in required_binding.items()],
        } - {""}))
        gate_result = self._gate_service.create_gate(CreateGateRequest(
            job_id=job_id,
            gate_phase="repair_review",
            stage_index=stage_index,
            source_artifact_checksum=source_checksum,
            source_artifact_refs=refs,
            created_by="system",
        ))
        if gate_result.status == "conflict":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="conflict",
                existing_gate_id=gate_result.existing_gate_id,
                reason="A repair_review gate already exists for this stage",
                policy_validation_checksum=policy_checksum,
            )

        revision_id = ""
        if self._revision_repo is not None:
            revision_id = uuid4().hex
            self._revision_repo.save(ArtifactRevisionRecord(
                revision_id=revision_id,
                job_id=job_id,
                stage_index=stage_index,
                revision_kind="repair",
                revision_status="draft",
                revision_order=0,
                evidence_checksum=source_checksum,
                prior_revision_checksum=None,
                artifact_refs_json=json.dumps(list(refs), separators=(",", ":")),
                prior_revision_id=None,
                superseded_by_revision_id=None,
                accepted_at_gate_id=None,
                created_at=utc_now_text(),
                created_by="system",
            ))
        return RepairGateCreationResult(
            gate_id=gate_result.gate_id,
            gate_checksum=gate_result.gate_checksum,
            diagnosis=None,
            status="created",
            revision_id=revision_id,
            policy_validation_checksum=policy_checksum,
            policy_status=policy_result.status,
        )

    # ── Job 101/102: Create repair_review gate on failure ───────────

    def _existing_open_repair_proposal(self, *, job_id: str, command_id: str) -> Any | None:
        if self._repair_repo is None:
            return None
        list_by_command = getattr(self._repair_repo, "list_proposals_by_command", None)
        if not callable(list_by_command):
            return None
        for proposal in list_by_command(command_id):
            if str(getattr(proposal, "job_id", "") or "") != job_id:
                continue
            status = str(getattr(proposal, "status", "") or "").strip().lower()
            if status in {"user_review_required", "reviewer_accepted", "diff_materialized"}:
                return proposal
        return None

    def create_repair_gate_on_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        failure_summary: str,
        failure_details: dict[str, Any] | None = None,
        source_artifact_refs: tuple[str, ...] = (),
        diagnosis: FailureDiagnosisRecord | None = None,
    ) -> RepairGateCreationResult:
        """Create a repair_review gate after a build/test/transform failure.

        Creates a repair_review gate bound to failure evidence.
        If a repair_review gate already exists for the same
        (job_id, stage_index), returns a conflict result.

        Args:
            job_id: The job that owns the failed command.
            stage_index: The stage where failure occurred.
            command_id: The failed command id.
            failure_summary: Human-readable failure summary.
            failure_details: Optional structured failure details
                (build/test/transform status, logs, classification).
            source_artifact_refs: References to failure evidence artifacts.
            diagnosis: Optional diagnosis record from V2FailureDiagnosisService.

        Returns:
            RepairGateCreationResult with gate_id and status.
        """
        # Compute source artifact checksum from failure evidence
        evidence_payload = dict(failure_details or {})
        evidence_payload["failure_summary"] = failure_summary
        evidence_payload["command_id"] = command_id
        if diagnosis is not None:
            evidence_payload["diagnosis_id"] = diagnosis.diagnosis_id
            evidence_payload["context_pack_checksum"] = diagnosis.context_pack_checksum
            evidence_payload["failure_type"] = diagnosis.failure_type

        source_checksum = sha256_canonical_json(evidence_payload)

        # Build artifact refs from failure details and diagnosis
        refs = list(source_artifact_refs)
        if diagnosis is not None and diagnosis.context_pack_checksum:
            refs.append(f"diagnosis:{diagnosis.diagnosis_id}")
            refs.append(f"checksum:{diagnosis.context_pack_checksum}")

        # Create the repair_review gate
        gate_result = self._gate_service.create_gate(CreateGateRequest(
            job_id=job_id,
            gate_phase="repair_review",
            stage_index=stage_index,
            source_artifact_checksum=source_checksum,
            source_artifact_refs=tuple(sorted(set(refs))),
            created_by="system",
        ))

        if gate_result.status == "conflict":
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=diagnosis,
                status="conflict",
                existing_gate_id=gate_result.existing_gate_id,
                reason="A repair_review gate already exists for this stage",
            )

        return RepairGateCreationResult(
            gate_id=gate_result.gate_id,
            gate_checksum=gate_result.gate_checksum,
            diagnosis=diagnosis,
            status="created",
        )

    # ── Job 104: request_repair_revision ─────────────────────────────

    def request_repair_revision(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        proposal_id: str,
        user_feedback: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
        command_id: str = "",
        model_client: Any | None = None,
        prior_apply_rerun_info: dict[str, Any] | None = None,
        source_profile: str = "",
        target_profile: str = "",
        sandbox_path: str = "",
        run_dir: str | Path = "",
        legacy_path: str = "",
        deterministic_rule_id: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        cycle_number: int = 1,
        h2_required: bool = False,
    ) -> GateActionResult:
        """Request a revision of the current repair proposal.

        Supersedes the current repair_review gate and creates a new one
        with a revised proposal. The user feedback is stored for context.

        Requires:
        - Gate exists and is OPEN
        - Gate phase is repair_review (REVISE is valid)
        - V2RepairFlowService is configured
        - The source proposal exists

        Returns:
            GateActionResult with status and new gate reference.
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.REVISE.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        should_regenerate = bool(
            model_client is not None
            and command_id
            and sandbox_path
            and str(run_dir)
            and legacy_path
            and deterministic_rule_id
        )

        # Use the repair-specific revise path so the revision history
        # remains tagged as repair, not planning.
        base_result = self._gate_action_service.request_repair_revision(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            proposal_id=proposal_id,
            user_feedback=user_feedback,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            open_followup_gate=not should_regenerate,
        )

        if base_result.status not in ("executed", "idempotent") or not should_regenerate:
            return base_result

        gate = self._gate_service._gate_repo.get(gate_id) if self._gate_service is not None else None
        if gate is None:
            return base_result

        refs = _parse_gate_ref_checksums(gate.source_artifact_refs_json)
        previous_checksums = previous_repair_review_checksums or (
            gate.source_artifact_checksum,
        )
        reviewed_result = self.regenerate_reviewed_repair_chain_on_revision(
            job_id=job_id,
            stage_index=gate.stage_index,
            command_id=command_id,
            user_comments=user_feedback,
            prior_evidence_checksum=refs.get("failure_evidence_checksum", gate.source_artifact_checksum),
            prior_context_checksum=refs.get("context_pack_checksum", ""),
            prior_primary_output_checksum=refs.get("primary_output_checksum", ""),
            prior_reviewer_output_checksum=refs.get("reviewer_output_checksum", ""),
            prior_final_diff_checksum=refs.get("final_reviewed_diff_checksum", ""),
            prior_policy_validation_checksum=refs.get("policy_validation_checksum", ""),
            prior_base_repo_state_checksum=refs.get("base_repo_state_checksum", ""),
            prior_apply_rerun_info=prior_apply_rerun_info,
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            source_profile=source_profile,
            target_profile=target_profile,
            previous_repair_review_checksums=previous_checksums,
            cycle_number=cycle_number,
            model_client=model_client,
            h2_required=h2_required,
        )
        if reviewed_result.status == "created":
            return GateActionResult(
                action=base_result.action,
                gate_id=base_result.gate_id,
                decision_id=base_result.decision_id,
                status=base_result.status,
                result_gate_id=reviewed_result.gate_id,
                result_command_id=base_result.result_command_id,
                result_revision_id=reviewed_result.revision_id or base_result.result_revision_id,
                reason=base_result.reason or reviewed_result.reason,
            )

        return GateActionResult(
            action=base_result.action,
            gate_id=base_result.gate_id,
            decision_id=base_result.decision_id,
            status=reviewed_result.status,
            result_gate_id=reviewed_result.gate_id or base_result.result_gate_id,
            result_command_id=base_result.result_command_id,
            result_revision_id=reviewed_result.revision_id or base_result.result_revision_id,
            reason=reviewed_result.reason or base_result.reason,
        )

    # ── F5: Regenerate reviewed repair chain on revision ───────────────

    def regenerate_reviewed_repair_chain_on_revision(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        user_comments: str = "",
        prior_evidence_checksum: str,
        prior_context_checksum: str,
        prior_primary_output_checksum: str,
        prior_reviewer_output_checksum: str,
        prior_final_diff_checksum: str,
        prior_policy_validation_checksum: str,
        prior_base_repo_state_checksum: str,
        prior_apply_rerun_info: dict[str, Any] | None = None,
        sandbox_path: str,
        run_dir: str | Path,
        legacy_path: str,
        deterministic_rule_id: str,
        source_profile: str = "",
        target_profile: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        cycle_number: int = 1,
        model_client: Any | None = None,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Regenerate a full Azure repair review chain after user revision request.

        Builds a new RepairContextPack including prior cycle context and user
        comments, calls produce_repair_review_chain() with Azure
        proposer/reviewer routing, policy-validates the new final diff, and
        opens a new repair_review gate if accepted.

        No old artifact mutation. No patch apply on revision.
        """
        from pathlib import Path as _Path
        from migration_factory.repair_loop.failure_evidence import (
            FailureSource,
            build_failure_evidence,
        )
        from migration_factory.repair_loop.repair_context import (
            build_repair_context_pack,
        )
        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )

        evidence = build_failure_evidence(
            failure_source=FailureSource.BUILD,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            failure_summary=f"Repair revision requested by user: {user_comments[:200] if user_comments else 'no comments'}",
            source_profile=source_profile,
            target_profile=target_profile,
            accepted_artifact_checksums=previous_repair_review_checksums,
        )

        prior_apply = prior_apply_rerun_info or {}
        prior_reviewer_notes: tuple[str, ...] = ()
        if prior_apply.get("reviewer_notes"):
            prior_reviewer_notes = tuple(str(n) for n in prior_apply["reviewer_notes"] if n)

        context_pack = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            source_profile=source_profile or evidence.source_profile,
            target_profile=target_profile or evidence.target_profile,
            prior_proposal_checksums=previous_repair_review_checksums,
            prior_reviewer_notes=prior_reviewer_notes,
            user_comments=user_comments,
            cycle_number=cycle_number,
            max_cycles=self._max_repair_attempts,
        )

        output_dir = _Path(run_dir) / "repair_chain"
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=source_profile or evidence.source_profile,
                target_profile=target_profile or evidence.target_profile,
                model_client=model_client,
            )
        except Exception:
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="skipped",
                reason="reviewer did not accept repair chain on revision",
            )

        return self.create_repair_gate_from_reviewed_chain(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            review_chain_result=chain_result,
            failure_evidence_checksum=evidence.content_checksum,
            context_pack_checksum=context_pack.context_pack_checksum,
            base_repo_state_checksum=context_pack.base_repo_state_checksum,
            sandbox_path=sandbox_path,
            run_dir=str(run_dir),
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            h2_required=h2_required,
        )

    # ── Job 105: approve_repair (delegate to gate action service) ──

    def approve_repair(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        proposal_id: str,
        proposal_checksum: str,
        context_pack_checksum: str,
        reviewer_output_checksum: str = "",
        final_reviewed_diff_checksum: str = "",
        policy_validation_checksum: str = "",
        base_repo_state_checksum: str = "",
        final_reviewed_artifact_checksum: str = "",
        repair_revision_id: str = "",
        repair_revision_checksum: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
        actor_type: str = "human",
    ) -> GateActionResult:
        """Approve a repair at a repair_review gate.

        Delegates to V2GateActionService.approve_repair() which
        handles proposal approval, reviewer critique gate, and
        gate resolution.

        After approval, the caller should queue the patch application
        via V2RepairFlowService.apply_patch().
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.CONTINUE.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        if actor_type != "human":
            return GateActionResult(
                action=GateDecision.CONTINUE.value,
                gate_id=gate_id,
                decision_id="",
                status="actor_not_authoritative",
                reason=(
                    "approve_repair requires a human actor; "
                    f"received actor_type='{actor_type}'"
                ),
            )

        return self._gate_action_service.approve_repair(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            context_pack_checksum=context_pack_checksum,
            reviewer_output_checksum=reviewer_output_checksum,
            final_reviewed_diff_checksum=final_reviewed_diff_checksum,
            policy_validation_checksum=policy_validation_checksum,
            base_repo_state_checksum=base_repo_state_checksum,
            final_reviewed_artifact_checksum=final_reviewed_artifact_checksum,
            repair_revision_id=repair_revision_id,
            repair_revision_checksum=repair_revision_checksum,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            actor_type=actor_type,
        )

    # ── Job 106: reject repair ───────────────────────────────────────

    def reject_repair(
        self,
        *,
        gate_id: str,
        job_id: str,
        decided_by: str,
        reason: str = "",
        idempotency_key: str | None = None,
        expected_gate_checksum: str | None = None,
        actor_type: str = "human",
    ) -> GateActionResult:
        """Reject a repair at a repair_review gate.

        Persists rejection and leaves stage failed/blocked.
        The gate is resolved with REJECT.

        Requires:
        - Gate exists and is OPEN
        - Gate phase is repair_review
        - Gate checksum must match

        Returns:
            GateActionResult with rejection status.
        """
        if self._gate_action_service is None:
            return GateActionResult(
                action=GateDecision.REJECT.value,
                gate_id=gate_id,
                decision_id="",
                status="no_action_service",
                reason="V2GateActionService is not configured",
            )

        if actor_type != "human":
            return GateActionResult(
                action=GateDecision.REJECT.value,
                gate_id=gate_id,
                decision_id="",
                status="actor_not_authoritative",
                reason=(
                    "reject_repair requires a human actor; "
                    f"received actor_type='{actor_type}'"
                ),
            )

        return self._gate_action_service.reject_gate(
            gate_id=gate_id,
            job_id=job_id,
            decided_by=decided_by,
            reason=reason,
            idempotency_key=idempotency_key,
            expected_gate_checksum=expected_gate_checksum,
            actor_type=actor_type,
        )

    # ── Job 107: Repair validation result gate transition ────────────

    def handle_repair_validation_result(
        self,
        *,
        job_id: str,
        stage_index: int,
        validation_passed: bool,
        validation_id: str,
        sandbox_path: str = "",
        diagnosis: FailureDiagnosisRecord | None = None,
    ) -> RepairValidationTransitionResult:
        """Route after-repair validation to the correct next gate.

        If validation passed:
          - Create a stage_completion_review gate
          - Reset attempt count for this stage

        If validation failed:
          - Increment attempt count
          - If attempts remaining, create a new repair_review gate
          - If attempts exhausted, mark exhausted (no new gate)

        Args:
            job_id: The job that owns the repair.
            stage_index: The stage where repair was applied.
            validation_passed: Whether validation passed.
            validation_id: The validation run identifier.
            sandbox_path: The sandbox path for artifact refs.
            diagnosis: Optional new diagnosis for the failure.

        Returns:
            RepairValidationTransitionResult with next gate info.
        """
        attempt_key = (job_id, stage_index)
        current_attempts = self._get_persisted_attempt_count(job_id, stage_index)

        if validation_passed:
            # Reset attempt count on success
            self._attempt_counts.pop(attempt_key, None)

            # Create stage_completion_review gate
            source_checksum = sha256_canonical_json({
                "validation_id": validation_id,
                "job_id": job_id,
                "stage_index": stage_index,
                "passed": True,
            })
            refs = [f"validation:{validation_id}", f"sandbox:{sandbox_path}"] if sandbox_path else [f"validation:{validation_id}"]

            gate_result = self._gate_service.create_gate(CreateGateRequest(
                job_id=job_id,
                gate_phase="stage_completion_review",
                stage_index=stage_index,
                source_artifact_checksum=source_checksum,
                source_artifact_refs=tuple(sorted(set(refs))),
                created_by="system",
            ))

            if gate_result.status == "created":
                return RepairValidationTransitionResult(
                    status="stage_completion_gate_created",
                    gate_id=gate_result.gate_id,
                    gate_checksum=gate_result.gate_checksum,
                    remaining_attempts=self._max_repair_attempts,
                    reason="Repair validation passed, stage_completion_review gate created",
                )
            return RepairValidationTransitionResult(
                status="no_action",
                reason=f"Could not create stage_completion_review gate: {gate_result.status}",
            )

        # Validation failed — increment attempt count (cap at max)
        current_attempts += 1
        if current_attempts > self._max_repair_attempts:
            current_attempts = self._max_repair_attempts
        self._attempt_counts[attempt_key] = current_attempts
        remaining = max(0, self._max_repair_attempts - current_attempts)

        if remaining > 0:
            # Create a new repair_review gate
            failure_details = {
                "validation_id": validation_id,
                "attempt": current_attempts,
                "remaining": remaining,
            }
            if diagnosis is not None:
                failure_details["diagnosis_id"] = diagnosis.diagnosis_id

            source_checksum = sha256_canonical_json(failure_details)
            refs = [f"validation:{validation_id}", f"diagnosis:{diagnosis.diagnosis_id}"] if diagnosis else [f"validation:{validation_id}"]

            gate_result = self._gate_service.create_gate(CreateGateRequest(
                job_id=job_id,
                gate_phase="repair_review",
                stage_index=stage_index,
                source_artifact_checksum=source_checksum,
                source_artifact_refs=tuple(sorted(set(refs))),
                created_by="system",
            ))

            if gate_result.status == "created":
                return RepairValidationTransitionResult(
                    status="repair_gate_created",
                    gate_id=gate_result.gate_id,
                    gate_checksum=gate_result.gate_checksum,
                    remaining_attempts=remaining,
                    reason=f"Repair validation failed, {remaining} attempt(s) remaining",
                )

        return RepairValidationTransitionResult(
            status="attempts_exhausted",
            remaining_attempts=remaining,
            reason=f"All {self._max_repair_attempts} repair attempt(s) exhausted for stage {stage_index}",
        )

    # ── F5: Create next bounded repair cycle after rerun failure ──────

    def create_next_repair_cycle_from_rerun_failure(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        prior_evidence_checksum: str,
        prior_context_checksum: str,
        prior_primary_output_checksum: str,
        prior_reviewer_output_checksum: str,
        prior_final_diff_checksum: str,
        prior_policy_validation_checksum: str,
        prior_base_repo_state_checksum: str,
        apply_result: dict[str, Any] | None = None,
        rerun_result: dict[str, Any] | None = None,
        rollback_result: dict[str, Any] | None = None,
        user_comments: str = "",
        sandbox_path: str,
        run_dir: str | Path,
        legacy_path: str,
        deterministic_rule_id: str,
        source_profile: str = "",
        target_profile: str = "",
        previous_repair_review_checksums: tuple[str, ...] = (),
        max_cycles: int | None = None,
        model_client: Any | None = None,
        h2_required: bool = False,
    ) -> RepairGateCreationResult:
        """Create the next bounded repair cycle after rerun validation failure.

        On rerun failure, if attempts remain:
        1. Build new FailureEvidence from rerun failure data
        2. Build new RepairContextPack including full prior cycle context
        3. Call produce_repair_review_chain with Azure proposer/reviewer
        4. Policy-validate the new final diff
        5. Open next repair_review gate with chain info

        If attempts exhausted, create terminal failure artifact.
        """
        from pathlib import Path as _Path
        from migration_factory.repair_loop.failure_evidence import (
            FailureSource,
            build_failure_evidence,
        )
        from migration_factory.repair_loop.repair_context import (
            build_repair_context_pack,
        )
        from migration_factory.orchestrator.repair_review_chain import (
            produce_repair_review_chain,
        )
        from migration_factory.control_tower.domain.checksums import (
            sha256_canonical_json,
        )

        effective_max = max_cycles or self._max_repair_attempts
        current_cycle = len(previous_repair_review_checksums) + 1
        remaining = effective_max - current_cycle
        run_path = _Path(run_dir)
        repairs_dir = run_path / "repairs"
        repairs_dir.mkdir(parents=True, exist_ok=True)

        def _write_cycle_artifact(filename: str, payload: dict[str, Any]) -> tuple[Path, str]:
            checksum = sha256_canonical_json(payload)
            artifact_path = repairs_dir / filename
            artifact_path.write_text(
                json.dumps({**payload, "artifact_checksum": checksum}, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return artifact_path, checksum

        if isinstance(rerun_result, dict) and rerun_result:
            rerun_path, rerun_checksum = _write_cycle_artifact(
                "repair_rerun_result.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "rerun_result": dict(rerun_result),
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            rerun_result = {**rerun_result, "artifact_ref": str(rerun_path), "artifact_checksum": rerun_checksum}
        if isinstance(rollback_result, dict) and rollback_result:
            rollback_path, rollback_checksum = _write_cycle_artifact(
                "repair_rollback_result.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "rollback_result": dict(rollback_result),
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            rollback_result = {**rollback_result, "artifact_ref": str(rollback_path), "artifact_checksum": rollback_checksum}

        if remaining < 1:
            _write_cycle_artifact(
                "repair_terminal_failure.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "status": "REPAIR_FAILED",
                    "reason": f"All {effective_max} repair attempt(s) exhausted",
                    "max_cycles": effective_max,
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="attempts_exhausted",
                reason=f"All {effective_max} repair attempt(s) exhausted",
            )

        rerun_payload = dict(rerun_result or {})
        rollback_payload = dict(rollback_result or {})
        apply_payload = dict(apply_result or {})

        failure_summary = f"Rerun validation failed (cycle {current_cycle}/{effective_max})"
        if rerun_payload.get("errors"):
            failure_summary += ": " + "; ".join(str(e) for e in rerun_payload["errors"])

        evidence = build_failure_evidence(
            failure_source=FailureSource.VALIDATION,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            failure_summary=failure_summary,
            source_profile=source_profile,
            target_profile=target_profile,
            accepted_artifact_checksums=previous_repair_review_checksums,
        )

        prior_reviewer_notes: tuple[str, ...] = ()
        if apply_payload.get("reviewer_notes"):
            prior_reviewer_notes = tuple(str(n) for n in apply_payload["reviewer_notes"] if n)

        context_pack = build_repair_context_pack(
            failure_evidence=evidence,
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            source_profile=source_profile or evidence.source_profile,
            target_profile=target_profile or evidence.target_profile,
            prior_proposal_checksums=previous_repair_review_checksums,
            prior_reviewer_notes=prior_reviewer_notes,
            user_comments=user_comments,
            cycle_number=current_cycle,
            max_cycles=effective_max,
        )

        output_dir = _Path(run_dir) / "repair_chain"
        try:
            chain_result = produce_repair_review_chain(
                failure_evidence=evidence,
                context_pack=context_pack,
                output_dir=output_dir,
                source_profile=source_profile or evidence.source_profile,
                target_profile=target_profile or evidence.target_profile,
                model_client=model_client,
            )
        except Exception:
            _write_cycle_artifact(
                "repair_terminal_failure.json",
                {
                    "job_id": job_id,
                    "stage_index": stage_index,
                    "command_id": command_id,
                    "cycle_number": current_cycle,
                    "status": "REPAIR_FAILED",
                    "reason": "Azure repair chain production failed on next cycle",
                    "max_cycles": effective_max,
                    "prior_evidence_checksum": prior_evidence_checksum,
                    "prior_context_checksum": prior_context_checksum,
                    "prior_primary_output_checksum": prior_primary_output_checksum,
                    "prior_reviewer_output_checksum": prior_reviewer_output_checksum,
                    "prior_final_diff_checksum": prior_final_diff_checksum,
                    "prior_policy_validation_checksum": prior_policy_validation_checksum,
                    "prior_base_repo_state_checksum": prior_base_repo_state_checksum,
                },
            )
            return RepairGateCreationResult(
                gate_id="",
                gate_checksum="",
                diagnosis=None,
                status="attempts_exhausted",
                reason="Azure repair chain production failed on next cycle",
            )

        return self.create_repair_gate_from_reviewed_chain(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            review_chain_result=chain_result,
            failure_evidence_checksum=evidence.content_checksum,
            context_pack_checksum=context_pack.context_pack_checksum,
            base_repo_state_checksum=context_pack.base_repo_state_checksum,
            sandbox_path=sandbox_path,
            run_dir=str(run_dir),
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            h2_required=h2_required,
        )

    # ── Job 108: Attempt limits ──────────────────────────────────────

    def get_remaining_attempts(
        self,
        job_id: str,
        stage_index: int,
    ) -> int:
        """Get remaining repair attempts for a job+stage."""
        current = self._get_persisted_attempt_count(job_id, stage_index)
        return max(0, self._max_repair_attempts - current)

    def reset_attempts(
        self,
        job_id: str,
        stage_index: int,
    ) -> None:
        """Reset repair attempt count (e.g., after successful stage completion)."""
        self._attempt_counts.pop((job_id, stage_index), None)

    def clear_attempts(self) -> None:
        """Clear all attempt counts (for testing)."""
        self._attempt_counts.clear()

    def _get_persisted_attempt_count(self, job_id: str, stage_index: int) -> int:
        """Derive the attempt count from persisted gate history."""
        if self._gate_service is None or self._gate_service._gate_repo is None:
            return self._attempt_counts.get((job_id, stage_index), 0)

        gates = self._gate_service._gate_repo.list_by_job_and_stage(job_id, stage_index)
        if any(g.gate_phase == "stage_completion_review" for g in gates):
            return 0

        repair_gates = [g for g in gates if g.gate_phase == "repair_review"]
        if not repair_gates:
            return self._attempt_counts.get((job_id, stage_index), 0)

        persisted = max(0, len(repair_gates) - 1)
        return min(self._max_repair_attempts, max(persisted, self._attempt_counts.get((job_id, stage_index), 0)))

    # ── Serialization ────────────────────────────────────────────────

    def gate_creation_to_dict(
        self,
        result: RepairGateCreationResult,
    ) -> dict[str, Any]:
        return {
            "gate_id": result.gate_id,
            "gate_checksum": result.gate_checksum,
            "status": result.status,
            "existing_gate_id": result.existing_gate_id,
            "reason": result.reason,
        }

    def transition_to_dict(
        self,
        result: RepairValidationTransitionResult,
    ) -> dict[str, Any]:
        return {
            "status": result.status,
            "gate_id": result.gate_id,
            "gate_checksum": result.gate_checksum,
            "remaining_attempts": result.remaining_attempts,
            "reason": result.reason,
        }


# ── Orchestrator integration helper ─────────────────────────────────


def create_repair_gate_diagnosis_callback(
    repair_gate_service: V2RepairGateService,
    diagnosis_service: V2FailureDiagnosisService,
    *,
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS,
) -> Callable[[str, int, str, str, dict[str, Any]], None]:
    """Create a callback suitable for V2OrchestratorRunner(diagnosis_callback=...).

    This callback:
    1. Runs diagnosis via V2FailureDiagnosisService.diagnose()
    2. Creates a repair_review gate via V2RepairGateService.create_repair_gate_on_failure()
    3. Binds failure evidence to the gate

    Usage:
        svc = V2RepairGateService(gate_service, gate_action_service, repair_flow)
        diag_svc = V2FailureDiagnosisService(repair_flow=repair_flow)
        runner = V2OrchestratorRunner(
            unit_of_work_factory=...,
            diagnosis_callback=create_repair_gate_diagnosis_callback(svc, diag_svc),
        )
    """

    def callback(
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        # Step 1: Run diagnosis (if the event_type is diagnosable)
        diagnosis = None
        if V2FailureDiagnosisService.is_diagnosable_event(event_type):
            try:
                diagnosis = diagnosis_service.diagnose(
                    job_id=job_id,
                    stage_index=stage_index,
                    command_id=command_id,
                    event_type=event_type,
                    payload=payload,
                )
            except Exception:
                # Diagnosis is best-effort — don't block gate creation
                pass

        # Step 2: Build failure summary from payload
        failure_summary = _build_failure_summary_from_payload(event_type, payload)
        failure_details = dict(payload or {})

        # Step 3: Extract artifact refs from payload
        artifact_refs: tuple[str, ...] = ()
        raw_refs = failure_details.get("artifact_refs", {})
        if isinstance(raw_refs, dict):
            artifact_refs = tuple(
                str(v) for v in raw_refs.values() if v and isinstance(v, str)
            )

        # Step 4: Create repair_review gate
        try:
            repair_gate_service.create_repair_gate_on_failure(
                job_id=job_id,
                stage_index=stage_index,
                command_id=command_id,
                failure_summary=failure_summary,
                failure_details=failure_details,
                source_artifact_refs=artifact_refs,
                diagnosis=diagnosis,
            )
        except Exception:
            # Gate creation is best-effort — don't block the pipeline
            pass

    return callback


def _build_failure_summary_from_payload(
    event_type: str,
    payload: dict[str, Any],
) -> str:
    """Build a human-readable failure summary from event payload."""
    payload_data = payload or {}
    build_status = str(payload_data.get("build_status", ""))
    test_status = str(payload_data.get("test_status", ""))
    transform_status = str(payload_data.get("transform_status", ""))
    message = str(payload_data.get("message", ""))
    stderr = str(payload_data.get("stderr", ""))[:200]

    parts: list[str] = []
    if event_type == "build_failed":
        parts.append(f"Build failed: {build_status}")
    elif event_type == "test_failed":
        parts.append(f"Test failed: {test_status}")
    elif event_type == "transform_failed":
        parts.append(f"Transform failed: {transform_status or build_status}")

    if message and message not in parts:
        parts.append(message[:200])
    if stderr:
        parts.append(f"stderr: {stderr}")

    return " | ".join(parts) if parts else f"{event_type} with no details"


def _read_json_ref(ref: Any) -> dict[str, Any]:
    if not ref:
        return {}
    try:
        payload = json.loads(Path(str(ref)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _reviewed_repair_unavailable_reason(exc: Exception) -> str:
    text = str(exc).lower()
    if hasattr(exc, "reason_code") and exc.reason_code:
        rc = str(exc.reason_code).lower()
        if "schema_invalid" in rc:
            return "proposer_schema_invalid"
        return rc
    if "proposer_schema_invalid" in text or "primary repair output" in text or "azure_response_format_rejected" in text:
        return "proposer_schema_invalid"
    if "reviewer_model_unavailable" in text or "missing_reviewer_deployment" in text:
        return "reviewer_model_unavailable"
    if "reviewer_schema_invalid" in text or "reviewer output must be valid json" in text:
        return "reviewer_schema_invalid"
    if "reviewer_model_failed" in text:
        return "reviewer_model_failed"
    if "reviewer decision failed closed" in text or "request_revision" in text or "reject" in text:
        return "reviewer_rejected"
    if "missing_endpoint" in text or "missing_key" in text or "azure_model_config_missing" in text:
        return "azure_model_config_missing"
    if "materializ" in text or "final_reviewed_repair" in text:
        return "diff_materialization_failed"
    if "primary repair model failed closed" in text:
        return "proposer_model_failed"
    return "reviewer_model_unavailable" if "reviewer repair model failed closed" in text else "diff_materialization_failed"


def _is_structural_materialization_failure(reason: str | None) -> bool:
    return "diff structure validation failed:" in str(reason or "").strip().lower()


def _extract_struct_issue(detail: str | None) -> str:
    text = str(detail or "").strip()
    marker = "Diff structure validation failed:"
    if text.startswith(marker):
        return text[len(marker):].strip()
    return ""


def _materialization_reason_code(reason: str | None) -> str:
    text = str(reason or "").strip()
    lowered = text.lower()
    stable = {
        "MALFORMED_DIFF",
        "PROPOSER_DIFF_MISSING",
        "DIFF_REF_MISSING",
        "PATCH_POLICY_REJECTED",
        "CHECKSUM_MISMATCH",
        "ARTIFACT_WRITE_FAILED",
        "SAFE_DIFF_PREVIEW_FAILED",
        "UNKNOWN_MATERIALIZATION_FAILURE",
    }
    if text in stable:
        return text
    if not text:
        return "UNKNOWN_MATERIALIZATION_FAILURE"
    if "diff structure validation failed" in lowered:
        return "MALFORMED_DIFF"
    if "missing artifact refs" in lowered or "missing_diff_ref" in lowered or "diff_ref" in lowered:
        return "DIFF_REF_MISSING"
    if "checksum" in lowered:
        return "CHECKSUM_MISMATCH"
    if "policy validation failed" in lowered or "patch policy" in lowered:
        return "PATCH_POLICY_REJECTED"
    if "safe diff" in lowered or "preview" in lowered:
        return "SAFE_DIFF_PREVIEW_FAILED"
    if "write" in lowered or "persistence" in lowered:
        return "ARTIFACT_WRITE_FAILED"
    if "proposed_diff" in lowered or "proposer" in lowered:
        return "PROPOSER_DIFF_MISSING"
    return "UNKNOWN_MATERIALIZATION_FAILURE"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _failure_evidence_from_json(path: Path) -> FailureEvidence:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("failure evidence artifact must be an object")
    compiler_errors = tuple(
        NormalizedCompilerError(
            message=str(item.get("message") or ""),
            file_path=str(item.get("file_path") or ""),
            line=int(item.get("line") or 0),
            column=int(item.get("column") or 0),
            severity=str(item.get("severity") or "error"),
        )
        for item in payload.get("compiler_errors", ())
        if isinstance(item, dict)
    )
    test_failures = tuple(
        NormalizedTestFailure(
            test_name=str(item.get("test_name") or ""),
            test_class=str(item.get("test_class") or ""),
            message=str(item.get("message") or ""),
            file_path=str(item.get("file_path") or ""),
        )
        for item in payload.get("test_failures", ())
        if isinstance(item, dict)
    )
    source = str(payload.get("failure_source") or "unknown")
    try:
        failure_source = FailureSource(source)
    except ValueError:
        failure_source = FailureSource.UNKNOWN
    return FailureEvidence(
        failure_source=failure_source,
        stage_index=int(payload.get("stage_index") or 0),
        job_id=str(payload.get("job_id") or ""),
        command_id=str(payload.get("command_id") or ""),
        failure_summary=str(payload.get("failure_summary") or ""),
        compiler_errors=compiler_errors,
        test_failures=test_failures,
        changed_files=tuple(str(item) for item in payload.get("changed_files", ()) if str(item).strip()),
        source_profile=str(payload.get("source_profile") or ""),
        target_profile=str(payload.get("target_profile") or ""),
        accepted_artifact_checksums=tuple(
            str(item) for item in payload.get("accepted_artifact_checksums", ()) if str(item).strip()
        ),
        artifact_refs={
            str(k): str(v)
            for k, v in dict(payload.get("artifact_refs") or {}).items()
            if str(k).strip() and str(v).strip()
        },
        stdout_tail=str(payload.get("stdout_tail") or ""),
        stderr_tail=str(payload.get("stderr_tail") or ""),
        safe_log_preview=str(payload.get("safe_log_preview") or ""),
        content_checksum=str(payload.get("content_checksum") or ""),
        artifact_checksum=str(payload.get("artifact_checksum") or ""),
        created_at=str(payload.get("created_at") or ""),
        schema_version=str(payload.get("schema_version") or "1.0.0"),
    )


def _repair_context_from_json(path: Path) -> RepairContextPack:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repair context artifact must be an object")
    return RepairContextPack(
        job_id=str(payload.get("job_id") or ""),
        stage_index=int(payload.get("stage_index") or 0),
        command_id=str(payload.get("command_id") or ""),
        failure_source=str(payload.get("failure_source") or ""),
        failure_evidence_checksum=str(payload.get("failure_evidence_checksum") or ""),
        source_profile=str(payload.get("source_profile") or ""),
        target_profile=str(payload.get("target_profile") or ""),
        accepted_analysis_checksum=str(payload.get("accepted_analysis_checksum") or ""),
        accepted_planning_checksum=str(payload.get("accepted_planning_checksum") or ""),
        prior_proposal_checksums=tuple(
            str(item) for item in payload.get("prior_proposal_checksums", ()) if str(item).strip()
        ),
        prior_reviewer_notes=tuple(
            str(item) for item in payload.get("prior_reviewer_notes", ()) if str(item).strip()
        ),
        user_comments=str(payload.get("user_comments") or ""),
        changed_files=tuple(str(item) for item in payload.get("changed_files", ()) if str(item).strip()),
        safe_log_preview=str(payload.get("safe_log_preview") or ""),
        base_repo_state_checksum=str(payload.get("base_repo_state_checksum") or ""),
        context_pack_checksum=str(payload.get("context_pack_checksum") or ""),
        prior_revision_ids=tuple(str(item) for item in payload.get("prior_revision_ids", ()) if str(item).strip()),
        cycle_number=int(payload.get("cycle_number") or 0),
        max_cycles=int(payload.get("max_cycles") or DEFAULT_MAX_REPAIR_ATTEMPTS),
        created_at=str(payload.get("created_at") or ""),
        schema_version=str(payload.get("schema_version") or "1.0.0"),
    )


def _parse_gate_ref_checksums(source_artifact_refs_json: str) -> dict[str, str]:
    try:
        parsed = json.loads(source_artifact_refs_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(parsed, list):
        return {}
    refs: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, str):
            continue
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        if key.endswith("_checksum") or key == "checksum" or key.endswith("_sha256_hex"):
            refs[key] = value
    return refs


def _normalized_flag(chain: Any) -> bool:
    """Check if the primary_output has the _diff_normalized flag."""
    if not isinstance(chain, dict):
        return False
    ref = chain.get("primary_output_ref")
    if not ref:
        return False
    try:
        primary = json.loads(Path(str(ref)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return False
    return bool(primary.get("_diff_normalized")) if isinstance(primary, dict) else False
