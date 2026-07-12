from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_PAGE_WIDTH = 595
_PAGE_HEIGHT = 842
_MARGIN = 46
_TOP_MARGIN = 54
_BOTTOM_MARGIN = 56
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN
_FONT_SIZE = 10
_HEADING_SIZES = {1: 22, 2: 15, 3: 12, 4: 10, 5: 10}
_LINE_HEIGHT = 14
_TABLE_LINE_HEIGHT = 18
_MAX_CELL_CHARS = 80
_NAVY = (0.09, 0.16, 0.25)
_BLUE = (0.10, 0.32, 0.58)
_TEAL = (0.00, 0.48, 0.52)
_GRAY = (0.34, 0.38, 0.43)
_LIGHT_BLUE = (0.92, 0.96, 0.99)
_LIGHT_TEAL = (0.91, 0.97, 0.96)
_LIGHT_GRAY = (0.96, 0.97, 0.98)
_BORDER = (0.78, 0.82, 0.86)
_WHITE = (1.0, 1.0, 1.0)
_BLACK = (0.08, 0.09, 0.10)


@dataclass
class _PdfCanvas:
    pages: list[list[str]] = field(default_factory=lambda: [[]])
    y: float = _PAGE_HEIGHT - _TOP_MARGIN
    page: int = 1

    @property
    def current_page(self) -> list[str]:
        return self.pages[-1]

    def add_page(self) -> None:
        self.pages.append([])
        self.page += 1
        self.y = _PAGE_HEIGHT - _TOP_MARGIN

    def ensure_space(self, height: float) -> None:
        if self.y - height < _BOTTOM_MARGIN:
            self.add_page()

    def add_command(self, command: str) -> None:
        self.current_page.append(command)

    def draw_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = None,
    ) -> None:
        if fill is not None:
            self.add_command(
                f"{_rgb(fill)} rg {x:.1f} {y:.1f} {width:.1f} {height:.1f} re f"
            )
        if stroke is not None:
            self.add_command(
                f"{_rgb(stroke)} RG {x:.1f} {y:.1f} {width:.1f} {height:.1f} re S"
            )

    def draw_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = _BORDER,
        width: float = 0.7,
    ) -> None:
        self.add_command(
            f"{_rgb(color)} RG {width:.1f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S"
        )

    def write_text(
        self,
        text: str,
        size: int | None = None,
        bold: bool = False,
        indent: float = 0,
        color: tuple[float, float, float] = _BLACK,
        leading: float | None = None,
    ) -> None:
        font_size = size or _FONT_SIZE
        line_height = leading or _line_height(font_size)
        self.ensure_space(line_height)
        self.add_command(
            f"BT {_rgb(color)} rg "
            f"/F{'B' if bold else 'H'} {font_size} Tf "
            f"{_MARGIN + indent:.1f} {self.y:.1f} Td "
            f"({_escape_pdf(text)}) Tj ET"
        )
        self.y -= line_height

    def write_wrapped(
        self,
        text: str,
        size: int | None = None,
        bold: bool = False,
        indent: float = 0,
        color: tuple[float, float, float] = _BLACK,
        max_chars: int | None = None,
        paragraph_gap: float = 4,
    ) -> None:
        font_size = size or _FONT_SIZE
        width = max(_CONTENT_WIDTH - indent, 60)
        chars = max_chars or _chars_for_width(width, font_size)
        lines = _wrap_text(text, chars)
        for line in lines:
            self.write_text(line, size=font_size, bold=bold, indent=indent, color=color)
        self.y -= paragraph_gap

    def draw_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        col_widths: list[float] | None = None,
    ) -> None:
        if not headers:
            return
        if col_widths is None:
            col_widths = [_CONTENT_WIDTH / len(headers)] * len(headers)
        if len(col_widths) != len(headers):
            col_widths = [_CONTENT_WIDTH / len(headers)] * len(headers)

        def draw_header() -> None:
            self.ensure_space(_TABLE_LINE_HEIGHT + 4)
            x = _MARGIN
            y = self.y
            for header, width in zip(headers, col_widths):
                self.draw_rect(
                    x,
                    y - _TABLE_LINE_HEIGHT + 3,
                    width,
                    _TABLE_LINE_HEIGHT,
                    fill=_LIGHT_BLUE,
                    stroke=_BORDER,
                )
                self.add_command(
                    f"BT {_rgb(_NAVY)} rg /FB 9 Tf {x + 4:.1f} {y - 9:.1f} Td "
                    f"({_escape_pdf(_fit_text(header, width - 8, 9))}) Tj ET"
                )
                x += width
            self.y -= _TABLE_LINE_HEIGHT

        draw_header()
        for row_index, row in enumerate(rows):
            cells = [str(cell or "") for cell in row]
            while len(cells) < len(headers):
                cells.append("")
            cell_lines = [
                _wrap_text(cell, max(_chars_for_width(width - 8, _FONT_SIZE - 1), 8))
                for cell, width in zip(cells, col_widths)
            ]
            fill = _LIGHT_GRAY if row_index % 2 else _WHITE
            max_line_count = max(len(lines) for lines in cell_lines)
            offset = 0
            while offset < max_line_count:
                available_height = self.y - _BOTTOM_MARGIN
                max_lines_this_page = int((available_height - 8) / (_LINE_HEIGHT - 1))
                if max_lines_this_page <= 0:
                    self.add_page()
                    draw_header()
                    continue

                chunk_size = min(max_lines_this_page, max_line_count - offset)
                chunked_cells = [lines[offset:offset + chunk_size] for lines in cell_lines]
                chunk_line_count = max((len(lines) for lines in chunked_cells), default=1)
                row_height = max(
                    _TABLE_LINE_HEIGHT,
                    chunk_line_count * (_LINE_HEIGHT - 1) + 8,
                )
                if self.y - row_height < _BOTTOM_MARGIN:
                    self.add_page()
                    draw_header()
                    continue

                x = _MARGIN
                top = self.y
                for lines, width in zip(chunked_cells, col_widths):
                    self.draw_rect(
                        x,
                        top - row_height + 3,
                        width,
                        row_height,
                        fill=fill,
                        stroke=_BORDER,
                    )
                    text_y = top - 10
                    for line in lines:
                        self.add_command(
                            f"BT {_rgb(_BLACK)} rg /FH 9 Tf {x + 4:.1f} {text_y:.1f} Td "
                            f"({_escape_pdf(line)}) Tj ET"
                        )
                        text_y -= _LINE_HEIGHT - 1
                    x += width
                self.y -= row_height
                offset += chunk_size
        self.y -= 8


