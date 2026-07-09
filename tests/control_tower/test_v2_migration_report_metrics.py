from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_migration_report import (
    _compare_source_trees,
    _overall_duration_seconds,
)


def test_source_tree_comparison_counts_added_deleted_and_replaced_lines(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "App.java").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (target / "App.java").write_text("one\nchanged\nthree\nfour\n", encoding="utf-8")
    (target / "New.java").write_text("alpha\nbeta\n", encoding="utf-8")
    generated = target / "target"
    generated.mkdir()
    (generated / "Ignored.class").write_bytes(b"\x00generated")

    metrics = _compare_source_trees(source, target)

    assert metrics == {
        "files_changed": 2,
        "lines_added": 4,
        "lines_deleted": 1,
        "lines_changed": 5,
        "source": "source_tree_comparison",
    }


def test_overall_duration_ignores_malformed_event_timestamps() -> None:
    job = SimpleNamespace(created_at="2026-07-09T10:00:00Z")
    events = [
        SimpleNamespace(type="stage_completed", created_at="not-a-timestamp"),
        SimpleNamespace(type="migration_completed", created_at="2026-07-09T10:02:00Z"),
    ]

    duration = _overall_duration_seconds(job, [], events)

    assert duration == 120.0
