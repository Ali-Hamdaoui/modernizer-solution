"""Materialize approved repair proposals into preview-only patch candidates."""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_repair_flow import (
    RepairProposal,
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_reviewer_service import (
    V2ReviewerService,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_command_repository import (
    SqliteV2CommandRepository,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import (
    SqliteV2RepairRepository,
    V2PatchCandidateRecord,
)
from migration_factory.repair_loop.patch_gate import evaluate_patch_proposal


_WILDCARD_VERSION_RE = re.compile(r"<version>\s*([0-9]+(?:\.[0-9]+)*)\.x\s*</version>")


@dataclass(frozen=True)
class PatchCandidate:
    patch_candidate_id: str
    proposal_id: str
    proposal_checksum: str
    diagnosis_id: str
    diagnosis_checksum: str
    evidence_pack_checksum: str
    context_pack_checksum: str
    unified_diff: str
    patch_candidate_checksum: str
    materialization_strategy: str
    status: str
    gate_status: str
    gate_reason: str
    touched_paths: tuple[str, ...]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["touched_paths"] = list(self.touched_paths)
        return payload


class V2PatchCandidateService:
    def __init__(
        self,
        *,
        repair_repo: SqliteV2RepairRepository,
        reviewer_service: V2ReviewerService,
        command_repo: SqliteV2CommandRepository,
    ) -> None:
        self._repair_repo = repair_repo
        self._reviewer = reviewer_service
        self._command_repo = command_repo

    def create_patch_candidate(
        self,
        *,
        proposal_id: str,
        materialization_mode: str = "deterministic_only",
    ) -> PatchCandidate:
        proposal = self._load_proposal(proposal_id)
        if proposal.status != "approved":
            raise ValueError(f"Proposal {proposal_id!r} must be approved before materialization")
        self._require_bindings(proposal)
        approval = self._require_current_approval(proposal)
        self._require_current_reviewer_accept(proposal)

        sandbox_path = self._resolve_sandbox_path(proposal.command_id)
        materialized = self._materialize(proposal=proposal, sandbox_path=sandbox_path, mode=materialization_mode)

        if materialized["status"] == "unsupported_materialization":
            candidate = self._persist_candidate(
                proposal=proposal,
                unified_diff="",
                materialization_strategy=str(materialized["materialization_strategy"]),
                status="unsupported_materialization",
                gate_status="NOT_RUN",
                gate_reason=str(materialized["gate_reason"]),
                touched_paths=(),
            )
            return candidate

        unified_diff = str(materialized["unified_diff"])
        rule_id = str(materialized["deterministic_rule_id"])
        gate = evaluate_patch_proposal(
            proposal={
                "deterministic_rule_id": rule_id,
                "risk": "LOW",
                "requires_human_review": False,
                "description": proposal.patch_summary,
                "unified_diff": unified_diff,
                "expected_validation": [],
                "limitations": ["preview only", "no patch applied"],
            },
            sandbox_path=sandbox_path,
            run_dir=self._preview_run_dir(sandbox_path, proposal.proposal_id),
            legacy_path=self._preview_legacy_path(sandbox_path),
            failure_classification={"failure_type": proposal.failure_summary},
            h2_required=False,
        )
        candidate = self._persist_candidate(
            proposal=proposal,
            unified_diff=unified_diff,
            materialization_strategy=str(materialized["materialization_strategy"]),
            status="gate_allowed" if gate.status == "ALLOWED" else "gate_blocked",
            gate_status=gate.status,
            gate_reason=gate.reason,
            touched_paths=tuple(gate.touched_paths),
        )
        return candidate

    def candidate_to_dict(self, candidate: PatchCandidate) -> dict[str, Any]:
        return candidate.to_dict()

    @staticmethod
    def preview_unified_diff(candidate: PatchCandidate, limit: int = 1200) -> str:
        clean = redact_model_summary(candidate.unified_diff)
        if len(clean) <= limit:
            return clean
        return clean[:limit] + "...[truncated]"

    def _load_proposal(self, proposal_id: str) -> RepairProposal:
        record = self._repair_repo.get_proposal(proposal_id)
        if record is None:
            raise ValueError(f"Proposal {proposal_id!r} not found")
        return V2RepairFlowService.record_to_proposal(record)

    @staticmethod
    def _require_bindings(proposal: RepairProposal) -> None:
        missing = [
            name
            for name, value in (
                ("proposal_checksum", proposal.proposal_checksum),
                ("diagnosis_checksum", proposal.diagnosis_checksum),
                ("evidence_pack_checksum", proposal.evidence_pack_checksum),
                ("context_pack_checksum", proposal.context_pack_checksum or ""),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError(f"Proposal is missing required checksum bindings: {', '.join(missing)}")

    def _require_current_approval(self, proposal: RepairProposal):
        latest = self._repair_repo.get_latest_approval_decision(proposal.proposal_id)
        if latest is None:
            raise ValueError(f"Proposal {proposal.proposal_id!r} has no human approval decision")
        if latest.operator_decision != "approve":
            raise ValueError(
                f"Proposal {proposal.proposal_id!r} latest human approval decision is {latest.operator_decision}"
            )
        if latest.proposal_checksum != proposal.proposal_checksum:
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale approval checksum binding")
        if latest.context_pack_checksum != (proposal.context_pack_checksum or ""):
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale approval context binding")
        if latest.approval_checksum != proposal.proposal_checksum:
            raise ValueError(f"Proposal {proposal.proposal_id!r} has stale human approval checksum")
        return latest

    def _require_current_reviewer_accept(self, proposal: RepairProposal) -> None:
        latest = self._reviewer.list_critiques(proposal.proposal_id)
        for critique in latest:
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
            raise ValueError(f"Command {command_id!r} has no sandbox binding for patch preview")
        try:
            result = json.loads(command.result_json)
        except (json.JSONDecodeError, TypeError):
            raise ValueError(f"Command {command_id!r} result_json is invalid for patch preview") from None
        sandbox_path = str(result.get("sandbox_path") or "").strip()
        if not sandbox_path:
            raise ValueError(f"Command {command_id!r} has no sandbox_path for patch preview")
        return Path(sandbox_path).resolve()

    def _materialize(
        self,
        *,
        proposal: RepairProposal,
        sandbox_path: Path,
        mode: str,
    ) -> dict[str, str]:
        if mode != "deterministic_only":
            raise ValueError(f"Unsupported materialization_mode {mode!r}")
        pom_path = sandbox_path / "pom.xml"
        if (
            proposal.diagnosis_id
            and "invalid_maven_wildcard_version" in proposal.failure_summary
            and pom_path.is_file()
        ):
            original = pom_path.read_text(encoding="utf-8")
            replaced = _WILDCARD_VERSION_RE.sub(
                lambda match: f"<version>{match.group(1)}.0</version>",
                original,
                count=1,
            )
            if replaced != original:
                return {
                    "status": "candidate_created",
                    "materialization_strategy": "deterministic_invalid_maven_wildcard_version",
                    "deterministic_rule_id": "POM_VERSION_PIN_EXACT",
                    "unified_diff": self._build_git_diff("pom.xml", original, replaced),
                    "gate_reason": "",
                }
        return {
            "status": "unsupported_materialization",
            "materialization_strategy": "unsupported_materialization",
            "deterministic_rule_id": "",
            "unified_diff": "",
            "gate_reason": "No deterministic materializer exists for this approved proposal.",
        }

    def _persist_candidate(
        self,
        *,
        proposal: RepairProposal,
        unified_diff: str,
        materialization_strategy: str,
        status: str,
        gate_status: str,
        gate_reason: str,
        touched_paths: tuple[str, ...],
    ) -> PatchCandidate:
        created_at = utc_now_text()
        checksum = self.compute_patch_candidate_checksum(
            proposal=proposal,
            unified_diff=unified_diff,
            materialization_strategy=materialization_strategy,
            gate_status=gate_status,
            gate_reason=gate_reason,
            touched_paths=touched_paths,
        )
        candidate = PatchCandidate(
            patch_candidate_id=uuid4().hex,
            proposal_id=proposal.proposal_id,
            proposal_checksum=proposal.proposal_checksum,
            diagnosis_id=proposal.diagnosis_id,
            diagnosis_checksum=proposal.diagnosis_checksum,
            evidence_pack_checksum=proposal.evidence_pack_checksum,
            context_pack_checksum=proposal.context_pack_checksum or "",
            unified_diff=unified_diff,
            patch_candidate_checksum=checksum,
            materialization_strategy=materialization_strategy,
            status=status,
            gate_status=gate_status,
            gate_reason=gate_reason,
            touched_paths=touched_paths,
            created_at=created_at,
        )
        self._repair_repo.save_patch_candidate(
            V2PatchCandidateRecord(
                patch_candidate_id=candidate.patch_candidate_id,
                proposal_id=candidate.proposal_id,
                proposal_checksum=candidate.proposal_checksum,
                diagnosis_id=candidate.diagnosis_id,
                diagnosis_checksum=candidate.diagnosis_checksum,
                evidence_pack_checksum=candidate.evidence_pack_checksum,
                context_pack_checksum=candidate.context_pack_checksum,
                unified_diff=candidate.unified_diff,
                patch_candidate_checksum=candidate.patch_candidate_checksum,
                materialization_strategy=candidate.materialization_strategy,
                status=candidate.status,
                gate_status=candidate.gate_status,
                gate_reason=candidate.gate_reason,
                touched_paths_json=json.dumps(list(candidate.touched_paths), separators=(",", ":")),
                created_at=candidate.created_at,
                result_summary="",
                validation_status="",
                rollback_status="",
                artifact_refs_json="{}",
                applied_action_id="",
                operator_note="",
            )
        )
        return candidate

    @staticmethod
    def compute_patch_candidate_checksum(
        *,
        proposal: RepairProposal,
        unified_diff: str,
        materialization_strategy: str,
        gate_status: str,
        gate_reason: str,
        touched_paths: tuple[str, ...],
    ) -> str:
        return sha256_canonical_json(
            {
                "proposal_id": proposal.proposal_id,
                "proposal_checksum": proposal.proposal_checksum,
                "diagnosis_id": proposal.diagnosis_id,
                "diagnosis_checksum": proposal.diagnosis_checksum,
                "evidence_pack_checksum": proposal.evidence_pack_checksum,
                "context_pack_checksum": proposal.context_pack_checksum or "",
                "unified_diff": unified_diff,
                "materialization_strategy": materialization_strategy,
                "gate_status": gate_status,
                "gate_reason": gate_reason,
                "touched_paths": list(touched_paths),
            }
        )

    @staticmethod
    def _build_git_diff(path: str, original: str, updated: str) -> str:
        diff_lines = list(
            difflib.unified_diff(
                original.splitlines(),
                updated.splitlines(),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                lineterm="",
            )
        )
        return "\n".join([f"diff --git a/{path} b/{path}", *diff_lines]) + "\n"

    @staticmethod
    def _preview_run_dir(sandbox_path: Path, proposal_id: str) -> Path:
        return sandbox_path.parent / ".migration-preview" / proposal_id

    @staticmethod
    def _preview_legacy_path(sandbox_path: Path) -> Path:
        return sandbox_path.parent / "__legacy_preview_only__"
