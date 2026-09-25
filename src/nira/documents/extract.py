"""Extract readable text from an uploaded file.

Everything here takes bytes and returns text, with no I/O of its own and no
FastAPI types, so the same code serves the HTTP upload path, chat attachments
and the CLI. Failures raise :class:`ExtractionError` with a message written for
the person who attached the file, not for a log.

Two decisions worth stating, because they are not obvious from the code:

**Everything is capped.** A 200-page PDF or a 50,000-row spreadsheet does not
fit in a context window, and silently sending the first N characters is worse
than saying what was cut: the model answers confidently about a document it
only partly saw. Every extractor stops at a limit and records what it left
behind, so the caller can tell the user.

**Spreadsheets keep their shape.** Flattening a grid to prose destroys the
thing that makes it a spreadsheet. Sheets come out as Markdown tables, which
models read reliably and which survive a round trip through a text field.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "SUPPORTED_TEXT_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "extract_text",
    "is_image",
]


class ExtractionError(RuntimeError):
    """The file could not be read. The message is shown to the user."""


# Roughly 25k characters ≈ 6-8k tokens: large enough for a long report, small
# enough to leave the model room to answer. Per file, and several files can be
# attached, so the caller also enforces a total.
MAX_CHARS_PER_FILE = 25_000

# Spreadsheets: a cap on rows *and* columns. A sheet wider than this is
# usually a pivot table or a dump, where the first columns carry the meaning.
MAX_SHEET_ROWS = 200
MAX_SHEET_COLS = 30
MAX_SHEETS = 10

SUPPORTED_TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".csv",
    ".tsv",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".html",
    ".pdf",
    ".docx",
    ".xlsx",
    ".xlsm",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


@dataclass
class ExtractionResult:
    """Text pulled out of a file, and an honest note about what was left."""

    text: str
    #: Human-readable notes: pages skipped, rows truncated, sheets dropped.
    notes: List[str] = field(default_factory=list)
    #: True when the file was cut short by a limit.
    truncated: bool = False

    def with_note(self, note: str) -> "ExtractionResult":
        self.notes.append(note)
        return self


def is_image(filename: str) -> bool:
    """Whether *filename* is an image, which goes to a vision model instead."""
    return _suffix(filename) in IMAGE_EXTENSIONS


def _suffix(filename: str) -> str:
    _, _, ext = filename.rpartition(".")
    return f".{ext.lower()}" if ext and ext != filename else ""


def _cap(text: str, result: ExtractionResult, what: str) -> str:
    if len(text) <= MAX_CHARS_PER_FILE:
        return text
    result.truncated = True
    result.with_note(
        f"{what} is {len(text):,} characters; only the first "
        f"{MAX_CHARS_PER_FILE:,} were read."
    )
    return text[:MAX_CHARS_PER_FILE]


# ---------------------------------------------------------------------------
# Per-format extractors
# ---------------------------------------------------------------------------


def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ExtractionError(
            "Reading PDFs needs pdfplumber. Install it with: "
            "uv sync --extra attachments"
        ) from exc

    result = ExtractionResult(text="")
    pages: List[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            total = len(pdf.pages)
            for index, page in enumerate(pdf.pages):
                pages.append(page.extract_text() or "")
                # Stop early rather than parsing 200 pages we will then throw
                # away — extraction is the slow part, not the truncation.
                if sum(len(p) for p in pages) > MAX_CHARS_PER_FILE:
                    if index + 1 < total:
                        result.truncated = True
                        result.with_note(
                            f"Read {index + 1} of {total} pages before reaching "
                            "the size limit."
                        )
                    break
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"This PDF could not be read: {exc}") from exc

    result.text = _cap("\n\n".join(pages).strip(), result, "This PDF")
    if not result.text:
        result.with_note(
            "No selectable text found — this looks like a scanned PDF. "
            "Attach it as an image instead so a vision model can read it."
        )
    return result


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ExtractionError(
            "Reading Word documents needs python-docx. Install it with: "
            "uv sync --extra attachments"
        ) from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise ExtractionError(f"This Word document could not be read: {exc}") from exc

    result = ExtractionResult(text="")
    parts = [p.text for p in document.paragraphs if p.text.strip()]

    # Tables are content, not decoration. A .docx report often puts its
    # numbers in one, and dropping them silently loses the point of the file.
    for table in document.tables:
        rows = []
        for row in table.rows[:MAX_SHEET_ROWS]:
            cells = [c.text.replace("\n", " ").strip() for c in row.cells]
            rows.append(cells)
        if rows:
            parts.append(_as_markdown_table(rows))
    if len(document.tables) and len(document.tables[0].rows) > MAX_SHEET_ROWS:
        result.with_note(f"Tables were cut to {MAX_SHEET_ROWS} rows.")

    result.text = _cap("\n\n".join(parts).strip(), result, "This document")
    return result


def _extract_xlsx(data: bytes) -> ExtractionResult:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise ExtractionError(
            "Reading Excel files needs openpyxl. Install it with: "
            "uv sync --extra attachments"
        ) from exc

    result = ExtractionResult(text="")
    try:
        # read_only + data_only: stream rather than build the whole object
        # model, and give us the cached values of formulas rather than the
        # formula text, which is what someone asking "what does this say"
        # means.
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ExtractionError(f"This spreadsheet could not be read: {exc}") from exc

    try:
        blocks: List[str] = []
        sheets = book.worksheets
        if len(sheets) > MAX_SHEETS:
            result.with_note(
                f"This workbook has {len(sheets)} sheets; the first "
                f"{MAX_SHEETS} were read."
            )
            result.truncated = True
            sheets = sheets[:MAX_SHEETS]

        for sheet in sheets:
            rows: List[List[str]] = []
            for row_index, row in enumerate(sheet.iter_rows(values_only=True)):
                if row_index >= MAX_SHEET_ROWS:
                    result.truncated = True
                    result.with_note(
                        f"Sheet {sheet.title!r} was cut to {MAX_SHEET_ROWS} rows."
                    )
                    break
                cells = ["" if v is None else str(v) for v in row[:MAX_SHEET_COLS]]
                if any(c.strip() for c in cells):
                    rows.append(cells)
            if rows:
                blocks.append(f"### Sheet: {sheet.title}\n\n{_as_markdown_table(rows)}")
        result.text = _cap("\n\n".join(blocks).strip(), result, "This spreadsheet")
    finally:
        book.close()

    if not result.text:
        result.with_note("This spreadsheet appears to be empty.")
    return result


def _extract_delimited(data: bytes, delimiter: str) -> ExtractionResult:
    result = ExtractionResult(text="")
    text = _decode(data)
    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = []
        for index, row in enumerate(reader):
            if index >= MAX_SHEET_ROWS:
                result.truncated = True
                result.with_note(f"Only the first {MAX_SHEET_ROWS} rows were read.")
                break
            rows.append([c.strip() for c in row[:MAX_SHEET_COLS]])
    except csv.Error as exc:
        raise ExtractionError(f"This file could not be parsed: {exc}") from exc

    if not rows:
        return result.with_note("This file appears to be empty.")
    result.text = _cap(_as_markdown_table(rows), result, "This file")
    return result


def _extract_plain(data: bytes) -> ExtractionResult:
    result = ExtractionResult(text="")
    result.text = _cap(_decode(data).strip(), result, "This file")
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    """Decode bytes as text, preferring UTF-8 and never raising.

    A file that is nearly-UTF-8 — a CSV exported from a Windows tool, say —
    should still be readable. Replacing the undecodable bytes loses a
    character; refusing loses the document.

    UTF-16 is tried **only** when a byte-order mark says so. It is not a
    fallback: UTF-16 decodes almost any even-length byte sequence without
    error, so trying it speculatively turns a cp1252 file into fluent
    mojibake — "caf\xe9" comes back as "慮敭挊晡" and nothing raises. Ask for
    the BOM or do not ask.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        # The de-facto default for Windows exports in Western locales, and a
        # superset of latin-1 for the punctuation those tools emit.
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _as_markdown_table(rows: List[List[str]]) -> str:
    """Render rows as a Markdown table, padded to the widest row.

    Markdown rather than CSV because the grid survives: a model reading
    `| Q3 | 41,200 |` can tell which number belongs to which column, where a
    flattened line of prose cannot.
    """
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [r + [""] * (width - len(r)) for r in rows]
    header, *body = padded
    lines = [
        "| " + " | ".join(_escape_cell(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines.extend("| " + " | ".join(_escape_cell(c) for c in r) + " |" for r in body)
    return "\n".join(lines)


def _escape_cell(value: str) -> str:
    # A pipe inside a cell would split the column.
    return value.replace("|", "\\|").replace("\n", " ")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def extract_text(filename: str, data: bytes) -> ExtractionResult:
    """Extract text from *data*, choosing the reader by *filename*'s extension.

    Raises :class:`ExtractionError` with a message meant for the user when the
    format is unsupported or the file cannot be parsed.
    """
    suffix = _suffix(filename)

    if suffix in IMAGE_EXTENSIONS:
        raise ExtractionError(
            f"{filename} is an image — send it to a vision model rather than "
            "extracting text from it."
        )

    if suffix == ".pdf":
        return _extract_pdf(data)
    if suffix == ".docx":
        return _extract_docx(data)
    if suffix in {".xlsx", ".xlsm"}:
        return _extract_xlsx(data)
    if suffix == ".csv":
        return _extract_delimited(data, ",")
    if suffix == ".tsv":
        return _extract_delimited(data, "\t")
    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return _extract_plain(data)

    # .doc and .xls are the old binary formats, and the common mistake.
    if suffix in {".doc", ".xls", ".ppt"}:
        raise ExtractionError(
            f"{filename} is in the old binary {suffix} format, which cannot be "
            f"read directly. Save it as {suffix}x and attach that instead."
        )

    raise ExtractionError(
        f"Nira cannot read {suffix or 'files without an extension'} yet. "
        "Supported: " + ", ".join(sorted(SUPPORTED_TEXT_EXTENSIONS | IMAGE_EXTENSIONS))
    )


def summarise_notes(results: List[ExtractionResult]) -> Optional[str]:
    """One line covering everything that was cut, or None if nothing was."""
    notes = [n for r in results for n in r.notes]
    return " ".join(notes) if notes else None
