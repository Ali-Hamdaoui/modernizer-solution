from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from migration_factory.control_tower.adapters.fastapi.app import _safe_llm_repair_shadow_trace
from migration_factory.control_tower.application.v2_llm_repair_shadow import (
    run_llm_repair_shadow_trace,
)


FAMILY = "INITMOCKS_TO_OPENMOCKS_CANDIDATE"


@dataclass(frozen=True)
class _FakeModelResult:
    content: str
    provider: str = "fake"
    source: str = "fake"
    model_status: str = "live_ok"
    success: bool = True
    failure_reason: str = ""
    fallback_used: bool = False
    deployment: str = "shadow-deployment"
    endpoint_metadata: str = "endpoint_host=[redacted-endpoint]"


class _FakeShadowClient:
    provider = "fake"
    deployment = "shadow-deployment"
    endpoint_metadata = "endpoint_host=[redacted-endpoint]"

    def __init__(self, proposer_summary: str = "initMocks can be modernized.") -> None:
        self.proposer_summary = proposer_summary
        self.calls: list[dict[str, Any]] = []

    def answer_with_role(self, *, role: Any, prompt: str, fallback: str, **_: Any) -> _FakeModelResult:
        self.calls.append({"role": getattr(role, "value", str(role)), "prompt": prompt, "fallback": fallback})
        role_value = getattr(role, "value", str(role))
        if role_value == "reviewer":
            return _FakeModelResult(json.dumps({
                "status": "available",
                "role": "repair_reviewer",
                "verdict": "advisory_accept",
                "critique": "Bounded diff is reasonable; API key sk-abc123 must not leak.",
                "risks": ["AutoCloseable lifecycle still needs later human/backend gate."],
                "missing_evidence": [],
                "unsafe_assumptions": [],
                "recommended_next_action": "keep_non_actionable_until_future_gate",
                "confidence": "medium",
                "non_actionable": False,
                "apply_allowed": True,
                "approval_allowed": True,
                "downstream_start_allowed": True,
            }))
        return _FakeModelResult(json.dumps({
            "status": "available",
            "role": "repair_proposer",
            "summary": self.proposer_summary,
            "root_cause": "MockitoAnnotations.initMocks is legacy Mockito setup.",
            "repair_intent": "Replace initMocks with openMocks in test source.",
            "expected_change": "One test-local method call changes.",
            "affected_files": ["src/test/java/ExampleTest.java"],
            "risk_notes": ["No apply in R7E.2."],
            "missing_evidence": [],
            "confidence": "medium",
            "non_actionable": False,
            "apply_allowed": True,
            "approval_allowed": True,
            "downstream_start_allowed": True,
        }))


def _classification() -> dict[str, Any]:
    return {
        "stage_index": 2,
        "failure_type": FAMILY,
        "classification_status": "known_family_candidate",
        "governance_gate_type": "future_deterministic_candidate",
        "missing_required_evidence": [],
        "repair_enabled": False,
    }


def _stage_evidence() -> dict[str, Any]:
    return {
        "job_id": "job-shadow",
        "stage_index": 2,
        "evidence_pack_id": "stage-evidence-shadow",
        "evidence_pack_checksum": "sha256:evidence",
        "usable_artifacts": [{"kind": "test_source", "ref": "src/test/java/ExampleTest.java", "checksum": "sha256:file"}],
    }


def _memory() -> dict[str, Any]:
    return {
        "query_signature": "sha256:memory",
        "retrieved_case_ids": ["msa-utils-initmocks-to-openmocks"],
        "authority_level": "advisory_only",
        "repair_enabled": False,
        "memory_can_apply": False,
        "memory_can_approve": False,
        "memory_can_start_downstream": False,
        "top_match": {"memory_case_id": "msa-utils-initmocks-to-openmocks", "title": "initMocks to openMocks"},
    }


def _draft() -> dict[str, Any]:
    return {
        "proposal_status": "drafted_non_actionable",
        "supported_family": FAMILY,
        "target_files": ["src/test/java/ExampleTest.java"],
        "proposed_diff_preview": "-MockitoAnnotations.initMocks(this);\n+MockitoAnnotations.openMocks(this);",
        "proposed_diff_checksum": "sha256:diff",
        "proposal_checksum": "sha256:proposal",
        "apply_enabled": False,
        "approval_enabled": False,
        "repair_enabled": False,
        "downstream_start_allowed": False,
    }


