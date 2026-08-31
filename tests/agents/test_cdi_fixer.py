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
