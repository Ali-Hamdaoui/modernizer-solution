from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_PAGE_WIDTH = 612.0
_PAGE_HEIGHT = 792.0
_MARGIN_X = 44.0
_MARGIN_TOP = 42.0
_MARGIN_BOTTOM = 42.0
_CONTENT_WIDTH = _PAGE_WIDTH - (_MARGIN_X * 2)
_FONT_REGULAR = "F1"
_FONT_BOLD = "F2"
_FONT_ITALIC = "F3"
_BODY_SIZE = 10.5
_SMALL_SIZE = 9.0
_SECTION_SIZE = 18.0
_SUBSECTION_SIZE = 14.0
_TITLE_SIZE = 24.0
_LINE_GAP = 4.0
_PARAGRAPH_GAP = 10.0
_SECTION_GAP = 16.0
_TABLE_CELL_PAD_X = 6.0
_TABLE_CELL_PAD_Y = 5.0

_NAVY = (0.09, 0.20, 0.37)
_TEAL = (0.10, 0.50, 0.54)
_TEXT = (0.14, 0.16, 0.20)
_MUTED = (0.33, 0.39, 0.45)
_BORDER = (0.80, 0.84, 0.88)
_ROW_ALT = (0.97, 0.98, 0.99)
_HEADER_FILL = (0.17, 0.30, 0.48)
_WHITE = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class _TextStyle:
    font: str
    size: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class _HeadingBlock:
    level: int
    text: str


@dataclass(frozen=True)
class _ParagraphBlock:
    text: str


@dataclass(frozen=True)
class _BulletBlock:
    text: str


@dataclass(frozen=True)
class _TableBlock:
    rows: list[list[str]]


_Block = _HeadingBlock | _ParagraphBlock | _BulletBlock | _TableBlock


class _PdfCanvas:
    def __init__(self) -> None:
        self._pages: list[list[str]] = [[]]
        self._page_index = 0
        self._cursor_y = _PAGE_HEIGHT - _MARGIN_TOP

    def ensure_space(self, height: float) -> None:
        if self._cursor_y - height < _MARGIN_BOTTOM:
            self.new_page()

    def new_page(self) -> None:
        self._pages.append([])
        self._page_index += 1
        self._cursor_y = _PAGE_HEIGHT - _MARGIN_TOP

    def draw_rect(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        fill: tuple[float, float, float] | None = None,
        stroke: tuple[float, float, float] | None = None,
        line_width: float = 1.0,
    ) -> None:
        commands: list[str] = []
        if fill is not None:
            commands.append(_fill_color(fill))
        if stroke is not None:
            commands.append(_stroke_color(stroke))
            commands.append(f"{line_width:.2f} w")
        mode = "B" if fill is not None and stroke is not None else "f" if fill is not None else "S"
        commands.append(f"{x:.2f} {y:.2f} {width:.2f} {height:.2f} re {mode}")
        self._append(commands)

    def draw_text(self, x: float, y: float, text: str, style: _TextStyle) -> None:
        self._append(
            [
                "BT",
                _fill_color(style.color),
                f"/{style.font} {style.size:.2f} Tf",
                f"1 0 0 1 {x:.2f} {y:.2f} Tm",
                f"({_escape_pdf_text(text)}) Tj",
                "ET",
            ]
        )

    def draw_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        color: tuple[float, float, float] = _BORDER,
        line_width: float = 1.0,
    ) -> None:
        self._append(
            [
                _stroke_color(color),
                f"{line_width:.2f} w",
                f"{x1:.2f} {y1:.2f} m",
                f"{x2:.2f} {y2:.2f} l S",
            ]
        )

    def move_cursor(self, amount: float) -> None:
        self._cursor_y -= amount

    @property
    def cursor_y(self) -> float:
        return self._cursor_y

    @property
    def pages(self) -> list[list[str]]:
        return self._pages

    def _append(self, commands: list[str]) -> None:
        self._pages[self._page_index].extend(commands)


def write_text_pdf_from_markdown(markdown_path: str | Path, pdf_path: str | Path) -> Path:
    source_path = Path(markdown_path)
    output_path = Path(pdf_path)
    markdown = source_path.read_text(encoding="utf-8")
    blocks = _parse_markdown(markdown)
    canvas = _PdfCanvas()
    _render_document(canvas, blocks)
    output_path.write_bytes(_build_pdf_bytes(canvas.pages))
    return output_path


