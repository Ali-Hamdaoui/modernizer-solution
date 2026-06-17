"""Governed persisted-diagnosis -> proposal -> reviewer flow."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from migration_factory.control_tower.application.redaction import redact_public_value
from migration_factory.control_tower.application.v2_assistant_model_client import (
    V2AssistantModelClient,
)
from migration_factory.control_tower.application.v2_model_schemas import ContextPack
from migration_factory.control_tower.application.v2_prompt_router import (
    EventPromptRouter,
    ModelCallRequest,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    RepairProposal,
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    ReviewerCritique,
    V2ReviewerService,
)
from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_failure_diagnosis_repository import (
    SqliteV2FailureDiagnosisRepository,
    V2FailureDiagnosisPersistedRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
)


ModelRole = Literal["proposer", "reviewer"]

_REVIEWER_UNSAFE_INTENT_RE = re.compile(
    r"(?i)\b(apply(?:\s+the)?\s+patch|execute(?:\s+the)?\s+command|run\s+the\s+command|approve(?:\s+this|\s+the)?\s+proposal)\b"
)


class RawStructuredModelClientProtocol(Protocol):
    def answer(self, *, prompt: str, fallback: str) -> Any:
        ...


class StructuredModelClient(Protocol):
    role: ModelRole

    def invoke(
        self,
        *,
        request: ModelCallRequest,
        schema_name: str,
    ) -> "StructuredModelCallResult":
        ...


@dataclass(frozen=True)
class StructuredModelCallResult:
    request_id: str
    output_schema_name: str
    validated_output: dict[str, Any]
    role: ModelRole
    provider: str
    deployment_label: str
    model_invocation_id: str
    source: str
    model_status: str
    success: bool
    compatibility_mode: str
    failure_reason: str = ""


class RoleAwareStructuredModelClient:
    """Role-specific structured model client with fail-closed parsing."""

    def __init__(
        self,
        raw_client: RawStructuredModelClientProtocol,
        *,
        role: ModelRole,
        compatibility_mode: str = "strict_role_separation",
        force_generic_answer: bool = False,
    ) -> None:
        self._raw_client = raw_client
        self.role = role
        self.compatibility_mode = compatibility_mode
        self._force_generic_answer = force_generic_answer

    def invoke(
        self,
        *,
        request: ModelCallRequest,
        schema_name: str,
    ) -> StructuredModelCallResult:
        result = self._call_raw_client(request.prompt_text)
        if not getattr(result, "success", False):
            raise ValueError(
                f"{self.role} model call failed for {schema_name}: "
                f"{getattr(result, 'failure_reason', 'unavailable') or 'unavailable'}"
            )
        parsed = _parse_json_object(str(getattr(result, "content", "")))
        validated = EventPromptRouter.validate_model_output(schema_name, parsed)
        if not validated.success:
            raise ValueError(validated.failure_reason or f"Invalid {schema_name} output")
        validated_output = dict(validated.validated_output)
        _enforce_role_policy(role=self.role, schema_name=schema_name, output=validated_output)
        return StructuredModelCallResult(
            request_id=request.request_id,
            output_schema_name=schema_name,
            validated_output=validated_output,
            role=self.role,
            provider=str(getattr(result, "provider", "unknown")),
            deployment_label=str(getattr(result, "deployment_label", "")),
            model_invocation_id=str(getattr(result, "model_invocation_id", "")) or f"{self.role}-{request.request_id}",
            source=str(getattr(result, "source", "unknown")),
            model_status=str(getattr(result, "model_status", "unknown")),
            success=True,
            compatibility_mode=self.compatibility_mode,
        )

    def _call_raw_client(self, prompt: str) -> Any:
        if (
            hasattr(self._raw_client, "answer_for_role")
            and callable(getattr(self._raw_client, "answer_for_role"))
            and not self._force_generic_answer
        ):
            return self._raw_client.answer_for_role(prompt=prompt, fallback="", role=self.role)
        return self._raw_client.answer(prompt=prompt, fallback="")


def build_default_structured_model_clients(
    raw_client: RawStructuredModelClientProtocol,
) -> tuple[StructuredModelClient, StructuredModelClient]:
    if isinstance(raw_client, V2AssistantModelClient):
        proposer_deployment = os.environ.get("AZURE_OPENAI_PROPOSER_DEPLOYMENT", "").strip()
        reviewer_deployment = os.environ.get("AZURE_OPENAI_REVIEWER_DEPLOYMENT", "").strip()
        compatibility_mode = (
            "shared_live_deployment"
            if proposer_deployment and reviewer_deployment and proposer_deployment == reviewer_deployment
            else "strict_role_separation"
        )
        return (
            RoleAwareStructuredModelClient(
                raw_client,
                role="proposer",
                compatibility_mode=compatibility_mode,
            ),
            RoleAwareStructuredModelClient(
                raw_client,
                role="reviewer",
                compatibility_mode=compatibility_mode,
            ),
        )
    return (
        RoleAwareStructuredModelClient(
            raw_client,
            role="proposer",
            compatibility_mode="development_shared_raw_client",
            force_generic_answer=True,
        ),
        RoleAwareStructuredModelClient(
            raw_client,
            role="reviewer",
            compatibility_mode="development_shared_raw_client",
            force_generic_answer=True,
        ),
    )


@dataclass(frozen=True)
class DiagnosisProposalFlowResult:
    diagnosis_id: str
    diagnosis_checksum: str
    evidence_pack_checksum: str
    context_pack_checksum: str
    proposal: RepairProposal
    proposal_checksum: str
    model_request: ModelCallRequest
    model_call: StructuredModelCallResult


@dataclass(frozen=True)
class DiagnosisProposalReviewResult:
    proposal: RepairProposal
    critique: ReviewerCritique
    model_request: ModelCallRequest
    model_call: StructuredModelCallResult


class V2DiagnosisProposalFlowService:
    def __init__(
        self,
        *,
        diagnosis_repo: SqliteV2FailureDiagnosisRepository,
        repair_repo: SqliteV2RepairRepository | None = None,
        repair_flow: V2RepairFlowService | None = None,
        reviewer_service: V2ReviewerService | None = None,
        proposer_client: StructuredModelClient | None = None,
        reviewer_client: StructuredModelClient | None = None,
        model_client: StructuredModelClient | None = None,
        proposal_model_client: StructuredModelClient | None = None,
        reviewer_model_client: StructuredModelClient | None = None,
    ) -> None:
        self._diagnosis_repo = diagnosis_repo
        self._repair_repo = repair_repo
        self._repair_flow = repair_flow or V2RepairFlowService(repair_repo=repair_repo)
        self._reviewer_service = reviewer_service or V2ReviewerService()
        compatibility_client = proposer_client or proposal_model_client or model_client
        self._proposer_client = compatibility_client
        self._reviewer_client = reviewer_client or reviewer_model_client or model_client

    def create_repair_proposal(
        self,
        *,
        diagnosis_id: str | None = None,
        job_id: str | None = None,
        stage_index: int | None = None,
    ) -> DiagnosisProposalFlowResult:
        diagnosis = self._load_diagnosis(
            diagnosis_id=diagnosis_id,
            job_id=job_id,
            stage_index=stage_index,
        )
        if self._proposer_client is None:
            raise ValueError("Proposer client is not configured")
        _require_non_empty_binding("diagnosis_checksum", diagnosis.diagnosis_checksum)
        _require_non_empty_binding("evidence_pack_checksum", diagnosis.evidence_pack_checksum)
        _require_non_empty_binding("context_pack_checksum", diagnosis.context_pack_checksum)

        pack = self._build_diagnosis_context_pack(diagnosis)
        request = EventPromptRouter.route(
            event_type=diagnosis.event_type,
            pack=pack,
            payload=self._proposal_payload(diagnosis, pack),
        )
        model_call = self._proposer_client.invoke(
            request=request,
            schema_name="RepairProposal",
        )
        output = model_call.validated_output
        proposal = self._repair_flow.create_proposal(
            command_id=diagnosis.command_id,
            failure_summary=_bounded_failure_summary(diagnosis),
            hypothesis=str(output["failure_hypothesis"]),
            patch_summary=str(output["patch_summary"]),
            affected_paths=tuple(str(path) for path in output["affected_paths"]),
            validation_plan=str(output["validation_plan"]),
            diagnosis_id=diagnosis.diagnosis_id,
            diagnosis_checksum=diagnosis.diagnosis_checksum,
            evidence_pack_checksum=diagnosis.evidence_pack_checksum,
            context_pack_checksum=diagnosis.context_pack_checksum,
            proposer_model_invocation_id=model_call.model_invocation_id,
            proposer_model_role=model_call.role,
            proposer_model_provider=model_call.provider,
            proposer_deployment_label=model_call.deployment_label,
        )
        return DiagnosisProposalFlowResult(
            diagnosis_id=diagnosis.diagnosis_id,
            diagnosis_checksum=diagnosis.diagnosis_checksum,
            evidence_pack_checksum=diagnosis.evidence_pack_checksum,
            context_pack_checksum=diagnosis.context_pack_checksum,
            proposal=proposal,
            proposal_checksum=proposal.proposal_checksum,
            model_request=request,
            model_call=model_call,
        )

    def review_repair_proposal(self, proposal_id: str) -> DiagnosisProposalReviewResult:
        if self._reviewer_client is None:
            raise ValueError("Reviewer client is not configured")
        proposal = self._load_proposal(proposal_id)
        _require_non_empty_binding("proposal_checksum", proposal.proposal_checksum)
        _require_non_empty_binding("context_pack_checksum", proposal.context_pack_checksum or "")
        if proposal.diagnosis_id:
            _require_non_empty_binding("diagnosis_checksum", proposal.diagnosis_checksum)
            _require_non_empty_binding("evidence_pack_checksum", proposal.evidence_pack_checksum)
        diagnosis = (
            self._diagnosis_repo.get_by_id(proposal.diagnosis_id)
            if proposal.diagnosis_id
            else None
        )
        pack = self._build_review_context_pack(proposal, diagnosis)
        request = EventPromptRouter.route(
            event_type="review_requested",
            pack=pack,
            payload=self._review_payload(proposal, diagnosis, pack),
        )
        model_call = self._reviewer_client.invoke(
            request=request,
            schema_name="ReviewerCritique",
        )
        output = model_call.validated_output
        critique = self._reviewer_service.record_critique(
            proposal_id=proposal.proposal_id,
            proposal_type="repair",
            proposal_checksum=proposal.proposal_checksum,
            context_pack_checksum=proposal.context_pack_checksum or "",
            decision=str(output["decision"]),
            reasoning=str(output["reasoning"]),
            missing_evidence=tuple(str(item) for item in output.get("missing_evidence", [])),
            unsafe_assumptions=tuple(str(item) for item in output.get("unsafe_assumptions", [])),
            model_invocation_id=model_call.model_invocation_id,
            model_role=model_call.role,
            model_provider=model_call.provider,
            deployment_label=model_call.deployment_label,
        )
        return DiagnosisProposalReviewResult(
            proposal=proposal,
            critique=critique,
            model_request=request,
            model_call=model_call,
        )

    @staticmethod
    def proposal_record_to_dict(record: V2RepairProposalRecord) -> dict[str, Any]:
        proposal = V2RepairFlowService.record_to_proposal(record)
        return V2RepairFlowService().proposal_to_dict(proposal)

    def _load_diagnosis(
        self,
        *,
        diagnosis_id: str | None,
        job_id: str | None,
        stage_index: int | None,
    ) -> V2FailureDiagnosisPersistedRecord:
        diagnosis = None
        if diagnosis_id:
            diagnosis = self._diagnosis_repo.get_by_id(diagnosis_id)
        elif job_id:
            diagnosis = self._diagnosis_repo.get_latest_for_job(job_id, stage_index=stage_index)
        if diagnosis is None:
            raise ValueError("Persisted diagnosis not found")
        return diagnosis

    def _load_proposal(self, proposal_id: str) -> RepairProposal:
        if self._repair_repo is None:
            raise ValueError("Repair repository is not configured")
        record = self._repair_repo.get_proposal(proposal_id)
        if record is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        return V2RepairFlowService.record_to_proposal(record)

    def _build_diagnosis_context_pack(self, diagnosis: V2FailureDiagnosisPersistedRecord) -> ContextPack:
        evidence = _load_json_list(diagnosis.evidence_json)
        evidence_refs = tuple(
            _bounded_text(
                f"{item.get('label') or item.get('source')}: {item.get('text', '')}",
                220,
            )
            for item in evidence[:3]
            if isinstance(item, dict)
        ) or ("no_evidence_refs",)
        return ContextPack(
            pack_id=f"diagnosis-{diagnosis.diagnosis_id}",
            pack_type="repair_proposal",
            title=f"Persisted diagnosis {diagnosis.failure_type}",
            description=_bounded_failure_summary(diagnosis),
            evidence_refs=evidence_refs,
            token_budget_input=20000,
            token_budget_output=6000,
            checksum=diagnosis.context_pack_checksum,
            created_at=utc_now_text(),
            agent_name="v2-diagnosis-proposal-flow",
            event_type=diagnosis.event_type,
            stage_index=diagnosis.stage_index,
            command_id=diagnosis.command_id,
            failure_type=diagnosis.failure_type,
            redaction_status=diagnosis.redaction_status,
        )

    def _build_review_context_pack(
        self,
        proposal: RepairProposal,
        diagnosis: V2FailureDiagnosisPersistedRecord | None,
    ) -> ContextPack:
        evidence_refs = ["proposal_checksum_bound", f"proposal_status={proposal.status}"]
        if diagnosis is not None:
            evidence_refs.append(f"diagnosis_checksum={diagnosis.diagnosis_checksum}")
            evidence_refs.append(f"evidence_pack_checksum={diagnosis.evidence_pack_checksum}")
        return ContextPack(
            pack_id=f"proposal-{proposal.proposal_id}",
            pack_type="reviewer_critique",
            title="Repair proposal review",
            description=_bounded_text(proposal.patch_summary, 300),
            evidence_refs=tuple(evidence_refs),
            token_budget_input=16000,
            token_budget_output=4000,
            checksum=proposal.context_pack_checksum or (diagnosis.context_pack_checksum if diagnosis is not None else ""),
            created_at=utc_now_text(),
            agent_name="v2-reviewer-flow",
            event_type="review_requested",
            command_id=proposal.command_id,
            redaction_status="redacted",
        )

    def _proposal_payload(
        self,
        diagnosis: V2FailureDiagnosisPersistedRecord,
        pack: ContextPack,
    ) -> dict[str, Any]:
        evidence = _load_json_list(diagnosis.evidence_json)
        refs = tuple(
            _bounded_text(str(item.get("text", "")), 180)
            for item in evidence[:3]
            if isinstance(item, dict)
        )
        return {
            "event_type": diagnosis.event_type,
            "stage_index": diagnosis.stage_index,
            "failure_summary": _bounded_failure_summary(diagnosis),
            "evidence_refs": ", ".join(refs or pack.evidence_refs),
            "context_pack_checksum": diagnosis.context_pack_checksum,
            "pom_summary_ref": "persisted_diagnosis",
            "sandbox_binding_ref": "backend_owned_only",
        }

    def _review_payload(
        self,
        proposal: RepairProposal,
        diagnosis: V2FailureDiagnosisPersistedRecord | None,
        pack: ContextPack,
    ) -> dict[str, Any]:
        evidence_refs = []
        if diagnosis is not None:
            evidence_refs.append(f"diagnosis_id={diagnosis.diagnosis_id}")
            evidence_refs.append(f"diagnosis_checksum={diagnosis.diagnosis_checksum}")
            evidence_refs.append(f"evidence_pack_checksum={diagnosis.evidence_pack_checksum}")
        evidence_refs.append(f"proposal_checksum={proposal.proposal_checksum}")
        return {
            "event_type": "review_requested",
            "stage_index": diagnosis.stage_index if diagnosis is not None else 1,
            "failure_summary": _bounded_text(proposal.patch_summary, 240),
            "evidence_refs": ", ".join(evidence_refs or pack.evidence_refs),
            "sandbox_binding_ref": "backend_owned_only",
            "pom_summary_ref": "persisted_diagnosis" if diagnosis is not None else "none",
            "safety_policy": (
                "No patch application. No command execution. "
                "No legacy source mutation. Human approval required before any apply path."
            ),
            "proposal_checksum": proposal.proposal_checksum,
            "context_pack_checksum": proposal.context_pack_checksum or "",
        }


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", str(content))
    if match is not None:
        parsed = json.loads(match.group(1).strip())
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("Model output is not valid JSON object")


def _load_json_list(raw: str) -> list[Any]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _bounded_text(value: str, limit: int) -> str:
    clean = str(redact_public_value(value or "")).strip()
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "...[truncated]"


def _bounded_failure_summary(diagnosis: V2FailureDiagnosisPersistedRecord) -> str:
    return _bounded_text(
        f"{diagnosis.failure_type}: {diagnosis.likely_root_cause}",
        320,
    )


def _require_non_empty_binding(name: str, value: str) -> None:
    if not str(value or "").strip():
        raise ValueError(f"Missing required checksum binding: {name}")


def _enforce_role_policy(
    *,
    role: ModelRole,
    schema_name: str,
    output: dict[str, Any],
) -> None:
    if role != "reviewer" or schema_name != "ReviewerCritique":
        return
    text_fragments = [str(output.get("reasoning", ""))]
    text_fragments.extend(str(item) for item in output.get("missing_evidence", []) if isinstance(item, str))
    text_fragments.extend(str(item) for item in output.get("unsafe_assumptions", []) if isinstance(item, str))
    joined = "\n".join(text_fragments)
    if _REVIEWER_UNSAFE_INTENT_RE.search(joined):
        raise ValueError("Reviewer output contains forbidden approve/apply/execute intent")
