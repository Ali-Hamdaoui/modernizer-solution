import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from textual import events
from textual.widgets import Button, DataTable, Input, Static, TextArea

from migration_factory.tui.app import (
    MigrationFactorySetupApp,
    RunViewModel,
    build_pipeline_rows,
    _current_phase_status_line,
    _format_details,
    _format_failure_from_view,
    _format_target_summary,
    _friendly_status,
    _normalized_run_state,
    _pipeline_rows,
    _progress_value,
    _summary_with_inferred_artifacts,
    _view_launch_state,
)
from migration_factory.tui.config import CONFIG_PATH, ENV_FIELD_MAP, TuiConfig, load_config
from migration_factory.tui.runner_adapter import RunnerLaunchResult, RunnerResumeResult
from migration_factory.tui.theme import BACKEND_BADGES, STATE_BADGES


def _clear_tui_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_key, _field_name in ENV_FIELD_MAP:
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.delenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", raising=False)


def test_setup_screen_renders_full_config_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_setup_screen_renders_full_config_fields())


async def _assert_setup_screen_renders_full_config_fields() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(
        legacy_app_path="/legacy",
        modernized_app_path="/modernized",
        ai_hub_path="/ai-hub",
        profile_id="java17",
        mode="read_only_assessment",
        approved_by="ada",
        run_id="run-001",
        source_jdk_home="/java8",
        target_jdk_home="/java21",
        active_java_home="/java21",
    )

    async with app.run_test():
        assert app.title == "Migration Ops"
        for field_id in (
            "legacy_app_path",
            "modernized_app_path",
            "ai_hub_path",
            "profile_id",
            "mode",
            "approved_by",
            "run_id",
            "source_jdk_home",
            "target_jdk_home",
            "active_java_home",
        ):
            assert app.query_one(f"#{field_id}", Input).value

        assert app.query_one("#paste_config", TextArea)
        assert app.query_one("#import_pasted_config", Button).label.plain == "Import pasted config"
        assert app.query_one("#save_config", Button).label.plain == "Save config"
        assert app.query_one("#validate_paths", Button).label.plain == "Validate paths"
        assert app.query_one("#refresh_history", Button).label.plain == "Refresh history"
        assert app.query_one("#launch_run", Button).label.plain == "Launch run"
        assert app.query_one("#resume_approval", Button).label.plain == "Resume approval"
        assert app.query_one("#reset_setup", Button).label.plain == "Reset/Clear setup"
        assert app.query_one("#quit_app", Button).label.plain == "Quit"
        assert app.query_one("#approval").display is False


def test_setup_screen_uses_neutral_migration_ops_branding(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_setup_screen_uses_neutral_migration_ops_branding())


async def _assert_setup_screen_uses_neutral_migration_ops_branding() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test():
        rendered = "\n".join(str(node.content) for node in app.query(Static))
        assert app.title == "Migration Ops"
        assert "Migration Ops" in rendered
        assert "EGA Modernizer" not in rendered
        assert "EGA MODERNIZER" not in rendered


def test_setup_screen_renders_field_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_setup_screen_renders_field_labels())


async def _assert_setup_screen_renders_field_labels() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test():
        expected = {
            "legacy_app_path_label": "Legacy app",
            "modernized_app_path_label": "Modernized app",
            "ai_hub_path_label": "AI Hub",
            "profile_id_label": "Profile",
            "mode_label": "Mode",
            "approved_by_label": "Approved by",
            "run_id_label": "Run ID",
            "source_jdk_home_label": "Source JDK / JAVA8_HOME",
            "target_jdk_home_label": "Target JDK / JAVA21_HOME",
            "active_java_home_label": "Active JAVA_HOME",
        }
        for label_id, text in expected.items():
            assert app.query_one(f"#{label_id}", Static).content == text
        assert "read_only_assessment = assessment only" in app.query_one("#mode_help", Static).content


def test_target_summary_uses_selected_profile_target_stack(tmp_path: Path) -> None:
    ai_hub = tmp_path / "ai-hub"
    profiles = ai_hub / "profiles"
    profiles.mkdir(parents=True)
    (profiles / "springboot-2.7-to-3.5-java17.yaml").write_text(
        "\n".join(
            [
                "id: springboot-2.7-to-3.5-java17",
                "target_stack:",
                '  java: "17"',
                '  spring_boot: "3.5.14"',
                '  spring_framework: "6.2.18"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = _format_target_summary(
        TuiConfig(ai_hub_path=str(ai_hub), profile_id="springboot-2.7-to-3.5-java17")
    )

    assert summary == "Target: Java 17 / Spring Boot 3.5.14 / Spring Framework 6.2.18"


def test_import_config_action_updates_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_import_config_action_updates_fields())


async def _assert_import_config_action_updates_fields() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app.query_one("#paste_config").text = """
        export LEGACY_APP="$HOME/legacy"
        export PROFILE="java17"
        export JAVA21_HOME="/usr/lib/jvm/java-21"
        export JAVA_HOME="$JAVA21_HOME"
        """
        await pilot.press("ctrl+i")

        assert app.query_one("#legacy_app_path", Input).value.endswith("/legacy")
        assert app.query_one("#profile_id", Input).value == "java17"
        assert app.query_one("#target_jdk_home", Input).value == "/usr/lib/jvm/java-21"
        assert app.query_one("#active_java_home", Input).value == "/usr/lib/jvm/java-21"
        assert app.query_one("#paste_config", TextArea).text == ""
        assert "Keys:" in app.query_one("#status", Static).content


def test_import_config_action_overwrites_visible_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_import_config_action_overwrites_visible_fields())


