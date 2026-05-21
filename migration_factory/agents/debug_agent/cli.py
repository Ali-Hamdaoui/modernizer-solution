from __future__ import annotations

import argparse
import sys

from migration_factory.contracts.migration import LedgerError

from .debug_agent import DebugAgentError, run_debug_agent


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_debug_agent(
            args.project_path,
            error_contract_path=args.error_contract,
            ledger_file=args.ledger_file,
            stream_output=not args.quiet,
            continue_on_failure=args.continue_on_failure,
        )
    except (DebugAgentError, LedgerError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    for item in result.commands:
        printable = " ".join(item.command)
        status = "OK" if item.succeeded else f"FAILED ({item.exit_code})"
        print(f"{status}: {printable}")

    if result.succeeded:
        print(result.message)
        return 0

    print(result.message, file=sys.stderr)
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="debug-agent",
        description="Run deterministic repair commands for a Build Agent failure contract.",
    )
    parser.add_argument(
        "project_path",
        nargs="?",
        help="Path to the modernized Java project. Defaults to project_path from the build error contract.",
    )
    parser.add_argument("--error-contract", help="Path to a Build Agent build-error-*.json contract")
    parser.add_argument("--ledger-file", help="Migration ledger JSON file to update after debug commands")
    parser.add_argument("--quiet", action="store_true", help="Do not stream command output")
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="Run every planned debug command even if one fails",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
