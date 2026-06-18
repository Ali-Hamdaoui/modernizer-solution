from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

from migration_factory.control_tower.application.redaction import redact_model_summary
from migration_factory.control_tower.application.v2_failure_classifier_rules import classify_failure
from migration_factory.control_tower.application.v2_failure_evidence import (
    FailureEvidenceCollector,
    FailureEvidencePack,
    infer_stage_run_root,
)


_EVIDENCE_QUESTION_RE = re.compile(
    r"(?i)\b(what happened|current state|where are we|how did .* go|run summary|migration summary|qu['’]est-ce qui s['’]est pass[ée])\b"
)
_AI_EVENT_TYPES = {
    "model_invocation_started",
    "model_invocation_completed",
    "model_invocation_failed",
}
_MIGRATION_FAILURE_EVENT_TYPES = {
    "build_failed",
    "sandbox_transform_failed",
    "transform_failed",
    "test_failed",
    "stage_failed",
    "result_contract_failed",
}
_RUNNING_EVENT_TYPES = {
    "stage_started",
    "command_started",
    "sandbox_transform_started",
    "resume_started",
    "approval_resume_queued",
    "approval_completed",
    "build_started",
    "test_started",
    "final_report_started",
}
_BLOCKED_EVENT_TYPES = {"approval_required", "stage_blocked_for_approval"}
_QUEUE_EVENT_TYPES = {"stage_queued", "next_stage_queued"}
_MAX_EXCERPT_CHARS = 240
_MAX_ARTIFACT_REFS = 12
_MAX_FAILURE_EVENTS = 4
_MAX_SNIPPETS = 5
_MAVEN_COORD_RE = re.compile(r"\b[\w.\-]+:[\w.\-]+:(?:jar|pom):\d+\.\d+\.x\b")
_PROPERTY_RE = re.compile(r"\b(?:javax\.persistence\.version|javax\.servlet\.version)\b")


@dataclass(frozen=True)
class FailureEvidenceBundle:
    failure_type: str
    root_cause: str
    confidence: str
    failure_events: tuple[dict[str, Any], ...]
    missing_artifacts: tuple[str, ...]
    error_contracts: tuple[dict[str, str], ...]
    log_excerpts: tuple[dict[str, str], ...]
    pom_excerpts: tuple[dict[str, str], ...]
    affected_paths: tuple[str, ...]


