# =============================================================================
# agents/policy_drafter/service.py — Policy Drafter Agent
# Generates complete CDI-compliant document drafts from a brief.
# Uses Ollama to generate each section of the document.
# Follows the 15-step sequence from DRG-QI-REF-DOCS-01-26 Section 8.
# Output is a structured draft + a fully formatted .docx buffer.
# =============================================================================

import logging

from agents.llm_client import llm_generate
from agents.policy_drafter.docx_builder import build_docx
from config import settings

logger = logging.getLogger(__name__)

# =============================================================================
#  Document type → code segment mapping
# =============================================================================

TYPE_CODES = {
    "Policy":    "POL",
    "Procedure": "PRO",
    "Combined":  "POL",
    "Manual":    "MAN",
    "Guideline": "GUI",
    "Standard":  "STD",
    "SLA":       "SLA",
}

DEPT_CODES = {
    "QI": "QI", "ISMS": "ISMS", "HR": "HR", "FIN": "FIN",
    "REC": "REC", "IT": "IT", "TES": "TES", "VER": "VER",
    "CX": "CX", "SD": "SD", "EX": "EX",
}


# =============================================================================
#  LLM call helper
# =============================================================================

async def _ollama(prompt: str, max_tokens: int = 1500) -> str:
    """Generate policy section text — heavy tier (14B)."""
    return await llm_generate(
        prompt,
        tier="heavy",
        max_tokens=max_tokens,
        temperature=0.3,
        top_p=0.9,
    )


# =============================================================================
#  Section generators
# =============================================================================

async def _generate_purpose(
    title: str, doc_type: str, department: str, notes: str,
    standards_mapping: str,
) -> str:
    effective_standards = standards_mapping or "ISO 27001, ISO 9001, NDPA"
    prompt = f"""You are a compliance document writer for Dragnet Solutions Limited, a Nigerian technology company.
Write the Purpose section for a {doc_type} titled "{title}".
Department: {department}
Standards this document addresses: {effective_standards}
Brief from requestor: {notes or 'No additional brief provided'}

Rules:
- ONE paragraph, 3-5 sentences maximum
- Opening must be: "This {doc_type} establishes..." or "The purpose of this {doc_type} is to..."
- You MUST name the standards explicitly: write "{effective_standards}" somewhere in the text
- Use only "shall" or "must" — NEVER "should" or "may"

Write only the Purpose section text, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=300)


async def _generate_scope(
    title: str, doc_type: str, department: str,
) -> str:
    prompt = f"""Write the Scope section for a {doc_type} titled "{title}" for Dragnet Solutions Limited.
Department: {department}

Rules:
- Open with: "This {doc_type} applies to..."
- Name a specific, plausible role for this department where possible (e.g. "the {department} Manager and all direct reports"), inferred from context — do not invent a generic register.
- You may also reference "all Dragnet team members" or "all contractors with access to Dragnet systems"
- BANNED WORDS — do NOT write any of these: employees, personnel, staff, management, administration, the team, leadership, stakeholders
- 2-4 sentences, specific about systems and activities covered

Write only the Scope section text, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=200)


async def _generate_policy_statement(
    title: str, doc_type: str, notes: str, standards_mapping: str,
) -> str:
    effective_standards = standards_mapping or "ISO 27001, ISO 9001, NDPA"
    prompt = f"""You are writing the Policy Statement section for a {doc_type} titled "{title}" for Dragnet Solutions Limited.
Brief: {notes or 'Standard policy controls'}

REQUIRED STANDARDS: {effective_standards}

MANDATORY RULES — violating any of these causes the document to FAIL quality review:
1. BANNED WORDS: Never write "employees", "personnel", "staff", "management", "administration", "the team", "leadership", "stakeholders", "responsible parties", "appropriate personnel". Assign responsibility to a specific, plausible named role instead (e.g. "the ISMS Lead", "the Compliance Officer") — infer a role appropriate to the statement's subject matter.
2. Every statement MUST end with a standards clause in parentheses, e.g. (ISO 27001 A.5.18) or (ISO 9001 8.1) or (NDPA S.39).
3. Every statement MUST use "shall" or "must" — never "should", "may", "where possible", "as appropriate".
4. Every statement MUST assign responsibility to a specific named role, not a group.
5. Write 5-8 numbered statements. Each must be specific and auditable.

CORRECT example:
1. The ISMS Lead shall review all user access rights quarterly and produce a signed access review report. (ISO 27001 A.5.18)
2. The HR Manager must ensure all new joiners complete mandatory onboarding training within five working days of their start date. (ISO 9001 7.2)

Write ONLY the numbered control statements. No headings, no preamble, no other text."""
    return await _ollama(prompt, max_tokens=700)


async def _generate_responsibilities(
    title: str, policy_statement: str,
) -> str:
    prompt = f"""Write the Responsibilities section for the policy "{title}" based on these control statements:

{policy_statement}

MANDATORY RULES:
- Name the specific role already used for each responsibility in the control statements above — do not introduce new roles here. BANNED: "employees", "personnel", "staff", "management", "administration", "the team", "leadership", "stakeholders". Using any banned word FAILS the quality check.
- Format:
[Role Title]
- Specific responsibility derived from the control statements above
- Another responsibility if applicable

Write only the responsibilities content, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=500)


async def _generate_procedure(
    title: str, doc_type: str, notes: str,
) -> str:
    if doc_type in ("Policy",):
        return "Refer to the associated procedure document for implementation steps."

    prompt = f"""Write the Procedure section for "{title}" for Dragnet Solutions Limited.
Brief: {notes or 'Standard operating procedure'}

The Procedure section must:
- List steps in numbered order
- Each step must be specific and actionable
- Reference the responsible role for each step
- Be 5-10 steps

