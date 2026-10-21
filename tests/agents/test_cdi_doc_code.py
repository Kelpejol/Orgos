# =============================================================================
# tests/agents/test_cdi_doc_code.py
#
# CDI-01 must not flag a combined policy-and-procedure document as having no
# control number. Regression for: the "Nonconformity and Corrective Action"
# document was reported as "no control number" because
#   1. the code-search pattern couldn't FIND a compound POL-PRO code in the
#      body, so intake stored DocumentCode = "", and
#   2. CDI-01 then reported "No document code provided".
#
# That was fixed once already (2026-09), but against the WRONG assumed shape:
# DRG-QI-POL-PRO-NCA-01-26 (with a trailing year). The real document in the
# ORGOS LIBRARY carries DRG-QI-POL-PRO-NCA-01 — a single trailing serial, no
# year — which the first fix did not match, so the bug was still live.
#
# Separately, CDI v06 (§4.0 Coding) retired the trailing "-SERIAL-YEAR" suffix
# entirely for NEW documents (DRG-QI-PRO-CDI, not DRG-QI-PRO-CDI-01-26). The
# compliance officer confirmed (2026-09) that legacy-suffixed codes must keep
# validating too, indefinitely — Wani (Victoria Shobayo) is converting the
# ~112 legacy-format documents herself with no fixed cutover date. So
# is_valid_doc_code() must accept every shape below, permanently, side by side.
# =============================================================================

from agents.cdi_checker.service import (
    check_01_document_code,
    find_doc_code_in_text,
    is_combined_document,
    is_valid_doc_code,
)

# The exact text/shape of the real, currently-live document that triggered
# the original bug report — no year suffix.
REAL_COMBINED_TEXT = (
    "Nonconformity and Corrective Action Policy and Procedure\n"
    "Document Code: DRG-QI-POL-PRO-NCA-01\n"
    "Purpose: this document establishes ...\n"
)

# The shape the first (incomplete) fix was tested against — kept as a
# still-valid legacy shape, since old documents may carry either.
LEGACY_COMBINED_WITH_YEAR_TEXT = (
    "Nonconformity and Corrective Action Policy and Procedure\n"
    "Document Code: DRG-QI-POL-PRO-NCA-01-26\n"
    "Purpose: this document establishes ...\n"
)


# ── code validity — new (v06) canonical format, no suffix ───────────────────

def test_new_canonical_code_is_valid():
    assert is_valid_doc_code("DRG-QI-PRO-CDI")


def test_new_canonical_combined_code_is_valid():
    assert is_valid_doc_code("DRG-QI-POL-PRO-NCA")


# ── code validity — legacy formats (accepted indefinitely, no cutover date) ──

def test_legacy_standard_code_is_valid():
    assert is_valid_doc_code("DRG-ISMS-POL-ACP-01-26")


def test_legacy_combined_with_year_is_valid():
    assert is_valid_doc_code("DRG-QI-POL-PRO-NCA-01-26")


def test_legacy_combined_single_serial_is_valid():
    """The REAL shape of the document from the original bug report."""
    assert is_valid_doc_code("DRG-QI-POL-PRO-NCA-01")


def test_legacy_no_mnemonic_code_is_valid():
    """e.g. Client Engagement SOP — DRG-CLE-SOP-01-25, no separate short code."""
    assert is_valid_doc_code("DRG-CLE-SOP-01-25")


# ── code validity — rejections ───────────────────────────────────────────────

def test_malformed_code_still_invalid():
    assert not is_valid_doc_code("DRG-BAD")
    assert not is_valid_doc_code("")


def test_incomplete_code_is_invalid():
    """Dept + type only, no ID — not a real code under either standard."""
    assert not is_valid_doc_code("DRG-QI-PRO")


def test_code_without_drg_prefix_is_invalid():
    assert not is_valid_doc_code("NOT-A-CODE")


# ── finding the code inside the document body ────────────────────────────────