def write_text_pdf_from_markdown(markdown_path: str | Path, output_pdf_path: str | Path) -> None:
    markdown_path = Path(markdown_path)
    output_pdf_path = Path(output_pdf_path)
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    text = markdown_path.read_text(encoding="utf-8")
    parsed = _parse_markdown(text)

    canvas = _PdfCanvas()
    _render_document(canvas, parsed)

    pdf_bytes = _build_pdf_bytes(canvas)
    output_pdf_path.write_bytes(pdf_bytes)


def _parse_markdown(text: str) -> list[dict[str, Any]]:
    lines = text.split("\n")
    blocks: list[dict[str, Any]] = []
    in_table = False
    table_headers: list[str] = []
    table_rows: list[list[str]] = []
    table_col_widths: list[float] | None = None

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                in_table = True
                table_headers = cells
                table_rows = []
            elif re.match(r"^[\s|:\-]+$", stripped):
                col_count = len(cells)
                table_col_widths = [_CONTENT_WIDTH / max(col_count, 1)] * max(col_count, 1)
            else:
                table_rows.append(cells)
            continue

        if in_table and table_headers:
            blocks.append({
                "type": "table",
                "headers": table_headers,
                "rows": table_rows,
                "col_widths": table_col_widths,
            })
            in_table = False
            table_headers = []
            table_rows = []
            table_col_widths = None

        if not stripped:
            blocks.append({"type": "spacer"})
            continue

        heading = re.match(r"^(#{1,5})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            blocks.append({
                "type": "heading",
                "level": level,
                "text": _strip_inline_markdown(heading.group(2).strip()),
            })
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({
                "type": "bullet",
                "text": _strip_inline_markdown(stripped[2:].strip()),
            })
            continue

        blocks.append({
            "type": "paragraph",
            "text": _strip_inline_markdown(stripped),
        })

    if in_table and table_headers:
        blocks.append({
            "type": "table",
            "headers": table_headers,
            "rows": table_rows,
            "col_widths": table_col_widths,
        })

    return blocks


