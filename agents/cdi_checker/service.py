# =============================================================================
# agents/cdi_checker/service.py — CDI Checker Agent
# Runs 16 checks from DRG-QI-REF-DOCS-01-26 Section 7 against a document.
#
# Architecture — hybrid deterministic + AI:
#
#   Stage 1  CDI-01..05, 09..15  (12 checks)
#            Pure rules/regex — presence of required sections, code format,
#            version number, dates, classification. Fast, 100% reproducible.
#            AI adds zero benefit here; do not change these to AI.
#
#   Stage 2  CDI-06, 07, 08, 16  (4 checks)
#            Language quality — requires semantic understanding to avoid false
#            positives ("management system" ≠ vague role, "may be granted" ≠
#            aspirational, etc.).  Single consolidated Ollama call using
#            qwen2.5:7b at temperature=0.  If Ollama is unavailable the check
#            falls back to improved regex patterns — no hard dependency.
#
# Per Bobby's amendment: every FAIL includes proposed_fix, current_text,
# fix_source, and confidence.
# =============================================================================

import io
import json
import logging
import re
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

# =============================================================================
#  Constants
# =============================================================================

DOC_CODE_PATTERN = re.compile(
    r"^DRG-[A-Z]{2,6}-[A-Z]{2,3}-[A-Z0-9]{2,6}-\d{2}-\d{2}$"
)

EVIDENCE_TYPE_CODES = {
    "LOG", "CFG", "APR", "FRM", "TRN", "ACK",
    "TST", "CRT", "MTG", "REV", "CHK", "CNT", "INV", "CHG", "INC", "RPT",
}

# Maximum document text sent to Ollama (chars).
# ~20 000 chars ≈ 5 000 words — covers any realistic policy document.
_AI_MAX_TEXT_CHARS = 20_000

# =============================================================================
#  Fallback pattern infrastructure (used when Ollama is unavailable)
# =============================================================================

# -- CDI-06 fallback ----------------------------------------------------------

_ASPIRATIONAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\bshould\b',              re.IGNORECASE), "shall"),
    (re.compile(r'\bwhere\s+possible\b',    re.IGNORECASE), "shall"),
    (re.compile(r'\bas\s+appropriate\b',    re.IGNORECASE), "shall"),
    (re.compile(r'\bwherever\s+possible\b', re.IGNORECASE), "shall"),
    (re.compile(r'\bideally\b',             re.IGNORECASE), "shall"),
    (re.compile(r'\bencouraged\s+to\b',     re.IGNORECASE), "shall"),
    (re.compile(r'\bconsider\b',            re.IGNORECASE), "shall"),
    (re.compile(r'\battempt\s+to\b',        re.IGNORECASE), "shall"),
    (re.compile(r'\bif\s+possible\b',       re.IGNORECASE), "shall"),
    (re.compile(r'\bwhere\s+applicable\b',  re.IGNORECASE), "shall"),
    (re.compile(r'\bwhere\s+practicable\b', re.IGNORECASE), "shall"),
]

_DIRECTIVE_RE = re.compile(
    r'\b(?:shall|must|is\s+required\s+to|are\s+required\s+to|'
    r'will\s+ensure|must\s+ensure|shall\s+ensure|'
    r'is\s+accountable|are\s+accountable)\b',
    re.IGNORECASE,
)

# -- CDI-07 fallback ----------------------------------------------------------

_MANAGEMENT_COMPOUND_RE = re.compile(
    r'\bmanagement\s+(?:system|framework|process|plan|approach|review|'
    r'function|practice|standard|procedure|tool|platform|policy|control|'
    r'committee|mechanism|structure|strategy|board|team|model|body|office)\b',
    re.IGNORECASE,
)

_OBLIGATION_LINE_RE = re.compile(
    r'\b(?:shall|must|is\s+responsible\s+for|are\s+responsible\s+for|'
    r'is\s+required\s+to|are\s+required\s+to|must\s+ensure|shall\s+ensure|'
    r'will\s+ensure|is\s+accountable|are\s+accountable)\b',
    re.IGNORECASE,
)

