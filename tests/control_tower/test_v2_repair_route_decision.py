from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from typing import Any

import pytest

from migration_factory.control_tower.application import v2_repair_route_decision as route_decision
from migration_factory.control_tower.application.v2_repair_route_decision import (
    RepairRouteDecision,
    emit_repair_route_decision,
    select_repair_route_decision,
)


CHECKSUM = "sha256:" + "a" * 64
CONTEXT = "sha256:" + "b" * 64
BASE = "sha256:" + "c" * 64


def _classification(
    *,
    status: str = "known_family_candidate",
    family: str = "INITMOCKS_TO_OPENMOCKS_CANDIDATE",
    failure_type: str | None = None,
    missing: tuple[str, ...] = (),
    gate: str = "future_deterministic_candidate",
    evidence_status: str = "collected",
    usable_artifacts: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "classification_status": status,
        "failure_type": failure_type or family,
        "repair_family_candidate": family,
        "missing_required_evidence": list(missing),
        "governance_gate_type": gate,
        "evidence_status": evidence_status,
        "usable_artifacts": list(usable_artifacts or []),
    }


def _select(**overrides: Any) -> RepairRouteDecision:
    data = {
        "job_id": "job-1",
        "stage_index": 1,
        "command_id": "cmd-1",
        "classification": _classification(),
        "evidence_checksum": CHECKSUM,
        "context_checksum": CONTEXT,
        "base_repo_state_checksum": BASE,
        "attempt_number": 0,
        "max_attempts": 3,
        "available_evidence": ("test_source", "test_report"),
    }
    data.update(overrides)
    return select_repair_route_decision(**data)


def _events() -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = []

    def sink(**kwargs: Any) -> None:
        events.append(kwargs)

    return events, sink


def test_repair_route_decision_is_immutable() -> None:
    decision = _select()
    assert not hasattr(decision, "__dict__")
    with pytest.raises(FrozenInstanceError):
        decision.route = "blocked_unsupported"  # type: ignore[misc]


def test_deterministic_recipe_uses_authoritative_rule_id() -> None:
    decision = _select()
    assert decision.route == "deterministic_recipe"
    assert decision.reason == "deterministic_recipe_available"
    assert decision.deterministic_rule_id == "INITMOCKS_TO_OPENMOCKS"
    assert decision.llm_eligible is False


def test_llm_reviewed_unknown_route() -> None:
    decision = _select(
        classification=_classification(
            status="unknown",
            family="UNKNOWN_FAILURE",
            failure_type="unknown",
            gate="unknown",
        ),
        available_evidence=("build_error_contract", "test_report", "test_agent_log"),
    )
    assert decision.route == "llm_reviewed_unknown"
    assert decision.reason == "llm_unknown_eligible"
    assert decision.deterministic_rule_id is None
    assert decision.llm_eligible is True


@pytest.mark.parametrize(
    ("overrides", "route", "reason"),
    [
        ({"evidence_checksum": ""}, "blocked_missing_evidence", "missing_evidence_checksum"),
        ({"sensitive_scope_blocked": True}, "blocked_sensitive_scope", "sensitive_scope_blocked"),
        ({"toolchain_blocked": True}, "blocked_toolchain", "toolchain_blocked"),
        ({"attempt_number": 3, "max_attempts": 3}, "blocked_attempts_exhausted", "attempts_exhausted"),
        (
            {
                "classification": _classification(
                    status="unsupported_known_failure",
                    family="POWERMOCK_LEGACY_TEST_STRATEGY",
                    failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
                    gate="human_review_gate",
                ),
                "available_evidence": ("test_source", "test_report"),
            },
            "blocked_unsupported",
            "unsupported_known_failure",
        ),
        (
            {
                "classification": _classification(
                    family="NOT_REGISTERED_FAMILY",
                    failure_type="NOT_REGISTERED_FAMILY",
                ),
                "available_evidence": ("build_error_contract", "test_report", "test_agent_log"),
            },
            "blocked_unsupported",
            "family_not_registered",
        ),
        (
            {
                "classification": _classification(
                    family="POWERMOCK_LEGACY_TEST_STRATEGY",
                    failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
                    gate="future_deterministic_candidate",
                ),
                "available_evidence": ("pom_xml", "test_source_markers", "build_error_contract", "test_report"),
            },
            "blocked_unsupported",
            "backend_recipe_unavailable",
        ),
    ],
)
def test_blocked_routes(overrides: dict[str, Any], route: str, reason: str) -> None:
    decision = _select(**overrides)
    assert decision.route == route
    assert decision.reason == reason


