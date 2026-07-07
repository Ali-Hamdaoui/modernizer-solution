from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application import v2_unknown_repair_review_chain as wf03a
from migration_factory.control_tower.application.v2_repair_route_decision import (
    RepairRouteDecision,
)
from migration_factory.repair_loop.failure_evidence import (
    FailureSource,
    build_failure_evidence,
)
from migration_factory.repair_loop.repair_context import build_repair_context_pack


def _evidence(**overrides: Any) -> Any:
    data = {
        "failure_source": FailureSource.BUILD,
        "job_id": "job-1",
        "stage_index": 1,
        "command_id": "cmd-1",
        "failure_summary": "Unknown build failure",
        "changed_files": ("src/main/java/App.java",),
        "source_profile": "java11",
        "target_profile": "java17",
    }
    data.update(overrides)
    return build_failure_evidence(**data)


def _context(evidence: Any, **overrides: Any) -> Any:
    data = {
        "failure_evidence": evidence,
        "job_id": evidence.job_id,
        "stage_index": evidence.stage_index,
        "command_id": evidence.command_id,
        "changed_files": evidence.changed_files,
        "source_profile": evidence.source_profile,
        "target_profile": evidence.target_profile,
        "cycle_number": 0,
        "max_cycles": 3,
    }
    data.update(overrides)
    return build_repair_context_pack(**data)


def _decision(evidence: Any, context: Any, **overrides: Any) -> RepairRouteDecision:
    data = {
        "route": "llm_reviewed_unknown",
        "reason": "llm_unknown_eligible",
        "failure_type": "unknown",
        "classification_status": "unknown",
        "evidence_checksum": evidence.content_checksum,
        "context_checksum": context.context_pack_checksum,
        "base_repo_state_checksum": context.base_repo_state_checksum,
        "deterministic_rule_id": None,
        "llm_eligible": True,
        "attempt_number": context.cycle_number,
    }
    data.update(overrides)
    return RepairRouteDecision(**data)


def _events() -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []

    def sink(**kwargs: Any) -> None:
        events.append(kwargs)

    return events, sink


def _accepted_chain(context: Any | None = None, **overrides: Any) -> dict[str, Any]:
    context = context or _context(_evidence())
    diff_checksum = "sha256:" + "3" * 64
    chain = {
        "reviewer_decision": "accept",
        "proposal_kind": "llm_repair_review",
        "context_pack_checksum": context.context_pack_checksum,
        "job_id": context.job_id,
        "stage_index": context.stage_index,
        "primary_output_checksum": "sha256:" + "1" * 64,
        "reviewer_output_checksum": "sha256:" + "2" * 64,
        "proposed_diff_checksum": diff_checksum,
        "raw_diff_bytes_checksum": diff_checksum,
        "final_reviewed_diff_checksum": diff_checksum,
        "final_artifact_checksum": "sha256:" + "4" * 64,
        "primary_deterministic_fallback_used": False,
        "reviewer_deterministic_fallback_used": False,
        "final_diff_ref": "C:/secret/path/final.diff",
        "primary_provider_source": "azure_should_not_emit",
        "proposer_invocation_id": "inv-secret",
    }
    chain.update(overrides)
    return {
        "artifact_refs": {"ignored": "C:/secret/path/final.diff"},
        "review_chain": chain,
    }


class Ledger:
    pass


_DEFAULT_LEDGER = object()
_DEFAULT_SINK = object()


