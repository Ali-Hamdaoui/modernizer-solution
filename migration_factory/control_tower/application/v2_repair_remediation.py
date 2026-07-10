"""Governed operator remediation commands over the existing repair pipeline."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path, PurePosixPath
import re
from types import SimpleNamespace
from typing import Any

from migration_factory.control_tower.application.v2_llm_read_only_candidate_persistence import (
    LlmReadOnlyCandidatePersistenceService,
)
from migration_factory.control_tower.application.v2_model_role_router import V2ModelRole
from migration_factory.control_tower.application.v2_repair_route_decision import (
    REASON_LLM_UNKNOWN_ELIGIBLE,
    ROUTE_LLM_REVIEWED_UNKNOWN,
    RepairRouteDecision,
)
from migration_factory.control_tower.domain.checksums import sha256_hex
from migration_factory.orchestrator.repair_review_chain import produce_repair_review_chain
from migration_factory.repair_loop.failure_evidence import (
    FailureEvidence,
    FailureSource,
    NormalizedCompilerError,
    NormalizedTestFailure,
)
from migration_factory.repair_loop.patch_gate import extract_touched_paths
from migration_factory.repair_loop.repair_context import (
    MAX_SOURCE_EVIDENCE_BYTES,
    MAX_SOURCE_EVIDENCE_FILES,
    RepairContextPack,
    _resolve_source_file,
    compute_context_pack_checksum,
)


MAX_OPERATOR_GUIDANCE_CHARS = 4000
MAX_MANUAL_DIFF_BYTES = 200_000


def repair_remediation_intent_from_text(
    text: str,
    *,
    job_id: str,
    stage_index: int,
    attempt_id: str,
) -> dict[str, Any] | None:
    """Translate conversation into a bounded, confirmation-required command."""
    raw = str(text or "").strip()
    lowered = raw.lower()
    if not raw:
        return None
    action = ""
    payload: dict[str, Any] = {}
    if "diff --git " in raw and any(term in lowered for term in ("manual diff", "use this", "apply this", "rerun")):
        action = "submit_manual_diff"
        payload["manual_diff"] = raw[raw.index("diff --git "):]
        payload["operator_justification"] = raw[:raw.index("diff --git ")].strip()
    elif any(term in lowered for term in ("add context", "add `", "include `", "inspect `")):
        requested = re.findall(r"`([^`]+)`", raw)
        if requested:
            action = "request_additional_context"
            payload["requested_context"] = requested[:8]
    elif "manual remediation" in lowered:
        action = "mark_manual_remediation_required"
    elif lowered.startswith("reject") or "reject current attempt" in lowered:
        action = "reject_current_attempt"
    elif "resume from" in lowered and "checkpoint" in lowered:
        action = "resume_from_repair_checkpoint"
    elif any(term in lowered for term in ("propose another", "another solution", "corrected proposal", "do not modify", "request revision")):
        action = "request_corrected_proposal"
        payload["operator_guidance"] = raw
    if not action:
        return None
    return {
        "action": action,
        "job_id": job_id,
        "stage_index": stage_index,
        "previous_attempt_id": attempt_id,
        **payload,
        "confirmation_required": True,
        "authority": "backend_governed",
    }


def execute_remediation_attempt(
    *,
    prior_attempt: dict[str, Any],
    action: str,
    model_client: Any,
    invocation_ledger: Any,
    repair_repo: Any,
    candidate_repo: Any,
    attempt_repo: Any,
    event_repo: Any,
    operator_guidance: str = "",
    requested_context: tuple[str, ...] = (),
    manual_diff: str = "",
    operator_justification: str = "",
) -> dict[str, Any]:
    latest = attempt_repo.latest_internal(
        str(prior_attempt.get("job_id") or ""),
        int(prior_attempt.get("stage_index") or 0),
    )
    if latest is None or str(latest.get("attempt_id") or "") != str(prior_attempt.get("attempt_id") or ""):
        raise ValueError("repair_attempt_superseded")
    internal = prior_attempt.get("internal") if isinstance(prior_attempt.get("internal"), dict) else {}
    evidence = failure_evidence_from_dict(internal.get("failure_evidence"))
    previous_context = repair_context_from_dict(internal.get("context_pack"))
    next_number = attempt_repo.next_attempt_number(evidence.job_id, evidence.stage_index)
    if next_number > previous_context.max_cycles:
        raise ValueError("maximum_repair_attempts_reached")
    guidance = str(operator_guidance or "").strip()
    if len(guidance) > MAX_OPERATOR_GUIDANCE_CHARS:
        raise ValueError("operator_guidance_too_long")
    context = _next_context_pack(
        previous_context,
        sandbox_path=str(internal.get("sandbox_path") or ""),
        operator_guidance=guidance,
        requested_context=requested_context,
        next_attempt_number=next_number,
    )
    client = model_client
    attempt_source = "llm"
    if action == "submit_manual_diff":
        raw = str(manual_diff or "")
        if not raw.strip():
            raise ValueError("manual_diff_required")
        if len(raw.encode("utf-8")) > MAX_MANUAL_DIFF_BYTES:
            raise ValueError("manual_diff_too_large")
        if not str(operator_justification or "").strip():
            raise ValueError("operator_justification_required")
        client = _ManualPrimaryClient(
            delegate=model_client,
            manual_diff=raw,
            operator_justification=str(operator_justification).strip(),
        )
        attempt_source = "manual"
    output_root_value = str(internal.get("output_dir") or "").strip()
    if not output_root_value:
        raise ValueError("repair_output_dir_unavailable")
    try:
        output_root = Path(output_root_value).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("repair_output_dir_unavailable") from exc
    if not output_root.is_dir():
        raise ValueError("repair_output_dir_unavailable")
    output_dir = output_root / f"attempt-{next_number:02d}"
    result = produce_repair_review_chain(
        failure_evidence=evidence,
        context_pack=context,
        output_dir=output_dir,
        source_profile=context.source_profile,
        target_profile=context.target_profile,
        model_client=client,
        invocation_ledger=invocation_ledger,
        proposal_id=None,
        gate_id=None,
        attempt_number=next_number,
        operator_guidance=guidance,
        advisory_reviewer=True,
    )
    chain = result.get("review_chain") if isinstance(result, dict) else None
    if isinstance(chain, dict):
        chain["attempt_source"] = attempt_source
        chain["previous_attempt_id"] = str(prior_attempt.get("attempt_id") or "")
        chain["operator_guidance"] = guidance
        chain["operator_justification"] = str(operator_justification or "").strip()
        metadata_ref = str((result.get("artifact_refs") or {}).get("review_chain_metadata") or "")
        if metadata_ref:
            metadata_path = Path(metadata_ref).resolve(strict=True)
            try:
                metadata_path.relative_to(output_dir.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise ValueError("repair_metadata_ref_outside_attempt") from exc
            metadata_path.write_text(json.dumps(chain, sort_keys=True, indent=2), encoding="utf-8")
    decision = RepairRouteDecision(
        route=ROUTE_LLM_REVIEWED_UNKNOWN,
        reason=REASON_LLM_UNKNOWN_ELIGIBLE,
        failure_type="unknown",
        classification_status="unknown",
        evidence_checksum=evidence.content_checksum,
        context_checksum=context.context_pack_checksum,
        base_repo_state_checksum=context.base_repo_state_checksum,
        deterministic_rule_id=None,
        llm_eligible=True,
        attempt_number=next_number - 1,
    )
    persistence = LlmReadOnlyCandidatePersistenceService(
        repair_repo=repair_repo,
        candidate_repo=candidate_repo,
        attempt_repo=attempt_repo,
        event_repo=event_repo,
    ).persist(
        decision=decision,
        failure_evidence=evidence,
        context_pack=context,
        chain_result=result,
        output_dir=output_root,
        sandbox_path=internal.get("sandbox_path"),
        run_dir=internal.get("run_dir"),
        legacy_path=internal.get("legacy_path"),
        source_proposal_id=str(prior_attempt.get("repair_candidate_id") or "") or None,
        source_gate_id=None,
    )
    created = attempt_repo.get_public(evidence.job_id, evidence.stage_index, persistence.attempt_id)
    return {
        "attempt": created,
        "candidate": candidate_repo.get_public(evidence.job_id, evidence.stage_index, persistence.llm_repair_candidate_id)
        if persistence.llm_repair_candidate_id else None,
        "status": persistence.status,
        "reason": persistence.reason,
    }


class _ManualPrimaryClient:
    def __init__(self, *, delegate: Any, manual_diff: str, operator_justification: str) -> None:
        self._delegate = delegate
        self._manual_diff = manual_diff
        self._justification = operator_justification

    def answer_with_role(self, *, role: Any, **kwargs: Any) -> Any:
        if role == V2ModelRole.PROPOSER:
            paths, _ = extract_touched_paths(self._manual_diff)
            content = json.dumps({
                "schema_version": "1.0",
                "proposal_kind": "llm_repair_primary",
                "root_cause": "Operator-investigated repair",
                "fix_strategy": self._justification,
                "changed_files": paths,
                "proposed_diff": self._manual_diff,
                "deterministic_rule_id": "no_safe_rule",
                "risk": "MEDIUM",
                "confidence": 1.0,
                "rationale": "Manual diff submitted by an authenticated operator; technical controls remain authoritative.",
            }, separators=(",", ":"))
            return SimpleNamespace(
                success=True,
                content=content,
                exact_provider_content=content,
                fallback_used=False,
                source="operator_manual_diff",
                provider="operator_manual_diff",
                model_status="available",
                failure_reason="",
                redacted_summary="manual diff captured",
                role="proposer",
            )
        return self._delegate.answer_with_role(role=role, **kwargs)


def _next_context_pack(
    previous: RepairContextPack,
    *,
    sandbox_path: str,
    operator_guidance: str,
    requested_context: tuple[str, ...],
    next_attempt_number: int,
) -> RepairContextPack:
    evidence = list(previous.source_evidence)
    if requested_context:
        evidence = _extend_source_evidence(evidence, sandbox_path=sandbox_path, requested=requested_context)
    comments = operator_guidance or previous.user_comments
    pack = replace(
        previous,
        user_comments=comments,
        source_evidence=tuple(evidence),
        prior_proposal_checksums=tuple(dict.fromkeys((*previous.prior_proposal_checksums, previous.context_pack_checksum))),
        cycle_number=next_attempt_number - 1,
        context_pack_checksum="",
    )
    return replace(pack, context_pack_checksum=compute_context_pack_checksum(pack))


def _extend_source_evidence(existing: list[dict[str, Any]], *, sandbox_path: str, requested: tuple[str, ...]) -> list[dict[str, Any]]:
    try:
        sandbox = Path(sandbox_path).resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("sandbox_context_unavailable")
    if not sandbox.is_dir():
        raise ValueError("sandbox_context_unavailable")
    paths = {str(entry.get("path") or "") for entry in existing}
    total = sum(int(entry.get("byte_length") or 0) for entry in existing)
    result = list(existing)
    for request in requested:
        candidates = _context_candidates(sandbox, str(request or "").strip())
        if not candidates:
            raise ValueError("additional_context_not_found")
        for candidate in candidates:
            resolved = _resolve_source_file(sandbox, candidate)
            if resolved is None:
                continue
            relative, path = resolved
            if relative in paths:
                continue
            raw = path.read_bytes()
            if len(raw) > MAX_SOURCE_EVIDENCE_BYTES or total + len(raw) > MAX_SOURCE_EVIDENCE_BYTES:
                raise ValueError("additional_context_size_limit")
            if len(result) >= MAX_SOURCE_EVIDENCE_FILES:
                raise ValueError("additional_context_file_limit")
            try:
                content = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("additional_context_invalid_encoding") from exc
            result.append({"path": relative, "checksum": "sha256:" + sha256_hex(raw), "byte_length": len(raw), "content": content})
            paths.add(relative)
            total += len(raw)
            break
        else:
            raise ValueError("additional_context_not_found")
    return result


def _context_candidates(sandbox: Path, request: str) -> tuple[str, ...]:
    if not request:
        return ()
    normalized = request.replace("\\", "/")
    explicit_suffixes = {".java", ".xml", ".gradle", ".kts", ".properties", ".yml", ".yaml"}
    if "/" in normalized or PurePosixPath(normalized).suffix.lower() in explicit_suffixes:
        return (normalized,)
    if "." in normalized and all(part and part[0].isalnum() for part in normalized.split(".")):
        fqcn = normalized.replace(".", "/") + ".java"
        return (f"src/main/java/{fqcn}", f"src/test/java/{fqcn}")
    matches: list[str] = []
    for root in (sandbox / "src" / "main" / "java", sandbox / "src" / "test" / "java"):
        if root.is_dir():
            for path in root.rglob(f"{normalized}.java"):
                try:
                    matches.append(path.relative_to(sandbox).as_posix())
                except ValueError:
                    continue
                if len(matches) >= 4:
                    break
    if not matches:
        symbol = re.compile(rf"\b{re.escape(normalized)}\b")
        inspected = 0
        for root in (sandbox / "src" / "main" / "java", sandbox / "src" / "test" / "java"):
            if not root.is_dir():
                continue
            for path in root.rglob("*.java"):
                inspected += 1
                if inspected > 500:
                    break
                try:
                    if path.stat().st_size > 256_000:
                        continue
                    if symbol.search(path.read_text(encoding="utf-8")):
                        matches.append(path.relative_to(sandbox).as_posix())
                except (OSError, UnicodeDecodeError, ValueError):
                    continue
                if len(matches) >= 4:
                    break
            if inspected > 500 or len(matches) >= 4:
                break
    module_pom = sandbox / normalized / "pom.xml"
    if module_pom.is_file():
        matches.append(module_pom.relative_to(sandbox).as_posix())
    return tuple(dict.fromkeys(matches))


def failure_evidence_from_dict(value: Any) -> FailureEvidence:
    data = value if isinstance(value, dict) else {}
    return FailureEvidence(
        failure_source=FailureSource(str(data.get("failure_source") or "unknown")),
        stage_index=int(data.get("stage_index") or 0),
        job_id=str(data.get("job_id") or ""),
        command_id=str(data.get("command_id") or ""),
        failure_summary=str(data.get("failure_summary") or ""),
        compiler_errors=tuple(NormalizedCompilerError(**item) for item in data.get("compiler_errors") or () if isinstance(item, dict)),
        test_failures=tuple(NormalizedTestFailure(**item) for item in data.get("test_failures") or () if isinstance(item, dict)),
        changed_files=tuple(data.get("changed_files") or ()),
        source_profile=str(data.get("source_profile") or ""),
        target_profile=str(data.get("target_profile") or ""),
        accepted_artifact_checksums=tuple(data.get("accepted_artifact_checksums") or ()),
        artifact_refs=dict(data.get("artifact_refs") or {}),
        stdout_tail=str(data.get("stdout_tail") or ""),
        stderr_tail=str(data.get("stderr_tail") or ""),
        safe_log_preview=str(data.get("safe_log_preview") or ""),
        content_checksum=str(data.get("content_checksum") or ""),
        artifact_checksum=str(data.get("artifact_checksum") or ""),
        created_at=str(data.get("created_at") or ""),
        schema_version=str(data.get("schema_version") or "1.0.0"),
    )


def repair_context_from_dict(value: Any) -> RepairContextPack:
    data = value if isinstance(value, dict) else {}
    return RepairContextPack(
        job_id=str(data.get("job_id") or ""), stage_index=int(data.get("stage_index") or 0),
        command_id=str(data.get("command_id") or ""), failure_source=str(data.get("failure_source") or "unknown"),
        failure_evidence_checksum=str(data.get("failure_evidence_checksum") or ""), source_profile=str(data.get("source_profile") or ""),
        target_profile=str(data.get("target_profile") or ""), accepted_analysis_checksum=str(data.get("accepted_analysis_checksum") or ""),
        accepted_planning_checksum=str(data.get("accepted_planning_checksum") or ""), prior_proposal_checksums=tuple(data.get("prior_proposal_checksums") or ()),
        prior_reviewer_notes=tuple(data.get("prior_reviewer_notes") or ()), user_comments=str(data.get("user_comments") or ""),
        changed_files=tuple(data.get("changed_files") or ()), safe_log_preview=str(data.get("safe_log_preview") or ""),
        source_evidence=tuple(data.get("source_evidence") or ()), base_repo_state_checksum=str(data.get("base_repo_state_checksum") or ""),
        context_pack_checksum=str(data.get("context_pack_checksum") or ""), prior_revision_ids=tuple(data.get("prior_revision_ids") or ()),
        cycle_number=int(data.get("cycle_number") or 0), max_cycles=int(data.get("max_cycles") or 3),
        created_at=str(data.get("created_at") or ""), schema_version=str(data.get("schema_version") or "1.0.0"),
    )
