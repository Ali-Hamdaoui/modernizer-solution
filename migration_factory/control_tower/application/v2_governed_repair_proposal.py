from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_diagnosis_proposal_flow import (
    StructuredModelCallResult,
    StructuredModelClient,
)
from migration_factory.control_tower.application.v2_failure_evidence import (
    infer_stage_run_root,
)
from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    ModelInvocationResult,
    Model2VerificationResult,
)
from migration_factory.control_tower.application.v2_model_schemas import (
    ContextPack,
    validate_model_output,
)
from migration_factory.control_tower.application.v2_prompt_router import (
    ModelCallRequest,
)
from migration_factory.control_tower.application.v2_run_evidence_bundle import RunEvidenceBundle
from migration_factory.control_tower.domain.checksums import utc_now_text


_MAVEN_COORD_RE = re.compile(r"\b[\w.\-]+:[\w.\-]+:(?:jar|pom):\d+\.\d+\.x\b")
_PROPERTY_RE = re.compile(r"\b(?:javax\.persistence\.version|javax\.servlet\.version)\b")
_FORBIDDEN_RECOMMENDATION_RE = re.compile(
    r"(?i)\b(execute|run command|apply repair|auto[- ]?approve|approve automatically|resume stage|write file|modify files?)\b"
)
_MAX_EVIDENCE = 6
_MAX_TEXT = 2600


@dataclass(frozen=True)
class GovernedRepairProposal:
    summary: str
    failure_type: str
    root_cause: str
    confidence: str
    recommended_action: str
    risk_level: str
    affected_paths: tuple[str, ...]
    proposed_file_changes: tuple[str, ...]
    validation_commands: tuple[str, ...]
    rollback_plan: str
    human_approval_required: bool
    no_auto_apply: bool
    evidence_refs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate_model_output("GovernedRepairProposal", data)
        return data


