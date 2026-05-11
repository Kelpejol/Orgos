# # =============================================================================
# # agents/extractor/ollama_client.py — Ollama local LLM client
# # Sends document text to the local Ollama server, receives structured JSON.
# # All document processing stays on the local GPU — no content leaves Dragnet.
# # Depends on: config.py, agents/extractor/schemas.py, httpx
# # =============================================================================

# import json
# import logging
# from typing import Optional

# import httpx

# from config import settings

# logger = logging.getLogger(__name__)

# # =============================================================================
# #  Extraction prompt — carefully crafted to produce consistent JSON output
# # =============================================================================

# _SYSTEM_PROMPT = """You are a GRC (Governance, Risk, and Compliance) extraction specialist.
# You analyse Dragnet Solutions policy documents and extract structured compliance data.

# Your ONLY job is to extract risk-control-evidence triplets and return them as valid JSON.
# Do not explain. Do not add commentary. Return ONLY the JSON array.

# For each control requirement you find in the document, extract:
# 1. risk_statement: The specific risk or threat this control addresses
# 2. control_statement: The exact control requirement (what must be done)
# 3. control_type: One of: Preventive, Detective, Corrective, Directive
# 4. evidence_required: What evidence proves this control is working
# 5. evidence_frequency: One of: Continuous, Monthly, Quarterly, Annual, Per occurrence
# 6. proposed_owner_role: The role title responsible (e.g. "ISMS Lead", "All Staff")
# 7. iso_clause: The most relevant ISO 27001, ISO 9001, or NDPA clause (e.g. "A.5.18", "7.5", "S.39")
# 8. source_clause: The section in this document (e.g. "§5.2", "Section 7.3")
# 9. confidence_score: Your confidence in this extraction from 0.0 to 1.0
# 10. completeness_flag: "COMPLETE" if risk+control+evidence are all clear, "DEFICIENT" if anything is ambiguous
# 11. deficiency_reason: If DEFICIENT, explain what is missing or unclear (otherwise null)

# Rules:
# - Extract EVERY control requirement, explicit or implied
# - Classify directives (must/shall) separately from guidelines (should/may)
# - If frequency is not stated, infer from control type and risk level
# - Map to the MOST SPECIFIC ISO clause possible
# - Do not invent information — if something is truly unclear, mark DEFICIENT

# Return format — a JSON array only, no wrapper object:
# [
#   {
#     "risk_statement": "...",
#     "control_statement": "...",
#     "control_type": "Preventive",
#     "evidence_required": "...",
#     "evidence_frequency": "Quarterly",
#     "proposed_owner_role": "...",
#     "iso_clause": "A.5.18",
#     "source_clause": "§7.3",
#     "confidence_score": 0.92,
#     "completeness_flag": "COMPLETE",
#     "deficiency_reason": null
#   }
# ]
# """


# def _build_extraction_prompt(document_text: str, doc_code: str) -> str:
#     """
#     Build the full extraction prompt for a given document.
#     Truncates very long documents to stay within context limits.

#     Args:
#         document_text: Full text of the policy document
#         doc_code: Document code for context (e.g. DRG-ISMS-POL-ACP-01-25)

#     Returns:
#         Complete prompt string to send to Ollama
#     """
#     # Truncate to ~12,000 chars to stay safely within typical context windows
#     # Llama3 8B: 8192 tokens ≈ 6000 words ≈ 9000 chars
#     # Mistral 7B: 8192 tokens — similar limit
#     max_chars = 3_000
#     truncated = False

#     if len(document_text) > max_chars:
#         document_text = document_text[:max_chars]
#         truncated = True
#         logger.warning(
#             f"Document {doc_code} truncated to {max_chars} chars for extraction. "
#             "Consider chunking long documents."
#         )

#     truncation_note = (
#         "\n\n[NOTE: This document was truncated. Extract from the visible content only.]"
#         if truncated
#         else ""
#     )

#     return (
#         f"{_SYSTEM_PROMPT}\n\n"
#         f"Document: {doc_code}{truncation_note}\n\n"
#         f"---BEGIN DOCUMENT---\n{document_text}\n---END DOCUMENT---\n\n"
#         "Extract all controls now. Return only the JSON array:"
#     )