def _parse_markdown(markdown: str) -> list[_Block]:
    lines = markdown.splitlines()
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            blocks.append(_HeadingBlock(level=min(level, 6), text=stripped[level:].strip()))
            index += 1
            continue
        if stripped.startswith("|"):
            table_lines = [stripped]
            index += 1
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            rows = []
            for row_index, row in enumerate(table_lines):
                if row_index == 1 and set(row.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                    continue
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append(_TableBlock(rows=rows))
            continue
        if stripped.startswith("- "):
            blocks.append(_BulletBlock(text=stripped[2:].strip()))
            index += 1
            continue
        paragraph_lines = [stripped]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            if not candidate or candidate.startswith("#") or candidate.startswith("|") or candidate.startswith("- "):
                break
            paragraph_lines.append(candidate)
            index += 1
        blocks.append(_ParagraphBlock(text=" ".join(paragraph_lines)))
    return blocks


def _render_document(canvas: _PdfCanvas, blocks: list[_Block]) -> None:
    if blocks and isinstance(blocks[0], _HeadingBlock) and blocks[0].level == 1:
        _render_title_banner(canvas, blocks[0].text)
        blocks = blocks[1:]
    else:
        _render_title_banner(canvas, "Final Migration Report")
    for block in blocks:
        if isinstance(block, _HeadingBlock):
            _render_heading(canvas, block)
        elif isinstance(block, _ParagraphBlock):
            _render_paragraph(canvas, block.text)
        elif isinstance(block, _BulletBlock):
            _render_bullet(canvas, block.text)
        elif isinstance(block, _TableBlock):
            _render_table(canvas, block.rows)


def _render_title_banner(canvas: _PdfCanvas, title: str) -> None:
    banner_height = 94.0
    canvas.ensure_space(banner_height + 24.0)
    banner_y = canvas.cursor_y - banner_height
    canvas.draw_rect(_MARGIN_X, banner_y, _CONTENT_WIDTH, banner_height, fill=_NAVY)
    canvas.draw_rect(_MARGIN_X, banner_y, 10.0, banner_height, fill=_TEAL)
    canvas.draw_text(_MARGIN_X + 20.0, banner_y + 56.0, title, _TextStyle(_FONT_BOLD, _TITLE_SIZE, _WHITE))
    canvas.draw_text(
        _MARGIN_X + 20.0,
        banner_y + 28.0,
        "Governed sandbox migration report",
        _TextStyle(_FONT_REGULAR, 11.0, (0.88, 0.93, 0.97)),
    )
    canvas.move_cursor(banner_height + 22.0)


def _render_heading(canvas: _PdfCanvas, block: _HeadingBlock) -> None:
    size = _SECTION_SIZE if block.level == 2 else _SUBSECTION_SIZE if block.level == 3 else 12.0
    style = _TextStyle(_FONT_BOLD, size, _NAVY if block.level <= 2 else _TEXT)
    height = size + 8.0
    canvas.ensure_space(height + _PARAGRAPH_GAP)
    if block.level == 2:
        y_line = canvas.cursor_y - 3.0
        canvas.draw_line(_MARGIN_X, y_line, _PAGE_WIDTH - _MARGIN_X, y_line, color=_BORDER, line_width=1.2)
        canvas.move_cursor(10.0)
    canvas.draw_text(_MARGIN_X, canvas.cursor_y - size, block.text, style)
    canvas.move_cursor(height)


def _render_paragraph(canvas: _PdfCanvas, text: str) -> None:
    lines = _wrap_text(text, _BODY_SIZE, _CONTENT_WIDTH)
    height = len(lines) * (_BODY_SIZE + _LINE_GAP) + _PARAGRAPH_GAP
    canvas.ensure_space(height)
    current_y = canvas.cursor_y
    for line in lines:
        canvas.draw_text(_MARGIN_X, current_y - _BODY_SIZE, line, _TextStyle(_FONT_REGULAR, _BODY_SIZE, _TEXT))
        current_y -= _BODY_SIZE + _LINE_GAP
    canvas.move_cursor(height)


def _render_bullet(canvas: _PdfCanvas, text: str) -> None:
    bullet_indent = 16.0
    wrap_width = _CONTENT_WIDTH - bullet_indent
    lines = _wrap_text(text, _BODY_SIZE, wrap_width)
    height = len(lines) * (_BODY_SIZE + _LINE_GAP) + 3.0
    canvas.ensure_space(height + 2.0)
    current_y = canvas.cursor_y
    canvas.draw_text(_MARGIN_X, current_y - _BODY_SIZE, "•", _TextStyle(_FONT_BOLD, _BODY_SIZE + 1.0, _TEAL))
    for index, line in enumerate(lines):
        x = _MARGIN_X + bullet_indent
        canvas.draw_text(x, current_y - _BODY_SIZE, line, _TextStyle(_FONT_REGULAR, _BODY_SIZE, _TEXT))
        current_y -= _BODY_SIZE + _LINE_GAP
        if index == 0:
            continue
    canvas.move_cursor(height)


def _render_table(canvas: _PdfCanvas, rows: list[list[str]]) -> None:
    if not rows:
        return
    normalized_rows = [list(row) for row in rows]
    column_count = max(len(row) for row in normalized_rows)
    normalized_rows = [row + [""] * (column_count - len(row)) for row in normalized_rows]
    widths = _table_column_widths(normalized_rows, _CONTENT_WIDTH)
    row_heights = [_table_row_height(row, widths, _BODY_SIZE if index else _SMALL_SIZE + 0.5) for index, row in enumerate(normalized_rows)]
    total_height = sum(row_heights) + _PARAGRAPH_GAP
    canvas.ensure_space(total_height)
    top_y = canvas.cursor_y
    current_top = top_y
    for row_index, row in enumerate(normalized_rows):
        row_height = row_heights[row_index]
        y_bottom = current_top - row_height
        fill = _HEADER_FILL if row_index == 0 else _ROW_ALT if row_index % 2 == 0 else _WHITE
        canvas.draw_rect(_MARGIN_X, y_bottom, _CONTENT_WIDTH, row_height, fill=fill, stroke=_BORDER, line_width=0.8)
        x = _MARGIN_X
        for col_index, cell in enumerate(row):
            if col_index:
                canvas.draw_line(x, current_top, x, y_bottom, color=_BORDER, line_width=0.8)
            style = _TextStyle(_FONT_BOLD if row_index == 0 else _FONT_REGULAR, _SMALL_SIZE + 0.5 if row_index == 0 else _BODY_SIZE, _WHITE if row_index == 0 else _TEXT)
            wrapped = _wrap_text(cell or " ", style.size, widths[col_index] - (_TABLE_CELL_PAD_X * 2))
            text_y = current_top - _TABLE_CELL_PAD_Y - style.size
            for line in wrapped:
                canvas.draw_text(x + _TABLE_CELL_PAD_X, text_y, line, style)
                text_y -= style.size + 2.5
            x += widths[col_index]
        current_top = y_bottom
    canvas.move_cursor(total_height)


def _table_column_widths(rows: list[list[str]], available_width: float) -> list[float]:
    column_count = len(rows[0])
    weights = [1.0] * column_count
    for column in range(column_count):
        max_len = max(len(row[column]) for row in rows)
        weights[column] = max(1.0, min(float(max_len), 30.0))
    total = sum(weights) or 1.0
    widths = [available_width * (weight / total) for weight in weights]
    min_width = max(available_width / column_count * 0.55, 72.0 if column_count <= 3 else 52.0)
    adjusted = [max(width, min_width) for width in widths]
    scale = available_width / sum(adjusted)
    return [width * scale for width in adjusted]


def _table_row_height(row: list[str], widths: list[float], font_size: float) -> float:
    line_counts = [
        max(1, len(_wrap_text(cell or " ", font_size, widths[index] - (_TABLE_CELL_PAD_X * 2))))
        for index, cell in enumerate(row)
    ]
    return max(line_counts) * (font_size + 2.5) + (_TABLE_CELL_PAD_Y * 2) + 2.0


def _wrap_text(text: str, font_size: float, width: float) -> list[str]:
    plain = text.replace("**", "").replace("`", "")
    lines: list[str] = []
    for paragraph in plain.replace("<br />", "\n").replace("<br>", "\n").splitlines() or [""]:
        words = [
            chunk
            for word in paragraph.split()
            for chunk in _split_long_word(word, font_size, width)
        ]
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if _estimate_text_width(candidate, font_size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _split_long_word(word: str, font_size: float, width: float) -> list[str]:
    if _estimate_text_width(word, font_size) <= width:
        return [word]

    max_chars = max(1, int(width / (font_size * 0.52)))
    chunks: list[str] = []
    remaining = word
    separators = ("/", "\\", "_", "-", ".", ":")
    while remaining:
        if _estimate_text_width(remaining, font_size) <= width:
            chunks.append(remaining)
            break
        split_at = max_chars
        for index in range(min(max_chars, len(remaining) - 1), 0, -1):
            if remaining[index - 1] in separators:
                split_at = index
                break
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    return chunks


def _estimate_text_width(text: str, font_size: float) -> float:
    return len(text) * font_size * 0.52


def _build_pdf_bytes(page_commands: list[list[str]]) -> bytes:
    objects: list[bytes] = []

    def add_object(payload: bytes) -> int:
        objects.append(payload)
        return len(objects)

    regular_font = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    bold_font = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    italic_font = add_object(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>")

    content_ids: list[int] = []
    for commands in page_commands:
        stream = "\n".join(commands).encode("latin-1", errors="replace")
        content_ids.append(
            add_object(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream")
        )

    pages_id = add_object(b"<< /Type /Pages /Kids [] /Count 0 >>")
    page_ids: list[int] = []
    for content_id in content_ids:
        page_ids.append(
            add_object(
                (
                    f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {_PAGE_WIDTH:.0f} {_PAGE_HEIGHT:.0f}] "
                    f"/Resources << /Font << /{_FONT_REGULAR} {regular_font} 0 R /{_FONT_BOLD} {bold_font} 0 R /{_FONT_ITALIC} {italic_font} 0 R >> >> "
                    f"/Contents {content_id} 0 R >>"
                ).encode("ascii")
            )
        )
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")
    catalog_id = add_object(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, payload in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(payload)
        pdf.extend(b"\nendobj\n")
    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(pdf)


def _fill_color(color: tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg"


def _stroke_color(color: tuple[float, float, float]) -> str:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG"


def _escape_pdf_text(value: str) -> str:
    cleaned = value.replace("—", "-").replace("–", "-").replace("•", "*").replace("→", "->")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
