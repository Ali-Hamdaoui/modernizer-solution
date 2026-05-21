from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from helpers import workspace_temp_dir
from migration_factory.agents.debug_agent import build_debug_commands, run_debug_agent
from migration_factory.agents.debug_agent.debug_agent import DebugCommandResult
from migration_factory.contracts.migration import (
    BuildValidationStatus,
    LedgerStatus,
    initialize_ledger,
    load_ledger,
    mark_build_failed,
    mark_unit_awaiting_build,
    mark_unit_in_progress,
)


class DebugAgentTests(unittest.TestCase):
    def test_builds_maven_dependency_repair_plan(self) -> None:
        with workspace_temp_dir() as project:
            contract = {
                "build_tool": "maven",
                "result_kind": "dependency_error",
                "module": "shoppoc-app",
            }

            with patch.dict(os.environ, {"MAVEN_CMD": "", "MVN_CMD": ""}):
                with patch("migration_factory.agents.debug_agent.debug_agent._which_windows", return_value=None):
                    commands = build_debug_commands(contract, project)

            self.assertEqual(
                commands,
                [
                    ["mvn", "-f", str(Path("shoppoc-app") / "pom.xml"), "-U", "dependency:resolve"],
                    ["mvn", "-f", str(Path("shoppoc-app") / "pom.xml"), "-U", "clean", "install", "-DskipTests"],
                ],
            )

    def test_successful_debug_reopens_ledger_for_build_retry(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            contract_file = tmp / "build-error.json"
            contract_file.write_text(
                json.dumps(
                    {
                        "project_path": str(tmp),
                        "build_tool": "maven",
                        "result_kind": "compilation_error",
                        "module": None,
                    }
                ),
                encoding="utf-8",
            )
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")
            mark_build_failed(
                ledger_file,
                result_kind="compilation_error",
                message="Compile failed",
                error_contract_path=contract_file,
            )

            with patch(
                "migration_factory.agents.debug_agent.debug_agent._run_command",
                return_value=DebugCommandResult(["mvn"], 0),
            ):
                result = run_debug_agent(ledger_file=ledger_file, stream_output=False)

            ledger = load_ledger(ledger_file)
            self.assertTrue(result.succeeded)
            self.assertEqual(ledger["status"], LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(ledger["blocked_unit"], None)
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PENDING)
            self.assertEqual(ledger["units"]["unit-001"]["status"], LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(len(ledger["units"]["unit-001"]["debug_attempts"]), 1)

    def test_failed_debug_keeps_ledger_blocked(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            contract_file = tmp / "build-error.json"
            contract_file.write_text(
                json.dumps(
                    {
                        "project_path": str(tmp),
                        "build_tool": "maven",
                        "result_kind": "compilation_error",
                        "module": None,
                    }
                ),
                encoding="utf-8",
            )
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")
            mark_build_failed(
                ledger_file,
                result_kind="compilation_error",
                message="Compile failed",
                error_contract_path=contract_file,
            )

            with patch(
                "migration_factory.agents.debug_agent.debug_agent._run_command",
                return_value=DebugCommandResult(["mvn"], 1),
            ):
                result = run_debug_agent(ledger_file=ledger_file, stream_output=False)

            ledger = load_ledger(ledger_file)
            self.assertFalse(result.succeeded)
            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "unit-001")
            self.assertEqual(ledger["build_validation"]["debug_status"], "failed")


if __name__ == "__main__":
    unittest.main()
