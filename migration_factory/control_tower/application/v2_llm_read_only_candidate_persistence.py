"""WF-04A read-only LLM repair candidate persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from migration_factory.control_tower.application.safe_diff_preview import build_safe_diff_preview
from migration_factory.control_tower.application.v2_repair_route_decision import (
    ROUTE_LLM_REVIEWED_UNKNOWN,
    RepairRouteDecision,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, sha256_hex, utc_now_text
from migration_factory.control_tower.infrastructure.sqlite.v2_repair_repository import V2RepairProposalRecord
from migration_factory.repair_loop.failure_evidence import FailureEvidence
from migration_factory.repair_loop.patch_gate import (
    PATCH_SOURCE_LLM_REVIEWED,
    POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
    REASON_REVIEW_CHAIN_INVALID,
    REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,
    REASON_REVIEWER_DECISION_NOT_ACCEPTED,
    REVIEWED_LLM_DECISION_ALLOWED,
    blocked_reviewed_llm_policy_result,
    evaluate_reviewed_llm_patch,
    reviewed_llm_allowed_route_scope,
    reviewed_llm_policy_payload,
    reviewed_llm_policy_checksum_input,
)
from migration_factory.repair_loop.repair_context import RepairContextPack


EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED = "llm_read_only_candidate_persisted"
EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED = "llm_read_only_candidate_blocked"
EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED = "llm_reviewed_patch_policy_evaluated"

STATUS_PERSISTED = "persisted"
STATUS_IDEMPOTENT = "idempotent"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED = "skipped"

REASON_PERSISTED = "llm_read_only_candidate_persisted"
REASON_IDEMPOTENT = "llm_read_only_candidate_already_persisted"
REASON_WF03_ONLY = "wf03_only_no_candidate_dependencies"
REASON_CONFIGURATION_INCOMPLETE = "llm_candidate_persistence_configuration_incomplete"
REASON_CONFIGURATION_MISMATCH = "llm_candidate_persistence_connection_mismatch"
REASON_NOT_ELIGIBLE = "llm_candidate_not_eligible"
REASON_INVALID_CHAIN = "llm_candidate_invalid_review_chain"
REASON_DIFF_REF_INVALID = "reviewed_diff_ref_invalid"
REASON_DIFF_OUTSIDE_OUTPUT_DIR = "reviewed_diff_ref_outside_output_dir"
REASON_DIFF_FILE_MISSING = "reviewed_diff_file_missing"
REASON_DIFF_CHECKSUM_MISMATCH = "reviewed_diff_checksum_mismatch"
REASON_PRIMARY_OUTPUT_ARTIFACT_INVALID = "primary_output_artifact_invalid"
REASON_FINAL_ARTIFACT_INVALID = "final_artifact_invalid"
REASON_POLICY_REJECTED = "reviewed_llm_patch_policy_rejected"
REASON_ID_COLLISION = "llm_candidate_checksum_collision"
REASON_REPOSITORY_WRITE_FAILED = "llm_candidate_repository_write_failed"

_SAFE_EVENT_KEYS = (
    "job_id",
    "stage_index",
    "command_id",
    "source_proposal_id",
    "source_gate_id",
    "llm_candidate_proposal_id",
    "llm_repair_candidate_id",
    "candidate_checksum",
    "review_chain_identity_checksum",
    "raw_reviewed_diff_checksum",
    "status",
    "reason",
    "policy_checksum",
    "decision",
    "reason_codes",
)


@dataclass(frozen=True, slots=True)
class LlmReadOnlyCandidatePersistenceResult:
    status: str
    reason: str
    job_id: str
    stage_index: int
    command_id: str
    llm_candidate_proposal_id: str = ""
    llm_repair_candidate_id: str = ""
    candidate_checksum: str = ""
    review_chain_identity_checksum: str = ""
    raw_reviewed_diff_checksum: str = ""
    source_proposal_id: str | None = None
    source_gate_id: str | None = None

    @property
    def persisted(self) -> bool:
        return self.status in {STATUS_PERSISTED, STATUS_IDEMPOTENT}


class LlmReadOnlyCandidatePersistenceService:
    def __init__(self, *, repair_repo: Any | None, candidate_repo: Any | None, event_repo: Any | None = None) -> None:
        self._repair_repo = repair_repo
        self._candidate_repo = candidate_repo
        self._event_repo = event_repo

    def persist(
        self,
        *,
        decision: RepairRouteDecision,
        failure_evidence: FailureEvidence,
        context_pack: RepairContextPack,
        chain_result: dict[str, Any],
        output_dir: str | Path,
        sandbox_path: str | Path | None,
        run_dir: str | Path | None,
        legacy_path: str | Path | None,
        source_proposal_id: str | None = None,
        source_gate_id: str | None = None,
    ) -> LlmReadOnlyCandidatePersistenceResult:
        base = {
            "job_id": str(failure_evidence.job_id),
            "stage_index": int(failure_evidence.stage_index),
            "command_id": str(failure_evidence.command_id),
            "source_proposal_id": source_proposal_id,
            "source_gate_id": source_gate_id,
        }
        if self._repair_repo is None or self._candidate_repo is None or self._event_repo is None:
            return LlmReadOnlyCandidatePersistenceResult(status=STATUS_BLOCKED, reason=REASON_CONFIGURATION_INCOMPLETE, **base)

        connection = _shared_connection(self._repair_repo, self._candidate_repo, self._event_repo)
        if connection is None:
            return LlmReadOnlyCandidatePersistenceResult(status=STATUS_BLOCKED, reason=REASON_CONFIGURATION_MISMATCH, **base)

        prepared = self._prepare(
            decision=decision,
            failure_evidence=failure_evidence,
            context_pack=context_pack,
            chain_result=chain_result,
            output_dir=Path(output_dir),
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            source_proposal_id=source_proposal_id,
            source_gate_id=source_gate_id,
        )
        if not isinstance(prepared, dict):
            return LlmReadOnlyCandidatePersistenceResult(status=STATUS_BLOCKED, reason=str(prepared), **base)

        transaction = _SqliteAtomicBoundary(connection)
        try:
            with transaction:
                if prepared["policy_result"].decision == REVIEWED_LLM_DECISION_ALLOWED:
                    existing = self._existing_result(prepared)
                    if existing is not None:
                        return existing
                self._write_policy_event(prepared)
                if prepared["policy_result"].decision != REVIEWED_LLM_DECISION_ALLOWED:
                    return LlmReadOnlyCandidatePersistenceResult(
                        status=STATUS_BLOCKED,
                        reason=REASON_POLICY_REJECTED,
                        llm_candidate_proposal_id=prepared.get("llm_candidate_proposal_id", ""),
                        llm_repair_candidate_id=prepared.get("llm_repair_candidate_id", ""),
                        candidate_checksum=prepared.get("candidate_checksum", ""),
                        review_chain_identity_checksum=prepared.get("review_chain_identity_checksum", ""),
                        raw_reviewed_diff_checksum=prepared.get("raw_reviewed_diff_checksum", ""),
                        **base,
                    )
                self._repair_repo.save_proposal(prepared["proposal_record"])
                self._candidate_repo.save_candidate(prepared["candidate"])
                self._write_persisted_event(prepared)
                verified = self._existing_result(prepared)
                if verified is None or not verified.persisted:
                    raise RuntimeError("llm_candidate_verification_failed")
        except Exception:
            return LlmReadOnlyCandidatePersistenceResult(status=STATUS_BLOCKED, reason=REASON_REPOSITORY_WRITE_FAILED, **base)

        return LlmReadOnlyCandidatePersistenceResult(
            status=STATUS_PERSISTED,
            reason=REASON_PERSISTED,
            llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            llm_repair_candidate_id=prepared["llm_repair_candidate_id"],
            candidate_checksum=prepared["candidate_checksum"],
            review_chain_identity_checksum=prepared["review_chain_identity_checksum"],
            raw_reviewed_diff_checksum=prepared["raw_reviewed_diff_checksum"],
            **base,
        )

    def _prepare(
        self,
        *,
        decision: RepairRouteDecision,
        failure_evidence: FailureEvidence,
        context_pack: RepairContextPack,
        chain_result: dict[str, Any],
        output_dir: Path,
        sandbox_path: str | Path | None,
        run_dir: str | Path | None,
        legacy_path: str | Path | None,
        source_proposal_id: str | None,
        source_gate_id: str | None,
    ) -> dict[str, Any] | str:
        if decision.route != ROUTE_LLM_REVIEWED_UNKNOWN or decision.deterministic_rule_id is not None:
            return REASON_NOT_ELIGIBLE
        allowed_route_scope = reviewed_llm_allowed_route_scope(route=decision.route, stage_index=failure_evidence.stage_index)
        chain = chain_result.get("review_chain") if isinstance(chain_result, dict) else None
        review_chain_identity_checksum = _review_chain_identity_checksum(chain) if isinstance(chain, dict) else ""
        policy_identity = {
            "failure_evidence_checksum": failure_evidence.content_checksum,
            "context_checksum": context_pack.context_pack_checksum,
            "base_repo_state_checksum": context_pack.base_repo_state_checksum,
            "reviewer_output_checksum": str(chain.get("reviewer_output_checksum") or "") if isinstance(chain, dict) else "",
            "review_chain_identity_checksum": review_chain_identity_checksum,
            "job_id": failure_evidence.job_id,
            "stage_index": failure_evidence.stage_index,
            "command_id": failure_evidence.command_id,
            "route": decision.route,
            "evidence_changed_files": tuple(context_pack.changed_files),
            "allowed_route_scope": allowed_route_scope,
        }
        if not isinstance(chain, dict):
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=REASON_REVIEW_CHAIN_INVALID,
                detail=REASON_INVALID_CHAIN,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum="",
                review_chain_identity_checksum=review_chain_identity_checksum,
            )
        chain_block = _chain_block_reason(decision, failure_evidence, context_pack, chain)
        if chain_block:
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=chain_block,
                detail=chain_block,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum="",
                review_chain_identity_checksum=review_chain_identity_checksum,
            )

        diff_ref = _producer_final_diff_ref(chain_result)
        diff_path, diff_error = _contained_file(Path(output_dir), diff_ref)
        if diff_path is None:
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=diff_error,
                detail=diff_error,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum="",
                review_chain_identity_checksum=review_chain_identity_checksum,
            )
        diff_bytes = diff_path.read_bytes()
        raw_diff_checksum = _sha256_prefixed(diff_bytes)
        if (
            raw_diff_checksum != _sha256_prefixed_text(chain.get("raw_diff_bytes_checksum"))
            or raw_diff_checksum != _sha256_prefixed_text(chain.get("final_reviewed_diff_checksum"))
            or raw_diff_checksum != _sha256_prefixed_text(chain.get("proposed_diff_checksum"))
        ):
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=REASON_REVIEWED_DIFF_CHECKSUM_MISMATCH,
                detail=REASON_DIFF_CHECKSUM_MISMATCH,
                reviewed_diff_checksum=raw_diff_checksum,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum=raw_diff_checksum,
                review_chain_identity_checksum=review_chain_identity_checksum,
            )

        primary_output, primary_error = _load_json_ref(
            output_dir=Path(output_dir),
            value=chain.get("primary_output_ref"),
            expected_checksum=chain.get("primary_output_artifact_checksum"),
        )
        if primary_error:
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=REASON_PRIMARY_OUTPUT_ARTIFACT_INVALID,
                detail=primary_error,
                reviewed_diff_checksum=raw_diff_checksum,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum=raw_diff_checksum,
                review_chain_identity_checksum=review_chain_identity_checksum,
            )
        final_artifact, final_error = _load_json_ref(
            output_dir=Path(output_dir),
            value=chain.get("final_artifact_ref"),
            expected_checksum=chain.get("final_artifact_persisted_checksum"),
        )
        if final_error:
            policy_result = blocked_reviewed_llm_policy_result(
                reason_code=REASON_FINAL_ARTIFACT_INVALID,
                detail=final_error,
                reviewed_diff_checksum=raw_diff_checksum,
                **policy_identity,
            )
            return _policy_block_prepared(
                policy_result=policy_result,
                raw_reviewed_diff_checksum=raw_diff_checksum,
                review_chain_identity_checksum=review_chain_identity_checksum,
            )
        declared_changed_files = _declared_changed_files(primary_output, final_artifact)
        policy_result = evaluate_reviewed_llm_patch(
            reviewed_diff_bytes=diff_bytes,
            reviewed_diff_path=diff_path,
            reviewed_diff_checksum=raw_diff_checksum,
            sandbox_path=sandbox_path,
            run_dir=run_dir,
            legacy_path=legacy_path,
            declared_changed_files=declared_changed_files,
            **policy_identity,
        )
        policy_checksum = "sha256:" + sha256_canonical_json(reviewed_llm_policy_checksum_input(policy_result))
        policy_payload = reviewed_llm_policy_payload(
            policy_result,
            policy_checksum=policy_checksum,
            evaluated_at=utc_now_text(),
        )
        policy_validation_checksum = policy_checksum
        if policy_result.decision != REVIEWED_LLM_DECISION_ALLOWED:
            return _policy_block_prepared(
                policy_result=policy_result,
                policy_payload=policy_payload,
                raw_reviewed_diff_checksum=raw_diff_checksum,
                review_chain_identity_checksum=review_chain_identity_checksum,
            )

        bindings = {
            "failure_evidence_checksum": failure_evidence.content_checksum,
            "context_checksum": context_pack.context_pack_checksum,
            "base_repo_state_checksum": context_pack.base_repo_state_checksum,
            "primary_output_checksum": str(chain.get("primary_output_checksum") or ""),
            "primary_output_artifact_checksum": str(chain.get("primary_output_artifact_checksum") or ""),
            "reviewer_output_checksum": str(chain.get("reviewer_output_checksum") or ""),
            "raw_reviewed_diff_checksum": raw_diff_checksum,
            "final_artifact_checksum": str(chain.get("final_artifact_checksum") or ""),
            "final_artifact_persisted_checksum": str(chain.get("final_artifact_persisted_checksum") or ""),
            "attempt_number": context_pack.cycle_number,
            "review_chain_identity_checksum": review_chain_identity_checksum,
        }
        identity_payload = {
            "job_id": failure_evidence.job_id,
            "stage_index": failure_evidence.stage_index,
            "command_id": failure_evidence.command_id,
            **bindings,
        }
        llm_candidate_proposal_id = "llm-candidate-proposal-" + sha256_canonical_json(identity_payload)[:20]
        llm_repair_candidate_id = "llm-repair-candidate-" + sha256_canonical_json(
            {**identity_payload, "llm_candidate_proposal_id": llm_candidate_proposal_id}
        )[:20]
        candidate_checksum = "sha256:" + sha256_canonical_json(
            {
                "candidate_kind": "llm_unknown_family",
                "patch_source": PATCH_SOURCE_LLM_REVIEWED,
                "policy_id": POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
                "policy_validation_checksum": policy_validation_checksum,
                "llm_candidate_proposal_id": llm_candidate_proposal_id,
                **identity_payload,
            }
        )
        preview = build_safe_diff_preview(
            proposal_id=llm_candidate_proposal_id,
            diff_ref=str(diff_path),
            stored_diff_checksum=raw_diff_checksum.removeprefix("sha256:"),
        )
        touched = tuple(file.path for file in preview.files)
        pre_apply_file_checksums = _sandbox_file_checksums(Path(sandbox_path), touched) if sandbox_path is not None else {}
        now = utc_now_text()
        metadata = {
            "candidate_kind": "llm_unknown_family",
            "patch_source": PATCH_SOURCE_LLM_REVIEWED,
            "policy_id": POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
            "policy_validation": policy_payload,
            "policy_validation_checksum": policy_validation_checksum,
            "llm_candidate_proposal_id": llm_candidate_proposal_id,
            "llm_repair_candidate_id": llm_repair_candidate_id,
            "candidate_checksum": candidate_checksum,
            "source_proposal_id": source_proposal_id,
            "source_gate_id": source_gate_id,
            "proposal_kind": "llm_repair_review",
            "reviewer_decision": "accept",
            **bindings,
        }
        candidate = {
            "job_id": failure_evidence.job_id,
            "stage_index": failure_evidence.stage_index,
            "command_id": failure_evidence.command_id,
            "repair_candidate_id": llm_repair_candidate_id,
            "candidate_kind": "llm_unknown_family",
            "status": "read_only",
            "family": "llm_unknown_family",
            "patch_source": PATCH_SOURCE_LLM_REVIEWED,
            "policy_id": POLICY_ID_GENERIC_REVIEWED_LLM_PATCH_V1,
            "policy_validation_checksum": policy_validation_checksum,
            "target_file": ",".join(touched),
            "pre_apply_checksum": "",
            "target_file_checksum": context_pack.base_repo_state_checksum,
            "patch_checksum": raw_diff_checksum,
            "review_checksum": str(chain.get("reviewer_output_checksum") or ""),
            "proposal_checksum": review_chain_identity_checksum,
            "candidate_checksum": candidate_checksum,
            **bindings,
            "approval_required": False,
            "approval_enabled": False,
            "apply_enabled": False,
            "repair_enabled": False,
            "sandbox_only": True,
            "legacy_mutation_allowed": False,
            "downstream_start_allowed": False,
            "llm_can_apply": False,
            "browser_can_supply_patch": False,
            "verification_status": "not_started",
            "rollback_status": "not_started",
            "proof_artifact": "",
            "created_at": now,
            "_llm_candidate_metadata": metadata,
            "_reviewed_diff_ref": str(diff_path),
            "_review_chain_output_dir": str(Path(output_dir).resolve()),
            "_sandbox_root": str(Path(sandbox_path).resolve()) if sandbox_path is not None else "",
            "_run_dir": str(Path(run_dir).resolve()) if run_dir is not None else "",
            "_legacy_path": str(Path(legacy_path).resolve()) if legacy_path is not None else "",
            "_allowed_route_scope": list(allowed_route_scope),
            "_declared_changed_files": list(declared_changed_files),
            "_evidence_changed_files": list(context_pack.changed_files),
            "_pre_apply_file_checksums": pre_apply_file_checksums,
        }
        return {
            "llm_candidate_proposal_id": llm_candidate_proposal_id,
            "llm_repair_candidate_id": llm_repair_candidate_id,
            "candidate_checksum": candidate_checksum,
            "review_chain_identity_checksum": review_chain_identity_checksum,
            "raw_reviewed_diff_checksum": raw_diff_checksum,
            "policy_result": policy_result,
            "policy_payload": policy_payload,
            "policy_validation_checksum": policy_validation_checksum,
            "candidate": candidate,
            "proposal_record": V2RepairProposalRecord(
                proposal_id=llm_candidate_proposal_id,
                command_id=failure_evidence.command_id,
                failure_summary=failure_evidence.failure_summary,
                hypothesis=str(chain.get("root_cause") or "LLM-reviewed unknown-family repair candidate"),
                patch_summary=str(chain.get("fix_strategy") or "Read-only LLM-reviewed candidate"),
                affected_paths_json=json.dumps(list(touched), separators=(",", ":")),
                status="llm_candidate_read_only",
                approval_checksum=None,
                created_at=now,
                proposal_checksum=candidate_checksum,
                source_proposal_id=source_proposal_id,
                context_pack_checksum=context_pack.context_pack_checksum,
                allowed_scope="sandbox_only",
                patch_package_json=json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                job_id=failure_evidence.job_id,
                route_step_index=failure_evidence.stage_index,
                attempt_number=context_pack.cycle_number,
                diff_ref=str(diff_path),
                diff_checksum=raw_diff_checksum.removeprefix("sha256:"),
                reviewer_output_checksum=str(chain.get("reviewer_output_checksum") or ""),
                policy_validation_checksum=policy_validation_checksum,
                gate_id=None,
                status_reason="llm_unknown_family_read_only",
                apply_status="disabled",
                rerun_status="disabled",
                rollback_status="not_started",
                remaining_attempts=0,
                reviewer_decision="accept",
            ),
        }

    def _existing_result(self, prepared: dict[str, Any]) -> LlmReadOnlyCandidatePersistenceResult | None:
        candidate = prepared["candidate"]
        preexisting_candidate = self._candidate_repo.get_internal(
            candidate["job_id"],
            int(candidate["stage_index"]),
            prepared["llm_repair_candidate_id"],
        )
        if isinstance(preexisting_candidate, dict) and preexisting_candidate.get("candidate_checksum") != prepared["candidate_checksum"]:
            return LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_BLOCKED,
                reason=REASON_ID_COLLISION,
                job_id=candidate["job_id"],
                stage_index=int(candidate["stage_index"]),
                command_id=str(candidate.get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            )
        proposal = self._repair_repo.get_proposal(prepared["llm_candidate_proposal_id"])
        if proposal is None and isinstance(preexisting_candidate, dict):
            return LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_BLOCKED,
                reason=REASON_ID_COLLISION,
                job_id=candidate["job_id"],
                stage_index=int(candidate["stage_index"]),
                command_id=str(candidate.get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
                llm_repair_candidate_id=prepared["llm_repair_candidate_id"],
                candidate_checksum=prepared["candidate_checksum"],
            )
        if proposal is None:
            return None
        try:
            metadata = json.loads(proposal.patch_package_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata = {}
        if metadata.get("candidate_checksum") != prepared["candidate_checksum"]:
            return LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_BLOCKED,
                reason=REASON_ID_COLLISION,
                job_id=prepared["candidate"]["job_id"],
                stage_index=int(prepared["candidate"]["stage_index"]),
                command_id=str(prepared["candidate"].get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            )
        existing_candidate = preexisting_candidate
        if not isinstance(existing_candidate, dict):
            return LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_BLOCKED,
                reason=REASON_ID_COLLISION,
                job_id=prepared["candidate"]["job_id"],
                stage_index=int(prepared["candidate"]["stage_index"]),
                command_id=str(prepared["candidate"].get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            )
        if existing_candidate.get("candidate_checksum") != prepared["candidate_checksum"]:
            return LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_BLOCKED,
                reason=REASON_ID_COLLISION,
                job_id=prepared["candidate"]["job_id"],
                stage_index=int(prepared["candidate"]["stage_index"]),
                command_id=str(prepared["candidate"].get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            )
        return LlmReadOnlyCandidatePersistenceResult(
            status=STATUS_IDEMPOTENT,
            reason=REASON_IDEMPOTENT,
            job_id=prepared["candidate"]["job_id"],
            stage_index=int(prepared["candidate"]["stage_index"]),
            command_id=str(proposal.command_id),
            llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
            llm_repair_candidate_id=prepared["llm_repair_candidate_id"],
            candidate_checksum=prepared["candidate_checksum"],
            review_chain_identity_checksum=prepared["review_chain_identity_checksum"],
            raw_reviewed_diff_checksum=prepared["raw_reviewed_diff_checksum"],
            source_proposal_id=metadata.get("source_proposal_id"),
            source_gate_id=metadata.get("source_gate_id"),
        )

    def _write_persisted_event(self, prepared: dict[str, Any]) -> None:
        payload = _safe_event_payload(
            LlmReadOnlyCandidatePersistenceResult(
                status=STATUS_PERSISTED,
                reason=REASON_PERSISTED,
                job_id=prepared["candidate"]["job_id"],
                stage_index=int(prepared["candidate"]["stage_index"]),
                command_id=str(prepared["candidate"].get("command_id") or ""),
                llm_candidate_proposal_id=prepared["llm_candidate_proposal_id"],
                llm_repair_candidate_id=prepared["llm_repair_candidate_id"],
                candidate_checksum=prepared["candidate_checksum"],
                review_chain_identity_checksum=prepared["review_chain_identity_checksum"],
                raw_reviewed_diff_checksum=prepared["raw_reviewed_diff_checksum"],
                source_proposal_id=prepared["candidate"]["_llm_candidate_metadata"].get("source_proposal_id"),
                source_gate_id=prepared["candidate"]["_llm_candidate_metadata"].get("source_gate_id"),
            )
        )
        self._event_repo.save(
            job_id=payload["job_id"],
            stage=int(payload["stage_index"]),
            event_type=EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED,
            status="completed",
            message="Read-only LLM repair candidate persistence recorded.",
            payload=payload,
        )

    def _write_policy_event(self, prepared: dict[str, Any]) -> None:
        policy_payload = prepared["policy_payload"]
        self._event_repo.save(
            job_id=str(policy_payload["job_id"]),
            stage=int(policy_payload["stage_index"]),
            event_type=EVENT_LLM_REVIEWED_PATCH_POLICY_EVALUATED,
            status="completed" if policy_payload["decision"] == REVIEWED_LLM_DECISION_ALLOWED else "blocked",
            message="Reviewed LLM patch policy decision recorded.",
            payload=policy_payload,
        )


def emit_llm_read_only_candidate_event(
    *,
    event_sink: Callable[..., None] | None,
    result: LlmReadOnlyCandidatePersistenceResult,
) -> None:
    if event_sink is None or result.status in {STATUS_SKIPPED, STATUS_IDEMPOTENT, STATUS_PERSISTED}:
        return
    event_type = EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED if result.persisted else EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED
    payload = _safe_event_payload(result)
    event_sink(
        job_id=result.job_id,
        stage=result.stage_index,
        event_type=event_type,
        status="completed" if result.persisted else "blocked",
        message="Read-only LLM repair candidate persistence recorded.",
        payload=payload,
    )


def _safe_event_payload(result: LlmReadOnlyCandidatePersistenceResult) -> dict[str, Any]:
    payload = {
        "job_id": result.job_id,
        "stage_index": result.stage_index,
        "command_id": result.command_id,
        "source_proposal_id": result.source_proposal_id,
        "source_gate_id": result.source_gate_id,
        "llm_candidate_proposal_id": result.llm_candidate_proposal_id,
        "llm_repair_candidate_id": result.llm_repair_candidate_id,
        "candidate_checksum": result.candidate_checksum,
        "review_chain_identity_checksum": result.review_chain_identity_checksum,
        "raw_reviewed_diff_checksum": result.raw_reviewed_diff_checksum,
        "status": result.status,
        "reason": result.reason,
    }
    return {key: value for key, value in payload.items() if key in _SAFE_EVENT_KEYS and value not in ("", None)}


def _chain_block_reason(
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    chain: dict[str, Any],
) -> str:
    if decision.route != ROUTE_LLM_REVIEWED_UNKNOWN:
        return REASON_REVIEW_CHAIN_INVALID
    if chain.get("reviewer_decision") != "accept":
        return REASON_REVIEWER_DECISION_NOT_ACCEPTED
    required = (
        "primary_output_checksum",
        "reviewer_output_checksum",
        "proposed_diff_checksum",
        "raw_diff_bytes_checksum",
        "final_reviewed_diff_checksum",
        "final_artifact_checksum",
    )
    if any(not str(chain.get(key) or "") for key in required):
        return REASON_REVIEW_CHAIN_INVALID
    valid = (
        chain.get("proposal_kind") == "llm_repair_review"
        and chain.get("context_pack_checksum") == context_pack.context_pack_checksum
        and chain.get("job_id") == context_pack.job_id == failure_evidence.job_id
        and chain.get("stage_index") == context_pack.stage_index == failure_evidence.stage_index
        and chain.get("primary_deterministic_fallback_used") is False
        and chain.get("reviewer_deterministic_fallback_used") is False
    )
    return "" if valid else REASON_REVIEW_CHAIN_INVALID


def _producer_final_diff_ref(chain_result: dict[str, Any]) -> str:
    chain = chain_result.get("review_chain") if isinstance(chain_result, dict) else {}
    artifact_refs = chain_result.get("artifact_refs") if isinstance(chain_result, dict) else {}
    final_diff_ref = str(chain.get("final_diff_ref") or "") if isinstance(chain, dict) else ""
    if not final_diff_ref:
        return ""
    if isinstance(artifact_refs, dict) and artifact_refs.get("final_reviewed_diff") not in (None, final_diff_ref):
        return ""
    if isinstance(chain, dict) and isinstance(chain.get("artifact_refs"), dict):
        if chain["artifact_refs"].get("final_reviewed_diff") not in (None, final_diff_ref):
            return ""
    return final_diff_ref


def _contained_file(output_dir: Path, diff_ref: str) -> tuple[Path | None, str]:
    if not diff_ref:
        return None, REASON_DIFF_REF_INVALID
    try:
        root = output_dir.resolve(strict=True)
        raw_path = Path(diff_ref)
        path = raw_path.resolve(strict=False)
    except OSError:
        return None, REASON_DIFF_REF_INVALID
    try:
        path.relative_to(root)
    except ValueError:
        return None, REASON_DIFF_OUTSIDE_OUTPUT_DIR
    if not path.exists():
        return None, REASON_DIFF_FILE_MISSING
    if not path.is_file():
        return None, REASON_DIFF_REF_INVALID
    return path.resolve(strict=True), ""


def _load_json_ref(*, output_dir: Path, value: Any, expected_checksum: Any) -> tuple[dict[str, Any], str]:
    ref = str(value or "")
    if not ref:
        return {}, "missing_json_ref"
    if not str(expected_checksum or "").strip():
        return {}, "json_artifact_checksum_missing"
    try:
        path, error = _contained_json_file(output_dir, ref)
        if error:
            return {}, error
        raw = path.read_bytes()
        actual_checksum = _sha256_prefixed(raw)
        if actual_checksum != _sha256_prefixed_text(expected_checksum):
            return {}, "json_artifact_checksum_mismatch"
        text = raw.decode("utf-8")
        loaded = json.loads(text)
    except UnicodeDecodeError:
        return {}, "invalid_json_encoding"
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}, "invalid_json_artifact"
    return (loaded, "") if isinstance(loaded, dict) else ({}, "invalid_json_artifact")


def _contained_json_file(output_dir: Path, ref: str) -> tuple[Path, str]:
    path, error = _contained_file(output_dir, ref)
    if error:
        return Path(), error
    if path.suffix.lower() != ".json":
        return Path(), "json_artifact_ref_invalid"
    return path, ""


def _declared_changed_files(primary_output: dict[str, Any], final_artifact: dict[str, Any]) -> tuple[str, ...]:
    for source in (final_artifact, primary_output):
        changed = source.get("changed_files") if isinstance(source, dict) else None
        if isinstance(changed, list):
            return tuple(str(path).replace("\\", "/") for path in changed if str(path).strip())
    return ()


def _sandbox_file_checksums(sandbox_path: Path, paths: tuple[str, ...]) -> dict[str, str]:
    sandbox = sandbox_path.resolve()
    checksums: dict[str, str] = {}
    for rel in paths:
        normalized = str(rel).replace("\\", "/")
        target = (sandbox / normalized).resolve()
        try:
            target.relative_to(sandbox)
        except ValueError:
            checksums[normalized] = ""
            continue
        checksums[normalized] = "sha256:" + sha256_hex(target.read_bytes()) if target.is_file() else ""
    return checksums


def _policy_block_prepared(
    *,
    policy_result: Any,
    raw_reviewed_diff_checksum: str,
    review_chain_identity_checksum: str,
    policy_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy_checksum = "sha256:" + sha256_canonical_json(reviewed_llm_policy_checksum_input(policy_result))
    payload = policy_payload or reviewed_llm_policy_payload(
        policy_result,
        policy_checksum=policy_checksum,
        evaluated_at=utc_now_text(),
    )
    return {
        "policy_result": policy_result,
        "policy_payload": payload,
        "policy_validation_checksum": policy_checksum,
        "raw_reviewed_diff_checksum": raw_reviewed_diff_checksum,
        "review_chain_identity_checksum": review_chain_identity_checksum,
    }


def _review_chain_identity_checksum(chain: dict[str, Any]) -> str:
    identity = {
        key: chain.get(key)
        for key in (
            "job_id",
            "stage_index",
            "proposal_kind",
            "reviewer_decision",
            "context_pack_checksum",
            "primary_output_checksum",
            "primary_output_artifact_checksum",
            "reviewer_output_checksum",
            "raw_diff_bytes_checksum",
            "final_reviewed_diff_checksum",
            "final_artifact_checksum",
            "final_artifact_persisted_checksum",
            "primary_deterministic_fallback_used",
            "reviewer_deterministic_fallback_used",
        )
    }
    return "sha256:" + sha256_canonical_json(identity)


def _sha256_prefixed(data: bytes) -> str:
    return "sha256:" + sha256_hex(data)


def _sha256_prefixed_text(value: Any) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        return text
    return f"sha256:{text}" if text else ""


def _shared_connection(repair_repo: Any, candidate_repo: Any, event_repo: Any | None = None) -> sqlite3.Connection | None:
    repair_conn = getattr(repair_repo, "_connection", None)
    candidate_conn = getattr(candidate_repo, "_connection", None)
    event_conn = getattr(event_repo, "_connection", None) if event_repo is not None else repair_conn
    if repair_conn is not None and repair_conn is candidate_conn and repair_conn is event_conn:
        return repair_conn
    return None


class _SqliteAtomicBoundary:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self._savepoint = f"llm_candidate_{id(self):x}"
        self._outer = False

    def __enter__(self) -> None:
        self._outer = self._connection.in_transaction
        if self._outer:
            self._connection.execute(f"SAVEPOINT {self._savepoint}")
        else:
            self._connection.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        if self._outer:
            if exc_type is None:
                self._connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
            else:
                self._connection.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint}")
                self._connection.execute(f"RELEASE SAVEPOINT {self._savepoint}")
        elif exc_type is None:
            self._connection.execute("COMMIT")
        else:
            self._connection.execute("ROLLBACK")
        return None