def _render_document(canvas: _PdfCanvas, blocks: list[dict[str, Any]]) -> None:
    title = "Detailed Migration Report"
    start = 0
    if blocks and blocks[0].get("type") == "heading" and int(blocks[0].get("level", 1)) == 1:
        title = str(blocks[0].get("text") or title)
        start = 1
    _draw_report_header(canvas, title)

    for block in blocks[start:]:
        block_type = block.get("type", "")

        if block_type == "spacer":
            canvas.y -= 5
            continue

        if block_type == "heading":
            level = int(block.get("level", 1))
            _draw_heading(canvas, str(block.get("text", "")), level)
            continue

        if block_type == "paragraph":
            canvas.write_wrapped(str(block.get("text", "")), size=10, color=_BLACK, paragraph_gap=7)
            continue

        if block_type == "bullet":
            canvas.write_wrapped(f"- {block.get('text', '')}", size=10, indent=12, color=_BLACK, paragraph_gap=2)
            continue

        if block_type == "table":
            headers = [_strip_inline_markdown(str(h)) for h in block.get("headers", [])]
            rows = [
                [_strip_inline_markdown(str(cell)) for cell in row]
                for row in block.get("rows", [])
            ]
            col_widths = _table_widths(headers)
            canvas.draw_table(headers, rows, col_widths=col_widths)
            continue


def _draw_report_header(canvas: _PdfCanvas, title: str) -> None:
    canvas.draw_rect(0, _PAGE_HEIGHT - 104, _PAGE_WIDTH, 104, fill=_NAVY)
    canvas.draw_rect(_MARGIN, _PAGE_HEIGHT - 118, 84, 6, fill=_TEAL)
    canvas.add_command(
        f"BT {_rgb(_WHITE)} rg /FB 24 Tf {_MARGIN:.1f} {_PAGE_HEIGHT - 48:.1f} Td "
        f"({_escape_pdf(_fit_text(title, _CONTENT_WIDTH, 24))}) Tj ET"
    )
    canvas.add_command(
        f"BT {_rgb((0.82, 0.89, 0.96))} rg /FH 10 Tf {_MARGIN:.1f} {_PAGE_HEIGHT - 72:.1f} Td "
        f"(Evidence-backed migration summary, technical progress, validation, and limitations) Tj ET"
    )
    canvas.y = _PAGE_HEIGHT - 138


def _draw_heading(canvas: _PdfCanvas, text: str, level: int) -> None:
    size = _HEADING_SIZES.get(level, 10)
    if level <= 2:
        canvas.ensure_space(42)
        canvas.y -= 6
        canvas.draw_rect(_MARGIN, canvas.y - 19, 4, 22, fill=_TEAL)
        canvas.write_text(text, size=size, bold=True, indent=12, color=_NAVY, leading=22)
        canvas.draw_line(
            _MARGIN,
            canvas.y + 4,
            _PAGE_WIDTH - _MARGIN,
            canvas.y + 4,
            color=_BORDER,
        )
        canvas.y -= 4
    elif level == 3:
        canvas.ensure_space(28)
        canvas.y -= 4
        canvas.write_text(text, size=size, bold=True, color=_BLUE, leading=18)
    else:
        canvas.write_text(text, size=size, bold=True, color=_GRAY)


def _build_pdf_bytes(canvas: _PdfCanvas) -> bytes:
    pages = canvas.pages or [[]]
    content_start = 6
    page_start = content_start + len(pages)
    page_refs = [page_start + index for index in range(len(pages))]

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            b"<< /Type /Pages /Kids ["
            + b" ".join(f"{ref} 0 R".encode() for ref in page_refs)
            + b"] /Count "
            + str(len(pages)).encode()
            + b" >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Font <</FH 3 0 R /FB 4 0 R>> >>",
    ]

    total_pages = len(pages)
    for page_number, page_content in enumerate(pages, start=1):
        stream_commands = _page_frame(page_number, total_pages) + page_content
        stream = b"q\n" + b"\n".join(
            line.encode("latin-1", errors="replace") if isinstance(line, str) else line
            for line in stream_commands
        ) + b"\nQ\n"
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode()
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )

    for content_ref in range(content_start, content_start + len(pages)):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            + str(_PAGE_WIDTH).encode()
            + b" "
            + str(_PAGE_HEIGHT).encode()
            + b"] /Contents "
            + str(content_ref).encode()
            + b" 0 R /Resources 5 0 R >>"
        )

    header = b"%PDF-1.4\n"
    body = b""
    for obj_num, data in enumerate(objects, start=1):
        body += f"{obj_num} 0 obj\n".encode() + data + b"\nendobj\n"

    xref_offset = len(header + body)
    xref = b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    xref += b"0000000000 65535 f \n"
    position = len(header)
    for obj_num, data in enumerate(objects, start=1):
        xref += f"{position:010d} 00000 n \n".encode()
        position += len(f"{obj_num} 0 obj\n".encode() + data + b"\nendobj\n")

    trailer = (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root 1 0 R >>\n"
    )
    eof = b"startxref\n" + str(xref_offset).encode() + b"\n%%EOF\n"

    return header + body + xref + trailer + eof