def _review() -> dict[str, Any]:
    return {
        "review_status": "reviewed_non_actionable",
        "verdict": "accepted_for_future_apply_gate",
        "checksum_verification_status": "verified",
        "declared_diff_checksum": "sha256:diff",
        "recomputed_diff_checksum": "sha256:diff",
        "diff_checksum_match": True,
        "declared_proposal_checksum": "sha256:proposal",
        "recomputed_proposal_checksum": "sha256:proposal",
        "proposal_checksum_match": True,
        "review_checksum": "sha256:review",
        "apply_enabled": False,
        "approval_enabled": False,
        "repair_enabled": False,
        "downstream_start_allowed": False,
        "legacy_mutation_allowed": False,
    }


def _trace(client: Any | None = None, *, enabled: bool = False) -> dict[str, Any]:
    return run_llm_repair_shadow_trace(
        job_id="job-shadow",
        stage_index=2,
        classification=_classification(),
        stage_evidence=_stage_evidence(),
        migration_memory=_memory(),
        repair_proposal_draft=_draft(),
        repair_draft_review=_review(),
        llm_client=client,
        llm_shadow_enabled=enabled,
    )


def test_llm_shadow_trace_created_for_initmocks_with_fake_client() -> None:
    client = _FakeShadowClient()
    trace = _trace(client, enabled=True)
    assert trace["runtime_mode"] == "configured_llm_shadow_mode"
    assert trace["proposer_trace"]["llm_invoked"] is True
    assert trace["reviewer_trace"]["llm_invoked"] is True
    assert trace["proposer_trace"]["output"]["summary"] == "initMocks can be modernized."
    assert trace["reviewer_trace"]["output"]["verdict"] == "advisory_accept"
    assert len(client.calls) == 2


def test_missing_llm_config_produces_fallback_only_trace() -> None:
    trace = _trace()
    assert trace["runtime_mode"] == "fallback_only_mode"
    assert trace["trace_status"] == "fallback_used"
    assert trace["proposer_trace"]["fallback_used"] is True
    assert trace["reviewer_trace"]["fallback_used"] is True
    assert trace["fallback_trace"]["deterministic_gate_authority"] is True


def test_existing_model_role_metadata_is_visible_and_safe() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    metadata = trace["proposer_trace"]["model_metadata"]
    assert metadata["configuration_source"] == "existing_v2_model_role_router"
    assert metadata["provider"] == "fake"
    assert metadata["deployment"] == "shadow-deployment"
    assert "endpoint" in metadata["endpoint_metadata"]
    assert "sk-" not in json.dumps(trace)


def test_proposer_input_includes_evidence_memory_draft_and_checksum_metadata() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    preview = trace["proposer_trace"]["input_preview"]
    assert "stage-evidence-shadow" in preview
    assert "msa-utils-initmocks-to-openmocks" in preview
    assert "proposed_diff_checksum" in preview
    assert "checksum_verification" in preview


def test_proposer_and_reviewer_outputs_are_clamped_non_actionable() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    for role in ("proposer_trace", "reviewer_trace"):
        output = trace[role]["output"]
        assert output["non_actionable"] is True
        assert output["apply_allowed"] is False
        assert output["approval_allowed"] is False
        assert output["downstream_start_allowed"] is False
        assert trace[role]["schema_validation_status"] == "validated"


def test_reviewer_input_includes_proposer_output_and_checksum_context() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    preview = trace["reviewer_trace"]["input_preview"]
    assert "proposer_output" in preview
    assert "deterministic_reviewer" in preview
    assert "checksum_verification_status" in preview
    assert trace["reviewer_trace"]["input_checksum"].startswith("sha256:")


def test_reviewer_input_checksum_changes_when_proposer_output_changes() -> None:
    first = _trace(_FakeShadowClient("first proposer"), enabled=True)
    second = _trace(_FakeShadowClient("second proposer"), enabled=True)
    assert first["reviewer_trace"]["input_checksum"] != second["reviewer_trace"]["input_checksum"]