def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    decision: RepairRouteDecision | None = None,
    evidence: Any | None = None,
    context: Any | None = None,
    producer: Any | None = None,
    ledger: Any | None = _DEFAULT_LEDGER,
    event_sink: Any | None = _DEFAULT_SINK,
    proposal_id: str | None = None,
    gate_id: str | None = None,
) -> Any:
    evidence = evidence or _evidence()
    context = context or _context(evidence)
    decision = decision or _decision(evidence, context)
    if producer is not None:
        monkeypatch.setattr(wf03a, "produce_repair_review_chain", producer)
    if event_sink is _DEFAULT_SINK:
        _, event_sink = _events()
    return wf03a.run_unknown_repair_review_chain(
        decision=decision,
        failure_evidence=evidence,
        context_pack=context,
        output_dir=tmp_path / "chain",
        model_client=object(),
        invocation_ledger=Ledger() if ledger is _DEFAULT_LEDGER else ledger,
        event_sink=event_sink,
        proposal_id=proposal_id,
        gate_id=gate_id,
    )


def test_llm_reviewed_unknown_calls_producer_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def producer(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _accepted_chain(kwargs["context_pack"])

    result = _run(monkeypatch, tmp_path, producer=producer)

    assert result.status == "completed"
    assert result.non_actionable is True
    assert len(calls) == 1
    assert calls[0]["attempt_number"] == 0
    assert calls[0]["proposal_id"] is None
    assert calls[0]["gate_id"] is None


@pytest.mark.parametrize(
    "route",
    [
        "deterministic_recipe",
        "blocked_missing_evidence",
        "blocked_sensitive_scope",
        "blocked_toolchain",
        "blocked_attempts_exhausted",
        "blocked_unsupported",
    ],
)
def test_non_unknown_routes_never_call_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, route: str) -> None:
    evidence = _evidence()
    context = _context(evidence)
    decision = _decision(
        evidence,
        context,
        route=route,
        llm_eligible=route == "llm_reviewed_unknown",
        deterministic_rule_id="RULE" if route == "deterministic_recipe" else None,
    )
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=decision,
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.status == "blocked"
    assert result.reason == "route_not_llm_reviewed_unknown"


def test_llm_eligible_false_never_calls_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence = _evidence()
    context = _context(evidence)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=_decision(evidence, context, llm_eligible=False),
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == "llm_not_eligible"


def test_deterministic_rule_id_never_calls_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence = _evidence()
    context = _context(evidence)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=_decision(evidence, context, deterministic_rule_id="RULE"),
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == "deterministic_rule_present"


def test_missing_event_sink_blocks_before_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **_: pytest.fail("producer called"),
        event_sink=None,
    )
    assert result.status == "blocked"
    assert result.reason == "event_sink_unavailable"


def test_started_event_sink_exception_blocks_before_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = 0

    def failing_sink(**_: Any) -> None:
        raise RuntimeError("raw sink failure")

    def producer(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _accepted_chain()

    result = _run(monkeypatch, tmp_path, producer=producer, event_sink=failing_sink)
    assert result.status == "blocked"
    assert result.reason == "event_sink_failed"
    assert calls == 0


def test_completed_event_sink_exception_prevents_completed_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    def sink(**kwargs: Any) -> None:
        events.append(kwargs["event_type"])
        if kwargs["event_type"] == "llm_review_chain_completed":
            raise RuntimeError("raw completion failure")

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
        event_sink=sink,
    )
    assert result.status == "blocked"
    assert result.reason == "event_sink_failed"
    assert events == ["llm_review_chain_started", "llm_review_chain_completed"]


@pytest.mark.parametrize(
    ("evidence_update", "reason"),
    [
        ({"job_id": ""}, "missing_failure_evidence_job_id"),
        ({"command_id": ""}, "missing_failure_evidence_command_id"),
        ({"stage_index": 0}, "invalid_failure_evidence_stage_index"),
        ({"stage_index": True}, "invalid_failure_evidence_stage_index"),
    ],
)
def test_invalid_failure_evidence_correlation_blocks_without_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    evidence_update: dict[str, Any],
    reason: str,
) -> None:
    events, sink = _events()
    evidence = replace(_evidence(), **evidence_update)
    context = _context(_evidence())
    decision = _decision(_evidence(), context)

    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=decision,
        producer=lambda **_: pytest.fail("producer called"),
        event_sink=sink,
    )
    assert result.status == "blocked"
    assert result.reason == reason
    assert result.job_id == evidence.job_id
    assert result.command_id == evidence.command_id
    assert result.stage_index == evidence.stage_index
    assert events == []


