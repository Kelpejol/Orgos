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
