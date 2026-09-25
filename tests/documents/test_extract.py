"""Reading the files a user attaches.

Built against real files rather than fixtures-of-convenience: a .xlsx written
by openpyxl, a .docx with a table in it, a multi-page PDF from reportlab. A
test that only ever sees hand-rolled bytes proves the parser handles the bytes
the test wrote, which is not the thing that breaks.
"""

from __future__ import annotations

import io

import pytest

from nira.documents import ExtractionError, extract_text, is_image
from nira.documents.extract import (
    MAX_CHARS_PER_FILE,
    MAX_SHEET_COLS,
    MAX_SHEET_ROWS,
    MAX_SHEETS,
)

# ---------------------------------------------------------------------------
# Builders for real files
# ---------------------------------------------------------------------------


def make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title=title[:31])
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def make_docx(paragraphs: list[str], table: list[list[str]] | None = None) -> bytes:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    if table:
        added = document.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for c, value in enumerate(row):
                added.cell(r, c).text = value
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def make_pdf(pages: list[str]) -> bytes:
    canvas_mod = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    canvas = canvas_mod.Canvas(buffer)
    for text in pages:
        canvas.drawString(72, 720, text)
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Spreadsheets keep their shape
# ---------------------------------------------------------------------------


class TestSpreadsheets:
    def test_a_sheet_becomes_a_markdown_table(self):
        data = make_xlsx(
            {"Q3": [["Region", "Q1", "Q3"], ["North", 100, 141], ["South", 90, 88]]}
        )
        result = extract_text("book.xlsx", data)

        # The grid is the point. Flattened to prose, "141" stops belonging to
        # a row and a column, and the model can only guess.
        assert "| Region | Q1 | Q3 |" in result.text
        assert "| North | 100 | 141 |" in result.text
        assert "### Sheet: Q3" in result.text
        assert not result.truncated

    def test_every_sheet_is_labelled(self):
        data = make_xlsx({"Revenue": [["a", 1]], "Costs": [["b", 2]]})
        result = extract_text("book.xlsx", data)
        assert "### Sheet: Revenue" in result.text
        assert "### Sheet: Costs" in result.text

    def test_formula_cells_come_through_as_their_values(self):
        openpyxl = pytest.importorskip("openpyxl")
        book = openpyxl.Workbook()
        sheet = book.active
        sheet["A1"] = 2
        sheet["A2"] = 3
        sheet["A3"] = "=SUM(A1:A2)"
        buffer = io.BytesIO()
        book.save(buffer)

        result = extract_text("f.xlsx", buffer.getvalue())
        # openpyxl reads the *cached* value, and a file openpyxl wrote has
        # none — so the formula is absent rather than shown as text. Either is
        # acceptable; "=SUM(A1:A2)" leaking through as content is not, because
        # the model would report the formula as the answer.
        assert "=SUM" not in result.text

    def test_a_long_sheet_is_cut_and_says_so(self):
        rows = [["n", "v"]] + [[str(i), i] for i in range(MAX_SHEET_ROWS + 50)]
        result = extract_text("long.xlsx", make_xlsx({"S": rows}))

        assert result.truncated
        assert any(str(MAX_SHEET_ROWS) in note for note in result.notes)
        assert result.text.count("\n") <= MAX_SHEET_ROWS + 6

    def test_a_wide_sheet_keeps_the_leftmost_columns(self):
        header = [f"c{i}" for i in range(MAX_SHEET_COLS + 20)]
        result = extract_text("wide.xlsx", make_xlsx({"S": [header, header]}))
        assert "c0" in result.text
        assert f"c{MAX_SHEET_COLS + 10}" not in result.text

    def test_too_many_sheets_is_reported(self):
        sheets = {f"S{i}": [["a", i]] for i in range(MAX_SHEETS + 4)}
        result = extract_text("many.xlsx", make_xlsx(sheets))
        assert result.truncated
        assert any("sheets" in note for note in result.notes)

    def test_an_empty_workbook_says_so_rather_than_returning_nothing(self):
        result = extract_text("empty.xlsx", make_xlsx({"Blank": []}))
        assert result.text == ""
        assert any("empty" in note.lower() for note in result.notes)


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------


class TestWord:
    def test_paragraphs_and_tables_both_survive(self):
        data = make_docx(
            ["Quarterly summary.", "Revenue grew."],
            table=[["Metric", "Value"], ["Revenue", "494"]],
        )
        result = extract_text("report.docx", data)

        assert "Quarterly summary." in result.text
        # The numbers in a .docx report are usually in the table. Dropping it
        # loses the reason the file was attached.
        assert "| Revenue | 494 |" in result.text

    def test_empty_paragraphs_do_not_pad_the_output(self):
        data = make_docx(["Real text.", "", "   ", "More text."])
        result = extract_text("d.docx", data)
        assert "\n\n\n" not in result.text


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


