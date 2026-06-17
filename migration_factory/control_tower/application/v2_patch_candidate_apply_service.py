"""Apply persisted gate-allowed patch candidates through governed repair flow."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from migration_factory.control_tower.application.v2_patch_candidate_service import (
    PatchCandidate,
    V2PatchCandidateService,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    RepairProposal,
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2PatchCandidateRecord,
)
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal
from migration_factory.repair_loop.validation_runner import (
    run_validation_after_patch,
)


@dataclass(frozen=True)
class PatchCandidateApplyResult:
    patch_candidate_id: str
    proposal_id: str
    apply_status: str
    candidate_status: str
    result_summary: str
    validation_status: str
    rollback_status: str
    artifact_refs: dict[str, str]
    applied: bool
    rolled_back: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2PatchCandidateApplyService:
    def __init__(
        self,
        *,
        repair_repo: SqliteV2RepairRepository,
        reviewer_service: V2ReviewerService,
        command_repo: SqliteV2CommandRepository,
        repair_flow: V2RepairFlowService | None = None,
    ) -> None:
        self._repair_repo = repair_repo
        self._reviewer = reviewer_service
        self._command_repo = command_repo
        self._repair_flow = repair_flow or V2RepairFlowService(
            repair_repo=repair_repo,
            reviewer_service=reviewer_service,
        )

    def apply_patch_candidate(
        self,
        *,
        patch_candidate_id: str,
        patch_candidate_checksum: str,
        operator_note: str = "",
        validation_runner=run_validation_after_patch,
    ) -> PatchCandidateApplyResult:
        candidate_record = self._load_candidate_record(patch_candidate_id)
        proposal = self._load_proposal(candidate_record.proposal_id)
        candidate = self._record_to_candidate(candidate_record)
        self._require_candidate_ready(candidate_record, candidate, patch_candidate_checksum, proposal)
        sandbox_path = self._resolve_sandbox_path(proposal.command_id)

        gate = evaluate_patch_proposal(
            proposal={
                "deterministic_rule_id": self._rule_id_for_candidate(candidate_record),
                "risk": "LOW",
                "requires_human_review": False,
                "description": proposal.patch_summary,
                "unified_diff": candidate.unified_diff,
                "expected_validation": [],
                "limitations": ["apply from persisted patch candidate only"],
            },
            sandbox_path=sandbox_path,
            run_dir=self._apply_run_dir(sandbox_path, patch_candidate_id),
            legacy_path=self._legacy_guard_path(sandbox_path),
            failure_classification={"failure_type": proposal.failure_summary},
            h2_required=False,
        )
        if gate.status != "ALLOWED":
            result = PatchCandidateApplyResult(
                patch_candidate_id=patch_candidate_id,
                proposal_id=proposal.proposal_id,
                apply_status="gate_blocked_at_apply",
                candidate_status="gate_blocked_at_apply",
                result_summary=gate.reason,
                validation_status="NOT_RUN",
                rollback_status="NOT_NEEDED",
                artifact_refs={},
                applied=False,
                rolled_back=False,
            )
            self._persist_apply_result(
                patch_candidate_id=patch_candidate_id,
                status="gate_blocked_at_apply",
                gate_status=gate.status,
                gate_reason=gate.reason,
                result_summary=gate.reason,
                validation_status="NOT_RUN",
                rollback_status="NOT_NEEDED",
                artifact_refs={},
                applied_action_id="",
                operator_note=operator_note,
            )
            return result

        run_dir = self._apply_run_dir(sandbox_path, patch_candidate_id)
        action = self._repair_flow.apply_patch(
            proposal_id=proposal.proposal_id,
            target_path=(candidate.touched_paths[0] if candidate.touched_paths else "pom.xml"),
            patch_content=candidate.unified_diff,
            run_dir=run_dir,
            sandbox_path=sandbox_path,
            legacy_path=self._legacy_guard_path(sandbox_path),
            deterministic_rule_id=self._rule_id_for_candidate(candidate_record),
            risk="LOW",
            requires_human_review=False,
            expected_validation=(),
            limitations=("apply from persisted patch candidate only",),
            failure_classification={"failure_type": proposal.failure_summary},
            h2_required=False,
            run_id=patch_candidate_id,
            binding_checksum=candidate.patch_candidate_checksum,
            validation_runner=validation_runner,
        )
        artifact_refs = self._artifact_refs_from_run_dir(run_dir)
        validation_status = self._validation_status_from_result_summary(action.result_summary)
        rollback_status = "ROLLED_BACK" if action.status == "rolled_back" else ("NOT_NEEDED" if action.status == "applied" else "UNKNOWN")
        candidate_status = {
            "applied": "applied",
            "rolled_back": "rolled_back",
            "failed": "apply_failed",
        }.get(action.status, "apply_failed")
        self._persist_apply_result(
            patch_candidate_id=patch_candidate_id,
            status=candidate_status,
            gate_status="ALLOWED",
            gate_reason=gate.reason,
            result_summary=action.result_summary,
            validation_status=validation_status,
            rollback_status=rollback_status,
            artifact_refs=artifact_refs,
            applied_action_id=action.action_id,
            operator_note=operator_note,
        )
        return PatchCandidateApplyResult(
            patch_candidate_id=patch_candidate_id,
            proposal_id=proposal.proposal_id,
            apply_status=action.status,
            candidate_status=candidate_status,
            result_summary=action.result_summary,
            validation_status=validation_status,
            rollback_status=rollback_status,
            artifact_refs=artifact_refs,
            applied=(action.status == "applied"),
            rolled_back=(action.status == "rolled_back"),
        )

    def _load_candidate_record(self, patch_candidate_id: str) -> V2PatchCandidateRecord:
        record = self._repair_repo.get_patch_candidate(patch_candidate_id)
        if record is None:
            raise ValueError(f"Patch candidate {patch_candidate_id!r} not found")
        return record

    def _load_proposal(self, proposal_id: str) -> RepairProposal:
        record = self._repair_repo.get_proposal(proposal_id)
        if record is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        return V2RepairFlowService.record_to_proposal(record)

    def _record_to_candidate(self, record: V2PatchCandidateRecord) -> PatchCandidate:
        return PatchCandidate(
            patch_candidate_id=record.patch_candidate_id,
            proposal_id=record.proposal_id,
            proposal_checksum=record.proposal_checksum,
            diagnosis_id=record.diagnosis_id,
            diagnosis_checksum=record.diagnosis_checksum,
            evidence_pack_checksum=record.evidence_pack_checksum,
            context_pack_checksum=record.context_pack_checksum,
            unified_diff=record.unified_diff,
            patch_candidate_checksum=record.patch_candidate_checksum,
            materialization_strategy=record.materialization_strategy,
            status=record.status,
            gate_status=record.gate_status,
            gate_reason=record.gate_reason,
            touched_paths=tuple(json.loads(record.touched_paths_json)),
            created_at=record.created_at,
        )

    def _require_candidate_ready(
        self,
        record: V2PatchCandidateRecord,
        candidate: PatchCandidate,
        request_checksum: str,
        proposal: RepairProposal,
    ) -> None:
        if record.status != "gate_allowed":
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} must be gate_allowed before apply")
        if not candidate.unified_diff.strip():
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has empty unified diff")
        recomputed = V2PatchCandidateService.compute_patch_candidate_checksum(
            proposal=proposal,
            unified_diff=candidate.unified_diff,
            materialization_strategy=candidate.materialization_strategy,
            gate_status=candidate.gate_status,
            gate_reason=candidate.gate_reason,
            touched_paths=candidate.touched_paths,
        )
        if recomputed != candidate.patch_candidate_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} checksum no longer matches persisted payload")
        if request_checksum != candidate.patch_candidate_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} checksum mismatch")
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal.proposal_id!r} must remain approved before apply")
        if proposal.proposal_checksum != candidate.proposal_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has stale proposal checksum binding")
        if proposal.diagnosis_id != candidate.diagnosis_id:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has stale diagnosis binding")
        if proposal.diagnosis_checksum != candidate.diagnosis_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has stale diagnosis checksum binding")
        if proposal.evidence_pack_checksum != candidate.evidence_pack_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has stale evidence checksum binding")
        if (proposal.context_pack_checksum or "") != candidate.context_pack_checksum:
            raise ValueError(f"Patch candidate {record.patch_candidate_id!r} has stale context checksum binding")
        self._require_current_human_approval(proposal)
        self._require_current_reviewer_accept(proposal)

    def _require_current_human_approval(self, proposal: RepairProposal) -> None:
        latest = self._repair_repo.get_latest_approval_decision(proposal.proposal_id)
        if latest is None or latest.operator_decision != "approve":
            raise ValueError(f"Proposal {proposal.proposal_id!r} lacks current human approval")
        if latest.approval_checksum != proposal.proposal_checksum:
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale human approval checksum")
        if latest.proposal_checksum != proposal.proposal_checksum:
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale approval proposal checksum binding")
        if latest.context_pack_checksum != (proposal.context_pack_checksum or ""):
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale human approval context binding")

    def _require_current_reviewer_accept(self, proposal: RepairProposal) -> None:
        for critique in self._reviewer.list_critiques(proposal.proposal_id):
            if (
                critique.proposal_checksum == proposal.proposal_checksum
                and critique.context_pack_checksum == (proposal.context_pack_checksum or "")
            ):
                if critique.decision != "accept":
                    raise ValueError(
                        f"Proposal {proposal.proposal_id!r} reviewer binding is stale: latest decision is {critique.decision}"
                    )
                return
        raise ValueError(f"Proposal {proposal.proposal_id!r} reviewer binding is stale or missing")

    def _resolve_sandbox_path(self, command_id: str) -> Path:
        command = self._command_repo.get(command_id)
        if command is None or not command.result_json:
            raise ValueError(f"Command {command_id!r} has no sandbox binding for apply")
        try:
            result = json.loads(command.result_json)
        except (json.JSONDecodeError, TypeError):
            raise ValueError(f"Command {command_id!r} result_json is invalid for apply") from None
        sandbox_path = str(result.get("sandbox_path") or "").strip()
        if not sandbox_path:
            raise ValueError(f"Command {command_id!r} has no sandbox_path for apply")
        return Path(sandbox_path).resolve()

    @staticmethod
    def _rule_id_for_candidate(record: V2PatchCandidateRecord) -> str:
        if record.materialization_strategy == "deterministic_invalid_maven_wildcard_version":
            return "POM_VERSION_PIN_EXACT"
        raise ValueError(f"Unsupported patch candidate materialization strategy {record.materialization_strategy!r}")

    @staticmethod
    def _apply_run_dir(sandbox_path: Path, patch_candidate_id: str) -> Path:
        return sandbox_path.parent / ".migration-apply" / patch_candidate_id

    @staticmethod
    def _legacy_guard_path(sandbox_path: Path) -> Path:
        return sandbox_path.parent / "__legacy_guard__"

    @staticmethod
    def _artifact_refs_from_run_dir(run_dir: Path) -> dict[str, str]:
        ledger_path = run_dir / "repairs" / "repair_ledger.json"
        if not ledger_path.is_file():
            return {}
        try:
            payload = json.loads(ledger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"repair_ledger": str(ledger_path)}
        artifact_refs = payload.get("artifact_refs")
        if isinstance(artifact_refs, dict):
            cleaned = {str(k): str(v) for k, v in artifact_refs.items() if str(v)}
            cleaned.setdefault("repair_ledger", str(ledger_path))
            return cleaned
        return {"repair_ledger": str(ledger_path)}

    @staticmethod
    def _validation_status_from_result_summary(summary: str) -> str:
        lowered = str(summary or "").lower()
        if "validation passed" in lowered:
            return "passed"
        if "rolled back" in lowered:
            return "failed"
        if "rejected in sandbox" in lowered:
            return "not_run"
        if "blocked repair proposal" in lowered:
            return "not_run"
        return "unknown"

    def _persist_apply_result(
        self,
        *,
        patch_candidate_id: str,
        status: str,
        gate_status: str,
        gate_reason: str,
        result_summary: str,
        validation_status: str,
        rollback_status: str,
        artifact_refs: dict[str, str],
        applied_action_id: str,
        operator_note: str,
    ) -> None:
        self._repair_repo.update_patch_candidate_apply_result(
            patch_candidate_id=patch_candidate_id,
            status=status,
            gate_status=gate_status,
            gate_reason=gate_reason,
            result_summary=result_summary,
            validation_status=validation_status,
            rollback_status=rollback_status,
            artifact_refs_json=json.dumps(artifact_refs, sort_keys=True, separators=(",", ":")),
            applied_action_id=applied_action_id,
            operator_note=operator_note,
        )
