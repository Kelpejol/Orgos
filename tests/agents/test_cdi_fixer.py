# =============================================================================
# tests/agents/test_cdi_fixer.py
#
# The deterministic CDI fix engine. Covers the scenarios that matter for "the
# AI must never spoil the document": single/multi occurrence, run-split spans,
# not-found fail-safe, smart-quote/nbsp normalisation, headers, verify+rollback,
# and sequential multi-fix on one paragraph.
# =============================================================================

import io

from docx import Document

from agents.cdi_checker.fixer import apply_fixes, preview_locations, locate


def _build(paras, header=None):
    d = Document()
    if header:
        d.sections[0].header.paragraphs[0].add_run(header)
    for p in paras:
        para = d.add_paragraph()
        if isinstance(p, str):
            para.add_run(p)
        else:  # list of run strings -> deliberately run-split
            for seg in p:
                para.add_run(seg)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _text(b):
    d = Document(io.BytesIO(b))
    return "\n".join(p.text for p in d.paragraphs)


def _fix(find, replace, **kw):
    return {"fix_id": kw.get("fix_id", "1"), "check_id": kw.get("check_id", "CDI-06"),
            "find": find, "replace": replace, "occurrence_index": kw.get("occurrence_index")}


def test_single_run_swap():
    b = _build(["The team should endeavour to protect information assets."])
    nb, out = apply_fixes(b, [_fix("should endeavour to", "shall")])
    assert out[0].status == "applied"
    assert "shall protect information assets" in _text(nb)


def test_run_split_span():
    b = _build([["The team ", "should ", "endeavour", " to protect", " assets."]])
    nb, out = apply_fixes(b, [_fix("should endeavour to protect", "shall protect")])
    assert out[0].status == "applied"
    assert "shall protect assets" in _text(nb)


def test_ambiguous_is_guarded_then_resolved():
    b = _build(["Staff should log incidents.", "Managers should log incidents."])
    nb, out = apply_fixes(b, [_fix("should log", "shall log")])
    assert out[0].status == "skipped_ambiguous"
    assert _text(nb).count("should log") == 2  # untouched

    nb, out = apply_fixes(b, [_fix("should log", "shall log", occurrence_index=1)])
    assert out[0].status == "applied"
    t = _text(nb)
    assert "Staff should log" in t and "Managers shall log" in t


def test_not_found_is_failsafe():
    b = _build(["This sentence is completely different."])
    nb, out = apply_fixes(b, [_fix("should endeavour", "shall")])
    assert out[0].status == "skipped_not_found"
    assert _text(nb) == _text(b)  # document untouched


def test_smart_quote_and_nbsp_normalised():
    b = _build(["Records ‘should’ be kept where possible."])
    nb, out = apply_fixes(b, [_fix("'should' be kept where possible", "shall be retained")])
    assert out[0].status == "applied"
    assert "shall be retained" in _text(nb)


def test_header_text_is_reachable():
    b = _build(["Body."], header="Classification: draft where appropriate")
    nb, out = apply_fixes(b, [_fix("draft where appropriate", "Internal", check_id="CDI-11")])
    assert out[0].status == "applied"
    d = Document(io.BytesIO(nb))
    assert "Internal" in d.sections[0].header.paragraphs[0].text


def test_not_applicable_when_no_find():
    b = _build(["Body."])
    nb, out = apply_fixes(b, [_fix("", "anything", check_id="CDI-01")])
    assert out[0].status == "not_applicable"
    assert _text(nb) == _text(b)


def test_two_fixes_same_paragraph_sequential():
    b = _build(["Staff should log and should review incidents."])
    nb, out = apply_fixes(b, [
        _fix("should log", "shall log", fix_id="1"),
        _fix("should review", "shall review", fix_id="2"),
    ])
    assert [o.status for o in out] == ["applied", "applied"]
    assert _text(nb) == "Staff shall log and shall review incidents."


def test_preview_locations_reports_status():
    b = _build(["Staff should comply.", "More text should comply too."])
    res = preview_locations(b, [
        {"fix_id": "a", "find": "should comply"},
        {"fix_id": "b", "find": "does not exist"},
    ])
    assert res["a"].status == "ambiguous"
    assert res["b"].status == "not_found"


def test_locate_case_insensitive_fallback():
    b = _build(["The Team Should Endeavour to act."])
    d = Document(io.BytesIO(b))
    res = locate(d, "should endeavour")
    assert res.status == "located"


# ── amendments (replace + insert) ─────────────────────────────────────────────
from agents.cdi_checker.fixer import apply_amendments


def _texts(b):
    return [p.text for p in Document(io.BytesIO(b)).paragraphs]


