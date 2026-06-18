# =============================================================================
# agents/extractor/ollama_client.py
# Simplified extraction — asks only for what small models do reliably:
#   control_statement, risk_statement, proposed_owner_role, iso_clause
# Everything else (ControlType, EvidenceType, booleans) is handled in
# service.py post-processing using deterministic rules, not the model.
# =============================================================================

import json
import logging
from enum import Enum
from typing import Optional

import httpx

from agents.llm_client import check_llm_connectivity, llm_generate
from config import settings

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 8000


# =============================================================================
#  Document type classification
# =============================================================================

class DocumentType(str, Enum):
    POLICY       = "Policy"
    JD           = "JobDescription"
    CONTRACT     = "Contract"
    REGULATORY   = "Regulatory"
    AUDIT        = "Audit"
    EVIDENCE     = "EvidenceSample"
    FORM         = "Form"
    REFERENCE    = "Reference"
    UNCLASSIFIED = "Unclassified"


FOLDER_TYPE_MAP = {
    "policies & sops":          DocumentType.POLICY,
    "policies and sops":        DocumentType.POLICY,
    "contracts & agreements":   DocumentType.CONTRACT,
    "contracts and agreements": DocumentType.CONTRACT,
    "job descriptions":         DocumentType.JD,
    "regulatory & statutory":   DocumentType.REGULATORY,
    "regulatory and statutory": DocumentType.REGULATORY,
    "evidence samples":         DocumentType.EVIDENCE,
    "audit & risks":            DocumentType.AUDIT,
    "audit and risks":          DocumentType.AUDIT,
}

CODE_PREFIX_MAP = {
    "-POL-PRO-": DocumentType.POLICY,
    "-POL-":     DocumentType.POLICY,
    "-PRO-":     DocumentType.POLICY,
    "DRG-JD-":   DocumentType.JD,
    "-JD-":      DocumentType.JD,
    "-SLA-":     DocumentType.CONTRACT,
    "-FM-":      DocumentType.FORM,
    "-REF-":     DocumentType.REFERENCE,
}

NON_EXTRACTION_TYPES = {
    DocumentType.EVIDENCE,
    DocumentType.FORM,
    DocumentType.REFERENCE,
}


def classify_document(
    filename: str,
    doc_code: str,
    folder_path: Optional[str] = None,
) -> DocumentType:
    if folder_path:
        folder_lower = folder_path.lower().strip()
        for k, v in FOLDER_TYPE_MAP.items():
            if k in folder_lower:
                return v
    code_upper = doc_code.upper()
    for k, v in CODE_PREFIX_MAP.items():
        if k.upper() in code_upper:
            return v
    fname = filename.lower()
    if any(k in fname for k in ["job description", " jd ", "_jd_", "-jd-"]):
        return DocumentType.JD
    if any(k in fname for k in ["contract", "agreement", "nda", "sla"]):
        return DocumentType.CONTRACT
    if any(k in fname for k in ["policy", "procedure", "sop"]):
        return DocumentType.POLICY
    if any(k in fname for k in ["audit", "finding", "risk assessment"]):
        return DocumentType.AUDIT
    return DocumentType.UNCLASSIFIED


# =============================================================================
#  POLICY prompt — ask for 4 fields only
#  Small models are reliable at: identifying a directive sentence,
#  writing a brief risk statement, naming a role, and spotting ISO references.
#  They are NOT reliable at: ControlType, EvidenceType, frequency, systems.
#  Those are handled in service.py with deterministic rules.
# =============================================================================

_POLICY_PROMPT = """You are reading a policy or procedure document. Extract compliance controls.

A control is a sentence using SHALL, MUST, IS REQUIRED TO, or WILL that mandates an action.
Do NOT extract: scope statements, definitions, purposes, aspirational language (should/may).

For each control you find, return a JSON object with exactly these 4 fields:
  "s": the complete control sentence including the subject (who must do what)
  "r": one sentence — what goes wrong if this control is not followed
  "o": the role or job title responsible (exact words from the document, or null)
  "c": ISO 27001 clause like A.5.18, or NDPA section like S.39, or null if not mentioned

Return a JSON array of these objects. Extract ALL controls — there are usually 3-8 per document.
If a sentence starts with "shall" without a subject, add the subject from context.

Return only the JSON array, nothing else."""