_VAGUE_ROLE_PATTERNS: dict[str, re.Pattern] = {
    "management":            re.compile(r'\bmanagement\b',            re.IGNORECASE),
    "staff":                 re.compile(r'\bstaff\b',                 re.IGNORECASE),
    "employees":             re.compile(r'\bemployees?\b',            re.IGNORECASE),
    "personnel":             re.compile(r'\bpersonnel\b',             re.IGNORECASE),
    "the team":              re.compile(r'\bthe\s+team\b',            re.IGNORECASE),
    "administration":        re.compile(r'\badministration\b',        re.IGNORECASE),
    "leadership":            re.compile(r'\bleadership\b',            re.IGNORECASE),
    "responsible parties":   re.compile(r'\bresponsible\s+parties\b', re.IGNORECASE),
    "relevant staff":        re.compile(r'\brelevant\s+staff\b',      re.IGNORECASE),
    "appropriate personnel": re.compile(r'\bappropriate\s+personnel\b', re.IGNORECASE),
    "stakeholders":          re.compile(r'\bstakeholders?\b',         re.IGNORECASE),
}

# -- CDI-08 fallback ----------------------------------------------------------

_VAGUE_EVIDENCE_RES: list[re.Pattern] = [
    re.compile(
        r'\b(?:records?|documentation?|logs?|evidence|audit\s+trails?)\s+'
        r'(?:shall|must|will|should|are\s+to)\s+(?:be\s+)?'
        r'(?:maintained?|kept|retained?|stored?|filed?|archived?|preserved?)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:shall|must|will)\s+(?:maintain|keep|retain|store|preserve|archive)\s+'
        r'(?:all\s+|relevant\s+|appropriate\s+)?'
        r'(?:records?|documentation?|logs?|evidence|files?)\b',
        re.IGNORECASE,
    ),
    re.compile(
        r'\b(?:records?|evidence|documentation?)\s+(?:are\s+to\s+be|will\s+be|must\s+be)\s+'
        r'(?:maintained?|kept|retained?|stored?|filed?)\b',
        re.IGNORECASE,
    ),
]

# -- CDI-16 fallback ----------------------------------------------------------

_ROLE_SUBJECT_RE = re.compile(
    r'\bthe\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\s+(?:shall|must)\b'
)

_NON_ROLE_SUBJECTS = {
    "document", "policy", "procedure", "process", "system",
    "organization", "company", "committee", "board",
}


# =============================================================================
#  Check result builders
# =============================================================================

def _pass(check_id: str, check_name: str) -> dict:
    return {
        "check_id":     check_id,
        "check_name":   check_name,
        "result":       "PASS",
        "finding":      None,
        "current_text": None,
        "proposed_fix": None,
        "fix_source":   None,
        "confidence":   100,
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
        "check_id":     check_id,
        "check_name":   check_name,
        "result":       "FAIL",
        "finding":      finding,
        "current_text": current_text,
        "proposed_fix": proposed_fix,
        "fix_source":   fix_source,
        "confidence":   confidence,
    }


# =============================================================================
#  Text extraction
# =============================================================================

