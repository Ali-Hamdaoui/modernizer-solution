from __future__ import annotations

import json
from pathlib import Path

from migration_factory.final_report.copilot import CopilotAdapterStatus
import migration_factory.tui.copilot_status as copilot_status
from migration_factory.tui.copilot_status import get_copilot_status_lines


def test_copilot_status_maps_present_response(tmp_path: Path) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "detected:gpt-5",
                "connectivity": "connected",
                "adapter": "copilot_cli",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": "generated",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert get_copilot_status_lines(tmp_path) == [
        "Copilot: Connected",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: gpt-5",
        "Auth: Authenticated",
        "CLI: Installed",
        "Report: Generated",
        "Report generation: Disabled",
    ]


def test_copilot_status_uses_live_detector_when_response_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="not_configured",
            adapter="local_deterministic_template",
            model="unknown",
            auth_status="unknown",
            cli_status="not_installed",
        ),
    )

    assert get_copilot_status_lines(Path("missing-run")) == [
        "Copilot: Not configured",
        "Provider: github_copilot",
        "Adapter: local_deterministic_template",
        "Model: unknown",
        "Auth: Unknown",
        "CLI: Not installed",
        "Report: Disabled",
        "Report generation: Disabled",
    ]


def test_copilot_status_shows_not_started_before_run_when_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="configured:gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    assert get_copilot_status_lines(None, prefer_response=False, active_run=False) == [
        "Copilot: Connected",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: gpt-5-mini",
        "Auth: Authenticated",
        "CLI: Installed",
        "Report: Not started",
        "Report generation: Enabled",
    ]


def test_copilot_status_ignores_old_response_when_live_source_requested(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "old-model",
                "connectivity": "connected",
                "adapter": "local_deterministic_template",
                "auth_status": "unknown",
                "cli_status": "not_installed",
                "report_status": "generated",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    lines = get_copilot_status_lines(tmp_path, prefer_response=False, active_run=False)

    assert "Adapter: copilot_cli" in lines
    assert "Model: gpt-5-mini" in lines
    assert "Report: Not started" in lines


def test_copilot_status_shows_pending_for_active_run_without_response(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    monkeypatch.setattr(
        copilot_status,
        "detect_copilot_cli_status",
        lambda **kwargs: CopilotAdapterStatus(
            connectivity="connected",
            adapter="copilot_cli",
            model="gpt-5-mini",
            auth_status="authenticated",
            cli_status="installed",
        ),
    )

    lines = get_copilot_status_lines(tmp_path, active_run=True)

    assert "Report: Pending" in lines
    assert "Report generation: Enabled" in lines


def test_copilot_status_maps_unavailable_and_failed(tmp_path: Path) -> None:
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "unknown",
                "connectivity": "unavailable",
                "adapter": "copilot_cli",
                "auth_status": "unauthenticated",
                "cli_status": "installed",
                "report_status": "failed",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert get_copilot_status_lines(tmp_path) == [
        "Copilot: Unavailable",
        "Provider: github_copilot",
        "Adapter: copilot_cli",
        "Model: unknown",
        "Auth: Unauthenticated",
        "CLI: Installed",
        "Report: Failed",
        "Report generation: Disabled",
    ]


def test_copilot_status_maps_fallback_warning_separately(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AI_MIGRATION_ENABLE_COPILOT_REPORT", "true")
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "copilot_report_response.json").write_text(
        json.dumps(
            {
                "provider": "github_copilot",
                "model": "gpt-5-mini",
                "connectivity": "connected",
                "adapter": "local_deterministic_template",
                "auth_status": "authenticated",
                "cli_status": "installed",
                "report_status": "generated_with_fallback",
                "warnings": ["copilot CLI report generation failed; used deterministic fallback: FileNotFoundError"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    lines = get_copilot_status_lines(tmp_path)

    assert "Report: Generated with fallback" in lines
    assert "Copilot warning: CLI failed, fallback used" in lines