_JD_PROMPT = """You are reading a Job Description. Extract responsibilities.

For each responsibility, return a JSON object:
  "s": the complete responsibility statement
  "r": why this responsibility matters for compliance
  "o": the job title from this JD
  "c": null

Return a JSON array. Extract ALL responsibilities. Return only the JSON array."""

_CONTRACT_PROMPT = """You are reading a contract. Extract obligations Dragnet must fulfil.

Look for: "Dragnet shall", "the provider shall", "both parties agree".
For each obligation:
  "s": the complete obligation sentence
  "r": consequence of non-compliance
  "o": the role responsible at Dragnet
  "c": NDPA section if applicable, otherwise null

Return a JSON array. Return only the JSON array."""

_REGULATORY_PROMPT = """You are reading a regulatory document. Extract compliance obligations.

For each obligation that applies to Dragnet:
  "s": the obligation statement
  "r": penalty or consequence if missed
  "o": the regulating authority
  "c": the law or section reference

Return a JSON array. Return only the JSON array."""

_AUDIT_PROMPT = """You are reading an audit report. Extract findings and nonconformities.

For each finding:
  "s": the finding statement
  "r": what must be done to remediate it
  "o": severity — Critical, Major, or Minor
  "c": standard clause reference or null

Return a JSON array. Return only the JSON array."""

PROMPTS = {
    DocumentType.POLICY:     _POLICY_PROMPT,
    DocumentType.JD:         _JD_PROMPT,
    DocumentType.CONTRACT:   _CONTRACT_PROMPT,
    DocumentType.REGULATORY: _REGULATORY_PROMPT,
    DocumentType.AUDIT:      _AUDIT_PROMPT,
}


# =============================================================================
#  Core extraction
# =============================================================================

def _build_prompt(doc_type: DocumentType, text: str, doc_code: str) -> str:
    system = PROMPTS.get(doc_type)
    if not system:
        raise ValueError(f"No prompt for {doc_type}")

    if len(text) > MAX_CHUNK_CHARS:
        text = text[:MAX_CHUNK_CHARS]
        logger.warning(f"{doc_code}: truncated to {MAX_CHUNK_CHARS} chars")

    return (
        f"{system}\n\n"
        f"Document: {doc_code}\n\n"
        f"===BEGIN===\n{text}\n===END===\n\n"
        f"JSON array:"
    )


async def run_extraction(
    document_text: str,
    doc_code: str,
    document_type: DocumentType = DocumentType.POLICY,
) -> list[dict]:
    if document_type in NON_EXTRACTION_TYPES:
        return []

    prompt = _build_prompt(document_type, document_text, doc_code)

    logger.info(
        f"Extracting | {doc_code} | {document_type.value} | "
        f"provider={settings.llm_provider} | chars={len(document_text)}"
    )

    raw = await llm_generate(
        prompt,
        tier="heavy",
        max_tokens=2000,
        temperature=0.1,
        top_p=0.9,
        repeat_penalty=1.2,
        json_mode=True,
    )
    return _parse_response(raw, doc_code)


def _parse_response(raw: str, doc_code: str) -> list[dict]:
    # Strip DeepSeek R1 thinking blocks before parsing
    # import re
    # cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    # Continue with existing logic using cleaned instead of raw
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    # Handle wrapped objects
    if cleaned.startswith("{"):
        try:
            wrapper = json.loads(cleaned)
            # Try common wrapper keys
            for k in ("items", "controls", "obligations", "findings", "responsibilities", "results"):
                if k in wrapper and isinstance(wrapper[k], list):
                    cleaned = json.dumps(wrapper[k])
                    break
            else:
                cleaned = json.dumps([wrapper])
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error(f"{doc_code}: JSON parse failed | raw[:200]: {raw[:200]}")
        return []

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    # Normalise short-key format {"s":..., "r":..., "o":..., "c":...}
    # to full field names for service.py
    normalised = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        # Handle both {"s": ..., "r": ..., "o": ..., "c": ...}
        # and {"control_statement": ..., "risk_statement": ..., ...}
        stmt = item.get("s") or item.get("control_statement") or item.get("responsibility_statement") or ""
        risk = item.get("r") or item.get("risk_statement") or ""
        role = item.get("o") or item.get("proposed_owner_role") or ""
        clause = item.get("c") or item.get("iso_clause") or ""

        # Skip empty items
        if not stmt or len(stmt.strip()) < 10:
            continue

        normalised.append({
            "statement": stmt.strip(),
            "risk":      risk.strip(),
            "role":      role.strip(),
            "clause":    clause.strip() if clause else "",
        })

    logger.info(f"{doc_code}: {len(normalised)} items parsed")
    return normalised