def _extract_text_from_pdf(file_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        logger.warning(f"PDF extraction failed: {exc}")
        return ""


def _extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extract text from a .docx file using mammoth.
    mammoth extracts clean, structured text and handles table content, headers,
    footers, and unusual DOCX variants more robustly than python-docx.
    python-docx is kept only for document GENERATION (Policy Drafter).
    """
    try:
        import mammoth
        result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
        # result.messages contains any warnings — log them at debug level
        for msg in result.messages:
            logger.debug(f"mammoth: {msg}")
        return result.value or ""
    except Exception as exc:
        logger.warning(f"DOCX extraction failed: {exc}")
        return ""


def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Extract plain text from a document for CDI checking.

    .doc vs .docx detection: python-docx only handles .docx (ZIP/Open XML).
    Genuine .doc files are OLE2 binary and make python-docx raise BadZipFile,
    which previously caused a silent empty-string return → false "Error" status.
    We distinguish them by magic bytes:
      .docx / any OOXML  → starts with PK\\x03\\x04 (it is a ZIP file)
      .doc OLE2 binary   → starts with \\xD0\\xCF\\x11\\xE0
    """
    ext = filename.lower().rsplit(".", 1)[-1]

    if ext == "pdf":
        return _extract_text_from_pdf(file_bytes)

    if ext == "docx":
        return _extract_text_from_docx(file_bytes)

    if ext == "doc":
        # A .doc saved by modern Word is often actually OOXML — check magic bytes
        if file_bytes[:2] == b"PK":
            return _extract_text_from_docx(file_bytes)
        # Genuine OLE2 binary .doc — python-docx cannot read this
        raise ValueError(
            "This is an old .doc file. Open it in Word, save as .docx, then re-upload."
        )

    if ext == "txt":
        return file_bytes.decode("utf-8", errors="replace")

    raise ValueError(
        f"'.{ext}' files are not supported. Upload a .docx, .pdf, or .txt file."
    )


# =============================================================================
#  Stage 1 — Deterministic structural checks (CDI-01..05, 09..15)
#  These are correct as rules-based checks. Do not convert to AI.
# =============================================================================

def check_01_document_code(text: str, doc_code: str) -> dict:
    """CDI-01: Document code present and in correct format."""
    if not doc_code:
        return _fail(
            "CDI-01", "Document code format",
            "No document code provided.",
            proposed_fix="Generate a code: DRG-{DEPT}-{TYPE}-{SHORT}-{SERIAL}-{YEAR}. E.g. DRG-ISMS-POL-ACP-01-26.",
            fix_source="Document Creation Standards §1",
        )
    if not DOC_CODE_PATTERN.match(doc_code.strip()):
        return _fail(
            "CDI-01", "Document code format",
            f"Document code '{doc_code}' does not match the required format.",
            current_text=doc_code,
            proposed_fix="Correct format: DRG-{DEPT}-{TYPE}-{SHORT}-{SERIAL}-{YEAR}. E.g. DRG-ISMS-POL-ACP-01-26.",
            fix_source="Document Creation Standards §1",
        )
    return _pass("CDI-01", "Document code format")


def check_02_revision_history(text: str) -> dict:
    """CDI-02: Revision history table present."""
    indicators = ["revision history", "version history", "change log", "amendment history"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-02", "Revision history table",
            "No revision history table found.",
            proposed_fix="Add a revision history table: Version | Date | Author | Change | Approved by.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-02", "Revision history table")


def check_03_purpose_section(text: str) -> dict:
    """CDI-03: Purpose section present."""
    if "purpose" not in text.lower():
        return _fail(
            "CDI-03", "Purpose section",
            "No Purpose section found.",
            proposed_fix="Add a Purpose section: 'This [policy/procedure] establishes...'",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-03", "Purpose section")


def check_04_scope_section(text: str) -> dict:
    """CDI-04: Scope section present."""
    if "scope" not in text.lower():
        return _fail(
            "CDI-04", "Scope section",
            "No Scope section found.",
            proposed_fix="Add a Scope section specifying who and what this document applies to.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-04", "Scope section")


def check_05_responsibilities_section(text: str) -> dict:
    """CDI-05: Responsibilities section present."""
    indicators = ["responsibilities", "roles and responsibilities", "accountability"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-05", "Responsibilities section",
            "No Responsibilities section found.",
            proposed_fix="Add a Responsibilities section assigning each control to a named Role Register title.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-05", "Responsibilities section")


def check_09_standards_references(text: str) -> dict:
    """CDI-09: Standards references present."""
    markers = ["ISO 27001", "ISO 9001", "NDPA", "A.5.", "A.8.", "A.6.", "A.9.", "S.3", "S.39"]
    if not any(m in text for m in markers):
        return _fail(
            "CDI-09", "Standards references",
            "No standards clause references found.",
            proposed_fix="Add ISO 27001, ISO 9001, or NDPA clause references. E.g. '(ISO 27001 A.5.18)' or '(NDPA S.39)'.",
            fix_source="Document Creation Standards §5.3",
            confidence=70,
        )
    return _pass("CDI-09", "Standards references")


def check_10_related_documents(text: str) -> dict:
    """CDI-10: Related documents section present."""
    indicators = ["related document", "associated document", "reference document", "see also"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-10", "Related documents section",
            "No Related Documents section found.",
            proposed_fix="Add a Related Documents section listing referenced documents with their codes.",
            fix_source="Document Creation Standards §2",
        )
    return _pass("CDI-10", "Related documents section")


def check_11_classification_label(text: str) -> dict:
    """CDI-11: Document classification label present."""
    labels = ["internal", "confidential", "restricted", "public", "classification"]
    if not any(l in text.lower() for l in labels):
        return _fail(
            "CDI-11", "Classification label",
            "No document classification label found.",
            proposed_fix="Add a classification label to the header/footer. Options: Internal | Confidential | Restricted.",
            fix_source="Document Creation Standards §3",
        )
    return _pass("CDI-11", "Classification label")


def check_12_owner_identified(text: str) -> dict:
    """CDI-12: Document owner identified."""
    indicators = ["document owner", "policy owner", "owner:", "approved by", "authored by"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-12", "Document owner identified",
            "No document owner identified in the document metadata.",
            proposed_fix="Add an owner field to the cover page specifying the role responsible. Must be a Role Register title.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-12", "Document owner identified")


def check_13_review_date(text: str) -> dict:
    """CDI-13: Review date present."""
    indicators = ["review date", "next review", "review due", "valid until", "expiry date"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-13", "Review date",
            "No review date found. All controlled documents must have a next review date.",
            proposed_fix="Add 'Next Review Date' to the document metadata. Maximum review period is 12 months.",
            fix_source="Document Creation Standards §6",
        )
    return _pass("CDI-13", "Review date")


def check_14_effective_date(text: str) -> dict:
    """CDI-14: Effective date present."""
    indicators = ["effective date", "effective from", "issue date", "date issued", "approved date"]
    if not any(ind in text.lower() for ind in indicators):
        return _fail(
            "CDI-14", "Effective date",
            "No effective date found.",
            proposed_fix="Add an 'Effective Date' to the cover page — the date from which this version applies.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-14", "Effective date")


def check_15_version_number(text: str) -> dict:
    """CDI-15: Version number present."""
    pattern = re.compile(r"v?\d+\.\d+|version\s*\d+|rev\s*\d+|revision\s*\d+", re.IGNORECASE)
    if not pattern.search(text):
        return _fail(
            "CDI-15", "Version number",
            "No version number found.",
            proposed_fix="Add a version number to the cover page or header. Format: v1.0, v1.1, v2.0. Initial draft is always v1.0.",
            fix_source="Document Creation Standards §4",
        )
    return _pass("CDI-15", "Version number")


# =============================================================================
#  Stage 2 — AI language quality checks (CDI-06, 07, 08, 16)
#
#  Primary: single Ollama call (qwen2.5:7b, temperature=0, format=json).
#  The model understands context — it distinguishes "management system" from
#  "management shall", "may be granted" (permission) from "may consider"
#  (aspirational), etc.
#
#  Fallback: improved regex patterns used when Ollama is unavailable.
# =============================================================================

def _build_ai_prompt(text: str, role_register_titles: list[str]) -> str:
    roles_section = (
        "\n".join(f"  - {r}" for r in role_register_titles)
        if role_register_titles
        else "  (Role Register is empty — skip CDI-16)"
    )
    # Truncate long documents for the AI call
    text_for_ai = (
        text[:_AI_MAX_TEXT_CHARS] + "\n\n[... document truncated for length ...]"
        if len(text) > _AI_MAX_TEXT_CHARS
        else text
    )
    return f"""You are a CDI (Controlled Document Interface) compliance checker for Dragnet Solutions Limited.
Analyse the document text and identify violations of four quality rules.
Be PRECISE — only flag genuine violations. False positives damage trust in this tool.
Return ONLY valid JSON, nothing else.

ROLE REGISTER — the only permitted role titles for obligation statements:
{roles_section}

=== RULE CDI-06: ASPIRATIONAL LANGUAGE ===
Obligation statements must use directive language.

DIRECTIVE (correct): shall, must, is required to, are required to, will ensure, must ensure
ASPIRATIONAL (violation): should, where possible, as appropriate, wherever possible,
ideally, encouraged to, if possible, where applicable, where practicable, attempt to

Flag a line ONLY when ALL of these are true:
1. It is a normative obligation/control statement (assigns a duty to someone)
2. It contains aspirational language
3. It does NOT already contain a directive verb (shall/must/is required to) on the same line

Do NOT flag:
- Explanatory text, background context, introductory paragraphs
- Scope statements ("This policy applies to...")
- Definitions or glossary entries
- "may" used to express PERMISSION ("access may be granted upon approval" = IS PERMITTED — correct)
- "may" used to express RESTRICTION ("data may only be processed when..." = a control — correct)
- Flag "may" only when it expresses optionality or uncertainty ("controls may be reviewed" = aspirational)

=== RULE CDI-07: VAGUE ROLE REFERENCES ===
Obligation statements must name a specific role from the Role Register, not a generic group.

VAGUE (violation when used as the subject of an obligation):
management, staff, employees, personnel, the team, administration,
leadership, stakeholders, responsible parties, all users, relevant staff

CRITICAL EXCEPTIONS — these are framework/system nouns, NOT role references. Do NOT flag them:
"management system", "management framework", "management process", "management plan",
"risk management", "change management", "information security management",
"quality management", "security management", "incident management",
"configuration management", "key management", "identity management",
any phrase where the vague word modifies a noun rather than performing an obligation

Flag ONLY when the vague term IS the grammatical subject performing an obligation:
  BAD: "Management shall ensure...", "Staff must complete...", "Employees are required to..."
  OK:  "...information security management system...", "...risk management framework..."
  OK:  "...as part of the change management process..."

For each violation, suggest the most relevant replacement from the Role Register.

=== RULE CDI-08: VAGUE EVIDENCE REFERENCES ===
Statements requiring evidence/records must specify an Evidence Taxonomy type code.
Valid codes (use exactly): LOG, CFG, APR, FRM, TRN, ACK, TST, CRT, MTG, REV, CHK, CNT, INV, CHG, INC, RPT

BAD: "records shall be maintained", "logs must be kept", "evidence shall be retained",
     "audit trails must be preserved", "documentation will be stored"
GOOD: "Evidence: REV — signed quarterly access review. Source: SharePoint. Frequency: quarterly."

Flag lines that vaguely require evidence to be collected/maintained/retained WITHOUT specifying a code.

=== RULE CDI-16: UNREGISTERED ROLE REFERENCES ===
Named roles used in obligation statements must exist in the Role Register above.
Only check roles used in obligations (not just mentioned in passing).
A partial match counts as registered ("ISMS Lead (Acting)" matches "ISMS Lead" in the register).
Skip this check if the Role Register is empty.

=== RESPONSE FORMAT ===
Return ONLY this exact JSON structure. No preamble, no explanation, no markdown.

{{
  "cdi_06": {{
    "passed": true,
    "findings": [
      {{"text": "<exact sentence from document, max 200 chars>", "word": "<aspirational word>", "fix": "<corrected sentence>"}}
    ]
  }},
  "cdi_07": {{
    "passed": true,
    "findings": [
      {{"text": "<exact sentence, max 200 chars>", "term": "<vague term>", "fix": "<corrected using a Role Register title>"}}
    ]
  }},
  "cdi_08": {{
    "passed": true,
    "findings": [
      {{"text": "<exact sentence, max 200 chars>", "fix": "Evidence: [TYPE_CODE] — [description]. Source: [system]. Frequency: [period]."}}
    ]
  }},
  "cdi_16": {{
    "passed": true,
    "findings": [
      {{"role": "<unregistered role name>", "text": "<exact sentence, max 200 chars>", "fix": "<suggested registered alternative>"}}
    ]
  }}
}}

Maximum 5 findings per check. If no violations found, set "passed": true and "findings": [].

DOCUMENT TEXT:
---
{text_for_ai}
---"""


async def _call_ollama_language_checks(
    text: str,
    role_register_titles: list[str],
) -> Optional[dict]:
    """
    Single Ollama call for CDI-06/07/08/16.
    Returns parsed dict or None (triggers fallback).
    qwen2.5:7b at temperature=0 — deterministic, semantic understanding.
    """
    prompt = _build_ai_prompt(text, role_register_titles)
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model":  settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0,
                        "num_predict": 2048,
                        "num_ctx":     32768,
                    },
                },
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()
            if not raw:
                logger.warning("CDI AI check: empty response from Ollama")
                return None
            result = json.loads(raw)
            # Validate expected top-level keys are present
            if not all(k in result for k in ("cdi_06", "cdi_07", "cdi_08", "cdi_16")):
                logger.warning("CDI AI check: response missing expected keys")
                return None
            return result
    except json.JSONDecodeError as exc:
        logger.warning(f"CDI AI check: invalid JSON from Ollama — {exc}")
        return None
    except Exception as exc:
        logger.warning(f"CDI AI check: Ollama call failed — {exc}")
        return None


