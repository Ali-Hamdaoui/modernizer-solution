from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json

import yaml

from migration_factory.contracts.migration import LedgerError, load_ledger, record_remediation_attempt

from .agent import (
    AUTO_APPLY_DETERMINISTIC_CANDIDATE,
    RemediationPlanResult,
    generate_remediation_plan,
)
from .policy import LlmPolicy


DEFAULT_MAX_AUTO_REMEDIATION_ATTEMPTS_PER_UNIT = 3
SAFE_AUTO_REMEDIATION_CATEGORIES = {"DEPENDENCY_ALIGNMENT"}
SAFE_AUTO_REMEDIATION_RULES = {"align_dependency_versions"}
BEHAVIORAL_CATEGORIES = {
    "SPRING_MVC_EXCEPTION_HANDLER_BEHAVIOR_DRIFT",
    "HTTP_STATUS_CONTRACT_DRIFT",
    "JAKARTA_VALIDATION_HANDLER_MISMATCH",
    "MOCKITO_FINAL_CLASS_MOCKING_LIMITATION",
    "APPLICATION_BEHAVIOR_REGRESSION",
}


@dataclass(frozen=True)
class AutoRemediationLoopResult:
    remediation_plan_path: Path
    remediation_attempts_path: Path
    applied_attempts: int
    rerun_result: Any | None
    rerun_called: bool
    stop_reason: str
    continued: bool


