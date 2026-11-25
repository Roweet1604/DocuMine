"""Converts the simple Markdown that DocuMine generates into a .docx file."""

import io
import re

import docx


def markdown_to_docx(markdown: str) -> bytes:
    """Headings, bullet and numbered lists, tables and paragraphs. Inline formatting is dropped."""
    document = docx.Document()
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):  # skip |---|---|
                    rows.append(cells)
                i += 1
            _add_table(document, rows)
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", line)
        if heading:
            document.add_heading(_plain(heading.group(2)), level=min(len(heading.group(1)), 4))
        elif re.match(r"\s*[-*]\s+", line):
            document.add_paragraph(_plain(re.sub(r"^\s*[-*]\s+", "", line)), style="List Bullet")
        elif re.match(r"\s*\d+\.\s+", line):
            document.add_paragraph(_plain(re.sub(r"^\s*\d+\.\s+", "", line)), style="List Number")
        elif line.strip():
            document.add_paragraph(_plain(line.lstrip("> ")))
        i += 1
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _add_table(document, rows: list[list[str]]) -> None:
    if not rows:
        return
    table = document.add_table(rows=len(rows), cols=max(len(r) for r in rows))
    table.style = "Table Grid"
    for row, cells in zip(table.rows, rows):
        for cell, text in zip(row.cells, cells):
            cell.text = _plain(text)


def _plain(text: str) -> str:
    text = re.sub(r"(\*\*|__|`)", "", text)
    if len(text) > 1 and text[0] == text[-1] and text[0] in "_*":
        text = text[1:-1]
    return text.strip()