def _ai_result_to_checks(
    ai: dict,
    role_register_titles: list[str],
) -> list[dict]:
    """Convert the structured AI response into standard check result dicts."""
    checks: list[dict] = []
    suggested = role_register_titles[0] if role_register_titles else "ISMS Lead"

    # CDI-06
    findings_06 = ai.get("cdi_06", {}).get("findings") or []
    if findings_06:
        for f in findings_06[:5]:
            word = f.get("word", "aspirational word")
            checks.append(_fail(
                "CDI-06", "Aspirational language",
                f"Aspirational language '{word}' in an obligation statement — use 'shall' or 'must'.",
                current_text=str(f.get("text", ""))[:200],
                proposed_fix=str(f.get("fix", f"Replace '{word}' with 'shall' or 'must'."))[:300],
                fix_source="Document Creation Standards §5.1",
                confidence=90,
            ))
    else:
        checks.append(_pass("CDI-06", "Aspirational language"))

    # CDI-07
    findings_07 = ai.get("cdi_07", {}).get("findings") or []
    if findings_07:
        for f in findings_07[:5]:
            term = f.get("term", "vague term")
            checks.append(_fail(
                "CDI-07", "Vague role reference",
                f"Vague term '{term}' used as subject of an obligation — use a Role Register title.",
                current_text=str(f.get("text", ""))[:200],
                proposed_fix=str(f.get("fix", f"Replace '{term}' with a Role Register title, e.g. '{suggested}'."))[:300],
                fix_source="Role Register + Document Creation Standards §5.2",
                confidence=92,
            ))
    else:
        checks.append(_pass("CDI-07", "Vague role reference"))

    # CDI-08
    findings_08 = ai.get("cdi_08", {}).get("findings") or []
    if findings_08:
        for f in findings_08[:5]:
            checks.append(_fail(
                "CDI-08", "Vague evidence reference",
                "Vague evidence obligation — must specify an Evidence Taxonomy type code.",
                current_text=str(f.get("text", ""))[:200],
                proposed_fix=str(f.get("fix", "Evidence: [TYPE_CODE] — [description]. Source: [system]. Frequency: [period]."))[:300],
                fix_source="Evidence Taxonomy DRG-QI-REF-EVTX-01-26",
                confidence=90,
            ))
    else:
        checks.append(_pass("CDI-08", "Vague evidence reference"))

    # CDI-16
    findings_16 = ai.get("cdi_16", {}).get("findings") or []
    if findings_16:
        for f in findings_16[:3]:
            role = f.get("role", "unknown role")
            checks.append(_fail(
                "CDI-16", "Unregistered role reference",
                f"'{role}' is used in an obligation but is not in the Role Register.",
                current_text=str(f.get("text", ""))[:200],
                proposed_fix=str(f.get("fix", f"Add '{role}' to the Role Register, or replace with an existing registered title."))[:300],
                fix_source="Role Register cross-reference",
                confidence=75,
            ))
    elif role_register_titles:
        checks.append(_pass("CDI-16", "Role Register alignment"))
    else:
        checks.append(_pass("CDI-16", "Role Register alignment (skipped — register empty)"))

    return checks