def execute_auto_remediation_loop(
    *,
    state: dict[str, Any],
    run_dir: str | Path,
    sandbox_path: str | Path,
    ledger_file: str | Path,
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
    rerun_validation: Callable[[], Any],
    rule_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]] | None = None,
    max_attempts_per_unit: int = DEFAULT_MAX_AUTO_REMEDIATION_ATTEMPTS_PER_UNIT,
) -> AutoRemediationLoopResult:
    resolved_run_dir = Path(run_dir).expanduser().resolve()
    resolved_sandbox = Path(sandbox_path).expanduser().resolve()
    resolved_ledger = Path(ledger_file).expanduser().resolve()
    remediation_dir = resolved_run_dir / "remediation"
    remediation_dir.mkdir(parents=True, exist_ok=True)

    attempts_path = remediation_dir / "remediation_attempts.json"
    attempts_payload = _load_attempts_payload(
        attempts_path,
        run_id=str(state.get("run_id") or ""),
        unit_id=_failed_unit(state, build_error_contract, resolved_ledger),
        max_attempts=max_attempts_per_unit,
    )
    handlers = {**_default_rule_handlers(), **dict(rule_handlers or {})}
    current_contract = build_error_contract or {}
    current_classification = failure_classification or {}
    rerun_result: Any | None = None
    rerun_called = False
    stop_reason = ""

    while True:
        plan = _write_plan(
            state=state,
            remediation_dir=remediation_dir,
            llm_policy=llm_policy,
            build_error_contract=current_contract,
            failure_classification=current_classification,
            attempts_payload=attempts_payload,
            stop_reason=stop_reason,
        )
        safe_candidate = _next_safe_candidate(plan.payload, attempts_payload)
        applied_attempts = _applied_attempt_count(attempts_payload)
        if safe_candidate is None:
            stop_reason = stop_reason or "No safelisted deterministic remediation candidate available."
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=stop_reason,
            )
            _write_attempts_payload(attempts_path, attempts_payload)
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=applied_attempts,
                rerun_result=rerun_result,
                rerun_called=rerun_called,
                stop_reason=stop_reason,
                continued=False,
            )
        if applied_attempts >= max_attempts_per_unit:
            stop_reason = f"Reached max_auto_remediation_attempts_per_unit={max_attempts_per_unit}."
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=stop_reason,
            )
            _write_attempts_payload(attempts_path, attempts_payload)
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=applied_attempts,
                rerun_result=rerun_result,
                rerun_called=rerun_called,
                stop_reason=stop_reason,
                continued=False,
            )

        unit_id = str(safe_candidate.get("unit_id") or attempts_payload.get("failed_unit") or "")
        rule = str(safe_candidate.get("deterministic_rule") or "")
        handler = handlers.get(rule)
        if handler is None:
            stop_reason = f"No safelisted handler registered for deterministic rule: {rule}."
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=stop_reason,
            )
            _write_attempts_payload(attempts_path, attempts_payload)
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=applied_attempts,
                rerun_result=rerun_result,
                rerun_called=rerun_called,
                stop_reason=stop_reason,
                continued=False,
            )

        before_signature = _failure_signature(current_contract, current_classification)
        attempt_index = len(attempts_payload["attempts"]) + 1
        attempt = {
            "attempt_index": attempt_index,
            "unit_id": unit_id,
            "category": str(safe_candidate.get("category") or ""),
            "deterministic_rule": rule,
            "safe_to_auto_apply": True,
            "status": "applying",
            "failure_signature_before": before_signature,
        }
        try:
            handler_result = handler(
                {
                    "run_dir": resolved_run_dir,
                    "sandbox_path": resolved_sandbox,
                    "ledger_file": resolved_ledger,
                    "remediation_dir": remediation_dir,
                    "unit_id": unit_id,
                    "deterministic_rule": rule,
                    "category": attempt["category"],
                }
            ) or {}
            attempt["handler_result"] = handler_result
            attempt["status"] = "applied"
        except Exception as exc:  # pragma: no cover - defensive
            attempt["status"] = "apply_failed"
            attempt["error"] = str(exc)
            attempts_payload["attempts"].append(attempt)
            attempts_payload["stopped_reason"] = str(exc)
            _record_attempt(resolved_ledger, unit_id, attempt)
            _write_attempts_payload(attempts_path, attempts_payload)
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=str(exc),
            )
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=_applied_attempt_count(attempts_payload),
                rerun_result=rerun_result,
                rerun_called=rerun_called,
                stop_reason=str(exc),
                continued=False,
            )

        rerun_called = True
        rerun_result = rerun_validation()
        attempt["rerun_called"] = True
        attempt["rerun_succeeded"] = bool(getattr(rerun_result, "succeeded", False))
        current_contract = _read_optional_json(getattr(rerun_result, "error_contract_path", None)) or {}
        current_classification = _read_optional_json(current_contract.get("failure_classification_path")) or {}
        attempt["failure_signature_after"] = _failure_signature(current_contract, current_classification)
        attempt["status"] = "rerun_passed" if attempt["rerun_succeeded"] else "rerun_failed"
        attempts_payload["attempts"].append(attempt)
        attempts_payload["last_rerun_succeeded"] = attempt["rerun_succeeded"]
        _record_attempt(resolved_ledger, unit_id, attempt)
        _write_attempts_payload(attempts_path, attempts_payload)

        if attempt["rerun_succeeded"]:
            stop_reason = "Deterministic remediation rerun succeeded."
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=stop_reason,
            )
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=_applied_attempt_count(attempts_payload),
                rerun_result=rerun_result,
                rerun_called=True,
                stop_reason=stop_reason,
                continued=True,
            )

        if attempt["failure_signature_after"] == before_signature:
            stop_reason = "Rerun produced the same failure signature after deterministic remediation."
            plan = _write_plan(
                state=state,
                remediation_dir=remediation_dir,
                llm_policy=llm_policy,
                build_error_contract=current_contract,
                failure_classification=current_classification,
                attempts_payload=attempts_payload,
                stop_reason=stop_reason,
            )
            return AutoRemediationLoopResult(
                remediation_plan_path=plan.path,
                remediation_attempts_path=attempts_path,
                applied_attempts=_applied_attempt_count(attempts_payload),
                rerun_result=rerun_result,
                rerun_called=True,
                stop_reason=stop_reason,
                continued=False,
            )


def _write_plan(
    *,
    state: dict[str, Any],
    remediation_dir: Path,
    llm_policy: LlmPolicy,
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
    attempts_payload: dict[str, Any],
    stop_reason: str,
) -> RemediationPlanResult:
    result = generate_remediation_plan(
        state=state,
        output_dir=remediation_dir,
        llm_policy=llm_policy,
        build_error_contract=build_error_contract,
        failure_classification=failure_classification,
    )
    payload = dict(result.payload)
    payload["max_auto_remediation_attempts_per_unit"] = attempts_payload.get("max_auto_remediation_attempts_per_unit")
    payload["remediation_attempts_path"] = str(remediation_dir / "remediation_attempts.json")
    payload["auto_remediation"] = {
        "attempts_made": _applied_attempt_count(attempts_payload),
        "rerun_count": _rerun_count(attempts_payload),
        "stopped_reason": stop_reason,
    }
    result.path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return RemediationPlanResult(path=result.path, payload=payload)


