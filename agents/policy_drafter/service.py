# =============================================================================
# agents/policy_drafter/service.py — Policy Drafter Agent
# Generates complete CDI-compliant document drafts from a brief.
# Uses Ollama to generate each section of the document.
# Follows the 15-step sequence from DRG-QI-REF-DOCS-01-26 Section 8.
# Output is a structured draft with all required CDI sections.
# =============================================================================

import logging
from typing import Optional

import httpx

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
#  Ollama call helper
# =============================================================================

async def _ollama(prompt: str, max_tokens: int = 1500) -> str:
    """Call Ollama and return the generated text."""
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={
                    "model":  settings.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.3,
                        "top_p":       0.9,
                    },
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.error(f"Ollama call failed: {exc}")
        return ""


# =============================================================================
#  Section generators
# =============================================================================

async def _generate_purpose(
    title: str, doc_type: str, department: str, notes: str,
    standards_mapping: str,
) -> str:
    prompt = f"""You are a compliance document writer for Dragnet Solutions Limited, a Nigerian technology company.
Write the Purpose section for a {doc_type} titled "{title}".
Department: {department}
Standards this document addresses: {standards_mapping or 'Not specified'}
Brief from requestor: {notes or 'No additional brief provided'}

The Purpose section must:
- State in ONE paragraph why this document exists
- Use directive language: "This {doc_type} establishes..." or "The purpose of this {doc_type} is to..."
- Reference the standards it addresses
- Be 3-5 sentences maximum
- Never use "should" or "may" — use "shall" or "must" only

Write only the Purpose section text, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=300)


async def _generate_scope(
    title: str, doc_type: str, department: str,
) -> str:
    prompt = f"""Write the Scope section for a {doc_type} titled "{title}" for Dragnet Solutions Limited.
Department: {department}

The Scope section must:
- Be specific about who this applies to (all staff, specific department, contractors, third parties)
- Be specific about what systems, processes, or activities it covers
- Be 2-4 sentences
- Use "This {doc_type} applies to..." as the opening

Write only the Scope section text, no heading, no preamble."""
    return await _ollama(prompt, max_tokens=200)


async def _generate_policy_statement(
    title: str, doc_type: str, notes: str, standards_mapping: str,
    role_titles: list[str],
) -> str:
    roles_sample = ", ".join(role_titles[:8]) if role_titles else "ISMS Lead, Department Head, All Staff"
    prompt = f"""You are a compliance document writer for Dragnet Solutions Limited.
Write the Policy Statement section for a {doc_type} titled "{title}".
Standards: {standards_mapping or 'ISO 27001, ISO 9001'}
Brief: {notes or 'Standard policy statement'}
Available role titles from Role Register: {roles_sample}

The Policy Statement must:
- Contain 4-8 specific, actionable control statements
- Each statement must use "shall" or "must" (never "should" or "may")
- Each statement must assign responsibility to a NAMED ROLE from the Role Register above
- Each statement must be measurable and auditable
- Format each statement as a numbered list

Example format:
1. The ISMS Lead shall review all user access rights quarterly and produce a signed access review report per department.
2. Department Heads must ensure all new starters complete information security awareness training within their first week.

Write only the numbered control statements, no other text."""
    return await _ollama(prompt, max_tokens=600)


async def _generate_responsibilities(
    title: str, role_titles: list[str], policy_statement: str,
) -> str:
    roles_sample = ", ".join(role_titles[:6]) if role_titles else "ISMS Lead, Department Head, All Staff"
    prompt = f"""Based on these control statements from the policy "{title}":

{policy_statement}

Write the Responsibilities section assigning each control to a named role.
Available roles: {roles_sample}

Format as:
[Role Title]
- Responsibility 1
- Responsibility 2

Only use roles from the available roles list above.
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
#  Document code generator
# =============================================================================

def _generate_doc_code(
    department: str, doc_type: str, title: str, serial: str = "01",
) -> str:
    dept = DEPT_CODES.get(department, department[:4].upper())
    type_code = TYPE_CODES.get(doc_type, "DOC")
    # Generate short code from title — take first letters of significant words
    words = [w for w in title.upper().split() if len(w) > 3 and w not in
             ("WITH", "FROM", "THAT", "THIS", "THEIR", "HAVE", "BEEN", "WILL",
              "SHALL", "MUST", "POLICY", "PROCEDURE", "GUIDELINES")]
    short = "".join(w[:3] for w in words[:2]) if words else "GEN"
    year  = "26"
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
    role_titles:       Optional[list[str]] = None,
    serial:            str = "01",
) -> dict:
    """
    Generate a complete CDI-compliant document draft from a brief.
    Follows DRG-QI-REF-DOCS-01-26 Section 8 fifteen-step sequence.

    Returns a dict with:
      doc_code, title, doc_type, department, sections (dict of section name → content),
      full_text (complete draft as plain text)
    """
    role_titles = role_titles or []
    logger.info(f"Policy Drafter starting: '{title}' ({doc_type}, {department})")

    doc_code = _generate_doc_code(department, doc_type, title, serial)

    # Generate all sections
    logger.info("Generating Purpose...")
    purpose = await _generate_purpose(title, doc_type, department, notes, standards_mapping)

    logger.info("Generating Scope...")
    scope = await _generate_scope(title, doc_type, department)

    logger.info("Generating Policy Statement...")
    policy_statement = await _generate_policy_statement(
        title, doc_type, notes, standards_mapping, role_titles
    )

    logger.info("Generating Responsibilities...")
    responsibilities = await _generate_responsibilities(title, role_titles, policy_statement)

    logger.info("Generating Procedure...")
    procedure = await _generate_procedure(title, doc_type, notes)

    logger.info("Generating Records...")
    records = await _generate_records(policy_statement)

    # Build full document text
    full_text = f"""DRAGNET SOLUTIONS LIMITED
{title.upper()}
Document Code: {doc_code}
Version: 1.0
Status: DRAFT
Standards: {standards_mapping or 'ISO 27001, ISO 9001'}
Department: {department}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REVISION HISTORY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Version | Date       | Author    | Change
1.0     | [DATE]     | [AUTHOR]  | Initial draft — AI-generated

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{purpose}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2. SCOPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{scope}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
3. POLICY STATEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{policy_statement}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
4. RESPONSIBILITIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{responsibilities}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
5. PROCEDURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{procedure}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
6. RECORDS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{records}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
7. RELATED DOCUMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[To be completed by document owner]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
8. REVIEW AND APPROVAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Document Owner:    [ROLE FROM ROLE REGISTER]
Approved By:       [APPROVER NAME AND ROLE]
Effective Date:    [DATE]
Next Review Date:  [DATE + 12 MONTHS]
Classification:    Internal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
END OF DOCUMENT — {doc_code} v1.0 DRAFT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    sections = {
        "purpose":         purpose,
        "scope":           scope,
        "policy_statement":policy_statement,
        "responsibilities":responsibilities,
        "procedure":       procedure,
        "records":         records,
    }

    logger.info(f"Policy Drafter complete: {doc_code}")

    return {
        "doc_code":         doc_code,
        "title":            title,
        "doc_type":         doc_type,
        "department":       department,
        "standards_mapping":standards_mapping,
        "sections":         sections,
        "full_text":        full_text,
        "ai_generated":     True,
    }