async def _assert_import_config_action_overwrites_visible_fields() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(
        legacy_app_path="/old-legacy",
        modernized_app_path="/old-modernized",
        profile_id="old-profile",
    )

    async with app.run_test() as pilot:
        app.query_one("#paste_config", TextArea).text = """
        export LEGACY_APP="/new-legacy"
        export MODERNIZED_APP="/new-modernized"
        export PROFILE="new-profile"
        """
        await pilot.press("ctrl+i")

        assert app.query_one("#legacy_app_path", Input).value == "/new-legacy"
        assert app.query_one("#modernized_app_path", Input).value == "/new-modernized"
        assert app.query_one("#profile_id", Input).value == "new-profile"


def test_import_powershell_block_updates_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_import_powershell_block_updates_fields())


async def _assert_import_powershell_block_updates_fields() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app.query_one("#paste_config", TextArea).text = """
        $LEGACY_APP = "C:\\apps\\legacy";
        $MODERNIZED_APP = "C:\\apps\\modernized";
        $AI_HUB = "C:\\ai-hub";
        $PROFILE = "java21";
        $MODE = "full_sandbox_migration";
        $APPROVED_BY = "ada";
        """
        assert app.query_one("#import_pasted_config", Button).label.plain == "Import pasted config"
        await pilot.press("ctrl+i")

        assert app.query_one("#legacy_app_path", Input).value == "C:\\apps\\legacy"
        assert app.query_one("#modernized_app_path", Input).value == "C:\\apps\\modernized"
        assert app.query_one("#mode", Input).value == "full_sandbox_migration"
        assert app.query_one("#approved_by", Input).value == "ada"


def test_import_block_updates_run_id_and_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_import_block_updates_run_id_and_mode())


async def _assert_import_block_updates_run_id_and_mode() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app.query_one("#paste_config", TextArea).text = """
        export RUN_ID="run-from-paste"
        export MODE="full_sandbox_migration"
        """
        await pilot.press("ctrl+i")

        assert app.query_one("#run_id", Input).value == "run-from-paste"
        assert app.query_one("#mode", Input).value == "full_sandbox_migration"


def test_multiline_config_paste_into_setup_input_imports_instead_of_field_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_multiline_config_paste_into_setup_input_imports_instead_of_field_text())


async def _assert_multiline_config_paste_into_setup_input_imports_instead_of_field_text() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig()
    pasted = """
    export LEGACY_APP="/imported-legacy"
    export PROFILE="java21"
    """

    async with app.run_test() as pilot:
        focused_input = app.query_one("#legacy_app_path", Input)
        focused_input.focus()
        await pilot.pause()
        app.on_paste(events.Paste(pasted))

        assert focused_input.value == "/imported-legacy"
        assert app.query_one("#profile_id", Input).value == "java21"
        assert app.query_one("#paste_config", TextArea).text == ""
        status = app.query_one("#status", Static).content
        assert "Imported config from pasted shell block" in status
        assert "legacy_app_path" in status


def test_shell_text_landing_in_setup_input_is_imported_and_cleared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_shell_text_landing_in_setup_input_is_imported_and_cleared())


async def _assert_shell_text_landing_in_setup_input_is_imported_and_cleared() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        field = app.query_one("#legacy_app_path", Input)
        field.value = 'export PROFILE="java21"'
        await pilot.pause()

        assert field.value == ""
        assert app.query_one("#profile_id", Input).value == "java21"
        assert app.query_one("#paste_config", TextArea).text == ""
        assert app.query_one("#status", Static).content.startswith(
            "Imported config from pasted shell block"
        )


def test_reset_setup_button_clears_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_reset_setup_button_clears_fields())


async def _assert_reset_setup_button_clears_fields() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(legacy_app_path="/legacy", profile_id="java21")

    async with app.run_test() as pilot:
        app.query_one("#paste_config", TextArea).text = 'export PROFILE="java17"'
        app.query_one("#reset_setup", Button).press()
        await pilot.pause()

        assert app.query_one("#legacy_app_path", Input).value == ""
        assert app.query_one("#profile_id", Input).value == ""
        assert app.query_one("#mode", Input).value == "read_only_assessment"
        assert app.query_one("#paste_config", TextArea).text == ""
        assert app.query_one("#status", Static).content == "Setup fields cleared."


def test_validate_button_failure_updates_status_and_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_validate_button_failure_updates_status_and_preview())


async def _assert_validate_button_failure_updates_status_and_preview() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app.query_one("#validate_paths", Button).press()
        await pilot.pause()

        status = app.query_one("#status", Static).content
        preview = app.query_one("#launch_preview", Static).content
        assert status.startswith("Validation failed:")
        assert "Validation required before launch: yes" in preview
        assert f"Last validation status: {status}" in preview


def test_launch_button_blocks_with_visible_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_launch_button_blocks_with_visible_validation_failure())


