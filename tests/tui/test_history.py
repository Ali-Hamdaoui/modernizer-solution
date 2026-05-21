from __future__ import annotations

import json
from pathlib import Path

from migration_factory.tui import history
from migration_factory.tui.config import TuiConfig
from migration_factory.tui.history import (
    discover_run_dashboards,
    load_run_dashboard,
    resolve_artifact_ref,
)


def test_discovers_runs_and_reads_orchestration_summary(tmp_path: Path) -> None:
    modernized = tmp_path / "modernized"
    run_dir = modernized / ".migration" / "runs" / "run-001"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-001",
                "profile_id": "java17",
                "final_status": "COMPLETED",
                "analysis_status": "PASS",
                "planning_status": "PASS",
                "blockers": [],
                "warnings": ["review required"],
                "artifact_refs": {
                    "assessment_report": "assessment/assessment_report.json"
                },
                "log_path": "logs/orchestrator.log",
            }
        ),
        encoding="utf-8",
    )

    runs = discover_run_dashboards(
        TuiConfig(modernized_app_path=str(modernized))
    )

    assert len(runs) == 1
    run = runs[0]
    assert run.run_id == "run-001"
    assert run.profile == "java17"
    assert run.final_status == "COMPLETED"
    assert run.statuses["analysis_status"] == "PASS"
    assert run.statuses["planning_status"] == "PASS"
    assert run.warnings == ("review required",)
    assert run.report_refs[0].path == run_dir / "assessment" / "assessment_report.json"
    assert run.report_refs[1].path == run_dir / "logs" / "orchestrator.log"
    assert [viewer.name for viewer in run.artifact_viewers] == [
        "assessment_summary",
        "approval_request",
        "timing_summary",
        "log_path",
    ]
    assert run.artifact_viewers[0].status == "missing"
    assert run.artifact_viewers[-1].tail is True


def test_missing_summary_returns_incomplete_view_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-002"
    run_dir.mkdir(parents=True)

    run = load_run_dashboard(run_dir)

    assert run.run_id == "run-002"
    assert run.final_status == "INCOMPLETE"
    assert run.statuses == {}
    assert run.blockers == ()
    assert run.warnings == ("orchestration_summary.json missing",)
    assert run.report_refs == ()
    assert [viewer.status for viewer in run.artifact_viewers] == [
        "missing",
        "missing",
        "missing",
    ]


def test_partial_summary_uses_defaults(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-003"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps({"run_id": "run-003", "blockers": ["blocked"]}),
        encoding="utf-8",
    )

    run = load_run_dashboard(run_dir)

    assert run.run_id == "run-003"
    assert run.final_status == "UNKNOWN"
    assert run.blockers == ("blocked",)
    assert run.warnings == ()


def test_unreadable_summary_returns_incomplete_view_model(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-004"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text("{bad", encoding="utf-8")

    run = load_run_dashboard(run_dir)

    assert run.run_id == "run-004"
    assert run.final_status == "INCOMPLETE"
    assert run.warnings
    assert "unreadable" in run.warnings[0]


def test_resolve_artifact_ref_allows_absolute_and_run_relative_refs(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    absolute = tmp_path / "artifact.json"

    assert resolve_artifact_ref(run_dir, str(absolute)) == absolute
    assert resolve_artifact_ref(run_dir, "logs/run.log") == run_dir / "logs" / "run.log"


def test_resolve_artifact_ref_rejects_relative_escape(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"

    assert resolve_artifact_ref(run_dir, "../outside.log") is None


def test_viewers_tail_logs_read_only_and_mark_missing_reports(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-005"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    log_path = run_dir / "logs" / "phase2_transform.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("\n".join(f"line-{index}" for index in range(125)), encoding="utf-8")
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-005",
                "artifact_refs": {"phase2_log": str(log_path)},
            }
        ),
        encoding="utf-8",
    )

    run = load_run_dashboard(run_dir)

    viewers = {viewer.name: viewer for viewer in run.artifact_viewers}
    assert viewers["assessment_summary"].status == "missing"
    assert viewers["phase2_log"].status == "present"
    assert viewers["phase2_log"].tail is True
    assert "line-0" not in viewers["phase2_log"].content
    assert "line-124" in viewers["phase2_log"].content


def test_read_only_assessment_does_not_expect_final_or_copilot_docs(tmp_path: Path) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-read-only"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-read-only",
                "mode": "read_only_assessment",
                "orchestration_status": "PASS",
                "final_status": "COMPLETED",
            }
        ),
        encoding="utf-8",
    )

    run = load_run_dashboard(run_dir)

    viewer_names = {viewer.name for viewer in run.artifact_viewers}
    assert "final_migration_report" not in viewer_names
    assert "copilot_review" not in viewer_names


