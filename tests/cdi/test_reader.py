# =============================================================================
# tests/cdi/test_reader.py — turning a file into paragraphs and tables
#
# The trap this exists for: python-docx drops text inside tracked changes
# without a word, so a control block row added as a tracked insertion came
# back empty. Documents under review are full of them.
# =============================================================================

import pytest

from cdi.reader import (
    Paragraph,
    Table,
    UnsupportedDocument,
    _join_lines,
    _running_lines,
    normalise_pdf_rows,
    read_document,
)
from tests.cdi.builders import DocBuilder


def read(builder):
    return read_document(builder.bytes(), "t.docx")


# ── Word ─────────────────────────────────────────────────────────────────────

def test_tracked_insertions_are_read_and_deletions_are_not():
    content = read(DocBuilder().para_with_changes("Owner: ", inserted="Head of IT", deleted="CTO"))
    assert content.blocks == [Paragraph("Owner: Head of IT")]
    assert (content.tracked_insertions, content.tracked_deletions) == (1, 1)


def test_a_table_row_added_as_a_tracked_change_is_not_lost():
    content = read(DocBuilder().table_row_inserted("Child Documents", "Records Procedure"))
    [table] = [b for b in content.blocks if isinstance(b, Table)]
    assert table.rows == (("Child Documents", "Records Procedure"),)


def test_blocks_keep_document_order_and_heading_styles():
    content = read(DocBuilder().heading("1.0 Purpose").table([["A", "B"]]).para("Text."))
    assert [type(b).__name__ for b in content.blocks] == ["Paragraph", "Table", "Paragraph"]
    assert content.blocks[0].is_heading_style


def test_table_of_contents_entries_are_not_content():
    b = DocBuilder()
    b.para("4.0 Business impact assessment (BCDR-01)\t3", style="toc 1")
    b.heading("4.0 Business impact assessment (BCDR-01)")
    texts = [x.text for x in read(b).blocks]
    assert texts == ["4.0 Business impact assessment (BCDR-01)"]


def test_unsupported_formats_say_what_to_do():
    with pytest.raises(UnsupportedDocument, match="docx"):
        read_document(b"", "old.doc")
    with pytest.raises(UnsupportedDocument):
        read_document(b"", "notes.txt")


# ── PDF tables ──────────────────────────────────────────────────────────────

def test_pdf_spacer_columns_are_dropped_and_split_headers_merged():
    raw = [
        ["Record", "Created by", "", "At", "", "Kept in", "Retention"],
        ["", "", "", "step", "", "", ""],
        ["REC-0675 Register", "Head of IT", "5.1", "", "", "Folder", "Annex C"],
    ]
    assert normalise_pdf_rows(raw) == (
        ("Record", "Created by", "At step", "Kept in", "Retention"),
        ("REC-0675 Register", "Head of IT", "5.1", "Folder", "Annex C"),
    )


def test_a_label_value_table_second_row_is_data_not_header():
    raw = [["", "Document Title", "", "Policy"], ["", "Document Code", "", "DRG-QI-POL-CDI"]]
    assert normalise_pdf_rows(raw) == (
        ("Document Title", "Policy"), ("Document Code", "DRG-QI-POL-CDI"))


# ── PDF paragraphs ──────────────────────────────────────────────────────────

def test_wrapped_lines_rejoin_and_numbered_clauses_start_new_paragraphs():
    lines = ["4.0 Business impact assessment (BCDR-01)",
             "4.1 The Head records each process in REC-",
             "0676: the downtime and the",
             "busiest periods.",
             "Risk statement (BCDR-01): A process could stay down."]
    assert _join_lines(lines) == [
        "4.0 Business impact assessment (BCDR-01)",
        "4.1 The Head records each process in REC-0676: the downtime and the busiest periods.",
        "Risk statement (BCDR-01): A process could stay down.",
    ]


def test_running_page_headers_are_recognised():
    pages = [["Title page"], ["Procedure Name", "4.1 text"], ["Procedure Name", "5.1 text"]]
    assert _running_lines(pages) == {"Procedure Name"}