async def _assert_launch_button_blocks_with_visible_validation_failure() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app.query_one("#launch_run", Button).press()
        await pilot.pause()

        status = app.query_one("#status", Static).content
        preview = app.query_one("#launch_preview", Static).content
        assert status.startswith("Launch blocked: Validation failed:")
        assert "Last validation status: Validation failed:" in preview


def test_launch_preview_describes_command_and_approval_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_launch_preview_describes_command_and_approval_behavior())


async def _assert_launch_preview_describes_command_and_approval_behavior() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(
        legacy_app_path="/legacy",
        modernized_app_path="/modernized",
        ai_hub_path="/ai-hub",
        profile_id="java21",
        run_id="run-preview",
        mode="full_sandbox_migration",
    )

    async with app.run_test():
        preview = app.query_one("#launch_preview", Static).content

    assert "Command equivalent:" in preview
    assert "--run-id '<generated-on-launch>'" in preview
    assert "Run ID: <generated-on-launch>" in preview
    assert "Current Run ID field: run-preview" in preview
    assert "Run dir: /modernized/.migration/runs/<generated-on-launch>" in preview
    assert "Mode: full_sandbox_migration" in preview
    assert "Profile: java21" in preview
    assert "may continue after approval and run sandbox transform" in preview


def test_save_writes_isolated_config_without_touching_user_config(
    isolated_tui_config_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    user_config_path = CONFIG_PATH
    before = (
        user_config_path.read_bytes()
        if user_config_path.exists()
        else None
    )

    asyncio.run(_assert_save_writes_isolated_config(isolated_tui_config_path))

    after = (
        user_config_path.read_bytes()
        if user_config_path.exists()
        else None
    )
    assert after == before


async def _assert_save_writes_isolated_config(config_path: Path) -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(
        legacy_app_path="/legacy",
        modernized_app_path="/modernized",
        ai_hub_path="/ai-hub",
        profile_id="java21",
        run_id="run-isolated",
    )

    async with app.run_test() as pilot:
        await pilot.press("ctrl+s")

    assert config_path.is_file()
    saved = load_config(config_path)
    assert saved.run_id == "run-isolated"
    assert saved.legacy_app_path == "/legacy"


def test_empty_config_history_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    monkeypatch.setattr("migration_factory.tui.app.CONFIG_PATH", tmp_path / "missing.json")
    asyncio.run(_assert_empty_config_history_message())


async def _assert_empty_config_history_message() -> None:
    app = MigrationFactorySetupApp()

    async with app.run_test():
        assert app.query_one("#dashboard", Static).content == "Set modernized_app_path first."


def test_history_dashboard_renders_markup_like_paths_as_plain_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_history_dashboard_renders_markup_like_paths_as_plain_text(tmp_path))


async def _assert_history_dashboard_renders_markup_like_paths_as_plain_text(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-[warning]"
    summary_dir = run_dir / "orchestration"
    assessment_dir = run_dir / "assessment"
    summary_dir.mkdir(parents=True)
    assessment_dir.mkdir(parents=True)
    (assessment_dir / "assessment_summary.md").write_text(
        "content with [warning] and [/tmp/file]\nC:\\Users\\abc\\[test]\\file.md\n",
        encoding="utf-8",
    )
    (summary_dir / "orchestration_summary.json").write_text(
        """
        {
          "run_id": "run-[warning]",
          "profile_id": "java21",
          "final_status": "DONE[/tmp/file]",
          "warnings": ["contains [warning] text"],
          "artifact_refs": {
            "assessment_summary": "assessment/assessment_summary.md",
            "absolute_summary": "/home/ubuntu/modernized-app/.migration/runs/x/assessment/assessment_summary.md",
            "windows_path": "C:\\\\Users\\\\abc\\\\[test]\\\\file.md"
          }
        }
        """,
        encoding="utf-8",
    )

    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized))

    async with app.run_test():
        dashboard = app.query_one("#dashboard", Static).content

    assert "run-[warning]" in dashboard
    assert "DONE[/tmp/file]" in dashboard
    assert "/home/ubuntu/modernized-app/.migration/runs/x/assessment/assessment_summary.md" in dashboard
    assert "C:\\Users\\abc\\[test]\\file.md" in dashboard
    assert "content with [warning] and [/tmp/file]" in dashboard


def test_failed_analysis_launch_shows_failure_panel_and_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_failed_analysis_launch_shows_failure_panel_and_blockers(tmp_path))


async def _assert_failed_analysis_launch_shows_failure_panel_and_blockers(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-analysis-fail"
    _write_summary(
        run_dir,
        {
            "run_id": "run-analysis-fail",
            "analysis_status": "FAIL",
            "orchestration_status": "FAIL",
            "blockers": ["Analysis modified source files; see read_only_verification.json"],
            "artifact_refs": {"phase1_log": "logs/phase1_analysis.log"},
        },
    )
    result = RunnerLaunchResult(
        run_id="run-analysis-fail",
        returncode=1,
        backend_result={
            "run_id": "run-analysis-fail",
            "analysis_status": "FAIL",
            "blockers": ["Analysis modified source files; see read_only_verification.json"],
        },
        run_dir=run_dir,
        stdout='{"analysis_status": "FAIL"}',
        stderr="",
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized))

    async with app.run_test() as pilot:
        app._show_launch_result(result)
        await pilot.pause()

        assert app.query_one("#launch_result", Static).content == "Run failed before approval"
        assert app.query_one("#approval").display is False
        assert app.query_one("#failure").display is True
        failure = app.query_one("#failure_screen", Static).content
        assert "FAILED AT: Analysis" in failure
        assert "Analysis modified source files" in failure
        assert "Next: Open Details for logs/artifacts" in failure
        app._set_view("details")
        app._update_details_screen()
        await pilot.pause()
        details = app.query_one("#details_content", Static).content
        assert "analysis_status: FAIL" in details
        assert "orchestration_status: FAIL" in details