def test_full_sandbox_pass_shows_final_and_copilot_doc_refs_when_present(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-full"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    final_dir = run_dir / "final"
    docs_dir = final_dir / "copilot_docs"
    docs_dir.mkdir(parents=True)
    report = final_dir / "migration_report.json"
    review = docs_dir / "copilot_review.md"
    report.write_text('{"ok": true}\n', encoding="utf-8")
    review.write_text("# Review\n", encoding="utf-8")
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-full",
                "mode": "full_sandbox_migration",
                "approval_status": "COMPLETED",
                "approval_decision": "approved",
                "orchestration_status": "PASS",
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "artifact_refs": {
                    "final_migration_report": str(report),
                    "copilot_review": str(review),
                },
            }
        ),
        encoding="utf-8",
    )

    run = load_run_dashboard(run_dir)

    viewers = {viewer.name: viewer for viewer in run.artifact_viewers}
    assert viewers["final_migration_report"].status == "present"
    assert viewers["final_migration_summary"].status == "missing"
    assert viewers["copilot_review"].status == "present"
    assert "Review" in viewers["copilot_review"].content


def test_dashboard_uses_friendly_artifact_names(tmp_path: Path) -> None:
    from migration_factory.tui.app import _format_dashboard

    run_dir = tmp_path / "modernized" / ".migration" / "runs" / "run-friendly"
    summary_dir = run_dir / "orchestration"
    summary_dir.mkdir(parents=True)
    (summary_dir / "orchestration_summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-friendly",
                "mode": "full_sandbox_migration",
                "approval_status": "COMPLETED",
                "approval_decision": "approved",
                "orchestration_status": "PASS",
                "final_status": "TRANSFORM_APPLIED_IN_SANDBOX",
                "test_summary_path": "test/post_transform/test_summary.md",
                "artifact_refs": {
                    "final_migration_report": "final/migration_report.json",
                    "final_migration_summary": "final/migration_summary.md",
                    "copilot_review": "final/copilot_docs/copilot_review.md",
                    "phase2_log": "logs/phase2_transform.log",
                    "migration_ledger": "workspaces/sandbox/.migration/ledger.json",
                },
            }
        ),
        encoding="utf-8",
    )

    run = load_run_dashboard(run_dir)

    report_names = {ref.name for ref in run.report_refs}
    viewer_labels = {viewer.label for viewer in run.artifact_viewers}
    assert "final_migration_report" in report_names
    assert "Final migration report" in viewer_labels
    assert "Final migration summary" in viewer_labels
    assert "Copilot docs - review" in viewer_labels
    assert "Phase 2 log" in viewer_labels

    dashboard = _format_dashboard(run)
    assert "Orchestration summary:" in dashboard
    assert "Final migration report:" in dashboard
    assert "Final migration summary:" in dashboard
    assert "Test summary:" in dashboard
    assert "Copilot docs - review:" in dashboard
    assert "Phase 2 log" in dashboard
    assert "Migration ledger:" in dashboard


def test_discover_marks_bad_run_error_without_aborting_other_runs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    modernized = tmp_path / "modernized"
    bad_run = modernized / ".migration" / "runs" / "bad-[warning]"
    good_run = modernized / ".migration" / "runs" / "good"
    (bad_run / "orchestration").mkdir(parents=True)
    (good_run / "orchestration").mkdir(parents=True)
    (bad_run / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"run_id": "bad-[warning]"}),
        encoding="utf-8",
    )
    (good_run / "orchestration" / "orchestration_summary.json").write_text(
        json.dumps({"run_id": "good", "final_status": "COMPLETED"}),
        encoding="utf-8",
    )

    original = history.load_run_dashboard

    def load_or_raise(run_dir: Path):
        if run_dir == bad_run:
            raise RuntimeError("[/tmp/file]")
        return original(run_dir)

    monkeypatch.setattr(history, "load_run_dashboard", load_or_raise)

    runs = discover_run_dashboards(TuiConfig(modernized_app_path=str(modernized)))

    runs_by_id = {run.run_id: run for run in runs}
    assert runs_by_id["bad-[warning]"].final_status == "ERROR"
    assert "[/tmp/file]" in runs_by_id["bad-[warning]"].warnings[0]
    assert runs_by_id["good"].final_status == "COMPLETED"