def test_deterministic_family_without_authoritative_rule_id_is_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(route_decision, "_DETERMINISTIC_RULE_IDS", {})
    decision = _select()
    assert decision.route == "blocked_unsupported"
    assert decision.reason == "deterministic_rule_id_missing"
    assert decision.deterministic_rule_id is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"sensitive_scope_blocked": True, "toolchain_blocked": True}, "blocked_sensitive_scope"),
        ({"toolchain_blocked": True, "attempt_number": 3, "max_attempts": 3}, "blocked_toolchain"),
        ({"attempt_number": 3, "max_attempts": 3, "evidence_checksum": ""}, "blocked_attempts_exhausted"),
        ({"evidence_checksum": ""}, "blocked_missing_evidence"),
        (
            {
                "classification": _classification(
                    status="unsupported_known_failure",
                    family="unknown",
                    failure_type="unknown",
                    gate="unknown",
                ),
                "available_evidence": ("build_error_contract", "test_report", "test_agent_log"),
            },
            "blocked_unsupported",
        ),
        (
            {
                "classification": _classification(
                    failure_type="INITMOCKS_TO_OPENMOCKS_CANDIDATE",
                    gate="unknown",
                ),
            },
            "blocked_unsupported",
        ),
    ],
)
def test_total_precedence(overrides: dict[str, Any], expected: str) -> None:
    decision = _select(**overrides)
    assert decision.route == expected