def test_approval_interrupt_launch_shows_approval_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_approval_interrupt_launch_shows_approval_panel(tmp_path))


async def _assert_approval_interrupt_launch_shows_approval_panel(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-approval"
    _write_summary(
        run_dir,
        {
            "run_id": "run-approval",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "INTERRUPTED",
            "orchestration_status": "INTERRUPTED",
        },
    )
    result = RunnerLaunchResult(
        run_id="run-approval",
        returncode=0,
        backend_result={
            "status": "human_approval_required",
            "run_id": "run-approval",
            "approval_status": "INTERRUPTED",
            "decision_options": ["approved", "rejected"],
        },
        run_dir=run_dir,
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized), mode="full_sandbox_migration")

    async with app.run_test() as pilot:
        app._show_launch_result(result)
        await pilot.pause()

        assert app.query_one("#launch_result", Static).content == "Run reached approval gate"
        assert app.query_one("#approval").display is True
        assert app.query_one("#resume_approval", Button).disabled is False
        assert "Decision options: approved, rejected" in app.query_one("#approval_screen", Static).content
        assert app.query_one("#failure").display is False


def test_approval_button_submits_exact_backend_decision_and_keeps_raw_output_in_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_approval_button_submits_exact_backend_decision_and_keeps_raw_output_in_details(tmp_path))


async def _assert_approval_button_submits_exact_backend_decision_and_keeps_raw_output_in_details(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-approval"
    _write_summary(
        run_dir,
        {
            "run_id": "run-approval",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "INTERRUPTED",
            "orchestration_status": "INTERRUPTED",
            "warnings": ["OpenRewrite impact is high."],
        },
    )
    calls = []

    def fake_resume(*, run_id, run_dir, decision, approved_by, comments=""):
        calls.append(
            {
                "run_id": run_id,
                "decision": decision,
                "approved_by": approved_by,
                "comments": comments,
            }
        )
        return {"status": "running", "approval_status": "COMPLETED", "transform_status": "RUNNING"}

    result = RunnerLaunchResult(
        run_id="run-approval",
        returncode=0,
        backend_result={
            "status": "human_approval_required",
            "run_id": "run-approval",
            "approval_status": "INTERRUPTED",
            "decision_options": ["approved", "rejected", "replan_required"],
            "artifact_refs": {"approval_request": "planning/approval_request.json"},
        },
        run_dir=run_dir,
        stdout=json.dumps({"status": "human_approval_required"}),
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(
        modernized_app_path=str(modernized),
        mode="full_sandbox_migration",
        approved_by="ada",
    )
    app.runner_adapter = app.runner_adapter.__class__(resume_function=fake_resume)

    async with app.run_test() as pilot:
        app._show_launch_result(result)
        await pilot.pause()

        assert app.query_one("#pipeline_table", DataTable).row_count == 10
        assert app.query_one("#run_monitor_status", Static).content == ""
        assert app.query_one("#launch_output", Static).display is False
        assert app.query_one("#launch_output", Static).content == ""

        app._set_view("details")
        app._update_details_screen()
        await pilot.pause()
        assert "analysis_status: PASS" in app.query_one("#details_content", Static).content
        assert "human_approval_required" in app.query_one("#launch_output", Static).content
        app._set_view("run")

        app.query_one("#approve_run", Button).press()
        await pilot.pause()
        await pilot.pause()

        assert calls == [
            {
                "run_id": "run-approval",
                "decision": "approved",
                "approved_by": "ada",
                "comments": "",
            }
        ]
        assert "Decision approved recorded" in app.query_one("#resume_result", Static).content


def test_successful_completed_run_refreshes_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_successful_completed_run_refreshes_history(tmp_path))


async def _assert_successful_completed_run_refreshes_history(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-complete"
    _write_summary(
        run_dir,
        {
            "run_id": "run-complete",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "COMPLETED",
            "orchestration_status": "PASS",
            "final_status": "READ_ONLY_ASSESSMENT_COMPLETE",
        },
    )
    result = RunnerLaunchResult(
        run_id="run-complete",
        returncode=0,
        backend_result={"run_id": "run-complete", "final_status": "READ_ONLY_ASSESSMENT_COMPLETE"},
        run_dir=run_dir,
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized))

    async with app.run_test() as pilot:
        app.runs = []
        app._show_launch_result(result)
        await pilot.pause()

        assert app.query_one("#launch_result", Static).content == "Run completed"
        assert [run.run_id for run in app.runs] == ["run-complete"]
        assert "run-complete" in app.query_one("#dashboard", Static).content


def test_run_and_dashboard_render_copilot_status_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    asyncio.run(_assert_run_and_dashboard_render_copilot_status_read_only(tmp_path))


async def _assert_run_and_dashboard_render_copilot_status_read_only(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-copilot"
    _write_summary(
        run_dir,
        {
            "run_id": "run-copilot",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "COMPLETED",
            "orchestration_status": "PASS",
            "final_status": "READ_ONLY_ASSESSMENT_COMPLETE",
        },
    )
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "configured:gpt-5",
                "connectivity": "connected",
                "report_status": "generated",
            }
        ),
        encoding="utf-8",
    )
    result = RunnerLaunchResult(
        run_id="run-copilot",
        returncode=0,
        backend_result={"run_id": "run-copilot", "final_status": "READ_ONLY_ASSESSMENT_COMPLETE"},
        run_dir=run_dir,
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized))

    async with app.run_test() as pilot:
        app._show_launch_result(result)
        await pilot.pause()

        copilot_status = app.query_one("#copilot_status", Static).content
        assert "Copilot: Connected" in copilot_status
        assert "Provider: github_copilot" in copilot_status
        assert "Model: gpt-5" in copilot_status
        assert "Report: Generated" in copilot_status
        assert "Report generation: Enabled" in copilot_status

        dashboard = app.query_one("#dashboard", Static).content
        assert "Copilot status:" in dashboard
        assert "Copilot: Connected" in dashboard