def _next_safe_candidate(plan_payload: dict[str, Any], attempts_payload: dict[str, Any]) -> dict[str, Any] | None:
    if plan_payload.get("remediation_decision") != AUTO_APPLY_DETERMINISTIC_CANDIDATE:
        return None
    failed_unit = str(attempts_payload.get("failed_unit") or "")
    applied_rules = {
        str(item.get("deterministic_rule") or "")
        for item in attempts_payload.get("attempts", [])
        if str(item.get("unit_id") or "") == failed_unit and str(item.get("status") or "") in {"applied", "rerun_passed", "rerun_failed"}
    }
    for candidate in list(plan_payload.get("remediation_candidates", []) or []):
        category = str(candidate.get("category") or "")
        rule = str(candidate.get("deterministic_rule") or "")
        if not candidate.get("safe_to_auto_apply"):
            continue
        if not rule:
            continue
        if category in BEHAVIORAL_CATEGORIES:
            continue
        if category not in SAFE_AUTO_REMEDIATION_CATEGORIES:
            continue
        if rule not in SAFE_AUTO_REMEDIATION_RULES:
            continue
        if rule in applied_rules:
            return None
        candidate["unit_id"] = failed_unit
        return candidate
    return None


def _failure_signature(
    build_error_contract: dict[str, Any] | None,
    failure_classification: dict[str, Any] | None,
) -> str:
    category_counts = (failure_classification or {}).get("category_counts")
    if isinstance(category_counts, dict) and category_counts:
        return "categories:" + ",".join(f"{key}={category_counts[key]}" for key in sorted(category_counts))
    result_kind = str((build_error_contract or {}).get("result_kind") or "")
    matched_line = str((build_error_contract or {}).get("matched_line") or "")
    message = str((build_error_contract or {}).get("message") or "")
    return f"error:{result_kind}:{matched_line or message}"


def _default_rule_handlers() -> dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]]:
    return {"align_dependency_versions": _write_synthetic_dependency_alignment_marker}


def _write_synthetic_dependency_alignment_marker(context: dict[str, Any]) -> dict[str, Any]:
    marker = Path(context["remediation_dir"]) / f"{context['unit_id']}-{context['deterministic_rule']}.yaml"
    marker.write_text(
        yaml.safe_dump(
            {
                "type": "synthetic_deterministic_remediation",
                "unit_id": context["unit_id"],
                "deterministic_rule": context["deterministic_rule"],
                "category": context["category"],
                "sandbox_only": True,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return {"marker_path": str(marker)}


def _load_attempts_payload(
    path: Path,
    *,
    run_id: str,
    unit_id: str,
    max_attempts: int,
) -> dict[str, Any]:
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("run_id", run_id)
    payload.setdefault("failed_unit", unit_id)
    payload.setdefault("max_auto_remediation_attempts_per_unit", max_attempts)
    payload.setdefault("attempts", [])
    return payload


def _write_attempts_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _applied_attempt_count(payload: dict[str, Any]) -> int:
    return sum(
        1
        for item in payload.get("attempts", [])
        if str(item.get("status") or "") in {"applied", "rerun_passed", "rerun_failed"}
    )


def _rerun_count(payload: dict[str, Any]) -> int:
    return sum(1 for item in payload.get("attempts", []) if bool(item.get("rerun_called")))


def _record_attempt(ledger_file: Path, unit_id: str, attempt: dict[str, Any]) -> None:
    try:
        record_remediation_attempt(ledger_file, unit_id=unit_id, attempt=attempt)
    except LedgerError:
        return


def _failed_unit(state: dict[str, Any], build_error_contract: dict[str, Any] | None, ledger_file: Path) -> str:
    values = [state.get("current_unit"), (build_error_contract or {}).get("unit_id")]
    try:
        ledger = load_ledger(ledger_file)
    except LedgerError:
        ledger = {}
    values.append(ledger.get("blocked_unit"))
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _read_optional_json(path_like: Any) -> dict[str, Any] | None:
    path_text = str(path_like or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
