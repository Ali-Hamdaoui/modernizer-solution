from __future__ import annotations

import json
from pathlib import Path

from migration_factory.control_tower.application.v2_dual_model_invocation_audit import (
    V2DualModelInvocationAuditStore,
)
from migration_factory.control_tower.application.v2_dual_model_runtime import (
    MODEL_1_ROLE,
    MODEL_2_ROLE,
    ModelInvocationRequest,
    V2DualModelRuntimeService,
)


def _bundle() -> dict[str, object]:
    return {
        "run_id": "v2-demo-s2",
        "migration_status": "failed",
        "ai_supervision_status": "not_requested",
        "approval_state": "not_required",
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "",
        "final_proof_level": "not_verified",
        "latest_trustworthy_migration_event": {"type": "build_failed", "status": "failed"},
        "generated_artifact_refs": [{"label": "pom.xml", "path": "pom.xml"}],
        "failure_bundle": {
            "failure_type": "invalid_maven_wildcard_version",
            "root_cause": "Wildcard Maven versions in pom.xml.",
            "confidence": "high",
            "affected_paths": ["pom.xml"],
        },
        "next_operator_action": "review_failure_evidence",
        "read_only": True,
    }


def test_model1_invocation_trace_is_persisted(tmp_path: Path) -> None:
    trace_root = tmp_path / "run-root"
    store = V2DualModelInvocationAuditStore()
    service = V2DualModelRuntimeService(trace_store=store)

    result = service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize failure.",
            evidence_bundle=_bundle(),
            source_input="Why fail?",
            supervision_context="stage_2_failure_review",
            trace_root=str(trace_root),
            correlation_id="req-123",
        )
    )

    assert result.trace_artifact_refs
    request_path = trace_root / result.trace_artifact_refs["request"]
    result_path = trace_root / result.trace_artifact_refs["result"]
    combined_path = trace_root / result.trace_artifact_refs["combined"]
    assert request_path.is_file()
    assert result_path.is_file()
    assert combined_path.is_file()

    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    result_payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert request_payload["read_only"] is True
    assert request_payload["model_role"] == MODEL_1_ROLE
    assert request_payload["provider"] == "deterministic"
    assert request_payload["fallback_used"] is True
    assert request_payload["request_id"] == "req-123"
    assert request_payload["evidence_summary"]["failure_type"] == "invalid_maven_wildcard_version"
    assert result_payload["read_only"] is True
    assert result_payload["model_role"] == MODEL_1_ROLE
    assert result_payload["provider"] == "deterministic"
    assert result_payload["fallback_used"] is True
    assert result_payload["validation_status"] == "validated"
    assert result_payload["structured_output"]["root_cause"] == "Wildcard Maven versions in pom.xml."


def test_model2_invocation_trace_is_persisted_and_references_model1_output(tmp_path: Path) -> None:
    trace_root = tmp_path / "run-root"
    store = V2DualModelInvocationAuditStore()
    service = V2DualModelRuntimeService(trace_store=store)
    bundle = _bundle()

    model1 = service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize failure.",
            evidence_bundle=bundle,
            trace_root=str(trace_root),
            supervision_context="stage_2_failure_review",
        )
    )
    model2 = service.invoke_model_2(
        ModelInvocationRequest(
            role=MODEL_2_ROLE,
            objective="Verify summary.",
            evidence_bundle=bundle,
            model1_output=model1.structured_output,
            trace_root=str(trace_root),
            supervision_context="stage_2_failure_review",
        )
    )

    traces = store.list_traces(trace_root=trace_root)
    assert len(traces) == 2
    latest_model2 = store.latest_trace(trace_root=trace_root, model_role=MODEL_2_ROLE)
    assert latest_model2 is not None
    assert latest_model2.model_role == MODEL_2_ROLE
    assert latest_model2.read_only is True
    assert latest_model2.provider == "deterministic"
    assert latest_model2.fallback_used is True
    assert latest_model2.structured_output["verdict"] == "accepted"

    model2_request = json.loads((trace_root / model2.trace_artifact_refs["request"]).read_text(encoding="utf-8"))
    assert model2_request["model1_output"]["root_cause"] == "Wildcard Maven versions in pom.xml."
    assert model2_request["evidence_summary"]["run_id"] == "v2-demo-s2"


def test_trace_artifacts_can_be_loaded_for_run(tmp_path: Path) -> None:
    trace_root = tmp_path / "run-root"
    store = V2DualModelInvocationAuditStore()
    service = V2DualModelRuntimeService(trace_store=store)

    service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize failure.",
            evidence_bundle=_bundle(),
            trace_root=str(trace_root),
        )
    )

    traces = store.list_traces(trace_root=trace_root)
    assert len(traces) == 1
    assert traces[0].run_id == "v2-demo-s2"
    assert traces[0].artifact_refs["combined"].endswith("dual_model_invocation_trace.json")


def test_trace_persistence_failure_is_controlled(tmp_path: Path) -> None:
    class _BrokenTraceStore:
        def persist_trace(self, *, request, result):
            raise OSError("disk full")

    service = V2DualModelRuntimeService(trace_store=_BrokenTraceStore())

    result = service.invoke_model_1(
        ModelInvocationRequest(
            role=MODEL_1_ROLE,
            objective="Summarize failure.",
            evidence_bundle=_bundle(),
            trace_root=str(tmp_path / "run-root"),
        )
    )

    assert result.success is True
    assert result.structured_output["root_cause"] == "Wildcard Maven versions in pom.xml."
    assert "Invocation trace persistence failed; execution status unchanged." in result.warnings
    assert "trace_persist_failed:OSError" in result.errors
    assert result.trace_artifact_refs == {}
