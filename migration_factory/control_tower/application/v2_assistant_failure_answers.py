from __future__ import annotations

from dataclasses import asdict, dataclass
from fnmatch import fnmatch
from pathlib import Path
import re
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_failure_classifier_rules import (
    classify_failure,
)
from migration_factory.control_tower.application.v2_failure_evidence import (
    FailureEvidenceCollector,
    FailureEvidencePack,
)


_FAILURE_QUESTION_RE = re.compile(
    r"(?i)\b(why .*fail|why build failed|what is real problem|what should i fix|explain the failure|failure|root cause|pourquoi .*échou|pourquoi .*fail)\b"
)
_STAGE_RE = re.compile(r"(?i)\bstage\s+([1-9][0-9]*)\b")
_SECRET_VALUE_RE = re.compile(
    r'(?i)"[^"]*(password|secret|token|api[_-]?key)[^"]*"\s*:\s*"[^"]+"|'
    r'\b(?:password|secret|token|api[_-]?key|access[_-]?key|authorization)\s*[:=]\s*[^\s,;]+|'
    r'bearer\s+[A-Za-z0-9._\-]{8,}'
)
_MAX_ANSWER_CHARS = 2400
_MAX_EVIDENCE_ITEMS = 4


@dataclass(frozen=True)
class V2AssistantFailureAnswer:
    failure_type: str
    root_cause: str
    confidence: str
    evidence: tuple[dict[str, str], ...]
    affected_paths: tuple[str, ...]
    recommended_next_step: str
    missing_artifacts: tuple[str, ...]
    safety_note: str
    answer: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2AssistantFailureAnswerService:
    def __init__(
        self,
        *,
        evidence_collector: FailureEvidenceCollector | None = None,
    ) -> None:
        self._evidence_collector = evidence_collector or FailureEvidenceCollector()

    @staticmethod
    def is_failure_question(text: str) -> bool:
        return bool(_FAILURE_QUESTION_RE.search(str(text or "")))

    @staticmethod
    def extract_stage_index(text: str) -> int | None:
        match = _STAGE_RE.search(str(text or ""))
        if match is None:
            return None
        return int(match.group(1))

    def build_answer_inputs(
        self,
        *,
        stage_index: int | None,
        event_type: str,
        recent_failure_event_payload: dict[str, Any] | None,
    ) -> tuple[FailureEvidencePack | None, dict[str, Any] | None]:
        payload = recent_failure_event_payload if isinstance(recent_failure_event_payload, dict) else None
        if payload is None:
            return None, None

        artifact_refs = payload.get("artifact_refs")
        if not isinstance(artifact_refs, dict):
            artifact_refs = {}
        sandbox_path = payload.get("sandbox_path")
        run_dir = self._infer_run_dir(payload=payload, artifact_refs=artifact_refs)

        evidence_pack = self._evidence_collector.collect(
            run_id=str(payload.get("command_id") or payload.get("run_id") or "unknown-run"),
            event_type=event_type,
            run_dir=run_dir,
            sandbox_path=sandbox_path,
            artifact_refs=artifact_refs,
            payload=payload,
        )
        classification = classify_failure(
            evidence_pack=evidence_pack,
            payload=payload,
            stage_index=stage_index or 0,
            event_type=event_type,
        )
        return evidence_pack, classification

    def answer_failure_question(
        self,
        *,
        job_id: str,
        stage_index: int | None = None,
        latest_diagnosis_data: dict[str, Any] | None = None,
        latest_proposal_data: dict[str, Any] | None = None,
        latest_reviewer_data: dict[str, Any] | None = None,
        failure_evidence_pack: FailureEvidencePack | None = None,
        failure_classification: dict[str, Any] | None = None,
        governed_status_data: dict[str, Any] | None = None,
        recent_failure_event_payload: dict[str, Any] | None = None,
        existing_message_text: str = "",
    ) -> V2AssistantFailureAnswer:
        diagnosis_data = latest_diagnosis_data if isinstance(latest_diagnosis_data, dict) else {}
        proposal_data = latest_proposal_data if isinstance(latest_proposal_data, dict) else {}
        reviewer_data = latest_reviewer_data if isinstance(latest_reviewer_data, dict) else {}
        governed_status = governed_status_data if isinstance(governed_status_data, dict) else {}
        payload = recent_failure_event_payload if isinstance(recent_failure_event_payload, dict) else {}
        classification = failure_classification if isinstance(failure_classification, dict) else {}

        missing_artifacts = list(
            diagnosis_data.get("missing_artifacts", [])
            if isinstance(diagnosis_data.get("missing_artifacts"), list)
            else ()
        )
        if failure_evidence_pack is not None:
            missing_artifacts.extend(failure_evidence_pack.missing_artifacts)
        if not payload:
            missing_artifacts.append("failed_event_payload")

        failure_type = str(
            diagnosis_data.get("failure_type")
            or classification.get("failure_type")
            or "unknown_build_failure"
        )
        root_cause = str(
            diagnosis_data.get("likely_root_cause")
            or classification.get("likely_root_cause")
            or "No deterministic failure diagnosis available because required backend evidence is missing."
        )
        confidence = str(diagnosis_data.get("confidence") or classification.get("confidence") or "low")
        recommended_next_step = str(
            diagnosis_data.get("recommended_next_step")
            or classification.get("recommended_next_step")
            or "Collect missing failure artifacts, then rerun deterministic diagnosis."
        )
        affected_paths = tuple(
            str(path)
            for path in (
                diagnosis_data.get("affected_paths")
                or classification.get("affected_paths")
                or (failure_evidence_pack.affected_paths if failure_evidence_pack is not None else ())
            )
            if str(path)
        )
        evidence = self._build_evidence(
            classification=diagnosis_data or classification,
            evidence_pack=failure_evidence_pack,
        )
        execution_status = self._execution_status(payload)
        pretty_missing = tuple(dict.fromkeys(self._humanize_missing_artifact(item) for item in missing_artifacts))
        safety_note = (
            "No patch was applied. Assistant cannot execute commands, apply changes, approve decisions, "
            "or bypass reviewer, approval, patch, validation, rollback, or proof gates."
        )
        answer = self._format_answer(
            failure_type=failure_type,
            root_cause=root_cause,
            confidence=confidence,
            evidence=evidence,
            execution_status=execution_status,
            affected_paths=affected_paths,
            recommended_next_step=recommended_next_step,
            missing_artifacts=pretty_missing,
            safety_note=safety_note,
            proposal_status=self._proposal_status_note(
                proposal_data=proposal_data,
                reviewer_data=reviewer_data,
                governed_status=governed_status,
            ),
            existing_message_text=existing_message_text,
        )
        return V2AssistantFailureAnswer(
            failure_type=failure_type,
            root_cause=root_cause,
            confidence=confidence,
            evidence=evidence,
            affected_paths=affected_paths,
            recommended_next_step=recommended_next_step,
            missing_artifacts=pretty_missing,
            safety_note=safety_note,
            answer=answer,
        )

    def _build_evidence(
        self,
        *,
        classification: dict[str, Any],
        evidence_pack: FailureEvidencePack | None,
    ) -> tuple[dict[str, str], ...]:
        items: list[dict[str, str]] = []
        raw = classification.get("evidence")
        if isinstance(raw, list):
            for item in raw[:_MAX_EVIDENCE_ITEMS]:
                if not isinstance(item, dict):
                    continue
                items.append(
                    {
                        "source": str(item.get("source", "")),
                        "label": str(item.get("label", "")),
                        "text": self._bounded_text(str(item.get("text", "")), 220),
                    }
                )
        elif evidence_pack is not None:
            for snippet in evidence_pack.snippets[:_MAX_EVIDENCE_ITEMS]:
                items.append(
                    {
                        "source": snippet.source,
                        "label": snippet.label,
                        "text": self._bounded_text(snippet.text, 220),
                    }
                )
        return tuple(item for item in items if item["text"])

    def _format_answer(
        self,
        *,
        failure_type: str,
        root_cause: str,
        confidence: str,
        evidence: tuple[dict[str, str], ...],
        execution_status: str,
        affected_paths: tuple[str, ...],
        recommended_next_step: str,
        missing_artifacts: tuple[str, ...],
        safety_note: str,
        proposal_status: str,
        existing_message_text: str,
    ) -> str:
        evidence_lines = (
            "; ".join(
                f"{item['label'] or item['source']}: {item['text']}"
                for item in evidence
            )
            if evidence
            else "No concrete evidence snippets available."
        )
        affected = ", ".join(affected_paths) if affected_paths else "No affected paths identified yet."
        missing = "; ".join(missing_artifacts) if missing_artifacts else "No required failure artifacts are currently missing."
        answer = (
            f"Failure question: {self._bounded_text(existing_message_text, 160)}\n"
            f"Failure type: {failure_type}\n"
            f"Root cause: {root_cause}\n"
            f"Confidence: {confidence}\n"
            f"Execution status: {execution_status}\n"
            f"Evidence: {evidence_lines}\n"
            f"Affected paths: {affected}\n"
            f"Missing artifacts: {missing}\n"
            f"Recommended next step: {recommended_next_step}\n"
            f"Proposal status: {proposal_status}\n"
            f"Safety: {safety_note}"
        )
        return self._bounded_text(answer, _MAX_ANSWER_CHARS)

    def _execution_status(self, payload: dict[str, Any]) -> str:
        for key in ("build_status", "final_status", "transform_status", "test_status"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return "unknown"

    def _infer_run_dir(
        self,
        *,
        payload: dict[str, Any],
        artifact_refs: dict[str, Any],
    ) -> str | None:
        for key in ("run_dir", "run_path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value

        candidates = [str(value) for value in artifact_refs.values() if isinstance(value, str) and value.strip()]
        for raw in candidates:
            path = Path(raw)
            if fnmatch(path.name, "build-error*.json") or path.name in {
                "phase2_transform.log",
                "orchestration_summary.json",
                "test_agent.log",
            }:
                return self._run_root_from_known_path(path)
        for raw in candidates:
            path = Path(raw)
            if path.is_absolute():
                return self._run_root_from_known_path(path)
        sandbox_path = payload.get("sandbox_path")
        if isinstance(sandbox_path, str) and sandbox_path.strip():
            return self._run_root_from_known_path(Path(sandbox_path))
        return None

    def _run_root_from_known_path(self, path: Path) -> str:
        resolved = path.resolve()
        location = resolved if resolved.is_dir() else resolved.parent
        lowered = location.name.lower()
        if lowered in {"logs", "build", "orchestration"}:
            return str(location.parent)
        if lowered == "post_transform" and location.parent.name.lower() == "test":
            return str(location.parent.parent)
        if lowered == "sandbox" and location.parent.name.lower() == "workspaces":
            return str(location.parent.parent)
        if resolved.name == "pom.xml" and resolved.parent.name.lower() == "sandbox" and resolved.parent.parent.name.lower() == "workspaces":
            return str(resolved.parent.parent.parent)
        return str(location)

    def _humanize_missing_artifact(self, artifact: str) -> str:
        mapping = {
            "build-error*.json": "no build-error artifact found",
            "phase2_transform.log": "no phase2_transform.log found",
            "orchestration_summary.json": "no orchestration_summary.json found",
            "test_agent.log": "no test_agent.log found",
            "pom.xml": "no sandbox pom.xml available",
            "failed_event_payload": "no failed event payload available",
            "artifact_ref:orchestration_summary": "no orchestration_summary artifact found",
        }
        return mapping.get(artifact, f"missing artifact: {artifact}")

    def _bounded_text(self, value: str, limit: int) -> str:
        clean = _SECRET_VALUE_RE.sub("[REDACTED]", str(value or ""))
        clean = redact_model_summary(clean).strip()
        if len(clean) <= limit:
            return clean
        return clean[:limit] + "...[truncated]"

    def _proposal_status_note(
        self,
        *,
        proposal_data: dict[str, Any],
        reviewer_data: dict[str, Any],
        governed_status: dict[str, Any],
    ) -> str:
        workflow_note = self._workflow_note(governed_status)
        if not proposal_data:
            base = "No governed repair proposal exists yet."
            return f"{base} {workflow_note}".strip()
        status = str(proposal_data.get("status") or "draft")
        decision = str(reviewer_data.get("decision") or proposal_data.get("reviewer_decision") or "").strip()
        if status in {"approved", "applied"}:
            if proposal_data.get("patch_candidate_status"):
                candidate_status = str(proposal_data.get("patch_candidate_status") or "")
                gate_status = str(proposal_data.get("patch_candidate_gate_status") or "unknown")
                gate_reason = str(proposal_data.get("patch_candidate_gate_reason") or "")
                result_summary = str(proposal_data.get("patch_candidate_result_summary") or "")
                rollback_status = str(proposal_data.get("patch_candidate_rollback_status") or "")
                validation_status = str(proposal_data.get("patch_candidate_validation_status") or "")
                if candidate_status == "applied":
                    base = (
                        "Sandbox patch was applied and validation passed. "
                        "Legacy source was not modified."
                    )
                    return f"{base} {workflow_note}".strip()
                if candidate_status == "rolled_back":
                    base = (
                        "Patch was attempted in sandbox, validation failed, and rollback happened. "
                        "Legacy source was not modified."
                    )
                    return f"{base} {workflow_note}".strip()
                if candidate_status == "gate_blocked_at_apply":
                    reason = gate_reason or result_summary or "governed apply gate blocked the patch candidate"
                    base = (
                        f"Patch candidate apply was blocked. Reason: {reason}. "
                        "Patch was not applied."
                    )
                    return f"{base} {workflow_note}".strip()
                base = (
                    "Exact patch candidate is prepared and awaiting operator review/apply phase. "
                    f"Patch gate status is {gate_status}. "
                    "Patch was not applied."
                )
                return f"{base} {workflow_note}".strip()
            base = (
                "Proposal is approved but patch candidate has not been prepared. "
                "No patch was applied."
            )
            return f"{base} {workflow_note}".strip()
        if status == "draft" and decision == "accept":
            base = (
                "A reviewed proposal is available and awaits human approval. "
                "No patch was applied."
            )
            return f"{base} {workflow_note}".strip()
        if decision:
            base = (
                f"Proposal exists with status {status}; reviewer decision is {decision}. "
                "This does not approve or apply anything. Human approval is still required before any future application."
            )
            return f"{base} {workflow_note}".strip()
        base = (
            f"Proposal exists with status {status}. No patch was applied, and human approval would still be required before any future application."
        )
        return f"{base} {workflow_note}".strip()

    def _workflow_note(self, governed_status: dict[str, Any]) -> str:
        next_action = str(governed_status.get("next_action") or "").strip()
        stage_index = governed_status.get("stage_index")
        if not next_action:
            return ""
        if isinstance(stage_index, int):
            return f"Current governed stage: {stage_index}. Next action: {next_action}."
        return f"Next action: {next_action}."