def test_details_render_default_copilot_status_and_present_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    monkeypatch.setattr(
        "migration_factory.tui.app.get_copilot_status_lines",
        lambda run_dir: [
            "Copilot: Not configured",
            "Provider: github_copilot",
            "Adapter: local_deterministic_template",
            "Model: unknown",
            "Auth: Unknown",
            "CLI: Not installed",
            "Report: Skipped",
        ],
    )
    run_dir = tmp_path / "run-copilot-details"
    final_dir = run_dir / "final"
    final_dir.mkdir(parents=True)
    (final_dir / "copilot_report_request.json").write_text("{}", encoding="utf-8")
    (final_dir / "copilot_migration_report.md").write_text("# report\n", encoding="utf-8")
    vm = _full_sandbox_vm(run_dir=run_dir)

    details = _format_details(vm, dashboard=None)

    assert "Copilot status:" in details
    assert "Copilot: Not configured" in details
    assert "Report: Skipped" in details
    assert "Copilot report artifacts:" in details
    assert f"Copilot report request: {final_dir / 'copilot_report_request.json'}" in details
    assert f"Copilot migration report: {final_dir / 'copilot_migration_report.md'}" in details
    assert "Copilot report response:" not in details


def test_backend_launch_exception_shows_launch_failed_before_run_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_backend_launch_exception_shows_launch_failed_before_run_dir())


async def _assert_backend_launch_exception_shows_launch_failed_before_run_dir() -> None:
    result = RunnerLaunchResult(
        run_id="run-exception",
        returncode=1,
        backend_result={
            "status": "backend_error",
            "message": "cannot start backend",
        },
        run_dir=None,
        stderr="[error] cannot start backend",
    )
    app = MigrationFactorySetupApp()

    async with app.run_test() as pilot:
        app._show_launch_result(result)
        await pilot.pause()

        assert app.query_one("#launch_result", Static).content == (
            "Run launch failed before run_dir was created"
        )
        assert app.query_one("#failure").display is True
        assert "cannot start backend" in app.query_one("#failure_screen", Static).content
        assert app.query_one("#launch_output", Static).content == ""


def test_build_failed_in_sandbox_maps_top_status_failed() -> None:
    vm = _full_sandbox_vm(
        status="BUILD_FAILED_IN_SANDBOX",
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
    )

    assert _view_launch_state(vm) == "Run failed"
    assert _friendly_status(_view_launch_state(vm)) == "Failed"


def test_build_failed_in_sandbox_marks_build_fail_and_tests_skipped() -> None:
    rows = _rows_by_phase(
        _full_sandbox_vm(
            summary={
                "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            }
        )
    )

    assert rows["Sandbox transform"] == "PASS"
    assert rows["Build validation"] == "FAIL"
    assert rows["Test validation"] == "SKIP"
    assert rows["Final report"] == "INCOMPLETE"


def test_build_failure_value_in_transform_field_does_not_mark_transform_pass() -> None:
    rows = _rows_by_phase(
        _full_sandbox_vm(
            summary={
                "transform_status": "BUILD_FAILED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "final_status": "BUILD_FAILED_IN_SANDBOX",
            }
        )
    )

    assert rows["Sandbox transform"] == "INCOMPLETE"
    assert rows["Build validation"] == "FAIL"


def test_sandbox_transform_pass_only_when_transform_succeeded() -> None:
    rows_without_transform = _rows_by_phase(
        _full_sandbox_vm(
            summary={
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            }
        )
    )
    rows_with_transform = _rows_by_phase(
        _full_sandbox_vm(
            summary={
                "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "build_status": "BUILD_FAILED_IN_SANDBOX",
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            }
        )
    )

    assert rows_without_transform["Sandbox transform"] != "PASS"
    assert rows_with_transform["Sandbox transform"] == "PASS"


def test_success_requires_transform_build_and_test_pass() -> None:
    missing_tests = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        }
    )
    complete = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        }
    )

    assert _view_launch_state(missing_tests) == "Run incomplete"
    assert _view_launch_state(complete) == "Run completed"


