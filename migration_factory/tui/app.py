from __future__ import annotations

import json
import os
import shlex
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    LoadingIndicator,
    ProgressBar,
    Static,
    TextArea,
)

from migration_factory.tui.config import (
    CONFIG_PATH,
    ConfigError,
    TuiConfig,
    fill_config_from_environment,
    load_config,
    save_config,
)
from migration_factory.tui.copilot_status import get_copilot_status_lines
from migration_factory.tui.history import RunDashboard, discover_run_dashboards, load_run_dashboard
from migration_factory.tui.parser import config_from_paste, parse_config_variables
from migration_factory.tui.runner_adapter import (
    ApprovalState,
    RunnerAdapter,
    RunnerLaunchResult,
    RunnerResumeResult,
    format_backend_result,
    format_resume_result,
)
from migration_factory.tui.theme import BACKEND_BADGES, EGA_CSS, STATE_BADGES, register_ega_theme
from migration_factory.tui.validation import validate_setup


_SETUP_INPUT_IDS = {
    "legacy_app_path",
    "modernized_app_path",
    "ai_hub_path",
    "profile_id",
    "mode",
    "approved_by",
    "run_id",
}
_CONFIG_INPUT_IDS = {
    *_SETUP_INPUT_IDS,
    "source_jdk_home",
    "target_jdk_home",
    "active_java_home",
}
_MONITOR_STATUS_KEYS = (
    "analysis_status",
    "planning_status",
    "assessment_status",
    "approval_status",
    "transform_status",
    "build_status",
    "test_status",
    "orchestration_status",
)
_PRE_APPROVAL_STATUS_KEYS = ("analysis_status", "planning_status", "assessment_status")
_FAIL_VALUES = {"FAIL", "FAILED", "ERROR"}
_BUILD_PASS_VALUES = {"BUILD_PASSED_IN_SANDBOX", "PASS", "PASSED"}
_TEST_PASS_VALUES = {"TEST_PASSED", "PASS", "PASSED"}
_TRUE_SUCCESS_VALUES = {
    "PASS",
    "PASSED",
    "COMPLETED",
    "DONE",
    "READ_ONLY_ASSESSMENT_COMPLETE",
    "BUILD_PASSED_IN_SANDBOX",
    "TESTS_PASSED_IN_SANDBOX",
}
_COMPLETED_STATUSES = {
    "COMPLETED",
    "DONE",
    "READ_ONLY_ASSESSMENT_COMPLETE",
}
_APPROVAL_DECISIONS = ("approved", "rejected", "replan_required")
_PIPELINE_PHASES = (
    ("preflight", "Preflight"),
    ("analysis", "Analysis"),
    ("planning", "Planning"),
    ("assessment", "Assessment"),
    ("human_approval", "Human approval"),
    ("sandbox_transform", "Sandbox transform"),
    ("build_validation", "Build validation"),
    ("test_validation", "Test validation"),
    ("final_report", "Final report"),
    ("copilot_docs", "Copilot docs"),
)
_FAILURE_ARTIFACTS = (
    ("orchestration summary", "orchestration/orchestration_summary.json"),
    ("phase2 log", "logs/phase2_transform.log"),
    ("build error json", "build/build_error.json"),
    ("test summary", "test/post_transform/test_summary.md"),
    ("read_only_verification.json", "analysis/read_only_verification.json"),
    ("analysis_summary.md", "analysis/analysis_summary.md"),
)
_COPILOT_REPORT_ENV = "AI_MIGRATION_ENABLE_COPILOT_REPORT"
_COPILOT_REPORT_ARTIFACTS = (
    ("Copilot report request", "final/copilot_report_request.json"),
    ("Copilot report response", "final/copilot_report_response.json"),
    ("Copilot migration report", "final/copilot_migration_report.md"),
)


@dataclass(frozen=True)
class RunViewModel:
    run_id: str
    status: str
    approval_status: str
    decision_options: tuple[str, ...]
    summary: dict[str, str]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    artifact_refs: dict[str, str]
    raw_backend: dict[str, Any]
    stdout: str = ""
    stderr: str = ""
    run_dir: Path | None = None
    returncode: int = 0
    launch_worker_active: bool = False
    resume_worker_active: bool = False
    approval_submitted: bool = False
    approval_pending: bool = False
    terminal_success: bool = False
    terminal_failed: bool = False
    current_phase: str = ""

    @property
    def approval_required(self) -> bool:
        return (
            self.status == "human_approval_required"
            or self.approval_status == "INTERRUPTED"
            or self.approval_pending
        )


@dataclass(frozen=True)
class PipelineRow:
    key: str
    phase_name: str
    state: str
    backend_value: str
    marker: str
    message: str


class DashboardScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main"):
            with Vertical(id="dashboard_panel", classes="panel"):
                yield Label("Migration Ops", markup=False)
                yield Static("", id="setup_summary", markup=False)
                yield Static("", id="copilot_status", markup=False)
                with Horizontal(classes="button_row"):
                    yield Button("Launch run", id="launch_run", variant="primary")
                    yield Button("Refresh history", id="refresh_history")
                    yield Button("Setup", id="focus_setup")
                    yield Button("Quit", id="quit_app")
            with Horizontal(id="dashboard_columns"):
                with Vertical(id="setup", classes="panel"):
                    yield Label("Setup", markup=False)
                    yield Label("Legacy app", classes="field_label", id="legacy_app_path_label", markup=False)
                    yield Input(value=self.app.config.legacy_app_path, placeholder="legacy_app_path", id="legacy_app_path")
                    yield Label("Modernized app", classes="field_label", id="modernized_app_path_label", markup=False)
                    yield Input(value=self.app.config.modernized_app_path, placeholder="modernized_app_path", id="modernized_app_path")
                    yield Label("AI Hub", classes="field_label", id="ai_hub_path_label", markup=False)
                    yield Input(value=self.app.config.ai_hub_path, placeholder="ai_hub_path", id="ai_hub_path")
                    yield Label("Profile", classes="field_label", id="profile_id_label", markup=False)
                    yield Input(value=self.app.config.profile_id, placeholder="profile_id", id="profile_id")
                    yield Label("Mode", classes="field_label", id="mode_label", markup=False)
                    yield Input(value=self.app.config.mode, placeholder="mode", id="mode")
                    yield Static(
                        "Default: read_only_assessment. read_only_assessment = assessment only; "
                        "full_sandbox_migration = approval may run sandbox transform.",
                        id="mode_help",
                        markup=False,
                    )
                    yield Label("Approved by", classes="field_label", id="approved_by_label", markup=False)
                    yield Input(value=self.app.config.approved_by, placeholder="approved_by", id="approved_by")
                    yield Label("Run ID", classes="field_label", id="run_id_label", markup=False)
                    yield Input(value=self.app.config.run_id, placeholder="run_id optional", id="run_id")
                    with Horizontal(classes="button_row"):
                        yield Button("Save config", id="save_config")
                        yield Button("Validate paths", id="validate_paths")
                        yield Button("Reset/Clear setup", id="reset_setup")
                with Vertical(id="environment", classes="panel"):
                    yield Label("Environment", markup=False)
                    yield Label("Source JDK / JAVA8_HOME", classes="field_label", id="source_jdk_home_label", markup=False)
                    yield Input(value=self.app.config.source_jdk_home, placeholder="source_jdk_home optional", id="source_jdk_home")
                    yield Label("Target JDK / JAVA21_HOME", classes="field_label", id="target_jdk_home_label", markup=False)
                    yield Input(value=self.app.config.target_jdk_home, placeholder="target_jdk_home optional", id="target_jdk_home")
                    yield Label("Active JAVA_HOME", classes="field_label", id="active_java_home_label", markup=False)
                    yield Input(value=self.app.config.active_java_home, placeholder="active_java_home from JAVA_HOME", id="active_java_home")
                    yield Label("Paste Config Import", markup=False)
                    yield TextArea("", id="paste_config", language=None)
                    with Horizontal(classes="button_row"):
                        yield Button("Import pasted config", id="import_pasted_config")
                        yield Button("Resume approval", id="resume_approval")
                    yield Static(
                        "Paste PowerShell $LEGACY_APP = \"...\" or Bash export LEGACY_APP=\"$HOME/...\". "
                        "Ctrl+I imports, Ctrl+S saves, Ctrl+V validates, Ctrl+R refreshes history, Ctrl+L launches run.",
                        id="help",
                        markup=False,
                    )
                    yield Static(self.app.load_error or "Ready.", id="status", markup=False)
                    yield Static("Run launch status will appear after launch.", id="launch_result", markup=False)
                    yield Static(_format_launch_preview(self.app.config), id="launch_preview", markup=False)
                with Vertical(id="history", classes="panel"):
                    yield Label("Run History", markup=False)
                    yield ListView(id="run_list")
                    yield Static("No run selected.", id="dashboard", markup=False)
            with Vertical(id="approval", classes="panel"):
                yield Label("Approval Required", markup=False)
                yield Static("", id="approval_screen", markup=False)
            yield Static("", id="resume_result", markup=False)
        if False:
            yield Footer()

    def on_mount(self) -> None:
        self.app._refresh_dashboard_widgets()
        approval_panel = list(self.query("#approval"))
        if approval_panel:
            approval_panel[0].display = False


class RunScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main"):
            # Compact header line
            yield Static("Run: - | Profile: - | Mode: - | State: -", id="run_header_line", markup=False)
            # Launch status
            yield Static("", id="launch_result", markup=False)
            # Pipeline table
            yield Label("Pipeline", markup=False)
            yield DataTable(id="pipeline_table")
            # Current phase/status line
            yield Static("", id="current_phase_line", markup=False)
            yield Static("", id="copilot_status", markup=False)
            # Run monitor status (textual summary for backward compatibility)
            yield Static("", id="run_monitor_status", markup=False)
            # Approval panel (only shown when waiting for approval)
            with Vertical(id="approval", classes="panel"):
                yield Label("Approval Required", markup=False)
                yield Static("", id="approval_screen", markup=False)
                yield Static("", id="resume_result", markup=False)
                with Horizontal(classes="button_row"):
                    yield Button("Approve", id="approve_run", variant="success")
                    yield Button("Reject", id="reject_run", variant="error")
                    yield Button("Replan", id="replan_run", variant="warning")
                    yield Button("Resume approval", id="resume_approval")
                    yield Button("Details", id="view_details_from_run")
                    yield Button("Back to dashboard", id="back_dashboard_from_run")
            yield Static("", id="dashboard", markup=False)
            # Failure panel
            with Vertical(id="failure", classes="panel"):
                yield Label("Failure", markup=False)
                yield Static("", id="failure_screen", markup=False)
            # Action row: Details, Back to dashboard
            with Horizontal(classes="button_row"):
                yield Button("Details", id="view_details")
                yield Button("Back to dashboard", id="back_dashboard")
            yield Static("", id="launch_output")
        if False:
            yield Footer()

    def on_mount(self) -> None:
        self.app._update_run_screen()


class DetailsScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main"):
            with Vertical(id="details_panel", classes="panel"):
                yield Label("Run Details", markup=False)
                yield Static("", id="details_header", markup=False)
                yield Static("", id="details_content", markup=False)
                yield Static("", id="launch_output", markup=False)
            with Horizontal(classes="button_row"):
                yield Button("Back to run", id="back_run")
                yield Button("Back to dashboard", id="back_dashboard")
        if False:
            yield Footer()

    def on_mount(self) -> None:
        self.app._update_details_screen()


class ApprovalModal(ModalScreen[str | None]):
    def compose(self) -> ComposeResult:
        with Vertical(id="approval_modal", classes="panel"):
            yield Label("Approval Required", markup=False)
            yield Static(
                "This continues sandbox transform only; legacy app remains unchanged.",
                id="approval_modal_warning",
                markup=False,
            )
            yield Static("", id="approval_modal_body", markup=False)
            with Horizontal(classes="button_row"):
                yield Button("Approve", id="modal_approve_run", variant="success")
                yield Button("Reject", id="modal_reject_run", variant="error")
                yield Button("Replan Required", id="modal_replan_run", variant="warning")
                yield Button("Cancel", id="modal_cancel_approval")

    def on_mount(self) -> None:
        body = self.query_one("#approval_modal_body", Static)
        body.update(_format_approval(self.app.current_approval))
        vm = self.app.current_view_model
        options = set(vm.decision_options if vm is not None else _APPROVAL_DECISIONS)
        for button_id, decision in (
            ("modal_approve_run", "approved"),
            ("modal_reject_run", "rejected"),
            ("modal_replan_run", "replan_required"),
        ):
            button = self.query_one(f"#{button_id}", Button)
            button.disabled = decision not in options

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decisions = {
            "modal_approve_run": "approved",
            "modal_reject_run": "rejected",
            "modal_replan_run": "replan_required",
            "modal_cancel_approval": None,
        }
        if event.button.id in decisions:
            self.dismiss(decisions[event.button.id])


