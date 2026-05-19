from __future__ import annotations

import json
import unittest
from unittest import mock
import io
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

import yaml

from migration_factory.contracts.build import BuildRunResult
from migration_factory.agents.transformation_agent.agent import (
    TransformationAgentError,
    TransformationRunResult,
)
from helpers import workspace_temp_dir
from migration_factory.agents.transformation_agent.execution_plan import (
    TransformationExecutionPlanError,
    write_transformation_execution_plan,
)
from migration_factory.agents.transformation_agent.plan import load_migration_plan
from migration_factory.approval import write_approval_decision, write_approved_plan_lock
from migration_factory.agents.transformation_agent import run_transformation_agent
from migration_factory.agents.transformation_agent.workspace import (
    TransformationWorkspaceError,
    prepare_sandbox_workspace,
)
from migration_factory.agents.transformation_agent import workspace as workspace_module
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
from migration_factory.transform_v1_after_approval import main as transform_v1_after_approval_main


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
    def test_execution_plan_adapter_writes_current_transformer_yaml(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id, include_rewrite_plan=True)

            output_path = write_transformation_execution_plan(app, run_id)
            payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
            loaded_plan = load_migration_plan(output_path)

            self.assertEqual(
                output_path,
                app
                / ".migration"
                / "runs"
                / run_id
                / "transformation"
                / "transformation_execution_plan.yaml",
            )
            self.assertEqual(payload["schema_version"], "1.3")
            self.assertEqual(payload["migration"]["id"], run_id)
            self.assertEqual(payload["workspaces"]["target"]["path"], str(app.resolve()))
            self.assertEqual([unit["id"] for unit in payload["migration_units"]], ["baseline", "java-17"])
            self.assertEqual(payload["migration_units"][0]["checks"][0]["command"], "mvn clean test")
            self.assertEqual(payload["migration_units"][1]["transformations"][0]["type"], "openrewrite")
            self.assertEqual(
                payload["migration_units"][1]["transformations"][0]["active_recipes"],
                ["org.openrewrite.java.migrate.UpgradeToJava17"],
            )
            self.assertEqual(loaded_plan.migration_id, run_id)
            self.assertEqual([unit.id for unit in loaded_plan.units], ["baseline", "java-17"])

    def test_execution_plan_adapter_rejects_missing_approval_decision(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_run_artifacts(app, run_id)
            write_approved_plan_lock(_run_dir(app, run_id), run_id)

            with self.assertRaisesRegex(
                TransformationExecutionPlanError,
                "approval_decision.json missing",
            ):
                write_transformation_execution_plan(app, run_id)

    def test_execution_plan_adapter_rejects_invalid_plan_lock(self) -> None:
        with workspace_temp_dir() as tmp:
            app = tmp / "modernized-app"
            run_id = "run-1"
            _write_approved_run_artifacts(app, run_id)
            units_path = _run_dir(app, run_id) / "planning" / "migration_units.yaml"
            units_path.write_text(units_path.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")

            with self.assertRaisesRegex(
                TransformationExecutionPlanError,
                "approved_plan_lock.json artifact hashes do not match current run artifacts",
            ):
                write_transformation_execution_plan(app, run_id)

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

    def test_prepare_sandbox_workspace_copies_legacy_with_exclusions_and_checkpoint(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (legacy / ".git").mkdir()
            (legacy / ".git" / "config").write_text("source git", encoding="utf-8")
            (legacy / ".migration").mkdir()
            (legacy / ".migration" / "ledger.json").write_text("{}", encoding="utf-8")
            (legacy / "target").mkdir()
            (legacy / "target" / "classes.txt").write_text("compiled", encoding="utf-8")
            (legacy / "build").mkdir()
            (legacy / "build" / "output.txt").write_text("built", encoding="utf-8")
            (legacy / "node_modules").mkdir()
            (legacy / "node_modules" / "package.txt").write_text("dependency", encoding="utf-8")
            (legacy / "__pycache__").mkdir()
            (legacy / "__pycache__" / "module.pyc").write_text("cache", encoding="utf-8")
            (modernized / "marker.txt").write_text("do not change", encoding="utf-8")

            sandbox = prepare_sandbox_workspace(
                legacy_app_path=legacy,
                modernized_app_path=modernized,
                run_dir=run_dir,
            )

            self.assertEqual(sandbox.path, run_dir / "workspaces" / "sandbox")
            self.assertEqual((sandbox.path / "pom.xml").read_text(encoding="utf-8"), "<project />")
            self.assertFalse((sandbox.path / ".migration").exists())
            self.assertFalse((sandbox.path / "target").exists())
            self.assertFalse((sandbox.path / "build").exists())
            self.assertFalse((sandbox.path / "node_modules").exists())
            self.assertFalse((sandbox.path / "__pycache__").exists())
            self.assertEqual((legacy / "pom.xml").read_text(encoding="utf-8"), "<project />")
            self.assertEqual((modernized / "marker.txt").read_text(encoding="utf-8"), "do not change")
            self.assertIn(sandbox.checkpoint_type, {"git", "manifest"})
            if sandbox.checkpoint_type == "git":
                self.assertTrue((sandbox.path / ".git").is_dir())
                self.assertRegex(sandbox.checkpoint_ref, r"^[0-9a-f]{40}$")
            else:
                self.assertTrue(Path(sandbox.checkpoint_ref).is_file())

    def test_prepare_sandbox_workspace_writes_manifest_without_git(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")

            with mock.patch("migration_factory.agents.transformation_agent.workspace.shutil.which", return_value=None):
                sandbox = prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

            manifest_path = sandbox.path / "baseline_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(sandbox.checkpoint_type, "manifest")
            self.assertEqual(Path(sandbox.checkpoint_ref), manifest_path)
            self.assertEqual([entry["path"] for entry in manifest["files"]], ["pom.xml"])

    def test_prepare_sandbox_workspace_rejects_sandbox_outside_run_dir(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            outside = tmp / "outside"
            legacy.mkdir()
            modernized.mkdir()
            run_dir.mkdir(parents=True)
            outside.mkdir()
            _symlink_or_skip(self, run_dir / "workspaces", outside, target_is_directory=True)

            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must stay inside run_dir"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

    def test_prepare_sandbox_workspace_rejects_sandbox_equal_to_source_or_target(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            legacy = run_dir / "workspaces" / "sandbox"
            modernized = tmp / "modernized-app"
            legacy.mkdir(parents=True)
            modernized.mkdir()

            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must not be the legacy_app_path"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

            modernized = legacy
            legacy = tmp / "legacy-app"
            legacy.mkdir()
            with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must not be the modernized_app_path"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=run_dir,
                )

    def test_prepare_sandbox_workspace_rejects_symlink_escape(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            outside = tmp / "outside.txt"
            legacy.mkdir()
            modernized.mkdir()
            outside.write_text("outside", encoding="utf-8")
            _symlink_or_skip(self, legacy / "escape.txt", outside)

            with self.assertRaisesRegex(TransformationWorkspaceError, "Symlink escapes"):
                prepare_sandbox_workspace(
                    legacy_app_path=legacy,
                    modernized_app_path=modernized,
                    run_dir=modernized / ".migration" / "runs" / "run-1",
                )

    def test_prepare_sandbox_workspace_wraps_cleanup_permission_error(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            run_dir = modernized / ".migration" / "runs" / "run-1"
            sandbox = run_dir / "workspaces" / "sandbox"
            legacy.mkdir()
            modernized.mkdir()
            sandbox.mkdir(parents=True)
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (sandbox / "locked.txt").write_text("locked", encoding="utf-8")

            with mock.patch(
                "migration_factory.agents.transformation_agent.workspace.shutil.rmtree",
                side_effect=PermissionError("[WinError 5] Access is denied"),
            ):
                with self.assertRaisesRegex(TransformationWorkspaceError, "SANDBOX_CLEAN_FAILED") as raised:
                    prepare_sandbox_workspace(
                        legacy_app_path=legacy,
                        modernized_app_path=modernized,
                        run_dir=run_dir,
                    )

            message = str(raised.exception)
            self.assertIn(str(sandbox), message)
            self.assertIn("stop Java process / close terminals/editors", message)
            self.assertIn("delete sandbox manually", message)
            self.assertIn("use a new run id", message)

    def test_sandbox_cleanup_refuses_target_outside_run_dir(self) -> None:
        with workspace_temp_dir() as tmp:
            run_dir = tmp / "run"
            outside = tmp / "outside-sandbox"
            run_dir.mkdir()
            outside.mkdir()

            with mock.patch("migration_factory.agents.transformation_agent.workspace.shutil.rmtree") as rmtree:
                with self.assertRaisesRegex(TransformationWorkspaceError, "sandbox must stay inside run_dir"):
                    workspace_module._remove_existing_sandbox(outside, run_dir)

            rmtree.assert_not_called()

    def test_transform_v1_after_approval_runs_transformer_against_sandbox(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("OPENREWRITE_FULL_LOG should be quiet by default")
                unit_id = str(kwargs.get("start_unit") or "baseline")
                _write_awaiting_build_ledger(ledger_file, unit_id)
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ) as run_agent:
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=lambda **kwargs: (
                        print("MAVEN_FULL_LOG should be quiet by default")
                        or BuildRunResult(
                            succeeded=True,
                            result_kind="success",
                            message="Application started successfully",
                        )
                    ),
                ) as run_build:
                    with redirect_stdout(stdout):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            sandbox_path = run_dir / "workspaces" / "sandbox"
            plan_path = run_dir / "transformation" / "transformation_execution_plan.yaml"
            plugin_path = run_dir / "transformation" / "openrewrite-plugin.xml"
            log_file = run_dir / "logs" / "phase2_transform.log"
            plan_payload = yaml.safe_load(plan_path.read_text(encoding="utf-8"))

            self.assertEqual(result, 0)
            self.assertIn("APPROVED_FOR_TRANSFORM", stdout.getvalue())
            self.assertIn("SANDBOX_PREPARED", stdout.getvalue())
            self.assertIn("TRANSFORM_RUNNING", stdout.getvalue())
            self.assertIn("BUILD_RUNNING_IN_SANDBOX", stdout.getvalue())
            self.assertIn("BUILD_PASSED_IN_SANDBOX", stdout.getvalue())
            self.assertEqual(stdout.getvalue().count("BUILD_PASSED_IN_SANDBOX"), 2)
            self.assertIn("TRANSFORM_APPLIED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("OPENREWRITE_FULL_LOG", stdout.getvalue())
            self.assertNotIn("MAVEN_FULL_LOG", stdout.getvalue())
            self.assertIn("OPENREWRITE_FULL_LOG", log_file.read_text(encoding="utf-8"))
            self.assertIn("MAVEN_FULL_LOG", log_file.read_text(encoding="utf-8"))
            first_build_passed = stdout.getvalue().index("BUILD_PASSED_IN_SANDBOX")
            second_transform_running = stdout.getvalue().index("TRANSFORM_RUNNING", stdout.getvalue().index("TRANSFORM_RUNNING") + 1)
            self.assertLess(first_build_passed, second_transform_running)
            self.assertEqual(stdout.getvalue().count("TRANSFORM_RUNNING"), 2)
            self.assertGreater(
                stdout.getvalue().index("TRANSFORM_APPLIED_IN_SANDBOX"),
                stdout.getvalue().rindex("BUILD_PASSED_IN_SANDBOX"),
            )
            self.assertEqual(plan_payload["workspaces"]["target"]["path"], str(sandbox_path.resolve()))
            self.assertTrue((sandbox_path / "pom.xml").is_file())
            self.assertIn("<artifactId>rewrite-maven-plugin</artifactId>", plugin_path.read_text(encoding="utf-8"))
            run_agent.assert_has_calls(
                [
                    mock.call(
                        sandbox_path,
                        plugin_path,
                        plan_path,
                        start_unit=None,
                        dry_run=False,
                        stream_output=True,
                        wait_for_continue=False,
                    ),
                    mock.call(
                        sandbox_path,
                        plugin_path,
                        plan_path,
                        start_unit="java-17",
                        dry_run=False,
                        stream_output=True,
                        wait_for_continue=False,
                    ),
                ]
            )
            self.assertEqual(run_build.call_count, 2)
            run_build.assert_has_calls(
                [
                    mock.call(
                        project_path=sandbox_path,
                        ledger_file=ledger_file,
                        output_dir=run_dir / "build",
                        stream_output=True,
                        validation_unit_id="baseline",
                        source_changing_unit=False,
                    ),
                    mock.call(
                        project_path=sandbox_path,
                        ledger_file=ledger_file,
                        output_dir=run_dir / "build",
                        stream_output=True,
                        validation_unit_id="java-17",
                        source_changing_unit=True,
                    ),
                ]
            )

    def test_transform_v1_after_approval_reports_build_failure(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)
            error_contract = run_dir / "build" / "build-error.json"
            ledger_file = run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json"

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                _write_awaiting_build_ledger(ledger_file, "baseline")
                return TransformationRunResult(
                    ledger_file=ledger_file,
                    status=LedgerStatus.AWAITING_BUILD_AGENT,
                    completed_units=[],
                )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch(
                    "migration_factory.transform_v1_after_approval.run_build_agent",
                    side_effect=lambda **kwargs: (
                        print("[ERROR] COMPILATION ERROR full Maven output")
                        or BuildRunResult(
                            succeeded=False,
                            result_kind="compilation_error",
                            message="Compilation failed",
                            error_contract_path=error_contract,
                        )
                    ),
                ):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertNotIn("TRANSFORM_APPLIED_IN_SANDBOX", stdout.getvalue())
            self.assertIn("BUILD_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertEqual(stdout.getvalue().count("TRANSFORM_RUNNING"), 1)
            self.assertNotIn("[ERROR] COMPILATION ERROR", stdout.getvalue())
            self.assertIn("Build result kind: compilation_error", stderr.getvalue())
            self.assertIn("Build message: Compilation failed", stderr.getvalue())
            self.assertIn(f"Build error contract: {error_contract}", stderr.getvalue())
            self.assertIn("log_file:", stderr.getvalue())
            self.assertIn("[ERROR] COMPILATION ERROR full Maven output", stderr.getvalue())

    def test_transform_v1_after_approval_reports_transform_failure(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            stdout = io.StringIO()
            stderr = io.StringIO()
            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("OpenRewrite failure output")
                raise TransformationAgentError("boom")

            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_build_agent") as run_build:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertIn("TRANSFORM_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("OpenRewrite failure output", stdout.getvalue())
            self.assertIn("ERROR: boom", stderr.getvalue())
            self.assertIn("log_file:", stderr.getvalue())
            self.assertIn("OpenRewrite failure output", stderr.getvalue())
            run_build.assert_not_called()

    def test_transform_v1_after_approval_writes_custom_log_file(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            custom_log = tmp / "custom" / "phase2.log"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("CUSTOM_LOG_OPENREWRITE_OUTPUT")
                return TransformationRunResult(
                    ledger_file=run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json",
                    status=LedgerStatus.COMPLETED,
                    completed_units=["java-17"],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_build_agent") as run_build:
                    with redirect_stdout(stdout):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                                "--log-file",
                                str(custom_log),
                            ]
                        )

            self.assertEqual(result, 0)
            self.assertNotIn("CUSTOM_LOG_OPENREWRITE_OUTPUT", stdout.getvalue())
            self.assertIn("CUSTOM_LOG_OPENREWRITE_OUTPUT", custom_log.read_text(encoding="utf-8"))
            self.assertFalse((run_dir / "logs" / "phase2_transform.log").exists())
            run_build.assert_not_called()

    def test_transform_v1_after_approval_verbose_streams_subprocess_output(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            legacy.mkdir()
            modernized.mkdir()
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            def run_agent_side_effect(*args: object, **kwargs: object) -> TransformationRunResult:
                print("VERBOSE_OPENREWRITE_OUTPUT")
                return TransformationRunResult(
                    ledger_file=run_dir / "workspaces" / "sandbox" / ".migration" / "ledger.json",
                    status=LedgerStatus.COMPLETED,
                    completed_units=["java-17"],
                )

            stdout = io.StringIO()
            with mock.patch(
                "migration_factory.transform_v1_after_approval.run_transformation_agent",
                side_effect=run_agent_side_effect,
            ):
                with redirect_stdout(stdout):
                    result = transform_v1_after_approval_main(
                        [
                            "--run-dir",
                            str(run_dir),
                            "--legacy-app",
                            str(legacy),
                            "--modernized-app",
                            str(modernized),
                            "--ai-hub",
                            str(ai_hub),
                            "--profile",
                            "java17",
                            "--approved-by",
                            "human",
                            "--verbose",
                        ]
                    )

            log_file = run_dir / "logs" / "phase2_transform.log"
            self.assertEqual(result, 0)
            self.assertIn("VERBOSE_OPENREWRITE_OUTPUT", stdout.getvalue())
            self.assertIn("Transformer status: completed", stdout.getvalue())
            self.assertIn("VERBOSE_OPENREWRITE_OUTPUT", log_file.read_text(encoding="utf-8"))

    def test_transform_v1_after_approval_reports_sandbox_cleanup_failure_without_traceback(self) -> None:
        with workspace_temp_dir() as tmp:
            legacy = tmp / "legacy-app"
            modernized = tmp / "modernized-app"
            ai_hub = tmp / "ai-hub"
            run_id = "run-1"
            run_dir = _run_dir(modernized, run_id)
            sandbox = run_dir / "workspaces" / "sandbox"
            legacy.mkdir()
            modernized.mkdir()
            sandbox.mkdir(parents=True)
            (legacy / "pom.xml").write_text("<project />", encoding="utf-8")
            (sandbox / "locked.txt").write_text("locked", encoding="utf-8")
            _write_ai_hub_profile(ai_hub)
            _write_approved_run_artifacts(modernized, run_id, include_rewrite_plan=True)

            stdout = io.StringIO()
            stderr = io.StringIO()
            with mock.patch(
                "migration_factory.agents.transformation_agent.workspace.shutil.rmtree",
                side_effect=PermissionError("[WinError 5] Access is denied"),
            ):
                with mock.patch("migration_factory.transform_v1_after_approval.run_transformation_agent") as run_agent:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = transform_v1_after_approval_main(
                            [
                                "--run-dir",
                                str(run_dir),
                                "--legacy-app",
                                str(legacy),
                                "--modernized-app",
                                str(modernized),
                                "--ai-hub",
                                str(ai_hub),
                                "--profile",
                                "java17",
                                "--approved-by",
                                "human",
                            ]
                        )

            self.assertEqual(result, 1)
            self.assertIn("TRANSFORM_FAILED_IN_SANDBOX", stdout.getvalue())
            self.assertNotIn("Traceback", stdout.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertIn("SANDBOX_CLEAN_FAILED", stderr.getvalue())
            self.assertIn(str(sandbox), stderr.getvalue())
            self.assertIn("stop Java process / close terminals/editors", stderr.getvalue())
            self.assertIn("delete sandbox manually", stderr.getvalue())
            self.assertIn("use a new run id", stderr.getvalue())
            run_agent.assert_not_called()


def _run_dir(app: Path, run_id: str) -> Path:
    return app / ".migration" / "runs" / run_id


def _symlink_or_skip(
    test_case: unittest.TestCase,
    link_path: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link_path.symlink_to(target, target_is_directory=target_is_directory)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            test_case.skipTest("Windows symlink privilege is not available")
        raise


def _write_awaiting_build_ledger(ledger_file: Path, unit_id: str) -> None:
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    ledger_file.write_text(
        json.dumps(
            {
                "status": LedgerStatus.AWAITING_BUILD_AGENT,
                "current_unit": unit_id,
                "blocked_unit": None,
                "completed_units": [],
                "build_validation": {
                    "required": True,
                    "status": BuildValidationStatus.PENDING,
                    "unit_id": unit_id,
                },
            }
        ),
        encoding="utf-8",
    )


def _write_approved_run_artifacts(
    app: Path,
    run_id: str,
    *,
    include_rewrite_plan: bool = False,
) -> None:
    _write_run_artifacts(app, run_id, include_rewrite_plan=include_rewrite_plan)
    run_dir = _run_dir(app, run_id)
    write_approved_plan_lock(run_dir, run_id)
    write_approval_decision(
        run_dir,
        run_id,
        "approved",
        plan_lock_ref="approved_plan_lock.json",
    )


def _write_run_artifacts(
    app: Path,
    run_id: str,
    *,
    include_rewrite_plan: bool = False,
) -> None:
    run_dir = _run_dir(app, run_id)
    planning_dir = run_dir / "planning"
    assessment_dir = run_dir / "assessment"
    analysis_dir = run_dir / "analysis"
    planning_dir.mkdir(parents=True, exist_ok=True)
    assessment_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    (planning_dir / "migration_plan.yaml").write_text(
        f"""
schema_version: "1.0.0"
run_id: "{run_id}"
status: "PASS"
risk: "LOW"
profile: "java17"
artifact_refs:
  self: "migration_plan.yaml"
""".lstrip(),
        encoding="utf-8",
    )
    (planning_dir / "migration_units.yaml").write_text(
        f"""
schema_version: "1.0.0"
run_id: "{run_id}"
status: "PASS"
artifact_refs:
  self: "migration_units.yaml"
units:
  - id: "baseline"
    goal: "Establish baseline build."
    tools:
      - "maven"
      - "junit"
    validation:
      - "mvn"
      - "clean"
      - "test"
    writes_source: false
    required: "yes"
    expected_artifacts:
      - "target/surefire-reports"
  - id: "java-17"
    goal: "Upgrade project runtime to Java 17."
    tools:
      - "maven"
    validation:
      - "mvn"
      - "clean"
      - "test"
    writes_source: true
    required: "yes"
    expected_artifacts:
      - "target/classes"
""".lstrip(),
        encoding="utf-8",
    )
    (assessment_dir / "assessment_report.json").write_text(
        json.dumps({"profile": "java17"}),
        encoding="utf-8",
    )
    if include_rewrite_plan:
        (analysis_dir / "rewrite_plugin_plan.json").write_text(
            json.dumps(
                {
                    "plugin": "org.openrewrite.maven:rewrite-maven-plugin:6.39.0",
                    "recipe_artifacts": ["org.openrewrite.recipe:rewrite-migrate-java:3.20.0"],
                    "active_recipes": ["org.openrewrite.java.migrate.UpgradeToJava17"],
                }
            ),
            encoding="utf-8",
        )


def _write_ai_hub_profile(ai_hub: Path) -> None:
    profiles = ai_hub / "profiles"
    catalogs = ai_hub / "catalogs"
    profiles.mkdir(parents=True)
    catalogs.mkdir(parents=True)
    (profiles / "java17.yaml").write_text(
        """
id: java17
openrewrite:
  catalog_path: catalogs/openrewrite.yaml
""".lstrip(),
        encoding="utf-8",
    )
    (catalogs / "openrewrite.yaml").write_text(
        """
id: openrewrite-java17
plugin:
  group_id: org.openrewrite.maven
  artifact_id: rewrite-maven-plugin
  version: 6.39.0
recipe_artifacts:
  - group_id: org.openrewrite.recipe
    artifact_id: rewrite-migrate-java
    version: 3.20.0
""".lstrip(),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