# async def (document_text: str, doc_code: str) -> list[dict]:
#     """
#     Send document text to the local Ollama LLM and return parsed extraction results.

#     Args:
#         document_text: Full text content of the policy document
#         doc_code: Source document code for context

#     Returns:
#         List of raw extraction dicts (validated by caller using ExtractionItem schema)

#     Raises:
#         httpx.ConnectError: If Ollama is not running on the configured URL
#         httpx.TimeoutException: If extraction takes longer than OLLAMA_TIMEOUT
#         ValueError: If Ollama returns unparseable JSON
#     """
#     prompt = _build_extraction_prompt(document_text, doc_code)

#     logger.info(
#         f"Sending {doc_code} to Ollama "
#         f"(model={settings.ollama_model}, "
#         f"timeout={settings.ollama_timeout}s, "
#         f"chars={len(document_text)})"
#     )

#     async with httpx.AsyncClient(
#         timeout=httpx.Timeout(settings.ollama_timeout, connect=10.0)
#     ) as client:
#         response = await client.post(
#             f"{settings.ollama_base_url}/api/generate",
#             json={
#                 "model": settings.ollama_model,
#                 "prompt": prompt,
#                 "stream": False,
#                 "format": "json",
#                 "options": {
#                     "temperature": 0.1,   # Low temperature = deterministic output
#                     "top_p": 0.9,
#                     "repeat_penalty": 1.1,
#                 },
#             },
#         )
#         response.raise_for_status()

#     raw_response = response.json().get("response", "")
#     logger.debug(f"Ollama raw response length: {len(raw_response)} chars")

#     return _parse_extraction_response(raw_response, doc_code)


# def _parse_extraction_response(raw: str, doc_code: str) -> list[dict]:
#     """
#     Parse the raw JSON string from Ollama into a list of extraction dicts.

#     Handles common LLM output issues:
#     - JSON wrapped in markdown code fences
#     - Trailing commas
#     - Single item returned as object instead of array

#     Args:
#         raw: Raw string response from Ollama
#         doc_code: Used for logging context only

#     Returns:
#         List of extraction item dicts

#     Raises:
#         ValueError: If the response cannot be parsed as valid JSON
#     """
#     # Strip markdown code fences if present
#     cleaned = raw.strip()
#     if cleaned.startswith("```"):
#         lines = cleaned.split("\n")
#         # Remove first line (```json or ```) and last line (```)
#         cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

#     # Some models wrap the array in an object — unwrap it
#     if cleaned.startswith("{") and '"items"' in cleaned:
#         try:
#             wrapper = json.loads(cleaned)
#             cleaned = json.dumps(wrapper.get("items", wrapper))
#         except json.JSONDecodeError:
#             pass

#     try:
#         parsed = json.loads(cleaned)
#     except json.JSONDecodeError as exc:
#         logger.error(
#             f"Failed to parse Ollama response for {doc_code}: {exc}\n"
#             f"Raw (first 500 chars): {raw[:500]}"
#         )
#         raise ValueError(
#             f"Ollama returned unparseable JSON for {doc_code}. "
#             "Check that the model supports JSON format mode."
#         ) from exc

#     # If a single dict was returned instead of a list, wrap it
#     if isinstance(parsed, dict):
#         parsed = [parsed]

#     if not isinstance(parsed, list):
#         raise ValueError(
#             f"Expected JSON array from Ollama, got {type(parsed).__name__}"
#         )

#     logger.info(f"Parsed {len(parsed)} extraction items from {doc_code}")
#     return parsed


