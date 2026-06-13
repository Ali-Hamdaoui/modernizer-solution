"""V2 assistant chat — read-only guidance, instruction drafts, pending actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import utc_now_text
from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_model_schemas import (
    ContextPackBuilder,
    ContextPack,
)


FORBIDDEN_CAPABILITIES = (
    "execute_command",
    "approve_decision",
    "write_file",
    "change_route",
    "change_stage",
    "choose_maven_goal",
    "choose_deployment",
    "override_proof",
)

ALLOWED_TOOLS = (
    "explain_status",
    "summarize_evidence",
    "diagnose_failure",
    "draft_plan_instruction",
    "draft_repair_instruction",
    "request_action",
    "show_context",
)


@dataclass(frozen=True)
class AssistantMessage:
    message_id: str
    job_id: str
    role: str  # user, assistant, system
    content: str
    correlation_id: str | None
    created_at: str


@dataclass(frozen=True)
class PendingActionDraft:
    action_id: str
    job_id: str
    action_type: str
    reason: str
    stage_index: int
    payload_checksum: str
    status: str  # draft, submitted
    created_at: str


class V2AssistantService:
    """Read-only assistant chat with action drafting capability.

    The assistant can:
    - Explain status, summarize evidence, diagnose failures
    - Draft plan/repair instructions
    - Request pending typed actions

    The assistant CANNOT:
    - Execute commands, approve decisions, write files
    - Change route, stages, or override proof
    """

    def __init__(self) -> None:
        self._messages: dict[str, AssistantMessage] = {}
        self._drafts: dict[str, PendingActionDraft] = {}

    def add_message(
        self,
        job_id: str,
        role: str,
        content: str,
        correlation_id: str | None = None,
    ) -> AssistantMessage:
        msg = AssistantMessage(
            message_id=uuid4().hex,
            job_id=job_id,
            role=role,
            content=content,
            correlation_id=correlation_id,
            created_at=utc_now_text(),
        )
        self._messages[msg.message_id] = msg
        return msg

    def draft_action(
        self,
        job_id: str,
        action_type: str,
        reason: str,
        stage_index: int = 1,
    ) -> PendingActionDraft:
        """Create a pending action draft (does NOT execute)."""
        draft = PendingActionDraft(
            action_id=uuid4().hex,
            job_id=job_id,
            action_type=action_type,
            reason=reason,
            stage_index=stage_index,
            payload_checksum=f"draft-{uuid4().hex[:8]}",
            status="draft",
            created_at=utc_now_text(),
        )
        self._drafts[draft.action_id] = draft
        return draft

    def summarize_context(
        self,
        pack_type: str,
        title: str,
        description: str,
        evidence_refs: tuple[str, ...],
    ) -> ContextPack:
        """Build a redacted context pack for the assistant."""
        return ContextPackBuilder.build_context_pack(
            pack_type=pack_type,
            title=title,
            description=description,
            evidence_refs=evidence_refs,
        )

    def get_messages(self, job_id: str) -> tuple[AssistantMessage, ...]:
        return tuple(
            m for m in self._messages.values() if m.job_id == job_id
        )

    def get_drafts(self, job_id: str) -> tuple[PendingActionDraft, ...]:
        return tuple(
            d for d in self._drafts.values() if d.job_id == d.job_id
        )

    def message_to_dict(self, msg: AssistantMessage) -> dict[str, Any]:
        return {
            "message_id": msg.message_id,
            "job_id": msg.job_id,
            "role": msg.role,
            "content": redact_model_summary(msg.content),
            "correlation_id": msg.correlation_id,
            "created_at": msg.created_at,
        }

    def draft_to_dict(self, draft: PendingActionDraft) -> dict[str, Any]:
        return {
            "action_id": draft.action_id,
            "job_id": draft.job_id,
            "action_type": draft.action_type,
            "reason": draft.reason,
            "stage_index": draft.stage_index,
            "payload_checksum": draft.payload_checksum,
            "status": draft.status,
            "created_at": draft.created_at,
        }
