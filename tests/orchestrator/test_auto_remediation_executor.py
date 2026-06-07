from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import yaml

from migration_factory.contracts.migration import initialize_ledger, load_ledger
from migration_factory.remediation import execute_auto_remediation_loop, load_llm_policy


def _prepare_state(tmp_path: Path, *, unit_id: str = "spring-boot-3-5-14") -> tuple[dict, Path]:
    run_dir = tmp_path / "run"
    sandbox = run_dir / "workspaces" / "sandbox"
    ledger_file = sandbox / ".migration" / "ledger.json"
    sandbox.mkdir(parents=True, exist_ok=True)
    initialize_ledger(
        ledger_file,
        migration_id="run-001",
        migration_name="test",
        total_units=1,
        target_path=sandbox,
    )
    state = {
        "run_id": "run-001",
        "run_dir": str(run_dir),
        "ai_hub_path": str(tmp_path / "ai-hub"),
        "profile_id": "springboot-2.1-to-3.5-java17",
        "current_unit": unit_id,
        "final_status": "BUILD_FAILED_IN_SANDBOX",
        "build_status": "BUILD_FAILED_IN_SANDBOX",
        "test_status": "",
        "artifact_refs": {
            "migration_ledger": str(ledger_file),
            "migration_plan": str(run_dir / "planning" / "migration_plan.yaml"),
        },
    }
    return state, ledger_file


def test_behavioral_failure_does_not_auto_apply(tmp_path: Path) -> None:
    state, ledger_file = _prepare_state(tmp_path)
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")
    classification = {
        "category_counts": {"HTTP_STATUS_CONTRACT_DRIFT": 2},
        "failures": [
            {
                "test_class": "com.example.MvcTest",
                "test_method": "requestMethodNotSupported",
                "category": "HTTP_STATUS_CONTRACT_DRIFT",
                "symptom": "expected 404 but was 405",
            }
        ],
    }
    rerun_calls = {"count": 0}

    def _rerun() -> SimpleNamespace:
        rerun_calls["count"] += 1
        return SimpleNamespace(succeeded=False, error_contract_path=None)

    result = execute_auto_remediation_loop(
        state=state,
        run_dir=Path(state["run_dir"]),
        sandbox_path=Path(state["run_dir"]) / "workspaces" / "sandbox",
        ledger_file=ledger_file,
        llm_policy=policy,
        build_error_contract={"result_kind": "unknown_failure", "unit_id": state["current_unit"]},
        failure_classification=classification,
        rerun_validation=_rerun,
    )

    payload = yaml.safe_load(result.remediation_plan_path.read_text(encoding="utf-8"))
    attempts = json.loads(result.remediation_attempts_path.read_text(encoding="utf-8"))
    assert rerun_calls["count"] == 0
    assert result.continued is False
    assert payload["remediation_decision"] == "LLM_DISABLED_REPORT_ONLY"
    assert attempts["attempts"] == []


def test_deterministic_safelisted_candidate_can_apply_and_rerun(tmp_path: Path) -> None:
    state, ledger_file = _prepare_state(tmp_path)
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")
    rerun_calls = {"count": 0}

    def _rerun() -> SimpleNamespace:
        rerun_calls["count"] += 1
        return SimpleNamespace(succeeded=True, error_contract_path=None)

    result = execute_auto_remediation_loop(
        state=state,
        run_dir=Path(state["run_dir"]),
        sandbox_path=Path(state["run_dir"]) / "workspaces" / "sandbox",
        ledger_file=ledger_file,
        llm_policy=policy,
        build_error_contract={
            "result_kind": "dependency_error",
            "message": "Could not resolve artifact",
            "unit_id": state["current_unit"],
        },
        failure_classification=None,
        rerun_validation=_rerun,
    )

    payload = yaml.safe_load(result.remediation_plan_path.read_text(encoding="utf-8"))
    attempts = json.loads(result.remediation_attempts_path.read_text(encoding="utf-8"))
    ledger = load_ledger(ledger_file)
    assert rerun_calls["count"] == 1
    assert result.continued is True
    assert payload["auto_remediation"]["attempts_made"] == 1
    assert attempts["attempts"][0]["deterministic_rule"] == "align_dependency_versions"
    assert attempts["attempts"][0]["status"] == "rerun_passed"
    assert ledger["remediation_attempts"][0]["status"] == "rerun_passed"