# =============================================================================
#  Stage 2 fallback — pattern-based (used only when Ollama is unavailable)
# =============================================================================

def _fallback_cdi_06(text: str) -> list[dict]:
    failures: list[dict] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 35 or s in seen:
            continue
        if _DIRECTIVE_RE.search(s):
            continue
        for pattern, replacement in _ASPIRATIONAL_PATTERNS:
            m = pattern.search(s)
            if m:
                seen.add(s)
                failures.append(_fail(
                    "CDI-06", "Aspirational language",
                    f"'{m.group(0)}' found in a statement without a directive verb.",
                    current_text=s[:200],
                    proposed_fix=pattern.sub(replacement, s)[:200],
                    fix_source="Document Creation Standards §5.1",
                    confidence=72,
                ))
                break
    return failures[:5]


def _fallback_cdi_07(text: str, role_register_titles: list[str]) -> list[dict]:
    failures: list[dict] = []
    seen: set[str] = set()
    suggested = role_register_titles[0] if role_register_titles else "ISMS Lead"
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 15 or s in seen:
            continue
        if not _OBLIGATION_LINE_RE.search(s):
            continue
        s_lower = s.lower()
        for term, pattern in _VAGUE_ROLE_PATTERNS.items():
            if not pattern.search(s_lower):
                continue
            if term == "management" and _MANAGEMENT_COMPOUND_RE.search(s_lower):
                continue
            seen.add(s)
            failures.append(_fail(
                "CDI-07", "Vague role reference",
                f"Vague term '{term}' as subject of an obligation — use a Role Register title.",
                current_text=s[:200],
                proposed_fix=f"Replace '{term}' with a named role, e.g. '{suggested}'.",
                fix_source="Role Register + Document Creation Standards §5.2",
                confidence=80,
            ))
            break
    return failures[:5]


