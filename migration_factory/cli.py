import argparse
import json
from pathlib import Path
from typing import Any

from migration_factory.orchestrator.graph import build_graph

RUN_STORE = Path(".mf_runs")


def _run_file(run_id: str) -> Path:
    RUN_STORE.mkdir(parents=True, exist_ok=True)
    return RUN_STORE / f"{run_id}.json"


def _save_state(run_id: str, payload: dict[str, Any]) -> None:
    _run_file(run_id).write_text(
        json.dumps(_to_json_safe(payload), indent=2), encoding="utf-8"
    )


def _load_state(run_id: str) -> dict[str, Any]:
    run_file = _run_file(run_id)
    if not run_file.exists():
        raise SystemExit(f"No run context found for run-id '{run_id}'.")
    return json.loads(run_file.read_text(encoding="utf-8"))


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _to_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_to_json_safe(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def cmd_run(args: argparse.Namespace) -> int:
    graph = build_graph()
    config = {"configurable": {"thread_id": args.run_id}}
    init_state = {
        "run_id": args.run_id,
        "thread_id": args.run_id,
        "legacy_app_path": args.legacy_app,
        "modernized_app_path": args.modernized_app,
        "ai_hub_path": args.ai_hub,
        "profile": args.profile,
        "analysis_status": "PENDING",
        "planning_status": "PENDING",
        "approval_status": "pending",
        "transformation_status": "PENDING",
        "current_unit": "init",
        "errors": [],
    }

    state = graph.invoke(init_state, config=config)
    paused = state.get("transformation_status") != "PASS"
    _save_state(
        args.run_id,
        {
            "paused": paused,
            "state": state,
        },
    )

    print(
        json.dumps(
            _to_json_safe({"run_id": args.run_id, "paused": paused, "state": state}),
            indent=2,
        )
    )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    persisted = _load_state(args.run_id)
    prev_state = persisted["state"]

    decision_map = {
        "approve": "approved",
        "reject": "rejected",
        "replan": "replan",
    }
    prev_state["approval_status"] = decision_map[args.decision]

    graph = build_graph()
    config = {"configurable": {"thread_id": args.run_id}}
    final_state = graph.invoke(prev_state, config=config)

    _save_state(
        args.run_id,
        {
            "paused": False,
            "state": final_state,
        },
    )

    print(
        json.dumps(
            _to_json_safe(
                {"run_id": args.run_id, "paused": False, "state": final_state}
            ),
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migration_factory.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--legacy-app", required=True)
    run_parser.add_argument("--modernized-app", required=True)
    run_parser.add_argument("--ai-hub", required=True)
    run_parser.add_argument("--profile", required=True)
    run_parser.set_defaults(func=cmd_run)

    approve_parser = subparsers.add_parser("approve")
    approve_parser.add_argument("--run-id", required=True)
    approve_parser.add_argument("--decision", choices=["approve", "reject", "replan"], required=True)
    approve_parser.set_defaults(func=cmd_approve)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