def test_same_rule_not_applied_twice_for_same_unit(tmp_path: Path) -> None:
    state, ledger_file = _prepare_state(tmp_path)
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")
    failure_contract_path = Path(state["run_dir"]) / "build-error.json"
    failure_contract_path.write_text(
        json.dumps(
            {
                "result_kind": "dependency_error",
                "message": "Could not resolve artifact",
                "unit_id": state["current_unit"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rerun_calls = {"count": 0}

    def _rerun() -> SimpleNamespace:
        rerun_calls["count"] += 1
        return SimpleNamespace(succeeded=False, error_contract_path=failure_contract_path)

    first = execute_auto_remediation_loop(
        state=state,
        run_dir=Path(state["run_dir"]),
        sandbox_path=Path(state["run_dir"]) / "workspaces" / "sandbox",
        ledger_file=ledger_file,
        llm_policy=policy,
        build_error_contract={
            "result_kind": "dependency_error",
            "message": "Could not resolve artifact",
            "unit_id": state["current_unit"],
        },
        failure_classification=None,
        rerun_validation=_rerun,
    )
    second = execute_auto_remediation_loop(
        state=state,
        run_dir=Path(state["run_dir"]),
        sandbox_path=Path(state["run_dir"]) / "workspaces" / "sandbox",
        ledger_file=ledger_file,
        llm_policy=policy,
        build_error_contract={
            "result_kind": "dependency_error",
            "message": "Could not resolve artifact",
            "unit_id": state["current_unit"],
        },
        failure_classification=None,
        rerun_validation=_rerun,
    )

    attempts = json.loads(first.remediation_attempts_path.read_text(encoding="utf-8"))
    assert rerun_calls["count"] == 1
    assert first.continued is False
    assert second.continued is False
    assert second.rerun_called is False
    assert len(attempts["attempts"]) == 1


def test_attempt_limit_is_enforced(tmp_path: Path) -> None:
    state, ledger_file = _prepare_state(tmp_path)
    policy = load_llm_policy(tmp_path / "missing-hub", "missing-profile")
    remediation_dir = Path(state["run_dir"]) / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)
    attempts_path = remediation_dir / "remediation_attempts.json"
    attempts_path.write_text(
        json.dumps(
            {
                "run_id": state["run_id"],
                "failed_unit": state["current_unit"],
                "max_auto_remediation_attempts_per_unit": 3,
                "attempts": [
                    {"status": "rerun_failed", "deterministic_rule": "rule-a"},
                    {"status": "rerun_failed", "deterministic_rule": "rule-b"},
                    {"status": "rerun_failed", "deterministic_rule": "rule-c"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    rerun_calls = {"count": 0}

    def _rerun() -> SimpleNamespace:
        rerun_calls["count"] += 1
        return SimpleNamespace(succeeded=True, error_contract_path=None)

    result = execute_auto_remediation_loop(
        state=state,
        run_dir=Path(state["run_dir"]),
        sandbox_path=Path(state["run_dir"]) / "workspaces" / "sandbox",
        ledger_file=ledger_file,
        llm_policy=policy,
        build_error_contract={
            "result_kind": "dependency_error",
            "message": "Could not resolve artifact",
            "unit_id": state["current_unit"],
        },
        failure_classification=None,
        rerun_validation=_rerun,
    )

    payload = yaml.safe_load(result.remediation_plan_path.read_text(encoding="utf-8"))
    assert rerun_calls["count"] == 0
    assert result.continued is False
    assert "max_auto_remediation_attempts_per_unit=3" in payload["auto_remediation"]["stopped_reason"]