Write only the numbered steps, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=500)


async def _generate_records(
    policy_statement: str,
) -> str:
    prompt = f"""Based on these control statements:
{policy_statement}

Write the Records section listing what evidence must be retained to prove these controls are operating.
For each record specify:
- Record name
- Evidence Taxonomy type code (LOG, CFG, APR, FRM, TRN, ACK, TST, CRT, MTG, REV, CHK, CNT, INV, CHG, INC, or RPT)
- Storage location (SharePoint, Intune, GitHub, SeamlessHR, etc.)
- Retention period

Format each as: [Record name] (Type: [CODE]) — Source: [system] — Retain: [period]

Write only the records list, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=400)


# =============================================================================
#  Document code helpers
# =============================================================================

def _doc_code_parts(department: str, doc_type: str, title: str) -> tuple[str, str, str]:
    """Return (dept_code, type_code, short_ref) — the variable parts of the doc code."""
    dept      = DEPT_CODES.get(department, department[:4].upper())
    type_code = TYPE_CODES.get(doc_type, "DOC")
    words     = [
        w for w in title.upper().split()
        if len(w) > 3 and w not in (
            "WITH", "FROM", "THAT", "THIS", "THEIR", "HAVE", "BEEN", "WILL",
            "SHALL", "MUST", "POLICY", "PROCEDURE", "GUIDELINES", "STANDARD",
        )
    ]
    short = "".join(w[:3] for w in words[:2]) if words else "GEN"
    return dept, type_code, short


def generate_doc_code_base(department: str, doc_type: str, title: str) -> str:
    """Return the base prefix WITHOUT serial and year — used for collision detection."""
    dept, type_code, short = _doc_code_parts(department, doc_type, title)
    return f"DRG-{dept}-{type_code}-{short}"


def _generate_doc_code(
    department: str, doc_type: str, title: str, serial: str = "01",
) -> str:
    dept, type_code, short = _doc_code_parts(department, doc_type, title)
    year = "26"
    return f"DRG-{dept}-{type_code}-{short}-{serial}-{year}"


# =============================================================================
#  Main entry point
# =============================================================================

async def draft_document(
    title:             str,
    doc_type:          str,
    department:        str,
    notes:             str = "",
    standards_mapping: str = "",
    serial:            str = "01",
) -> dict:
    """
    Generate a complete CDI-compliant document draft from a brief.
    Follows DRG-QI-REF-DOCS-01-26 Section 8 fifteen-step sequence.

    Returns a dict with:
      doc_code, title, doc_type, department, sections (dict),
      full_text (plain text), docx_buffer (BytesIO — ready to serve / upload)
    """
    logger.info(f"Document Drafter starting: '{title}' ({doc_type}, {department})")

    doc_code = _generate_doc_code(department, doc_type, title, serial)

    # Default standards if not provided — ensures CDI-09 passes
    effective_standards = standards_mapping or "ISO 27001, ISO 9001, NDPA"

    # ── Generate all sections via Ollama ─────────────────────────────────────
    logger.info("Generating Purpose...")
    purpose = await _generate_purpose(title, doc_type, department, notes, effective_standards)

    logger.info("Generating Scope...")
    scope = await _generate_scope(title, doc_type, department)

    logger.info("Generating Policy Statement...")
    policy_statement = await _generate_policy_statement(
        title, doc_type, notes, effective_standards
    )

    logger.info("Generating Responsibilities...")
    responsibilities = await _generate_responsibilities(title, policy_statement)

    logger.info("Generating Procedure...")
    procedure = await _generate_procedure(title, doc_type, notes)

    logger.info("Generating Records...")
    records = await _generate_records(policy_statement)

    # ── Assemble sections dict ────────────────────────────────────────────────
    sections = {
        "purpose":          purpose,
        "scope":            scope,
        "policy_statement": policy_statement,
        "responsibilities": responsibilities,
        "procedure":        procedure,
        "records":          records,
    }

    # ── Plain-text fallback (still useful for Notes field in SharePoint) ──────
    full_text = f"""DRAGNET SOLUTIONS LIMITED
{title.upper()}
Document Code: {doc_code}
Version: 1.0
Status: DRAFT
Standards: {standards_mapping or 'ISO 27001, ISO 9001'}
Department: {department}

REVISION HISTORY
Version | Date       | Author    | Change
1.0     | [DATE]     | [AUTHOR]  | Initial draft — AI-generated

1. PURPOSE
{purpose}

2. SCOPE
{scope}

3. POLICY STATEMENT
{policy_statement}

4. RESPONSIBILITIES
{responsibilities}

5. PROCEDURE
{procedure}

6. RECORDS
{records}

7. RELATED DOCUMENTS
[To be completed by document owner]

8. REVIEW AND APPROVAL
Document Owner:    [ROLE NAME]
Approved By:       [APPROVER NAME AND ROLE]
Effective Date:    [DATE]
Next Review Date:  [DATE + 12 MONTHS]
Classification:    Internal

END OF DOCUMENT — {doc_code} v1.0 DRAFT"""

    # ── Build the formatted .docx ─────────────────────────────────────────────
    draft_meta = {
        "doc_code":          doc_code,
        "title":             title,
        "doc_type":          doc_type,
        "department":        department,
        "standards_mapping": effective_standards,   # always non-empty — CDI-09 cover page
        "sections":          sections,
    }
    logger.info("Building .docx...")
    docx_buffer = build_docx(draft_meta)
    logger.info(f"Document Drafter complete: {doc_code}")

    return {
        **draft_meta,
        "full_text":    full_text,
        "docx_buffer":  docx_buffer,   # BytesIO — use in download endpoint
        "ai_generated": True,
    }