def test_real_combined_code_is_found_in_document_text():
    assert find_doc_code_in_text(REAL_COMBINED_TEXT) == "DRG-QI-POL-PRO-NCA-01"


def test_legacy_combined_with_year_is_found_in_document_text():
    assert find_doc_code_in_text(LEGACY_COMBINED_WITH_YEAR_TEXT) == "DRG-QI-POL-PRO-NCA-01-26"


def test_new_canonical_code_is_found_in_document_text():
    assert find_doc_code_in_text("Document Code: DRG-QI-PRO-CDI\nPurpose:") == "DRG-QI-PRO-CDI"


def test_standard_code_is_found_in_document_text():
    assert find_doc_code_in_text("Code: DRG-ISMS-POL-ACP-01-26") == "DRG-ISMS-POL-ACP-01-26"


def test_no_code_in_text_returns_empty():
    assert find_doc_code_in_text("A document with no controlled code at all") == ""


def test_first_valid_code_is_returned_when_two_are_present():
    text = "This document (DRG-QI-PRO-CDI) replaces DRG-QI-PRO-CM-01-26."
    assert find_doc_code_in_text(text) == "DRG-QI-PRO-CDI"


# ── CDI-01 behaviour ─────────────────────────────────────────────────────────

def test_combined_document_passes_when_code_recorded():
    assert check_01_document_code(REAL_COMBINED_TEXT, "DRG-QI-POL-PRO-NCA-01")["result"] == "PASS"


def test_combined_document_passes_when_code_only_in_body():
    """The reported bug: register field blank, code present in the document."""
    result = check_01_document_code(REAL_COMBINED_TEXT, "")
    assert result["result"] == "PASS"
    assert "read from the document body" in (result.get("note") or "")


def test_new_canonical_document_passes():
    result = check_01_document_code("Some body text", "DRG-QI-PRO-CDI")
    assert result["result"] == "PASS"


def test_genuinely_missing_code_still_fails():
    result = check_01_document_code("A policy with no code anywhere", "")
    assert result["result"] == "FAIL"
    assert "No document code" in result["finding"]


def test_genuinely_malformed_code_still_fails():
    assert check_01_document_code("A policy", "DRG-BAD")["result"] == "FAIL"


# ── combined-document detection ──────────────────────────────────────────────

def test_combined_detected_by_code_and_by_title():
    assert is_combined_document("", "DRG-QI-POL-PRO-NCA-01")
    assert is_combined_document("QMS Policies and Procedures Manual", "")
    assert not is_combined_document("An access control policy", "DRG-ISMS-POL-ACP-01-26")


# ── severity: advisory checks warn; date depends on a version being present ──
import asyncio
import io as _io
from docx import Document as _Doc


def _docx(*paras):
    d = _Doc()
    for t in paras:
        d.add_paragraph(t)
    b = _io.BytesIO(); d.save(b)
    return b.getvalue()


def _run(*paras):
    from agents.cdi_checker.service import run_cdi_check
    res = asyncio.run(run_cdi_check(_docx(*paras), "x.docx", "DRG-ISMS-PRO-CMIG"))
    return res, {c["check_id"]: c for c in res["checks"]}


def test_a_draft_is_not_asked_for_a_version_or_an_effective_date():
    # Approval numbers the version and stamps the dates on the CDT cover.
    res, c = _run("Change Management Procedure", "Body text.")
    assert c["CDI-15"]["result"] == "WARN" and c["CDI-14"]["result"] == "WARN"


def test_stating_a_version_does_not_make_the_effective_date_required():
    res, c = _run("Change Management Procedure", "Version: 1.0", "Body text.")
    assert c["CDI-15"]["result"] == "PASS"
    assert c["CDI-14"]["result"] == "WARN"


def test_a_draft_may_say_draft():
    from agents.cdi_checker.service import check_15_version_number
    assert check_15_version_number("Access Policy\nVersion: Draft\nBody.")["result"] == "PASS"