def _page_frame(page_number: int, total_pages: int) -> list[str]:
    return [
        f"{_rgb(_WHITE)} rg 0 0 {_PAGE_WIDTH:.1f} {_PAGE_HEIGHT:.1f} re f",
        f"{_rgb(_LIGHT_TEAL)} rg 0 0 {_PAGE_WIDTH:.1f} 28.0 re f",
        f"{_rgb(_BORDER)} RG 0.6 w {_MARGIN:.1f} 42.0 m {_PAGE_WIDTH - _MARGIN:.1f} 42.0 l S",
        (
            f"BT {_rgb(_GRAY)} rg /FH 8 Tf {_MARGIN:.1f} 24.0 Td "
            f"({_escape_pdf('Detailed Migration Report')}) Tj ET"
        ),
        (
            f"BT {_rgb(_GRAY)} rg /FH 8 Tf {_PAGE_WIDTH - _MARGIN - 62:.1f} 24.0 Td "
            f"({_escape_pdf(f'Page {page_number} of {total_pages}')}) Tj ET"
        ),
    ]


def _table_widths(headers: list[str]) -> list[float] | None:
    normalized = [header.strip().lower() for header in headers]
    if normalized == ["metric", "value"]:
        return [_CONTENT_WIDTH * 0.42, _CONTENT_WIDTH * 0.58]
    if normalized == ["time", "stage", "event", "status", "detail"]:
        return [96, 42, 96, 70, _CONTENT_WIDTH - 304]
    if normalized == ["phase", "duration"]:
        return [_CONTENT_WIDTH * 0.62, _CONTENT_WIDTH * 0.38]
    if normalized == ["event type", "count"]:
        return [_CONTENT_WIDTH * 0.72, _CONTENT_WIDTH * 0.28]
    return None


def _fit_text(text: str, width: float, font_size: int) -> str:
    value = str(text)
    max_chars = max(_chars_for_width(width, font_size), 4)
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return "." * max_chars
    return value[:max_chars - 3].rstrip() + "..."

def _strip_inline_markdown(text: str) -> str:
    text = str(text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = text.replace("<br />", " ").replace("<br>", " ")
    return text.strip()


def _escape_pdf(text: str) -> str:
    text = str(text)
    text = text.replace("\\", "\\\\")
    text = text.replace("(", "\\(")
    text = text.replace(")", "\\)")
    text = text.replace("\n", "\\n")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", " ")
    return text


def _wrap_text(text: str, max_chars: int = _MAX_CELL_CHARS) -> list[str]:
    text = str(text)
    text = text.replace("<br />", "\n").replace("<br>", "\n")
    if len(text) <= max_chars and "\n" not in text:
        return [text]

    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        while len(paragraph) > max_chars:
            split = _split_long_word(paragraph, max_chars)
            if split:
                part, paragraph = split
            else:
                part = paragraph[:max_chars]
                paragraph = paragraph[max_chars:]
            lines.append(part.rstrip())
            paragraph = paragraph.lstrip()
        if paragraph:
            lines.append(paragraph)

    return lines if lines else [""]


def _split_long_word(text: str, max_chars: int) -> tuple[str, str] | None:
    if len(text) <= max_chars:
        return None
    for sep in ("/", "\\", ".", "-", "_", ":", " "):
        idx = text.rfind(sep, 0, max_chars)
        if idx > 0:
            return text[:idx + 1], text[idx + 1:]
    return None


def _chars_for_width(width: float, font_size: int) -> int:
    return max(int(width / max(font_size * 0.48, 1)), 12)


def _line_height(font_size: int) -> float:
    return max(font_size + 4, _LINE_HEIGHT)


def _rgb(color: tuple[float, float, float]) -> str:
    return " ".join(f"{component:.3f}" for component in color)


def _table_height(rows: list[list[str]], col_widths: list[float]) -> float:
    if not rows:
        return 0
    height = _TABLE_LINE_HEIGHT
    for row in rows:
        max_lines = 1
        for cell, width in zip(row, col_widths):
            wrapped = _wrap_text(str(cell or ""), _chars_for_width(width - 8, _FONT_SIZE - 1))
            max_lines = max(max_lines, len(wrapped))
        height += max(_TABLE_LINE_HEIGHT, max_lines * (_LINE_HEIGHT - 1) + 8)
    return height