def test_amend_insert_after():
    b = _build(["Purpose: sets the rules.", "Scope: applies to all staff."])
    nb, out = apply_amendments(b, [{"amend_id": "a1", "action": "insert_after",
        "find": "Scope: applies to all staff.", "text": "Exceptions need ISMS Lead approval."}])
    assert out[0].status == "applied"
    assert _texts(nb)[-1] == "Exceptions need ISMS Lead approval."


def test_amend_insert_before():
    b = _build(["Responsibilities", "All staff comply."])
    nb, out = apply_amendments(b, [{"amend_id": "a2", "action": "insert_before",
        "find": "All staff comply.", "text": "The DPO owns this section."}])
    assert out[0].status == "applied"
    assert _texts(nb)[1] == "The DPO owns this section."


def test_amend_replace_and_missing_anchor():
    b = _build(["The team should endeavour to review quarterly."])
    nb, out = apply_amendments(b, [{"amend_id": "a3", "action": "replace",
        "find": "should endeavour to review", "text": "shall review"}])
    assert out[0].status == "applied"
    assert "shall review quarterly" in _texts(nb)[0]

    nb, out = apply_amendments(b, [{"amend_id": "a4", "action": "insert_after",
        "find": "text that is not present", "text": "new line"}])
    assert out[0].status == "skipped_not_found"
    assert _texts(nb) == _texts(b)


# ── structural inserts (missing sections / lines / tables) ───────────────────
def _insert(heading, text, kind="section", position="end", fix_id="i1"):
    return {"fix_id": fix_id, "check_id": "CDI-03", "action": "insert",
            "insert": {"heading": heading, "text": text, "kind": kind, "position": position}}


def test_insert_section_before_first_heading():
    d = Document()
    d.add_paragraph("Change Management Procedure")
    d.add_paragraph("Definitions", style="Heading 1")
    d.add_paragraph("Some body.")
    b = io.BytesIO(); d.save(b)
    nb, out = apply_fixes(b.getvalue(), [_insert("Purpose", "This procedure establishes change control.",
                                                 position="before_first_heading")])
    assert out[0].status == "applied"
    t = _text(nb).splitlines()
    assert t.index("Purpose") < t.index("Definitions")


def test_insert_table_and_line():
    b = _build(["Body text."])
    nb, out = apply_fixes(b, [
        _insert("Revision History", "Version | Date\n1.0 | 01/01/2026", kind="table", fix_id="t"),
        {"fix_id": "l", "check_id": "CDI-15", "action": "insert",
         "insert": {"kind": "line", "position": "top", "text": "Version: 1.0"}},
    ])
    assert [o.status for o in out] == ["applied", "applied"]
    d = Document(io.BytesIO(nb))
    assert d.paragraphs[0].text == "Version: 1.0"
    assert d.tables[0].cell(1, 0).text == "1.0"


def test_insert_refuses_unfilled_placeholders():
    b = _build(["Body text."])
    nb, out = apply_fixes(b, [_insert("Scope", "Applies to [who and what].")])
    assert out[0].status == "needs_input"
    assert "Scope" not in _text(nb)


# ── preview: the fixed document, with changes marked ─────────────────────────
def test_preview_marks_only_changed_blocks():
    from agents.cdi_checker.fixer import document_preview
    b = _build(["Access Policy", "The team should endeavour to protect assets.", "Untouched line."])
    nb, out = apply_fixes(b, [_fix("should endeavour to", "shall")])
    blocks = document_preview(nb, out)
    texts = [x["text"] for x in blocks]
    assert "Untouched line." in texts
    changed = [x for x in blocks if x["changed"]]
    assert len(changed) == 1
    assert "shall protect assets" in changed[0]["text"]
    assert changed[0]["check_id"] == "CDI-06"


def test_preview_marks_inserted_section_and_table_rows():
    from agents.cdi_checker.fixer import document_preview
    b = _build(["Access Policy", "Body."])
    nb, out = apply_fixes(b, [
        _insert("Purpose", "This policy establishes access control.", fix_id="p"),
        _insert("Revision History", "Version | Date\n1.0 | 01/01/2026", kind="table", fix_id="t"),
    ])
    blocks = document_preview(nb, out)
    changed = [x["text"] for x in blocks if x["changed"]]
    assert "Purpose" in changed
    assert "This policy establishes access control." in changed
    assert any(t.startswith("1.0 | 01/01/2026") for t in changed)   # table row, readable
    assert "Body." in [x["text"] for x in blocks if not x["changed"]]


def test_preview_of_an_unfixed_document_marks_nothing():
    from agents.cdi_checker.fixer import document_preview
    blocks = document_preview(_build(["A", "B"]))
    assert blocks and not any(x["changed"] for x in blocks)