def test_advisory_checks_warn_and_dont_count_as_failures():
    res, c = _run("Change Management Procedure", "Body text.")
    for cid in ("CDI-02", "CDI-03", "CDI-04", "CDI-10", "CDI-11", "CDI-12"):
        assert c[cid]["result"] == "WARN", cid
    assert c["CDI-09"]["result"] == "FAIL"           # feeds the Standards Map
    assert res["fail_count"] == sum(1 for x in res["checks"] if x["result"] == "FAIL")
    assert res["warn_count"] >= 6


# ── CDI-15: a worded version field resolves to a one-click swap ──────────────
def test_wordy_version_becomes_a_located_swap():
    from agents.cdi_checker.service import check_15_version_number
    r = check_15_version_number("Access Policy\nVersion: TBC\nBody text.")
    assert r["result"] == "FAIL" and r["fixable"] == "auto"
    assert r["find"] == "Version: TBC" and r["replace"] == "Version: 1.0"


def test_version_in_prose_is_not_mistaken_for_the_field():
    from agents.cdi_checker.service import check_15_version_number
    r = check_15_version_number("Staff may read the draft version of the policy.")
    assert r["result"] == "FAIL" and r["fixable"] == "insert"   # nothing to swap


def test_every_failing_check_states_its_rule():
    res, c = _run("Change Management Procedure", "Body text.")
    flagged = [x for x in res["checks"] if x["result"] in ("FAIL", "WARN")]
    assert flagged and all(x["rule"] for x in flagged)
    assert "Draft" in c["CDI-15"]["rule"]


# ── a fix must satisfy the check it claims to fix ───────────────────────────
def test_version_words_are_refused_before_they_reach_the_document():
    from agents.cdi_checker.service import validate_fix_content
    for bad in ("Version: TBC", "Version: N/A"):
        ok, reason = validate_fix_content("CDI-15", bad)
        assert not ok and "CDI-15" in reason
    assert validate_fix_content("CDI-15", "Version: 1.0")[0]
    assert validate_fix_content("CDI-15", "Version: Draft")[0]


def test_a_date_that_is_not_a_date_is_refused():
    from agents.cdi_checker.service import validate_fix_content
    assert not validate_fix_content("CDI-14", "Effective Date: 18|10|2026")[0]
    assert validate_fix_content("CDI-14", "Effective Date: 18/10/2026")[0]


def test_a_section_is_validated_with_its_heading():
    from agents.cdi_checker.service import validate_fix_content
    assert validate_fix_content("CDI-03", "This procedure establishes X.", "Purpose")[0]
    assert not validate_fix_content("CDI-09", "nothing relevant", "Standards References")[0]


def test_language_checks_are_not_insert_validated():
    from agents.cdi_checker.service import validate_fix_content
    assert validate_fix_content("CDI-07", "anything at all")[0]


# ── CDI-06: the AI only locates aspirational wording; it can't invent it ─────
def test_an_ai_finding_naming_a_word_that_is_not_aspirational_is_dropped():
    from agents.cdi_checker.service import _ai_result_to_checks
    ai = {"cdi_06": {"findings": [
        {"word": "requirements", "anchor": "requirements for controlling records", "find": "x", "replace": "y"},
        {"word": "keep", "anchor": "keep the register", "find": "x", "replace": "y"},
        {"word": "do not change", "anchor": "do not change the master", "find": "x", "replace": "y"},
    ]}}
    assert [c["result"] for c in _ai_result_to_checks(ai) if c["check_id"] == "CDI-06"] == ["PASS"]


def test_a_real_aspirational_finding_is_kept_and_must_appear_in_its_quote():
    from agents.cdi_checker.service import _ai_result_to_checks
    real = {"word": "where possible", "anchor": "Staff should, where possible, log changes.",
            "find": "where possible", "replace": "always"}
    invented = {"word": "ideally", "anchor": "Staff shall log every change.", "find": "x", "replace": "y"}
    results = [c["result"] for c in _ai_result_to_checks({"cdi_06": {"findings": [real, invented]}})
               if c["check_id"] == "CDI-06"]
    assert results == ["FAIL"]                      # only the real one (a warning downstream)