class MigrationFactorySetupApp(App[None]):
    TITLE = "Migration Ops"
    SUB_TITLE = "Setup, launch, and approval console"

    CSS = EGA_CSS

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("ctrl+i", "import_config", "Import paste"),
        ("ctrl+v", "validate", "Validate"),
        ("ctrl+l", "launch_run", "Launch run"),
        ("ctrl+a", "resume_approval", "Resume approval"),
        ("ctrl+r", "refresh_history", "Refresh history"),
        ("escape", "back_dashboard", "Back"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        register_ega_theme(self)
        saved_config_exists = CONFIG_PATH.exists()
        try:
            self.config = load_config(CONFIG_PATH)
            self.load_error = ""
        except ConfigError as exc:
            self.config = TuiConfig()
            self.load_error = str(exc)
        self.config, self.env_imported_keys = fill_config_from_environment(
            self.config,
            saved_config_exists=saved_config_exists,
        )
        self.runs: list[RunDashboard] = []
        self.runner_adapter = RunnerAdapter()
        self.current_approval: ApprovalState | None = None
        self.current_result: RunnerLaunchResult | None = None
        self.current_resume_result: RunnerResumeResult | None = None
        self.current_dashboard: RunDashboard | None = None
        self.current_view_model: RunViewModel | None = None
        self.last_validation_status = "Not validated yet."
        self._writing_config = False
        self._active_run_dir: Path | None = None
        self._backend_active = False
        self._run_started_at: datetime | None = None
        self._terminal_elapsed_label: str | None = None
        self._awaiting_copilot_response = False

    def compose(self) -> ComposeResult:
        if False:
            yield Footer()

    def get_default_screen(self) -> Screen:
        return DashboardScreen()

    def _get_dom_base(self) -> Screen:
        return self.screen

    def on_mount(self) -> None:
        self.install_screen(DashboardScreen(), name="dashboard")
        self.install_screen(RunScreen(), name="run")
        self.install_screen(DetailsScreen(), name="details")
        self.set_interval(1, self._poll_current_run)
        approval_panel = list(self.query("#approval"))
        if approval_panel:
            approval_panel[0].display = False
        failure_panel = list(self.query("#failure"))
        if failure_panel:
            failure_panel[0].display = False
        self._refresh_history()
        self._refresh_approval_from_file(show_status=False)

    def action_save(self) -> None:
        self.config = self._read_config()
        save_config(self.config)
        self._refresh_launch_preview()
        self._update_static("#status", "Saved ~/.ega-migration/config.json")

    def action_validate(self) -> None:
        self.config = self._read_config()
        result = validate_setup(self.config)
        message = "Validation passed" if result.ok else f"Validation failed: {result.message}"
        self.last_validation_status = message
        self._refresh_launch_preview()
        self._update_static("#status", message)

    def action_launch_run(self) -> None:
        self.config = self._read_config()
        validation = validate_setup(self.config)
        self.last_validation_status = "Validation passed" if validation.ok else f"Validation failed: {validation.message}"
        self._refresh_launch_preview()
        if not validation.ok:
            self._update_static("#status", f"Launch blocked: {self.last_validation_status}")
            return
        run_id = self.runner_adapter.next_run_id()
        run_dir = Path(self.config.modernized_app_path).expanduser() / ".migration" / "runs" / run_id
        self.config.run_id = run_id
        self._active_run_dir = run_dir
        self._backend_active = True
        self._run_started_at = datetime.now(timezone.utc)
        self._terminal_elapsed_label = None
        self.current_view_model = RunViewModel(
            run_id=run_id,
            status="launching",
            approval_status="",
            decision_options=(),
            summary={},
            blockers=(),
            warnings=(),
            artifact_refs={},
            raw_backend={},
            run_dir=run_dir,
            launch_worker_active=True,
            current_phase="analysis",
        )
        self._set_view("run")
        self._update_run_screen()
        self.run_worker(lambda: self._launch_run_worker(run_id), thread=True)

    def action_refresh_history(self) -> None:
        self.config = self._read_config()
        self._refresh_launch_preview()
        self._refresh_history()
        self._refresh_approval_from_file(show_status=False)
        self._update_static(
            "#status",
            f"History refreshed: {len(self.runs)} run(s) found."
            if self.config.modernized_app_path.strip()
            else "History refreshed. Set modernized_app_path first.",
        )

    def action_import_config(self) -> None:
        matches = list(self.query("#paste_config"))
        content = matches[0].text if matches and isinstance(matches[0], TextArea) else ""
        self._import_config_text(content)

    def action_reset_setup(self) -> None:
        self.config = TuiConfig()
        self._write_config(self.config)
        matches = list(self.query("#paste_config"))
        if matches and isinstance(matches[0], TextArea):
            matches[0].text = ""
        self.last_validation_status = "Not validated yet."
        self._refresh_launch_preview()
        self._update_static("#status", "Setup fields cleared.")

    def action_resume_approval(self) -> None:
        if self.current_approval is None:
            self._refresh_approval_from_file(show_status=False)
        if self.current_approval is None:
            self._show_resume_error("No approval interrupt loaded.")
            return
        self.push_screen(ApprovalModal(), self._handle_approval_modal_decision)

    def action_back_dashboard(self) -> None:
        self._set_view("dashboard")
        self._refresh_dashboard_widgets()

    def on_paste(self, event: events.Paste) -> None:
        focused = self.focused
        if (
            isinstance(focused, Input)
            and focused.id in _SETUP_INPUT_IDS
            and _looks_like_config_paste(event.text)
        ):
            event.prevent_default()
            event.stop()
            self._import_config_text(event.text, from_normal_field=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._writing_config:
            return
        if event.input.id in _SETUP_INPUT_IDS and _looks_like_config_paste(event.value):
            self._import_config_text(
                event.value,
                from_normal_field=True,
                polluted_input_id=event.input.id,
            )
            return
        if event.input.id in _CONFIG_INPUT_IDS:
            self._refresh_launch_preview()
            self._refresh_setup_summary()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "import_pasted_config":
            self.action_import_config()
        elif button_id == "save_config":
            self.action_save()
        elif button_id == "validate_paths":
            self.action_validate()
        elif button_id == "refresh_history":
            self.action_refresh_history()
        elif button_id == "launch_run":
            self.action_launch_run()
        elif button_id == "resume_approval":
            self.action_resume_approval()
        elif button_id == "reset_setup":
            self.action_reset_setup()
        elif button_id == "quit_app":
            self.action_quit()
        elif button_id == "focus_setup":
            matches = list(self.query("#legacy_app_path"))
            if matches:
                matches[0].focus()
        elif button_id == "approve_run":
            self._resume_with_decision("approved")
        elif button_id == "reject_run":
            self._resume_with_decision("rejected")
        elif button_id == "replan_run":
            self._resume_with_decision("replan_required")
        elif button_id == "view_details":
            self._set_view("details")
            self._update_details_screen()
        elif button_id == "back_run":
            self._set_view("run")
            self._update_run_screen()
        elif button_id in {"back_dashboard", "back_dashboard_details"}:
            self.action_back_dashboard()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "run_list":
            return
        index = event.list_view.index
        if index is not None and 0 <= index < len(self.runs):
            self._update_static("#dashboard", _format_dashboard(self.runs[index]))

    def _set_view(self, view_name: str) -> None:
        try:
            current_screen = self.screen
            current_name = current_screen.name
        except Exception:
            current_screen = None
            current_name = ""
        if current_name == view_name:
            return
        if view_name == "dashboard" and isinstance(current_screen, DashboardScreen):
            return
        if view_name == "dashboard":
            if len(self.screen_stack) > 1:
                self.pop_screen()
            else:
                self.switch_screen(view_name)
            return
        if isinstance(current_screen, DashboardScreen):
            self.push_screen(view_name)
            return
        if current_name in {None, "", "_default"}:
            self.push_screen(view_name)
            return
        self.switch_screen(view_name)

    def _read_config(self) -> TuiConfig:
        values = self.config.__dict__.copy()
        for field_name in TuiConfig.__dataclass_fields__:
            matches = list(self.query(f"#{field_name}"))
            if matches and isinstance(matches[0], Input):
                values[field_name] = matches[0].value
        return TuiConfig(**values)

    def _write_config(self, config: TuiConfig) -> None:
        self._writing_config = True
        try:
            for field_name in config.__dataclass_fields__:
                matches = list(self.query(f"#{field_name}"))
                if matches and isinstance(matches[0], Input):
                    matches[0].value = getattr(config, field_name)
        finally:
            self._writing_config = False
        self._refresh_launch_preview()
        self._refresh_setup_summary()

    def _import_config_text(
        self,
        content: str,
        *,
        from_normal_field: bool = False,
        polluted_input_id: str | None = None,
    ) -> None:
        imported = parse_config_variables(content)
        next_config = config_from_paste(content, base=self._read_config())
        if polluted_input_id and polluted_input_id not in imported:
            setattr(next_config, polluted_input_id, "")
        self.config = next_config
        self._write_config(self.config)
        keys = ", ".join(sorted(imported)) if imported else "none"
        matches = list(self.query("#paste_config"))
        if imported and matches and isinstance(matches[0], TextArea):
            matches[0].text = ""
        message = (
            "Imported config from pasted shell block"
            if from_normal_field and imported
            else "Imported pasted config into setup fields"
        )
        self._update_static("#status", f"{message}. Keys: {keys}")

    def _refresh_dashboard_widgets(self) -> None:
        self._write_config(self.config)
        self._refresh_history()
        self._refresh_setup_summary()
        self._show_approval()

    def _refresh_setup_summary(self) -> None:
        config = self._read_config()
        self._update_static(
            "#setup_summary",
            "\n".join(
                [
                    f"Profile: {config.profile_id or '-'}",
                    f"Mode: {config.mode or '-'}",
                    f"Legacy: {_path_name(config.legacy_app_path)}",
                    _format_target_summary(config),
                ]
            ),
        )
        if self.current_view_model is not None and self.current_view_model.run_dir is not None:
            self._update_static(
                "#copilot_status",
                _format_copilot_status(
                    self.current_view_model.run_dir,
                    active_run=not _terminal_from_vm(self.current_view_model) or self._waiting_for_copilot_response(),
                ),
            )
        else:
            self._update_static("#copilot_status", _format_copilot_status(None, prefer_response=False, active_run=False))

    def _refresh_launch_preview(self) -> None:
        matches = list(self.query("#launch_preview"))
        if matches:
            matches[0].update(
                _format_launch_preview(
                    self._read_config(),
                    validation_status=self.last_validation_status,
                )
            )

    def _refresh_history(self) -> None:
        self.runs = discover_run_dashboards(self.config)
        matches = list(self.query("#run_list"))
        if not matches or not isinstance(matches[0], ListView):
            return
        run_list = matches[0]
        run_list.clear()

        for run in self.runs:
            run_list.append(ListItem(Label(f"{run.run_id}  {run.final_status}", markup=False), name=run.run_id))

        if self.runs:
            run_list.index = 0
            self._update_static("#dashboard", _format_dashboard(self.runs[0]))
        else:
            self._update_static(
                "#dashboard",
                "No runs found under modernized_app_path/.migration/runs."
                if self.config.modernized_app_path.strip()
                else "Set modernized_app_path first.",
            )

    def _launch_run_worker(self, run_id: str) -> None:
        result = self.runner_adapter.launch(self.config, run_id=run_id)
        self.call_from_thread(self._show_launch_result, result)

    def _show_launch_result(self, result: RunnerLaunchResult) -> None:
        self._backend_active = False
        self._active_run_dir = result.run_dir or self._active_run_dir
        self.current_result = result
        self.current_resume_result = None
        self.config.run_id = result.run_id
        self._write_config(self.config)
        self._refresh_history()
        self.current_dashboard = _find_run_dashboard(self.runs, result)
        if result.human_approval_required:
            self.current_approval = self.runner_adapter.load_approval_state(self.config, payload=result.backend_result)
        else:
            self.current_approval = None
        self.current_view_model = _view_model_from_launch(result, self.current_dashboard, self.current_approval)
        self._set_view("run")
        self._update_run_screen()
        if self.current_dashboard is not None:
            self._update_static("#dashboard", _format_dashboard(self.current_dashboard))

    def _refresh_approval_from_file(self, *, show_status: bool = True) -> None:
        self.current_approval = self.runner_adapter.load_approval_state(self.config)
        self._show_approval()
        if show_status and self.current_approval is not None:
            self._update_static("#status", "Approval interrupt loaded.")

    def _show_approval(self) -> None:
        self._update_static("#approval_screen", _format_approval(self.current_approval))
        matches = list(self.query("#resume_approval"))
        if matches and isinstance(matches[0], Button):
            matches[0].disabled = self.current_approval is None

    def _handle_approval_modal_decision(self, decision: str | None) -> None:
        if decision is not None:
            self._resume_with_decision(decision)

    def _resume_with_decision(self, decision: str) -> None:
        if decision not in _APPROVAL_DECISIONS:
            self._show_resume_error(f"Unsupported approval decision: {decision}")
            return
        self.config = self._read_config()
        if self.current_approval is None:
            self._refresh_approval_from_file(show_status=False)
        if self.current_approval is None:
            self._show_resume_error("No approval interrupt loaded.")
            return
        approved_by = self.config.approved_by.strip()
        self._update_static("#resume_result", "Resuming orchestration...")
        self._backend_active = True
        self._active_run_dir = self.current_approval.run_dir
        if self._run_started_at is None:
            self._run_started_at = datetime.now(timezone.utc)
        self._terminal_elapsed_label = None
        if decision == "approved":
            self._update_static("#run_warning_blocker_summary", "Approval will continue sandbox transform only; legacy app remains unchanged.")
            if self.current_view_model is not None:
                summary = dict(self.current_view_model.summary)
                summary["approval_status"] = "COMPLETED"
                self.current_view_model = replace(
                    self.current_view_model,
                    status="running",
                    approval_status="COMPLETED",
                    summary=summary,
                    approval_submitted=True,
                    approval_pending=False,
                    resume_worker_active=True,
                    current_phase="sandbox_transform",
                )
                self._set_view("run")
                self._update_run_screen()
            self._update_static("#status", "Approval submitted. Resuming sandbox migration...")
        else:
            if self.current_view_model is not None:
                self.current_view_model = replace(
                    self.current_view_model,
                    status=decision,
                    approval_submitted=False,
                    approval_pending=False,
                    resume_worker_active=True,
                    terminal_failed=True,
                    current_phase="human_approval",
                )
                self._set_view("run")
                self._update_run_screen()
        self.run_worker(
            lambda: self._resume_approval_worker(
                self.current_approval,
                decision=decision,
                approved_by=approved_by,
                comments="",
            ),
            thread=True,
        )

    def _resume_approval_worker(
        self,
        approval: ApprovalState,
        *,
        decision: str,
        approved_by: str,
        comments: str,
    ) -> None:
        try:
            result = self.runner_adapter.resume(
                approval,
                decision=decision,
                approved_by=approved_by,
                comments=comments,
            )
        except Exception as exc:
            self.call_from_thread(self._show_resume_error, str(exc))
            return
        self.call_from_thread(self._show_resume_result, result)

    def _show_resume_error(self, message: str) -> None:
        self._backend_active = False
        if self.current_view_model is not None:
            self.current_view_model = replace(
                self.current_view_model,
                resume_worker_active=False,
                terminal_failed=True,
                current_phase=self.current_view_model.current_phase or "human_approval",
            )
        self._update_static("#resume_result", f"Resume failed: {message}")
        self._update_static("#status", f"Resume failed: {message}")

    def _show_resume_result(self, result: RunnerResumeResult) -> None:
        self._backend_active = False
        self.current_resume_result = result
        status = (
            f"Decision {result.decision} recorded; orchestration stopped."
            if result.stopped
            else "Decision approved recorded; orchestration resumed."
        )
        self._update_static("#resume_result", status)
        self._update_static("#status", status)
        self._force_poll_from_active_run()
        self._refresh_history()
        self.current_dashboard = _find_run_dashboard_by_id(self.runs, result.run_id) or self.current_dashboard
        self.current_view_model = _view_model_from_resume(
            result,
            self.current_view_model,
            self.current_dashboard,
        )
        if result.decision == "approved" or _terminal_from_vm(self.current_view_model):
            self.current_approval = None
        self._set_view("run")
        self._update_run_screen()

    def _poll_current_run(self) -> None:
        if self._active_run_dir is None:
            return
        if not self._should_poll_current_run():
            return

        self._force_poll_from_active_run()
        self._update_run_screen()
        if _file_exists(_copilot_response_path(self._active_run_dir)):
            self._awaiting_copilot_response = False

    def _should_poll_current_run(self) -> bool:
        if self._backend_active:
            return True
        if self.current_view_model is not None and not _terminal_from_vm(self.current_view_model):
            return True
        if self._waiting_for_copilot_response():
            self._awaiting_copilot_response = True
            return True
        if (
            self._awaiting_copilot_response
            and self._active_run_dir is not None
            and _file_exists(_copilot_response_path(self._active_run_dir))
        ):
            return True
        if self._active_run_dir is None:
            return False
        return _file_exists(self._active_run_dir / "orchestration" / "approval_interrupt_state.json")

    def _waiting_for_copilot_response(self) -> bool:
        if self._active_run_dir is None or not _copilot_report_enabled():
            return False
        if self.current_view_model is None or not _terminal_from_vm(self.current_view_model):
            return False
        return not _file_exists(_copilot_response_path(self._active_run_dir))

    def _force_poll_from_active_run(self) -> None:
        if self._active_run_dir is None:
            return
        dashboard: RunDashboard | None = None
        try:
            dashboard = load_run_dashboard(self._active_run_dir)
        except Exception:
            dashboard = None

        if dashboard is not None:
            self.current_dashboard = dashboard

        approval_payload = _load_json(self._active_run_dir / "orchestration" / "approval_interrupt_state.json")
        approval = None
        dashboard_summary = _summary_with_final(dashboard) if dashboard is not None else {}
        if (
            approval_payload
            and dashboard_summary.get("approval_status") != "COMPLETED"
            and not _is_terminal_summary(dashboard_summary, None)
        ):
            approval = self.runner_adapter.load_approval_state(self.config, payload=approval_payload)
        elif (
            self.current_approval is not None
            and self.current_view_model is not None
            and self.current_view_model.approval_required
            and dashboard_summary.get("approval_status") != "COMPLETED"
            and not _is_terminal_summary(dashboard_summary, None)
        ):
            approval = self.current_approval
        self.current_approval = approval

        if self.current_view_model is None:
            self.current_view_model = _view_model_from_poll(
                run_id=self.config.run_id or self._active_run_dir.name,
                run_dir=self._active_run_dir,
                dashboard=dashboard,
                approval=self.current_approval,
                backend_active=self._backend_active,
            )
        else:
            self.current_view_model = _merge_poll_view_model(
                self.current_view_model,
                dashboard,
                self.current_approval,
                backend_active=self._backend_active,
            )

    def _update_run_screen(self) -> None:
        vm = self.current_view_model
        if vm is None:
            return
        launch_state = _view_launch_state(vm)
        # Update compact header line
        profile, mode = _run_identity(self.config, vm)
        self._update_static(
            "#run_header_line",
            f"Run: {vm.run_id or '-'} | Profile: {profile} | Mode: {mode} | State: {_normalized_run_state(vm)}",
        )
        self._update_static("#launch_result", launch_state)
        self._update_pipeline_table(vm)
        # Update current phase/status line
        self._update_static("#current_phase_line", _current_phase_status_line(vm))
        self._update_static(
            "#copilot_status",
            _format_copilot_status(vm.run_dir, active_run=not _terminal_from_vm(vm) or self._waiting_for_copilot_response()),
        )
        # Handle approval panel visibility
        approval_panel = list(self.query("#approval"))
        if approval_panel:
            approval_panel[0].display = vm.approval_required
        self._show_approval_buttons(vm)
        self._update_static("#approval_screen", _format_approval(self.current_approval) if vm.approval_required else "")
        # Update run monitor status for backward compatibility with tests
        self._update_static("#run_monitor_status", "")
        if self.current_dashboard is not None:
            self._update_static("#dashboard", _format_dashboard(self.current_dashboard))
        failure = _format_failure_from_view(vm)
        failure_panel = list(self.query("#failure"))
        if failure_panel:
            failure_panel[0].display = bool(failure)
        self._update_static("#failure_screen", failure)

    def _show_approval_buttons(self, vm: RunViewModel) -> None:
        options = set(vm.decision_options or _APPROVAL_DECISIONS)
        for button_id, decision in (
            ("approve_run", "approved"),
            ("reject_run", "rejected"),
            ("replan_run", "replan_required"),
        ):
            matches = list(self.query(f"#{button_id}"))
            if matches and isinstance(matches[0], Button):
                matches[0].disabled = decision not in options
        matches = list(self.query("#resume_approval"))
        if matches and isinstance(matches[0], Button):
            matches[0].disabled = not vm.approval_required

    def _update_pipeline_table(self, vm: RunViewModel) -> None:
        matches = list(self.query("#pipeline_table"))
        if not matches or not isinstance(matches[0], DataTable):
            return
        table = matches[0]
        table.clear(columns=True)
        table.add_columns("Now", "State", "Phase", "Backend", "Message")
        for phase_name, state, backend_value, phase_marker, message in _pipeline_rows(vm):
            backend_badge = _backend_badge_key(backend_value)
            table.add_row(
                phase_marker,
                Text.from_markup(STATE_BADGES.get(state, state)),
                phase_name,
                Text.from_markup(BACKEND_BADGES.get(backend_badge, backend_value or "-")),
                message,
            )

    def _update_details_screen(self) -> None:
        vm = self.current_view_model
        if vm is None:
            self._update_static("#details_header", "No run loaded.")
            self._update_static("#details_content", "")
            return
        self._update_static("#details_header", f"Run: {vm.run_id}")
        self._update_static("#details_content", _format_details(vm, self.current_dashboard))
        self._update_static("#launch_output", _format_raw_output(vm))

    def _update_static(self, selector: str, content: str) -> None:
        for match in self.query(selector):
            if isinstance(match, Static):
                match.update(content)


def _view_model_from_launch(
    result: RunnerLaunchResult,
    dashboard: RunDashboard | None,
    approval: ApprovalState | None,
) -> RunViewModel:
    payload = result.backend_result
    summary_payload = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    summary = _summary_with_inferred_artifacts(_merged_statuses(result, dashboard), result.run_dir, backend_active=False)
    for key in ("analysis_status", "planning_status", "assessment_status"):
        value = _string_value(summary_payload.get(key))
        if value:
            summary[key] = value
    artifact_refs = _artifact_refs(payload.get("artifact_refs"))
    if dashboard is not None:
        artifact_refs.update({ref.name: ref.raw_ref for ref in dashboard.report_refs})
    if approval is not None:
        artifact_refs.update(approval.artifact_refs)
    return RunViewModel(
        run_id=result.run_id,
        status=_string_value(payload.get("status")) or _launch_state(result, dashboard),
        approval_status=_string_value(payload.get("approval_status")) or summary.get("approval_status", ""),
        decision_options=_decision_options(payload.get("decision_options"), approval),
        summary=summary,
        blockers=_items(payload.get("blockers"), dashboard.blockers if dashboard else ()),
        warnings=_items(payload.get("warnings"), dashboard.warnings if dashboard else ()),
        artifact_refs=artifact_refs,
        raw_backend=payload,
        stdout=result.stdout,
        stderr=result.stderr,
        run_dir=result.run_dir,
        returncode=result.returncode,
        launch_worker_active=False,
        approval_pending=approval is not None,
        terminal_success=_summary_success(summary, _string_value(payload.get("status"))),
        terminal_failed=_summary_failed(summary) or _is_failure_status(_string_value(payload.get("status"))),
    )


def _view_model_from_resume(
    result: RunnerResumeResult,
    previous: RunViewModel | None,
    dashboard: RunDashboard | None,
) -> RunViewModel:
    payload = result.backend_result
    summary = dict(previous.summary) if previous is not None else {}
    if dashboard is not None:
        summary.update(dashboard.statuses)
    for key in _MONITOR_STATUS_KEYS:
        value = _string_value(payload.get(key))
        if value:
            summary[key] = value
    summary = _summary_with_inferred_artifacts(
        summary,
        previous.run_dir if previous is not None else None,
        backend_active=False,
    )
    if result.decision == "approved":
        summary["approval_status"] = _string_value(payload.get("approval_status")) or "COMPLETED"
    status = _string_value(payload.get("status")) or _string_value(payload.get("final_status"))
    if not status:
        status = "running" if result.decision == "approved" else result.decision
    artifact_refs = dict(previous.artifact_refs) if previous is not None else {}
    artifact_refs.update(_artifact_refs(payload.get("artifact_refs")))
    return RunViewModel(
        run_id=result.run_id,
        status=status,
        approval_status=summary.get("approval_status", ""),
        decision_options=previous.decision_options if previous is not None else _APPROVAL_DECISIONS,
        summary=summary,
        blockers=_items(payload.get("blockers"), dashboard.blockers if dashboard else ()),
        warnings=_items(payload.get("warnings"), dashboard.warnings if dashboard else ()),
        artifact_refs=artifact_refs,
        raw_backend=payload,
        stdout=previous.stdout if previous is not None else "",
        stderr=previous.stderr if previous is not None else "",
        run_dir=previous.run_dir if previous is not None else None,
        returncode=0,
        launch_worker_active=False,
        resume_worker_active=False,
        approval_submitted=result.decision == "approved",
        approval_pending=False,
        terminal_success=_summary_success(summary, status),
        terminal_failed=result.stopped or _summary_failed(summary) or _is_failure_status(status),
        current_phase="" if result.decision == "approved" else "human_approval",
    )


def _view_model_from_poll(
    *,
    run_id: str,
    run_dir: Path,
    dashboard: RunDashboard | None,
    approval: ApprovalState | None,
    backend_active: bool,
) -> RunViewModel:
    summary = _summary_with_inferred_artifacts(_summary_with_final(dashboard), run_dir, backend_active=backend_active)
    artifact_refs = {ref.name: ref.raw_ref for ref in dashboard.report_refs} if dashboard is not None else {}
    if approval is not None:
        artifact_refs.update(approval.artifact_refs)
    return RunViewModel(
        run_id=run_id,
        status=_status_from_summary(summary, backend_active=backend_active, approval=approval),
        approval_status=(approval and "INTERRUPTED") or summary.get("approval_status", ""),
        decision_options=approval.decision_options if approval is not None else _APPROVAL_DECISIONS,
        summary=summary,
        blockers=dashboard.blockers if dashboard is not None else (),
        warnings=dashboard.warnings if dashboard is not None else (),
        artifact_refs=artifact_refs,
        raw_backend={},
        run_dir=run_dir,
        launch_worker_active=backend_active,
        resume_worker_active=backend_active and summary.get("approval_status") == "COMPLETED",
        approval_submitted=summary.get("approval_status") == "COMPLETED" and backend_active,
        approval_pending=approval is not None,
        terminal_success=_summary_success(summary, summary.get("final_status", "")),
        terminal_failed=_summary_failed(summary),
    )


def _merge_poll_view_model(
    previous: RunViewModel,
    dashboard: RunDashboard | None,
    approval: ApprovalState | None,
    *,
    backend_active: bool,
) -> RunViewModel:
    summary = dict(previous.summary)
    if dashboard is not None:
        summary.update(_summary_with_final(dashboard))
    summary = _summary_with_inferred_artifacts(summary, previous.run_dir, backend_active=backend_active or previous.resume_worker_active)
    artifact_refs = dict(previous.artifact_refs)
    if dashboard is not None:
        artifact_refs.update({ref.name: ref.raw_ref for ref in dashboard.report_refs})
    if approval is not None:
        artifact_refs.update(approval.artifact_refs)
    status = previous.status
    if backend_active and not _is_terminal_summary(summary, approval):
        status = "running"
    elif approval is not None:
        status = "human_approval_required"
    else:
        status = _status_from_summary(summary, backend_active=False, approval=None)
    return RunViewModel(
        run_id=previous.run_id,
        status=status,
        approval_status=(approval and "INTERRUPTED") or summary.get("approval_status", ""),
        decision_options=approval.decision_options if approval is not None else previous.decision_options,
        summary=summary,
        blockers=_items(None, dashboard.blockers if dashboard is not None else previous.blockers),
        warnings=_items(None, dashboard.warnings if dashboard is not None else previous.warnings),
        artifact_refs=artifact_refs,
        raw_backend=previous.raw_backend,
        stdout=previous.stdout,
        stderr=previous.stderr,
        run_dir=previous.run_dir,
        returncode=previous.returncode,
        launch_worker_active=backend_active and not previous.approval_submitted,
        resume_worker_active=backend_active and previous.approval_submitted,
        approval_submitted=previous.approval_submitted or summary.get("approval_status") == "COMPLETED",
        approval_pending=approval is not None,
        terminal_success=_summary_success(summary, status),
        terminal_failed=_summary_failed(summary) or _is_failure_status(status),
        current_phase=previous.current_phase,
    )


def _summary_with_final(dashboard: RunDashboard | None) -> dict[str, str]:
    if dashboard is None:
        return {}
    summary = dict(dashboard.statuses)
    if dashboard.final_status:
        summary["final_status"] = dashboard.final_status
    return summary


def _summary_with_inferred_artifacts(
    summary: dict[str, str],
    run_dir: Path | None,
    *,
    backend_active: bool,
) -> dict[str, str]:
    if run_dir is None:
        return summary
    inferred = dict(summary)
    transform_log = run_dir / "logs" / "phase2_transform.log"
    if (
        backend_active
        and transform_log.is_file()
        and not inferred.get("transform_status")
        and inferred.get("approval_status") != "INTERRUPTED"
    ):
        inferred["transform_status"] = "RUNNING"

    build_error = run_dir / "build" / "build_error.json"
    if build_error.is_file() and not inferred.get("build_status"):
        inferred["build_status"] = "BUILD_FAILED_IN_SANDBOX"
    for rel_path in ("build/build_summary.json", "build/build_result.json"):
        payload = _load_json(run_dir / rel_path)
        if payload and not inferred.get("build_status"):
            status = _string_value(payload.get("build_status") or payload.get("status"))
            if status:
                inferred["build_status"] = status

    test_summary = run_dir / "test" / "post_transform" / "test_summary.md"
    if test_summary.is_file() and not inferred.get("test_status"):
        text = _read_text(test_summary).upper()
        inferred["test_status"] = "TEST_FAILED" if "FAIL" in text or "ERROR" in text else "TEST_PASSED"
    for rel_path in ("test/post_transform/test_summary.json", "test/post_transform/test_result.json"):
        payload = _load_json(run_dir / rel_path)
        if payload and not inferred.get("test_status"):
            status = _string_value(payload.get("test_status") or payload.get("status"))
            if status:
                inferred["test_status"] = status
            for key in ("failures", "errors", "test_failures", "test_errors"):
                value = _string_value(payload.get(key))
                if value:
                    inferred[key] = value

    if _has_any_file(run_dir, ("final/migration_report.json", "final/migration_summary.md")):
        inferred.setdefault("final_report_status", "GENERATED")
    if _has_any_file(
        run_dir,
        (
            "final/copilot_docs/migration_overview.md",
            "final/copilot_docs/technical_changes.md",
            "final/copilot_docs/validation_evidence.md",
            "final/copilot_docs/risks_and_warnings.md",
            "final/copilot_docs/copilot_review.md",
        ),
    ):
        inferred.setdefault("copilot_docs_status", "GENERATED")
    return inferred


def _status_from_summary(
    summary: dict[str, str],
    *,
    backend_active: bool,
    approval: ApprovalState | None,
) -> str:
    if backend_active and not _is_terminal_summary(summary, approval):
        return "running"
    if approval is not None:
        return "human_approval_required"
    if _summary_failed(summary):
        return "failed"
    if _summary_success(summary, summary.get("final_status", "")):
        return "success"
    return summary.get("final_status") or "incomplete"


def _format_dashboard(run: RunDashboard) -> str:
    lines = [
        f"Run: {run.run_id}",
        f"Profile: {run.profile or '-'}",
        f"Final status: {run.final_status}",
        f"Run dir: {run.run_dir}",
        f"Orchestration summary: {run.summary_path}",
        "",
        "Copilot status:",
        *_format_copilot_status_lines(run.run_dir),
        "",
        "Statuses:",
    ]
    if run.statuses:
        lines.extend(f"- {key}: {value}" for key, value in run.statuses.items())
    else:
        lines.append("- none recorded")
    lines.extend(["", "Blockers:"])
    lines.extend(f"- {item}" for item in run.blockers) if run.blockers else lines.append("- none")
    lines.extend(["", "Warnings:"])
    lines.extend(f"- {item}" for item in run.warnings) if run.warnings else lines.append("- none")
    lines.extend(["", "Artifact/log paths:"])
    if run.report_refs:
        for ref in run.report_refs:
            path = str(ref.path) if ref.path is not None else f"unsafe ref: {ref.raw_ref}"
            lines.append(f"- {_friendly_artifact_name(ref.name)}: {path}")
    else:
        lines.append("- none recorded")

    lines.extend(["", "Report/log viewers:"])
    if run.artifact_viewers:
        for viewer in run.artifact_viewers:
            path = str(viewer.path) if viewer.path is not None else "-"
            tail_marker = " (tail)" if viewer.tail else ""
            lines.append(f"- {viewer.label}{tail_marker}: {viewer.status} [{path}]")
            if viewer.content:
                lines.extend(_indent_viewer_content(viewer.content))
    else:
        lines.append("- none recorded")
    return "\n".join(lines)


def _find_run_dashboard(runs: list[RunDashboard], result: RunnerLaunchResult) -> RunDashboard | None:
    for run in runs:
        if run.run_id == result.run_id:
            return run
    if result.run_dir is not None:
        for run in runs:
            if run.run_dir == result.run_dir:
                return run
    return None


def _find_run_dashboard_by_id(runs: list[RunDashboard], run_id: str) -> RunDashboard | None:
    for run in runs:
        if run.run_id == run_id:
            return run
    return None


def _launch_state(result: RunnerLaunchResult, dashboard: RunDashboard | None) -> str:
    statuses = _merged_statuses(result, dashboard)
    if result.human_approval_required:
        return "Run reached approval gate"
    if any(_is_failure_status(statuses.get(key)) for key in _PRE_APPROVAL_STATUS_KEYS):
        return "Run failed before approval"
    if _summary_failed(statuses):
        return "Run failed"
    if result.run_dir is None or (
        result.returncode != 0
        and result.backend_result.get("status") == "backend_error"
        and not result.run_dir.exists()
    ):
        return "Run launch failed before run_dir was created"
    final_status = dashboard.final_status if dashboard is not None else _string_value(result.backend_result.get("final_status"))
    if _summary_success(statuses, final_status):
        return "Run completed"
    if result.returncode != 0:
        return "Run failed"
    return "Run incomplete"


def _view_launch_state(vm: RunViewModel) -> str:
    if vm.approval_required and not _summary_success(vm.summary, vm.status):
        return "Run reached approval gate"
    if any(_is_failure_status(vm.summary.get(key)) for key in _PRE_APPROVAL_STATUS_KEYS):
        return "Run failed before approval"
    if (
        _summary_failed(vm.summary)
        or _is_failure_status(vm.status)
        or _backend_failed(vm.raw_backend)
        or _test_counts_failed(vm.summary)
        or _test_counts_failed(vm.raw_backend)
    ):
        return "Run failed"
    if vm.status in {"backend_error"} and vm.run_dir is None:
        return "Run launch failed before run_dir was created"
    if _summary_success(vm.summary, vm.status):
        return "Run completed"
    if vm.returncode != 0:
        return "Run failed"
    if vm.status == "running":
        return "Run running"
    return "Run incomplete"


def _pipeline_rows(vm: RunViewModel) -> list[tuple[str, str, str, str, str]]:
    return [
        (row.phase_name, row.state, row.backend_value, row.marker, row.message)
        for row in build_pipeline_rows(vm)
    ]


def build_pipeline_rows(vm: RunViewModel) -> list[PipelineRow]:
    states: dict[str, str] = {}
    backend: dict[str, str] = {}

    backend["preflight"] = "backend_error" if vm.status == "backend_error" else "PASS"
    states["preflight"] = "FAIL" if vm.status == "backend_error" else "PASS"

    analysis = _phase_status_value(vm, "analysis_status")
    planning = _phase_status_value(vm, "planning_status")
    assessment = _phase_status_value(vm, "assessment_status")
    backend["analysis"] = analysis
    backend["planning"] = planning
    backend["assessment"] = assessment

    states["analysis"] = _preapproval_phase_state("analysis", analysis, vm, prior_pass=True)
    states["planning"] = _preapproval_phase_state("planning", planning, vm, prior_pass=states["analysis"] == "PASS")
    states["assessment"] = _preapproval_phase_state("assessment", assessment, vm, prior_pass=states["planning"] == "PASS")

    approval = _phase_status_value(vm, "approval_status") or vm.approval_status
    backend["human_approval"] = approval
    approval_upper = approval.upper()
    if vm.status in {"rejected", "replan_required"}:
        states["human_approval"] = "FAIL"
        backend["human_approval"] = vm.status
    elif vm.approval_submitted:
        states["human_approval"] = "PASS"
        backend["human_approval"] = "approved"
    elif approval_upper == "COMPLETED":
        states["human_approval"] = "PASS"
    elif approval_upper == "INTERRUPTED" or vm.approval_required:
        states["human_approval"] = "WAIT"
    else:
        states["human_approval"] = "TODO"

    transform = _phase_status_value(vm, "transform_status")
    backend["sandbox_transform"] = transform
    transform_upper = transform.upper()
    if "BUILD_FAILED" in transform_upper:
        states["sandbox_transform"] = "INCOMPLETE"
    elif _is_failure_status(transform_upper):
        states["sandbox_transform"] = "FAIL"
    elif transform_upper == "TRANSFORM_APPLIED_IN_SANDBOX":
        states["sandbox_transform"] = "PASS"
    elif vm.status in {"rejected", "replan_required"}:
        states["sandbox_transform"] = "SKIP"
    elif approval_upper == "INTERRUPTED" and not vm.approval_submitted:
        states["sandbox_transform"] = "TODO"
    elif vm.approval_submitted or vm.resume_worker_active or transform_upper == "RUNNING":
        states["sandbox_transform"] = "RUN"
    elif transform:
        states["sandbox_transform"] = "INCOMPLETE"
    else:
        states["sandbox_transform"] = "TODO"

    build = _phase_status_value(vm, "build_status")
    backend["build_validation"] = build
    build_upper = build.upper()
    if _is_failure_status(build_upper):
        states["build_validation"] = "FAIL"
    elif build_upper == "BUILD_PASSED_IN_SANDBOX":
        states["build_validation"] = "PASS"
    elif states["sandbox_transform"] == "PASS" and (vm.resume_worker_active or vm.status == "running"):
        states["build_validation"] = "RUN"
    elif build:
        states["build_validation"] = "INCOMPLETE"
    else:
        states["build_validation"] = "TODO"

    test = _phase_status_value(vm, "test_status")
    backend["test_validation"] = test
    test_upper = test.upper()
    if states["build_validation"] == "FAIL":
        states["test_validation"] = "SKIP"
    elif _test_counts_failed(vm.summary) or _test_counts_failed(vm.raw_backend) or _is_failure_status(test_upper):
        states["test_validation"] = "FAIL"
    elif test_upper == "TEST_PASSED":
        states["test_validation"] = "PASS"
    elif states["build_validation"] == "PASS" and (vm.resume_worker_active or vm.status == "running"):
        states["test_validation"] = "RUN"
    elif test:
        states["test_validation"] = "INCOMPLETE"
    else:
        states["test_validation"] = "TODO"

    backend["final_report"] = _phase_status_value(vm, "final_status") or _phase_status_value(vm, "final_report_status")
    report_terminal = states["build_validation"] == "FAIL" or states["test_validation"] in {"PASS", "FAIL"}
    if report_terminal and _has_final_report(vm):
        states["final_report"] = "PASS"
        backend["final_report"] = backend["final_report"] or "GENERATED"
    elif report_terminal and _backend_says_generated(vm, "final"):
        states["final_report"] = "PASS"
        backend["final_report"] = backend["final_report"] or "GENERATED"
    elif report_terminal and vm.status == "running":
        states["final_report"] = "RUN"
    elif report_terminal and _summary_success(vm.summary, vm.status):
        states["final_report"] = "WARN"
    elif report_terminal and (states["build_validation"] == "FAIL" or states["test_validation"] == "FAIL"):
        states["final_report"] = "INCOMPLETE"
    else:
        states["final_report"] = "TODO"

    backend["copilot_docs"] = _phase_status_value(vm, "copilot_docs_status")
    if states["final_report"] == "PASS" and (_has_copilot_docs(vm) or _backend_says_generated(vm, "copilot")):
        states["copilot_docs"] = "PASS"
        backend["copilot_docs"] = backend["copilot_docs"] or "GENERATED"
    elif states["final_report"] in {"PASS", "RUN"}:
        states["copilot_docs"] = "TODO"
    else:
        states["copilot_docs"] = "SKIP"

    current_key = _current_phase_key(vm, states)
    rows: list[PipelineRow] = []
    for key, label in _PIPELINE_PHASES:
        state = states[key]
        rows.append(
            PipelineRow(
                key=key,
                phase_name=label,
                state=state,
                backend_value=backend.get(key, ""),
                marker=_phase_marker(key, state, current_key),
                message=_phase_message(key, state, vm),
            )
        )
    return rows


def _phase_status_value(vm: RunViewModel, key: str) -> str:
    return _string_value(vm.summary.get(key)) or _string_value(vm.raw_backend.get(key))


def _preapproval_phase_state(key: str, value: str, vm: RunViewModel, *, prior_pass: bool) -> str:
    upper = value.upper()
    if upper == "PASS":
        return "PASS"
    if _is_failure_status(upper):
        return "FAIL"
    if value:
        return "INCOMPLETE"
    if not prior_pass:
        return "TODO"
    if key == "analysis" and vm.launch_worker_active:
        return "RUN"
    if key == "planning" and vm.launch_worker_active:
        return "RUN"
    if key == "assessment" and vm.launch_worker_active:
        return "RUN"
    return "TODO"


def _current_phase_key(vm: RunViewModel, states: dict[str, str]) -> str:
    if vm.current_phase and states.get(vm.current_phase) in {"RUN", "WAIT", "FAIL"}:
        return vm.current_phase
    for key in ("analysis", "planning", "assessment", "human_approval", "sandbox_transform", "build_validation", "test_validation", "final_report"):
        if states.get(key) in {"RUN", "WAIT", "FAIL"}:
            return key
    return ""


def _phase_marker(key: str, state: str, current_key: str) -> str:
    if state == "PASS":
        return "✓"
    if state == "FAIL":
        return "✗"
    if state == "WAIT":
        return "⏸"
    if key == current_key and state == "RUN":
        return "▶"
    return "·"


def _phase_message(key: str, state: str, vm: RunViewModel) -> str:
    if key == "analysis":
        return {"RUN": "Running analysis...", "PASS": "Analysis completed", "FAIL": "Analysis failed"}.get(state, "Waiting to start analysis...")
    if key == "planning":
        return {"RUN": "Running planning...", "PASS": "Planning completed", "FAIL": "Planning failed"}.get(state, "Waiting to start planning...")
    if key == "assessment":
        return {"RUN": "Running assessment...", "PASS": "Assessment completed", "FAIL": "Assessment failed"}.get(state, "Waiting to start assessment...")
    if key == "human_approval":
        if vm.approval_submitted and state == "PASS":
            return "Human approved the plan. Continuing to sandbox migration."
        return {
            "WAIT": "Human approval required. Choose Approve, Reject, or Replan.",
            "RUN": "Approval submitted. Resuming sandbox migration...",
            "PASS": "Approval completed",
            "FAIL": "Approval stopped",
        }.get(state, "Waiting for approval...")
    if key == "sandbox_transform":
        if state == "RUN" and vm.approval_submitted and not _transform_passed(vm):
            return "Starting sandbox transform..."
        return {"RUN": "Running sandbox transform...", "PASS": "Sandbox transform completed", "FAIL": "Sandbox transform failed"}.get(state, "Waiting to start sandbox transform...")
    if key == "build_validation":
        return {"RUN": "Running build validation...", "PASS": "Build validation passed", "FAIL": "Build validation failed"}.get(state, "Waiting to start build validation...")
    if key == "test_validation":
        return {"RUN": "Running test validation...", "PASS": "Test validation passed", "FAIL": "Test validation failed"}.get(state, "Waiting to start test validation...")
    if key == "final_report":
        return {"RUN": "Generating final report...", "PASS": "Final report generated"}.get(state, "Waiting to generate final report...")
    if key == "copilot_docs":
        return {"PASS": "Copilot docs generated"}.get(state, "Waiting to generate Copilot docs...")
    return ""


def _current_phase_status_line(vm: RunViewModel) -> str:
    rows = build_pipeline_rows(vm)
    current = next((row for row in rows if row.marker in {"▶", "⏸"}), None)
    if current is not None:
        if current.key == "sandbox_transform" and vm.approval_submitted and not _transform_passed(vm):
            return "Human approved the plan. Continuing to sandbox migration."
        return current.message
    failed = next((row for row in rows if row.state == "FAIL"), None)
    if failed is not None:
        return f"Migration failed at {failed.phase_name}: {_failure_reason(vm)}"
    if _summary_success(vm.summary, vm.status):
        return "Migration succeeded."
    return ""


def _state_marker(state: str) -> str:
    return {
        "PASS": "[PASS]",
        "FAIL": "[FAIL]",
        "WAIT": "[WAIT]",
        "RUN": "[RUN]",
        "INCOMPLETE": "[INCOMPLETE]",
        "TODO": "[TODO]",
        "SKIP": "[SKIP]",
        "WARN": "[WARN]",
    }[state]


def _format_run_monitor_from_view(vm: RunViewModel) -> str:
    rows = _pipeline_rows(vm)
    current = next((label for label, state, _value, _marker, _msg in rows if state in {"RUN", "WAIT", "FAIL", "INCOMPLETE"}), rows[-1][0])
    latest = _latest_short_message(vm)
    lines = [
        f"Run: {vm.run_id or '-'}",
        f"Status: {_friendly_status(_view_launch_state(vm))}",
        f"Current phase: {current}",
        f"Latest: {latest}",
        "",
        "Phase states:",
    ]
    lines.extend(f"- {label}: {state} ({backend or '-'})" for label, state, backend, _marker, _msg in rows)
    lines.extend(["", "Statuses:"])
    lines.extend(f"- {key}: {vm.summary.get(key) or '-'}" for key in _MONITOR_STATUS_KEYS)
    return "\n".join(lines)


def _format_warning_blockers(vm: RunViewModel) -> str:
    lines: list[str] = []
    if vm.approval_required and "approved" in vm.decision_options:
        lines.extend(["Approval:", "- Approval will continue sandbox transform only; legacy app remains unchanged."])
    lines.append("Blockers:")
    lines.extend(f"- {item}" for item in vm.blockers[:3]) if vm.blockers else lines.append("- none")
    lines.append("Warnings:")
    lines.extend(f"- {item}" for item in vm.warnings[:3]) if vm.warnings else lines.append("- none")
    return "\n".join(lines)


def _format_failure_from_view(vm: RunViewModel) -> str:
    if _view_launch_state(vm) not in {"Run failed", "Run failed before approval", "Run launch failed before run_dir was created"}:
        return ""
    return "\n".join(
        [
            f"FAILED AT: {_failed_phase(vm)}",
            f"Reason: {_failure_reason(vm)}",
            "Next: Open Details for logs/artifacts",
        ]
    )


def _format_details(vm: RunViewModel, dashboard: RunDashboard | None) -> str:
    lines = [
        "Backend result:",
        json.dumps(vm.raw_backend, indent=2, sort_keys=True, default=str),
        "",
        "Copilot status:",
        *_format_copilot_status_lines(vm.run_dir),
        "",
        _format_run_monitor_from_view(vm),
        "",
        "Artifact refs:",
    ]
    if vm.artifact_refs:
        lines.extend(f"- {name}: {ref}" for name, ref in sorted(vm.artifact_refs.items()))
    else:
        lines.append("- none recorded")
    raw_output = _format_raw_output(vm)
    if raw_output:
        lines.extend(["", "Raw stdout/stderr:", raw_output])
    if dashboard is not None:
        lines.extend(["", f"Run dir: {dashboard.run_dir}", f"Orchestration summary: {dashboard.summary_path}", "", "Report/log viewers:"])
        if dashboard.artifact_viewers:
            for viewer in dashboard.artifact_viewers:
                path = str(viewer.path) if viewer.path is not None else "-"
                tail_marker = " (tail)" if viewer.tail else ""
                lines.append(f"- {viewer.label}{tail_marker}: {viewer.status} [{path}]")
                if viewer.content:
                    lines.extend(_indent_viewer_content(viewer.content))
        else:
            lines.append("- none recorded")
    if vm.run_dir is not None:
        copilot_paths = _present_copilot_report_paths(vm.run_dir)
        if copilot_paths:
            lines.extend(["", "Copilot report artifacts:"])
            lines.extend(f"- {label}: {path}" for label, path in copilot_paths)
        lines.extend(["", "Failure artifact fallbacks:"])
        lines.extend(f"- {label}: {vm.run_dir / rel_path}" for label, rel_path in _FAILURE_ARTIFACTS)
    return "\n".join(lines)


def _format_copilot_status(
    run_dir: Path | None,
    *,
    prefer_response: bool = True,
    active_run: bool = False,
) -> str:
    return "\n".join(
        _format_copilot_status_lines(run_dir, prefer_response=prefer_response, active_run=active_run)
    )


def _format_copilot_status_lines(
    run_dir: Path | None,
    *,
    prefer_response: bool = True,
    active_run: bool = False,
) -> list[str]:
    try:
        return get_copilot_status_lines(run_dir, prefer_response=prefer_response, active_run=active_run)
    except TypeError:
        return get_copilot_status_lines(run_dir)


def _copilot_report_enabled() -> bool:
    return os.environ.get(_COPILOT_REPORT_ENV, "").strip().lower() == "true"


def _copilot_response_path(run_dir: Path) -> Path:
    return run_dir / "final" / "copilot_report_response.json"


def _present_copilot_report_paths(run_dir: Path) -> list[tuple[str, Path]]:
    paths: list[tuple[str, Path]] = []
    for label, rel_path in _COPILOT_REPORT_ARTIFACTS:
        path = run_dir / rel_path
        try:
            is_present = path.is_file()
        except OSError:
            is_present = False
        if is_present:
            paths.append((label, path))
    return paths


def _format_raw_output(vm: RunViewModel) -> str:
    parts: list[str] = []
    if vm.stdout.strip():
        parts.extend(["stdout tail:", _tail_lines(vm.stdout)])
    if vm.stderr.strip():
        if parts:
            parts.append("")
        parts.extend(["stderr tail:", _tail_lines(vm.stderr)])
    if parts:
        return "\n".join(parts)
    return format_backend_result(
        RunnerLaunchResult(
            run_id=vm.run_id,
            returncode=vm.returncode,
            backend_result=vm.raw_backend,
            run_dir=vm.run_dir,
        )
    )


def _merged_statuses(result: RunnerLaunchResult, dashboard: RunDashboard | None) -> dict[str, str]:
    statuses = dict(dashboard.statuses) if dashboard is not None else {}
    for key in _MONITOR_STATUS_KEYS:
        value = _string_value(result.backend_result.get(key))
        if value:
            statuses[key] = value
    final_status = _string_value(result.backend_result.get("final_status"))
    if final_status:
        statuses["final_status"] = final_status
    elif dashboard is not None and dashboard.final_status:
        statuses["final_status"] = dashboard.final_status
    return statuses


def _decision_options(value: Any, approval: ApprovalState | None = None) -> tuple[str, ...]:
    options = tuple(option for option in _items(value) if option in _APPROVAL_DECISIONS)
    if options:
        return options
    if approval is not None and approval.decision_options:
        return approval.decision_options
    return _APPROVAL_DECISIONS


def _artifact_refs(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(raw_ref) for key, raw_ref in value.items() if raw_ref}


def _items(value: Any, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    items: list[str] = []
    if isinstance(value, (list, tuple)):
        items.extend(str(item) for item in value if item is not None)
    elif value:
        items.append(str(value))
    items.extend(extra)
    return tuple(dict.fromkeys(items))


def _tail_lines(text: str, *, limit: int = 80) -> str:
    lines = text.splitlines()
    if len(lines) <= limit:
        return text.strip()
    return "\n".join(["... truncated ...", *lines[-limit:]])


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _has_any_file(run_dir: Path, rel_paths: tuple[str, ...]) -> bool:
    return any((run_dir / rel_path).is_file() for rel_path in rel_paths)


def _is_failed(value: str | None) -> bool:
    return (value or "").upper() in _FAIL_VALUES


def _is_failure_status(value: str | None) -> bool:
    upper = (value or "").upper()
    return upper in _FAIL_VALUES or "FAIL" in upper or "FAILED" in upper


def _summary_failed(summary: dict[str, str]) -> bool:
    return any(_is_failure_status(value) for value in summary.values()) or _test_counts_failed(summary)


def _summary_success(summary: dict[str, str], status: str = "") -> bool:
    final_status = (summary.get("final_status") or status or "").upper()
    full_sandbox_passed = (
        summary.get("transform_status", "").upper() == "TRANSFORM_APPLIED_IN_SANDBOX"
        and summary.get("build_status", "").upper() == "BUILD_PASSED_IN_SANDBOX"
        and summary.get("test_status", "").upper() == "TEST_PASSED"
        and not _summary_failed(summary)
    )
    if full_sandbox_passed:
        return True
    if final_status == "TRANSFORM_APPLIED_IN_SANDBOX":
        return (
            summary.get("transform_status", "").upper() == "TRANSFORM_APPLIED_IN_SANDBOX"
            and summary.get("build_status", "").upper() == "BUILD_PASSED_IN_SANDBOX"
            and summary.get("test_status", "").upper() == "TEST_PASSED"
            and not _summary_failed(summary)
        )
    if final_status in _COMPLETED_STATUSES:
        return not _summary_failed(summary)
    return False


def _is_terminal_summary(summary: dict[str, str], approval: ApprovalState | None) -> bool:
    if approval is not None:
        return False
    return _summary_failed(summary) or _summary_success(summary, summary.get("final_status", ""))


def _latest_short_message(vm: RunViewModel) -> str:
    for item in (*vm.blockers[:1], *vm.warnings[:1]):
        if item:
            return item[:160]
    for key in reversed(_MONITOR_STATUS_KEYS):
        value = vm.summary.get(key)
        if value:
            return f"{key}: {value}"
    if vm.raw_backend.get("message"):
        return str(vm.raw_backend["message"])[:160]
    return vm.status or "-"


def _failed_phase(vm: RunViewModel) -> str:
    for label, state, _value, _marker, _msg in _pipeline_rows(vm):
        if state == "FAIL":
            return label
    return "unknown"


def _failure_reason(vm: RunViewModel) -> str:
    raw_status = _string_value(vm.raw_backend.get("status"))
    if _is_failure_status(raw_status) and raw_status != "backend_error":
        return f"status: {raw_status}"
    if vm.raw_backend.get("message"):
        return str(vm.raw_backend["message"])
    if vm.blockers:
        return vm.blockers[0]
    for key in (
        "final_status",
        "orchestration_status",
        "build_status",
        "test_status",
        "transform_status",
        "approval_status",
    ):
        value = _string_value(vm.raw_backend.get(key)) or vm.summary.get(key, "")
        if _is_failure_status(value):
            return f"{key}: {value}"
    if _test_counts_failed(vm.raw_backend) or _test_counts_failed(vm.summary):
        failures = _string_value(vm.raw_backend.get("failures") or vm.summary.get("failures") or 0)
        errors = _string_value(vm.raw_backend.get("errors") or vm.summary.get("errors") or 0)
        return f"test counts: failures={failures}, errors={errors}"
    if vm.run_dir is None:
        return "run_dir was not created"
    return _latest_short_message(vm)


def _progress_value(vm: RunViewModel) -> int:
    rows = _pipeline_rows(vm)
    launch_state = _view_launch_state(vm)
    if launch_state == "Run completed":
        return len(rows)
    for index, (_label, state, _value, _marker, _msg) in enumerate(rows):
        if state in {"FAIL", "WAIT", "RUN", "INCOMPLETE"}:
            return index + 1
    return len([row for row in rows if row[1] == "PASS"])


def _terminal_from_vm(vm: RunViewModel | None) -> bool:
    return vm is not None and _is_terminal_launch_state(_view_launch_state(vm))


def _is_terminal_launch_state(state: str) -> bool:
    return state in {
        "Run completed",
        "Run failed",
        "Run failed before approval",
        "Run launch failed before run_dir was created",
    }


def _view_failed(vm: RunViewModel) -> bool:
    return _view_launch_state(vm) in {
        "Run failed",
        "Run failed before approval",
        "Run launch failed before run_dir was created",
    }


def _build_failed(vm: RunViewModel) -> bool:
    return _is_failure_status(vm.summary.get("build_status")) or _is_failure_status(vm.raw_backend.get("build_status"))


def _build_passed(vm: RunViewModel) -> bool:
    return (
        vm.summary.get("build_status", "").upper() == "BUILD_PASSED_IN_SANDBOX"
        or _string_value(vm.raw_backend.get("build_status")).upper() == "BUILD_PASSED_IN_SANDBOX"
    )


def _transform_passed(vm: RunViewModel) -> bool:
    return (
        vm.summary.get("transform_status", "").upper() == "TRANSFORM_APPLIED_IN_SANDBOX"
        or _string_value(vm.raw_backend.get("transform_status")).upper() == "TRANSFORM_APPLIED_IN_SANDBOX"
    )


def _transform_failed(vm: RunViewModel) -> bool:
    return _is_failure_status(vm.summary.get("transform_status")) or _is_failure_status(vm.raw_backend.get("transform_status"))


def _test_counts_failed(values: dict[str, Any]) -> bool:
    for key in ("failures", "errors", "test_failures", "test_errors"):
        value = values.get(key)
        try:
            if value is not None and int(value) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _backend_failed(value: Any) -> bool:
    if isinstance(value, dict):
        ignored_keys = {"warnings", "artifact_refs", "copilot_report_response", "copilot_migration_report"}
        return any(_backend_failed(item) for key, item in value.items() if str(key) not in ignored_keys)
    if isinstance(value, (list, tuple)):
        return any(_backend_failed(item) for item in value)
    return _is_failure_status(_string_value(value))


def _backend_badge_key(value: str) -> str:
    upper = (value or "-").upper()
    if upper in BACKEND_BADGES:
        return upper
    if upper in _BUILD_PASS_VALUES or upper in _TEST_PASS_VALUES or upper in _TRUE_SUCCESS_VALUES:
        return "PASS"
    if _is_failure_status(upper):
        return "FAIL"
    return upper if value else "-"


def _backend_says_generated(vm: RunViewModel, kind: str) -> bool:
    needle = kind.lower()
    for source in (vm.summary, vm.raw_backend):
        for key, value in source.items():
            text = f"{key} {_string_value(value)}".lower()
            if needle in text and "generated" in text:
                return True
    return False


def _has_copilot_docs(vm: RunViewModel) -> bool:
    for name, ref in vm.artifact_refs.items():
        if "copilot" not in name.lower():
            continue
        if vm.run_dir is None:
            return True
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = vm.run_dir / path
        if path.is_file():
            return True
    if vm.run_dir is None:
        return False
    return any((vm.run_dir / rel_path).is_file() for _key, _label, rel_path in (
        ("copilot_migration_overview", "Copilot docs - migration overview", "final/copilot_docs/migration_overview.md"),
        ("copilot_technical_changes", "Copilot docs - technical changes", "final/copilot_docs/technical_changes.md"),
        ("copilot_validation_evidence", "Copilot docs - validation evidence", "final/copilot_docs/validation_evidence.md"),
        ("copilot_risks_and_warnings", "Copilot docs - risks and warnings", "final/copilot_docs/risks_and_warnings.md"),
        ("copilot_review", "Copilot docs - review", "final/copilot_docs/copilot_review.md"),
    ))


def _has_final_report(vm: RunViewModel) -> bool:
    for name, ref in vm.artifact_refs.items():
        if name not in {"final_migration_report", "final_migration_summary"}:
            continue
        if vm.run_dir is None:
            return True
        path = Path(ref).expanduser()
        if not path.is_absolute():
            path = vm.run_dir / path
        if path.is_file():
            return True
    if vm.run_dir is None:
        return False
    return any(
        (vm.run_dir / rel_path).is_file()
        for rel_path in ("final/migration_report.json", "final/migration_summary.md")
    )


def _elapsed_label(started_at: datetime | None) -> str:
    if started_at is None:
        return "-"
    seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    minutes, seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _file_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _format_launch_preview(config: TuiConfig, *, validation_status: str = "Not validated yet.") -> str:
    preview_run_id = "<generated-on-launch>"
    current_run_id = config.run_id.strip() or "-"
    run_dir = (
        _display_joined_path(config.modernized_app_path, ".migration", "runs", preview_run_id)
        if config.modernized_app_path.strip()
        else "-"
    )
    mode = config.mode.strip() or "read_only_assessment"
    approval_effect = (
        "may continue after approval and run sandbox transform"
        if mode == "full_sandbox_migration"
        else "stops at approval/assessment only"
    )
    command = [
        sys.executable,
        "-m",
        "migration_factory.orchestrator.runner",
        "--run-id",
        preview_run_id,
        "--legacy",
        config.legacy_app_path,
        "--modernized",
        config.modernized_app_path,
        "--ai-hub",
        config.ai_hub_path,
        "--profile",
        config.profile_id,
        "--mode",
        mode,
    ]
    return "\n".join(
        [
            "Command equivalent:",
            " ".join(shlex.quote(part) for part in command),
            f"Run ID: {preview_run_id}",
            f"Current Run ID field: {current_run_id}",
            f"Run dir: {run_dir}",
            f"Mode: {mode}",
            f"Profile: {config.profile_id or '-'}",
            "Validation required before launch: yes",
            f"Last validation status: {validation_status}",
            f"Approval behavior: {approval_effect}",
        ]
    )


def _display_joined_path(base: str, *parts: str) -> str:
    stripped = base.strip()
    if "/" in stripped and "\\" not in stripped:
        return "/".join([stripped.rstrip("/"), *parts])
    return str(Path(stripped).expanduser().joinpath(*parts))


def _looks_like_config_paste(text: str) -> bool:
    stripped = text.lstrip()
    return (
        "\n" in text
        or stripped.startswith("export ")
        or stripped.startswith("$LEGACY_APP")
        or stripped.startswith("$env:")
    )


def _friendly_status(status: str) -> str:
    return {
        "Run reached approval gate": "Waiting for approval",
        "Run completed": "Success",
        "Run failed": "Failed",
        "Run failed before approval": "Failed",
        "Run launch failed before run_dir was created": "Failed",
        "Run running": "Running",
        "Run incomplete": "Incomplete",
    }.get(status, status)


def _normalized_run_state(vm: RunViewModel) -> str:
    launch_state = _view_launch_state(vm)
    if launch_state in {
        "Run completed",
        "Run failed",
        "Run failed before approval",
        "Run launch failed before run_dir was created",
        "Run incomplete",
    }:
        return _friendly_status(launch_state)
    if vm.status == "rejected":
        return "Rejected"
    if vm.status == "replan_required":
        return "Replan required"
    if vm.approval_required:
        return "Waiting for approval"
    if vm.approval_submitted and (vm.resume_worker_active or vm.status == "running"):
        return "Resuming after approval"
    return _friendly_status(launch_state)


def _run_identity(config: TuiConfig, vm: RunViewModel) -> tuple[str, str]:
    profile = (
        config.profile_id.strip()
        or _string_value(vm.raw_backend.get("profile_id")).strip()
        or _string_value(vm.raw_backend.get("profile")).strip()
        or vm.summary.get("profile_id", "").strip()
        or vm.summary.get("profile", "").strip()
        or "-"
    )
    mode = (
        config.mode.strip()
        or _string_value(vm.raw_backend.get("mode")).strip()
        or vm.summary.get("mode", "").strip()
        or "read_only_assessment"
    )
    return profile, mode


def _format_target_summary(config: TuiConfig) -> str:
    target = _target_from_profile(config) or _target_from_latest_final_report(config)
    if not target:
        return "Target: unknown"
    parts = []
    java = _string_value(target.get("java")).strip()
    boot = _string_value(target.get("spring_boot")).strip()
    framework = _string_value(target.get("spring_framework")).strip()
    if java:
        parts.append(f"Java {java}")
    if boot:
        parts.append(f"Spring Boot {boot}")
    if framework:
        parts.append(f"Spring Framework {framework}")
    return "Target: " + (" / ".join(parts) if parts else "unknown")


def _target_from_profile(config: TuiConfig) -> dict[str, Any]:
    profile_id = config.profile_id.strip()
    if not profile_id:
        return {}
    for hub in _candidate_ai_hub_paths(config):
        profile_path = hub / "profiles" / f"{profile_id}.yaml"
        try:
            payload = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(payload, dict) and isinstance(payload.get("target_stack"), dict):
            return dict(payload["target_stack"])
    return {}


def _candidate_ai_hub_paths(config: TuiConfig) -> list[Path]:
    paths: list[Path] = []
    if config.ai_hub_path.strip():
        paths.append(Path(config.ai_hub_path).expanduser())
    paths.append(Path(__file__).resolve().parents[2] / "modernizer-solution-ai-hub")
    return paths


def _target_from_latest_final_report(config: TuiConfig) -> dict[str, Any]:
    latest = _latest_run_dir(config)
    if latest is None:
        return {}
    report_path = latest / "final" / "migration_report.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("target_stack"), dict):
        return dict(payload["target_stack"])
    return {}


def _latest_run_dir(config: TuiConfig) -> Path | None:
    if not config.modernized_app_path.strip():
        return None
    runs_root = Path(config.modernized_app_path).expanduser() / ".migration" / "runs"
    try:
        run_dirs = [path for path in runs_root.iterdir() if path.is_dir()]
    except OSError:
        return None
    if not run_dirs:
        return None
    return max(run_dirs, key=lambda path: (_path_mtime(path), path.name))


def _path_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _path_name(path: str) -> str:
    return Path(path).name if path else "-"


def _format_approval(approval: ApprovalState | None) -> str:
    if approval is None:
        return "No approval interrupt loaded."
    lines = [
        f"Run: {approval.run_id}",
        f"Decision options: {', '.join(approval.decision_options) or '-'}",
    ]
    if approval.mode == "full_sandbox_migration":
        lines.extend(["", "Warning:", "- Approval will continue sandbox transform only; legacy app remains unchanged."])
    lines.extend(["", "Blockers:"])
    lines.extend(f"- {item}" for item in approval.blockers) if approval.blockers else lines.append("- none")
    lines.extend(["", "Warnings:"])
    lines.extend(f"- {item}" for item in approval.warnings) if approval.warnings else lines.append("- none")
    return "\n".join(lines)


def _friendly_artifact_name(name: str) -> str:
    return {
        "orchestration_summary": "Orchestration summary",
        "final_migration_report": "Final migration report",
        "final_migration_summary": "Final migration summary",
        "test_summary_path": "Test summary",
        "post_transform_test_summary": "Test summary",
        "copilot_migration_overview": "Copilot docs - migration overview",
        "copilot_technical_changes": "Copilot docs - technical changes",
        "copilot_validation_evidence": "Copilot docs - validation evidence",
        "copilot_risks_and_warnings": "Copilot docs - risks and warnings",
        "copilot_review": "Copilot docs - review",
        "phase2_log": "Phase 2 log",
        "migration_ledger": "Migration ledger",
    }.get(name, name)


def _indent_viewer_content(content: str) -> list[str]:
    lines = content.splitlines() or [""]
    return [f"    {line}" for line in lines]


def main() -> None:
    MigrationFactorySetupApp().run()


if __name__ == "__main__":
    main()