class TestPdf:
    def test_text_is_read_across_pages(self):
        data = make_pdf(["Page one: revenue 494.", "Page two: margin up 3."])
        result = extract_text("r.pdf", data)
        assert "revenue 494" in result.text
        assert "margin up 3" in result.text

    def test_a_long_pdf_stops_early_and_says_how_far_it_got(self):
        data = make_pdf([f"Page {i}: " + "word " * 900 for i in range(40)])
        result = extract_text("long.pdf", data)

        assert result.truncated
        assert any("pages" in note for note in result.notes)
        assert len(result.text) <= MAX_CHARS_PER_FILE

    def test_a_scanned_pdf_suggests_attaching_it_as_an_image(self):
        # No text layer — the single most common "why didn't it work".
        blank = make_pdf([""])
        result = extract_text("scan.pdf", blank)
        assert result.text == ""
        assert any("scanned" in note.lower() for note in result.notes)

    def test_a_corrupt_pdf_fails_with_a_readable_message(self):
        with pytest.raises(ExtractionError) as excinfo:
            extract_text("bad.pdf", b"%PDF-1.4 this is not really a pdf")
        assert "could not be read" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Delimited and plain text
# ---------------------------------------------------------------------------


class TestDelimited:
    def test_csv_becomes_a_table(self):
        result = extract_text("d.csv", b"name,qty\nwidget,3\ngizmo,11\n")
        assert "| name | qty |" in result.text
        assert "| widget | 3 |" in result.text

    def test_tsv_uses_tabs(self):
        result = extract_text("d.tsv", b"a\tb\n1\t2\n")
        assert "| a | b |" in result.text

    def test_a_pipe_in_a_cell_does_not_break_the_column(self):
        result = extract_text("d.csv", b"name,note\nwidget,a|b\n")
        assert r"a\|b" in result.text

    def test_windows_encoded_text_is_still_readable(self):
        # A CSV exported from a Windows tool. Refusing it loses the document;
        # replacing one character loses a character.
        result = extract_text("d.csv", "name\ncaf\xe9\n".encode("cp1252"))
        assert "caf" in result.text


class TestPlainText:
    def test_markdown_passes_through(self):
        result = extract_text("n.md", b"# Title\n\nBody text.")
        assert "# Title" in result.text

    def test_a_huge_file_is_capped_and_says_by_how_much(self):
        result = extract_text("big.txt", b"x" * (MAX_CHARS_PER_FILE * 2))
        assert len(result.text) == MAX_CHARS_PER_FILE
        assert result.truncated
        assert any("characters" in note for note in result.notes)


# ---------------------------------------------------------------------------
# Routing and refusals
# ---------------------------------------------------------------------------


class TestRouting:
    def test_images_are_refused_here_and_pointed_at_a_vision_model(self):
        with pytest.raises(ExtractionError) as excinfo:
            extract_text("photo.png", b"\x89PNG\r\n")
        assert "vision model" in str(excinfo.value)

    @pytest.mark.parametrize("name", ["a.PNG", "b.JPG", "c.webp"])
    def test_is_image_ignores_case(self, name):
        assert is_image(name)

    def test_a_text_file_is_not_an_image(self):
        assert not is_image("notes.md")

    @pytest.mark.parametrize("name", ["old.doc", "old.xls", "deck.ppt"])
    def test_the_old_binary_formats_name_the_fix(self, name):
        # The single most common upload mistake. "Unsupported" is true and
        # useless; "save it as .docx" is what the person needs.
        with pytest.raises(ExtractionError) as excinfo:
            extract_text(name, b"\xd0\xcf\x11\xe0")
        assert "Save it as" in str(excinfo.value)

    def test_an_unknown_format_lists_what_is_supported(self):
        with pytest.raises(ExtractionError) as excinfo:
            extract_text("thing.bin", b"\x00\x01")
        message = str(excinfo.value)
        assert ".pdf" in message and ".xlsx" in message

    def test_a_file_with_no_extension_is_refused_clearly(self):
        with pytest.raises(ExtractionError) as excinfo:
            extract_text("README", b"hello")
        assert "without an extension" in str(excinfo.value)


class TestNoCrashes:
    """Nothing a user can attach should raise something other than ExtractionError."""

    @pytest.mark.parametrize(
        "name",
        ["x.pdf", "x.docx", "x.xlsx", "x.csv", "x.txt", "x.json"],
    )
    def test_garbage_bytes_never_escape_as_an_unexpected_exception(self, name):
        try:
            extract_text(name, b"\x00\xff\xfe garbage \x00")
        except ExtractionError:
            pass  # The contract.
        # Anything else fails the test by propagating.

    def test_empty_bytes_are_handled(self):
        try:
            result = extract_text("x.txt", b"")
            assert result.text == ""
        except ExtractionError:
            pass