def _fallback_cdi_08(text: str) -> list[dict]:
    failures: list[dict] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        s = line.strip()
        if len(s) < 20 or s in seen:
            continue
        for pattern in _VAGUE_EVIDENCE_RES:
            m = pattern.search(s)
            if m:
                seen.add(s)
                failures.append(_fail(
                    "CDI-08", "Vague evidence reference",
                    f"Vague evidence obligation '{m.group(0)}' — specify an Evidence Taxonomy type code.",
                    current_text=s[:200],
                    proposed_fix="Evidence: [TYPE_CODE] — [description]. Source: [system]. Frequency: [period].",
                    fix_source="Evidence Taxonomy DRG-QI-REF-EVTX-01-26",
                    confidence=82,
                ))
                break
    return failures[:5]


def _fallback_cdi_16(text: str, role_register_titles: list[str]) -> list[dict]:
    if not role_register_titles:
        return []
    role_titles_lower = {r.lower().strip() for r in role_register_titles}
    failures: list[dict] = []
    seen: set[str] = set()
    for line in text.split("\n"):
        for match in _ROLE_SUBJECT_RE.finditer(line):
            extracted = match.group(1).strip()
            el = extracted.lower()
            if el in seen or el in _NON_ROLE_SUBJECTS:
                continue
            if not any(el == r or el in r or r in el for r in role_titles_lower):
                seen.add(el)
                failures.append(_fail(
                    "CDI-16", "Unregistered role reference",
                    f"'{extracted}' used in an obligation but not found in the Role Register.",
                    current_text=line.strip()[:200],
                    proposed_fix=f"Add '{extracted}' to the Role Register, or replace with an existing registered title.",
                    fix_source="Role Register cross-reference",
                    confidence=62,
                ))
    return failures[:3]


