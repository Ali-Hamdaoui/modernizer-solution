"""V2 Automatic Failure Diagnosis (F02).

Creates governed LLM diagnosis and repair proposal objects when backend-owned
migration execution emits build_failed, test_failed, or transform_failed.

Responsibilities:
1. Accept backend failure events with job/stage/command context.
2. Idempotency: reject duplicate diagnoses for the same command+event_type.
3. Collect existing failure evidence via evidence_collector.
4. Classify failure via failure_classifier.
5. Build enriched ContextPack using F01 metadata fields.
6. Route through F03 EventPromptRouter to RepairProposal.
7. Validate model output with existing schema validation.
8. Persist diagnosis/proposal correlation.
9. Emit ai_diagnosis_created event.
10. Never apply patches, create approval cards, or bypass repair_loop.

Non-goals (inherited from architecture):
- New failure collector, classifier, repair schema, event stream, or frontend-only diagnosis.
- Patch apply, approval card creation, or legacy source mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.redaction import (
    redact_absolute_paths,
    redact_model_summary,
)
from migration_factory.control_tower.domain.checksums import sha256_canonical_json, stream_sha256, utc_now_text
from migration_factory.control_tower.application.v2_model_schemas import (
    ContextPack,
    ContextPackBuilder,
    validate_model_output,
    SCHEMA_REGISTRY,
)
from migration_factory.control_tower.application.v2_prompt_router import (
    EventPromptRouter,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.application.v2_stage_failure_classifier import (
    classify_stage_failure,
)
from migration_factory.control_tower.application.v2_migration_memory import (
    retrieve_migration_memory,
)
from migration_factory.control_tower.application.v2_repair_proposer import (
    propose_stage_repair,
)
from migration_factory.control_tower.application.v2_repair_reviewer import (
    review_stage_repair_draft,
)
from migration_factory.control_tower.application.v2_llm_repair_shadow import (
    run_llm_repair_shadow_trace,
)
from migration_factory.control_tower.application.v2_repair_apply_candidate import (
    create_repair_apply_candidate,
    public_repair_apply_candidate,
)
from migration_factory.control_tower.application.v2_repair_strategy_packet import (
    create_repair_strategy_packet,
)


def _bind_if_exists(bound: dict[str, str], kind: str, path: Path) -> None:
    if bound.get(kind):
        return
    try:
        if path.exists():
            bound[kind] = str(path)
    except OSError:
        return


def _bind_power_mock_test_source_if_present(bound: dict[str, str], root: Path) -> None:
    if bound.get("test_source"):
        return
    try:
        files = root.rglob("*.java") if root.exists() else ()
        for index, path in enumerate(files):
            if index >= 200:
                break
            text = path.read_text(encoding="utf-8", errors="replace")[:2000].lower()
            if any(marker in text for marker in ("powermock", "powermockito", "preparefortest", "whennew", "mockstatic", "whitebox")):
                bound["test_source"] = str(path)
                return
    except OSError:
        return


def _bind_compile_error_source_files(bound: dict[str, str], contract: Path, sandbox: Path) -> None:
    try:
        text = contract.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    refs: list[str] = []
    for error in _extract_public_compile_errors(text):
        public_path = error.get("path", "")
        if not public_path.startswith("src/main/java"):
            continue
        candidate = (sandbox / public_path).resolve()
        try:
            candidate.relative_to(sandbox.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            refs.append(str(candidate))
    for index, ref in enumerate(dict.fromkeys(refs), start=1):
        bound[f"source_ref:{index}"] = ref
    if refs and not bound.get("source_ref"):
        bound["source_ref"] = refs[0]


def _extract_public_compile_errors(text: str) -> list[dict[str, str]]:
    text = _failure_contract_search_text(text)
    pattern = re.compile(
        r"(?P<path>(?:[a-z]:)?[^\"'\n\r]*src[\\/]+main[\\/]+java[^:\]\n\r]*\.java)"
        r"(?::?\[(?P<bracket_line>\d+),(?P<bracket_column>\d+)\]|[:\[](?P<line>\d+)(?:,(?P<column>\d+))?)?"
        r".{0,220}?(?P<message>incompatible types|cannot find symbol|package [^\"'\n\r]+ does not exist|compilation failure)",
        re.IGNORECASE,
    )
    errors: list[dict[str, str]] = []
    for match in pattern.finditer(text):
        errors.append({
            "path": _public_source_path(match.group("path")),
            "line": match.group("bracket_line") or match.group("line") or "",
            "column": match.group("bracket_column") or match.group("column") or "",
            "message": match.group("message"),
        })
    return errors[:12]


def _failure_contract_search_text(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    fields = ("stdout_tail", "stderr_tail", "errors", "blockers", "compile_errors", "message", "details", "causes", "logs")
    collected: list[str] = []

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                if str(child_key) in fields or key in fields:
                    collect(child_value, str(child_key))
                elif isinstance(child_value, (dict, list)):
                    collect(child_value, str(child_key))
        elif isinstance(value, list):
            for item in value:
                collect(item, key)
        elif key in fields or isinstance(value, str):
            collected.append(str(value))

    collect(parsed)
    return "\n".join(collected) if collected else text


def _public_source_path(path: str) -> str:
    marker = "src/main/java"
    normalized = path.replace("\\", "/")
    idx = normalized.lower().find(marker)
    return normalized[idx:] if idx >= 0 else normalized[-220:]


# ── Diagnosis record ──────────────────────────────────────────────


@dataclass(frozen=True)
class FailureDiagnosisRecord:
    """Correlated diagnosis record.

    Stored in-memory and/or serialized into ai_diagnosis_created event payload
    for audit. Keyed by (command_id, event_type) for idempotency.
    """
    diagnosis_id: str
    command_id: str
    event_type: str  # build_failed, test_failed, transform_failed
    failure_type: str  # from failure classifier
    context_pack_id: str
    context_pack_checksum: str
    repair_proposal_id: str | None
    model_invocation_id: str | None
    redaction_status: str
    created_at: str
    stage_evidence_pack: dict[str, Any] | None = None
    classification_envelope: dict[str, Any] | None = None


# ── Diagnosis service ─────────────────────────────────────────────


class V2FailureDiagnosisService:
    """Automatic failure diagnosis service.

    Triggered by backend failure events. Routes through existing evidence
    collection, classification, context pack building, prompt routing,
    schema validation, and repair proposal persistence.

    The service is idempotent: the same (command_id, event_type) pair
    cannot create duplicate diagnosis records.

    Production callers must serialize access via an event loop or lock.
    """

    # Failure event types that trigger diagnosis
    TRIGGER_EVENT_TYPES = frozenset({
        "build_failed",
        "test_failed",
        "transform_failed",
    })

    def __init__(
        self,
        *,
        repair_flow: V2RepairFlowService | None = None,
        event_sink: Callable[[str, int | None, str, str, str, dict[str, Any] | None], None] | None = None,
        evidence_collector: Callable[..., tuple[dict[str, Any], Path, dict[str, Any]]] | None = None,
        run_dir_resolver: Callable[[str, str], str | None] | None = None,
        repair_candidate_sink: Callable[[dict[str, Any]], None] | None = None,
        repair_strategy_sink: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
        llm_repair_shadow_client: Any | None = None,
        llm_repair_shadow_enabled: bool = False,
    ) -> None:
        self._repair_flow = repair_flow or V2RepairFlowService()
        self._event_sink = event_sink
        self._evidence_collector = evidence_collector
        self._run_dir_resolver = run_dir_resolver
        self._repair_candidate_sink = repair_candidate_sink
        self._repair_strategy_sink = repair_strategy_sink
        self._llm_repair_shadow_client = llm_repair_shadow_client
        self._llm_repair_shadow_enabled = llm_repair_shadow_enabled

        # In-memory idempotency store: {(command_id, event_type): diagnosis_id}
        self._diagnoses: dict[tuple[str, str], FailureDiagnosisRecord] = {}

    def diagnose(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        profile_id: str | None = None,
        pom_summary_ref: str | None = None,
        sandbox_binding_ref: str | None = None,
    ) -> FailureDiagnosisRecord:
        """Create a diagnosis for a backend failure event.

        Idempotent: returns existing record if already diagnosed for this
        (command_id, event_type).

        Args:
            job_id: The job that owns the failed command.
            stage_index: The stage index where failure occurred.
            command_id: The failed command id.
            event_type: One of build_failed, test_failed, transform_failed.
            payload: The full failure event payload with build/test/transform
                     status and contract fields.

        Returns:
            A FailureDiagnosisRecord with correlation fields.

        Raises:
            ValueError: If event_type is not a trigger type, or if
                        required context is missing.
        """
        # 1. Validate trigger event type
        if event_type not in self.TRIGGER_EVENT_TYPES:
            raise ValueError(
                f"Event type {event_type!r} is not a diagnosis trigger. "
                f"Expected one of: {', '.join(sorted(self.TRIGGER_EVENT_TYPES))}"
            )

        # 2. Idempotency check
        existing = self._diagnoses.get((command_id, event_type))
        if existing is not None:
            return existing

        payload_data = payload or {}

        # 3. Determine build/test statuses from payload for evidence collector
        build_status = str(payload_data.get("build_status", ""))
        test_status = str(payload_data.get("test_status", ""))
        transform_status = str(payload_data.get("transform_status", ""))

        # 4. Optional: resolve run_dir and sandbox_path from payload
        #    (prod callers pass artifact_refs; test callers may omit)
        artifact_refs = payload_data.get("artifact_refs", {})
        if not isinstance(artifact_refs, dict):
            artifact_refs = {}

        # 5. Build failure summary from payload
        failure_summary = self._build_failure_summary(
            event_type=event_type,
            payload=payload_data,
        )

        # 6. Collect failure evidence. Prefer injected collector; otherwise
        # build a bounded backend-owned stage evidence envelope from payload.
        stage_evidence_pack = self._build_stage_evidence_pack(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            event_type=event_type,
            payload=payload_data,
            failure_summary=failure_summary,
            build_status=build_status,
            test_status=test_status,
            transform_status=transform_status,
        )
        classification_result = None
        if self._evidence_collector:
            classification_result = self._collect_and_classify(
                command_id=command_id,
                event_type=event_type,
                payload=payload_data,
                build_status=build_status,
                test_status=test_status,
            )
        elif stage_evidence_pack is not None:
            classification_result = self._classification_from_stage_evidence(
                job_id=job_id,
                event_type=event_type,
                evidence_pack=stage_evidence_pack,
            )

        # 7. Build ContextPack with enrichment metadata (F01)
        failure_type = (
            classification_result.get("failure_type", "UNKNOWN")
            if classification_result
            else "UNKNOWN"
        )
        classification_envelope = (
            classification_result
            if classification_result
            else self._classification_unavailable(stage_index=stage_index)
        )
        if stage_evidence_pack is not None:
            stage_evidence_pack = self._strip_internal_artifact_refs(stage_evidence_pack)
        # Collect artifact refs from payload for context pack enrichment
        evidence_artifact_refs: tuple[str, ...] = ()
        raw_refs = payload_data.get("artifact_refs", {})
        if isinstance(raw_refs, dict):
            evidence_artifact_refs = tuple(
                str(v) for v in raw_refs.values() if v
            )[:10]
        pack = self._build_context_pack(
            event_type=event_type,
            stage_index=stage_index,
            command_id=command_id,
            failure_type=failure_type,
            failure_summary=failure_summary,
            classification=classification_result,
            redaction_status=(
                str(stage_evidence_pack.get("redaction_status") or "stage_evidence_collected")
                if stage_evidence_pack is not None
                else "evidence_redacted"
                if self._evidence_collector is not None
                else "evidence_collector_unavailable"
            ),
            pom_summary_ref=pom_summary_ref,
            sandbox_binding_ref=sandbox_binding_ref,
            profile_id=profile_id,
            artifact_refs_used=evidence_artifact_refs,
        )

        # 8. Route through EventPromptRouter to get ModelCallRequest
        route_payload = {
            "event_type": event_type,
            "stage_index": stage_index,
            "failure_summary": failure_summary,
            "evidence_refs": ", ".join(pack.evidence_refs),
            "command_id": command_id,
        }
        model_request = EventPromptRouter.route(
            event_type=event_type,
            pack=pack,
            payload=route_payload,
        )

        # 9. Validate the prompt_router output schema name exists
        schema_name = model_request.output_schema_name
        if schema_name not in SCHEMA_REGISTRY:
            raise ValueError(
                f"Schema {schema_name!r} resolved by prompt router is not registered"
            )

        # 10. Create the RepairProposal via repair flow.
        #     The proposal is a draft with evidence-based hypothesis.
        #     In production, LLM fills patch_summary and affected_paths
        #     via model-structured output after prompt routing.
        hypothesis = (
            classification_result.get("likely_root_cause", "Unknown failure")
            if classification_result
            else "Unknown failure"
        )
        proposal = self._repair_flow.create_proposal(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary="Diagnosis pending model-generated repair proposal",
            affected_paths=(),
        )

        # 11. Validate proposal against RepairProposal schema for defensive consistency.
        #     In production, the real model output is validated after model call.
        proposal_dict = {
            "failure_hypothesis": hypothesis,
            "patch_summary": "Diagnosis pending model-generated repair proposal",
            "affected_paths": [],
            "validation_plan": "Run model diagnosis to produce validated repair proposal.",
        }
        validate_model_output("RepairProposal", proposal_dict)

        # 12. Build diagnosis record
        diagnosis = FailureDiagnosisRecord(
            diagnosis_id=uuid4().hex,
            command_id=command_id,
            event_type=event_type,
            failure_type=failure_type,
            context_pack_id=pack.pack_id,
            context_pack_checksum=pack.checksum,
            repair_proposal_id=proposal.proposal_id,
            model_invocation_id=f"model-{model_request.request_id[:12]}",
            redaction_status=(
                str(stage_evidence_pack.get("redaction_status") or "stage_evidence_collected")
                if stage_evidence_pack is not None
                else "evidence_redacted"
                if self._evidence_collector is not None
                else "evidence_collector_unavailable"
            ),
            created_at=utc_now_text(),
            stage_evidence_pack=stage_evidence_pack,
            classification_envelope=classification_envelope,
        )

        # 13. Store for idempotency
        self._diagnoses[(command_id, event_type)] = diagnosis

        # 14. Emit ai_diagnosis_created event
        self._emit_diagnosis_created(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            event_type=event_type,
            diagnosis=diagnosis,
        )

        return diagnosis

    def classify_for_repair_route(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the normalized stage-failure classification for route selection.

        This intentionally stops at the pure stage-evidence classifier.  It does
        not create diagnosis records, prompt-router requests, strategy packets,
        apply candidates, repair proposals, LLM shadow traces, events, or gates.
        """
        if event_type not in self.TRIGGER_EVENT_TYPES:
            raise ValueError(
                f"Event type {event_type!r} is not a diagnosis trigger. "
                f"Expected one of: {', '.join(sorted(self.TRIGGER_EVENT_TYPES))}"
            )
        payload_data = payload or {}
        build_status = str(payload_data.get("build_status", ""))
        test_status = str(payload_data.get("test_status", ""))
        transform_status = str(payload_data.get("transform_status", ""))
        failure_summary = self._build_failure_summary(
            event_type=event_type,
            payload=payload_data,
        )
        stage_evidence_pack = self._build_stage_evidence_pack(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            event_type=event_type,
            payload=payload_data,
            failure_summary=failure_summary,
            build_status=build_status,
            test_status=test_status,
            transform_status=transform_status,
        )
        if stage_evidence_pack is None:
            return self._classification_unavailable(stage_index=stage_index)
        classification = classify_stage_failure(stage_evidence_pack)
        if not isinstance(classification, dict):
            return self._classification_unavailable(stage_index=stage_index)
        return classification

    def get_diagnosis(
        self,
        command_id: str,
        event_type: str,
    ) -> FailureDiagnosisRecord | None:
        """Retrieve an existing diagnosis record (idempotency lookup)."""
        return self._diagnoses.get((command_id, event_type))

    def list_diagnoses(self) -> tuple[FailureDiagnosisRecord, ...]:
        """List all in-memory diagnosis records."""
        return tuple(self._diagnoses.values())

    def clear(self) -> None:
        """Clear in-memory diagnoses (for testing)."""
        self._diagnoses.clear()

    # ── Internal helpers ───────────────────────────────────────────

    def _build_failure_summary(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        """Build a human-readable failure summary from event payload."""
        build_status = str(payload.get("build_status", ""))
        test_status = str(payload.get("test_status", ""))
        transform_status = str(payload.get("transform_status", ""))
        message = str(payload.get("message", ""))
        stderr = str(payload.get("stderr", ""))[:200]
        stdout_tail = str(payload.get("stdout_tail", ""))[:200]

        parts: list[str] = []

        if event_type == "build_failed":
            parts.append(f"Build failed: {build_status}")
        elif event_type == "test_failed":
            parts.append(f"Test failed: {test_status}")
        elif event_type == "transform_failed":
            parts.append(f"Transform failed: {transform_status or build_status}")

        if message and message != parts[-1] if parts else False:
            parts.append(message[:200])
        if stderr:
            parts.append(f"stderr: {stderr}")
        if stdout_tail:
            parts.append(f"stdout: {stdout_tail}")

        return " | ".join(parts) if parts else f"{event_type} with no details"

    def _collect_and_classify(
        self,
        *,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
        build_status: str,
        test_status: str,
    ) -> dict[str, Any]:
        """Collect failure evidence and classify the failure.

        Uses existing evidence_collector.collect_failure_evidence() and
        failure_classifier.agent.classify_failure() when available.
        Falls back to minimal classification when collector is not configured.
        """
        if self._evidence_collector is None:
            return self._minimal_classification(
                event_type=event_type,
                build_status=build_status,
                test_status=test_status,
            )

        # Resolve run_dir from command_id if resolver available
        run_dir_str = None
        if self._run_dir_resolver:
            run_dir_str = self._run_dir_resolver(command_id, event_type)

        run_dir = Path(run_dir_str) if run_dir_str else Path("/tmp/unknown")

        # Extract artifact refs if available
        artifact_refs = payload.get("artifact_refs", {})
        if not isinstance(artifact_refs, dict):
            artifact_refs = {}

        sandbox_path = payload.get("sandbox_path", None)
        h2_report = payload.get("h2_startup_report", None)

        try:
            classification, _, _ = self._evidence_collector(
                run_id=command_id,
                run_dir=str(run_dir),
                sandbox_path=sandbox_path,
                artifact_refs=artifact_refs,
                build_status=build_status,
                test_status=test_status,
                h2_startup_report=h2_report,
            )
            return classification
        except Exception:
            return self._minimal_classification(
                event_type=event_type,
                build_status=build_status,
                test_status=test_status,
            )

    def _build_context_pack(
        self,
        *,
        event_type: str,
        stage_index: int,
        command_id: str,
        failure_type: str,
        failure_summary: str,
        classification: dict[str, Any] | None,
        redaction_status: str = "evidence_collector_unavailable",
        pom_summary_ref: str | None = None,
        sandbox_binding_ref: str | None = None,
        profile_id: str | None = None,
        artifact_refs_used: tuple[str, ...] = (),
    ) -> ContextPack:
        """Build an enriched ContextPack for the diagnosis.

        Passes F01 enrichment metadata fields so downstream services
        (prompt router, model client, cockpit) can use them.
        Evidence refs include the failure classification artifact path
        when available.
        """
        evidence_refs: list[str] = []

        if classification:
            evidence_refs.append(f"failure_type={classification.get('failure_type', 'UNKNOWN')}")
            evidence_refs.append(f"severity={classification.get('severity', 'UNKNOWN')}")
            if classification.get("evidence"):
                evidence_refs.extend(str(e) for e in classification["evidence"][:3])

        pack = ContextPackBuilder.build_context_pack(
            pack_type="repair_proposal",
            title=f"Diagnosis for {event_type}",
            description=failure_summary,
            evidence_refs=tuple(evidence_refs) if evidence_refs else ("no_evidence",),
            agent_name="v2-failure-diagnosis",
            event_type=event_type,
            stage_index=stage_index,
            command_id=command_id,
            failure_type=failure_type,
            redaction_status=redaction_status,
            pom_summary_ref=pom_summary_ref,
            sandbox_binding_ref=sandbox_binding_ref,
            profile_id=profile_id,
            artifact_refs_used=artifact_refs_used,
        )
        return pack

    def _emit_diagnosis_created(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        diagnosis: FailureDiagnosisRecord,
    ) -> None:
        """Emit ai_diagnosis_created event via the configured event sink."""
        if self._event_sink is None:
            return

        event_payload = {
            "diagnosis_id": diagnosis.diagnosis_id,
            "context_pack_id": diagnosis.context_pack_id,
            "context_pack_checksum": diagnosis.context_pack_checksum,
            "command_id": diagnosis.command_id,
            "event_type": diagnosis.event_type,
            "failure_type": diagnosis.failure_type,
            "repair_proposal_id": diagnosis.repair_proposal_id,
            "model_invocation_id": diagnosis.model_invocation_id,
            "redaction_status": diagnosis.redaction_status,
        }
        if diagnosis.stage_evidence_pack is not None:
            event_payload["stage_evidence"] = diagnosis.stage_evidence_pack
            event_payload["evidence_refs"] = [
                str(diagnosis.stage_evidence_pack.get("evidence_pack_id") or ""),
                str(diagnosis.stage_evidence_pack.get("evidence_pack_checksum") or ""),
                *[
                    str(item.get("ref") or "")
                    for item in diagnosis.stage_evidence_pack.get("usable_artifacts", [])
                    if isinstance(item, dict)
                ],
            ][:12]
        if diagnosis.classification_envelope is not None:
            event_payload["classification"] = diagnosis.classification_envelope
        self._event_sink(
            job_id=job_id,
            stage=stage_index,
            event_type="ai_diagnosis_created",
            status="completed",
            message=f"AI diagnosis created for {event_type} (command {command_id})",
            payload=event_payload,
        )

    @staticmethod
    def _minimal_classification(
        *,
        event_type: str,
        build_status: str,
        test_status: str,
    ) -> dict[str, Any]:
        """Create a minimal classification when evidence collector is unavailable."""
        failure_type = event_type.upper()
        severity = "BLOCKER"

        if event_type == "build_failed":
            likely_root_cause = f"Maven build failed: {build_status or 'unknown error'}"
        elif event_type == "test_failed":
            likely_root_cause = f"Test validation failed: {test_status or 'unknown error'}"
        elif event_type == "transform_failed":
            likely_root_cause = "Sandbox transform failed"
        else:
            likely_root_cause = "Unknown failure"

        return {
            "failure_type": failure_type,
            "severity": severity,
            "migration_blocker": True,
            "security_env_warning": False,
            "likely_root_cause": likely_root_cause,
            "evidence": [],
            "recommended_next_step": "Review build/test logs and rerun.",
            "requires_human_review": False,
        }

    @staticmethod
    def _stage_metadata(stage_index: int, payload: dict[str, Any]) -> dict[str, Any]:
        defaults: dict[int, dict[str, str]] = {
            1: {
                "stage_name": "Spring Boot 2.1 + Java 11 to Spring Boot 2.7 + Java 11",
                "source_boot_version": "2.1",
                "target_boot_version": "2.7",
                "source_java_version": "11",
                "target_java_version": "11",
            },
            2: {
                "stage_name": "Spring Boot 2.7 + Java 11 to Spring Boot 3.5.16 + Java 17",
                "source_boot_version": "2.7",
                "target_boot_version": "3.5.16",
                "source_java_version": "11",
                "target_java_version": "17",
            },
            3: {
                "stage_name": "Spring Boot 3.5.16 + Java 17 to Spring Boot 3.5.16 + Java 21",
                "source_boot_version": "3.5.16",
                "target_boot_version": "3.5.16",
                "source_java_version": "17",
                "target_java_version": "21",
            },
            4: {
                "stage_name": "Spring Boot 3.5.16 + Java 21 to Spring Boot 4.0.7 + Java 21",
                "source_boot_version": "3.5.16",
                "target_boot_version": "4.0.7",
                "source_java_version": "21",
                "target_java_version": "21",
            },
        }
        meta = dict(defaults.get(stage_index, {}))
        for key in (
            "stage_name",
            "source_boot_version",
            "target_boot_version",
            "source_java_version",
            "target_java_version",
            "input_source_kind",
            "input_artifact_ref",
            "output_sandbox_ref",
            "previous_stage_ref",
        ):
            if payload.get(key):
                meta[key] = str(payload[key])
        meta.setdefault("stage_name", f"Stage {stage_index}")
        meta.setdefault("source_boot_version", "unknown")
        meta.setdefault("target_boot_version", "unknown")
        meta.setdefault("source_java_version", "unknown")
        meta.setdefault("target_java_version", "unknown")
        meta.setdefault("input_source_kind", "stage_output" if stage_index > 1 else "legacy_source")
        meta.setdefault("input_artifact_ref", "")
        meta.setdefault("output_sandbox_ref", str(payload.get("sandbox_path") or ""))
        meta.setdefault("previous_stage_ref", f"stage:{stage_index - 1}" if stage_index > 1 else "")
        return meta

    def _build_stage_evidence_pack(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
        failure_summary: str,
        build_status: str,
        test_status: str,
        transform_status: str,
    ) -> dict[str, Any] | None:
        artifact_refs = payload.get("artifact_refs", {})
        if not isinstance(artifact_refs, dict):
            artifact_refs = {}
        sandbox_ref = str(payload.get("sandbox_path") or "")
        if not artifact_refs and not sandbox_ref and not any(payload.get(k) for k in ("stage_name", "input_artifact_ref", "output_sandbox_ref")):
            return None

        expected = (
            "build_error_contract",
            "test_agent_log",
            "test_report",
            "test_source",
            "pom_xml",
            "dependency_graph",
            "runtime_contract",
            "reference_delta",
            "rewrite_patch",
            "rewrite_preview",
            "migration_ledger",
            "orchestration_summary",
            "phase2_log",
            "transformation_execution_plan",
            "target_dependency_plan",
            "sandbox",
        )
        bound_refs = self._bind_existing_failure_artifacts(artifact_refs, sandbox_ref)
        usable: list[dict[str, Any]] = []
        missing: list[str] = []
        for kind in expected:
            ref = bound_refs.get(kind)
            if ref is None and kind == "build_error_contract" and payload.get(kind):
                ref = payload.get(kind)
            if ref is None and kind == "sandbox" and sandbox_ref:
                ref = sandbox_ref
            if ref:
                usable.append(self._artifact_summary(kind, str(ref)))
            else:
                missing.append(kind)
        for kind, ref in sorted(bound_refs.items()):
            if kind.startswith("source_ref:"):
                usable.append(self._artifact_summary("source_ref", str(ref)))

        stage_meta = self._stage_metadata(stage_index, payload)
        downstream = {
            "next_stage_index": stage_index + 1,
            "state": "pending_blocked_by_failed_stage",
            "auto_started": False,
        }
        pack: dict[str, Any] = {
            "job_id": job_id,
            "stage_index": stage_index,
            **stage_meta,
            "downstream_stage_state": downstream,
            "failed_command_id": command_id,
            "event_type": event_type,
            "build_status": build_status,
            "test_status": test_status,
            "transform_status": transform_status,
            "failure_summary": redact_absolute_paths(redact_model_summary(failure_summary)),
            "evidence_status": "collected" if usable else "partial",
            "redaction_status": "stage_evidence_collected",
            "usable_artifacts": usable,
            "missing_artifacts": missing,
            "repair_enabled": False,
            "assistant_next_action": "classify_stage_failure",
            "created_at": utc_now_text(),
        }
        pack_id = f"stage-evidence-{uuid4().hex[:12]}"
        pack["evidence_pack_id"] = pack_id
        pack["evidence_pack_checksum"] = f"sha256:{sha256_canonical_json(pack)}"
        return pack

    @staticmethod
    def _bind_existing_failure_artifacts(artifact_refs: dict[str, Any], sandbox_ref: str) -> dict[str, str]:
        bound = {
            str(kind): str(ref)
            for kind, ref in artifact_refs.items()
            if ref
        }
        aliases = {
            "build_error_contract": ("build_error_path", "error_contract_path", "build_error", "result_contract"),
            "pom_xml": ("pom", "pom.xml", "sandbox_pom", "primary_pom"),
            "phase2_log": ("phase2_transform_log", "transform_log", "log_path"),
            "orchestration_summary": ("summary", "final_summary", "orchestration"),
            "migration_ledger": ("ledger", "ledger_path"),
        }
        for canonical, keys in aliases.items():
            if bound.get(canonical):
                continue
            for key in keys:
                value = artifact_refs.get(key)
                if value:
                    bound[canonical] = str(value)
                    break

        sandbox_path = Path(sandbox_ref) if sandbox_ref else None
        run_dir = None
        if sandbox_path is not None:
            try:
                if sandbox_path.name == "sandbox" and sandbox_path.parent.name == "workspaces":
                    run_dir = sandbox_path.parent.parent
            except IndexError:
                run_dir = None
            _bind_if_exists(bound, "sandbox", sandbox_path)
            _bind_if_exists(bound, "pom_xml", sandbox_path / "pom.xml")
            _bind_if_exists(bound, "migration_ledger", sandbox_path / ".migration" / "ledger.json")
            _bind_if_exists(bound, "test_report", sandbox_path / "target" / "surefire-reports")

        if run_dir is not None:
            _bind_if_exists(bound, "orchestration_summary", run_dir / "orchestration" / "orchestration_summary.json")
            _bind_if_exists(bound, "phase2_log", run_dir / "logs" / "phase2_transform.log")
            _bind_if_exists(bound, "runtime_contract", run_dir / "analysis" / "runtime_contract.json")
            _bind_if_exists(bound, "test_report", run_dir / "analysis" / "readonly-workspace" / "target" / "surefire-reports")
            _bind_if_exists(bound, "pom_xml", run_dir / "workspaces" / "sandbox" / "pom.xml")
            _bind_power_mock_test_source_if_present(bound, run_dir / "analysis" / "readonly-workspace" / "src" / "test" / "java")
            if not bound.get("build_error_contract"):
                build_dir = run_dir / "build"
                try:
                    matches = sorted(build_dir.glob("build-error-*.json"))
                except OSError:
                    matches = []
                if matches:
                    bound["build_error_contract"] = str(matches[-1])
            if bound.get("build_error_contract") and sandbox_path is not None:
                _bind_compile_error_source_files(bound, Path(bound["build_error_contract"]), sandbox_path)
        return bound

    @staticmethod
    def _artifact_summary(kind: str, ref: str) -> dict[str, Any]:
        redacted_ref = redact_absolute_paths(redact_model_summary(ref))
        summary: dict[str, Any] = {
            "kind": kind,
            "ref": redacted_ref,
            "checksum": "",
            "checksum_algorithm": "sha256",
        }
        if ref:
            summary["internal_ref"] = ref
        try:
            path = Path(ref)
            if path.is_file():
                checksum, size_bytes = stream_sha256(path)
                raw_text = path.read_text(encoding="utf-8", errors="replace")
                summary["checksum"] = f"sha256:{checksum}"
                summary["size_bytes"] = size_bytes
                if kind == "build_error_contract":
                    summary["compile_errors"] = _extract_public_compile_errors(raw_text)
                summary["excerpt"] = redact_absolute_paths(
                    redact_model_summary(raw_text[:2000])
                )
            elif path.exists():
                summary["note"] = "ref_exists_not_file"
        except OSError:
            summary["note"] = "checksum_unavailable"
        return summary

    @staticmethod
    def _classification_unavailable(*, stage_index: int) -> dict[str, Any]:
        return {
            "stage_index": stage_index,
            "failure_type": "UNKNOWN",
            "classification_status": "unknown",
            "repair_enabled": False,
            "reason": "evidence_pack_unavailable",
            "assistant_next_action": "collect_missing_stage_evidence",
        }

    def _classification_from_stage_evidence(
        self,
        *,
        job_id: str,
        event_type: str,
        evidence_pack: dict[str, Any],
    ) -> dict[str, Any]:
        _ = event_type
        classification = classify_stage_failure(evidence_pack)
        memory_context = {
            **classification,
            "failure_summary": evidence_pack.get("failure_summary", ""),
            "evidence_artifacts": evidence_pack.get("usable_artifacts", []),
        }
        classification["migration_memory"] = retrieve_migration_memory(memory_context)
        classification["repair_proposal_draft"] = propose_stage_repair(
            classification,
            evidence_pack,
            classification["migration_memory"],
        )
        classification["repair_draft_review"] = review_stage_repair_draft(
            classification,
            evidence_pack,
            classification["migration_memory"],
            classification["repair_proposal_draft"],
        )
        classification["llm_repair_shadow_trace"] = run_llm_repair_shadow_trace(
            job_id=job_id or str(evidence_pack.get("job_id") or ""),
            stage_index=evidence_pack.get("stage_index"),
            classification=classification,
            stage_evidence=evidence_pack,
            migration_memory=classification["migration_memory"],
            repair_proposal_draft=classification["repair_proposal_draft"],
            repair_draft_review=classification["repair_draft_review"],
            llm_client=self._llm_repair_shadow_client,
            llm_shadow_enabled=self._llm_repair_shadow_enabled,
        )
        strategy_packet = create_repair_strategy_packet(
            job_id=job_id or str(evidence_pack.get("job_id") or ""),
            stage_index=evidence_pack.get("stage_index"),
            classification=classification,
            stage_evidence=evidence_pack,
            migration_memory=classification["migration_memory"],
            llm_client=self._llm_repair_shadow_client,
            llm_enabled=self._llm_repair_shadow_enabled,
        )
        if self._repair_strategy_sink is not None:
            persisted = self._repair_strategy_sink(strategy_packet)
            if isinstance(persisted, dict):
                strategy_packet = persisted
        classification["repair_strategy_packet"] = strategy_packet
        if isinstance(strategy_packet.get("repair_subfamily_assessment"), dict):
            classification["repair_subfamily_assessment"] = strategy_packet["repair_subfamily_assessment"]
        internal_candidate = create_repair_apply_candidate(
            classification,
            evidence_pack,
            classification["llm_repair_shadow_trace"],
        )
        if internal_candidate is not None and self._repair_candidate_sink is not None:
            self._repair_candidate_sink(internal_candidate)
        classification["repair_apply_candidate"] = public_repair_apply_candidate(internal_candidate)
        classification["repair_enabled"] = False
        return classification

    @staticmethod
    def _strip_internal_artifact_refs(evidence_pack: dict[str, Any]) -> dict[str, Any]:
        clean = dict(evidence_pack)
        clean["usable_artifacts"] = [
            {key: value for key, value in item.items() if key != "internal_ref"}
            if isinstance(item, dict)
            else item
            for item in evidence_pack.get("usable_artifacts", [])
        ]
        return clean

    # ── Serialization ──────────────────────────────────────────────

    @staticmethod
    def diagnosis_to_dict(diagnosis: FailureDiagnosisRecord) -> dict[str, Any]:
        """Convert a FailureDiagnosisRecord to a dict for API responses."""
        return {
            "diagnosis_id": diagnosis.diagnosis_id,
            "command_id": diagnosis.command_id,
            "event_type": diagnosis.event_type,
            "failure_type": diagnosis.failure_type,
            "context_pack_id": diagnosis.context_pack_id,
            "context_pack_checksum": diagnosis.context_pack_checksum,
            "repair_proposal_id": diagnosis.repair_proposal_id,
            "model_invocation_id": diagnosis.model_invocation_id,
            "redaction_status": diagnosis.redaction_status,
            "created_at": diagnosis.created_at,
            "stage_evidence_pack": diagnosis.stage_evidence_pack,
            "classification_envelope": diagnosis.classification_envelope,
        }

    @staticmethod
    def is_diagnosable_event(event_type: str) -> bool:
        """Check if an event type can trigger diagnosis."""
        return event_type in V2FailureDiagnosisService.TRIGGER_EVENT_TYPES


# ── Orchestrator integration helper ───────────────────────────────


def create_orchestrator_diagnosis_callback(
    service: V2FailureDiagnosisService | None = None,
    *,
    repair_flow: Any | None = None,
    event_sink: Any | None = None,
    evidence_collector: Any | None = None,
    run_dir_resolver: Any | None = None,
    repair_candidate_sink: Any | None = None,
    repair_strategy_sink: Any | None = None,
    profile_id: str | None = None,
    pom_summary_ref: str | None = None,
    sandbox_binding_ref: str | None = None,
) -> Callable[[str, int, str, str, dict[str, Any]], None]:
    """Create a callback suitable for V2OrchestratorRunner(diagnosis_callback=...).

    The returned callback has the exact signature that
    V2OrchestratorRunner._maybe_diagnose expects:
        (job_id, stage_index, command_id, event_type, payload) -> None

    Usage:
        svc = V2FailureDiagnosisService(repair_flow=..., event_sink=...)
        runner = V2OrchestratorRunner(
            unit_of_work_factory=...,
            diagnosis_callback=create_orchestrator_diagnosis_callback(svc),
        )
    """
    if service is None:
        service = V2FailureDiagnosisService(
            repair_flow=repair_flow,
            event_sink=event_sink,
            evidence_collector=evidence_collector,
            run_dir_resolver=run_dir_resolver,
            repair_candidate_sink=repair_candidate_sink,
            repair_strategy_sink=repair_strategy_sink,
        )

    def callback(
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        service.diagnose(  # type: ignore[union-attr]
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            event_type=event_type,
            payload=payload,
            profile_id=profile_id,
            pom_summary_ref=pom_summary_ref,
            sandbox_binding_ref=sandbox_binding_ref,
        )

    return callback
