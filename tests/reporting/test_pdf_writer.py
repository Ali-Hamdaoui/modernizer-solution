from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

from migration_factory.final_report.pdf_writer import (
    write_text_pdf_from_markdown,
    _wrap_text,
    _split_long_word,
    _fit_text,
)


def test_pdf_writes_valid_pdf_with_content() -> None:
    markdown = """# Test Report

- Run ID: test-123
- Status: completed

## Validated

- sandbox transform applied

POC-ready sandbox migration artifacts.
"""
    with TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "input.md"
        pdf_path = Path(tmpdir) / "output.pdf"
        md_path.write_text(markdown, encoding="utf-8")

        write_text_pdf_from_markdown(str(md_path), str(pdf_path))

        assert pdf_path.is_file()
        content = pdf_path.read_bytes()
        assert content.startswith(b"%PDF-1.4")
        assert len(content) > 200
        assert _page_tree_kids_are_pages(content)
        assert _page_count_matches_kids(content)
        assert _page_content_stream_refs_are_valid(content)
        assert _xref_offsets_are_valid(content)


def test_pdf_handles_table_with_long_cells() -> None:
    markdown = """# Report

| Header1 | Header2 |
|---------|---------|
| /this/is/a/very/long/unbroken/path/that/should/wrap/automatically | value2 |
"""
    with TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "input.md"
        pdf_path = Path(tmpdir) / "output.pdf"
        md_path.write_text(markdown, encoding="utf-8")

        write_text_pdf_from_markdown(str(md_path), str(pdf_path))

        assert pdf_path.is_file()
        content = pdf_path.read_bytes()
        assert content.startswith(b"%PDF-1.4")


def test_pdf_paginates_long_reports() -> None:
    paragraphs = [
        f"Paragraph {index}: "
        + "This migration detail should flow across pages with readable spacing. " * 5
        for index in range(80)
    ]
    markdown = "# Long Report\n\n## Migration Story\n\n" + "\n\n".join(paragraphs)
    with TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "input.md"
        pdf_path = Path(tmpdir) / "output.pdf"
        md_path.write_text(markdown, encoding="utf-8")

        write_text_pdf_from_markdown(str(md_path), str(pdf_path))

        content = pdf_path.read_bytes()
        assert _page_count(content) > 1
        assert _page_tree_kids_are_pages(content)


def test_pdf_splits_oversized_table_rows_across_pages() -> None:
    long_detail = " ".join(f"detail-{index}" for index in range(900))
    markdown = (
        "# Table Report\n\n"
        "| Time | Stage | Event | Status | Detail |\n"
        "|---|---|---|---|---|\n"
        f"| 2026-07-10T10:00:00Z | 3 | migration completed | completed | {long_detail} |\n"
    )
    with TemporaryDirectory() as tmpdir:
        md_path = Path(tmpdir) / "input.md"
        pdf_path = Path(tmpdir) / "output.pdf"
        md_path.write_text(markdown, encoding="utf-8")

        write_text_pdf_from_markdown(str(md_path), str(pdf_path))

        content = pdf_path.read_bytes()
        assert _page_count(content) > 1
        assert _page_tree_kids_are_pages(content)
        assert _page_count_matches_kids(content)
        assert _page_content_stream_refs_are_valid(content)
        assert _xref_offsets_are_valid(content)


def test_wrap_text_splits_long_lines() -> None:
    text = "A" * 200
    wrapped = _wrap_text(text, max_chars=80)
    assert len(wrapped) > 1
    assert all(len(line) <= 80 for line in wrapped)


def test_wrap_text_handles_br_tags() -> None:
    text = "line1<br />line2<br>line3"
    wrapped = _wrap_text(text, max_chars=80)
    assert len(wrapped) == 3


def test_split_long_word_at_separator() -> None:
    text = "a/very/long/path/component"
    result = _split_long_word(text, max_chars=10)
    assert result is not None
    part, rest = result
    assert len(part) <= 10
    assert len(part) + len(rest) == len(text)


def test_split_long_word_returns_none_for_short_text() -> None:
    text = "short"
    result = _split_long_word(text, max_chars=80)
    assert result is None

def test_fit_text_keeps_truncated_text_within_target_width() -> None:
    fitted = _fit_text("A very long report title that should be shortened", width=60, font_size=12)

    assert fitted.endswith("...")
    assert len(fitted) <= 12


def _page_count(content: bytes) -> int:
    return len(_page_tree_kid_refs(content))


def _page_tree_kids_are_pages(content: bytes) -> bool:
    objects = _pdf_objects(content)
    return all(
        re.search(r"/Type\s*/Page\b", objects.get(ref, ""))
        for ref in _page_tree_kid_refs(content)
    )


def _page_count_matches_kids(content: bytes) -> bool:
    pages = _pdf_objects(content).get(2, "")
    count_match = re.search(r"/Count (\d+)", pages)
    assert count_match is not None
    return int(count_match.group(1)) == len(_page_tree_kid_refs(content))


def _page_content_stream_refs_are_valid(content: bytes) -> bool:
    objects = _pdf_objects(content)
    for page_ref in _page_tree_kid_refs(content):
        contents_match = re.search(r"/Contents (\d+) 0 R", objects.get(page_ref, ""))
        assert contents_match is not None
        stream = objects.get(int(contents_match.group(1)), "")
        assert "stream\n" in stream
    return True


def _xref_offsets_are_valid(content: bytes) -> bool:
    marker = b"startxref\n"
    startxref_index = content.rfind(marker)
    assert startxref_index != -1
    xref_offset_end = content.find(b"\n", startxref_index + len(marker))
    xref_offset = int(content[startxref_index + len(marker):xref_offset_end])
    assert content[xref_offset:xref_offset + 4] == b"xref"

    text = content.decode("latin-1")
    xref_match = re.search(r"xref\n0 (\d+)\n(.*?)trailer", text, re.S)
    assert xref_match is not None
    entries = [line for line in xref_match.group(2).splitlines() if line.strip()]
    for obj_num, entry in enumerate(entries[1:], start=1):
        offset = int(entry[:10])
        expected = f"{obj_num} 0 obj".encode()
        assert content[offset:offset + len(expected)] == expected
    return True


def _page_tree_kid_refs(content: bytes) -> list[int]:
    pages = _pdf_objects(content).get(2, "")
    kids_match = re.search(r"/Kids \[(.*?)\]", pages)
    assert kids_match is not None
    kid_refs = [int(ref) for ref in re.findall(r"(\d+) 0 R", kids_match.group(1))]
    assert kid_refs
    return kid_refs


def _pdf_objects(content: bytes) -> dict[int, str]:
    text = content.decode("latin-1")
    return {
        int(match.group(1)): match.group(2)
        for match in re.finditer(r"(?ms)^(\d+) 0 obj\n(.*?)\nendobj", text)
    }