@dataclass(frozen=True)
class RunEvidenceBundle:
    run_id: str
    stage_statuses: dict[str, str]
    migration_status: str
    ai_supervision_status: str
    approval_state: str
    final_status: str
    build_status: str
    test_status: str
    final_proof_level: str
    latest_trustworthy_migration_event: dict[str, Any]
    generated_artifact_refs: tuple[dict[str, str], ...]
    failure_events: tuple[dict[str, Any], ...]
    build_test_error_contracts: tuple[dict[str, str], ...]
    relevant_log_excerpts: tuple[dict[str, str], ...]
    pom_excerpts: tuple[dict[str, str], ...]
    deterministic_failure_classification: dict[str, Any] | None
    failure_bundle: FailureEvidenceBundle | None
    next_operator_action: str
    read_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class V2RunEvidenceBundleService:
    def __init__(
        self,
        *,
        evidence_collector: FailureEvidenceCollector | None = None,
    ) -> None:
        self._collector = evidence_collector or FailureEvidenceCollector()

    @staticmethod
    def is_evidence_question(text: str) -> bool:
        return bool(_EVIDENCE_QUESTION_RE.search(str(text or "")))

    def build_bundle(
        self,
        *,
        job_id: str,
        setup: Any,
        events: tuple[Any, ...],
        approvals: tuple[Any, ...],
        commands: tuple[Any, ...],
        persisted_diagnosis: dict[str, Any] | None = None,
    ) -> RunEvidenceBundle:
        ordered = tuple(sorted(events, key=lambda event: int(getattr(event, "sequence", 0) or 0)))
        stage_statuses = self._stage_statuses(ordered)
        latest_trustworthy = self._latest_trustworthy_event(ordered)
        approval_state = self._approval_state(approvals=approvals, events=ordered)
        final_status = self._latest_payload_value(ordered, "final_status")
        build_status = self._latest_payload_value(ordered, "build_status")
        test_status = self._latest_payload_value(ordered, "test_status")
        final_proof_level = self._latest_payload_value(ordered, "final_proof_level")
        artifact_refs = self._artifact_refs(setup=setup, commands=commands, events=ordered)
        migration_failures = tuple(
            self._event_dict(event)
            for event in ordered
            if self._is_migration_failure_event(event)
        )[-_MAX_FAILURE_EVENTS:]

        failure_bundle: FailureEvidenceBundle | None = None
        failure_classification: dict[str, Any] | None = None
        error_contracts: tuple[dict[str, str], ...] = ()
        log_excerpts: tuple[dict[str, str], ...] = ()
        pom_excerpts: tuple[dict[str, str], ...] = ()
        run_id = job_id

        latest_failure_event = self._latest_migration_failure_event(ordered)
        if latest_failure_event is not None:
            payload = self._event_payload(latest_failure_event)
            stage_artifacts = self._resolve_stage_artifacts(
                setup=setup,
                commands=commands,
                events=ordered,
                stage_index=getattr(latest_failure_event, "stage", None),
            )
            payload = self._merge_failure_payload(payload=payload, stage_artifacts=stage_artifacts)
            evidence_pack = self._collector.collect(
                run_id=str(stage_artifacts.get("run_id") or job_id),
                event_type=str(getattr(latest_failure_event, "type", "")),
                run_dir=stage_artifacts.get("run_dir"),
                sandbox_path=stage_artifacts.get("sandbox_path"),
                artifact_refs=payload.get("artifact_refs"),
                payload=payload,
            )
            run_id = str(stage_artifacts.get("run_id") or evidence_pack.run_id or job_id)
            failure_classification = self._classification(
                latest_failure_event=latest_failure_event,
                payload=payload,
                evidence_pack=evidence_pack,
                persisted_diagnosis=persisted_diagnosis,
            )
            error_contracts = self._contract_snippets(evidence_pack)
            log_excerpts = self._log_snippets(evidence_pack)
            pom_excerpts = self._pom_snippets(
                evidence_pack=evidence_pack,
                classification=failure_classification,
                payload=payload,
            )
            failure_bundle = FailureEvidenceBundle(
                failure_type=str(failure_classification.get("failure_type") or ""),
                root_cause=str(failure_classification.get("likely_root_cause") or ""),
                confidence=str(failure_classification.get("confidence") or "low"),
                failure_events=migration_failures,
                missing_artifacts=evidence_pack.missing_artifacts,
                error_contracts=error_contracts,
                log_excerpts=log_excerpts,
                pom_excerpts=pom_excerpts,
                affected_paths=tuple(
                    str(path)
                    for path in (
                        failure_classification.get("affected_paths")
                        or evidence_pack.affected_paths
                    )
                    if str(path)
                ),
            )

        migration_status = self._migration_status(
            stage_statuses=stage_statuses,
            approval_state=approval_state,
            migration_failures=migration_failures,
            final_status=final_status,
            build_status=build_status,
            test_status=test_status,
            final_proof_level=final_proof_level,
        )
        ai_supervision_status = self._ai_status(ordered=ordered, migration_status=migration_status)
        next_operator_action = self._next_operator_action(
            migration_status=migration_status,
            ai_supervision_status=ai_supervision_status,
            approval_state=approval_state,
            failure_bundle=failure_bundle,
        )

        return RunEvidenceBundle(
            run_id=run_id,
            stage_statuses=stage_statuses,
            migration_status=migration_status,
            ai_supervision_status=ai_supervision_status,
            approval_state=approval_state,
            final_status=final_status,
            build_status=build_status,
            test_status=test_status,
            final_proof_level=final_proof_level,
            latest_trustworthy_migration_event=latest_trustworthy,
            generated_artifact_refs=artifact_refs,
            failure_events=migration_failures,
            build_test_error_contracts=error_contracts,
            relevant_log_excerpts=log_excerpts,
            pom_excerpts=pom_excerpts,
            deterministic_failure_classification=failure_classification,
            failure_bundle=failure_bundle,
            next_operator_action=next_operator_action,
            read_only=True,
        )

    def render_answer(self, *, question: str, bundle: RunEvidenceBundle) -> str:
        stage_summary = ", ".join(
            f"Stage {stage}: {status}"
            for stage, status in sorted(
                ((int(key), value) for key, value in bundle.stage_statuses.items()),
                key=lambda item: item[0],
            )
        ) or "No stage status yet."
        latest = bundle.latest_trustworthy_migration_event
        latest_text = (
            f"{latest.get('type', 'none')} ({latest.get('status', 'unknown')})"
            if latest
            else "none"
        )
        artifact_names = ", ".join(ref["label"] for ref in bundle.generated_artifact_refs) or "none"
        lines = [
            f"Question: {self._bounded(question, 160)}",
            f"Migration status: {bundle.migration_status}",
            f"AI supervision status: {bundle.ai_supervision_status}",
            f"Approval state: {bundle.approval_state}",
            f"Stage statuses: {stage_summary}",
            f"Final status: {bundle.final_status or 'unknown'}",
            f"Build status: {bundle.build_status or 'unknown'}",
            f"Test status: {bundle.test_status or 'unknown'}",
            f"Final proof level: {bundle.final_proof_level or 'unknown'}",
            f"Latest trustworthy migration event: {latest_text}",
            f"Artifacts: {artifact_names}",
        ]
        if bundle.failure_bundle is not None:
            lines.extend([
                f"Root cause: {bundle.failure_bundle.root_cause}",
                f"Failure type: {bundle.failure_bundle.failure_type}",
                f"Confidence: {bundle.failure_bundle.confidence}",
            ])
            if bundle.failure_bundle.failure_events:
                lines.append(
                    "Failure events: "
                    + "; ".join(
                        f"{item['type']}: {item['message']}"
                        for item in bundle.failure_bundle.failure_events
                    )
                )
            if bundle.build_test_error_contracts:
                lines.append(
                    "Error contracts: "
                    + "; ".join(
                        f"{item['label']}: {item['text']}"
                        for item in bundle.build_test_error_contracts
                    )
                )
            if bundle.relevant_log_excerpts:
                lines.append(
                    "Log excerpts: "
                    + "; ".join(
                        f"{item['label']}: {item['text']}"
                        for item in bundle.relevant_log_excerpts
                    )
                )
            if bundle.pom_excerpts:
                lines.append(
                    "POM excerpts: "
                    + "; ".join(
                        f"{item['label']}: {item['text']}"
                        for item in bundle.pom_excerpts
                    )
                )
            if bundle.failure_bundle.missing_artifacts:
                lines.append(
                    "Missing artifacts: "
                    + "; ".join(bundle.failure_bundle.missing_artifacts)
                )
        elif bundle.ai_supervision_status == "unavailable_fallback":
            lines.append(
                "Root cause: Migration evidence shows completion. Only AI/model supervision is unavailable, so deterministic fallback is active."
            )
        elif bundle.approval_state == "pending_human_approval":
            lines.append("Root cause: Human approval is pending before backend execution may continue.")
        lines.append(f"Next operator action: {bundle.next_operator_action}")
        lines.append(
            "Safety: Read-only evidence only. No files modified, no commands executed, no approvals issued, no repairs applied."
        )
        return redact_model_summary("\n".join(lines)).strip()

    def _classification(
        self,
        *,
        latest_failure_event: Any,
        payload: dict[str, Any],
        evidence_pack: FailureEvidencePack,
        persisted_diagnosis: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(persisted_diagnosis, dict) and persisted_diagnosis.get("failure_type"):
            return {
                "failure_type": persisted_diagnosis.get("failure_type", ""),
                "likely_root_cause": persisted_diagnosis.get("likely_root_cause", ""),
                "confidence": persisted_diagnosis.get("confidence", "low"),
                "affected_paths": persisted_diagnosis.get("affected_paths", []),
            }
        return classify_failure(
            evidence_pack=evidence_pack,
            payload=payload,
            stage_index=int(getattr(latest_failure_event, "stage", 0) or 0),
            event_type=str(getattr(latest_failure_event, "type", "")),
        )

    def _stage_statuses(self, events: tuple[Any, ...]) -> dict[str, str]:
        grouped: dict[int, list[Any]] = {}
        for event in events:
            stage = getattr(event, "stage", None)
            if not isinstance(stage, int):
                continue
            grouped.setdefault(stage, []).append(event)
        result: dict[str, str] = {}
        for stage, stage_events in grouped.items():
            current = "pending"
            for event in stage_events:
                mapped = self._stage_status_from_event(
                    event_type=str(getattr(event, "type", "")),
                    event_status=str(getattr(event, "status", "")),
                )
                current = self._transition_stage_status(current, mapped)
            result[str(stage)] = current
        return result

    def _stage_status_from_event(self, *, event_type: str, event_status: str) -> str:
        if event_type in _AI_EVENT_TYPES:
            return "pending"
        if event_type == "stage_failed" or event_status == "failed":
            return "failed"
        if event_type == "stage_completed":
            return "completed"
        if event_type in _RUNNING_EVENT_TYPES or event_status == "running":
            return "running"
        if event_type in _BLOCKED_EVENT_TYPES or event_status == "blocked":
            return "blocked"
        if event_type in _QUEUE_EVENT_TYPES or event_status == "queued":
            return "queued"
        return "pending"

    def _transition_stage_status(self, current: str, mapped: str) -> str:
        if mapped == "failed":
            return "failed"
        if mapped == "completed":
            return "completed"
        if mapped == "running":
            return "running"
        if mapped == "blocked":
            return current if current in {"running", "completed", "failed"} else "blocked"
        if mapped == "queued":
            return current if current in {"running", "completed", "failed", "blocked"} else "queued"
        return current

    def _latest_trustworthy_event(self, events: tuple[Any, ...]) -> dict[str, Any]:
        for event in reversed(events):
            event_type = str(getattr(event, "type", ""))
            if event_type in _AI_EVENT_TYPES or event_type in {"stdout", "stderr"}:
                continue
            return self._event_dict(event)
        return {}

    def _approval_state(self, *, approvals: tuple[Any, ...], events: tuple[Any, ...]) -> str:
        pending = [card for card in approvals if str(getattr(card, "status", "")) == "pending"]
        if pending:
            return "pending_human_approval"
        approved = [card for card in approvals if str(getattr(card, "status", "")) == "approved"]
        if approved:
            return "approved"
        for event in reversed(events):
            event_type = str(getattr(event, "type", ""))
            if event_type in _BLOCKED_EVENT_TYPES:
                return "pending_human_approval"
            if event_type in {"approval_completed", "approval_resume_queued"}:
                return "approved"
        return "not_required"

    def _latest_payload_value(self, events: tuple[Any, ...], key: str) -> str:
        for event in reversed(events):
            payload = self._event_payload(event)
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return ""

    def _artifact_refs(
        self,
        *,
        setup: Any,
        commands: tuple[Any, ...],
        events: tuple[Any, ...],
    ) -> tuple[dict[str, str], ...]:
        refs: list[dict[str, str]] = []
        for event in events:
            if str(getattr(event, "type", "")) != "artifact_written":
                continue
            payload = self._event_payload(event)
            raw_ref = str(payload.get("relative_path") or payload.get("path") or "").strip()
            if not raw_ref:
                continue
            resolved = self._resolve_artifact_ref(raw_ref=raw_ref, setup=setup, commands=commands)
            refs.append(
                {
                    "artifact_kind": str(payload.get("artifact_kind") or "artifact"),
                    "label": Path(raw_ref).name or raw_ref.replace("\\", "/").split("/")[-1],
                    "path": self._display_path(resolved or raw_ref),
                }
            )
        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            key = (ref["artifact_kind"], ref["path"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ref)
        return tuple(deduped[-_MAX_ARTIFACT_REFS:])

    def _latest_migration_failure_event(self, events: tuple[Any, ...]) -> Any | None:
        for event in reversed(events):
            if self._is_migration_failure_event(event):
                return event
        return None

    def _is_migration_failure_event(self, event: Any) -> bool:
        event_type = str(getattr(event, "type", ""))
        event_status = str(getattr(event, "status", ""))
        if event_type in _AI_EVENT_TYPES:
            return False
        return event_type in _MIGRATION_FAILURE_EVENT_TYPES or event_status == "failed"

    def _merge_failure_payload(
        self,
        *,
        payload: dict[str, Any],
        stage_artifacts: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(payload)
        if stage_artifacts.get("run_dir") and not merged.get("run_dir"):
            merged["run_dir"] = str(stage_artifacts["run_dir"])
        if stage_artifacts.get("sandbox_path") and not merged.get("sandbox_path"):
            merged["sandbox_path"] = str(stage_artifacts["sandbox_path"])
        refs = merged.get("artifact_refs")
        merged_refs = dict(refs) if isinstance(refs, dict) else {}
        merged_refs.update(stage_artifacts.get("artifact_refs") or {})
        if merged_refs:
            merged["artifact_refs"] = merged_refs
        if stage_artifacts.get("command_id") and not merged.get("command_id"):
            merged["command_id"] = stage_artifacts["command_id"]
        return merged

    def _resolve_stage_artifacts(
        self,
        *,
        setup: Any,
        commands: tuple[Any, ...],
        events: tuple[Any, ...],
        stage_index: int | None,
    ) -> dict[str, Any]:
        run_root: Path | None = None
        sandbox_path: Path | None = None
        artifact_refs: dict[str, str] = {}
        for event in events:
            if str(getattr(event, "type", "")) != "artifact_written":
                continue
            if stage_index is not None and getattr(event, "stage", None) != stage_index:
                continue
            payload = self._event_payload(event)
            raw_ref = str(payload.get("relative_path") or payload.get("path") or "").strip()
            if not raw_ref:
                continue
            resolved = self._resolve_artifact_ref(raw_ref=raw_ref, setup=setup, commands=commands)
            if resolved is None:
                continue
            inferred = infer_stage_run_root(resolved)
            if inferred is not None:
                run_root = inferred
            artifact_kind = str(payload.get("artifact_kind") or "")
            artifact_refs[artifact_kind or Path(raw_ref).name] = str(resolved)
            if artifact_kind.lower() == "sandbox" and resolved.is_dir():
                sandbox_path = resolved
        if sandbox_path is None and run_root is not None:
            candidate = run_root / "workspaces" / "sandbox"
            if candidate.is_dir():
                sandbox_path = candidate
        if run_root is not None:
            known = {
                "phase2_transform.log": run_root / "logs" / "phase2_transform.log",
                "orchestration_summary.json": run_root / "orchestration" / "orchestration_summary.json",
                "test_agent.log": run_root / "test" / "post_transform" / "test_agent.log",
            }
            for key, path in known.items():
                if path.is_file():
                    artifact_refs.setdefault(key, str(path))
            build_dir = run_root / "build"
            if build_dir.is_dir():
                matches = sorted(build_dir.glob("build-error*.json"))
                if matches:
                    artifact_refs.setdefault("build_error", str(matches[-1]))
        command_id = ""
        for event in reversed(events):
            if stage_index is not None and getattr(event, "stage", None) != stage_index:
                continue
            payload = self._event_payload(event)
            candidate = str(payload.get("command_id") or "").strip()
            if candidate:
                command_id = candidate
                break
        if not command_id:
            for command in reversed(commands):
                if stage_index is not None and int(getattr(command, "stage_index", 0) or 0) != stage_index:
                    continue
                candidate = str(getattr(command, "command_id", "") or "").strip()
                if candidate:
                    command_id = candidate
                    break
        return {
            "run_dir": run_root,
            "run_id": run_root.name if run_root is not None else "",
            "sandbox_path": sandbox_path,
            "artifact_refs": artifact_refs,
            "command_id": command_id,
        }

    def _resolve_artifact_ref(self, *, raw_ref: str, setup: Any, commands: tuple[Any, ...]) -> Path | None:
        if self._is_unsafe_ref(raw_ref):
            return None
        relative_ref = Path(raw_ref)
        for base_root in self._artifact_base_roots(setup=setup, commands=commands):
            candidate = self._contained_existing_path(base_root, relative_ref)
            if candidate is not None:
                return candidate
        if raw_ref.replace("\\", "/").startswith(".migration/"):
            rest = Path(*Path(raw_ref).parts[1:])
            for base_root in self._artifact_base_roots(setup=setup, commands=commands):
                try:
                    migration_dirs = base_root.rglob(".migration") if base_root.is_dir() else ()
                    for migration_dir in migration_dirs:
                        candidate = self._contained_existing_path(migration_dir.parent, Path(".migration") / rest)
                        if candidate is not None:
                            return candidate
                except (OSError, ValueError):
                    continue
        return None

    def _artifact_base_roots(self, *, setup: Any, commands: tuple[Any, ...]) -> tuple[Path, ...]:
        roots: list[Path] = []

        def add(value: Any) -> None:
            text = str(value or "").strip()
            if not text:
                return
            path = Path(text)
            win_path = PureWindowsPath(text)
            if not (path.is_absolute() or win_path.is_absolute() or win_path.drive):
                return
            try:
                resolved = path.resolve(strict=False)
            except (OSError, RuntimeError, ValueError):
                return
            if resolved not in roots:
                roots.append(resolved)

        add(getattr(setup, "output_parent_path", ""))
        for command in commands:
            try:
                argv = json.loads(getattr(command, "argv_json", "") or "[]")
            except (json.JSONDecodeError, TypeError):
                argv = []
            if not isinstance(argv, list):
                continue
            for index, item in enumerate(argv):
                if str(item) == "--modernized" and index + 1 < len(argv):
                    add(argv[index + 1])
                if str(item) in {"--legacy", "--sandbox"} and index + 1 < len(argv):
                    add(argv[index + 1])
            try:
                result = json.loads(getattr(command, "result_json", "") or "{}")
            except (json.JSONDecodeError, TypeError):
                result = {}
            if isinstance(result, dict):
                add(result.get("sandbox_path"))
        return tuple(roots)

    def _contained_existing_path(self, base_root: Path, relative_ref: Path) -> Path | None:
        try:
            resolved_base = base_root.resolve(strict=False)
            candidate = (resolved_base / relative_ref).resolve(strict=True)
            candidate.relative_to(resolved_base)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return None
        return candidate

    def _is_unsafe_ref(self, ref: str) -> bool:
        if ref.startswith(("\\\\", "//")):
            return True
        path = Path(ref)
        win_path = PureWindowsPath(ref)
        if path.is_absolute() or win_path.is_absolute() or win_path.drive:
            return True
        return any(part == ".." for part in path.parts)

    def _contract_snippets(self, evidence_pack: FailureEvidencePack) -> tuple[dict[str, str], ...]:
        return tuple(
            self._snippet_dict(snippet)
            for snippet in evidence_pack.snippets
            if snippet.source in {"build_error_contract", "orchestration_summary.json", "test_agent.log"}
        )[:_MAX_SNIPPETS]

    def _log_snippets(self, evidence_pack: FailureEvidencePack) -> tuple[dict[str, str], ...]:
        return tuple(
            self._snippet_dict(snippet)
            for snippet in evidence_pack.snippets
            if snippet.label in {"phase2_transform.log", "stderr", "stdout_tail", "message"}
        )[:_MAX_SNIPPETS]

    def _pom_snippets(
        self,
        *,
        evidence_pack: FailureEvidencePack,
        classification: dict[str, Any] | None,
        payload: dict[str, Any],
    ) -> tuple[dict[str, str], ...]:
        failure_type = str((classification or {}).get("failure_type") or "")
        result_kind = str(payload.get("result_kind") or "")
        if failure_type not in {
            "invalid_maven_wildcard_version",
            "jakarta_migration_dependency_issue",
            "jakarta_namespace_issue",
        } and result_kind != "dependency_error":
            return ()
        return tuple(
            self._snippet_dict(snippet)
            for snippet in evidence_pack.snippets
            if snippet.label == "pom.xml"
        )[:2]

    def _snippet_dict(self, snippet: Any) -> dict[str, str]:
        raw_text = str(getattr(snippet, "text", ""))
        return {
            "source": str(getattr(snippet, "source", "")),
            "label": str(getattr(snippet, "label", "")),
            "text": self._bounded(self._compress_snippet_text(raw_text), _MAX_EXCERPT_CHARS),
        }

    def _compress_snippet_text(self, text: str) -> str:
        coords = _MAVEN_COORD_RE.findall(text)
        props = _PROPERTY_RE.findall(text)
        fragments: list[str] = []
        for item in coords:
            if item not in fragments:
                fragments.append(item)
        for item in props:
            if item not in fragments:
                fragments.append(item)
        if "BUILD_FAILED_IN_SANDBOX" in text and "BUILD_FAILED_IN_SANDBOX" not in fragments:
            fragments.append("BUILD_FAILED_IN_SANDBOX")
        if fragments:
            return "; ".join(fragments[:6])
        return text

    def _migration_status(
        self,
        *,
        stage_statuses: dict[str, str],
        approval_state: str,
        migration_failures: tuple[dict[str, Any], ...],
        final_status: str,
        build_status: str,
        test_status: str,
        final_proof_level: str,
    ) -> str:
        if approval_state == "pending_human_approval":
            return "approval_required"
        if migration_failures:
            return "failed"
        completed = any(status == "completed" for status in stage_statuses.values())
        proof_complete = final_proof_level.lower() in {"compiled", "verified", "proof_complete"}
        success_status = final_status in {"TRANSFORM_APPLIED_IN_SANDBOX", "BUILD_PASSED_IN_SANDBOX"}
        build_complete = build_status == "BUILD_PASSED_IN_SANDBOX"
        if completed or proof_complete or success_status or build_complete:
            if test_status == "PASS_WITH_WARNINGS":
                return "completed_with_warnings"
            return "completed"
        if any(status == "running" for status in stage_statuses.values()):
            return "running"
        return "pending"

    def _ai_status(self, *, ordered: tuple[Any, ...], migration_status: str) -> str:
        latest_ai = None
        for event in reversed(ordered):
            if str(getattr(event, "type", "")) in _AI_EVENT_TYPES:
                latest_ai = event
                break
        if latest_ai is None:
            return "not_requested"
        if str(getattr(latest_ai, "type", "")) == "model_invocation_failed":
            if migration_status in {"completed", "completed_with_warnings"}:
                return "unavailable_fallback"
            return "failed"
        if str(getattr(latest_ai, "type", "")) == "model_invocation_completed":
            return "available"
        return "running"

    def _next_operator_action(
        self,
        *,
        migration_status: str,
        ai_supervision_status: str,
        approval_state: str,
        failure_bundle: FailureEvidenceBundle | None,
    ) -> str:
        if approval_state == "pending_human_approval":
            return "human_approval_required"
        if migration_status == "failed":
            return "review_failure_evidence"
        if migration_status == "completed_with_warnings":
            return "inspect_warnings"
        if migration_status == "completed" and ai_supervision_status == "unavailable_fallback":
            return "migration_completed_ai_unavailable"
        if migration_status == "completed":
            return "completed"
        if failure_bundle is not None:
            return "review_failure_evidence"
        if migration_status == "running":
            return "wait_for_backend"
        return "inspect_event_stream"

    def _event_payload(self, event: Any) -> dict[str, Any]:
        try:
            payload = json.loads(getattr(event, "payload_json", "") or "{}")
        except (json.JSONDecodeError, TypeError):
            payload = {}
        return payload if isinstance(payload, dict) else {}

    def _event_dict(self, event: Any) -> dict[str, Any]:
        return {
            "stage": getattr(event, "stage", None),
            "type": str(getattr(event, "type", "")),
            "status": str(getattr(event, "status", "")),
            "message": self._bounded(str(getattr(event, "message", "")), _MAX_EXCERPT_CHARS),
            "created_at": str(getattr(event, "created_at", "")),
        }

    def _display_path(self, value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        path = Path(text)
        return path.name or text.replace("\\", "/").split("/")[-1]

    def _bounded(self, text: str, limit: int) -> str:
        return redact_model_summary(str(text or "")[:limit]).strip()