def test_success_evidence_overrides_final_report_incomplete() -> None:
    vm = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "INCOMPLETE",
        }
    )

    rows = _rows_by_phase(vm)

    assert _view_launch_state(vm) == "Run completed"
    assert _progress_value(vm) == 10
    assert rows["Final report"] == "WARN"


def test_progress_freezes_on_failed_phase() -> None:
    vm = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
        }
    )

    assert _view_launch_state(vm) == "Run failed"
    assert _progress_value(vm) == 7


def test_approval_completed_does_not_stay_waiting() -> None:
    vm = _full_sandbox_vm(
        status="human_approval_required",
        approval_status="INTERRUPTED",
        summary={
            "approval_status": "COMPLETED",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
        },
    )

    assert _friendly_status(_view_launch_state(vm)) == "Success"
    assert _rows_by_phase(vm)["Human approval"] == "PASS"


def test_badge_markup_parses_for_datatable_cells() -> None:
    from rich.text import Text

    assert Text.from_markup(STATE_BADGES["PASS"]).plain == "[ PASS ]"
    assert Text.from_markup(STATE_BADGES["SKIP"]).plain == "[ SKIP ]"
    assert Text.from_markup(BACKEND_BADGES["INTERRUPTED"]).plain == "INTERRUPTED"


def test_theme_registered_without_crashing() -> None:
    app = MigrationFactorySetupApp()

    assert app.theme == "ega-dark"
    assert app.CSS


def test_resume_completion_triggers_final_poll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_resume_completion_triggers_final_poll(tmp_path))


async def _assert_resume_completion_triggers_final_poll(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-resumed"
    _write_summary(
        run_dir,
        {
            "run_id": "run-resumed",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "COMPLETED",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "INCOMPLETE",
        },
    )
    interrupt_dir = run_dir / "orchestration"
    (interrupt_dir / "approval_interrupt_state.json").write_text(
        json.dumps({"run_id": "run-resumed", "approval_status": "INTERRUPTED"}),
        encoding="utf-8",
    )
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(modernized_app_path=str(modernized), run_id="run-resumed")
    app._active_run_dir = run_dir
    app.current_view_model = _full_sandbox_vm(
        status="human_approval_required",
        approval_status="INTERRUPTED",
        summary={"approval_status": "INTERRUPTED"},
    )

    async with app.run_test() as pilot:
        app._show_resume_result(
            RunnerResumeResult(
                run_id="run-resumed",
                decision="approved",
                backend_result={"status": "running", "approval_status": "COMPLETED"},
            )
        )
        await pilot.pause()

        assert app.current_view_model is not None
        assert _view_launch_state(app.current_view_model) == "Run completed"
        assert app.current_approval is None
        assert app.query_one("#launch_result", Static).content == "Run completed"


def test_terminal_timer_stops_on_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_tui_env(monkeypatch)
    asyncio.run(_assert_terminal_timer_stops_on_success(tmp_path))


async def _assert_terminal_timer_stops_on_success(tmp_path: Path) -> None:
    app = MigrationFactorySetupApp()
    app.current_view_model = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
        }
    )

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()
        first = app.query_one("#run_header_line", Static).content
        app._run_started_at = datetime.now(timezone.utc)
        app._update_run_screen()
        await pilot.pause()

        assert app.query_one("#run_header_line", Static).content == first


def test_terminal_run_polls_until_copilot_response_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_tui_env(monkeypatch)
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    asyncio.run(_assert_terminal_run_polls_until_copilot_response_exists(tmp_path))


async def _assert_terminal_run_polls_until_copilot_response_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-copilot-refresh"
    _write_summary(
        run_dir,
        {
            "run_id": "run-copilot-refresh",
            "analysis_status": "PASS",
            "planning_status": "PASS",
            "assessment_status": "PASS",
            "approval_status": "COMPLETED",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
            "final_status": "GENERATED",
        },
    )
    app = MigrationFactorySetupApp()
    app._active_run_dir = run_dir
    app.current_view_model = _full_sandbox_vm(
        run_dir=run_dir,
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
        },
    )

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()

        assert app._should_poll_current_run() is True
        assert "Report: Pending" in app.query_one("#copilot_status", Static).content

        final_dir = run_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "copilot_report_response.json").write_text(
            json.dumps(
                {
                    "provider": "github_copilot",
                    "model": "gpt-5-mini",
                    "connectivity": "connected",
                    "adapter": "copilot_cli",
                    "auth_status": "authenticated",
                    "cli_status": "installed",
                    "report_status": "generated",
                }
            ),
            encoding="utf-8",
        )

        app._poll_current_run()
        await pilot.pause()

        copilot_status = app.query_one("#copilot_status", Static).content
        assert "Adapter: copilot_cli" in copilot_status
        assert "Model: gpt-5-mini" in copilot_status
        assert "Report: Generated" in copilot_status
        assert app._should_poll_current_run() is False


def test_waiting_for_approval_mapping() -> None:
    vm = _full_sandbox_vm(
        status="human_approval_required",
        approval_status="INTERRUPTED",
        summary={"approval_status": "INTERRUPTED"},
    )

    assert _friendly_status(_view_launch_state(vm)) == "Waiting for approval"
    assert _rows_by_phase(vm)["Human approval"] == "WAIT"