# async def check_ollama_connectivity() -> dict:
#     """
#     Check if Ollama is running and the configured model is available.
#     Used by health check endpoints.
#     """
#     try:
#         async with httpx.AsyncClient(timeout=5.0) as client:
#             response = await client.get(f"{settings.ollama_base_url}/api/tags")
#             response.raise_for_status()
#             models = [m["name"] for m in response.json().get("models", [])]
#             model_available = any(
#                 settings.ollama_model in m for m in models
#             )
#             return {
#                 "status": "ok",
#                 "ollama_url": settings.ollama_base_url,
#                 "model": settings.ollama_model,
#                 "model_available": model_available,
#                 "available_models": models,
#             }
#     except httpx.ConnectError:
#         return {
#             "status": "error",
#             "detail": (
#                 f"Cannot connect to Ollama at {settings.ollama_base_url}. "
#                 "Run: ollama serve"
#             ),
#         }
#     except Exception as exc:
#         return {"status": "error", "detail": str(exc)}


# =============================================================================
# agents/extractor/ollama_client.py — Ollama LLM client
# Document-type-aware extraction per:
#   DRG-QI-REF-EXRL-01-26 (Extraction Rules by Document Type)
#   DRG-QI-REF-EVTX-01-26 (Evidence Taxonomy v2.0)
# Each document type uses a different prompt and produces different output.
# Depends on: config.py
# =============================================================================

import json
import logging
from enum import Enum
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


# =============================================================================
#  Document type classification
# =============================================================================


class DocumentType(str, Enum):
    POLICY = "Policy"
    JD = "JobDescription"
    CONTRACT = "Contract"
    REGULATORY = "Regulatory"
    AUDIT = "Audit"
    EVIDENCE = "EvidenceSample"
    FORM = "Form"
    REFERENCE = "Reference"
    UNCLASSIFIED = "Unclassified"


FOLDER_TYPE_MAP = {
    "policies & sops": DocumentType.POLICY,
    "policies and sops": DocumentType.POLICY,
    "contracts & agreements": DocumentType.CONTRACT,
    "contracts and agreements": DocumentType.CONTRACT,
    "job descriptions": DocumentType.JD,
    "regulatory & statutory": DocumentType.REGULATORY,
    "regulatory and statutory": DocumentType.REGULATORY,
    "evidence samples": DocumentType.EVIDENCE,
    "audit & risks": DocumentType.AUDIT,
    "audit and risks": DocumentType.AUDIT,
}

