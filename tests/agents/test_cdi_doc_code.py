# =============================================================================
# tests/agents/test_cdi_doc_code.py
#
# CDI-01 must not flag a combined policy-and-procedure document as having no
# control number. Regression for: the "Nonconformity and Corrective Action"
# document was reported as "no control number" because
#   1. the code-search pattern couldn't FIND a compound POL-PRO code in the
#      body, so intake stored DocumentCode = "", and
#   2. CDI-01 then reported "No document code provided".
# =============================================================================

from agents.cdi_checker.service import (
    check_01_document_code,
    find_doc_code_in_text,
    is_combined_document,
    is_valid_doc_code,
)

COMBINED_TEXT = (
    "Nonconformity and Corrective Action Policy and Procedure\n"
    "Document Code: DRG-QI-POL-PRO-NCA-01-26\n"
    "Purpose: this document establishes ...\n"
)


# ── code validity ────────────────────────────────────────────────────────────

def test_combined_compound_code_is_valid():
    assert is_valid_doc_code("DRG-QI-POL-PRO-NCA-01-26")


def test_standard_code_still_valid():
    assert is_valid_doc_code("DRG-ISMS-POL-ACP-01-26")


def test_malformed_code_still_invalid():
    assert not is_valid_doc_code("DRG-BAD")
    assert not is_valid_doc_code("")


# ── finding the code inside the document body ────────────────────────────────

def test_compound_code_is_found_in_document_text():
    assert find_doc_code_in_text(COMBINED_TEXT) == "DRG-QI-POL-PRO-NCA-01-26"


def test_standard_code_is_found_in_document_text():
    assert find_doc_code_in_text("Code: DRG-ISMS-POL-ACP-01-26") == "DRG-ISMS-POL-ACP-01-26"


def test_no_code_in_text_returns_empty():
    assert find_doc_code_in_text("A document with no controlled code at all") == ""


# ── CDI-01 behaviour ─────────────────────────────────────────────────────────

def test_combined_document_passes_when_code_recorded():
    assert check_01_document_code(COMBINED_TEXT, "DRG-QI-POL-PRO-NCA-01-26")["result"] == "PASS"


def test_combined_document_passes_when_code_only_in_body():
    """The reported bug: register field blank, code present in the document."""
    result = check_01_document_code(COMBINED_TEXT, "")
    assert result["result"] == "PASS"
    assert "read from the document body" in (result.get("note") or "")


def test_genuinely_missing_code_still_fails():
    result = check_01_document_code("A policy with no code anywhere", "")
    assert result["result"] == "FAIL"
    assert "No document code" in result["finding"]


def test_genuinely_malformed_code_still_fails():
    assert check_01_document_code("A policy", "DRG-BAD")["result"] == "FAIL"


# ── combined-document detection ──────────────────────────────────────────────

def test_combined_detected_by_code_and_by_title():
    assert is_combined_document("", "DRG-QI-POL-PRO-NCA-01-26")
    assert is_combined_document("QMS Policies and Procedures Manual", "")
    assert not is_combined_document("An access control policy", "DRG-ISMS-POL-ACP-01-26")
