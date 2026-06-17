"""V2 Automatic Failure Diagnosis (F02)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from migration_factory.control_tower.application.v2_failure_classifier_rules import (
    classify_failure,
)
from migration_factory.control_tower.application.v2_failure_evidence import (
    EvidenceSnippet,
    FailureEvidenceCollector,
    FailureEvidencePack,
)
from migration_factory.control_tower.application.v2_model_schemas import (
    ContextPack,
    ContextPackBuilder,
    SCHEMA_REGISTRY,
    validate_model_output,
)
from migration_factory.control_tower.application.v2_prompt_router import (
    EventPromptRouter,
)
from migration_factory.control_tower.application.v2_repair_flow import (
    V2RepairFlowService,
)
from migration_factory.control_tower.domain.checksums import (
    canonical_json_text,
    sha256_canonical_json,
    utc_now_text,
)
from migration_factory.control_tower.infrastructure.sqlite.v2_failure_diagnosis_repository import (
    SqliteV2FailureDiagnosisRepository,
    V2FailureDiagnosisPersistedRecord,
)


@dataclass(frozen=True)
class FailureDiagnosisRecord:
    diagnosis_id: str
    command_id: str
    event_type: str
    failure_type: str
    context_pack_id: str
    context_pack_checksum: str
    repair_proposal_id: str | None
    model_invocation_id: str | None
    redaction_status: str
    likely_root_cause: str = ""
    confidence: str = "low"
    recommended_fix_type: str = ""
    affected_paths: tuple[str, ...] = ()
    validation_plan: tuple[str, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    missing_artifacts: tuple[str, ...] = ()
    evidence_pack_checksum: str = ""
    diagnosis_checksum: str = ""
    created_at: str = ""


class V2FailureDiagnosisService:
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
        diagnosis_repo: SqliteV2FailureDiagnosisRepository | None = None,
    ) -> None:
        self._repair_flow = repair_flow or V2RepairFlowService()
        self._event_sink = event_sink
        self._evidence_collector = evidence_collector
        self._run_dir_resolver = run_dir_resolver
        self._default_evidence_collector = FailureEvidenceCollector()
        self._diagnosis_repo = diagnosis_repo
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
        if event_type not in self.TRIGGER_EVENT_TYPES:
            raise ValueError(
                f"Event type {event_type!r} is not a diagnosis trigger. "
                f"Expected one of: {', '.join(sorted(self.TRIGGER_EVENT_TYPES))}"
            )

        persisted = self._get_persisted_diagnosis(command_id=command_id, event_type=event_type)
        if persisted is not None:
            self._diagnoses[(command_id, event_type)] = persisted
            return persisted

        existing = self._diagnoses.get((command_id, event_type))
        if existing is not None:
            return existing

        payload_data = payload or {}
        build_status = str(payload_data.get("build_status", ""))
        test_status = str(payload_data.get("test_status", ""))
        failure_summary = self._build_failure_summary(event_type=event_type, payload=payload_data)

        evidence_pack, classification_result = self._collect_and_classify(
            command_id=command_id,
            event_type=event_type,
            payload=payload_data,
            build_status=build_status,
            test_status=test_status,
            stage_index=stage_index,
        )

        failure_type = classification_result.get("failure_type", "UNKNOWN") if classification_result else "UNKNOWN"
        evidence_artifact_refs: tuple[str, ...] = ()
        raw_refs = payload_data.get("artifact_refs", {})
        if isinstance(raw_refs, dict):
            evidence_artifact_refs = tuple(str(v) for v in raw_refs.values() if v)[:10]

        pack = self._build_context_pack(
            event_type=event_type,
            stage_index=stage_index,
            command_id=command_id,
            failure_type=failure_type,
            failure_summary=failure_summary,
            classification=classification_result,
            redaction_status=("evidence_redacted" if classification_result else "evidence_collector_unavailable"),
            pom_summary_ref=pom_summary_ref,
            sandbox_binding_ref=sandbox_binding_ref,
            profile_id=profile_id,
            artifact_refs_used=evidence_artifact_refs,
        )

        model_request = EventPromptRouter.route(
            event_type=event_type,
            pack=pack,
            payload={
                "event_type": event_type,
                "stage_index": stage_index,
                "failure_summary": failure_summary,
                "evidence_refs": ", ".join(pack.evidence_refs),
                "command_id": command_id,
            },
        )
        if model_request.output_schema_name not in SCHEMA_REGISTRY:
            raise ValueError(
                f"Schema {model_request.output_schema_name!r} resolved by prompt router is not registered"
            )

        hypothesis = classification_result.get("likely_root_cause", "Unknown failure") if classification_result else "Unknown failure"
        proposal = self._repair_flow.create_proposal(
            command_id=command_id,
            failure_summary=failure_summary,
            hypothesis=hypothesis,
            patch_summary="Diagnosis pending model-generated repair proposal",
            affected_paths=(),
        )
        validate_model_output(
            "RepairProposal",
            {
                "failure_hypothesis": hypothesis,
                "patch_summary": "Diagnosis pending model-generated repair proposal",
                "affected_paths": [],
                "validation_plan": "Run model diagnosis to produce validated repair proposal.",
            },
        )

        diagnosis = FailureDiagnosisRecord(
            diagnosis_id=uuid4().hex,
            command_id=command_id,
            event_type=event_type,
            failure_type=failure_type,
            context_pack_id=pack.pack_id,
            context_pack_checksum=pack.checksum,
            repair_proposal_id=proposal.proposal_id,
            model_invocation_id=f"model-{model_request.request_id[:12]}",
            redaction_status=("evidence_redacted" if classification_result else "evidence_collector_unavailable"),
            likely_root_cause=hypothesis,
            confidence=str(classification_result.get("confidence", "low") if classification_result else "low"),
            recommended_fix_type=str(classification_result.get("recommended_fix_type", "") if classification_result else ""),
            affected_paths=tuple(str(path) for path in classification_result.get("affected_paths", []) if str(path)) if classification_result else (),
            validation_plan=self._validation_plan_tuple(classification_result),
            evidence=self._evidence_tuple(classification_result),
            missing_artifacts=tuple(evidence_pack.missing_artifacts) if evidence_pack is not None else (),
            evidence_pack_checksum=self.compute_evidence_pack_checksum(evidence_pack),
            diagnosis_checksum="",
            created_at=utc_now_text(),
        )
        diagnosis = self._persist_if_possible(
            job_id=job_id,
            stage_index=stage_index,
            diagnosis=diagnosis,
            context_pack_checksum=pack.checksum,
        )

        self._diagnoses[(command_id, event_type)] = diagnosis
        self._emit_diagnosis_created(
            job_id=job_id,
            stage_index=stage_index,
            command_id=command_id,
            event_type=event_type,
            diagnosis=diagnosis,
        )
        return diagnosis

    def get_diagnosis(self, command_id: str, event_type: str) -> FailureDiagnosisRecord | None:
        return self._diagnoses.get((command_id, event_type)) or self._get_persisted_diagnosis(
            command_id=command_id,
            event_type=event_type,
        )

    def list_diagnoses(self) -> tuple[FailureDiagnosisRecord, ...]:
        return tuple(self._diagnoses.values())

    def clear(self) -> None:
        self._diagnoses.clear()

    def _build_failure_summary(
        self,
        *,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
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
        stage_index: int,
    ) -> tuple[FailureEvidencePack | None, dict[str, Any]]:
        run_dir_str = self._run_dir_resolver(command_id, event_type) if self._run_dir_resolver else None
        artifact_refs = payload.get("artifact_refs", {})
        if not isinstance(artifact_refs, dict):
            artifact_refs = {}
        sandbox_path = payload.get("sandbox_path", None)

        try:
            if self._evidence_collector is not None:
                classification, _, _ = self._evidence_collector(
                    run_id=command_id,
                    run_dir=str(Path(run_dir_str)) if run_dir_str else "",
                    sandbox_path=sandbox_path,
                    artifact_refs=artifact_refs,
                    build_status=build_status,
                    test_status=test_status,
                    h2_startup_report=payload.get("h2_startup_report", None),
                )
                return self._classification_to_pack(command_id=command_id, event_type=event_type, classification=classification), classification

            evidence_pack = self._default_evidence_collector.collect(
                run_id=command_id,
                event_type=event_type,
                run_dir=run_dir_str,
                sandbox_path=sandbox_path,
                artifact_refs=artifact_refs,
                payload=payload,
            )
            return evidence_pack, classify_failure(
                evidence_pack=evidence_pack,
                payload=payload,
                stage_index=stage_index,
                event_type=event_type,
            )
        except Exception:
            return None, self._minimal_classification(
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
        evidence_refs: list[str] = []
        if classification:
            evidence_refs.append(f"failure_type={classification.get('failure_type', 'UNKNOWN')}")
            evidence_refs.append(f"severity={classification.get('severity', 'UNKNOWN')}")
            if classification.get("evidence"):
                evidence_refs.extend(str(e) for e in classification["evidence"][:3])

        return ContextPackBuilder.build_context_pack(
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

    def _emit_diagnosis_created(
        self,
        *,
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        diagnosis: FailureDiagnosisRecord,
    ) -> None:
        if self._event_sink is None:
            return
        self._event_sink(
            job_id=job_id,
            stage=stage_index,
            event_type="ai_diagnosis_created",
            status="completed",
            message=f"AI diagnosis created for {event_type} (command {command_id})",
            payload={
                "diagnosis_id": diagnosis.diagnosis_id,
                "context_pack_id": diagnosis.context_pack_id,
                "context_pack_checksum": diagnosis.context_pack_checksum,
                "command_id": diagnosis.command_id,
                "event_type": diagnosis.event_type,
                "failure_type": diagnosis.failure_type,
                "repair_proposal_id": diagnosis.repair_proposal_id,
                "model_invocation_id": diagnosis.model_invocation_id,
                "redaction_status": diagnosis.redaction_status,
                "likely_root_cause": diagnosis.likely_root_cause,
                "confidence": diagnosis.confidence,
                "recommended_fix_type": diagnosis.recommended_fix_type,
                "affected_paths": list(diagnosis.affected_paths),
                "validation_plan": list(diagnosis.validation_plan),
                "evidence": list(diagnosis.evidence),
                "missing_artifacts": list(diagnosis.missing_artifacts),
                "evidence_pack_checksum": diagnosis.evidence_pack_checksum,
                "diagnosis_checksum": diagnosis.diagnosis_checksum,
            },
        )

    @staticmethod
    def _minimal_classification(
        *,
        event_type: str,
        build_status: str,
        test_status: str,
    ) -> dict[str, Any]:
        if event_type == "build_failed":
            likely_root_cause = f"Maven build failed: {build_status or 'unknown error'}"
        elif event_type == "test_failed":
            likely_root_cause = f"Test validation failed: {test_status or 'unknown error'}"
        elif event_type == "transform_failed":
            likely_root_cause = "Sandbox transform failed"
        else:
            likely_root_cause = "Unknown failure"
        return {
            "failure_type": event_type.upper(),
            "severity": "BLOCKER",
            "migration_blocker": True,
            "security_env_warning": False,
            "likely_root_cause": likely_root_cause,
            "confidence": "low",
            "evidence": [],
            "recommended_fix_type": "inspect_failure_logs",
            "affected_paths": [],
            "validation_plan": "Review build/test logs and rerun deterministic diagnosis with artifacts.",
            "recommended_next_step": "Review build/test logs and rerun.",
            "send_to_copilot": True,
            "requires_human_review": False,
        }

    @staticmethod
    def diagnosis_to_dict(diagnosis: FailureDiagnosisRecord) -> dict[str, Any]:
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
            "likely_root_cause": diagnosis.likely_root_cause,
            "confidence": diagnosis.confidence,
            "recommended_fix_type": diagnosis.recommended_fix_type,
            "affected_paths": list(diagnosis.affected_paths),
            "validation_plan": list(diagnosis.validation_plan),
            "evidence": list(diagnosis.evidence),
            "missing_artifacts": list(diagnosis.missing_artifacts),
            "evidence_pack_checksum": diagnosis.evidence_pack_checksum,
            "diagnosis_checksum": diagnosis.diagnosis_checksum,
            "created_at": diagnosis.created_at,
        }

    @staticmethod
    def is_diagnosable_event(event_type: str) -> bool:
        return event_type in V2FailureDiagnosisService.TRIGGER_EVENT_TYPES

    @staticmethod
    def compute_evidence_pack_checksum(evidence_pack: FailureEvidencePack | None) -> str:
        if evidence_pack is None:
            return sha256_canonical_json({})
        return sha256_canonical_json(
            {
                "run_id": evidence_pack.run_id,
                "event_type": evidence_pack.event_type,
                "snippets": [
                    {"source": snippet.source, "label": snippet.label, "text": snippet.text}
                    for snippet in evidence_pack.snippets
                ],
                "missing_artifacts": list(evidence_pack.missing_artifacts),
                "affected_paths": list(evidence_pack.affected_paths),
                "redaction_status": evidence_pack.redaction_status,
            }
        )

    @staticmethod
    def compute_diagnosis_checksum(payload: dict[str, Any]) -> str:
        candidate = dict(payload)
        candidate.pop("created_at", None)
        candidate.pop("diagnosis_id", None)
        return sha256_canonical_json(candidate)

    @staticmethod
    def persisted_record_to_dict(record: V2FailureDiagnosisPersistedRecord) -> dict[str, Any]:
        return {
            "diagnosis_id": record.diagnosis_id,
            "job_id": record.job_id,
            "stage_index": record.stage_index,
            "command_id": record.command_id,
            "event_type": record.event_type,
            "failure_type": record.failure_type,
            "likely_root_cause": record.likely_root_cause,
            "confidence": record.confidence,
            "recommended_fix_type": record.recommended_fix_type,
            "affected_paths": json.loads(record.affected_paths_json),
            "validation_plan": json.loads(record.validation_plan_json),
            "recommended_next_step": "; ".join(json.loads(record.validation_plan_json)),
            "evidence": json.loads(record.evidence_json),
            "missing_artifacts": json.loads(record.missing_artifacts_json),
            "context_pack_checksum": record.context_pack_checksum,
            "evidence_pack_checksum": record.evidence_pack_checksum,
            "diagnosis_checksum": record.diagnosis_checksum,
            "redaction_status": record.redaction_status,
            "created_at": record.created_at,
        }

    def _persist_if_possible(
        self,
        *,
        job_id: str,
        stage_index: int,
        diagnosis: FailureDiagnosisRecord,
        context_pack_checksum: str,
    ) -> FailureDiagnosisRecord:
        diagnosis_checksum = self.compute_diagnosis_checksum(
            self._diagnosis_payload_for_checksum(
                job_id=job_id,
                stage_index=stage_index,
                diagnosis=diagnosis,
                context_pack_checksum=context_pack_checksum,
            )
        )
        if self._diagnosis_repo is None:
            return FailureDiagnosisRecord(**{
                **self.diagnosis_to_dict(diagnosis),
                "context_pack_id": diagnosis.context_pack_id,
                "diagnosis_checksum": diagnosis_checksum,
            })

        record = V2FailureDiagnosisPersistedRecord(
            diagnosis_id=diagnosis.diagnosis_id,
            job_id=job_id,
            stage_index=stage_index,
            command_id=diagnosis.command_id,
            event_type=diagnosis.event_type,
            failure_type=diagnosis.failure_type,
            likely_root_cause=diagnosis.likely_root_cause,
            confidence=diagnosis.confidence,
            recommended_fix_type=diagnosis.recommended_fix_type,
            affected_paths_json=canonical_json_text(list(diagnosis.affected_paths)),
            validation_plan_json=canonical_json_text(list(diagnosis.validation_plan)),
            evidence_json=canonical_json_text(list(diagnosis.evidence)),
            missing_artifacts_json=canonical_json_text(list(diagnosis.missing_artifacts)),
            context_pack_checksum=context_pack_checksum,
            evidence_pack_checksum=diagnosis.evidence_pack_checksum,
            diagnosis_checksum=diagnosis_checksum,
            redaction_status=diagnosis.redaction_status,
            created_at=diagnosis.created_at,
        )
        self._diagnosis_repo.save_diagnosis(record)
        return self._persisted_to_runtime_record(record, diagnosis.context_pack_id, diagnosis.repair_proposal_id, diagnosis.model_invocation_id)

    def _get_persisted_diagnosis(
        self,
        *,
        command_id: str,
        event_type: str,
    ) -> FailureDiagnosisRecord | None:
        if self._diagnosis_repo is None:
            return None
        record = self._diagnosis_repo.get_by_command_and_event(command_id, event_type)
        if record is None:
            return None
        return self._persisted_to_runtime_record(record, "persisted-diagnosis", None, None)

    def _persisted_to_runtime_record(
        self,
        record: V2FailureDiagnosisPersistedRecord,
        context_pack_id: str,
        repair_proposal_id: str | None,
        model_invocation_id: str | None,
    ) -> FailureDiagnosisRecord:
        payload = self.persisted_record_to_dict(record)
        return FailureDiagnosisRecord(
            diagnosis_id=record.diagnosis_id,
            command_id=record.command_id,
            event_type=record.event_type,
            failure_type=record.failure_type,
            context_pack_id=context_pack_id,
            context_pack_checksum=record.context_pack_checksum,
            repair_proposal_id=repair_proposal_id,
            model_invocation_id=model_invocation_id,
            redaction_status=record.redaction_status,
            likely_root_cause=record.likely_root_cause,
            confidence=record.confidence,
            recommended_fix_type=record.recommended_fix_type,
            affected_paths=tuple(str(item) for item in payload["affected_paths"]),
            validation_plan=tuple(str(item) for item in payload["validation_plan"]),
            evidence=tuple(payload["evidence"]),
            missing_artifacts=tuple(str(item) for item in payload["missing_artifacts"]),
            evidence_pack_checksum=record.evidence_pack_checksum,
            diagnosis_checksum=record.diagnosis_checksum,
            created_at=record.created_at,
        )

    def _classification_to_pack(
        self,
        *,
        command_id: str,
        event_type: str,
        classification: dict[str, Any],
    ) -> FailureEvidencePack:
        snippets = tuple(
            EvidenceSnippet(
                source=str(item.get("source", "")),
                label=str(item.get("label", "")),
                text=str(item.get("text", "")),
            )
            for item in classification.get("evidence", [])
            if isinstance(item, dict)
        )
        return FailureEvidencePack(
            run_id=command_id,
            event_type=event_type,
            snippets=snippets,
            missing_artifacts=(),
            affected_paths=tuple(str(path) for path in classification.get("affected_paths", []) if str(path)),
            redaction_status="redacted",
            total_chars=sum(len(snippet.text) for snippet in snippets),
        )

    def _validation_plan_tuple(self, classification: dict[str, Any] | None) -> tuple[str, ...]:
        if not classification:
            return ()
        plan = classification.get("validation_plan")
        if isinstance(plan, list):
            return tuple(str(item) for item in plan if str(item))
        if isinstance(plan, str) and plan.strip():
            return (plan.strip(),)
        recommended = classification.get("recommended_next_step")
        if isinstance(recommended, str) and recommended.strip():
            return (recommended.strip(),)
        return ()

    def _evidence_tuple(self, classification: dict[str, Any] | None) -> tuple[dict[str, Any], ...]:
        if not classification:
            return ()
        evidence = classification.get("evidence")
        if not isinstance(evidence, list):
            return ()
        return tuple(item for item in evidence if isinstance(item, dict))

    def _diagnosis_payload_for_checksum(
        self,
        *,
        job_id: str,
        stage_index: int,
        diagnosis: FailureDiagnosisRecord,
        context_pack_checksum: str,
    ) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "stage_index": stage_index,
            "command_id": diagnosis.command_id,
            "event_type": diagnosis.event_type,
            "failure_type": diagnosis.failure_type,
            "likely_root_cause": diagnosis.likely_root_cause,
            "confidence": diagnosis.confidence,
            "recommended_fix_type": diagnosis.recommended_fix_type,
            "affected_paths": list(diagnosis.affected_paths),
            "validation_plan": list(diagnosis.validation_plan),
            "evidence": list(diagnosis.evidence),
            "missing_artifacts": list(diagnosis.missing_artifacts),
            "context_pack_checksum": context_pack_checksum,
            "evidence_pack_checksum": diagnosis.evidence_pack_checksum,
            "redaction_status": diagnosis.redaction_status,
        }


def create_orchestrator_diagnosis_callback(
    service: V2FailureDiagnosisService | None = None,
    *,
    repair_flow: Any | None = None,
    event_sink: Any | None = None,
    evidence_collector: Any | None = None,
    run_dir_resolver: Any | None = None,
    diagnosis_repo: Any | None = None,
    profile_id: str | None = None,
    pom_summary_ref: str | None = None,
    sandbox_binding_ref: str | None = None,
) -> Callable[[str, int, str, str, dict[str, Any]], None]:
    if service is None:
        service = V2FailureDiagnosisService(
            repair_flow=repair_flow,
            event_sink=event_sink,
            evidence_collector=evidence_collector,
            run_dir_resolver=run_dir_resolver,
            diagnosis_repo=diagnosis_repo,
        )

    def callback(
        job_id: str,
        stage_index: int,
        command_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        service.diagnose(
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
