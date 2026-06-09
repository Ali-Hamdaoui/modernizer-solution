from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from langgraph.types import Command

from migration_factory.orchestrator.checkpointing import default_checkpointer
from migration_factory.orchestrator import graph as graph_module
from migration_factory.orchestrator.phase_services import record_approval_decision_phase
from migration_factory.orchestrator.preflight import build_langgraph_config
from migration_factory.orchestrator.state import (
    APPROVAL_DECISION_VALUES,
    FULL_SANDBOX_MIGRATION_MODE,
    apply_copilot_config,
    parse_copilot_config_from_env,
)
from migration_factory.orchestrator.summary import finalize_orchestration_state
from migration_factory.orchestrator.timing import start_total_run_timing


class ResumeCliError(ValueError):
    """Raised when an orchestrator run cannot be resumed."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.orchestrator.resume",
        description="Resume a paused migration orchestration after human approval.",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--decision", required=True, choices=sorted(APPROVAL_DECISION_VALUES))
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--comments", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        result = resume_orchestration(
            run_id=args.run_id,
            run_dir=Path(args.run_dir),
            decision=args.decision,
            approved_by=args.approved_by,
            comments=args.comments,
        )
    except ResumeCliError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(_to_json_safe(result), indent=2, sort_keys=True))
    return 0


def resume_orchestration(
    *,
    run_id: str,
    run_dir: Path,
    decision: str,
    approved_by: str,
    comments: str = "",
) -> dict[str, Any]:
    if decision not in APPROVAL_DECISION_VALUES:
        raise ResumeCliError(f"Unsupported approval decision: {decision}")
    if not approved_by:
        raise ResumeCliError("--approved-by is required")

    resolved_run_dir = Path(run_dir).expanduser().resolve()
    explicit_recorded = _record_explicit_approval_decision(
        run_id=run_id,
        run_dir=resolved_run_dir,
        decision=decision,
        approved_by=approved_by,
        comments=comments,
    )
    config = build_langgraph_config(run_id)
    graph = graph_module.build_graph(checkpointer=default_checkpointer(resolved_run_dir))
    result = graph.invoke(
        Command(
            resume={
                "decision": decision,
                "approved_by": approved_by,
                "comments": comments,
            }
        ),
        config=config,
    )
    result = _normalize_resume_result(
        _with_explicit_run_paths(dict(result), resolved_run_dir),
        decision=decision,
        explicit_recorded=explicit_recorded,
    )
    start_total_run_timing(result)
    if decision != "approved" and not (resolved_run_dir / "approval" / "approval_decision.json").is_file():
        return finalize_orchestration_state(
            _normalize_resume_result(
                _resume_from_interrupt_snapshot(
                    run_id=run_id,
                    run_dir=resolved_run_dir,
                    decision=decision,
                    approved_by=approved_by,
                    comments=comments,
                ),
                decision=decision,
                explicit_recorded=explicit_recorded,
            )
        )
    if _resume_completed(result, resolved_run_dir):
        return finalize_orchestration_state(result)
    return finalize_orchestration_state(
        _normalize_resume_result(
            _resume_from_interrupt_snapshot(
                run_id=run_id,
                run_dir=resolved_run_dir,
                decision=decision,
                approved_by=approved_by,
                comments=comments,
            ),
            decision=decision,
            explicit_recorded=explicit_recorded,
        )
    )


def _resume_completed(result: dict[str, Any], run_dir: Path) -> bool:
    if result.get("approval_decision") not in APPROVAL_DECISION_VALUES:
        return False
    if not (run_dir / "approval" / "approval_decision.json").is_file():
        return False
    if result.get("approval_decision") == "approved":
        if result.get("mode") != FULL_SANDBOX_MIGRATION_MODE:
            return True
        return bool(result.get("transform_status"))
    return True


def _resume_from_interrupt_snapshot(
    *,
    run_id: str,
    run_dir: Path,
    decision: str,
    approved_by: str,
    comments: str,
) -> dict[str, Any]:
    snapshot_path = run_dir / "orchestration" / "approval_interrupt_state.json"
    if not snapshot_path.is_file():
        raise ResumeCliError(f"approval interrupt checkpoint not found: {snapshot_path}")
    state = json.loads(snapshot_path.read_text(encoding="utf-8"))
    start_total_run_timing(state)
    if state.get("run_id") != run_id:
        raise ResumeCliError("approval interrupt checkpoint run_id mismatch")
    state["run_dir"] = str(run_dir)
    state = _with_explicit_run_paths(state, run_dir)

    state.update(
        {
            "approval_status": "COMPLETED",
            "approval_decision": decision,
            "approved_by": approved_by,
            "approval_comments": comments,
            "current_phase": "approval",
            "stop_reason": f"Approval decision '{decision}' received; stopping.",
        }
    )
    if decision == "approved" and state.get("mode") == FULL_SANDBOX_MIGRATION_MODE:
        state["stop_reason"] = "Approval decision 'approved' received; continuing to sandbox transform."

    recorded = dict(state)
    recorded.update(record_approval_decision_phase(recorded))
    if decision != "approved" or recorded.get("errors"):
        return recorded
    if recorded.get("mode") != FULL_SANDBOX_MIGRATION_MODE:
        recorded["stop_reason"] = "Approval decision 'approved' recorded; stopping."
        return recorded

    transformed = dict(recorded)
    transformed.update(graph_module.run_sandbox_transform_phase(transformed))
    return transformed


def _record_explicit_approval_decision(
    *,
    run_id: str,
    run_dir: Path,
    decision: str,
    approved_by: str,
    comments: str,
) -> dict[str, Any]:
    state = _with_explicit_run_paths(
        {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "approval_decision": decision,
            "approved_by": approved_by,
            "approval_comments": comments,
            "artifact_refs": {},
        },
        run_dir,
    )
    recorded = record_approval_decision_phase(state)
    if recorded.get("errors"):
        raise ResumeCliError("; ".join(str(error) for error in recorded.get("errors", [])))
    return recorded


def _with_explicit_run_paths(state: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    updated = dict(state)
    updated["run_dir"] = str(run_dir)
    updated["analysis_dir"] = str(run_dir / "analysis")
    updated["planning_dir"] = str(run_dir / "planning")
    updated["assessment_dir"] = str(run_dir / "assessment")
    updated["orchestration_dir"] = str(run_dir / "orchestration")
    return load_copilot_config(updated)


def _normalize_resume_result(
    state: dict[str, Any],
    *,
    decision: str,
    explicit_recorded: dict[str, Any],
) -> dict[str, Any]:
    result = dict(state)
    artifact_refs = dict(result.get("artifact_refs", {}) or {})
    artifact_refs.update(explicit_recorded.get("artifact_refs", {}) or {})
    result["artifact_refs"] = artifact_refs
    if decision != "approved":
        result["stop_reason"] = f"Approval decision '{decision}' recorded; stopping."
        result["final_status"] = decision.upper()
    elif result.get("mode") != FULL_SANDBOX_MIGRATION_MODE:
        result["stop_reason"] = "Approval decision 'approved' recorded; stopping."
    return result


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_to_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def load_copilot_config(state: dict[str, Any]) -> dict[str, Any]:
    return apply_copilot_config(state)


def parse_copilot_config() -> dict[str, Any]:
    return parse_copilot_config_from_env()


if __name__ == "__main__":
    raise SystemExit(main())
