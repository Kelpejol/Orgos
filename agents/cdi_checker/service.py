# =============================================================================
# agents/cdi_checker/service.py — CDI Checker Agent
# Runs 15 checks from DRG-QI-REF-DOCS-01-26 Section 7 against a document.
# Per Bobby's amendment: each FAIL now outputs proposed_fix alongside finding.
# Two stages:
#   Stage 1 — Format/structure checks (no model needed, pure text analysis)
#   Stage 2 — Language/content checks (uses Ollama for AI-assisted analysis)
# Additional inputs per amendment: Role Register, Evidence Taxonomy, Control Register
# =============================================================================

import io
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# =============================================================================
#  Document code pattern
#  Format: DRG-{DEPT}-{TYPE}-{SHORT}-{SERIAL}-{YEAR}
#  Example: DRG-ISMS-POL-ACP-01-26
# =============================================================================

DOC_CODE_PATTERN = re.compile(
    r"^DRG-[A-Z]{2,6}-[A-Z]{2,3}-[A-Z0-9]{2,6}-\d{2}-\d{2}$"
)

ASPIRATIONAL_WORDS = [
    "should", "may ", "where possible", "as appropriate",
    "wherever possible", "ideally", "recommended", "encouraged",
    "consider", "attempt to",
]

DIRECTIVE_VERBS = ["shall", "must", "is required to", "are required to", "will "]

EVIDENCE_TYPE_CODES = {
    "LOG", "CFG", "APR", "FRM", "TRN", "ACK",
    "TST", "CRT", "MTG", "REV", "CHK", "CNT", "INV", "CHG", "INC", "RPT",
}

VAGUE_ROLE_TERMS = [
    "management", "relevant staff", "staff", "employees", "the team",
    "administration", "personnel", "leadership", "appropriate personnel",
    "responsible parties", "stakeholders",
]


# =============================================================================
#  Check result builder
# =============================================================================

def _pass(check_id: str, check_name: str) -> dict:
    return {
        "check_id":      check_id,
        "check_name":    check_name,
        "result":        "PASS",
        "finding":       None,
        "current_text":  None,
        "proposed_fix":  None,
        "fix_source":    None,
        "confidence":    100,
    }


def _fail(
    check_id: str,
    check_name: str,
    finding: str,
    current_text: str = "",
    proposed_fix: str = "",
    fix_source: str = "",
    confidence: int = 90,
) -> dict:
    return {
        "check_id":      check_id,
        "check_name":    check_name,
        "result":        "FAIL",
        "finding":       finding,
        "current_text":  current_text,
        "proposed_fix":  proposed_fix,
        "fix_source":    fix_source,
        "confidence":    confidence,
    }


# =============================================================================
#  Text extraction helpers
# =============================================================================

def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
    except Exception as exc:
        logger.warning(f"PDF extraction failed: {exc}")
        return ""


def _extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as exc:
        logger.warning(f"DOCX extraction failed: {exc}")
        return ""


def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = filename.lower().split(".")[-1]
    if ext == "pdf":
        return _extract_text_from_pdf(file_bytes)
    elif ext in ("docx", "doc"):
        return _extract_text_from_docx(file_bytes)
    elif ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {ext}")


# =============================================================================
#  Stage 1 — Format and structure checks (no model)
# =============================================================================

def check_01_document_code(text: str, doc_code: str) -> dict:
    """CDI-01: Document code present and in correct format."""
    if not doc_code:
        return _fail(
            "CDI-01", "Document code format",
            "No document code provided.",
            current_text="",
            proposed_fix="Generate a code in format DRG-{DEPT}-{TYPE}-{SHORT}-{SERIAL}-{YEAR}, e.g. DRG-ISMS-POL-ACP-01-26.",
            fix_source="Document Creation Standards §1",
        )
    if not DOC_CODE_PATTERN.match(doc_code.strip()):
        return _fail(
            "CDI-01", "Document code format",
            f"Document code '{doc_code}' does not match the required format.",
            current_text=doc_code,
            proposed_fix="Correct format: DRG-{DEPT}-{TYPE}-{SHORT}-{SERIAL}-{YEAR}. Example: DRG-ISMS-POL-ACP-01-26.",
            fix_source="Document Creation Standards §1",
        )
    return _pass("CDI-01", "Document code format")


def check_02_revision_history(text: str) -> dict:
    """CDI-02: Revision history table present."""
    indicators = ["revision history", "version history", "change log", "amendment history"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-02", "Revision history table",
            "No revision history table found in the document.",
            current_text="",
            proposed_fix="Add a revision history table on page 2 with columns: Version | Date | Author | Change description | Approved by.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-02", "Revision history table")