@pytest.mark.parametrize(
    ("context_update", "reason"),
    [
        ({"job_id": ""}, "missing_context_job_id"),
        ({"command_id": ""}, "missing_context_command_id"),
        ({"stage_index": 0}, "invalid_context_stage_index"),
        ({"stage_index": True}, "invalid_context_stage_index"),
    ],
)
def test_invalid_context_correlation_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    context_update: dict[str, Any],
    reason: str,
) -> None:
    evidence = _evidence()
    context = replace(_context(evidence), **context_update)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=_decision(evidence, context),
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == reason


@pytest.mark.parametrize(
    ("evidence_kwargs", "context_kwargs", "reason"),
    [
        ({"job_id": "job-a"}, {"job_id": "job-b"}, "job_id_mismatch"),
        ({"stage_index": 1}, {"stage_index": 2}, "stage_index_mismatch"),
        ({"command_id": "cmd-a"}, {"command_id": "cmd-b"}, "command_id_mismatch"),
    ],
)
def test_job_stage_command_mismatch_blocks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    evidence_kwargs: dict[str, Any],
    context_kwargs: dict[str, Any],
    reason: str,
) -> None:
    evidence = _evidence(**evidence_kwargs)
    context = _context(evidence, **context_kwargs)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=_decision(evidence, context),
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == reason


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda e, c, d: (replace(e, content_checksum=""), c, replace(d, evidence_checksum="")), "missing_failure_evidence_checksum"),
        (lambda e, c, d: (e, replace(c, context_pack_checksum=""), replace(d, context_checksum="")), "missing_context_checksum"),
        (lambda e, c, d: (e, replace(c, base_repo_state_checksum=""), replace(d, base_repo_state_checksum="")), "missing_base_repo_state_checksum"),
    ],
)
def test_missing_authoritative_checksums_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutator: Any,
    reason: str,
) -> None:
    evidence = _evidence()
    context = _context(evidence)
    decision = _decision(evidence, context)
    evidence, context, decision = mutator(evidence, context, decision)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=decision,
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == reason


@pytest.mark.parametrize(
    ("decision_update", "context_update", "reason"),
    [
        ({"attempt_number": True}, {}, "invalid_decision_attempt_number"),
        ({}, {"cycle_number": True}, "invalid_cycle_number"),
        ({}, {"max_cycles": True}, "invalid_max_cycles"),
        ({}, {"cycle_number": -1}, "invalid_cycle_number"),
        ({}, {"max_cycles": 0}, "invalid_max_cycles"),
        ({}, {"cycle_number": 3, "max_cycles": 3}, "attempts_exhausted"),
        ({"attempt_number": 1}, {}, "attempt_number_mismatch"),
    ],
)
def test_attempt_types_ranges_exhaustion_and_mismatch_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    decision_update: dict[str, Any],
    context_update: dict[str, Any],
    reason: str,
) -> None:
    evidence = _evidence()
    context = replace(_context(evidence), **context_update)
    decision = _decision(evidence, context, **decision_update)
    if context_update.get("cycle_number") == -1:
        decision = replace(decision, attempt_number=0)

    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=decision,
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == reason


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("evidence_checksum", "failure_evidence_checksum_mismatch"),
        ("context_checksum", "context_checksum_mismatch"),
        ("base_repo_state_checksum", "base_repo_state_checksum_mismatch"),
    ],
)
def test_decision_checksum_mismatches_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    evidence = _evidence()
    context = _context(evidence)
    result = _run(
        monkeypatch,
        tmp_path,
        evidence=evidence,
        context=context,
        decision=_decision(evidence, context, **{field: "sha256:" + "9" * 64}),
        producer=lambda **_: pytest.fail("producer called"),
    )
    assert result.reason == reason


