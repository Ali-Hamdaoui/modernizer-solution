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
from migration_factory.repair_loop.repair_context import RepairContextPack


EVENT_LLM_READ_ONLY_CANDIDATE_PERSISTED = "llm_read_only_candidate_persisted"
EVENT_LLM_READ_ONLY_CANDIDATE_BLOCKED = "llm_read_only_candidate_blocked"

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
REASON_DIFF_CHECKSUM_MISMATCH = "reviewed_diff_checksum_mismatch"
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
            source_proposal_id=source_proposal_id,
            source_gate_id=source_gate_id,
        )
        if not isinstance(prepared, dict):
            return LlmReadOnlyCandidatePersistenceResult(status=STATUS_BLOCKED, reason=str(prepared), **base)

        transaction = _SqliteAtomicBoundary(connection)
        try:
            with transaction:
                existing = self._existing_result(prepared)
                if existing is not None:
                    return existing
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
        source_proposal_id: str | None,
        source_gate_id: str | None,
    ) -> dict[str, Any] | str:
        if decision.route != ROUTE_LLM_REVIEWED_UNKNOWN or decision.deterministic_rule_id is not None:
            return REASON_NOT_ELIGIBLE
        chain = chain_result.get("review_chain") if isinstance(chain_result, dict) else None
        if not isinstance(chain, dict) or not _chain_accepts(decision, failure_evidence, context_pack, chain):
            return REASON_INVALID_CHAIN

        diff_ref = _producer_final_diff_ref(chain_result)
        diff_path = _contained_file(Path(output_dir), diff_ref)
        if diff_path is None:
            return REASON_DIFF_REF_INVALID if not diff_ref else REASON_DIFF_OUTSIDE_OUTPUT_DIR
        diff_bytes = diff_path.read_bytes()
        raw_diff_checksum = _sha256_prefixed(diff_bytes)
        if raw_diff_checksum != _sha256_prefixed_text(chain.get("raw_diff_bytes_checksum")):
            return REASON_DIFF_CHECKSUM_MISMATCH
        if raw_diff_checksum != _sha256_prefixed_text(chain.get("final_reviewed_diff_checksum")):
            return REASON_DIFF_CHECKSUM_MISMATCH

        review_chain_identity_checksum = _review_chain_identity_checksum(chain)
        bindings = {
            "failure_evidence_checksum": failure_evidence.content_checksum,
            "context_checksum": context_pack.context_pack_checksum,
            "base_repo_state_checksum": context_pack.base_repo_state_checksum,
            "primary_output_checksum": str(chain.get("primary_output_checksum") or ""),
            "reviewer_output_checksum": str(chain.get("reviewer_output_checksum") or ""),
            "raw_reviewed_diff_checksum": raw_diff_checksum,
            "final_artifact_checksum": str(chain.get("final_artifact_checksum") or ""),
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
                "patch_source": "llm_reviewed",
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
        now = utc_now_text()
        metadata = {
            "candidate_kind": "llm_unknown_family",
            "patch_source": "llm_reviewed",
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
            "patch_source": "llm_reviewed",
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
        }
        return {
            "llm_candidate_proposal_id": llm_candidate_proposal_id,
            "llm_repair_candidate_id": llm_repair_candidate_id,
            "candidate_checksum": candidate_checksum,
            "review_chain_identity_checksum": review_chain_identity_checksum,
            "raw_reviewed_diff_checksum": raw_diff_checksum,
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
                policy_validation_checksum="",
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


def _chain_accepts(
    decision: RepairRouteDecision,
    failure_evidence: FailureEvidence,
    context_pack: RepairContextPack,
    chain: dict[str, Any],
) -> bool:
    if decision.route != ROUTE_LLM_REVIEWED_UNKNOWN:
        return False
    required = (
        "primary_output_checksum",
        "reviewer_output_checksum",
        "proposed_diff_checksum",
        "raw_diff_bytes_checksum",
        "final_reviewed_diff_checksum",
        "final_artifact_checksum",
    )
    if any(not str(chain.get(key) or "") for key in required):
        return False
    return (
        chain.get("reviewer_decision") == "accept"
        and chain.get("proposal_kind") == "llm_repair_review"
        and chain.get("context_pack_checksum") == context_pack.context_pack_checksum
        and chain.get("job_id") == context_pack.job_id == failure_evidence.job_id
        and chain.get("stage_index") == context_pack.stage_index == failure_evidence.stage_index
        and _sha256_prefixed_text(chain.get("proposed_diff_checksum")) == _sha256_prefixed_text(chain.get("raw_diff_bytes_checksum"))
        and _sha256_prefixed_text(chain.get("proposed_diff_checksum")) == _sha256_prefixed_text(chain.get("final_reviewed_diff_checksum"))
        and chain.get("primary_deterministic_fallback_used") is False
        and chain.get("reviewer_deterministic_fallback_used") is False
    )


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


def _contained_file(output_dir: Path, diff_ref: str) -> Path | None:
    if not diff_ref:
        return None
    try:
        root = output_dir.resolve(strict=True)
        path = Path(diff_ref).resolve(strict=True)
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


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
            "reviewer_output_checksum",
            "raw_diff_bytes_checksum",
            "final_reviewed_diff_checksum",
            "final_artifact_checksum",
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