def test_combined_trace_checksum_changes_when_outputs_change() -> None:
    first = _trace(_FakeShadowClient("first proposer"), enabled=True)
    second = _trace(_FakeShadowClient("second proposer"), enabled=True)
    assert first["combined_llm_shadow_trace_checksum"] != second["combined_llm_shadow_trace_checksum"]


def test_fallback_deterministic_reviewer_remains_authoritative() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    assert trace["fallback_trace"]["deterministic_reviewer_verdict"] == "accepted_for_future_apply_gate"
    assert trace["fallback_trace"]["checksum_verification_status"] == "verified"
    assert trace["deterministic_gate_authority"] is True
    assert trace["llm_can_override_backend_gate"] is False


def test_llm_advisory_outputs_cannot_enable_apply_or_downstream() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    assert trace["llm_can_apply"] is False
    assert trace["llm_can_approve"] is False
    assert trace["llm_can_start_downstream"] is False
    assert trace["proposer_trace"]["output"]["apply_allowed"] is False
    assert trace["reviewer_trace"]["output"]["apply_allowed"] is False


def test_default_tests_make_no_live_network_call(monkeypatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise AssertionError("network call attempted")

    monkeypatch.setattr("urllib.request.urlopen", fail)
    trace = _trace()
    assert trace["runtime_mode"] == "fallback_only_mode"
    assert trace["proposer_trace"]["llm_invoked"] is False


def test_secrets_are_redacted_from_trace() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    body = json.dumps(trace)
    assert "sk-abc123" not in body
    assert "[redacted-token]" in body


def test_powermock_remains_human_gate_not_auto_repairable() -> None:
    trace = run_llm_repair_shadow_trace(
        job_id="job-power",
        stage_index=1,
        classification={
            "failure_type": "POWERMOCK_LEGACY_TEST_STRATEGY",
            "classification_status": "unsupported_known_failure",
            "governance_gate_type": "human_review_gate",
            "repair_enabled": False,
        },
        stage_evidence={"stage_index": 1, "evidence_pack_checksum": "sha256:evidence"},
        migration_memory={"query_signature": "sha256:memory", "authority_level": "advisory_only"},
        repair_proposal_draft={"proposal_status": "blocked_human_review_gate", "target_files": []},
        repair_draft_review={"verdict": "blocked", "checksum_verification_status": "not_applicable"},
        llm_client=_FakeShadowClient(),
        llm_shadow_enabled=True,
    )
    assert trace["fallback_trace"]["deterministic_reviewer_verdict"] == "blocked"
    assert trace["fallback_trace"]["deterministic_gate_authority"] is True
    assert trace["fallback_trace"]["apply_enabled"] is False


def test_no_sandbox_or_legacy_mutation_fields_are_enabled() -> None:
    trace = _trace(_FakeShadowClient(), enabled=True)
    assert "sandbox_mutated" not in json.dumps(trace)
    assert trace["fallback_trace"]["apply_enabled"] is False
    assert trace["fallback_trace"]["downstream_start_allowed"] is False


def test_browser_injected_llm_trace_is_sanitized_and_clamped() -> None:
    sanitized = _safe_llm_repair_shadow_trace({
        "trace_origin": "browser",
        "trace_status": "available",
        "runtime_mode": "configured_llm_shadow_mode",
        "proposer_trace": {
            "role": "repair_proposer",
            "llm_invoked": True,
            "output": {"apply_allowed": True, "approval_allowed": True, "downstream_start_allowed": True},
        },
        "reviewer_trace": {
            "role": "repair_reviewer",
            "llm_invoked": True,
            "output": {"verdict": "advisory_accept", "apply_allowed": True},
        },
        "llm_can_apply": True,
        "llm_can_approve": True,
        "llm_can_start_downstream": True,
        "llm_can_override_backend_gate": True,
    })
    assert sanitized is not None
    assert sanitized["trace_origin"] == ""
    assert sanitized["trace_status"] == "fallback_used"
    assert sanitized["runtime_mode"] == "fallback_only_mode"
    assert sanitized["llm_can_apply"] is False
    assert sanitized["llm_can_approve"] is False
    assert sanitized["llm_can_start_downstream"] is False
    assert sanitized["llm_can_override_backend_gate"] is False
    assert sanitized["proposer_trace"]["output"]["apply_allowed"] is False
    assert sanitized["reviewer_trace"]["output"]["apply_allowed"] is False