def test_missing_invocation_ledger_blocks_before_producer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **_: pytest.fail("producer called"),
        ledger=None,
    )
    assert result.reason == "invocation_ledger_unavailable"


def test_started_emitted_immediately_before_producer_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events, sink = _events()
    order: list[str] = []

    def recorder(**kwargs: Any) -> None:
        order.append(kwargs["event_type"])
        sink(**kwargs)

    def producer(**kwargs: Any) -> dict[str, Any]:
        order.append("producer")
        return _accepted_chain(kwargs["context_pack"])

    result = _run(monkeypatch, tmp_path, producer=producer, event_sink=recorder)

    assert result.status == "completed"
    assert order[:2] == ["llm_review_chain_started", "producer"]
    assert [event["event_type"] for event in events] == [
        "llm_review_chain_started",
        "llm_review_chain_completed",
    ]


def test_producer_exception_constant_reason_and_no_exception_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events, sink = _events()

    def producer(**_: Any) -> dict[str, Any]:
        raise RuntimeError("reviewer reject fallback schema C:/secret/provider text")

    result = _run(monkeypatch, tmp_path, producer=producer, event_sink=sink)

    assert result.status == "blocked"
    assert result.reason == "review_chain_producer_failed"
    blob = json.dumps([result.__dict__ if hasattr(result, "__dict__") else {}, events], default=str)
    assert "reviewer reject fallback schema" not in blob
    assert [event["event_type"] for event in events] == [
        "llm_review_chain_started",
        "llm_review_chain_blocked",
    ]


@pytest.mark.parametrize(
    ("chain_update", "reason"),
    [
        ({"context_pack_checksum": "sha256:" + "9" * 64}, "review_chain_invalid_result"),
        ({"job_id": "job-other"}, "review_chain_invalid_result"),
        ({"stage_index": 2}, "review_chain_invalid_result"),
        ({"proposal_kind": "wrong_kind"}, "review_chain_invalid_result"),
        ({"primary_output_checksum": ""}, "review_chain_invalid_result"),
        ({"reviewer_output_checksum": ""}, "review_chain_invalid_result"),
        ({"proposed_diff_checksum": ""}, "review_chain_invalid_result"),
        ({"raw_diff_bytes_checksum": ""}, "review_chain_invalid_result"),
        ({"final_reviewed_diff_checksum": ""}, "review_chain_invalid_result"),
        ({"final_artifact_checksum": ""}, "review_chain_invalid_result"),
        ({"raw_diff_bytes_checksum": "sha256:" + "8" * 64}, "review_chain_invalid_result"),
        ({"primary_deterministic_fallback_used": True}, "review_chain_invalid_result"),
        ({"reviewer_deterministic_fallback_used": True}, "review_chain_invalid_result"),
        ({"reviewer_decision": "reject"}, "review_chain_invalid_result"),
    ],
)
def test_invalid_producer_outputs_emit_started_then_blocked(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    chain_update: dict[str, Any],
    reason: str,
) -> None:
    events, sink = _events()

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"], **chain_update),
        event_sink=sink,
    )

    assert result.status == "blocked"
    assert result.reason == reason
    assert [event["event_type"] for event in events] == [
        "llm_review_chain_started",
        "llm_review_chain_blocked",
    ]


def test_valid_producer_output_emits_started_then_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events, sink = _events()
    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
        event_sink=sink,
    )

    assert result.status == "completed"
    assert [event["event_type"] for event in events] == [
        "llm_review_chain_started",
        "llm_review_chain_completed",
    ]


def test_non_dictionary_redaction_fails_closed_and_does_not_emit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events, sink = _events()
    monkeypatch.setattr(wf03a, "redact_public_value", lambda value: "not-a-dict")

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
        event_sink=sink,
    )

    assert result.status == "blocked"
    assert result.reason == "event_payload_redaction_failed"
    assert events == []


