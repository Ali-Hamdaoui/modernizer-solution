from __future__ import annotations

import json
import unittest

from helpers import workspace_temp_dir
from migration_factory.agents.transformation_agent import run_transformation_agent
from migration_factory.contracts.migration import (
    BuildValidationStatus,
    LedgerStatus,
    initialize_ledger,
    load_ledger,
    mark_build_failed,
    mark_build_passed,
    mark_unit_awaiting_build,
    mark_unit_in_progress,
)


PLUGIN_XML = """<plugin>
  <groupId>org.openrewrite.maven</groupId>
  <artifactId>rewrite-maven-plugin</artifactId>
  <version>6.23.0</version>
</plugin>
"""


PLAN_YAML = """schema_version: "1.3"
migration:
  id: test-migration
  name: Test Migration
workspaces:
  target:
    path: ./modernized-app
    migration_dir: .migration
    ledger_file: .migration/ledger.json
migration_units:
  - id: unit-001
    title: First Unit
    expected_files:
      - pom.xml
    transformations:
      - type: custom_code_change
        description: record only
    checks:
      - id: compile
        command: mvn clean compile
        required: true
"""


class TransformationAgentTests(unittest.TestCase):
    def test_transformation_agent_initializes_ledger_and_waits_for_build(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            app.mkdir()
            (app / "pom.xml").write_text("<project />", encoding="utf-8")
            plan = tmp / "plan.yaml"
            plan.write_text(PLAN_YAML, encoding="utf-8")
            plugin = tmp / "rewrite-plugin.txt"
            plugin.write_text(PLUGIN_XML, encoding="utf-8")

            result = run_transformation_agent(app, plugin, plan, dry_run=True, wait_for_continue=False)
            ledger = load_ledger(result.ledger_file)

            self.assertEqual(result.status, LedgerStatus.AWAITING_BUILD_AGENT)
            self.assertEqual(ledger["current_unit"], "unit-001")
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PENDING)

    def test_build_ledger_pass_marks_unit_completed(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
            initialize_ledger(
                ledger_file,
                migration_id="test",
                migration_name="Test",
                total_units=1,
                target_path=tmp,
            )
            mark_unit_in_progress(ledger_file, unit_id="unit-001", unit_index=0, title="Unit 1")
            mark_unit_awaiting_build(ledger_file, unit_id="unit-001")

            mark_build_passed(ledger_file, result_kind="success", message="Application started")
            ledger = json.loads(ledger_file.read_text(encoding="utf-8"))

            self.assertEqual(ledger["status"], LedgerStatus.BUILD_VALIDATED)
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.PASSED)
            self.assertEqual(ledger["completed_units"], ["unit-001"])

    def test_build_ledger_failure_blocks_unit(self) -> None:
        with workspace_temp_dir() as tmp:
            ledger_file = tmp / ".migration" / "ledger.json"
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
                error_contract_path=tmp / "build-error.json",
            )
            ledger = load_ledger(ledger_file)

            self.assertEqual(ledger["status"], LedgerStatus.BLOCKED)
            self.assertEqual(ledger["blocked_unit"], "unit-001")
            self.assertEqual(ledger["build_validation"]["status"], BuildValidationStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