CODE_PREFIX_MAP = {
    "-POL-PRO-": DocumentType.POLICY,
    "-POL-": DocumentType.POLICY,
    "-PRO-": DocumentType.POLICY,
    "DRG-JD-": DocumentType.JD,
    "-JD-": DocumentType.JD,
    "-SLA-": DocumentType.CONTRACT,
    "-FM-": DocumentType.FORM,
    "-REF-": DocumentType.REFERENCE,
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
    """
    Classify a document by folder, code prefix, or filename.
    Per DRG-QI-REF-EXRL-01-26 Section 2.
    Priority: folder > code prefix > filename.
    """
    if folder_path:
        folder_lower = folder_path.lower().strip()
        for folder_key, doc_type in FOLDER_TYPE_MAP.items():
            if folder_key in folder_lower:
                logger.debug(f"'{filename}' → {doc_type} (folder: {folder_path})")
                return doc_type

    code_upper = doc_code.upper()
    for prefix, doc_type in CODE_PREFIX_MAP.items():
        if prefix.upper() in code_upper:
            logger.debug(f"'{filename}' → {doc_type} (code prefix)")
            return doc_type

    fname_lower = filename.lower()
    if any(k in fname_lower for k in ["job description", " jd ", "_jd_", "-jd-"]):
        return DocumentType.JD
    if any(k in fname_lower for k in ["contract", "agreement", "nda", "sla"]):
        return DocumentType.CONTRACT
    if any(k in fname_lower for k in ["policy", "procedure", "sop"]):
        return DocumentType.POLICY
    if any(k in fname_lower for k in ["audit", "finding", "risk assessment"]):
        return DocumentType.AUDIT

    logger.warning(
        f"Could not classify '{filename}' (code={doc_code}, folder={folder_path})"
    )
    return DocumentType.UNCLASSIFIED


# =============================================================================
#  Evidence taxonomy shared content (injected into relevant prompts)
# =============================================================================

_EVIDENCE_TYPES = """
Evidence type codes — use EXACTLY one of these per evidence item, no free-text:
LOG=System log export | CFG=Configuration evidence | APR=Signed approval record |
FRM=Completed form/record | TRN=Training record | ACK=Policy acknowledgement |
TST=Test/drill/verification | CRT=Certificate/external attestation |
MTG=Meeting/governance record | REV=Review record | CHK=Checklist completion |
CNT=Contract/agreement | INV=Inventory/register extract | CHG=Change record |
INC=Incident record | RPT=Report/assessment"""

_APPROVED_SYSTEMS = """
Approved source systems — use ONLY these:
Entra ID | Intune | Azure | Azure DevOps | GitHub | SharePoint | Microsoft Teams |
3CX | AAMP | SeamlessHR | QuickBooks | Scanner | Manual/Physical"""

_EVIDENCE_ANTI_PATTERNS = """
REJECT your own output if evidence matches any of these — they are NOT valid evidence:
- Control restatement: 'Continuous monitoring of user activity' → blocked
- Abstract phrase: 'Regular review of access rights' → blocked (no system/format/frequency)
- Vague artefact: 'Evidence of compliance' → blocked (name the specific thing)
- Process description: 'Incidents are reported and investigated' → blocked (describes process not proof)
- Intent statement: 'Ensure all devices are encrypted' → blocked (objective not evidence)
- Missing system: 'Monitoring logs reviewed monthly' → blocked (which system?)
If evidence fails any test above: set evidence_type=null, evidence_undefined=true, explain in evidence_undefined_reason."""

_EVIDENCE_FIELDS_NOTE = """
Every evidence item MUST have ALL these fields populated or it is INVALID:
evidence_type, evidence_description, source_system, evidence_format,
evidence_frequency, evidence_collection_method, evidence_owner_role, evidence_validation_criteria."""


# =============================================================================
#  Prompts by document type
# =============================================================================

_POLICY_PROMPT = f"""You are a GRC extraction specialist. Extract controls from this Dragnet policy/procedure document.

WHAT TO EXTRACT:
- Controls: directive language only — 'shall', 'must', 'is required to', 'will'
- For each control: risk implication, role reference, evidence requirement, ISO/NDPA clause
- Review/recurrence obligations → note for Compliance Calendar

DO NOT EXTRACT:
- Guidance language: 'should', 'may', 'where possible', 'is encouraged to'
- Definitions sections, revision history, purpose/scope, document references
- 'IT is responsible for X' as a control — it is a role assignment, extract the role only
- Controls from other documents referenced here — do not re-extract them

{_EVIDENCE_TYPES}
{_APPROVED_SYSTEMS}
{_EVIDENCE_ANTI_PATTERNS}
{_EVIDENCE_FIELDS_NOTE}

COMPLETENESS: Every control needs risk + evidence. If any missing → DEFICIENT.
CONFIDENCE: Below 0.8 = needs careful review. Below 0.6 = potential false positive.
NEVER fabricate. If unclear, set confidence below 0.6 and explain.

Return ONLY a JSON array, no preamble, no markdown:
[{{"document_type":"Policy","extraction_category":"Extraction","risk_statement":"...","control_statement":"...","control_type":"Preventive|Detective|Corrective|Directive","proposed_owner_role":"...","iso_clause":"...","source_clause":"...","confidence_score":0.0,"completeness_flag":"COMPLETE|DEFICIENT","deficiency_reason":null,"evidence_type":"LOG|CFG|etc|null","evidence_description":"...","source_system":"...","evidence_format":"...","evidence_frequency":"...","evidence_collection_method":"Automated|Triggered|Scheduled|On-demand","evidence_owner_role":"...","evidence_validation_criteria":"...","evidence_undefined":false,"evidence_undefined_reason":null}}]"""

_JD_PROMPT = """You are a GRC specialist performing orphan matching on a Dragnet Job Description.

CRITICAL: JD responsibilities are NOT controls. Do NOT extract controls. Do NOT extract evidence.
JDs define accountability. Controls live in policies.

WHAT TO EXTRACT:
- Role title and any alternate names used
- Department and reporting line
- Each responsibility — classify as POTENTIAL_ORPHAN or ROLE_REFERENCE

POTENTIAL_ORPHAN: responsibility that would typically require a controlling document (policy/procedure).
  Flag as 'JD responsibility — no controlling document found'
ROLE_REFERENCE: administrative accountability that does not require a separate control document

DO NOT EXTRACT: qualifications, experience, skills, compensation, benefits, 'any other duties as assigned'

Return ONLY a JSON array, no preamble, no markdown:
[{"document_type":"JobDescription","extraction_category":"Orphan","orphan_direction":"JD_to_Doc","role_title":"...","department":"...","reports_to":null,"responsibility_statement":"...","orphan_classification":"POTENTIAL_ORPHAN|ROLE_REFERENCE","orphan_reason":"...","source_clause":null,"confidence_score":0.0}]"""

_CONTRACT_PROMPT = f"""You are a GRC extraction specialist processing a Dragnet contract or agreement.

Contract obligations become controls with source_type=Contract.
Extract obligations Dragnet must meet: 'Dragnet shall', 'the provider shall', 'both parties agree to'.

WHAT TO EXTRACT:
- SLA commitments (response times, uptime, resolution windows)
- Data protection clauses (breach timelines → map to NDPA)
- Compliance requirements (certifications required, audit rights)
- Expiry and renewal dates
- Termination triggers

DO NOT EXTRACT: pricing/payments, boilerplate (jurisdiction/severability unless specific obligation),
contact details, preamble and recitals.

{_EVIDENCE_TYPES}
{_APPROVED_SYSTEMS}
{_EVIDENCE_ANTI_PATTERNS}
{_EVIDENCE_FIELDS_NOTE}

Return ONLY a JSON array, no preamble, no markdown:
[{{"document_type":"Contract","extraction_category":"Extraction","source_type":"Contract","obligation_statement":"...","control_type":"Preventive|Detective|Corrective|Directive","proposed_owner_role":"...","counterparty":null,"contract_clause":null,"expiry_date":null,"renewal_date":null,"ndpa_section":null,"confidence_score":0.0,"completeness_flag":"COMPLETE|DEFICIENT","deficiency_reason":null,"evidence_type":"LOG|CFG|etc|null","evidence_description":"...","source_system":"...","evidence_format":"...","evidence_frequency":"...","evidence_collection_method":"Automated|Triggered|Scheduled|On-demand","evidence_owner_role":"...","evidence_validation_criteria":"...","evidence_undefined":false,"evidence_undefined_reason":null}}]"""

_REGULATORY_PROMPT = """You are a GRC specialist processing a regulatory or statutory document for Dragnet Solutions.

Regulatory documents produce Compliance Calendar obligations, NOT controls.

WHAT TO EXTRACT:
- Compliance obligations (what the law requires of Dragnet)
- Reporting requirements with specific deadlines
- Standards references (ISO/NDPA clauses engaged)
- Penalties for non-compliance
- Applicability conditions

DO NOT EXTRACT: full legal text, commentary/interpretation, historical amendments,
obligations that do not apply to Dragnet.

Return ONLY a JSON array, no preamble, no markdown:
[{"document_type":"Regulatory","extraction_category":"Extraction","obligation_statement":"...","authority":"...","deadline":"...","recurrence":"Monthly|Quarterly|Annual|Per occurrence|Once","standards_reference":null,"applies_to_dragnet":true,"penalty_if_missed":null,"source_clause":null,"confidence_score":0.0}]"""

_AUDIT_PROMPT = """You are a GRC specialist processing an audit report or risk assessment for Dragnet Solutions.

Audit documents produce Gap Analysis candidates, NOT controls directly.

WHAT TO EXTRACT:
- Audit findings → severity Critical/Major/Minor, clause reference, remediation required
- Nonconformities (major and minor NCs)
- Corrective actions required — note if they trigger document creation
- Observations/opportunities for improvement → Minor severity
- Risks: SWOT/PESTLE → flag for Strategic Risk Register. Operational → attach to relevant control.
- For each finding: is this an evidence gap (policy exists, evidence missing) or control gap (no policy)?

DO NOT EXTRACT: auditor methodology/credentials, positive findings ('no issues found'),
generic recommendations without specifics.

Return ONLY a JSON array, no preamble, no markdown:
[{"document_type":"Audit","extraction_category":"Extraction","finding_type":"NonConformity|Finding|Observation|Risk","severity":"Critical|Major|Minor","finding_statement":"...","standard_reference":null,"gap_type":"EvidenceGap|ControlGap|ProcessGap|Unknown","remediation_required":"...","triggers_document_lifecycle":false,"is_repeated_finding":false,"source_clause":null,"confidence_score":0.0}]"""

PROMPTS = {
    DocumentType.POLICY: _POLICY_PROMPT,
    DocumentType.JD: _JD_PROMPT,
    DocumentType.CONTRACT: _CONTRACT_PROMPT,
    DocumentType.REGULATORY: _REGULATORY_PROMPT,
    DocumentType.AUDIT: _AUDIT_PROMPT,
}


# =============================================================================
#  Core extraction function
# =============================================================================


def _build_prompt(doc_type: DocumentType, text: str, doc_code: str) -> str:
    """Build the full extraction prompt for the given document type."""
    system = PROMPTS.get(doc_type)
    if not system:
        raise ValueError(f"No prompt for document type: {doc_type}")

    max_chars = 3_000
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
        logger.warning(f"{doc_code}: truncated to {max_chars} chars")

    note = (
        "\n[Document truncated. Extract from visible content only.]"
        if truncated
        else ""
    )

    return (
        f"{system}\n\n"
        f"Document: {doc_code} (Type: {doc_type.value}){note}\n\n"
        f"---BEGIN DOCUMENT---\n{text}\n---END DOCUMENT---\n\n"
        f"Extract now. Return only the JSON array:"
    )


async def run_extraction(
    document_text: str,
    doc_code: str,
    document_type: DocumentType = DocumentType.POLICY,
) -> list[dict]:
    """
    Send document text to Ollama and return parsed extraction results.
    Uses the correct prompt for the document type.
    Non-extraction types (Evidence Samples, Forms, Reference docs) return empty list.
    """
    if document_type in NON_EXTRACTION_TYPES:
        logger.info(
            f"Skipping {doc_code} — {document_type} is not an extraction target"
        )
        return []

    prompt = _build_prompt(document_type, document_text, doc_code)

    logger.info(
        f"Extracting | doc={doc_code} | type={document_type.value} | "
        f"model={settings.ollama_model} | chars={len(document_text)}"
    )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(settings.ollama_timeout, connect=10.0)
    ) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/generate",
            json={
                "model": settings.ollama_model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "top_p": 0.9, "repeat_penalty": 1.1},
            },
        )
        response.raise_for_status()

    raw = response.json().get("response", "")
    return _parse_response(raw, doc_code)