def test_event_payload_allow_list_excludes_sensitive_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    events, sink = _events()

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
        event_sink=sink,
        proposal_id="proposal-1",
        gate_id="gate-1",
    )

    assert result.proposal_id == "proposal-1"
    assert result.gate_id == "gate-1"
    payload = events[-1]["payload"]
    assert set(payload) <= set(wf03a._ALLOWED_EVENT_PAYLOAD_KEYS)
    blob = json.dumps(payload, sort_keys=True)
    forbidden = (
        "path",
        "prompt",
        "completion",
        "provider",
        "endpoint",
        "environment",
        "secret",
        "log",
        "source code",
        "--- a/",
        "sandbox",
        "legacy",
        "C:/",
        "inv-secret",
        str(Path.cwd()),
    )
    for marker in forbidden:
        assert marker.lower() not in blob.lower()


def test_no_candidate_gate_policy_approval_apply_verification_or_downstream_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    forbidden = [
        "migration_factory.control_tower.application.v2_repair_apply_candidate.create_repair_apply_candidate",
        "migration_factory.control_tower.application.v2_repair_gate_service.V2RepairGateService.create_repair_gate_from_reviewed_chain",
        "migration_factory.repair_loop.patch_gate.evaluate_patch_proposal",
        "migration_factory.control_tower.application.v2_repair_apply_candidate.approve_repair_apply_candidate",
        "migration_factory.control_tower.application.v2_repair_apply_candidate.apply_approved_repair_candidate",
        "migration_factory.control_tower.application.v2_post_repair_verification.run_post_repair_verification",
    ]

    def fail(*_: Any, **__: Any) -> None:
        raise AssertionError("forbidden downstream function called")

    for target in forbidden:
        monkeypatch.setattr(target, fail, raising=False)

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
    )
    assert result.status == "completed"


def test_sandbox_and_legacy_dirs_remain_unchanged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy"
    sandbox.mkdir()
    legacy.mkdir()
    (sandbox / "keep.txt").write_text("sandbox", encoding="utf-8")
    (legacy / "keep.txt").write_text("legacy", encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for root in (sandbox, legacy)
        for path in root.rglob("*")
        if path.is_file()
    }

    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
    )

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_text(encoding="utf-8")
        for root in (sandbox, legacy)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert result.status == "completed"
    assert after == before


def test_optional_proposal_gate_correlations_preserved_and_not_fabricated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def producer(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _accepted_chain(kwargs["context_pack"])

    no_ids = _run(monkeypatch, tmp_path, producer=producer)
    with_ids = _run(
        monkeypatch,
        tmp_path,
        producer=producer,
        proposal_id="proposal-abc",
        gate_id="gate-abc",
    )

    assert no_ids.proposal_id is None
    assert no_ids.gate_id is None
    assert with_ids.proposal_id == "proposal-abc"
    assert with_ids.gate_id == "gate-abc"
    assert calls[0]["proposal_id"] is None
    assert calls[0]["gate_id"] is None
    assert calls[1]["proposal_id"] == "proposal-abc"
    assert calls[1]["gate_id"] == "gate-abc"


def test_result_contains_no_actionable_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = _run(
        monkeypatch,
        tmp_path,
        producer=lambda **kwargs: _accepted_chain(kwargs["context_pack"]),
    )
    payload = {
        name: getattr(result, name)
        for name in result.__dataclass_fields__  # type: ignore[attr-defined]
    }
    forbidden = (
        "approval",
        "apply",
        "sandbox_mutation",
        "patch_bytes",
        "artifact_ref",
        "candidate_id",
        "approval_id",
        "verification",
        "downstream",
    )
    blob = json.dumps(payload, sort_keys=True)
    assert result.non_actionable is True
    for marker in forbidden:
        assert marker not in blob