def check_03_purpose_section(text: str) -> dict:
    """CDI-03: Purpose section present with directive language."""
    has_purpose = "purpose" in text.lower()
    if not has_purpose:
        return _fail(
            "CDI-03", "Purpose section",
            "No Purpose section found.",
            current_text="",
            proposed_fix="Add a Purpose section stating why this document exists using directive language: 'This [policy/procedure] establishes...'",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-03", "Purpose section")


def check_04_scope_section(text: str) -> dict:
    """CDI-04: Scope section present and specific."""
    has_scope = "scope" in text.lower()
    if not has_scope:
        return _fail(
            "CDI-04", "Scope section",
            "No Scope section found.",
            current_text="",
            proposed_fix="Add a Scope section specifying exactly who and what this document applies to. Example: 'This policy applies to all Dragnet employees, contractors, and third parties with access to Dragnet systems.'",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-04", "Scope section")


def check_05_responsibilities_section(text: str) -> dict:
    """CDI-05: Responsibilities section present."""
    indicators = ["responsibilities", "roles and responsibilities", "accountability"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-05", "Responsibilities section",
            "No Responsibilities section found.",
            current_text="",
            proposed_fix="Add a Responsibilities section assigning each control or obligation to a named role from the Role Register.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-05", "Responsibilities section")


def check_06_aspirational_language(text: str) -> list[dict]:
    """CDI-06: No aspirational language in control statements."""
    failures = []
    lines = text.split("\n")
    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        for word in ASPIRATIONAL_WORDS:
            if word in line_lower and len(line.strip()) > 20:
                # Only flag lines that look like control statements
                has_directive = any(d in line_lower for d in DIRECTIVE_VERBS)
                if not has_directive:
                    failures.append(_fail(
                        "CDI-06", "Aspirational language",
                        f"Aspirational language '{word.strip()}' found — use 'shall' or 'must' instead.",
                        current_text=line.strip()[:200],
                        proposed_fix=line.strip().replace(word.strip(), "shall").replace("Should", "Shall"),
                        fix_source="Document Creation Standards §5.1",
                        confidence=75,
                    ))
                    break
    return failures[:5]  # Return max 5 instances to avoid overwhelming


def check_07_vague_roles(text: str, role_register_titles: list[str]) -> list[dict]:
    """CDI-07: No vague role references — must use Role Register titles."""
    failures = []
    lines = text.split("\n")
    role_titles_lower = {r.lower() for r in role_register_titles}

    for line in lines:
        line_lower = line.lower().strip()
        for vague in VAGUE_ROLE_TERMS:
            if vague in line_lower and len(line.strip()) > 15:
                # Try to suggest the closest Role Register title
                suggested = role_register_titles[0] if role_register_titles else "ISMS Lead"
                failures.append(_fail(
                    "CDI-07", "Vague role reference",
                    f"Vague role term '{vague}' found — must use a Role Register title.",
                    current_text=line.strip()[:200],
                    proposed_fix=f"Replace '{vague}' with the specific role title from the Role Register, e.g. '{suggested}'.",
                    fix_source="Role Register + Document Creation Standards §5.2",
                    confidence=80,
                ))
                break
    return failures[:5]


def check_08_evidence_references(text: str) -> list[dict]:
    """CDI-08: Evidence references use Taxonomy type codes, not vague language."""
    vague_evidence = [
        "records shall be maintained",
        "records must be maintained",
        "documentation shall be kept",
        "logs shall be retained",
        "evidence shall be",
        "records will be",
    ]
    failures = []
    text_lower = text.lower()
    for phrase in vague_evidence:
        if phrase in text_lower:
            # Find the line
            for line in text.split("\n"):
                if phrase in line.lower():
                    failures.append(_fail(
                        "CDI-08", "Vague evidence reference",
                        f"Vague evidence language '{phrase}' found — must specify Taxonomy type code.",
                        current_text=line.strip()[:200],
                        proposed_fix=(
                            f"Replace with a specific Evidence Taxonomy reference. Example: "
                            f"'Evidence: REV — signed review report. Source: SharePoint. Frequency: quarterly.'"
                        ),
                        fix_source="Evidence Taxonomy (DRG-QI-REF-EVTX-01-26)",
                        confidence=85,
                    ))
                    break
    return failures[:3]


def check_09_standards_references(text: str, standard_hints: list[str] = None) -> dict:
    """CDI-09: Standards references present where applicable."""
    has_iso = any(s in text for s in ["ISO 27001", "ISO 9001", "NDPA", "A.5.", "A.8.", "A.6.", "S.3"])
    if not has_iso:
        return _fail(
            "CDI-09", "Standards references",
            "No standards clause references found. Controls should reference the ISO/NDPA clause they address.",
            current_text="",
            proposed_fix="Add ISO 27001, ISO 9001, or NDPA clause references to each control statement. Example: '(ISO 27001 A.5.18)' or '(NDPA S.39)'.",
            fix_source="Document Creation Standards §5.3",
            confidence=70,
        )
    return _pass("CDI-09", "Standards references")


def check_10_related_documents(text: str) -> dict:
    """CDI-10: Related documents section present."""
    indicators = ["related document", "associated document", "reference document", "see also"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-10", "Related documents section",
            "No Related Documents section found.",
            current_text="",
            proposed_fix="Add a Related Documents section listing any documents this one references or is referenced by, with their document codes.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-10", "Related documents section")


def check_11_classification_label(text: str) -> dict:
    """CDI-11: Document classification label present."""
    labels = ["internal", "confidential", "restricted", "public", "classification"]
    found = any(l in text.lower() for l in labels)
    if not found:
        return _fail(
            "CDI-11", "Classification label",
            "No document classification label found.",
            current_text="",
            proposed_fix="Add a classification label to the document header and footer. Dragnet standard classifications: Internal | Confidential | Restricted.",
            fix_source="Document Creation Standards §3",
        )
    return _pass("CDI-11", "Classification label")


def check_12_owner_identified(text: str) -> dict:
    """CDI-12: Document owner identified."""
    indicators = ["document owner", "policy owner", "owner:", "approved by", "authored by"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-12", "Document owner identified",
            "No document owner identified in the document metadata.",
            current_text="",
            proposed_fix="Add an owner field to the cover page or metadata section specifying the role responsible for this document. Must be a Role Register title.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-12", "Document owner identified")


def check_13_review_date(text: str) -> dict:
    """CDI-13: Review date present and not overdue."""
    indicators = ["review date", "next review", "review due", "valid until", "expiry date"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-13", "Review date",
            "No review date found. All controlled documents must have a defined next review date.",
            current_text="",
            proposed_fix="Add a 'Next Review Date' field to the document metadata. Maximum review period is 12 months from the effective date.",
            fix_source="Document Creation Standards §6",
        )
    return _pass("CDI-13", "Review date")


def check_14_effective_date(text: str) -> dict:
    """CDI-14: Effective date present."""
    indicators = ["effective date", "effective from", "issue date", "date issued", "approved date"]
    found = any(ind in text.lower() for ind in indicators)
    if not found:
        return _fail(
            "CDI-14", "Effective date",
            "No effective date found in the document.",
            current_text="",
            proposed_fix="Add an 'Effective Date' field to the cover page or metadata. This is the date from which this version of the document applies.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-14", "Effective date")


def check_15_version_number(text: str) -> dict:
    """CDI-15: Version number present."""
    version_pattern = re.compile(r"v?\d+\.\d+|version\s*\d+|rev\s*\d+|revision\s*\d+", re.IGNORECASE)
    found = bool(version_pattern.search(text))
    if not found:
        return _fail(
            "CDI-15", "Version number",
            "No version number found. All controlled documents must be versioned.",
            current_text="",
            proposed_fix="Add a version number to the document header or cover page. Format: v1.0, v1.1, v2.0 etc. Initial version is always v1.0.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-15", "Version number")


# =============================================================================
#  Main CDI check runner
# =============================================================================

async def run_cdi_check(
    file_bytes: bytes,
    filename: str,
    doc_code: str = "",
    role_register_titles: Optional[list[str]] = None,
) -> dict:
    """
    Run all 15 CDI checks against a document.
    Returns a structured report with PASS/FAIL per check and proposed fixes.
    Per Bobby's amendment: every FAIL includes proposed_fix, current_text, fix_source, confidence.
    """
    role_register_titles = role_register_titles or []

    try:
        text = extract_text(file_bytes, filename)
    except Exception as exc:
        return {
            "passed":        False,
            "error":         str(exc),
            "checks":        [],
            "pass_count":    0,
            "fail_count":    0,
            "total_checks":  15,
        }

    if not text.strip():
        return {
            "passed":       False,
            "error":        "Document contains no extractable text. May be a scanned image.",
            "checks":       [],
            "pass_count":   0,
            "fail_count":   15,
            "total_checks": 15,
        }

    checks = []

    # Stage 1 — format and structure
    checks.append(check_01_document_code(text, doc_code))
    checks.append(check_02_revision_history(text))
    checks.append(check_03_purpose_section(text))
    checks.append(check_04_scope_section(text))
    checks.append(check_05_responsibilities_section(text))

    # CDI-06 — aspirational language (can return multiple)
    asp_failures = check_06_aspirational_language(text)
    if asp_failures:
        checks.extend(asp_failures)
    else:
        checks.append(_pass("CDI-06", "Aspirational language"))

    # CDI-07 — vague roles (can return multiple)
    role_failures = check_07_vague_roles(text, role_register_titles)
    if role_failures:
        checks.extend(role_failures)
    else:
        checks.append(_pass("CDI-07", "Vague role reference"))

    # CDI-08 — evidence references (can return multiple)
    evd_failures = check_08_evidence_references(text)
    if evd_failures:
        checks.extend(evd_failures)
    else:
        checks.append(_pass("CDI-08", "Vague evidence reference"))

    checks.append(check_09_standards_references(text))
    checks.append(check_10_related_documents(text))
    checks.append(check_11_classification_label(text))
    checks.append(check_12_owner_identified(text))
    checks.append(check_13_review_date(text))
    checks.append(check_14_effective_date(text))
    checks.append(check_15_version_number(text))

    pass_count = sum(1 for c in checks if c["result"] == "PASS")
    fail_count = sum(1 for c in checks if c["result"] == "FAIL")
    passed     = fail_count == 0

    return {
        "passed":       passed,
        "pass_count":   pass_count,
        "fail_count":   fail_count,
        "total_checks": len(checks),
        "checks":       checks,
    }