"""V2 repair/proposal flow — failed stage evidence to bounded repair."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
    V2SandboxActionRecord,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.repair_loop.ledger import (
    append_attempt,
    base_attempt,
    new_ledger,
    write_patch_draft,
    write_ledger,
    write_patch_attempt_result,
)
from migration_factory.repair_loop.patch_apply import apply_patch_to_sandbox, rollback_patch
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal
from migration_factory.repair_loop.validation_runner import (
    ValidationResult,
    run_validation_after_patch,
)


ValidationRunner = Callable[..., ValidationResult]
RepairEventRecorder = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class RepairProposal:
    proposal_id: str
    command_id: str
    failure_summary: str
    hypothesis: str
    patch_summary: str
    affected_paths: tuple[str, ...]
    status: str  # draft, proposed, approved, rejected, applied
    approval_checksum: str | None
    created_at: str
    proposal_checksum: str = ""
    # F05: revision metadata (None for non-revision proposals)
    source_proposal_id: str | None = None
    revision_of: str | None = None
    revision_number: int | None = None
    context_pack_checksum: str | None = None
    allowed_scope: str | None = None


@dataclass(frozen=True)
class SandboxAction:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str  # pending, applied, failed, rolled_back
    result_summary: str
    created_at: str


class V2RepairFlowService:
    """Convert failed command evidence into repair proposals and actions.

    - Proposal created from failure context
    - Approval with checksum required before patch application
    - Reviewer critique gate: approval requires latest accepted critique
      matching current proposal_checksum and context_pack_checksum (F07)
    - Actions are sandbox-only (no legacy source mutation)
    - Rollback on failure
    """

    def __init__(
        self,
        repair_repo: SqliteV2RepairRepository | None = None,
        reviewer_service: V2ReviewerService | None = None,
    ) -> None:
        self._proposals: dict[str, RepairProposal] = {}
        self._actions: dict[str, SandboxAction] = {}
        self._repo = repair_repo
        self._reviewer = reviewer_service or V2ReviewerService()

    def create_proposal(
        self,
        command_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
    ) -> RepairProposal:
        proposal_checksum = self._proposal_checksum(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
        )
        proposal = RepairProposal(
            proposal_id=uuid4().hex,
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            status="draft",
            approval_checksum=None,
            created_at=utc_now_text(),
            proposal_checksum=proposal_checksum,
        )
        self._proposals[proposal.proposal_id] = proposal
        # Persist if repo available
        if self._repo is not None:
            record = V2RepairProposalRecord(
                proposal_id=proposal.proposal_id,
                command_id=proposal.command_id,
                failure_summary=proposal.failure_summary,
                hypothesis=proposal.hypothesis,
                patch_summary=proposal.patch_summary,
                affected_paths_json=json.dumps(list(proposal.affected_paths), separators=(",", ":")),
                status=proposal.status,
                approval_checksum=proposal.approval_checksum,
                created_at=proposal.created_at,
                proposal_checksum=proposal.proposal_checksum,
                source_proposal_id=proposal.source_proposal_id,
                revision_of=proposal.revision_of,
                revision_number=proposal.revision_number,
                context_pack_checksum=proposal.context_pack_checksum,
                allowed_scope=proposal.allowed_scope,
            )
            self._repo.save_proposal(record)
        return proposal

    def create_revision_proposal(
        self,
        *,
        command_id: str,
        source_proposal_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
        revision_instruction: str = "",
        context_pack_checksum: str = "",
        allowed_scope: str = "any",
        revision_number: int = 1,
    ) -> RepairProposal:
        """Create a revised proposal draft from a source proposal.

        F05: Never mutates the source proposal. The new proposal is a
        separate draft with revision metadata linking back to the source.
        The caller must first validate binding via V2AssistantActionResolver.
        """
        proposal_checksum = self._proposal_checksum(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            source_proposal_id=source_proposal_id,
            revision_of=source_proposal_id,
            revision_number=revision_number,
            context_pack_checksum=context_pack_checksum,
            allowed_scope=allowed_scope,
        )
        proposal = RepairProposal(
            proposal_id=uuid4().hex,
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            status="draft",
            approval_checksum=None,
            created_at=utc_now_text(),
            proposal_checksum=proposal_checksum,
            source_proposal_id=source_proposal_id,
            revision_of=source_proposal_id,
            revision_number=revision_number,
            context_pack_checksum=context_pack_checksum,
            allowed_scope=allowed_scope,
        )
        self._proposals[proposal.proposal_id] = proposal
        if self._repo is not None:
            record = V2RepairProposalRecord(
                proposal_id=proposal.proposal_id,
                command_id=proposal.command_id,
                failure_summary=proposal.failure_summary,
                hypothesis=proposal.hypothesis,
                patch_summary=proposal.patch_summary,
                affected_paths_json=json.dumps(list(proposal.affected_paths), separators=(",", ":")),
                status=proposal.status,
                approval_checksum=proposal.approval_checksum,
                created_at=proposal.created_at,
                proposal_checksum=proposal.proposal_checksum,
                source_proposal_id=proposal.source_proposal_id,
                revision_of=proposal.revision_of,
                revision_number=proposal.revision_number,
                context_pack_checksum=proposal.context_pack_checksum,
                allowed_scope=proposal.allowed_scope,
            )
            self._repo.save_proposal(record)
        return proposal

    def approve_proposal(
        self,
        proposal_id: str,
        approval_checksum: str,
        *,
        proposal_checksum: str,
        context_pack_checksum: str,
        reviewer_critique_id: str | None = None,
    ) -> RepairProposal:
        """Approve a repair proposal.

        F07: Requires reviewer gate — a latest accepted critique must match
        the given proposal_checksum and context_pack_checksum. No bypass.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = RepairProposal(
                    proposal_id=record.proposal_id,
                    command_id=record.command_id,
                    failure_summary=record.failure_summary,
                    hypothesis=record.hypothesis,
                    patch_summary=record.patch_summary,
                    affected_paths=tuple(json.loads(record.affected_paths_json)),
                    status=record.status,
                    approval_checksum=record.approval_checksum,
                    created_at=record.created_at,
                    proposal_checksum=record.proposal_checksum
                    or self._proposal_checksum(
                        command_id=record.command_id,
                        failure_summary=record.failure_summary,
                        hypothesis=record.hypothesis,
                        patch_summary=record.patch_summary,
                        affected_paths=tuple(json.loads(record.affected_paths_json)),
                        source_proposal_id=record.source_proposal_id,
                        revision_of=record.revision_of,
                        revision_number=record.revision_number,
                        context_pack_checksum=record.context_pack_checksum,
                        allowed_scope=record.allowed_scope,
                    ),
                    source_proposal_id=record.source_proposal_id,
                    revision_of=record.revision_of,
                    revision_number=record.revision_number,
                    context_pack_checksum=record.context_pack_checksum,
                    allowed_scope=record.allowed_scope,
                )
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status != "draft":
            raise ValueError(f"Proposal {proposal_id!r} is already {proposal.status}")

        # F07: Reviewer gate — mandatory. Requires latest accepted critique
        # matching the current proposal_checksum and context_pack_checksum.
        accepted = self._reviewer.check_reviewer_gate(
            proposal_id=proposal_id,
            proposal_checksum=proposal_checksum,
            context_pack_checksum=context_pack_checksum,
        )
        if accepted is None:
            raise ValueError(
                f"Proposal {proposal_id!r} blocked by reviewer gate: "
                f"no accepted critique matches current proposal_checksum "
                f"{proposal_checksum!r} and context_pack_checksum "
                f"{context_pack_checksum!r}"
            )
        reviewer_critique_id = accepted.critique_id

        updated = RepairProposal(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            failure_summary=proposal.failure_summary,
            hypothesis=proposal.hypothesis,
            patch_summary=proposal.patch_summary,
            affected_paths=proposal.affected_paths,
            status="approved",
            approval_checksum=approval_checksum,
            created_at=proposal.created_at,
            proposal_checksum=proposal.proposal_checksum,
        )
        self._proposals[proposal_id] = updated
        # Persist if repo available
        if self._repo is not None:
            self._repo.update_proposal_status(proposal_id, "approved", approval_checksum)
        return updated

    def apply_patch(
        self,
        proposal_id: str,
        target_path: str,
        patch_content: str,
        *,
        run_dir: str | Path,
        sandbox_path: str | Path,
        legacy_path: str | Path,
        deterministic_rule_id: str,
        risk: str = "LOW",
        requires_human_review: bool = False,
        expected_validation: tuple[str, ...] = (),
        limitations: tuple[str, ...] = (),
        failure_classification: dict[str, Any] | None = None,
        h2_required: bool = False,
        run_id: str = "",
        binding_checksum: str | None = None,
        validation_runner: ValidationRunner = run_validation_after_patch,
        event_recorder: RepairEventRecorder | None = None,
    ) -> SandboxAction:
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = RepairProposal(
                    proposal_id=record.proposal_id,
                    command_id=record.command_id,
                    failure_summary=record.failure_summary,
                    hypothesis=record.hypothesis,
                    patch_summary=record.patch_summary,
                    affected_paths=tuple(json.loads(record.affected_paths_json)),
                    status=record.status,
                    approval_checksum=record.approval_checksum,
                    created_at=record.created_at,
                    proposal_checksum=record.proposal_checksum
                    or self._proposal_checksum(
                        command_id=record.command_id,
                        failure_summary=record.failure_summary,
                        hypothesis=record.hypothesis,
                        patch_summary=record.patch_summary,
                        affected_paths=tuple(json.loads(record.affected_paths_json)),
                        source_proposal_id=record.source_proposal_id,
                        revision_of=record.revision_of,
                        revision_number=record.revision_number,
                        context_pack_checksum=record.context_pack_checksum,
                        allowed_scope=record.allowed_scope,
                    ),
                    source_proposal_id=record.source_proposal_id,
                    revision_of=record.revision_of,
                    revision_number=record.revision_number,
                    context_pack_checksum=record.context_pack_checksum,
                    allowed_scope=record.allowed_scope,
                )
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal_id!r} must be approved first")

        run_path = Path(run_dir)
        resolved_run_id = run_id or proposal.command_id
        classification = dict(failure_classification or {})
        failure_type = str(classification.get("failure_type") or proposal.failure_summary or "V2_REPAIR_PROPOSAL")
        artifact_refs: dict[str, str] = {}
        ledger = new_ledger(
            run_id=resolved_run_id,
            enabled=True,
            auto_apply_enabled=False,
            max_attempts=1,
            artifact_refs=artifact_refs,
        )
        ledger_ref = write_ledger(run_path, ledger)
        artifact_refs["repair_ledger"] = str(ledger_ref)

        attempt = base_attempt(
            attempt=1,
            failure_type=failure_type,
            classification_ref="",
            repair_plan_ref=proposal.proposal_id,
        )
        if binding_checksum:
            attempt["binding_checksum"] = binding_checksum
        attempt["proposal_id"] = proposal.proposal_id

        repair_loop_proposal = {
            "proposal_id": proposal.proposal_id,
            "deterministic_rule_id": deterministic_rule_id,
            "risk": risk,
            "requires_human_review": requires_human_review,
            "description": proposal.hypothesis,
            "unified_diff": patch_content,
            "expected_validation": list(expected_validation),
            "limitations": list(limitations),
        }
        repair_proposal_checksum = sha256_canonical_json(repair_loop_proposal)
        draft_path = write_patch_draft(
            run_dir=run_path,
            attempt=1,
            payload={
                "schema_version": "1.0",
                "repair_proposal_checksum": repair_proposal_checksum,
                **repair_loop_proposal,
            },
        )
        artifact_refs["repair_patch_draft"] = str(draft_path)
        gate = evaluate_patch_proposal(
            proposal=repair_loop_proposal,
            sandbox_path=sandbox_path,
            run_dir=run_path,
            legacy_path=legacy_path,
            failure_classification=classification,
            h2_required=h2_required,
        )
        attempt["patch_gate_status"] = gate.status
        attempt["deterministic_rule_id"] = gate.rule_id
        attempt["touched_paths"] = list(gate.touched_paths)
        attempt["repair_proposal_checksum"] = repair_proposal_checksum
        attempt["repair_patch_draft_ref"] = str(draft_path)
        resolved_target_path = ",".join(gate.touched_paths) or "<unresolved>"
        self._emit_repair_event(
            event_recorder,
            "repair_patch_gate_completed",
            {
                "proposal_id": proposal.proposal_id,
                "repair_proposal_checksum": repair_proposal_checksum,
                "repair_patch_draft_ref": str(draft_path),
                "binding_checksum": binding_checksum,
                "patch_gate_status": gate.status,
                "deterministic_rule_id": gate.rule_id,
                "touched_paths": list(gate.touched_paths),
                "ledger_ref": artifact_refs["repair_ledger"],
            },
        )

        if gate.status != "ALLOWED":
            attempt["status"] = "BLOCKED"
            append_attempt(ledger, attempt)
            ledger["artifact_refs"] = artifact_refs
            ledger["final_status"] = "REPAIR_BLOCKED_HUMAN_REVIEW" if gate.human_review_required else "REPAIR_BLOCKED"
            ledger.setdefault("warnings", []).append(gate.reason)
            write_ledger(run_path, ledger)
            return self._record_action(
                proposal_id=proposal_id,
                target_path=resolved_target_path,
                patch_content=patch_content,
                status="failed",
                result_summary=f"Patch gate blocked repair proposal: {gate.reason}",
            )

        apply_result = apply_patch_to_sandbox(
            run_dir=run_path,
            sandbox_path=sandbox_path,
            attempt=1,
            unified_diff=patch_content,
            touched_paths=list(gate.touched_paths),
        )
        attempt["patch_ref"] = str(apply_result.patch_path)
        if apply_result.status != "APPLIED":
            result_path = write_patch_attempt_result(
                run_dir=run_path,
                run_id=resolved_run_id,
                attempt=1,
                status=apply_result.status,
                reason=apply_result.reason,
                rule_id=gate.rule_id,
                risk=gate.risk,
                paths=apply_result.touched_paths,
                before_hashes=apply_result.before_hashes,
                errors=apply_result.errors,
            )
            attempt["patch_result_ref"] = str(result_path)
            attempt["status"] = "FAILED"
            append_attempt(ledger, attempt)
            ledger["artifact_refs"] = artifact_refs
            ledger["final_status"] = "REPAIR_FAILED"
            write_ledger(run_path, ledger)
            return self._record_action(
                proposal_id=proposal_id,
                target_path=resolved_target_path,
                patch_content=patch_content,
                status="failed",
                result_summary=f"Repair patch was rejected in sandbox: {apply_result.reason}",
            )
        self._emit_repair_event(
            event_recorder,
            "repair_patch_applied",
            {
                "proposal_id": proposal.proposal_id,
                "patch_ref": str(apply_result.patch_path),
                "patch_status": apply_result.status,
                "touched_paths": list(apply_result.touched_paths),
                "ledger_ref": artifact_refs["repair_ledger"],
            },
        )

        validation: ValidationResult = validation_runner(
            run_id=resolved_run_id,
            run_dir=run_path,
            sandbox_path=sandbox_path,
            attempt=1,
            h2_required=h2_required,
            h2_enabled=h2_required,
        )
        attempt["validation"] = {
            "build_status": validation.build_status,
            "test_status": validation.test_status,
            "h2_status": validation.h2_status,
        }
        artifact_refs.update(validation.artifact_refs)
        self._emit_repair_event(
            event_recorder,
            "repair_validation_completed",
            {
                "proposal_id": proposal.proposal_id,
                "passed": validation.passed,
                "build_status": validation.build_status,
                "test_status": validation.test_status,
                "h2_status": validation.h2_status,
                "artifact_refs": dict(validation.artifact_refs),
                "ledger_ref": artifact_refs["repair_ledger"],
            },
        )

        if validation.passed:
            result_path = write_patch_attempt_result(
                run_dir=run_path,
                run_id=resolved_run_id,
                attempt=1,
                status="APPLIED",
                reason="patch applied and validation passed",
                rule_id=gate.rule_id,
                risk=gate.risk,
                paths=apply_result.touched_paths,
                before_hashes=apply_result.before_hashes,
                after_hashes=apply_result.after_hashes,
                validation_commands=validation.validation_commands,
                warnings=validation.warnings,
            )
            attempt["patch_result_ref"] = str(result_path)
            attempt["status"] = "VALIDATED"
            append_attempt(ledger, attempt)
            ledger["artifact_refs"] = artifact_refs
            ledger["final_status"] = "REPAIR_VALIDATED"
            write_ledger(run_path, ledger)
            action = self._record_action(
                proposal_id=proposal_id,
                target_path=resolved_target_path,
                patch_content=patch_content,
                status="applied",
                result_summary=f"Patch applied to {resolved_target_path} and validation passed",
            )
            self._mark_proposal_applied(proposal)
            return action

        rolled_back, rollback_reason = rollback_patch(
            sandbox_path=sandbox_path,
            snapshot_dir=apply_result.snapshot_dir,
            touched_paths=apply_result.touched_paths,
            created_paths=apply_result.created_paths,
        )
        self._emit_repair_event(
            event_recorder,
            "repair_rollback_completed",
            {
                "proposal_id": proposal.proposal_id,
                "rollback_status": "ROLLED_BACK" if rolled_back else "ROLLBACK_FAILED",
                "reason": rollback_reason,
            },
        )
        attempt["rollback"] = {
            "performed": True,
            "reason": "; ".join(validation.errors) or "validation failed",
            "status": "ROLLED_BACK" if rolled_back else "ROLLBACK_FAILED",
        }
        result_path = write_patch_attempt_result(
            run_dir=run_path,
            run_id=resolved_run_id,
            attempt=1,
            status="ROLLED_BACK" if rolled_back else "FAILED",
            reason=rollback_reason,
            rule_id=gate.rule_id,
            risk=gate.risk,
            paths=apply_result.touched_paths,
            before_hashes=apply_result.before_hashes,
            after_hashes=apply_result.after_hashes,
            validation_commands=validation.validation_commands,
            warnings=validation.warnings,
            errors=validation.errors,
        )
        attempt["patch_result_ref"] = str(result_path)
        attempt["status"] = "ROLLED_BACK" if rolled_back else "FAILED"
        append_attempt(ledger, attempt)
        ledger["artifact_refs"] = artifact_refs
        ledger["final_status"] = "REPAIR_FAILED"
        if not rolled_back:
            ledger.setdefault("errors", []).append("rollback failed after repair validation failure")
        write_ledger(run_path, ledger)
        return self._record_action(
            proposal_id=proposal_id,
            target_path=resolved_target_path,
            patch_content=patch_content,
            status="rolled_back" if rolled_back else "failed",
            result_summary=rollback_reason,
        )

    def _emit_repair_event(
        self,
        recorder: RepairEventRecorder | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if recorder is not None:
            recorder(event_type, payload)

    def _record_action(
        self,
        *,
        proposal_id: str,
        target_path: str,
        patch_content: str,
        status: str,
        result_summary: str,
    ) -> SandboxAction:
        action = SandboxAction(
            action_id=uuid4().hex,
            proposal_id=proposal_id,
            target_path=target_path,
            patch_content=patch_content,
            status=status,
            result_summary=result_summary,
            created_at=utc_now_text(),
        )
        self._actions[action.action_id] = action
        if self._repo is not None:
            action_record = V2SandboxActionRecord(
                action_id=action.action_id,
                proposal_id=action.proposal_id,
                target_path=action.target_path,
                patch_content=action.patch_content,
                status=action.status,
                result_summary=action.result_summary,
                created_at=action.created_at,
            )
            self._repo.save_action(action_record)
        return action

    def _mark_proposal_applied(self, proposal: RepairProposal) -> None:
        updated = RepairProposal(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            failure_summary=proposal.failure_summary,
            hypothesis=proposal.hypothesis,
            patch_summary=proposal.patch_summary,
            affected_paths=proposal.affected_paths,
            status="applied",
            approval_checksum=proposal.approval_checksum,
            created_at=proposal.created_at,
            proposal_checksum=proposal.proposal_checksum,
        )
        if self._repo is not None:
            self._repo.update_proposal_status(proposal.proposal_id, "applied")
        self._proposals[proposal.proposal_id] = updated

    def proposal_to_dict(self, proposal: RepairProposal, *, reviewer_critique_id: str | None = None, reviewer_decision: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "proposal_id": proposal.proposal_id,
            "command_id": proposal.command_id,
            "failure_summary": proposal.failure_summary,
            "hypothesis": proposal.hypothesis,
            "patch_summary": proposal.patch_summary,
            "affected_paths": list(proposal.affected_paths),
            "status": proposal.status,
            "approval_checksum": proposal.approval_checksum,
            "created_at": proposal.created_at,
            "proposal_checksum": proposal.proposal_checksum,
        }
        # F07: Include reviewer metadata when available
        if reviewer_critique_id is not None:
            result["reviewer_critique_id"] = reviewer_critique_id
        if reviewer_decision is not None:
            result["reviewer_decision"] = reviewer_decision
        # F05: Include revision metadata when present
        if proposal.source_proposal_id is not None:
            result["source_proposal_id"] = proposal.source_proposal_id
            result["revision_of"] = proposal.revision_of
            result["revision_number"] = proposal.revision_number
        if proposal.allowed_scope is not None:
            result["allowed_scope"] = proposal.allowed_scope
        return result

    def action_to_dict(self, action: SandboxAction) -> dict[str, Any]:
        return {
            "action_id": action.action_id,
            "proposal_id": action.proposal_id,
            "target_path": action.target_path,
            "patch_content": action.patch_content[:100] if action.patch_content else "",
            "status": action.status,
            "result_summary": action.result_summary,
            "created_at": action.created_at,
        }

    @staticmethod
    def _proposal_checksum(
        *,
        command_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
        source_proposal_id: str | None = None,
        revision_of: str | None = None,
        revision_number: int | None = None,
        context_pack_checksum: str | None = None,
        allowed_scope: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "command_id": command_id,
            "failure_summary": failure_summary,
            "hypothesis": hypothesis,
            "patch_summary": patch_summary,
            "affected_paths": list(affected_paths),
        }
        if source_proposal_id is not None:
            payload["source_proposal_id"] = source_proposal_id
        if revision_of is not None:
            payload["revision_of"] = revision_of
        if revision_number is not None:
            payload["revision_number"] = revision_number
        if context_pack_checksum is not None:
            payload["context_pack_checksum"] = context_pack_checksum
        if allowed_scope is not None:
            payload["allowed_scope"] = allowed_scope
        return sha256_canonical_json(payload)