def test_failure_summary_content_for_build_failure() -> None:
    vm = _full_sandbox_vm(
        raw_backend={"status": "BUILD_FAILED_IN_SANDBOX"},
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
            "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
    )

    assert _format_failure_from_view(vm) == "\n".join(
        [
            "FAILED AT: Build validation",
            "Reason: status: BUILD_FAILED_IN_SANDBOX",
            "Next: Open Details for logs/artifacts",
        ]
    )


def _write_summary(run_dir: Path, summary: dict) -> None:
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(summary),
        encoding="utf-8",
    )


def _full_sandbox_vm(
    *,
    status: str = "TRANSFORM_APPLIED_IN_SANDBOX",
    approval_status: str = "COMPLETED",
    summary: dict[str, str] | None = None,
    raw_backend: dict | None = None,
    run_dir: Path | None = None,
) -> RunViewModel:
    base_summary = {
        "analysis_status": "PASS",
        "planning_status": "PASS",
        "assessment_status": "PASS",
        "approval_status": approval_status,
        "orchestration_status": "PASS",
    }
    base_summary.update(summary or {})
    return RunViewModel(
        run_id="run-full",
        status=status,
        approval_status=approval_status,
        decision_options=("approved", "rejected", "replan_required"),
        summary=base_summary,
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend=raw_backend or {},
        run_dir=run_dir,
    )


def _rows_by_phase(vm: RunViewModel) -> dict[str, str]:
    return {label: state for label, state, _backend, _marker, _msg in _pipeline_rows(vm)}


def _row_by_key(vm: RunViewModel, key: str):
    return next(row for row in build_pipeline_rows(vm) if row.key == key)


def test_launch_start_keeps_post_approval_phases_not_started() -> None:
    vm = RunViewModel(
        run_id="run-launch",
        status="launching",
        approval_status="",
        decision_options=(),
        summary={},
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={},
        launch_worker_active=True,
    )

    rows = _rows_by_phase(vm)

    assert rows["Preflight"] == "PASS"
    assert rows["Analysis"] == "RUN"
    assert rows["Sandbox transform"] == "TODO"
    assert rows["Final report"] == "TODO"
    assert rows["Copilot docs"] in {"TODO", "SKIP"}


def test_approval_interrupt_keeps_transform_todo_and_wait_marker() -> None:
    vm = _full_sandbox_vm(
        status="human_approval_required",
        approval_status="INTERRUPTED",
        summary={"approval_status": "INTERRUPTED"},
    )

    rows = _rows_by_phase(vm)
    approval = _row_by_key(vm, "human_approval")

    assert rows["Analysis"] == "PASS"
    assert rows["Planning"] == "PASS"
    assert rows["Assessment"] == "PASS"
    assert approval.state == "WAIT"
    assert approval.marker == "⏸"
    assert rows["Sandbox transform"] == "TODO"


def test_approve_clicked_optimistic_mapping_moves_current_to_transform() -> None:
    vm = _full_sandbox_vm(
        status="running",
        approval_status="COMPLETED",
        summary={"approval_status": "INTERRUPTED"},
    )
    vm = RunViewModel(
        **{
            **vm.__dict__,
            "approval_submitted": True,
            "resume_worker_active": True,
            "current_phase": "sandbox_transform",
        }
    )

    approval = _row_by_key(vm, "human_approval")
    transform = _row_by_key(vm, "sandbox_transform")

    assert vm.approval_submitted is True
    assert approval.state in {"PASS", "RUN"}
    assert approval.backend_value == "approved"
    assert approval.message == "Human approved the plan. Continuing to sandbox migration."
    assert transform.state == "RUN"
    assert transform.marker == "▶"
    assert transform.message == "Starting sandbox transform..."


def test_transform_running_inferred_from_phase2_log(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-transform"
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "logs" / "phase2_transform.log").write_text("start\n", encoding="utf-8")

    summary = _summary_with_inferred_artifacts(
        {"approval_status": "COMPLETED"},
        run_dir,
        backend_active=True,
    )
    vm = _full_sandbox_vm(status="running", summary=summary)

    assert _rows_by_phase(vm)["Sandbox transform"] == "RUN"


def test_success_evidence_maps_transform_build_test_pass_and_success_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-success"
    (run_dir / "final").mkdir(parents=True)
    (run_dir / "final" / "migration_summary.md").write_text("ok\n", encoding="utf-8")
    vm = _full_sandbox_vm(
        run_dir=run_dir,
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
        },
    )

    rows = _rows_by_phase(vm)

    assert rows["Sandbox transform"] == "PASS"
    assert rows["Build validation"] == "PASS"
    assert rows["Test validation"] == "PASS"
    assert _current_phase_status_line(vm) == "Migration succeeded."
    assert _normalized_run_state(vm) == "Success"


def test_copilot_report_fallback_warning_does_not_fail_successful_run() -> None:
    vm = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_PASSED_IN_SANDBOX",
            "test_status": "TEST_PASSED",
        },
        raw_backend={
            "warnings": [
                "copilot CLI report generation failed; used deterministic fallback: "
                "FileNotFoundError: Copilot executable path was not resolved for live call"
            ]
        },
    )

    assert _view_launch_state(vm) == "Run completed"
    assert _normalized_run_state(vm) == "Success"