def _run_fallback_language_checks(
    text: str,
    role_register_titles: list[str],
) -> list[dict]:
    """Run pattern-based language checks. Used when Ollama is unavailable."""
    checks: list[dict] = []

    f06 = _fallback_cdi_06(text)
    checks.extend(f06) if f06 else checks.append(_pass("CDI-06", "Aspirational language"))

    f07 = _fallback_cdi_07(text, role_register_titles)
    checks.extend(f07) if f07 else checks.append(_pass("CDI-07", "Vague role reference"))

    f08 = _fallback_cdi_08(text)
    checks.extend(f08) if f08 else checks.append(_pass("CDI-08", "Vague evidence reference"))

    f16 = _fallback_cdi_16(text, role_register_titles)
    if f16:
        checks.extend(f16)
    elif role_register_titles:
        checks.append(_pass("CDI-16", "Role Register alignment"))
    else:
        checks.append(_pass("CDI-16", "Role Register alignment (skipped — register empty)"))

    return checks


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
    Run all 16 CDI checks against a document.

    Checks CDI-01..05 and CDI-09..15 are deterministic (rules/regex).
    Checks CDI-06, 07, 08, 16 use a single Ollama call (qwen2.5:7b, temp=0)
    for semantic accuracy, falling back to enhanced regex if Ollama is down.

    Returns a structured report with PASS/FAIL per check and proposed fixes.
    Every FAIL includes proposed_fix, current_text, fix_source, confidence.
    """
    role_register_titles = role_register_titles or []

    try:
        text = extract_text(file_bytes, filename)
    except Exception as exc:
        return {
            "passed":       False,
            "error":        str(exc),
            "checks":       [],
            "pass_count":   0,
            "fail_count":   0,
            "total_checks": 16,
            "used_ai":      False,
        }

    if not text.strip():
        return {
            "passed":       False,
            "error":        (
                "No text could be extracted from this document. "
                "If it is a scanned PDF, convert it to a searchable PDF first. "
                "If it is a .docx, ensure it contains actual text (not just images)."
            ),
            "checks":       [],
            "pass_count":   0,
            "fail_count":   16,
            "total_checks": 16,
            "used_ai":      False,
        }

    checks: list[dict] = []

    # ── Stage 1: Deterministic structural checks ──────────────────────────────
    checks.append(check_01_document_code(text, doc_code))
    checks.append(check_02_revision_history(text))
    checks.append(check_03_purpose_section(text))
    checks.append(check_04_scope_section(text))
    checks.append(check_05_responsibilities_section(text))

    # ── Stage 2: Language quality — try AI, fall back to patterns ─────────────
    ai_result = await _call_ollama_language_checks(text, role_register_titles)
    used_ai = ai_result is not None

    if used_ai:
        logger.info("CDI language checks: using AI (Ollama)")
        language_checks = _ai_result_to_checks(ai_result, role_register_titles)
    else:
        logger.info("CDI language checks: Ollama unavailable — using pattern fallback")
        language_checks = _run_fallback_language_checks(text, role_register_titles)

    checks.extend(language_checks)

    # ── Stage 3: Deterministic metadata checks ───────────────────────────────
    checks.append(check_09_standards_references(text))
    checks.append(check_10_related_documents(text))
    checks.append(check_11_classification_label(text))
    checks.append(check_12_owner_identified(text))
    checks.append(check_13_review_date(text))
    checks.append(check_14_effective_date(text))
    checks.append(check_15_version_number(text))

    pass_count = sum(1 for c in checks if c["result"] == "PASS")
    fail_count = sum(1 for c in checks if c["result"] == "FAIL")

    return {
        "passed":       fail_count == 0,
        "pass_count":   pass_count,
        "fail_count":   fail_count,
        "total_checks": len(checks),
        "checks":       checks,
        "used_ai":      used_ai,
    }