def test_attempt_limit_uses_zero_based_cycle_convention() -> None:
    assert _select(attempt_number=2, max_attempts=3).route == "deterministic_recipe"
    assert _select(attempt_number=3, max_attempts=3).route == "blocked_attempts_exhausted"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"attempt_number": None}, "invalid_attempt_binding:attempt_number"),
        ({"max_attempts": None}, "invalid_attempt_binding:max_attempts"),
        ({"attempt_number": -1}, "invalid_attempt_binding:attempt_number"),
        ({"max_attempts": 0}, "invalid_attempt_binding:max_attempts"),
        ({"attempt_number": True}, "invalid_attempt_binding:attempt_number"),
        ({"max_attempts": False}, "invalid_attempt_binding:max_attempts"),
    ],
)
def test_invalid_attempt_bindings_raise_without_fabricating_zero(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _select(**overrides)


def test_invalid_attempt_binding_emits_no_event() -> None:
    events, sink = _events()
    with pytest.raises(ValueError, match="invalid_attempt_binding:attempt_number"):
        decision = _select(attempt_number=None)
        emit_repair_route_decision(
            event_sink=sink,
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            decision=decision,
        )
    assert events == []


@pytest.mark.parametrize("stage_index", [None, 0, "1", True])
def test_invalid_stage_index_raises(stage_index: Any) -> None:
    with pytest.raises(ValueError, match="missing_required_correlation:stage_index"):
        _select(stage_index=stage_index)


def test_missing_policy_evidence_blocks_before_deterministic() -> None:
    decision = _select(available_evidence=("test_source",))
    assert decision.route == "blocked_missing_evidence"
    assert decision.reason == "missing_policy_evidence"


def test_classifier_style_usable_artifacts_strings_satisfy_policy_evidence() -> None:
    decision = _select(
        available_evidence=(),
        classification=_classification(usable_artifacts=["test_source", "test_report", 42, {}]),
    )
    assert decision.route == "deterministic_recipe"


def test_legacy_usable_artifacts_dicts_satisfy_policy_evidence() -> None:
    decision = _select(
        available_evidence=(),
        classification=_classification(
            usable_artifacts=[
                {"kind": "test_source", "ref": "ignored"},
                {"kind": "test_report", "internal_ref": "ignored"},
                {"bad": "item"},
                42,
            ],
        ),
    )
    assert decision.route == "deterministic_recipe"


def test_unknown_policy_without_reviewer_cannot_select_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    original = route_decision.repair_family_policy

    def fake_policy(family: str | None):
        policy = original(family)
        if family == "UNKNOWN_FAILURE":
            return replace(policy, llm_reviewer_required=False)
        return policy

    monkeypatch.setattr(route_decision, "repair_family_policy", fake_policy)
    decision = _select(
        classification=_classification(status="unknown", family="UNKNOWN_FAILURE", failure_type="unknown", gate="unknown"),
        available_evidence=("build_error_contract", "test_report", "test_agent_log"),
    )
    assert decision.route == "blocked_unsupported"
    assert decision.reason == "llm_unknown_policy_unavailable"
    assert decision.llm_eligible is False


def test_unknown_policy_not_applicable_to_stage_cannot_select_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    original = route_decision.repair_family_policy

    def fake_policy(family: str | None):
        policy = original(family)
        if family == "UNKNOWN_FAILURE":
            return replace(policy, stage_applicability=("stage_2",))
        return policy

    monkeypatch.setattr(route_decision, "repair_family_policy", fake_policy)
    decision = _select(
        classification=_classification(status="unknown", family="UNKNOWN_FAILURE", failure_type="unknown", gate="unknown"),
        available_evidence=("build_error_contract", "test_report", "test_agent_log"),
    )
    assert decision.route == "blocked_unsupported"
    assert decision.reason == "llm_unknown_stage_unsupported"
    assert decision.llm_eligible is False


def test_missing_correlation_raises_and_emits_no_event() -> None:
    events, sink = _events()
    with pytest.raises(ValueError, match="missing_required_correlation:job_id"):
        decision = _select(job_id="")
        emit_repair_route_decision(
            event_sink=sink,
            job_id="",
            stage_index=1,
            command_id="cmd-1",
            decision=decision,
        )
    assert events == []


def test_event_emitter_rejects_missing_correlation_and_emits_no_event() -> None:
    events, sink = _events()
    decision = _select()
    with pytest.raises(ValueError, match="missing_required_correlation:command_id"):
        emit_repair_route_decision(
            event_sink=sink,
            job_id="job-1",
            stage_index=1,
            command_id="",
            decision=decision,
        )
    assert events == []


@pytest.mark.parametrize(
    "decision",
    [
        _select(),
        _select(
            classification=_classification(status="unknown", family="UNKNOWN_FAILURE", failure_type="unknown", gate="unknown"),
            available_evidence=("build_error_contract", "test_report", "test_agent_log"),
        ),
    ],
)
def test_selected_routes_emit_selected_event(decision: RepairRouteDecision) -> None:
    events, sink = _events()
    emit_repair_route_decision(event_sink=sink, job_id="job-1", stage_index=1, command_id="cmd-1", decision=decision)
    assert len(events) == 1
    assert events[0]["event_type"] == "repair_route_selected"
    assert events[0]["status"] == "completed"


@pytest.mark.parametrize(
    "decision",
    [
        _select(evidence_checksum=""),
        _select(sensitive_scope_blocked=True),
        _select(toolchain_blocked=True),
        _select(attempt_number=3, max_attempts=3),
        _select(
            classification=_classification(
                status="unsupported_known_failure",
                family="POWERMOCK_LEGACY_TEST_STRATEGY",
                failure_type="POWERMOCK_LEGACY_TEST_STRATEGY",
                gate="human_review_gate",
            ),
            available_evidence=("test_source", "test_report"),
        ),
    ],
)
def test_blocked_routes_emit_blocked_event(decision: RepairRouteDecision) -> None:
    events, sink = _events()
    emit_repair_route_decision(event_sink=sink, job_id="job-1", stage_index=1, command_id="cmd-1", decision=decision)
    assert len(events) == 1
    assert events[0]["event_type"] == "repair_route_blocked"
    assert events[0]["status"] == "blocked"


def test_event_payload_is_allow_listed_and_safe() -> None:
    events, sink = _events()
    decision = _select()
    emit_repair_route_decision(event_sink=sink, job_id="job-1", stage_index=1, command_id="cmd-1", decision=decision)
    payload = events[0]["payload"]
    assert set(payload) <= {
        "job_id",
        "stage_index",
        "command_id",
        "route",
        "reason",
        "failure_type",
        "classification_status",
        "evidence_checksum",
        "context_checksum",
        "base_repo_state_checksum",
        "deterministic_rule_id",
        "llm_eligible",
        "attempt_number",
    }
    blob = json.dumps(payload, sort_keys=True)
    forbidden = (
        "sandbox_path",
        "legacy_path",
        "internal_ref",
        "stderr",
        "stdout",
        "prompt",
        "completion",
        "provider",
        "endpoint",
        "deployment",
        "argv",
        "SECRET=",
        "token",
        "diff",
        "source code",
        str(Path.cwd()),
    )
    for marker in forbidden:
        assert marker not in blob
    assert events[0]["message"] == "Repair route decision recorded."


def test_event_emitter_rejects_non_dict_redaction_result(monkeypatch: pytest.MonkeyPatch) -> None:
    events, sink = _events()
    decision = _select()
    monkeypatch.setattr(route_decision, "redact_public_value", lambda value: "not-a-dict")
    with pytest.raises(ValueError, match="repair_route_payload_redaction_failed"):
        emit_repair_route_decision(
            event_sink=sink,
            job_id="job-1",
            stage_index=1,
            command_id="cmd-1",
            decision=decision,
        )
    assert events == []


def test_selection_has_no_downstream_side_effect_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    forbidden = {
        "migration_factory.control_tower.application.v2_repair_proposer.propose_stage_repair",
        "migration_factory.control_tower.application.v2_repair_reviewer.review_stage_repair_draft",
        "migration_factory.control_tower.application.v2_llm_repair_shadow.run_llm_repair_shadow_trace",
        "migration_factory.control_tower.application.v2_repair_apply_candidate.create_repair_apply_candidate",
        "migration_factory.control_tower.application.v2_repair_apply_candidate.approve_repair_apply_candidate",
        "migration_factory.control_tower.application.v2_repair_apply_candidate.apply_approved_repair_candidate",
        "migration_factory.control_tower.application.v2_post_repair_verification.run_post_repair_verification",
        "migration_factory.orchestrator.repair_review_chain.produce_repair_review_chain",
    }

    def fail(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
        raise AssertionError("downstream side effect called")

    for target in forbidden:
        monkeypatch.setattr(target, fail)

    sandbox = tmp_path / "sandbox"
    legacy = tmp_path / "legacy"
    sandbox.mkdir()
    legacy.mkdir()
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    decision = _select()
    after = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert decision.route == "deterministic_recipe"
    assert before == after