def test_failed_build_maps_normalized_state_failed() -> None:
    vm = _full_sandbox_vm(
        summary={
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
            "build_status": "BUILD_FAILED_IN_SANDBOX",
        }
    )

    assert _normalized_run_state(vm) == "Failed"


def test_preflight_backend_displays_pass_not_started() -> None:
    row = _row_by_key(_full_sandbox_vm(), "preflight")

    assert row.backend_value == "PASS"


def test_details_contains_phase_debug_info() -> None:
    details = _format_details(_full_sandbox_vm(), None)

    assert "Phase states:" in details
    assert "- Analysis: PASS" in details


def test_run_header_uses_config_profile_and_mode() -> None:
    asyncio.run(_assert_run_header_uses_config_profile_and_mode())


async def _assert_run_header_uses_config_profile_and_mode() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(profile_id="java21", mode="full_sandbox_migration")
    app.current_view_model = RunViewModel(
        run_id="run-header",
        status="running",
        approval_status="",
        decision_options=(),
        summary={},
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={},
    )

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()

        header = app.query_one("#run_header_line", Static).content
        assert "Profile: java21" in header
        assert "Mode: full_sandbox_migration" in header
        assert "Profile: -" not in header


def test_run_header_falls_back_to_launch_payload_profile_and_mode() -> None:
    asyncio.run(_assert_run_header_falls_back_to_launch_payload_profile_and_mode())


async def _assert_run_header_falls_back_to_launch_payload_profile_and_mode() -> None:
    app = MigrationFactorySetupApp()
    app.config = TuiConfig(profile_id="", mode="")
    app.current_view_model = RunViewModel(
        run_id="run-header",
        status="running",
        approval_status="",
        decision_options=(),
        summary={},
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={"profile_id": "java17", "mode": "full_sandbox_migration"},
    )

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()

        header = app.query_one("#run_header_line", Static).content
        assert "Profile: java17" in header
        assert "Mode: full_sandbox_migration" in header


def test_run_screen_does_not_render_phase_states_debug() -> None:
    asyncio.run(_assert_run_screen_does_not_render_phase_states_debug())


async def _assert_run_screen_does_not_render_phase_states_debug() -> None:
    app = MigrationFactorySetupApp()
    app.current_view_model = _full_sandbox_vm()

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()

        content = "\n".join(str(node.content) for node in app.query(Static))
        assert "Phase states:" not in content


def test_final_report_and_copilot_docs_not_early() -> None:
    vm = _full_sandbox_vm(
        status="running",
        summary={
            "approval_status": "COMPLETED",
            "transform_status": "TRANSFORM_APPLIED_IN_SANDBOX",
        },
    )

    rows = _rows_by_phase(vm)

    assert rows["Final report"] == "TODO"
    assert rows["Copilot docs"] in {"TODO", "SKIP"}


def test_run_screen_table_refresh_rebuilds_after_approval_submitted() -> None:
    asyncio.run(_assert_run_screen_table_refresh_rebuilds_after_approval_submitted())


async def _assert_run_screen_table_refresh_rebuilds_after_approval_submitted() -> None:
    app = MigrationFactorySetupApp()
    waiting = _full_sandbox_vm(
        status="human_approval_required",
        approval_status="INTERRUPTED",
        summary={"approval_status": "INTERRUPTED"},
    )
    submitted = RunViewModel(
        **{
            **waiting.__dict__,
            "status": "running",
            "approval_status": "COMPLETED",
            "approval_submitted": True,
            "resume_worker_active": True,
            "current_phase": "sandbox_transform",
        }
    )

    async with app.run_test() as pilot:
        app.current_view_model = waiting
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()
        table = app.query_one("#pipeline_table", DataTable)
        assert "Human approval" in [str(cell) for cell in table.get_row_at(4)]
        assert "Sandbox transform" in [str(cell) for cell in table.get_row_at(5)]
        assert app.query_one("#run_monitor_status", Static).content == ""

        app.current_view_model = submitted
        app._update_run_screen()
        await pilot.pause()

        assert app.query_one("#run_monitor_status", Static).content == ""


def test_run_screen_keeps_raw_json_out_of_main_view() -> None:
    asyncio.run(_assert_run_screen_keeps_raw_json_out_of_main_view())


async def _assert_run_screen_keeps_raw_json_out_of_main_view() -> None:
    app = MigrationFactorySetupApp()
    app.current_view_model = RunViewModel(
        run_id="run-json",
        status="running",
        approval_status="",
        decision_options=(),
        summary={},
        blockers=(),
        warnings=(),
        artifact_refs={},
        raw_backend={"secret_json": {"nested": True}},
        stdout=json.dumps({"raw": "stdout"}),
    )

    async with app.run_test() as pilot:
        app._set_view("run")
        app._update_run_screen()
        await pilot.pause()

        main_content = "\n".join(
            str(app.query_one(selector, Static).content)
            for selector in (
                "#run_header_line",
                "#launch_result",
                "#current_phase_line",
                "#run_monitor_status",
                "#approval_screen",
                "#dashboard",
                "#failure_screen",
                "#launch_output",
            )
        )
        assert "secret_json" not in main_content
        assert '"raw": "stdout"' not in main_content
