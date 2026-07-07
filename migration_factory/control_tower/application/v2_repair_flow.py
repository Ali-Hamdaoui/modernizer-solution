"""V2 repair/proposal flow — failed stage evidence to bounded repair."""

from __future__ import annotations

import json
import difflib
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.domain.checksums import (
    sha256_canonical_json,
    sha256_unified_diff_text,
    utc_now_text,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2RepairProposalRecord,
    V2SandboxActionRecord,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_job_repository import (
    SqliteV2JobRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_setup_repository import (
    SqliteV2SetupRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
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
from migration_factory.repair_loop.patch_apply import (
    apply_patch_to_sandbox,
    rollback_patch,
    validate_patch_artifact,
)
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal
from migration_factory.repair_loop.validation_runner import (
    ValidationResult,
    run_validation_after_patch,
)


ValidationRunner = Callable[..., ValidationResult]
RepairEventRecorder = Callable[[str, dict[str, Any]], None]


def _json_or_text(value: str) -> object:
    try:
        return json.loads(value or "{}")
    except (json.JSONDecodeError, TypeError):
        return value


def _json_object_or_empty(value: str) -> dict[str, Any]:
    parsed = _json_or_text(value)
    return parsed if isinstance(parsed, dict) else {}


class RepairContextBindingError(ValueError):
    """Raised when a repair-review context is not bound to durable run state."""


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
    patch_package_json: str = "{}"


@dataclass(frozen=True)
class SandboxAction:
    action_id: str
    proposal_id: str
    target_path: str
    patch_content: str
    status: str  # pending, applied, failed, rolled_back
    result_summary: str
    created_at: str
    verification_status: str = "not_available"
    verification_build_status: str = ""
    verification_test_status: str = ""
    verification_h2_status: str = ""
    verification_artifact_refs_json: str = "{}"
    verification_failure_classification_ref: str = ""


@dataclass(frozen=True)
class RepairApplyFailureEvidence:
    failure_stage: str
    failure_code: str
    human_readable_summary: str
    failed_command_id: str
    proposal_id: str
    context_id: str
    approval_id: str
    patch_artifact: str
    patch_checksum: str
    expected_sandbox_checksum: str
    actual_sandbox_checksum: str
    expected_legacy_checksum: str
    actual_legacy_checksum: str
    worktree_used: str
    strip_level: int
    git_executable: str
    git_apply_check_stdout: str
    git_apply_check_stderr: str
    verification_artifacts: dict[str, str]
    recommended_next_action: str
    assistant_followup_intent: str


@dataclass(frozen=True)
class RepairApplyContext:
    context_id: str
    proposal_id: str
    command_id: str
    reviewer_critique_id: str
    proposer_invocation_id: str
    reviewer_invocation_id: str
    reviewer_decision: str
    proposal_summary: str
    patch_preview: str
    patch_preview_checksum: str
    target_path: str
    sandbox_reference: str
    sandbox_checksum: str
    legacy_checksum: str
    context_pack_checksum: str
    proposal_checksum: str
    evidence_refs_json: str
    approval_eligible: bool
    blockers_json: str
    approval_scope: str
    created_at: str


@dataclass(frozen=True)
class RepairApprovalRecord:
    approval_id: str
    context_id: str
    proposal_id: str
    approval_status: str
    approval_scope: str
    approval_note: str
    approval_checksum: str
    sandbox_checksum: str
    legacy_checksum: str
    created_at: str


@dataclass(frozen=True)
class RepairApplyGuardResult:
    context_id: str
    approval_id: str
    proposal_id: str
    sandbox_reference: str
    target_path: str
    patch_preview_checksum: str
    approval_checksum: str
    sandbox_checksum: str
    legacy_checksum: str
    apply_ready: bool
    blockers: tuple[str, ...]


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
        job_repo: SqliteV2JobRepository | None = None,
        setup_repo: SqliteV2SetupRepository | None = None,
        command_repo: SqliteV2CommandRepository | None = None,
    ) -> None:
        self._proposals: dict[str, RepairProposal] = {}
        self._actions: dict[str, SandboxAction] = {}
        self._repo = repair_repo
        self._reviewer = reviewer_service or V2ReviewerService()
        self._job_repo = job_repo
        self._setup_repo = setup_repo
        self._command_repo = command_repo

    def create_proposal(
        self,
        command_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
        patch_package_json: str = "{}",
        context_pack_checksum: str | None = None,
    ) -> RepairProposal:
        effective_context_checksum = context_pack_checksum or self._patch_package_checksum(patch_package_json)
        proposal_checksum = self._proposal_checksum(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            context_pack_checksum=effective_context_checksum,
            patch_package_json=patch_package_json,
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
            context_pack_checksum=effective_context_checksum,
            patch_package_json=patch_package_json,
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
                patch_package_json=proposal.patch_package_json,
            )
            self._repo.save_proposal(record)
        return proposal

    def create_patch_backed_proposal(
        self,
        *,
        command_id: str,
        failure_summary: str,
        hypothesis: str,
        patch_summary: str,
        affected_paths: tuple[str, ...],
        verification_command: tuple[str, ...] = ("mvn", "-q", "-DskipTests", "compile"),
        controlled_demo_evidence: dict[str, Any] | None = None,
    ) -> RepairProposal:
        patch_package_json = self._build_patch_package_json(
            command_id=command_id,
            failure_summary=failure_summary,
            affected_paths=affected_paths,
            verification_command=verification_command,
            controlled_demo_evidence=controlled_demo_evidence,
        )
        context_pack_checksum = self._patch_package_checksum(patch_package_json)
        return self.create_proposal(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary=patch_summary,
            affected_paths=affected_paths,
            patch_package_json=patch_package_json,
            context_pack_checksum=context_pack_checksum,
        )

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
        patch_package_json: str = "{}",
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
            patch_package_json=patch_package_json,
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
            patch_package_json=patch_package_json,
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
                patch_package_json=proposal.patch_package_json,
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
                proposal = self._record_to_proposal(record)
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
            source_proposal_id=proposal.source_proposal_id,
            revision_of=proposal.revision_of,
            revision_number=proposal.revision_number,
            context_pack_checksum=proposal.context_pack_checksum,
            allowed_scope=proposal.allowed_scope,
            patch_package_json=proposal.patch_package_json,
        )
        self._proposals[proposal_id] = updated
        # Persist if repo available
        if self._repo is not None:
            self._repo.update_proposal_status(proposal_id, "approved", approval_checksum)
        return updated

    def prepare_apply_context(
        self,
        *,
        proposal_id: str,
        command_id: str,
        proposal_checksum: str,
        context_pack_checksum: str,
        reviewer_critique_id: str,
        proposer_invocation_id: str,
        reviewer_invocation_id: str,
        patch_preview: str,
        target_path: str,
        sandbox_reference: str,
        sandbox_checksum: str,
        legacy_checksum: str,
        evidence_refs: dict[str, str],
        approval_scope: str = "sandbox_only",
    ) -> RepairApplyContext:
        proposal = self._get_proposal_or_raise(proposal_id)
        if proposal.command_id != command_id:
            raise ValueError(
                f"Proposal {proposal_id!r} is bound to command {proposal.command_id!r}, not {command_id!r}"
            )
        if approval_scope != "sandbox_only":
            raise ValueError("Repair apply context must be scoped to sandbox_only")
        if not patch_preview.strip():
            raise ValueError("Repair apply context requires a patch preview")
        if not target_path.strip():
            raise ValueError("Repair apply context requires a target path")
        if not sandbox_reference.strip():
            raise ValueError("Repair apply context requires a sandbox reference")
        if not sandbox_checksum.strip():
            raise ValueError("Repair apply context requires a sandbox checksum")
        if not legacy_checksum.strip():
            raise ValueError("Repair apply context requires a legacy checksum")
        if not evidence_refs:
            raise ValueError("Repair apply context requires evidence references")
        patch_package = _json_object_or_empty(proposal.patch_package_json)
        if patch_package:
            package_checksum = str(patch_package.get("package_checksum") or "").strip()
            if package_checksum and context_pack_checksum != package_checksum:
                raise ValueError("Repair apply context requires current patch package checksum")
            repair_artifact = patch_package.get("repair_artifact") if isinstance(patch_package.get("repair_artifact"), dict) else {}
            package_patch = str(repair_artifact.get("unified_diff") or "")
            package_target = str((patch_package.get("target_files") or [{}])[0].get("relative_path") or "") if isinstance(patch_package.get("target_files"), list) else ""
            package_sandbox = str(patch_package.get("sandbox_path") or "")
            package_sandbox_checksum = str(patch_package.get("sandbox_checksum") or "")
            package_legacy_checksum = str(patch_package.get("legacy_checksum") or "")
            if not package_patch.strip():
                raise ValueError("Repair apply context requires patch package bytes")
            if patch_preview != package_patch:
                raise ValueError("Repair apply context patch bytes do not match persisted patch package")
            if package_target and target_path != package_target:
                raise ValueError("Repair apply context target does not match persisted patch package")
            if package_sandbox and sandbox_reference != package_sandbox:
                raise ValueError("Repair apply context sandbox does not match persisted patch package")
            if package_sandbox_checksum and sandbox_checksum != package_sandbox_checksum:
                raise ValueError("Repair apply context sandbox checksum does not match persisted patch package")
            if package_legacy_checksum and legacy_checksum != package_legacy_checksum:
                raise ValueError("Repair apply context legacy checksum does not match persisted patch package")
            evidence_refs = {
                **evidence_refs,
                "patch_artifact": str(repair_artifact.get("patch_path") or evidence_refs.get("patch_artifact") or ""),
                "patch_checksum": str(repair_artifact.get("patch_checksum") or evidence_refs.get("patch_checksum") or ""),
                "strip_level": "1",
                "prevalidation_worktree": package_sandbox or sandbox_reference,
            }
        self._validate_prepare_binding(
            command_id=command_id,
            sandbox_reference=sandbox_reference,
            target_path=target_path,
        )

        critique = self._reviewer.get_critique(reviewer_critique_id)
        if critique is None:
            raise ValueError(f"Reviewer critique {reviewer_critique_id!r} not found")
        if critique.proposal_id != proposal_id:
            raise ValueError("Reviewer critique is not bound to the requested proposal")
        if critique.decision != "accept":
            raise ValueError("Repair apply context is blocked unless reviewer decision is accept")
        if critique.proposal_checksum != proposal_checksum:
            raise ValueError("Repair apply context requires a matching proposal checksum")
        if critique.context_pack_checksum != context_pack_checksum:
            raise ValueError("Repair apply context requires a matching context checksum")

        patch_preview_checksum = sha256_canonical_json(
            {
                "proposal_id": proposal_id,
                "patch_preview": patch_preview,
                "target_path": target_path,
            }
        )
        latest = self._latest_context_for_proposal(proposal_id)
        if latest is not None:
            if (
                latest.patch_preview_checksum == patch_preview_checksum
                and latest.sandbox_checksum == sandbox_checksum
                and latest.legacy_checksum == legacy_checksum
                and latest.context_pack_checksum == context_pack_checksum
            ):
                return latest

        context = RepairApplyContext(
            context_id=uuid4().hex,
            proposal_id=proposal_id,
            command_id=command_id,
            reviewer_critique_id=reviewer_critique_id,
            proposer_invocation_id=proposer_invocation_id.strip(),
            reviewer_invocation_id=reviewer_invocation_id.strip(),
            reviewer_decision=critique.decision,
            proposal_summary=proposal.patch_summary,
            patch_preview=patch_preview,
            patch_preview_checksum=patch_preview_checksum,
            target_path=target_path,
            sandbox_reference=sandbox_reference,
            sandbox_checksum=sandbox_checksum,
            legacy_checksum=legacy_checksum,
            context_pack_checksum=context_pack_checksum,
            proposal_checksum=proposal_checksum,
            evidence_refs_json=json.dumps(evidence_refs, separators=(",", ":"), sort_keys=True),
            approval_eligible=True,
            blockers_json="[]",
            approval_scope=approval_scope,
            created_at=utc_now_text(),
        )
        self._save_context(context)
        return context

    def _validate_prepare_binding(
        self,
        *,
        command_id: str,
        sandbox_reference: str,
        target_path: str,
    ) -> None:
        if self._job_repo is None and self._setup_repo is None and self._command_repo is None:
            return
        if self._job_repo is None or self._setup_repo is None or self._command_repo is None:
            raise RepairContextBindingError(
                "Repair apply context requires job, setup, and command repositories"
            )
        command = self._command_repo.get(command_id)
        if command is None:
            raise RepairContextBindingError(f"Command {command_id!r} not found")
        if not str(command.job_id or "").strip():
            raise RepairContextBindingError(f"Command {command_id!r} is missing job_id")
        job = self._job_repo.get(command.job_id)
        if job is None:
            raise RepairContextBindingError(
                f"Job {command.job_id!r} not found for command {command_id!r}"
            )
        setup = self._setup_repo.get(job.setup_id)
        if setup is None:
            raise RepairContextBindingError(
                f"Setup {job.setup_id!r} not found for job {job.job_id!r}"
            )
        legacy_path = Path(str(setup.legacy_app_path or ""))
        if not legacy_path.is_absolute():
            raise RepairContextBindingError("Repair apply context requires absolute legacy path")

        result_data: dict[str, Any] = {}
        if command.result_json:
            try:
                parsed = json.loads(command.result_json)
                if isinstance(parsed, dict):
                    result_data = parsed
            except (json.JSONDecodeError, TypeError):
                result_data = {}
        run_id = str(result_data.get("run_id") or "").strip()
        if not run_id:
            raise RepairContextBindingError(
                f"Command {command_id!r} result is missing run_id"
            )

        command_sandbox = str(
            result_data.get("sandbox_path")
            or result_data.get("modernized_app_path")
            or result_data.get("output_app_path")
            or ""
        ).strip()
        if not command_sandbox:
            raise RepairContextBindingError(
                f"Command {command_id!r} result is missing sandbox path"
            )
        command_sandbox_path = Path(command_sandbox)
        if not command_sandbox_path.is_absolute():
            raise RepairContextBindingError(
                f"Command {command_id!r} sandbox path must be absolute"
            )
        requested_sandbox_path = Path(sandbox_reference)
        if not requested_sandbox_path.is_absolute():
            raise RepairContextBindingError(
                "Repair apply context requires absolute sandbox reference"
            )
        try:
            if command_sandbox_path.resolve() != requested_sandbox_path.resolve():
                raise RepairContextBindingError(
                    "Repair apply context sandbox reference does not match command sandbox"
                )
        except OSError as exc:
            raise RepairContextBindingError(
                "Repair apply context sandbox reference could not be resolved"
            ) from exc
        if not command_sandbox_path.exists():
            raise RepairContextBindingError(
                f"Command {command_id!r} sandbox path does not exist"
            )
        self._resolve_bound_run_dir(
            result_data=result_data,
            setup_output_parent=setup.output_parent_path,
            sandbox_path=command_sandbox_path,
            run_id=run_id,
            error_cls=RepairContextBindingError,
            command_id=command_id,
        )
        try:
            command_sandbox_path.resolve().relative_to(legacy_path.resolve())
            raise RepairContextBindingError("Repair apply context sandbox must not be inside legacy path")
        except ValueError as exc:
            if str(exc) == "Repair apply context sandbox must not be inside legacy path":
                raise
        if not self._is_sandbox_bound_target_values(
            target_path=Path(sandbox_reference) / target_path
            if not Path(target_path).is_absolute()
            else Path(target_path),
            sandbox_path=requested_sandbox_path,
        ):
            raise RepairContextBindingError("Repair apply context target is not sandbox-bound")

    def record_approval_only(
        self,
        *,
        context_id: str,
        approval_checksum: str,
        approval_note: str,
        approval_scope: str,
    ) -> RepairApprovalRecord:
        context = self.get_apply_context(context_id)
        if context is None:
            raise ValueError(f"Repair apply context {context_id!r} not found")
        if context.reviewer_decision != "accept":
            raise ValueError("Human approval is blocked unless reviewer decision is accept")
        if not context.approval_eligible:
            raise ValueError("Human approval is blocked until repair apply context is eligible")
        if approval_scope != "sandbox_only":
            raise ValueError("Human approval scope must be sandbox_only")
        if not approval_note.strip():
            raise ValueError("Human approval note is required")
        if not approval_checksum.strip():
            raise ValueError("Human approval checksum is required")
        if not context.patch_preview.strip():
            raise ValueError("Human approval requires a prepared patch preview")
        if not context.sandbox_checksum.strip() or not context.legacy_checksum.strip():
            raise ValueError("Human approval requires checksum guards")

        existing = self._latest_approval_for_context(context_id)
        if existing is not None:
            if (
                existing.approval_checksum == approval_checksum
                and existing.approval_note == approval_note.strip()
                and existing.approval_scope == approval_scope
            ):
                return existing
            raise ValueError(f"Repair apply context {context_id!r} is already approved")

        approval = RepairApprovalRecord(
            approval_id=uuid4().hex,
            context_id=context_id,
            proposal_id=context.proposal_id,
            approval_status="recorded",
            approval_scope=approval_scope,
            approval_note=approval_note.strip(),
            approval_checksum=approval_checksum.strip(),
            sandbox_checksum=context.sandbox_checksum,
            legacy_checksum=context.legacy_checksum,
            created_at=utc_now_text(),
        )
        self._save_approval(context, approval)
        return approval

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
        apply_failure_context: dict[str, Any] | None = None,
        validation_runner: ValidationRunner = run_validation_after_patch,
        event_recorder: RepairEventRecorder | None = None,
    ) -> SandboxAction:
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = self._record_to_proposal(record)
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
                "proposal_id": proposal.proposal_id,
                "repair_proposal_checksum": repair_proposal_checksum,
                "target_path": target_path,
                "deterministic_rule_id": deterministic_rule_id,
                "risk": risk,
                "requires_human_review": requires_human_review,
                "binding_checksum": binding_checksum,
                "h2_required": h2_required,
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
                apply_failure=self._apply_failure_payload(
                    failure_stage="official_apply",
                    failure_code="PATCH_GATE_BLOCKED",
                    summary=f"Patch gate blocked repair proposal: {gate.reason}",
                    proposal=proposal,
                    context=apply_failure_context,
                    patch_artifact=str(draft_path),
                    patch_checksum="",
                    expected_sandbox_checksum="",
                    actual_sandbox_checksum="",
                    expected_legacy_checksum="",
                    actual_legacy_checksum="",
                    worktree_used=str(sandbox_path),
                    git_apply_check_stderr=gate.reason,
                    recommended_next_action="regenerate_proposal_against_current_sandbox",
                    assistant_followup_intent="regenerate_proposal_against_current_sandbox",
                ),
            )

        apply_result = apply_patch_to_sandbox(
            run_dir=run_path,
            sandbox_path=sandbox_path,
            attempt=1,
            unified_diff=patch_content,
            touched_paths=list(gate.touched_paths),
        )
        attempt["patch_ref"] = str(apply_result.patch_path)
        apply_artifact_ref, apply_artifact_checksum = self._write_repair_json_artifact(
            run_path,
            "repair_apply_result.json",
            {
                "proposal_id": proposal.proposal_id,
                "attempt": 1,
                "status": apply_result.status,
                "reason": apply_result.reason,
                "touched_paths": list(apply_result.touched_paths),
                "created_paths": list(apply_result.created_paths),
                "patch_ref": str(apply_result.patch_path),
                "binding_checksum": binding_checksum or "",
            },
        )
        artifact_refs["repair_apply_result"] = str(apply_artifact_ref)
        attempt["repair_apply_result_ref"] = str(apply_artifact_ref)
        attempt["repair_apply_result_checksum"] = apply_artifact_checksum
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
            terminal_ref, terminal_checksum = self._write_repair_json_artifact(
                run_path,
                "repair_terminal_failure.json",
                {
                    "proposal_id": proposal.proposal_id,
                    "attempt": 1,
                    "status": "REPAIR_FAILED",
                    "reason": apply_result.reason,
                    "max_attempts_exhausted": True,
                    "binding_checksum": binding_checksum or "",
                },
            )
            artifact_refs["repair_terminal_failure"] = str(terminal_ref)
            attempt["repair_terminal_failure_ref"] = str(terminal_ref)
            attempt["repair_terminal_failure_checksum"] = terminal_checksum
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
                apply_failure=self._apply_failure_payload(
                    failure_stage="git_apply_check" if apply_result.status == "REJECTED" else "official_apply",
                    failure_code="GIT_APPLY_CHECK_FAILED" if apply_result.status == "REJECTED" else "GIT_APPLY_FAILED",
                    summary=f"Repair patch was rejected in sandbox: {apply_result.reason}",
                    proposal=proposal,
                    context=apply_failure_context,
                    patch_artifact=str(apply_result.patch_path),
                    patch_checksum=self._sha256_file(apply_result.patch_path),
                    expected_sandbox_checksum=str((apply_failure_context or {}).get("expected_sandbox_checksum") or ""),
                    actual_sandbox_checksum=str((apply_failure_context or {}).get("actual_sandbox_checksum") or ""),
                    expected_legacy_checksum=str((apply_failure_context or {}).get("expected_legacy_checksum") or ""),
                    actual_legacy_checksum=str((apply_failure_context or {}).get("actual_legacy_checksum") or ""),
                    worktree_used=apply_result.worktree_used,
                    strip_level=apply_result.strip_level,
                    git_executable=apply_result.git_executable,
                    git_apply_check_stdout=apply_result.git_apply_check_stdout,
                    git_apply_check_stderr=apply_result.git_apply_check_stderr or apply_result.reason,
                    recommended_next_action="regenerate_proposal_against_current_sandbox",
                    assistant_followup_intent="regenerate_proposal_against_current_sandbox",
                ),
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
        patch_package = _json_object_or_empty(proposal.patch_package_json)
        controlled_verification = self._controlled_repair_verification(
            sandbox_path=Path(sandbox_path),
            patch_package=patch_package,
        )

        validation: ValidationResult = validation_runner(
            run_id=resolved_run_id,
            run_dir=run_path,
            sandbox_path=sandbox_path,
            attempt=1,
            h2_required=h2_required,
            h2_enabled=h2_required,
        )
        verification_artifact_refs = dict(validation.artifact_refs)
        build_error_ref = verification_artifact_refs.get("repair_build_error_contract", "")
        if build_error_ref:
            failure_classification_ref = str(Path(build_error_ref).parent / "post_transform_failure_classification.json")
            if Path(failure_classification_ref).is_file():
                verification_artifact_refs["post_transform_failure_classification"] = failure_classification_ref
        attempt["validation"] = {
            "build_status": validation.build_status,
            "test_status": validation.test_status,
            "h2_status": validation.h2_status,
        }
        rerun_ref, rerun_checksum = self._write_repair_json_artifact(
            run_path,
            "repair_rerun_result.json",
            {
                "proposal_id": proposal.proposal_id,
                "attempt": 1,
                "passed": validation.passed,
                "build_status": validation.build_status,
                "test_status": validation.test_status,
                "h2_status": validation.h2_status,
                "validation_commands": list(validation.validation_commands),
                "warnings": list(validation.warnings),
                "errors": list(validation.errors),
                "artifact_refs": dict(verification_artifact_refs),
                "binding_checksum": binding_checksum or "",
            },
        )
        artifact_refs["repair_rerun_result"] = str(rerun_ref)
        attempt["repair_rerun_result_ref"] = str(rerun_ref)
        attempt["repair_rerun_result_checksum"] = rerun_checksum
        artifact_refs.update(verification_artifact_refs)
        self._emit_repair_event(
            event_recorder,
            "repair_validation_completed",
            {
                "proposal_id": proposal.proposal_id,
                "passed": validation.passed,
                "build_status": validation.build_status,
                "test_status": validation.test_status,
                "h2_status": validation.h2_status,
                "artifact_refs": dict(verification_artifact_refs),
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
            proof_ref, proof_checksum = self._write_repair_json_artifact(
                run_path,
                "repair_proof.json",
                {
                    "proposal_id": proposal.proposal_id,
                    "attempt": 1,
                    "status": "REPAIR_VALIDATED",
                    "patch_result_ref": str(result_path),
                    "repair_apply_result_ref": str(apply_artifact_ref),
                    "repair_rerun_result_ref": str(rerun_ref),
                    "binding_checksum": binding_checksum or "",
                    "repair_apply_result_checksum": apply_artifact_checksum,
                    "repair_rerun_result_checksum": rerun_checksum,
                },
            )
            artifact_refs["repair_proof"] = str(proof_ref)
            attempt["repair_proof_ref"] = str(proof_ref)
            attempt["repair_proof_checksum"] = proof_checksum
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
                verification_status="passed",
                verification_build_status=validation.build_status,
                verification_test_status=validation.test_status,
                verification_h2_status=validation.h2_status,
                verification_artifact_refs_json=json.dumps(verification_artifact_refs, separators=(",", ":"), sort_keys=True),
                verification_failure_classification_ref="",
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
        rollback_sandbox_checksum = self._path_tree_checksum(Path(sandbox_path))
        maven_classification = self._classify_maven_failure_after_controlled_repair(
            validation=validation,
            patch_package=patch_package,
            controlled_verification=controlled_verification,
        )
        attempt["rollback"] = {
            "performed": True,
            "reason": "; ".join(validation.errors) or "validation failed",
            "status": "ROLLED_BACK" if rolled_back else "ROLLBACK_FAILED",
        }
        rollback_ref, rollback_checksum = self._write_repair_json_artifact(
            run_path,
            "repair_rollback_result.json",
            {
                "proposal_id": proposal.proposal_id,
                "attempt": 1,
                "performed": True,
                "status": "ROLLED_BACK" if rolled_back else "ROLLBACK_FAILED",
                "reason": rollback_reason,
                "validation_errors": list(validation.errors),
                "binding_checksum": binding_checksum or "",
            },
        )
        artifact_refs["repair_rollback_result"] = str(rollback_ref)
        attempt["repair_rollback_result_ref"] = str(rollback_ref)
        attempt["repair_rollback_result_checksum"] = rollback_checksum
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
        terminal_ref, terminal_checksum = self._write_repair_json_artifact(
            run_path,
            "repair_terminal_failure.json",
            {
                "proposal_id": proposal.proposal_id,
                "attempt": 1,
                "status": "REPAIR_FAILED",
                "reason": rollback_reason,
                "validation_errors": list(validation.errors),
                "rollback_status": attempt["rollback"]["status"],
                "max_attempts_exhausted": True,
                "binding_checksum": binding_checksum or "",
            },
        )
        artifact_refs["repair_terminal_failure"] = str(terminal_ref)
        attempt["repair_terminal_failure_ref"] = str(terminal_ref)
        attempt["repair_terminal_failure_checksum"] = terminal_checksum
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
            verification_status="failed",
            verification_build_status=validation.build_status,
            verification_test_status=validation.test_status,
            verification_h2_status=validation.h2_status,
            verification_artifact_refs_json=json.dumps(verification_artifact_refs, separators=(",", ":"), sort_keys=True),
            verification_failure_classification_ref=build_error_ref,
            apply_failure=self._apply_failure_payload(
                failure_stage="maven_verification",
                failure_code="MAVEN_VERIFICATION_FAILED",
                summary=self._maven_failure_summary(maven_classification, rolled_back),
                proposal=proposal,
                context=apply_failure_context,
                patch_artifact=str(apply_result.patch_path),
                patch_checksum=self._sha256_file(apply_result.patch_path),
                expected_sandbox_checksum=str((apply_failure_context or {}).get("expected_sandbox_checksum") or ""),
                actual_sandbox_checksum=rollback_sandbox_checksum,
                expected_legacy_checksum=str((apply_failure_context or {}).get("expected_legacy_checksum") or ""),
                actual_legacy_checksum=str((apply_failure_context or {}).get("actual_legacy_checksum") or ""),
                worktree_used=apply_result.worktree_used,
                strip_level=apply_result.strip_level,
                git_executable=apply_result.git_executable,
                git_apply_check_stdout=apply_result.git_apply_check_stdout,
                git_apply_check_stderr=apply_result.git_apply_check_stderr,
                verification_artifacts=verification_artifact_refs,
                recommended_next_action="inspect_unrelated_maven_failures",
                assistant_followup_intent="inspect_unrelated_maven_failures",
                extra={
                    "git_apply_check_status": "passed",
                    "patch_apply_status": "applied_then_rolled_back" if rolled_back else "applied_then_rollback_failed",
                    "patch_apply_stdout": self._excerpt(apply_result.git_apply_stdout),
                    "patch_apply_stderr": self._excerpt(apply_result.git_apply_stderr),
                    "controlled_verification_status": controlled_verification["status"],
                    "controlled_verification_code": controlled_verification["code"],
                    "controlled_verification_summary": controlled_verification["summary"],
                    "controlled_target_repaired": controlled_verification["target_repaired"],
                    "controlled_failure_still_present": maven_classification["controlled_failure_still_present"],
                    "pre_existing_failure_detected": maven_classification["pre_existing_failure_detected"],
                    "full_maven_verification_status": "failed",
                    "full_maven_failure_classification": maven_classification["classification"],
                    "rollback_attempted": True,
                    "rollback_succeeded": bool(rolled_back),
                    "rollback_reason": rollback_reason,
                    "rollback_sandbox_checksum": rollback_sandbox_checksum,
                },
            ),
        )

    def _emit_repair_event(
        self,
        recorder: RepairEventRecorder | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if recorder is not None:
            recorder(event_type, payload)

    @staticmethod
    def _write_repair_json_artifact(
        run_path: Path,
        filename: str,
        payload: dict[str, Any],
    ) -> tuple[Path, str]:
        repairs_dir = run_path / "repairs"
        repairs_dir.mkdir(parents=True, exist_ok=True)
        checksum = sha256_canonical_json(payload)
        artifact_payload = {
            "schema_version": "1.0",
            "artifact_checksum": checksum,
            **payload,
        }
        artifact_ref = repairs_dir / filename
        artifact_ref.write_text(
            json.dumps(artifact_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return artifact_ref, checksum

    def _record_action(
        self,
        *,
        proposal_id: str,
        target_path: str,
        patch_content: str,
        status: str,
        result_summary: str,
        verification_status: str = "not_available",
        verification_build_status: str = "",
        verification_test_status: str = "",
        verification_h2_status: str = "",
        verification_artifact_refs_json: str = "{}",
        verification_failure_classification_ref: str = "",
        apply_failure: dict[str, Any] | None = None,
    ) -> SandboxAction:
        stored_summary = result_summary
        if apply_failure:
            stored_summary = json.dumps(
                {
                    "kind": "repair_apply_result_v1",
                    "human_readable_summary": result_summary,
                    "apply_failure": apply_failure,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        action = SandboxAction(
            action_id=uuid4().hex,
            proposal_id=proposal_id,
            target_path=target_path,
            patch_content=patch_content,
            status=status,
            result_summary=stored_summary,
            created_at=utc_now_text(),
            verification_status=verification_status,
            verification_build_status=verification_build_status,
            verification_test_status=verification_test_status,
            verification_h2_status=verification_h2_status,
            verification_artifact_refs_json=verification_artifact_refs_json,
            verification_failure_classification_ref=verification_failure_classification_ref,
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
                verification_status=action.verification_status,
                verification_build_status=action.verification_build_status,
                verification_test_status=action.verification_test_status,
                verification_h2_status=action.verification_h2_status,
                verification_artifact_refs_json=action.verification_artifact_refs_json,
                verification_failure_classification_ref=action.verification_failure_classification_ref,
            )
            self._repo.save_action(action_record)
        return action

    def apply_approved_proposal(
        self,
        *,
        proposal_id: str,
        command_id: str,
        validation_runner: ValidationRunner | None = None,
        event_recorder: RepairEventRecorder | None = None,
    ) -> SandboxAction:
        """Fail closed: legacy draft patches are not authoritative for F5."""
        raise ValueError(
            "Legacy repair proposal apply is disabled. "
            "Use apply_reviewed_repair_diff with checksum-bound reviewed artifacts."
        )
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = self._record_to_proposal(record)
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status == "applied":
            return self._idempotent_applied_action(proposal_id, proposal)
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal_id!r} must be approved first")
        if proposal.command_id != command_id:
            raise ValueError(
                f"Proposal {proposal_id!r} is bound to command {proposal.command_id!r}, "
                f"not {command_id!r}"
            )
        if self._job_repo is None or self._setup_repo is None or self._command_repo is None:
            raise ValueError("Repair approval apply requires job, setup, and command repositories")
        if validation_runner is None:
            validation_runner = run_validation_after_patch

        command = self._command_repo.get(command_id)
        if command is None:
            raise ValueError(f"Command {command_id!r} not found")
        job = self._job_repo.get(command.job_id)
        if job is None:
            raise ValueError(f"Job {command.job_id!r} not found for command {command_id!r}")
        setup = self._setup_repo.get(job.setup_id)
        if setup is None:
            raise ValueError(f"Setup {job.setup_id!r} not found for job {job.job_id!r}")

        result_json = command.result_json or ""
        result_data: dict[str, Any] = {}
        if result_json:
            try:
                parsed = json.loads(result_json)
                if isinstance(parsed, dict):
                    result_data = parsed
            except (json.JSONDecodeError, TypeError):
                result_data = {}

        run_id = str(result_data.get("run_id") or command.command_id)
        output_root = str(
            result_data.get("modernized_app_path")
            or result_data.get("output_root_dir")
            or setup.output_parent_path
        )
        run_dir = Path(output_root) / ".migration" / "runs" / run_id
        sandbox_path = str(
            result_data.get("sandbox_path")
            or result_data.get("modernized_app_path")
            or result_data.get("output_app_path")
            or ""
        )
        if not sandbox_path:
            raise ValueError(f"Sandbox path could not be resolved for command {command_id!r}")

        draft_path = run_dir / "repairs" / "patch_draft_1.json"
        if not draft_path.is_file():
            raise ValueError(f"Repair patch draft not found at {draft_path}")

        try:
            draft_payload = json.loads(draft_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            raise ValueError(f"Repair patch draft could not be read: {draft_path}") from exc
        if not isinstance(draft_payload, dict):
            raise ValueError(f"Repair patch draft is invalid: {draft_path}")
        if draft_payload.get("proposal_id") != proposal_id:
            raise ValueError(f"Repair patch draft proposal mismatch at {draft_path}")
        if draft_payload.get("repair_proposal_checksum") != proposal.proposal_checksum:
            raise ValueError(
                "Repair patch draft checksum does not match the approved proposal"
            )

        affected_paths = list(proposal.affected_paths)
        target_path = affected_paths[0] if affected_paths else ""
        if not target_path:
            raise ValueError(f"Proposal {proposal_id!r} does not declare a target path")

        expected_validation = tuple(
            str(item) for item in draft_payload.get("expected_validation", [])
            if isinstance(item, str)
        )
        limitations = tuple(
            str(item) for item in draft_payload.get("limitations", [])
            if isinstance(item, str)
        )

        return self.apply_patch(
            proposal_id=proposal_id,
            target_path=target_path,
            patch_content=str(draft_payload.get("unified_diff", "")),
            run_id=run_id,
            run_dir=run_dir,
            sandbox_path=sandbox_path,
            legacy_path=setup.legacy_app_path,
            deterministic_rule_id=str(draft_payload.get("deterministic_rule_id", "")),
            risk=str(draft_payload.get("risk", "LOW")),
            requires_human_review=bool(draft_payload.get("requires_human_review", False)),
            expected_validation=expected_validation,
            limitations=limitations,
            failure_classification=dict(draft_payload.get("failure_classification") or {}),
            h2_required=bool(draft_payload.get("h2_required", False)),
            binding_checksum=str(draft_payload.get("binding_checksum") or "") or None,
            validation_runner=validation_runner,
            event_recorder=event_recorder,
        )

    def apply_prepared_context(
        self,
        *,
        context_id: str,
        approval_id: str,
        expected_approval_checksum: str,
        expected_sandbox_checksum: str,
        expected_legacy_checksum: str,
        validation_runner: ValidationRunner | None = None,
        event_recorder: RepairEventRecorder | None = None,
    ) -> SandboxAction:
        """Apply a prepared repair-review context after approval-only guards pass."""
        guard = self.validate_apply_guard(
            context_id=context_id,
            approval_id=approval_id,
            expected_approval_checksum=expected_approval_checksum,
            expected_sandbox_checksum=expected_sandbox_checksum,
            expected_legacy_checksum=expected_legacy_checksum,
        )
        context = self.get_apply_context(context_id)
        approval = self.get_approval(context_id, approval_id)
        if context is None or approval is None:
            raise ValueError("Repair apply requires persisted context and approval")
        proposal = self._get_proposal_or_raise(context.proposal_id)
        if proposal.command_id != context.command_id:
            raise ValueError("Repair apply context command does not match proposal")
        if proposal.status == "applied":
            return self._idempotent_applied_action(proposal.proposal_id, proposal)
        if self._job_repo is None or self._setup_repo is None or self._command_repo is None:
            raise ValueError("Repair-review apply requires job, setup, and command repositories")
        if validation_runner is None:
            validation_runner = run_validation_after_patch

        command = self._command_repo.get(context.command_id)
        if command is None:
            raise ValueError(f"Command {context.command_id!r} not found")
        job = self._job_repo.get(command.job_id)
        if job is None:
            raise ValueError(f"Job {command.job_id!r} not found for command {context.command_id!r}")
        setup = self._setup_repo.get(job.setup_id)
        if setup is None:
            raise ValueError(f"Setup {job.setup_id!r} not found for job {job.job_id!r}")

        result_data: dict[str, Any] = {}
        if command.result_json:
            try:
                parsed = json.loads(command.result_json)
                if isinstance(parsed, dict):
                    result_data = parsed
            except (json.JSONDecodeError, TypeError):
                result_data = {}
        run_id = str(result_data.get("run_id") or command.command_id)
        sandbox_path = Path(context.sandbox_reference)
        if not sandbox_path.is_absolute():
            raise ValueError("Repair-review apply requires an absolute sandbox reference")
        if not sandbox_path.exists():
            raise ValueError(f"Repair-review sandbox path does not exist: {sandbox_path}")
        run_dir = self._resolve_bound_run_dir(
            result_data=result_data,
            setup_output_parent=setup.output_parent_path,
            sandbox_path=sandbox_path,
            run_id=run_id,
            error_cls=ValueError,
            command_id=context.command_id,
        )
        command_sandbox = str(
            result_data.get("sandbox_path")
            or result_data.get("modernized_app_path")
            or result_data.get("output_app_path")
            or ""
        )
        if command_sandbox and Path(command_sandbox).resolve() != sandbox_path.resolve():
            raise ValueError("Repair-review sandbox reference does not match command sandbox")
        legacy_path = Path(setup.legacy_app_path)
        if not legacy_path.is_absolute():
            raise ValueError("Repair-review apply requires an absolute legacy path")
        if not legacy_path.exists():
            raise ValueError(f"Repair-review legacy path does not exist: {legacy_path}")
        try:
            sandbox_path.resolve().relative_to(legacy_path.resolve())
            raise ValueError("Repair-review sandbox must not be inside legacy path")
        except ValueError as exc:
            if str(exc) == "Repair-review sandbox must not be inside legacy path":
                raise

        actual_sandbox_checksum = self._path_tree_checksum(sandbox_path)
        actual_legacy_checksum = self._path_tree_checksum(legacy_path)
        patch_package = _json_object_or_empty(proposal.patch_package_json)
        repair_artifact = patch_package.get("repair_artifact") if isinstance(patch_package.get("repair_artifact"), dict) else {}
        package_patch = str(repair_artifact.get("unified_diff") or "")
        if package_patch and context.patch_preview != package_patch:
            return self._record_action(
                proposal_id=proposal.proposal_id,
                target_path=context.target_path,
                patch_content=context.patch_preview,
                status="failed",
                result_summary="Prepared patch bytes do not match persisted patch package.",
                apply_failure=self._apply_failure_payload(
                    failure_stage="official_apply",
                    failure_code="PATCH_BYTES_MISMATCH",
                    summary="Prepared patch bytes do not match persisted patch package.",
                    proposal=proposal,
                    context={"context_id": context_id, "approval_id": approval_id, "failed_command_id": context.command_id},
                    patch_artifact=str(repair_artifact.get("patch_path") or ""),
                    patch_checksum=str(repair_artifact.get("patch_checksum") or ""),
                    expected_sandbox_checksum=context.sandbox_checksum,
                    actual_sandbox_checksum=actual_sandbox_checksum,
                    expected_legacy_checksum=context.legacy_checksum,
                    actual_legacy_checksum=actual_legacy_checksum,
                    worktree_used=str(sandbox_path),
                    recommended_next_action="reject_stale_context",
                    assistant_followup_intent="reject_stale_context",
                ),
            )
        if actual_legacy_checksum != context.legacy_checksum:
            return self._record_action(
                proposal_id=proposal.proposal_id,
                target_path=context.target_path,
                patch_content=context.patch_preview,
                status="failed",
                result_summary="Legacy checksum changed before repair apply; backend refused to continue.",
                apply_failure=self._apply_failure_payload(
                    failure_stage="official_apply",
                    failure_code="LEGACY_CHECKSUM_MISMATCH",
                    summary="Legacy checksum changed before repair apply; backend refused to continue.",
                    proposal=proposal,
                    context={"context_id": context_id, "approval_id": approval_id, "failed_command_id": context.command_id},
                    patch_artifact=str(repair_artifact.get("patch_path") or ""),
                    patch_checksum=str(repair_artifact.get("patch_checksum") or ""),
                    expected_sandbox_checksum=context.sandbox_checksum,
                    actual_sandbox_checksum=actual_sandbox_checksum,
                    expected_legacy_checksum=context.legacy_checksum,
                    actual_legacy_checksum=actual_legacy_checksum,
                    worktree_used=str(sandbox_path),
                    recommended_next_action="escalate_to_human",
                    assistant_followup_intent="escalate_to_human",
                ),
            )
        if actual_sandbox_checksum != context.sandbox_checksum:
            latest_action = self._latest_action_for_proposal(proposal.proposal_id)
            if (
                latest_action is not None
                and latest_action.status in {"applied", "idempotent"}
                and self._proposal_target_checksums_match(
                    sandbox_path=sandbox_path,
                    proposal=proposal,
                    checksum_key="proposed_checksum",
                )
            ):
                return self._idempotent_applied_action(proposal.proposal_id, proposal)
            return self._record_action(
                proposal_id=proposal.proposal_id,
                target_path=context.target_path,
                patch_content=context.patch_preview,
                status="failed",
                result_summary="Sandbox changed since proposal/context creation; patch is stale.",
                apply_failure=self._apply_failure_payload(
                    failure_stage="stale_patch",
                    failure_code="SANDBOX_CHECKSUM_MISMATCH",
                    summary="Sandbox changed since proposal/context creation; patch is stale.",
                    proposal=proposal,
                    context={"context_id": context_id, "approval_id": approval_id, "failed_command_id": context.command_id},
                    patch_artifact=str(repair_artifact.get("patch_path") or ""),
                    patch_checksum=str(repair_artifact.get("patch_checksum") or ""),
                    expected_sandbox_checksum=context.sandbox_checksum,
                    actual_sandbox_checksum=actual_sandbox_checksum,
                    expected_legacy_checksum=context.legacy_checksum,
                    actual_legacy_checksum=actual_legacy_checksum,
                    worktree_used=str(sandbox_path),
                    recommended_next_action="regenerate_proposal_against_current_sandbox",
                    assistant_followup_intent="regenerate_proposal_against_current_sandbox",
                ),
            )

        evidence_refs = json.loads(context.evidence_refs_json or "{}")
        deterministic_rule_id = str(evidence_refs.get("deterministic_rule_id") or "").strip()
        if not deterministic_rule_id:
            deterministic_rule_id = (
                "DEPENDENCY_ADD_H2_RUNTIME"
                if context.target_path.replace("\\", "/") == "pom.xml"
                else "JAKARTA_IMPORT_MECHANICAL_SOURCE"
            )
        h2_required = str(evidence_refs.get("h2_required") or "").lower() == "true"
        if deterministic_rule_id == "DEPENDENCY_ADD_H2_RUNTIME":
            h2_required = True
        expected_validation = tuple(
            item.strip()
            for item in str(evidence_refs.get("expected_validation") or "").split("|")
            if item.strip()
        )

        approved = RepairProposal(
            proposal_id=proposal.proposal_id,
            command_id=proposal.command_id,
            failure_summary=proposal.failure_summary,
            hypothesis=proposal.hypothesis,
            patch_summary=proposal.patch_summary,
            affected_paths=proposal.affected_paths,
            status="approved",
            approval_checksum=approval.approval_checksum,
            created_at=proposal.created_at,
            proposal_checksum=proposal.proposal_checksum,
            source_proposal_id=proposal.source_proposal_id,
            revision_of=proposal.revision_of,
            revision_number=proposal.revision_number,
            context_pack_checksum=proposal.context_pack_checksum,
            allowed_scope=proposal.allowed_scope,
            patch_package_json=proposal.patch_package_json,
        )
        self._proposals[proposal.proposal_id] = approved
        if self._repo is not None:
            self._repo.update_proposal_status(proposal.proposal_id, "approved", approval.approval_checksum)

        return self.apply_patch(
            proposal_id=guard.proposal_id,
            target_path=context.target_path,
            patch_content=context.patch_preview,
            run_id=run_id,
            run_dir=run_dir,
            sandbox_path=sandbox_path,
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            risk=str(evidence_refs.get("risk") or "LOW"),
            requires_human_review=False,
            expected_validation=expected_validation,
            limitations=(),
            failure_classification={},
            h2_required=h2_required,
            binding_checksum=context.context_pack_checksum,
            apply_failure_context={
                "context_id": context_id,
                "approval_id": approval_id,
                "failed_command_id": context.command_id,
                "expected_sandbox_checksum": context.sandbox_checksum,
                "actual_sandbox_checksum": actual_sandbox_checksum,
                "expected_legacy_checksum": context.legacy_checksum,
                "actual_legacy_checksum": actual_legacy_checksum,
            },
            validation_runner=validation_runner,
            event_recorder=event_recorder,
        )

    def _latest_action_for_proposal(
        self,
        proposal_id: str,
    ) -> SandboxAction | None:
        if proposal_id in {action.proposal_id for action in self._actions.values()}:
            for action in reversed(list(self._actions.values())):
                if action.proposal_id == proposal_id:
                    return action
        if self._repo is not None:
            records = self._repo.list_actions_by_proposal(proposal_id)
            if records:
                record = records[0]
                return SandboxAction(
                    action_id=record.action_id,
                    proposal_id=record.proposal_id,
                    target_path=record.target_path,
                    patch_content=record.patch_content,
                    status=record.status,
                    result_summary=record.result_summary,
                    created_at=record.created_at,
                    verification_status=record.verification_status,
                    verification_build_status=record.verification_build_status,
                    verification_test_status=record.verification_test_status,
                    verification_h2_status=record.verification_h2_status,
                    verification_artifact_refs_json=record.verification_artifact_refs_json,
                    verification_failure_classification_ref=record.verification_failure_classification_ref,
                )
        return None

    @classmethod
    def _proposal_target_checksums_match(
        cls,
        *,
        sandbox_path: Path,
        proposal: RepairProposal,
        checksum_key: str,
    ) -> bool:
        package = _json_object_or_empty(proposal.patch_package_json)
        targets = package.get("target_files")
        if not isinstance(targets, list) or not targets:
            return False
        for target in targets:
            if not isinstance(target, dict):
                return False
            rel_path = str(target.get("relative_path") or "").strip()
            expected = str(target.get(checksum_key) or "").strip()
            if not rel_path or not expected:
                return False
            path = sandbox_path / PurePosixPath(rel_path.replace("\\", "/"))
            if not path.is_file() or cls._sha256_file(path) != expected:
                return False
        return True

    @staticmethod
    def _sha256_file(path: Path) -> str:
        if not path.is_file():
            return ""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _excerpt(value: str, limit: int = 4000) -> str:
        text = str(value or "").strip()
        return text[-limit:] if len(text) > limit else text

    def _controlled_repair_verification(
        self,
        *,
        sandbox_path: Path,
        patch_package: dict[str, Any],
    ) -> dict[str, Any]:
        failure_evidence = patch_package.get("failure_evidence") if isinstance(patch_package.get("failure_evidence"), dict) else {}
        controlled = failure_evidence.get("controlled_demo_evidence")
        if not isinstance(controlled, dict) or controlled.get("controlled_demo") is not True:
            return {
                "status": "not_applicable",
                "code": "not_controlled_r6_demo",
                "summary": "Controlled target verification is not applicable.",
                "target_repaired": False,
            }
        target_files = patch_package.get("target_files") if isinstance(patch_package.get("target_files"), list) else []
        if not target_files:
            return {
                "status": "failed",
                "code": "controlled_target_missing",
                "summary": "Controlled target verification could not find target file metadata.",
                "target_repaired": False,
            }
        target = target_files[0] if isinstance(target_files[0], dict) else {}
        rel_path = str(target.get("relative_path") or controlled.get("target_file") or "").replace("\\", "/")
        expected_checksum = str(target.get("proposed_checksum") or "")
        proposed_namespace = str(controlled.get("proposed_import_namespace") or "")
        injected_namespace = str(controlled.get("injected_import_namespace") or "")
        target_path = (sandbox_path / rel_path).resolve()
        try:
            target_path.relative_to(sandbox_path.resolve())
        except ValueError:
            return {
                "status": "failed",
                "code": "controlled_target_escaped_sandbox",
                "summary": "Controlled target verification rejected escaped target path.",
                "target_repaired": False,
            }
        if not target_path.is_file():
            return {
                "status": "failed",
                "code": "controlled_target_missing",
                "summary": "Controlled target file is missing after patch apply.",
                "target_repaired": False,
            }
        text = target_path.read_text(encoding="utf-8")
        actual_checksum = self._sha256_text(text)
        repaired = (
            bool(expected_checksum)
            and actual_checksum == expected_checksum
            and bool(proposed_namespace)
            and proposed_namespace in text
            and (not injected_namespace or injected_namespace not in text)
        )
        return {
            "status": "passed" if repaired else "failed",
            "code": "controlled_target_repaired" if repaired else "controlled_target_not_repaired",
            "summary": (
                "Controlled target checksum matches proposed checksum and injected namespace is absent."
                if repaired
                else "Controlled target does not match proposed checksum or injected namespace remains."
            ),
            "target_repaired": repaired,
            "target_file": rel_path,
            "expected_checksum": expected_checksum,
            "actual_checksum": actual_checksum,
        }

    def _classify_maven_failure_after_controlled_repair(
        self,
        *,
        validation: ValidationResult,
        patch_package: dict[str, Any],
        controlled_verification: dict[str, Any],
    ) -> dict[str, Any]:
        failure_text = self._validation_failure_text(validation)
        controlled_applies = controlled_verification.get("status") != "not_applicable"
        controlled_failure_present = "package jakarta.servlet.http does not exist" in failure_text
        controlled_repaired = controlled_verification.get("status") == "passed"
        if controlled_applies and controlled_failure_present:
            classification = "controlled_failure_still_present"
        elif controlled_applies and controlled_repaired:
            classification = "unrelated_preexisting_failure"
        elif controlled_applies:
            classification = "unknown_maven_failure"
        else:
            classification = "maven_verification_failed"
        return {
            "classification": classification,
            "controlled_failure_still_present": controlled_failure_present,
            "pre_existing_failure_detected": classification == "unrelated_preexisting_failure",
        }

    def _validation_failure_text(self, validation: ValidationResult) -> str:
        chunks = list(validation.errors or []) + list(validation.warnings or [])
        for ref in (validation.artifact_refs or {}).values():
            path = Path(str(ref))
            if not path.is_file():
                continue
            try:
                chunks.append(path.read_text(encoding="utf-8", errors="ignore")[-12000:])
            except OSError:
                continue
        return "\n".join(str(item) for item in chunks)

    @staticmethod
    def _maven_failure_summary(classification: dict[str, Any], rolled_back: bool) -> str:
        rollback_text = "rolled back" if rolled_back else "rollback failed"
        if classification.get("classification") == "unrelated_preexisting_failure":
            return (
                "Controlled repair verified, but full Maven verification failed due unrelated/pre-existing "
                f"sandbox failures and patch was {rollback_text}."
            )
        if classification.get("classification") == "controlled_failure_still_present":
            return f"Controlled repair did not remove the original Jakarta/javax failure and patch was {rollback_text}."
        return f"Patch applied, but full Maven verification failed and patch was {rollback_text}."

    def _apply_failure_payload(
        self,
        *,
        failure_stage: str,
        failure_code: str,
        summary: str,
        proposal: RepairProposal,
        context: dict[str, Any] | None,
        patch_artifact: str,
        patch_checksum: str,
        expected_sandbox_checksum: str,
        actual_sandbox_checksum: str,
        expected_legacy_checksum: str,
        actual_legacy_checksum: str,
        worktree_used: str,
        strip_level: int = 1,
        git_executable: str = "",
        git_apply_check_stdout: str = "",
        git_apply_check_stderr: str = "",
        verification_artifacts: dict[str, str] | None = None,
        recommended_next_action: str = "regenerate_proposal_against_current_sandbox",
        assistant_followup_intent: str = "regenerate_proposal_against_current_sandbox",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = dict(context or {})
        payload = {
            "failure_stage": failure_stage,
            "failure_code": failure_code,
            "human_readable_summary": summary,
            "failed_command_id": str(ctx.get("failed_command_id") or proposal.command_id),
            "proposal_id": proposal.proposal_id,
            "context_id": str(ctx.get("context_id") or ""),
            "approval_id": str(ctx.get("approval_id") or ""),
            "patch_artifact": patch_artifact,
            "patch_checksum": patch_checksum,
            "expected_sandbox_checksum": expected_sandbox_checksum,
            "actual_sandbox_checksum": actual_sandbox_checksum,
            "expected_legacy_checksum": expected_legacy_checksum,
            "actual_legacy_checksum": actual_legacy_checksum,
            "worktree_used": worktree_used,
            "strip_level": strip_level,
            "git_executable": git_executable,
            "git_apply_check_stdout": self._excerpt(git_apply_check_stdout),
            "git_apply_check_stderr": self._excerpt(git_apply_check_stderr),
            "verification_artifacts": dict(verification_artifacts or {}),
            "recommended_next_action": recommended_next_action,
            "assistant_followup_intent": assistant_followup_intent,
        }
        payload.update(dict(extra or {}))
        return payload

    def get_apply_context(self, context_id: str) -> RepairApplyContext | None:
        if self._repo is None:
            return None
        record = self._repo.get_action(context_id)
        if record is None or record.status != "prepared_apply_context":
            return None
        return self._record_to_apply_context(record)

    def get_latest_approval(self, context_id: str) -> RepairApprovalRecord | None:
        return self._latest_approval_for_context(context_id)

    def get_approval(self, context_id: str, approval_id: str) -> RepairApprovalRecord | None:
        context = self.get_apply_context(context_id)
        if context is None or self._repo is None:
            return None
        for record in self._repo.list_actions_by_proposal(context.proposal_id):
            if record.action_id != approval_id or record.status != "approval_recorded":
                continue
            approval = self._record_to_approval(record)
            if approval.context_id == context_id:
                return approval
        return None

    def validate_apply_guard(
        self,
        *,
        context_id: str,
        approval_id: str,
        expected_approval_checksum: str,
        expected_sandbox_checksum: str,
        expected_legacy_checksum: str,
    ) -> RepairApplyGuardResult:
        context = self.get_apply_context(context_id)
        if context is None:
            raise ValueError(f"Repair apply context {context_id!r} not found")
        approval = self.get_approval(context_id, approval_id)
        if approval is None:
            raise ValueError(f"Repair approval {approval_id!r} not found for context {context_id!r}")
        if approval.approval_status != "recorded":
            raise ValueError("Repair approval must have status recorded")
        if approval.approval_scope != "sandbox_only":
            raise ValueError("Repair approval scope must be sandbox_only")
        if context.reviewer_decision != "accept":
            raise ValueError("Repair apply requires reviewer decision accept")
        if not context.approval_eligible:
            raise ValueError("Repair apply context is not approval eligible")
        if not context.patch_preview.strip() or not context.patch_preview_checksum.strip():
            raise ValueError("Repair apply requires patch preview and checksum")
        if not context.sandbox_reference.strip():
            raise ValueError("Repair apply requires sandbox reference")
        if not context.sandbox_checksum.strip() or not context.legacy_checksum.strip():
            raise ValueError("Repair apply requires checksum guards")
        if expected_approval_checksum != approval.approval_checksum:
            raise ValueError("Repair approval checksum mismatch")
        if expected_sandbox_checksum != context.sandbox_checksum or expected_sandbox_checksum != approval.sandbox_checksum:
            raise ValueError("Repair sandbox checksum mismatch")
        if expected_legacy_checksum != context.legacy_checksum or expected_legacy_checksum != approval.legacy_checksum:
            raise ValueError("Repair legacy checksum mismatch")
        if not self._is_sandbox_bound_target(context):
            raise ValueError("Repair apply target is not sandbox-bound")
        return RepairApplyGuardResult(
            context_id=context.context_id,
            approval_id=approval.approval_id,
            proposal_id=context.proposal_id,
            sandbox_reference=context.sandbox_reference,
            target_path=context.target_path,
            patch_preview_checksum=context.patch_preview_checksum,
            approval_checksum=approval.approval_checksum,
            sandbox_checksum=context.sandbox_checksum,
            legacy_checksum=context.legacy_checksum,
            apply_ready=True,
            blockers=(),
        )

    def _latest_context_for_proposal(self, proposal_id: str) -> RepairApplyContext | None:
        if self._repo is None:
            return None
        for record in self._repo.list_actions_by_proposal(proposal_id):
            if record.status == "prepared_apply_context":
                return self._record_to_apply_context(record)
        return None

    def _latest_approval_for_context(self, context_id: str) -> RepairApprovalRecord | None:
        context = self.get_apply_context(context_id)
        if context is None or self._repo is None:
            return None
        for record in self._repo.list_actions_by_proposal(context.proposal_id):
            if record.status != "approval_recorded":
                continue
            approval = self._record_to_approval(record)
            if approval.context_id == context_id:
                return approval
        return None

    def _idempotent_applied_action(
        self,
        proposal_id: str,
        proposal: RepairProposal,
    ) -> SandboxAction:
        existing = self._latest_action_for_proposal(proposal_id)
        if existing is not None and existing.status in {"applied", "idempotent"}:
            return SandboxAction(
                action_id=existing.action_id,
                proposal_id=existing.proposal_id,
                target_path=existing.target_path,
                patch_content=existing.patch_content,
                status="idempotent",
                result_summary="Proposal already applied; sandbox unchanged",
                created_at=existing.created_at,
                verification_status=existing.verification_status,
                verification_build_status=existing.verification_build_status,
                verification_test_status=existing.verification_test_status,
                verification_h2_status=existing.verification_h2_status,
                verification_artifact_refs_json=existing.verification_artifact_refs_json,
                verification_failure_classification_ref=existing.verification_failure_classification_ref,
            )
        target_path = proposal.affected_paths[0] if proposal.affected_paths else ""
        return SandboxAction(
            action_id=uuid4().hex,
            proposal_id=proposal.proposal_id,
            target_path=target_path,
            patch_content="",
            status="failed",
            result_summary="Proposal appears applied but no prior applied action proves idempotency.",
            created_at=utc_now_text(),
            verification_status="not_available",
        )

    def apply_reviewed_repair_diff(
        self,
        *,
        proposal_id: str,
        final_diff_ref: str | Path,
        final_diff_checksum: str,
        reviewer_output_checksum: str,
        expected_reviewer_output_checksum: str,
        policy_validation_checksum: str,
        expected_policy_validation_checksum: str,
        policy_status: str,
        expected_base_repo_state_checksum: str,
        current_base_repo_state_checksum: str,
        target_path: str,
        run_dir: str | Path,
        sandbox_path: str | Path,
        legacy_path: str | Path,
        deterministic_rule_id: str,
        run_id: str = "",
        risk: str = "LOW",
        expected_validation: tuple[str, ...] = (),
        h2_required: bool = False,
        validation_runner: ValidationRunner = run_validation_after_patch,
        event_recorder: RepairEventRecorder | None = None,
    ) -> SandboxAction:
        """Apply only an exact reviewed diff loaded from backend artifact storage."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = self._record_to_proposal(record)
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal_id!r} must be approved first")
        if not expected_reviewer_output_checksum or reviewer_output_checksum != expected_reviewer_output_checksum:
            raise ValueError("Reviewed diff cannot be applied: reviewer checksum mismatch")
        if not expected_policy_validation_checksum or policy_validation_checksum != expected_policy_validation_checksum:
            raise ValueError("Reviewed diff cannot be applied: policy validation checksum mismatch")
        if str(policy_status).lower() not in {"allowed", "allow"}:
            raise ValueError("Reviewed diff cannot be applied: policy validation is not allowed")
        if expected_base_repo_state_checksum != current_base_repo_state_checksum:
            raise ValueError("Reviewed diff cannot be applied: base repository state is stale")

        diff_path = Path(final_diff_ref)
        if not diff_path.is_file():
            raise ValueError(f"Reviewed repair diff artifact not found: {diff_path}")
        diff_content = diff_path.read_bytes().decode("utf-8")
        actual_diff_checksum = sha256_unified_diff_text(diff_content)
        if actual_diff_checksum != final_diff_checksum:
            raise ValueError("Reviewed repair diff artifact checksum mismatch")

        binding_checksum = sha256_canonical_json(
            {
                "proposal_id": proposal_id,
                "final_diff_checksum": final_diff_checksum,
                "reviewer_output_checksum": reviewer_output_checksum,
                "policy_validation_checksum": policy_validation_checksum,
                "base_repo_state_checksum": expected_base_repo_state_checksum,
            }
        )
        return self.apply_patch(
            proposal_id=proposal_id,
            target_path=target_path,
            patch_content=diff_content,
            run_id=run_id,
            run_dir=run_dir,
            sandbox_path=sandbox_path,
            legacy_path=legacy_path,
            deterministic_rule_id=deterministic_rule_id,
            risk=risk,
            requires_human_review=False,
            expected_validation=expected_validation,
            h2_required=h2_required,
            binding_checksum=binding_checksum,
            validation_runner=validation_runner,
            event_recorder=event_recorder,
        )

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
            source_proposal_id=proposal.source_proposal_id,
            revision_of=proposal.revision_of,
            revision_number=proposal.revision_number,
            context_pack_checksum=proposal.context_pack_checksum,
            allowed_scope=proposal.allowed_scope,
            patch_package_json=proposal.patch_package_json,
        )
        if self._repo is not None:
            self._repo.update_proposal_status(proposal.proposal_id, "applied")
        self._proposals[proposal.proposal_id] = updated

    def _save_context(self, context: RepairApplyContext) -> None:
        if self._repo is None:
            raise ValueError("Repair apply context persistence requires a repair repository")
        self._repo.save_action(
            V2SandboxActionRecord(
                action_id=context.context_id,
                proposal_id=context.proposal_id,
                target_path=context.target_path,
                patch_content=context.patch_preview,
                status="prepared_apply_context",
                result_summary=json.dumps(
                    {
                        "kind": "repair_apply_context_v1",
                        "context_id": context.context_id,
                        "command_id": context.command_id,
                        "reviewer_critique_id": context.reviewer_critique_id,
                        "proposer_invocation_id": context.proposer_invocation_id,
                        "reviewer_invocation_id": context.reviewer_invocation_id,
                        "reviewer_decision": context.reviewer_decision,
                        "proposal_summary": context.proposal_summary,
                        "patch_preview_checksum": context.patch_preview_checksum,
                        "sandbox_reference": context.sandbox_reference,
                        "sandbox_checksum": context.sandbox_checksum,
                        "legacy_checksum": context.legacy_checksum,
                        "context_pack_checksum": context.context_pack_checksum,
                        "proposal_checksum": context.proposal_checksum,
                        "evidence_refs": json.loads(context.evidence_refs_json),
                        "approval_eligible": context.approval_eligible,
                        "blockers": json.loads(context.blockers_json),
                        "approval_scope": context.approval_scope,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=context.created_at,
            )
        )

    def _save_approval(self, context: RepairApplyContext, approval: RepairApprovalRecord) -> None:
        if self._repo is None:
            raise ValueError("Repair approval persistence requires a repair repository")
        self._repo.save_action(
            V2SandboxActionRecord(
                action_id=approval.approval_id,
                proposal_id=approval.proposal_id,
                target_path=context.target_path,
                patch_content="",
                status="approval_recorded",
                result_summary=json.dumps(
                    {
                        "kind": "repair_approval_record_v1",
                        "approval_id": approval.approval_id,
                        "context_id": approval.context_id,
                        "approval_status": approval.approval_status,
                        "approval_scope": approval.approval_scope,
                        "approval_note": approval.approval_note,
                        "approval_checksum": approval.approval_checksum,
                        "sandbox_checksum": approval.sandbox_checksum,
                        "legacy_checksum": approval.legacy_checksum,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                created_at=approval.created_at,
            )
        )

    def _get_proposal_or_raise(self, proposal_id: str) -> RepairProposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None and self._repo is not None:
            record = self._repo.get_proposal(proposal_id)
            if record is not None:
                proposal = self._record_to_proposal(record)
                self._proposals[proposal_id] = proposal
        if proposal is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        return proposal

    def _build_patch_package_json(
        self,
        *,
        command_id: str,
        failure_summary: str,
        affected_paths: tuple[str, ...],
        verification_command: tuple[str, ...],
        controlled_demo_evidence: dict[str, Any] | None = None,
    ) -> str:
        if self._job_repo is None or self._setup_repo is None or self._command_repo is None:
            return "{}"
        command = self._command_repo.get(command_id)
        if command is None:
            return "{}"
        job = self._job_repo.get(command.job_id)
        if job is None:
            return "{}"
        setup = self._setup_repo.get(job.setup_id)
        if setup is None:
            return "{}"

        result_data: dict[str, Any] = {}
        if command.result_json:
            try:
                parsed = json.loads(command.result_json)
                if isinstance(parsed, dict):
                    result_data = parsed
            except (json.JSONDecodeError, TypeError):
                result_data = {}
        run_id = str(result_data.get("run_id") or "").strip()
        sandbox_text = str(result_data.get("sandbox_path") or "").strip()
        if not run_id or not sandbox_text:
            return "{}"
        sandbox_path = Path(sandbox_text)
        legacy_path = Path(setup.legacy_app_path)
        if not sandbox_path.is_absolute() or not legacy_path.is_absolute() or not sandbox_path.exists():
            return "{}"
        run_dir = self._resolve_bound_run_dir(
            result_data=result_data,
            setup_output_parent=setup.output_parent_path,
            sandbox_path=sandbox_path,
            run_id=run_id,
            error_cls=ValueError,
            command_id=command_id,
        )

        targets: list[dict[str, Any]] = []
        unified_diffs: list[str] = []
        blockers: list[str] = []
        repair_family = ""
        for raw_path in affected_paths:
            rel_path = str(raw_path).replace("\\", "/").strip()
            if not rel_path or Path(rel_path).is_absolute() or ".." in Path(rel_path).parts:
                blockers.append(f"target path is not a safe relative path: {raw_path}")
                continue
            absolute_path = (sandbox_path / rel_path).resolve()
            if not self._is_sandbox_bound_target_values(target_path=absolute_path, sandbox_path=sandbox_path):
                blockers.append(f"target path escapes sandbox: {rel_path}")
                continue
            if absolute_path == legacy_path.resolve() or absolute_path.is_relative_to(legacy_path.resolve()):
                blockers.append(f"target path touches legacy: {rel_path}")
                continue
            if not absolute_path.is_file():
                blockers.append(f"target file is missing: {rel_path}")
                continue
            before_text = absolute_path.read_text(encoding="utf-8")
            after_text, target_repair_family = self._propose_deterministic_source_fix(
                before_text,
                failure_summary,
            )
            if target_repair_family:
                if repair_family and repair_family != target_repair_family:
                    blockers.append("mixed repair families are not supported")
                repair_family = repair_family or target_repair_family
            before_checksum = self._sha256_text(before_text)
            after_checksum = self._sha256_text(after_text)
            target: dict[str, Any] = {
                "relative_path": rel_path,
                "absolute_path": str(absolute_path),
                "before_checksum": before_checksum,
                "proposed_checksum": after_checksum,
                "repair_family": target_repair_family,
            }
            if after_text == before_text:
                blockers.append(f"no concrete patch generated for target: {rel_path}")
            else:
                unified_diffs.append(self._build_unified_diff(rel_path, before_text, after_text))
            targets.append(target)

        unified_diff = "".join(unified_diffs)
        patch_checksum = self._sha256_text(unified_diff) if unified_diff else ""
        repairs_dir = run_dir / "repairs" / "proposals"
        repairs_dir.mkdir(parents=True, exist_ok=True)
        patch_slug = (patch_checksum.split(":", 1)[-1] if ":" in patch_checksum else patch_checksum)[:12] or "missing"
        patch_path = repairs_dir / f"patch-{patch_slug}.diff"
        if unified_diff:
            patch_path.write_text(unified_diff, encoding="utf-8")
            patch_valid, patch_error = validate_patch_artifact(patch_path=patch_path, cwd=sandbox_path)
            if not patch_valid:
                raise ValueError(f"REPAIR_PATCH_INVALID: {patch_error}")

        failure_evidence = {
            "verification_command": list(verification_command),
            "cwd": str(sandbox_path),
            "exit_code": 1,
            "stdout_stderr_tail": failure_summary,
            "diagnostic_line": self._diagnostic_line(failure_summary),
            "failing_file": targets[0]["relative_path"] if targets else "",
        }
        if controlled_demo_evidence:
            evidence = dict(controlled_demo_evidence)
            failure_evidence["controlled_demo_evidence"] = evidence
            if isinstance(evidence.get("dependency_alignment"), dict):
                failure_evidence["dependency_alignment"] = evidence["dependency_alignment"]
        package: dict[str, Any] = {
            "schema_version": "1.0",
            "command_id": command_id,
            "job_id": command.job_id,
            "run_id": run_id,
            "sandbox_path": str(sandbox_path),
            "sandbox_checksum": self._path_tree_checksum(sandbox_path),
            "legacy_checksum": self._path_tree_checksum(legacy_path),
            "repair_family": repair_family,
            "deterministic_rule_id": repair_family if repair_family == "JAKARTA_IMPORT_MECHANICAL_SOURCE" else "",
            "failure_evidence": failure_evidence,
            "target_files": targets,
            "repair_artifact": {
                "unified_diff": unified_diff,
                "patch_path": str(patch_path) if unified_diff else "",
                "patch_checksum": patch_checksum,
            },
            "containment": {
                "all_targets_under_sandbox": not any("escapes sandbox" in item for item in blockers),
                "legacy_target_present": any("touches legacy" in item for item in blockers),
                "sandbox_outside_legacy": not self._is_sandbox_bound_target_values(
                    target_path=sandbox_path,
                    sandbox_path=legacy_path,
                ),
            },
            "verification_plan": {
                "command": list(verification_command),
                "cwd": str(sandbox_path),
                "llm_during_verification": False,
            },
            "approval_apply_separate": True,
            "blockers": blockers,
        }
        package["package_checksum"] = sha256_canonical_json(package)
        evidence_path = repairs_dir / f"evidence-{str(package['package_checksum'])[:12]}.json"
        evidence_path.write_text(json.dumps(package, indent=2, sort_keys=True), encoding="utf-8")
        package["evidence_artifact_path"] = str(evidence_path)
        package["package_checksum"] = sha256_canonical_json(package)
        return json.dumps(package, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _sha256_text(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _path_tree_checksum(root: Path) -> str:
        digest = hashlib.sha256()
        if root.is_file():
            digest.update(root.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(root.read_bytes())
            return "sha256:" + digest.hexdigest()
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.relative_to(root).as_posix()):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".git/") or rel.startswith(".migration/") or "/.git/" in rel or "/.migration/" in rel:
                continue
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return "sha256:" + digest.hexdigest()

    @staticmethod
    def _build_unified_diff(rel_path: str, before_text: str, after_text: str) -> str:
        diff = difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            lineterm="",
        )
        return "\n".join([f"diff --git a/{rel_path} b/{rel_path}", *diff]) + "\n"

    @staticmethod
    def _diagnostic_line(text: str) -> str:
        for line in text.splitlines():
            if "cannot find symbol" in line or "doesNotCompile" in line:
                return line.strip()
            if "does not exist" in line and ("package javax." in line or "package jakarta." in line):
                return line.strip()
        return text.strip().splitlines()[0] if text.strip() else ""

    @classmethod
    def _propose_deterministic_source_fix(cls, source: str, failure_summary: str) -> tuple[str, str]:
        import_fix = cls._propose_import_package_source_fix(source, failure_summary)
        if import_fix != source:
            return import_fix, "JAKARTA_IMPORT_MECHANICAL_SOURCE"

        controlled_fix = cls._propose_controlled_source_fix(source, failure_summary)
        if controlled_fix != source:
            return controlled_fix, "CONTROLLED_ASSIGNMENT_SOURCE"
        return source, ""

    @staticmethod
    def _propose_import_package_source_fix(source: str, failure_summary: str) -> str:
        match = re.search(
            r"package\s+(javax|jakarta)\.([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s+does\s+not\s+exist",
            failure_summary,
        )
        if not match:
            return source

        from_namespace = match.group(1)
        package_suffix = match.group(2)
        to_namespace = "jakarta" if from_namespace == "javax" else "javax"
        package_prefix = re.escape(f"{from_namespace}.{package_suffix}")
        lines = source.splitlines(keepends=True)
        line_pattern = re.compile(
            rf"^(?P<indent>\s*)(?P<kind>import|package)\s+{package_prefix}"
            r"(?P<tail>(?:\.[A-Za-z_][A-Za-z0-9_]*|\.\*)*)\s*;(?P<ending>\r?\n?)$"
        )
        for index, line in enumerate(lines):
            line_match = line_pattern.match(line)
            if line_match is None:
                continue
            lines[index] = (
                f"{line_match.group('indent')}{line_match.group('kind')} "
                f"{to_namespace}.{package_suffix}{line_match.group('tail')};"
                f"{line_match.group('ending')}"
            )
            return "".join(lines)
        return source

    @staticmethod
    def _propose_controlled_source_fix(source: str, failure_summary: str) -> str:
        match = re.search(r"variable\s+([A-Za-z_][A-Za-z0-9_]*)", failure_summary)
        symbol = match.group(1) if match else "doesNotCompile"
        return re.sub(
            rf"=\s*{re.escape(symbol)}\s*;",
            "= 0;",
            source,
            count=1,
        )

    def _record_to_proposal(self, record: V2RepairProposalRecord) -> RepairProposal:
        affected_paths = tuple(json.loads(record.affected_paths_json))
        return RepairProposal(
            proposal_id=record.proposal_id,
            command_id=record.command_id,
            failure_summary=record.failure_summary,
            hypothesis=record.hypothesis,
            patch_summary=record.patch_summary,
            affected_paths=affected_paths,
            status=record.status,
            approval_checksum=record.approval_checksum,
            created_at=record.created_at,
            proposal_checksum=record.proposal_checksum
            or self._proposal_checksum(
                command_id=record.command_id,
                failure_summary=record.failure_summary,
                hypothesis=record.hypothesis,
                patch_summary=record.patch_summary,
                affected_paths=affected_paths,
                source_proposal_id=record.source_proposal_id,
                revision_of=record.revision_of,
                revision_number=record.revision_number,
                context_pack_checksum=record.context_pack_checksum,
                allowed_scope=record.allowed_scope,
                patch_package_json=record.patch_package_json,
            ),
            source_proposal_id=record.source_proposal_id,
            revision_of=record.revision_of,
            revision_number=record.revision_number,
            context_pack_checksum=record.context_pack_checksum,
            allowed_scope=record.allowed_scope,
            patch_package_json=record.patch_package_json,
        )

    def _record_to_apply_context(self, record: V2SandboxActionRecord) -> RepairApplyContext:
        payload = json.loads(record.result_summary or "{}")
        evidence_refs = payload.get("evidence_refs") or {}
        blockers = payload.get("blockers") or []
        return RepairApplyContext(
            context_id=record.action_id,
            proposal_id=record.proposal_id,
            command_id=str(payload.get("command_id") or ""),
            reviewer_critique_id=str(payload.get("reviewer_critique_id") or ""),
            proposer_invocation_id=str(payload.get("proposer_invocation_id") or ""),
            reviewer_invocation_id=str(payload.get("reviewer_invocation_id") or ""),
            reviewer_decision=str(payload.get("reviewer_decision") or ""),
            proposal_summary=str(payload.get("proposal_summary") or ""),
            patch_preview=record.patch_content,
            patch_preview_checksum=str(payload.get("patch_preview_checksum") or ""),
            target_path=record.target_path,
            sandbox_reference=str(payload.get("sandbox_reference") or ""),
            sandbox_checksum=str(payload.get("sandbox_checksum") or ""),
            legacy_checksum=str(payload.get("legacy_checksum") or ""),
            context_pack_checksum=str(payload.get("context_pack_checksum") or ""),
            proposal_checksum=str(payload.get("proposal_checksum") or ""),
            evidence_refs_json=json.dumps(evidence_refs, separators=(",", ":"), sort_keys=True),
            approval_eligible=bool(payload.get("approval_eligible", False)),
            blockers_json=json.dumps(list(blockers), separators=(",", ":")),
            approval_scope=str(payload.get("approval_scope") or "sandbox_only"),
            created_at=record.created_at,
        )

    def _record_to_approval(self, record: V2SandboxActionRecord) -> RepairApprovalRecord:
        payload = json.loads(record.result_summary or "{}")
        return RepairApprovalRecord(
            approval_id=record.action_id,
            context_id=str(payload.get("context_id") or ""),
            proposal_id=record.proposal_id,
            approval_status=str(payload.get("approval_status") or record.status),
            approval_scope=str(payload.get("approval_scope") or ""),
            approval_note=str(payload.get("approval_note") or ""),
            approval_checksum=str(payload.get("approval_checksum") or ""),
            sandbox_checksum=str(payload.get("sandbox_checksum") or ""),
            legacy_checksum=str(payload.get("legacy_checksum") or ""),
            created_at=record.created_at,
        )

    @staticmethod
    def _absolute_path_or_none(value: object) -> Path | None:
        text = str(value or "").strip()
        if not text or text.startswith("[redacted"):
            return None
        path = Path(text)
        return path if path.is_absolute() else None

    def _resolve_bound_run_dir(
        self,
        *,
        result_data: dict[str, Any],
        setup_output_parent: str,
        sandbox_path: Path,
        run_id: str,
        error_cls: type[Exception],
        command_id: str,
    ) -> Path:
        output_root = next(
            (
                path
                for path in (
                    self._absolute_path_or_none(result_data.get("output_root_dir")),
                    self._absolute_path_or_none(result_data.get("modernized_app_path")),
                    self._absolute_path_or_none(setup_output_parent),
                )
                if path is not None
            ),
            None,
        )
        run_dir = (
            output_root / ".migration" / "runs" / run_id
            if output_root is not None
            else self._run_dir_from_sandbox(sandbox_path=sandbox_path, run_id=run_id)
        )
        if run_dir is None:
            raise error_cls(f"Command {command_id!r} cannot resolve absolute output root")
        try:
            sandbox_path.resolve().relative_to(run_dir.resolve())
        except (OSError, ValueError) as exc:
            raise error_cls("Repair sandbox is outside the bound run root") from exc
        return run_dir

    @staticmethod
    def _run_dir_from_sandbox(*, sandbox_path: Path, run_id: str) -> Path | None:
        resolved = sandbox_path.resolve()
        for parent in (resolved, *resolved.parents):
            if (
                parent.name == run_id
                and parent.parent.name == "runs"
                and parent.parent.parent.name == ".migration"
            ):
                return parent
        return None

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
        context_pack_checksum = proposal.context_pack_checksum
        patch_package = _json_or_text(proposal.patch_package_json)
        if isinstance(patch_package, dict) and patch_package:
            context_pack_checksum = context_pack_checksum or str(patch_package.get("package_checksum") or "")
            result["patch_package"] = patch_package
            result["target_files"] = patch_package.get("target_files", [])
            result["failure_evidence"] = patch_package.get("failure_evidence", {})
            result["repair_artifact"] = patch_package.get("repair_artifact", {})
            result["verification_plan"] = patch_package.get("verification_plan", {})
            result["containment"] = patch_package.get("containment", {})
            result["sandbox_checksum"] = patch_package.get("sandbox_checksum", "")
            result["legacy_checksum"] = patch_package.get("legacy_checksum", "")
            result["repair_family"] = patch_package.get("repair_family", "")
            result["deterministic_rule_id"] = patch_package.get("deterministic_rule_id", "")
        if context_pack_checksum:
            result["context_pack_checksum"] = context_pack_checksum
        return result

    def action_to_dict(self, action: SandboxAction) -> dict[str, Any]:
        summary = action.result_summary
        apply_failure = None
        parsed = _json_object_or_empty(action.result_summary)
        if parsed.get("kind") == "repair_apply_result_v1":
            summary = str(parsed.get("human_readable_summary") or "")
            failure = parsed.get("apply_failure")
            apply_failure = failure if isinstance(failure, dict) else None
        result = {
            "action_id": action.action_id,
            "proposal_id": action.proposal_id,
            "target_path": action.target_path,
            "patch_content": action.patch_content[:100] if action.patch_content else "",
            "status": action.status,
            "result_summary": summary,
            "created_at": action.created_at,
            "verification_status": action.verification_status,
            "verification_build_status": action.verification_build_status,
            "verification_test_status": action.verification_test_status,
            "verification_h2_status": action.verification_h2_status,
            "verification_artifact_refs": json.loads(action.verification_artifact_refs_json or "{}"),
            "verification_failure_classification_ref": action.verification_failure_classification_ref,
            "human_approved": True,
            "sandbox_only": True,
            "source_mutated": False,
            "sandbox_mutated": action.status == "applied",
            "stage_resumed": False,
            "backend_runner_invoked": False,
            "llm_invoked": False,
            "approval_bypass": False,
        }
        if apply_failure is not None:
            result["apply_failure"] = apply_failure
        return result

    def apply_context_to_dict(self, context: RepairApplyContext) -> dict[str, Any]:
        return {
            "context_id": context.context_id,
            "proposal_id": context.proposal_id,
            "command_id": context.command_id,
            "reviewer_critique_id": context.reviewer_critique_id,
            "proposer_invocation_id": context.proposer_invocation_id,
            "reviewer_invocation_id": context.reviewer_invocation_id,
            "reviewer_decision": context.reviewer_decision,
            "proposal_summary": context.proposal_summary,
            "patch_preview": context.patch_preview,
            "patch_preview_checksum": context.patch_preview_checksum,
            "target_path": context.target_path,
            "sandbox_reference": context.sandbox_reference,
            "sandbox_checksum": context.sandbox_checksum,
            "legacy_checksum": context.legacy_checksum,
            "proposal_checksum": context.proposal_checksum,
            "context_pack_checksum": context.context_pack_checksum,
            "evidence_refs": json.loads(context.evidence_refs_json or "{}"),
            "approval_eligible": context.approval_eligible,
            "blockers": json.loads(context.blockers_json or "[]"),
            "approval_scope": context.approval_scope,
            "created_at": context.created_at,
            "sandbox_only": True,
            "source_mutated": False,
            "apply_ready": False,
            "llm_invoked": False,
        }

    def approval_to_dict(self, approval: RepairApprovalRecord) -> dict[str, Any]:
        return {
            "approval_id": approval.approval_id,
            "context_id": approval.context_id,
            "proposal_id": approval.proposal_id,
            "approval_status": approval.approval_status,
            "approval_scope": approval.approval_scope,
            "approval_note": approval.approval_note,
            "approval_checksum": approval.approval_checksum,
            "sandbox_checksum": approval.sandbox_checksum,
            "legacy_checksum": approval.legacy_checksum,
            "created_at": approval.created_at,
            "apply_ready": True,
            "sandbox_only": True,
            "source_mutated": False,
            "llm_invoked": False,
        }

    def apply_guard_to_dict(self, guard: RepairApplyGuardResult) -> dict[str, Any]:
        return {
            "context_id": guard.context_id,
            "approval_id": guard.approval_id,
            "proposal_id": guard.proposal_id,
            "sandbox_reference": guard.sandbox_reference,
            "target_path": guard.target_path,
            "patch_preview_checksum": guard.patch_preview_checksum,
            "approval_checksum": guard.approval_checksum,
            "sandbox_checksum": guard.sandbox_checksum,
            "legacy_checksum": guard.legacy_checksum,
            "apply_ready": guard.apply_ready,
            "blockers": list(guard.blockers),
            "sandbox_only": True,
            "source_mutated": False,
            "llm_invoked": False,
        }

    @staticmethod
    def _is_sandbox_bound_target(context: RepairApplyContext) -> bool:
        target = context.target_path.strip()
        sandbox = context.sandbox_reference.strip()
        if not target or not sandbox:
            return False
        target_path = Path(target)
        if not target_path.is_absolute():
            return ".." not in target_path.parts
        try:
            sandbox_path = Path(sandbox)
            if not sandbox_path.is_absolute():
                return False
            return V2RepairFlowService._is_sandbox_bound_target_values(
                target_path=target_path,
                sandbox_path=sandbox_path,
            )
        except (OSError, ValueError):
            return False

    @staticmethod
    def _is_sandbox_bound_target_values(*, target_path: Path, sandbox_path: Path) -> bool:
        try:
            target_path.resolve().relative_to(sandbox_path.resolve())
            return True
        except (OSError, ValueError):
            return False

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
        patch_package_json: str = "{}",
    ) -> str:
        payload: dict[str, Any] = {
            "command_id": command_id,
            "failure_summary": failure_summary,
            "hypothesis": hypothesis,
            "patch_summary": patch_summary,
            "affected_paths": list(affected_paths),
            "patch_package": _json_or_text(patch_package_json),
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

    @staticmethod
    def _patch_package_checksum(patch_package_json: str) -> str | None:
        patch_package = _json_or_text(patch_package_json)
        if not isinstance(patch_package, dict):
            return None
        checksum = str(patch_package.get("package_checksum") or "").strip()
        return checksum or None