async def check_ollama_connectivity() -> dict:
    """Delegates to the central LLM client health check (Ollama or RunPod)."""
    return await check_llm_connectivity()


# =============================================================================
#  Procedural step extraction (second output stream for Policy/PRO documents)
# =============================================================================

_PROCEDURAL_PROMPT = """You are reading a policy or procedure document. Extract procedural HOW-TO content only.

You are looking for: numbered workflow steps, approval chains, form references, timelines,
contact points, escalation paths, threshold criteria, and system references.

DO NOT extract: policy statements with SHALL/MUST (those are controls, not procedures),
definitions, purpose sections, revision history, or scope statements.

For each distinct process or workflow you find, return one object per step:
  "process": name of the process (e.g. "Asset acquisition", "Leave application")
  "section": section number in the document (e.g. "8.4") or null
  "step": integer step number within this process
  "text": the actual instruction for this step
  "roles": comma-separated roles involved in this step, or null
  "forms": any form names or codes mentioned, or null
  "systems": any systems mentioned (AAMP, SeamlessHR, etc.), or null
  "tags": 3-5 comma-separated keywords for search (e.g. "laptop, procurement, asset")

Return a JSON array of step objects. If no procedural content exists, return [].
Return only the JSON array, nothing else."""


def _build_procedural_prompt(text: str, doc_code: str) -> str:
    if len(text) > MAX_CHUNK_CHARS:
        text = text[:MAX_CHUNK_CHARS]
    return (
        f"{_PROCEDURAL_PROMPT}\n\n"
        f"Document: {doc_code}\n\n"
        f"===BEGIN===\n{text}\n===END===\n\n"
        f"JSON array:"
    )


async def extract_procedural_steps(
    document_text: str,
    doc_code: str,
) -> list[dict]:
    """
    Extract procedural how-to steps from a policy/procedure document.
    Returns normalised step dicts ready for procedures_service.write_procedural_steps().
    Fails soft — returns [] on any error.
    """
    prompt = _build_procedural_prompt(document_text, doc_code)

    logger.info(
        f"Procedural extraction | {doc_code} | "
        f"provider={settings.llm_provider} | chars={len(document_text)}"
    )

    raw = await llm_generate(
        prompt,
        tier="light",
        max_tokens=3000,
        temperature=0.1,
        top_p=0.9,
        json_mode=True,
    )
    return _parse_procedural_response(raw, doc_code)


def _parse_procedural_response(raw: str, doc_code: str) -> list[dict]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines   = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    if cleaned.startswith("{"):
        try:
            wrapper = json.loads(cleaned)
            for k in ("steps", "items", "procedures", "results"):
                if k in wrapper and isinstance(wrapper[k], list):
                    cleaned = json.dumps(wrapper[k])
                    break
            else:
                cleaned = json.dumps([wrapper])
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"{doc_code}: procedural JSON parse failed | raw[:200]: {raw[:200]}")
        return []

    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        return []

    steps = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        step_text = str(item.get("text") or item.get("step_text") or "").strip()
        if not step_text or len(step_text) < 10:
            continue
        steps.append({
            "process_name":      str(item.get("process") or item.get("process_name") or "").strip(),
            "section_ref":       str(item.get("section") or item.get("section_ref") or "").strip(),
            "step_number":       int(item.get("step") or item.get("step_number") or 0),
            "step_text":         step_text,
            "roles_involved":    str(item.get("roles") or item.get("roles_involved") or "").strip(),
            "forms_referenced":  str(item.get("forms") or item.get("forms_referenced") or "").strip(),
            "systems_referenced":str(item.get("systems") or item.get("systems_referenced") or "").strip(),
            "keywords":          str(item.get("tags") or item.get("keywords") or "").strip(),
        })

    logger.info(f"{doc_code}: {len(steps)} procedural steps parsed")
    return steps