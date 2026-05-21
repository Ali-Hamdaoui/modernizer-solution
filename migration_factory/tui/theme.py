from __future__ import annotations

from textual.theme import Theme


STATE_BADGES = {
    "PASS": "[bold $success][ PASS ][/]",
    "FAIL": "[bold $error][ FAIL ][/]",
    "WAIT": "[bold $warning][ WAIT ][/]",
    "RUN": "[bold $accent][ RUN  ][/]",
    "TODO": "[dim][ TODO ][/dim]",
    "INCOMPLETE": "[bold $error-lighten-1][ INCL ][/]",
    "WARN": "[bold $warning][ WARN ][/]",
    "SKIP": "[dim italic][ SKIP ][/]",
}

BACKEND_BADGES = {
    "PASS": "[bold $success]PASS[/]",
    "FAIL": "[bold $error]FAIL[/]",
    "INTERRUPTED": "[bold $warning]INTERRUPTED[/]",
    "COMPLETED": "[bold $success]COMPLETED[/]",
    "GENERATED": "[bold $primary]GENERATED[/]",
    "INCOMPLETE": "[dim $error]INCOMPLETE[/]",
    "-": "[dim]-[/dim]",
}

EGA_CSS = """
Screen {
    background: $background;
    layout: vertical;
    overflow-y: auto;
}

Header {
    background: $primary-darken-3;
    color: $text-primary;
    text-style: bold;
    border-bottom: heavy $primary;
    height: 3;
}

Footer {
    background: $background;
    border-top: tall $ega-border-dim;
    color: $text-muted;
}

#main {
    width: 100%;
    height: 1fr;
    padding: 1 2;
}

.panel {
    border: round $ega-border-dim;
    background: $surface;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}

#dashboard_panel {
    border: round $primary;
}

#run_status {
    border: heavy $accent;
    background: $panel;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}

#run_header {
    color: $text;
}

#run_monitor, #run_messages, #details_panel {
    max-width: 100%;
    height: auto;
}

#approval, #approval_panel {
    border: heavy $accent;
    background: $panel;
}

#failure {
    border: round $error;
    background: $error-darken-3;
}

#dashboard_columns {
    width: 100%;
    height: auto;
}

#setup, #environment, #history {
    width: 1fr;
    height: auto;
    margin: 0 1;
}

Label.field_label, Label.field-label {
    color: $text-muted;
    margin-bottom: 0;
}

Input, Select {
    border: tall $ega-border-dim;
    background: $surface;
    color: $text;
    margin: 0 0 1 0;
}

Input:focus, Select:focus {
    border: tall $accent;
    background: $boost;
}

TextArea {
    height: 6;
    margin-bottom: 1;
    border: tall $ega-border-dim;
    background: $surface;
}

#run_list {
    height: 8;
    margin-bottom: 1;
}

ProgressBar {
    margin: 1 0 0 0;
}

ProgressBar > .bar--bar {
    color: $accent;
    background: $panel;
}

ProgressBar > .bar--indeterminate {
    color: $primary;
}

ProgressBar > .bar--complete {
    color: $success;
}

#pipeline_table {
    border: round $primary-darken-1;
    background: $surface;
    height: 12;
}

DataTable {
    background: $surface;
    height: auto;
}

DataTable > .datatable--header {
    background: $primary-darken-2;
    color: $text-primary;
    text-style: bold;
}

DataTable > .datatable--cursor {
    background: $accent 20%;
    color: $text;
}

DataTable > .datatable--even-row {
    background: $boost;
}

DataTable > .datatable--odd-row {
    background: $surface;
}

.button_row {
    height: auto;
    layout: horizontal;
    align: center middle;
}

.button_row Button {
    width: 1fr;
    margin-right: 1;
    margin-bottom: 1;
    text-style: bold;
}

#approve_btn, #approve_run, #modal_approve_run {
    background: $success-darken-2;
    color: $text;
    border: heavy $success;
}

#reject_btn, #reject_run, #modal_reject_run {
    background: $error-darken-2;
    color: $text;
    border: heavy $error;
}

#replan_btn, #replan_run, #modal_replan_run {
    background: $warning-darken-2;
    color: $text;
    border: heavy $warning;
}

#resume_btn, #resume_approval {
    background: $panel;
    color: $text-muted;
    border: round $ega-border-dim;
}

LoadingIndicator {
    color: $accent;
    background: $surface;
}

#launch_output {
    display: none;
}

ScrollBar {
    color: $ega-border-dim;
    background: $background;
}

ScrollBar:hover {
    color: $primary;
}
"""


def register_ega_theme(app) -> None:
    theme = Theme(
        name="ega-dark",
        primary="#0EA5E9",
        secondary="#8B5CF6",
        accent="#F59E0B",
        success="#10B981",
        warning="#F97316",
        error="#EF4444",
        background="#0C0F1A",
        surface="#111827",
        panel="#1F2937",
        dark=True,
        variables={
            "ega-cyan": "#22D3EE",
            "ega-green-vivid": "#34D399",
            "ega-amber-vivid": "#FBBF24",
            "ega-border-dim": "#374151",
            "ega-run-glow": "#0EA5E9 15%",
        },
    )
    app.register_theme(theme)
    app.theme = "ega-dark"