def _parse_response(raw: str, doc_code: str) -> list[dict]:
    """Parse Ollama JSON response, handling common LLM formatting quirks."""
    cleaned = raw.strip()

    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    if cleaned.startswith("{") and '"items"' in cleaned:
        try:
            wrapper = json.loads(cleaned)
            cleaned = json.dumps(wrapper.get("items", wrapper))
        except json.JSONDecodeError:
            pass

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(f"{doc_code}: parse failed: {exc}\nRaw[:500]: {raw[:500]}")
        raise ValueError(
            f"Ollama returned unparseable JSON for {doc_code}. "
            "Check model supports JSON format mode."
        ) from exc

    if isinstance(parsed, dict):
        parsed = [parsed]

    if not isinstance(parsed, list):
        raise ValueError(f"Expected array from Ollama, got {type(parsed).__name__}")

    logger.info(f"{doc_code}: {len(parsed)} items parsed")
    return parsed


async def check_ollama_connectivity() -> dict:
    """Check Ollama is running and the configured model is available."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return {
                "status": "ok",
                "model": settings.ollama_model,
                "model_available": any(settings.ollama_model in m for m in models),
                "available_models": models,
            }
    except httpx.ConnectError:
        return {
            "status": "error",
            "detail": f"Cannot connect to Ollama at {settings.ollama_base_url}. Run: ollama serve",
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}
