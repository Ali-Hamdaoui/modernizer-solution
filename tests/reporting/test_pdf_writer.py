from __future__ import annotations

from migration_factory.final_report.pdf_writer import _estimate_text_width, _table_row_height, _wrap_text


def test_pdf_table_cells_wrap_long_unbroken_values() -> None:
    width = 90.0
    font_size = 10.5
    value = "TRANSFORM_APPLIED_IN_SANDBOX_WITH_EXTRA_REPAIR_LOOP_VALIDATION"

    wrapped = _wrap_text(value, font_size, width)

    assert len(wrapped) > 1
    assert all(_estimate_text_width(line, font_size) <= width for line in wrapped)


def test_pdf_table_row_height_grows_for_long_report_cells() -> None:
    row = [
        "`timing_report`",
        "`docs/migration-reports/job-123/performance/timing_report_with_a_very_long_name.json`",
    ]
    short_row = ["`Status`", "`PASS`"]
    widths = [120.0, 180.0]

    assert _table_row_height(row, widths, 10.5) > _table_row_height(short_row, widths, 10.5)