@dataclass(frozen=True)
class V2GovernedRepairProposalResult:
    proposal_id: str
    migration_status: str
    model2_verdict: str
    answer: str
    proposal: dict[str, Any]
    verification: dict[str, Any]
    diagnosis: dict[str, Any]
    trace_artifact_refs: dict[str, dict[str, str]]
    proposal_artifact_refs: dict[str, str]
    read_only: bool = True
    no_auto_apply: bool = True
    human_approval_required: bool = True
    manual_review_required: bool = True
    patch_candidate_supported: bool = False
    sandbox_only: bool = True
    source_mutated: bool = False
    stage_resumed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2GovernedRepairProposalService:
    def __init__(
        self,
        *,
        proposer_client: StructuredModelClient | None,
        reviewer_client: StructuredModelClient | None,
        trace_store: V2DualModelInvocationAuditStore | None = None,
    ) -> None:
        self._proposer_client = proposer_client
        self._reviewer_client = reviewer_client
        self._trace_store = trace_store or V2DualModelInvocationAuditStore()

    @staticmethod
    def is_repairable_failure(bundle: RunEvidenceBundle) -> bool:
        if bundle.migration_status.startswith("completed"):
            return False
        return bool(
            bundle.migration_status == "failed"
            or bundle.failure_bundle is not None
            or bundle.deterministic_failure_classification is not None
        )

    def propose(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        setup: Any | None,
        diagnosis_review: dict[str, Any] | None = None,
        persisted_diagnosis: dict[str, Any] | None = None,
        trace_root: str | Path | None = None,
    ) -> V2GovernedRepairProposalResult:
        diagnosis = self._diagnosis_payload(
            bundle=bundle,
            diagnosis_review=diagnosis_review,
            persisted_diagnosis=persisted_diagnosis,
        )
        proposal_id = uuid4().hex
        if not self.is_repairable_failure(bundle):
            proposal = GovernedRepairProposal(
                summary="No migration repair is needed because deterministic evidence shows migration completion.",
                failure_type=str((bundle.failure_bundle.failure_type if bundle.failure_bundle is not None else "") or "no_migration_failure"),
                root_cause="Migration completed; only AI/model supervision is unavailable." if bundle.ai_supervision_status == "unavailable_fallback" else "Migration completed with no deterministic repairable failure.",
                confidence="high",
                recommended_action="No repair proposal. Inspect AI/model availability separately if needed.",
                risk_level="low",
                affected_paths=(),
                proposed_file_changes=(),
                validation_commands=("No validation change requested.",),
                rollback_plan="No patch prepared or applied.",
                human_approval_required=True,
                no_auto_apply=True,
                evidence_refs=self._evidence_refs(bundle),
            ).to_dict()
            proposal.update(
                {
                    "manual_review_required": True,
                    "patch_candidate_supported": False,
                    "read_only": True,
                    "source_mutated": False,
                    "sandbox_only": True,
                    "stage_resumed": False,
                    "risk": proposal.get("risk_level", "low"),
                    "recommended_actions": [proposal.get("recommended_action", "")],
                }
            )
            verification = Model2VerificationResult(
                verdict="accepted",
                evidence_alignment="aligned",
                hallucination_check="passed",
                policy_check="passed",
                risk_level="low",
                issues_found=(),
                human_approval_required=True,
            ).to_dict()
            answer = self._render_answer(
                question=question,
                bundle=bundle,
                proposal=proposal,
                verification=verification,
            )
            return V2GovernedRepairProposalResult(
                proposal_id=proposal_id,
                migration_status=bundle.migration_status,
                model2_verdict="accepted",
                answer=answer,
                proposal=proposal,
                verification=verification,
                diagnosis=diagnosis,
                trace_artifact_refs={"model1": {}, "model2": {}},
                proposal_artifact_refs={},
            )

        resolved_trace_root = self._trace_root(bundle=bundle, setup=setup, trace_root=trace_root)
        model1_request = self._model1_request(
            question=question,
            bundle=bundle,
            diagnosis=diagnosis,
            trace_root=resolved_trace_root,
        )
        model1_result = self._invoke_model1(request=model1_request, bundle=bundle, diagnosis=diagnosis)
        proposal = dict(model1_result.structured_output)
        proposal["human_approval_required"] = True
        proposal["no_auto_apply"] = True
        proposal["recommended_action"] = str(proposal.get("recommended_action") or "Review and approve proposal before any later backend execution.")

        model2_request = self._model2_request(
            question=question,
            bundle=bundle,
            proposal=proposal,
            trace_root=resolved_trace_root,
        )
        model2_result = self._invoke_model2(
            request=model2_request,
            bundle=bundle,
            proposal=proposal,
        )
        verification = dict(model2_result.structured_output)
        artifact_refs = self._persist_proposal_artifacts(
            proposal_id=proposal_id,
            trace_root=resolved_trace_root,
            bundle=bundle,
            diagnosis=diagnosis,
            proposal=proposal,
            verification=verification,
        )
        answer = self._render_answer(
            question=question,
            bundle=bundle,
            proposal=proposal,
            verification=verification,
        )
        return V2GovernedRepairProposalResult(
            proposal_id=proposal_id,
            migration_status=bundle.migration_status,
            model2_verdict=str(verification.get("verdict") or "needs_human_review"),
            answer=answer,
            proposal=proposal,
            verification=verification,
            diagnosis=diagnosis,
            trace_artifact_refs={
                "model1": dict(model1_result.trace_artifact_refs),
                "model2": dict(model2_result.trace_artifact_refs),
            },
            proposal_artifact_refs=artifact_refs,
        )

    def _invoke_model1(
        self,
        *,
        request: ModelInvocationRequest,
        bundle: RunEvidenceBundle,
        diagnosis: dict[str, Any],
    ) -> ModelInvocationResult:
        created_at = utc_now_text()
        if self._live_ready(role="proposer") and self._proposer_client is not None:
            try:
                call_request = self._request_to_model_call_request(request)
                call = self._proposer_client.invoke(
                    request=call_request,
                    schema_name="GovernedRepairProposal",
                )
                result = ModelInvocationResult(
                    role=MODEL_1_ROLE,
                    provider=call.provider,
                    mode="live",
                    success=call.success,
                    structured_output=call.validated_output,
                    invocation_id=call.model_invocation_id,
                    created_at=created_at,
                )
                return self._persist_trace_if_possible(request=request, result=result)
            except Exception as exc:
                proposal = self._fallback_proposal(bundle=bundle, diagnosis=diagnosis)
                result = ModelInvocationResult(
                    role=MODEL_1_ROLE,
                    provider="deterministic",
                    mode="fallback",
                    success=False,
                    structured_output=proposal,
                    invocation_id=f"repair-proposal-{uuid4().hex}",
                    created_at=created_at,
                    warnings=self._fallback_warnings(role="proposer"),
                    errors=(*self._fallback_errors(), str(exc)),
                )
                return self._persist_trace_if_possible(request=request, result=result)

        proposal = self._fallback_proposal(bundle=bundle, diagnosis=diagnosis)
        result = ModelInvocationResult(
            role=MODEL_1_ROLE,
            provider="deterministic",
            mode="fallback",
            success=True,
            structured_output=proposal,
            invocation_id=f"repair-proposal-{uuid4().hex}",
            created_at=created_at,
            warnings=self._fallback_warnings(role="proposer"),
            errors=self._fallback_errors(),
        )
        return self._persist_trace_if_possible(request=request, result=result)

    def _invoke_model2(
        self,
        *,
        request: ModelInvocationRequest,
        bundle: RunEvidenceBundle,
        proposal: dict[str, Any],
    ) -> ModelInvocationResult:
        created_at = utc_now_text()
        if self._live_ready(role="reviewer") and self._reviewer_client is not None:
            try:
                call_request = self._request_to_model_call_request(request)
                call = self._reviewer_client.invoke(
                    request=call_request,
                    schema_name="Model2VerificationResult",
                )
                result = ModelInvocationResult(
                    role=MODEL_2_ROLE,
                    provider=call.provider,
                    mode="live",
                    success=call.success,
                    structured_output=call.validated_output,
                    invocation_id=call.model_invocation_id,
                    created_at=created_at,
                )
                return self._persist_trace_if_possible(request=request, result=result)
            except Exception as exc:
                verification = self._fallback_verification(bundle=bundle, proposal=proposal)
                result = ModelInvocationResult(
                    role=MODEL_2_ROLE,
                    provider="deterministic",
                    mode="fallback",
                    success=False,
                    structured_output=verification,
                    invocation_id=f"repair-verification-{uuid4().hex}",
                    created_at=created_at,
                    warnings=self._fallback_warnings(role="reviewer"),
                    errors=(*self._fallback_errors(), str(exc)),
                )
                return self._persist_trace_if_possible(request=request, result=result)

        verification = self._fallback_verification(bundle=bundle, proposal=proposal)
        result = ModelInvocationResult(
            role=MODEL_2_ROLE,
            provider="deterministic",
            mode="fallback",
            success=True,
            structured_output=verification,
            invocation_id=f"repair-verification-{uuid4().hex}",
            created_at=created_at,
            warnings=self._fallback_warnings(role="reviewer"),
            errors=self._fallback_errors(),
        )
        return self._persist_trace_if_possible(request=request, result=result)

    def _fallback_proposal(
        self,
        *,
        bundle: RunEvidenceBundle,
        diagnosis: dict[str, Any],
    ) -> dict[str, Any]:
        failure_type = str(diagnosis.get("failure_type") or (bundle.failure_bundle.failure_type if bundle.failure_bundle is not None else "unknown_build_failure"))
        root_cause = str(diagnosis.get("root_cause") or diagnosis.get("likely_root_cause") or (bundle.failure_bundle.root_cause if bundle.failure_bundle is not None else "No verified root cause available."))
        evidence_refs = self._evidence_refs(bundle)
        if failure_type == "invalid_maven_wildcard_version":
            payload = GovernedRepairProposal(
                summary=(
                    "Prepare bounded pom.xml-only repair proposal for "
                    "jakarta.persistence:jakarta.persistence-api:jar:3.0.x and "
                    "jakarta.servlet:jakarta.servlet-api:jar:5.0.x by replacing "
                    "invalid wildcard versions with exact supported versions."
                ),
                failure_type=failure_type,
                root_cause=root_cause,
                confidence=str(diagnosis.get("confidence") or "high"),
                recommended_action="Review bounded pom.xml-only repair proposal and approve it before any later patch materialization.",
                risk_level="medium",
                affected_paths=("pom.xml",),
                proposed_file_changes=(
                    "Replace javax.persistence.version 3.0.x with 3.1.0 in pom.xml.",
                    "Replace javax.servlet.version 5.0.x with 6.0.0 in pom.xml.",
                ),
                validation_commands=(
                    "Use existing governed Stage 2 sandbox build validation.",
                    "Use existing governed Stage 2 sandbox test validation after build passes.",
                ),
                rollback_plan="No patch applied in this ticket. If a future approved patch fails validation, use governed sandbox rollback.",
                human_approval_required=True,
                no_auto_apply=True,
                evidence_refs=evidence_refs,
            )
            proposal_payload = payload.to_dict()
            proposal_payload.update(
                {
                    "manual_review_required": True,
                    "patch_candidate_supported": True,
                    "read_only": True,
                    "no_auto_apply": True,
                    "human_approval_required": True,
                    "source_mutated": False,
                    "sandbox_only": True,
                    "stage_resumed": False,
                    "risk": proposal_payload.get("risk_level", "medium"),
                    "recommended_actions": [proposal_payload.get("recommended_action", "")],
                }
            )
            return proposal_payload
        payload = GovernedRepairProposal(
            summary="Prepared cautious repair proposal shell from deterministic failure evidence. Human review still required.",
            failure_type=failure_type,
            root_cause=root_cause,
            confidence=str(diagnosis.get("confidence") or "medium"),
            recommended_action="Review evidence and decide whether to prepare a narrower bounded proposal before any approval.",
            risk_level="high",
            affected_paths=tuple(diagnosis.get("affected_paths") or (bundle.failure_bundle.affected_paths if bundle.failure_bundle is not None else ())),
            proposed_file_changes=(),
            validation_commands=(),
            rollback_plan="No patch applied in this ticket.",
            human_approval_required=True,
            no_auto_apply=True,
            evidence_refs=evidence_refs,
        )
        proposal_payload = payload.to_dict()
        proposal_payload.update(
            {
                "manual_review_required": True,
                "patch_candidate_supported": False,
                "read_only": True,
                "no_auto_apply": True,
                "human_approval_required": True,
                "source_mutated": False,
                "sandbox_only": True,
                "stage_resumed": False,
                "risk": proposal_payload.get("risk_level", "high"),
                "recommended_actions": [proposal_payload.get("recommended_action", "")],
            }
        )
        return proposal_payload

    def _fallback_verification(
        self,
        *,
        bundle: RunEvidenceBundle,
        proposal: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []
        if bool(proposal.get("no_auto_apply")) is not True:
            issues.append("Proposal did not keep no_auto_apply=true.")
        if bool(proposal.get("human_approval_required")) is not True:
            issues.append("Proposal did not keep human_approval_required=true.")
        if _FORBIDDEN_RECOMMENDATION_RE.search(str(proposal.get("recommended_action") or "")):
            issues.append("Proposal recommended direct execution or approval bypass.")
        if not proposal.get("evidence_refs"):
            issues.append("Proposal omitted evidence references.")
        if not self._proposal_aligns_with_bundle(bundle=bundle, proposal=proposal):
            issues.append("Proposal does not align with deterministic failure evidence.")
        verdict = "accepted" if not issues else "needs_human_review"
        if any("does not align" in issue.lower() for issue in issues):
            verdict = "rejected"
        return Model2VerificationResult(
            verdict=verdict,
            evidence_alignment="aligned" if not issues else "mismatch",
            hallucination_check="passed" if not issues else "warning",
            policy_check="passed" if not issues else "failed",
            risk_level=str(proposal.get("risk_level") or "medium"),
            issues_found=tuple(issues),
            human_approval_required=True,
        ).to_dict()

    def _proposal_aligns_with_bundle(
        self,
        *,
        bundle: RunEvidenceBundle,
        proposal: dict[str, Any],
    ) -> bool:
        failure_type = str(proposal.get("failure_type") or "")
        bundle_failure_type = str((bundle.failure_bundle.failure_type if bundle.failure_bundle is not None else "") or "")
        if bundle_failure_type and failure_type and failure_type != bundle_failure_type:
            return False
        if failure_type == "invalid_maven_wildcard_version":
            joined = " ".join(str(item) for item in proposal.get("proposed_file_changes", []))
            return all(
                snippet in joined
                for snippet in ("3.1.0", "6.0.0")
            )
        return True

    def _model1_request(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        diagnosis: dict[str, Any],
        trace_root: Path | None,
    ) -> ModelInvocationRequest:
        return ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Create governed read-only repair proposal from verified migration failure evidence.",
            evidence_bundle=bundle.to_dict(),
            source_input=json.dumps(
                {
                    "question": question,
                    "supervision_purpose": "repair_proposal",
                    "diagnosis": diagnosis,
                    "failure_bundle": asdict(bundle.failure_bundle) if bundle.failure_bundle is not None else None,
                    "deterministic_failure_classification": bundle.deterministic_failure_classification,
                    "build_test_error_contracts": list(bundle.build_test_error_contracts[:_MAX_EVIDENCE]),
                    "relevant_log_excerpts": list(bundle.relevant_log_excerpts[:_MAX_EVIDENCE]),
                    "pom_excerpts": list(bundle.pom_excerpts[:_MAX_EVIDENCE]),
                    "allowed_action_constraints": {
                        "evidence_grounded_only": True,
                        "no_direct_execution": True,
                        "no_approval_bypass": True,
                        "no_source_or_sandbox_mutation": True,
                        "no_auto_apply": True,
                    },
                },
                sort_keys=True,
                default=str,
            ),
            correlation_id=f"{bundle.run_id}:repair:model1",
            supervision_context="repair_proposal",
            trace_root=str(trace_root) if trace_root is not None else "",
        )

    def _model2_request(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        proposal: dict[str, Any],
        trace_root: Path | None,
    ) -> ModelInvocationRequest:
        return ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify governed repair proposal against deterministic migration evidence and safety policy.",
            evidence_bundle=bundle.to_dict(),
            source_input=json.dumps(
                {
                    "question": question,
                    "supervision_purpose": "repair_proposal_verification",
                    "proposal": proposal,
                    "guardrails": {
                        "evidence_grounded_only": True,
                        "no_unsupported_claims": True,
                        "no_direct_execution": True,
                        "no_approval_bypass": True,
                        "no_source_or_sandbox_mutation": True,
                    },
                },
                sort_keys=True,
                default=str,
            ),
            model1_output=proposal,
            correlation_id=f"{bundle.run_id}:repair:model2",
            supervision_context="repair_proposal_verification",
            trace_root=str(trace_root) if trace_root is not None else "",
        )

    def _request_to_model_call_request(self, request: ModelInvocationRequest) -> ModelCallRequest:
        return ModelCallRequest(
            request_id=uuid4().hex,
            event_type="build_failed",
            prompt_template_id=request.supervision_context or request.objective,
            output_schema_name="GovernedRepairProposal" if request.role == MODEL_1_ROLE else "Model2VerificationResult",
            prompt_text=redact_model_summary(request.source_input),
            token_budget_input=20000,
            token_budget_output=6000 if request.role == MODEL_1_ROLE else 3000,
            context_pack_checksum=str(request.evidence_bundle.get("run_id") or "unknown"),
            created_at=utc_now_text(),
        )

    def _persist_trace_if_possible(
        self,
        *,
        request: ModelInvocationRequest,
        result: ModelInvocationResult,
    ) -> ModelInvocationResult:
        if not str(request.trace_root or "").strip():
            return result
        try:
            refs = self._trace_store.persist_trace(request=request, result=result)
        except Exception:
            return result
        return ModelInvocationResult(
            role=result.role,
            provider=result.provider,
            mode=result.mode,
            success=result.success,
            structured_output=result.structured_output,
            invocation_id=result.invocation_id,
            created_at=result.created_at,
            warnings=result.warnings,
            errors=result.errors,
            trace_artifact_refs=refs,
        )

    def _persist_proposal_artifacts(
        self,
        *,
        proposal_id: str,
        trace_root: Path | None,
        bundle: RunEvidenceBundle,
        diagnosis: dict[str, Any],
        proposal: dict[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, str]:
        if trace_root is None:
            return {}
        proposal_dir = trace_root / "ai_supervision" / "repair_proposals" / proposal_id
        proposal_dir.mkdir(parents=True, exist_ok=True)
        proposal_json = proposal_dir / "repair_proposal.json"
        verification_json = proposal_dir / "repair_verification.json"
        proposal_md = proposal_dir / "repair_proposal.md"
        proposal_payload = {
            "proposal_id": proposal_id,
            "run_id": bundle.run_id,
            "failure_type": proposal.get("failure_type"),
            "root_cause": proposal.get("root_cause"),
            "evidence_refs": proposal.get("evidence_refs"),
            "affected_paths": proposal.get("affected_paths"),
            "proposed_changes_summary": proposal.get("proposed_file_changes"),
            "validation_commands": proposal.get("validation_commands"),
            "rollback_plan": proposal.get("rollback_plan"),
            "model1_result": proposal,
            "model2_result": verification,
            "diagnosis": diagnosis,
            "manual_review_required": bool(proposal.get("manual_review_required", True)),
            "patch_candidate_supported": bool(proposal.get("patch_candidate_supported", False)),
            "human_approval_required": True,
            "no_auto_apply": True,
            "read_only": True,
            "source_mutated": bool(proposal.get("source_mutated", False)),
            "stage_resumed": bool(proposal.get("stage_resumed", False)),
            "sandbox_only": bool(proposal.get("sandbox_only", True)),
        }
        verification_payload = {
            "proposal_id": proposal_id,
            "run_id": bundle.run_id,
            "verification": verification,
            "human_approval_required": True,
            "no_auto_apply": True,
            "read_only": True,
        }
        proposal_json.write_text(json.dumps(proposal_payload, indent=2, sort_keys=True), encoding="utf-8")
        verification_json.write_text(json.dumps(verification_payload, indent=2, sort_keys=True), encoding="utf-8")
        proposal_md.write_text(self._proposal_markdown(proposal_id=proposal_id, proposal=proposal, verification=verification), encoding="utf-8")
        return {
            "repair_proposal_json": self._relative_path(proposal_json, trace_root),
            "repair_verification_json": self._relative_path(verification_json, trace_root),
            "repair_proposal_md": self._relative_path(proposal_md, trace_root),
        }

    def _proposal_markdown(
        self,
        *,
        proposal_id: str,
        proposal: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        changes = "\n".join(f"- {item}" for item in proposal.get("proposed_file_changes", [])) or "- none"
        commands = "\n".join(f"- {item}" for item in proposal.get("validation_commands", [])) or "- none"
        refs = "\n".join(f"- {item}" for item in proposal.get("evidence_refs", [])) or "- none"
        return (
            f"# Repair Proposal {proposal_id}\n\n"
            f"- Read only: true\n"
            f"- No auto apply: true\n"
            f"- Human approval required: true\n"
            f"- Failure type: {proposal.get('failure_type', '')}\n"
            f"- Root cause: {proposal.get('root_cause', '')}\n"
            f"- Risk level: {proposal.get('risk_level', '')}\n"
            f"- Model 2 verdict: {verification.get('verdict', '')}\n\n"
            f"## Evidence refs\n{refs}\n\n"
            f"## Proposed file changes\n{changes}\n\n"
            f"## Validation commands\n{commands}\n\n"
            f"## Rollback plan\n{proposal.get('rollback_plan', '')}\n"
        )

    def _trace_root(
        self,
        *,
        bundle: RunEvidenceBundle,
        setup: Any | None,
        trace_root: str | Path | None,
    ) -> Path | None:
        if trace_root not in (None, ""):
            resolved = infer_stage_run_root(Path(str(trace_root))) or Path(str(trace_root)).resolve()
            return resolved
        output_parent = str(getattr(setup, "output_parent_path", "") or "").strip()
        run_id = str(bundle.run_id or "").strip()
        if output_parent and run_id:
            candidates = [
                Path(output_parent) / ".migration" / "runs" / run_id,
                Path(output_parent) / ".migration" / "runs" / f"{run_id}-s1",
                Path(output_parent) / ".migration" / "runs" / f"{run_id}-s2",
                Path(output_parent) / ".migration" / "runs" / f"{run_id}-s3",
            ]
            for candidate in candidates:
                inferred = infer_stage_run_root(candidate)
                if inferred is not None:
                    return inferred
            return candidates[0].resolve()
        for candidate in self._bundle_trace_root_candidates(bundle=bundle):
            inferred = infer_stage_run_root(candidate)
            if inferred is not None:
                return inferred
        return None

    def _bundle_trace_root_candidates(self, *, bundle: RunEvidenceBundle) -> tuple[Path, ...]:
        candidates: list[Path] = []
        for item in bundle.generated_artifact_refs:
            if isinstance(item, dict):
                for key in ("path", "label", "source"):
                    value = str(item.get(key) or "").strip()
                    if value and ".migration" in value and "runs" in value:
                        candidates.append(Path(value))
        return tuple(candidates)

    def _diagnosis_payload(
        self,
        *,
        bundle: RunEvidenceBundle,
        diagnosis_review: dict[str, Any] | None,
        persisted_diagnosis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(diagnosis_review, dict) and diagnosis_review:
            return {
                "failure_type": diagnosis_review.get("root_cause") and (bundle.failure_bundle.failure_type if bundle.failure_bundle is not None else bundle.deterministic_failure_classification.get("failure_type") if isinstance(bundle.deterministic_failure_classification, dict) else ""),
                "root_cause": diagnosis_review.get("root_cause"),
                "confidence": diagnosis_review.get("confidence"),
                "model2_verdict": diagnosis_review.get("model2_verdict"),
                "evidence_refs": diagnosis_review.get("evidence_refs", []),
            }
        if isinstance(persisted_diagnosis, dict) and persisted_diagnosis:
            return {
                "failure_type": persisted_diagnosis.get("failure_type"),
                "root_cause": persisted_diagnosis.get("likely_root_cause"),
                "confidence": persisted_diagnosis.get("confidence"),
                "affected_paths": persisted_diagnosis.get("affected_paths", []),
            }
        if bundle.failure_bundle is not None:
            return {
                "failure_type": bundle.failure_bundle.failure_type,
                "root_cause": bundle.failure_bundle.root_cause,
                "confidence": bundle.failure_bundle.confidence,
                "affected_paths": list(bundle.failure_bundle.affected_paths),
            }
        return {}

    def _evidence_refs(self, bundle: RunEvidenceBundle) -> tuple[str, ...]:
        refs: list[str] = []
        for item in bundle.generated_artifact_refs:
            if isinstance(item, dict):
                text = str(item.get("label") or item.get("path") or "").strip()
                if text:
                    refs.append(text)
        for collection in (bundle.build_test_error_contracts, bundle.relevant_log_excerpts, bundle.pom_excerpts):
            for item in collection:
                label = str(item.get("label") or item.get("source") or "").strip()
                if label:
                    refs.append(label)
        deduped: list[str] = []
        for ref in refs:
            if ref not in deduped:
                deduped.append(ref)
        return tuple(deduped[:_MAX_EVIDENCE])

    def _render_answer(
        self,
        *,
        question: str,
        bundle: RunEvidenceBundle,
        proposal: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        if str(proposal.get("failure_type") or "") == "no_migration_failure":
            lines = [
                f"Question: {self._bounded(question, 160)}",
                f"Migration status: {bundle.migration_status}",
                "No migration repair is needed.",
                f"Root cause: {self._bounded(str(proposal.get('root_cause') or ''), 240)}",
                "Next operator action: inspect AI/model availability separately if needed.",
                "Safety: Read-only proposal check only. No commands executed. No approvals changed. No patch applied. No source or sandbox files modified.",
            ]
            return self._bounded("\n".join(lines), _MAX_TEXT)
        evidence = self._evidence_details(bundle)
        files = ", ".join(str(item) for item in proposal.get("affected_paths", [])) or "none"
        commands = "; ".join(str(item) for item in proposal.get("validation_commands", [])) or "none"
        issues = "; ".join(str(item) for item in verification.get("issues_found", [])) or "none"
        lines = [
            f"Question: {self._bounded(question, 160)}",
            f"Migration status: {bundle.migration_status}",
            "I prepared a repair proposal; I did not apply it.",
            f"Root cause: {self._bounded(str(proposal.get('root_cause') or ''), 240)}",
            f"Failure type: {proposal.get('failure_type') or 'unknown'}",
            f"Confidence: {proposal.get('confidence') or 'low'}",
            f"Proposed fix summary: {self._bounded(str(proposal.get('summary') or ''), 260)}",
            f"Risk level: {proposal.get('risk_level') or 'unknown'}",
            f"Model 2 verdict: {verification.get('verdict') or 'needs_human_review'}",
            f"Files likely affected: {files}",
            f"Validation commands: {commands}",
        ]
        if evidence:
            lines.append(f"Evidence: {evidence}")
        if verification.get("verdict") != "accepted":
            lines.append(f"Verifier issues: {self._bounded(issues, 320)}")
            lines.append("This proposal needs human review before it should be treated as safe.")
        lines.append("Next operator action: review and approve proposal before any future patch/apply phase.")
        lines.append("Safety: Proposal only. No commands executed. No approvals changed. No patch applied. No source or sandbox files modified.")
        return self._bounded("\n".join(lines), _MAX_TEXT)

    def _evidence_details(self, bundle: RunEvidenceBundle) -> str:
        parts: list[str] = []
        for collection in (bundle.build_test_error_contracts, bundle.relevant_log_excerpts, bundle.pom_excerpts):
            for item in collection[:2]:
                text = str(item.get("text") or "")
                label = str(item.get("label") or item.get("source") or "evidence").strip()
                compressed = self._compress_evidence_text(text)
                if compressed:
                    parts.append(f"{label}: {compressed}")
        deduped: list[str] = []
        for part in parts:
            if part not in deduped:
                deduped.append(part)
        return self._bounded("; ".join(deduped[:6]), 520)

    def _compress_evidence_text(self, text: str) -> str:
        coords = _MAVEN_COORD_RE.findall(text)
        props = _PROPERTY_RE.findall(text)
        fragments: list[str] = []
        for item in coords + props:
            if item not in fragments:
                fragments.append(item)
        if "BUILD_FAILED_IN_SANDBOX" in text and "BUILD_FAILED_IN_SANDBOX" not in fragments:
            fragments.append("BUILD_FAILED_IN_SANDBOX")
        if fragments:
            return "; ".join(fragments[:6])
        return self._bounded(text, 180)

    def _live_ready(self, *, role: str) -> bool:
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get(
            "AZURE_OPENAI_PROPOSER_DEPLOYMENT" if role == "proposer" else "AZURE_OPENAI_REVIEWER_DEPLOYMENT",
            "",
        ).strip()
        return bool(endpoint and api_key and deployment)

    def _fallback_warnings(self, *, role: str) -> tuple[str, ...]:
        deployment_name = "Model 1" if role == "proposer" else "Model 2"
        return (f"{deployment_name} live deployment not configured; deterministic fallback used.",)

    def _fallback_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip():
            errors.append("Azure OpenAI endpoint not configured.")
        if not os.environ.get("AZURE_OPENAI_API_KEY", "").strip():
            errors.append("Azure OpenAI API key not configured.")
        return tuple(errors)

    def _relative_path(self, path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.name

    def _bounded(self, text: str, limit: int) -> str:
        clean = redact_model_summary(str(text or "")).strip()
        if len(clean) <= limit:
            return clean
        return clean[:limit] + "...[truncated]"
