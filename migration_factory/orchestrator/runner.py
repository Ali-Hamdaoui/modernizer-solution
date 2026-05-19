from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from migration_factory.orchestrator.checkpointing import default_checkpointer
from migration_factory.orchestrator.graph import build_graph
from migration_factory.orchestrator.preflight import (
    PreflightError,
    build_langgraph_config,
    validate_preflight,
)
from migration_factory.orchestrator.state import (
    READ_ONLY_ASSESSMENT_MODE,
    build_initial_state,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m migration_factory.orchestrator.runner",
        description="Run read-only migration assessment orchestration.",
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--legacy", required=True)
    parser.add_argument("--modernized", required=True)
    parser.add_argument("--ai-hub", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument(
        "--mode",
        default=READ_ONLY_ASSESSMENT_MODE,
        choices=[READ_ONLY_ASSESSMENT_MODE],
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)

    state = build_initial_state(
        run_id=args.run_id,
        legacy_app_path=args.legacy,
        modernized_app_path=args.modernized,
        ai_hub_path=args.ai_hub,
        profile_id=args.profile,
        thread_id=args.run_id,
        mode=args.mode,
    )
    config = build_langgraph_config(args.run_id)

    try:
        validate_preflight(state, config)
        graph = build_graph(checkpointer=default_checkpointer())
        result = graph.invoke(state, config=config)
    except PreflightError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(_render_result(result), indent=2, sort_keys=True))
    return 0


def _render_result(result: Any) -> Any:
    interrupt_payload = _extract_interrupt_payload(result)
    if interrupt_payload is not None:
        return {
            "status": "human_approval_required",
            "approval_status": "INTERRUPTED",
            "run_id": interrupt_payload.get("run_id", ""),
            "summary": interrupt_payload.get("summary", {}),
            "artifact_refs": interrupt_payload.get("artifact_refs", {}),
            "blockers": interrupt_payload.get("blockers", []),
            "warnings": interrupt_payload.get("warnings", []),
            "decision_options": interrupt_payload.get("decision_options", []),
        }
    return _to_json_safe(result)


def _extract_interrupt_payload(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None

    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return None

    interrupt = interrupts[0]
    payload = getattr(interrupt, "value", interrupt)
    if isinstance(payload, dict):
        return payload
    return {"summary": _to_json_safe(payload)}


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


if __name__ == "__main__":
    raise SystemExit(main())
