# =============================================================================
# agents/extractor/service.py
# Handles post-processing of raw model output:
#   - Normalises the short-key format from ollama_client
#   - Assigns ControlType using keyword rules (not the model)
#   - Assigns EvidenceType using keyword rules where possible
#   - Detects and flags incomplete fragments
#   - Detects and rejects non-controls (scope statements, definitions)
#   - Forces correct boolean values
#   - Writes to SharePoint AI Review Queue
# =============================================================================

import io
import logging
import os
import re
import tempfile
from typing import Optional

from agents.extractor.ollama_client import (
    DocumentType,
    NON_EXTRACTION_TYPES,
    classify_document,
    run_extraction,
)
from agents.extractor.schemas import ExtractionResponse
from config import settings

logger = logging.getLogger(__name__)


def _get_queue_list_id() -> str:
    return settings.ai_review_queue_list_id

_QUEUE_LIST_NAME = "AI Review Queue"


# =============================================================================
#  Text extraction from files
# =============================================================================

# Minimum character count from native extraction before trying Azure OCR
_OCR_THRESHOLD = 100

# Helper to collapse excessive whitespace after any extraction method
_clean_text = lambda t: re.sub(r' {4,}', '  ', re.sub(r'[\r\n]{3,}', '\n\n', t.strip()))


async def _azure_ocr_fallback(file_bytes: bytes, content_type: str) -> str:
    """
    Azure Document Intelligence prebuilt-read model OCR fallback.
    Used when native extraction yields fewer than _OCR_THRESHOLD characters
    (scanned PDFs, image-only DOCXs). Not called for legacy .doc — Azure
    Document Intelligence does not support the .doc binary format.
    """
    try:
        from azure.ai.formrecognizer.aio import DocumentAnalysisClient
        from azure.core.credentials import AzureKeyCredential
    except ImportError as exc:
        raise RuntimeError(
            "azure-ai-formrecognizer not installed. Run: pip install azure-ai-formrecognizer"
        ) from exc

    endpoint = settings.azure_document_intelligence_endpoint
    key = settings.azure_document_intelligence_key
    if not endpoint or not key:
        raise RuntimeError(
            "Azure Document Intelligence not configured — "
            "set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY"
        )

    async with DocumentAnalysisClient(endpoint, AzureKeyCredential(key)) as client:
        poller = await client.begin_analyze_document(
            "prebuilt-read",
            file_bytes,
            content_type=content_type,
        )
        result = await poller.result()

    pages = []
    for page in result.pages:
        if page.lines:
            page_text = " ".join(line.content for line in page.lines)
            pages.append(f"[Page {page.page_number}]\n{page_text}")
    return "\n\n".join(pages)


async def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract text from a PDF.
    1. Try native pypdf extraction.
    2. If result is below _OCR_THRESHOLD chars, call Azure Document Intelligence.
    3. Return whichever result is longer. Log but do not raise on empty result.
    """
    native_text = ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages.append(f"[Page {i+1}]\n{text}")
        native_text = _clean_text("\n\n".join(pages))
        logger.info(f"PDF: native extraction yielded {len(native_text)} chars")
    except ImportError as exc:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf") from exc
    except Exception as exc:
        logger.warning(f"PDF: native extraction failed: {exc}")

    if len(native_text) < _OCR_THRESHOLD:
        logger.info(
            f"PDF: {len(native_text)} chars below threshold ({_OCR_THRESHOLD}) — trying Azure OCR"
        )
        try:
            ocr_text = await _azure_ocr_fallback(file_bytes, "application/pdf")
            logger.info(f"PDF: Azure OCR yielded {len(ocr_text)} chars")
            if len(ocr_text) > len(native_text):
                return ocr_text
        except Exception as exc:
            logger.warning(f"PDF: Azure OCR failed: {exc}")

    if not native_text:
        logger.error("PDF: all extraction methods yielded empty text")
    return native_text


async def extract_text_from_docx(file_bytes: bytes) -> str:
    """
    Extract text from a .docx file.
    1. Try native mammoth extraction.
    2. If result is below _OCR_THRESHOLD chars, call Azure Document Intelligence.
    3. Return whichever result is longer. Log but do not raise on empty result.
    """
    native_text = ""
    try:
        import mammoth
        result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
        native_text = _clean_text(result.value or "")
        logger.info(f"DOCX: native extraction yielded {len(native_text)} chars")
    except ImportError as exc:
        raise RuntimeError("mammoth not installed. Run: pip install mammoth") from exc
    except Exception as exc:
        logger.warning(f"DOCX: native extraction failed: {exc}")

    if len(native_text) < _OCR_THRESHOLD:
        logger.info(
            f"DOCX: {len(native_text)} chars below threshold ({_OCR_THRESHOLD}) — trying Azure OCR"
        )
        _DOCX_CONTENT_TYPE = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        try:
            ocr_text = await _azure_ocr_fallback(file_bytes, _DOCX_CONTENT_TYPE)
            logger.info(f"DOCX: Azure OCR yielded {len(ocr_text)} chars")
            if len(ocr_text) > len(native_text):
                return ocr_text
        except Exception as exc:
            logger.warning(f"DOCX: Azure OCR failed: {exc}")

    if not native_text:
        logger.error("DOCX: all extraction methods yielded empty text")
    return native_text


def extract_text_from_doc(file_bytes: bytes) -> str:
    """
    Extract text from a legacy .doc file (Word 97-2003 binary format).
    Two paths — no Azure OCR fallback (Azure DI does not support .doc):
      - RTF path: file starts with {\\rtf → use striprtf
      - OLE2 path: parse WordDocument stream via olefile
    Log but do not raise on empty result.
    """
    # RTF path — some .doc files are stored as RTF
    if file_bytes[:5] == b'{\\rtf':
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError as exc:
            raise RuntimeError(
                "striprtf not installed. Run: pip install striprtf"
            ) from exc
        try:
            rtf_str = file_bytes.decode('latin-1', errors='ignore')
            text = _clean_text(rtf_to_text(rtf_str))
            logger.info(f"DOC (RTF): {len(text)} chars extracted")
            if not text:
                logger.error("DOC (RTF): extraction yielded empty text")
            return text
        except Exception as exc:
            logger.warning(f"DOC (RTF): striprtf failed: {exc} — falling through to OLE2")

    # OLE2 binary path
    try:
        import olefile
    except ImportError as exc:
        raise RuntimeError(
            "olefile not installed. Run: pip install olefile"
        ) from exc

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix='.doc', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        ole = olefile.OleFileIO(tmp_path)

        if not ole.exists('WordDocument'):
            logger.error("DOC: OLE2 file has no WordDocument stream")
            ole.close()
            return ""

        raw = ole.openstream('WordDocument').read()
        ole.close()

        # Word binary stores Unicode text as UTF-16-LE; decode and strip control bytes
        decoded = raw.decode('utf-16-le', errors='ignore')
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', decoded)
        text = _clean_text(text)

        # Sanity: if under 40% printable chars the UTF-16 decode gave mostly garbage;
        # fall back to pulling ASCII strings (the "strings" tool approach)
        printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
        if not text or printable / max(len(text), 1) < 0.4:
            ascii_parts = re.findall(rb'[\x20-\x7e]{4,}', raw)
            text = _clean_text(
                ' '.join(p.decode('ascii', errors='ignore') for p in ascii_parts)
            )

        logger.info(f"DOC (OLE2): {len(text)} chars extracted")
        if not text:
            logger.error("DOC: OLE2 extraction yielded empty text")
        return text

    except Exception as exc:
        logger.error(f"DOC: extraction failed: {exc}")
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# =============================================================================
#  ControlType assignment — keyword rules
# Better than asking a small model to classify
# =============================================================================

_PREVENTIVE_KEYWORDS = [
    "encrypt", "password", "mfa", "multi-factor", "access control", "restrict",
    "block", "prevent", "prior approval", "before they are", "must not",
    "shall not", "prohibited", "firewall", "backup", "approved before",
    "authorised before", "locked", "segregation", "separation of duties",
    "cannot be", "not permitted", "only authorised",
]

_DETECTIVE_KEYWORDS = [
    "review", "audit", "monitor", "log", "inspect", "quarterly", "annually",
    "monthly", "check", "verify", "assess", "evaluate", "report on",
    "track", "record", "surveillance", "detect", "investigate",
    "scan", "test", "penetration", "vulnerability assessment",
]

_CORRECTIVE_KEYWORDS = [
    "remediate", "correct", "fix", "resolve", "incident response",
    "corrective action", "root cause", "restore", "recover", "rollback",
    "patch", "update to fix", "address the",
]

def _assign_control_type(statement: str) -> str:
    """
    Assign ControlType based on keyword matching.
    More reliable than asking a small model to classify.
    Priority: Preventive > Detective > Corrective > Directive
    """
    s = statement.lower()
    if any(k in s for k in _PREVENTIVE_KEYWORDS):
        return "Preventive"
    if any(k in s for k in _DETECTIVE_KEYWORDS):
        return "Detective"
    if any(k in s for k in _CORRECTIVE_KEYWORDS):
        return "Corrective"
    return "Directive"


# =============================================================================
#  EvidenceType suggestion — keyword rules
# =============================================================================

_EVD_KEYWORDS = {
    "TRN": ["training", "awareness", "induction", "onboarding course", "workshop"],
    "REV": ["review", "quarterly review", "annual review", "access review", "assessment"],
    "APR": ["approved", "signed off", "authorisation", "sign-off", "approved by"],
    "LOG": ["log", "audit log", "system log", "event log", "activity log"],
    "CFG": ["configuration", "setting", "system configuration", "config", "screenshot"],
    "INC": ["incident", "breach", "security event", "reported incident"],
    "TST": ["test", "drill", "penetration test", "vulnerability scan", "simulation"],
    "CHG": ["change", "change request", "change management", "change record"],
    "FRM": ["form", "record", "completed form", "survey", "questionnaire"],
    "RPT": ["report", "monthly report", "quarterly report", "status report"],
    "ACK": ["acknowledgement", "acknowledged", "read and understood", "signed policy"],
    "MTG": ["meeting", "committee", "board meeting", "governance meeting"],
    "INV": ["inventory", "asset register", "register of"],
    "CRT": ["certificate", "certification", "external attestation", "accreditation"],
}

def _suggest_evidence_type(statement: str) -> Optional[str]:
    """
    Suggest an evidence type based on control statement keywords.
    Returns None if no confident match found.
    """
    s = statement.lower()
    for code, keywords in _EVD_KEYWORDS.items():
        if any(k in s for k in keywords):
            return code
    return None


# =============================================================================
#  Non-control detection
# =============================================================================

_SCOPE_PATTERNS = [
    r"^this (policy|procedure|document) (applies|covers|governs|sets out)",
    r"^the (purpose|objective|aim|goal) of",
    r"^this (section|clause) (describes|outlines|provides)",
    r"^(for the purpose|in the context|as used in) (of|this)",
    r"^definitions?:",
    r"^introduction",
    r"^background",
    r"foundational competency map",
    r"^revision history",
    r"^document (owner|version|code|title)",
    r"serves as the baseline for",
]

_SCOPE_RE = [re.compile(p, re.IGNORECASE) for p in _SCOPE_PATTERNS]


def _is_non_control(statement: str) -> bool:
    """Returns True if the statement is a scope/definition/intro, not a control."""
    s = statement.strip()
    for pattern in _SCOPE_RE:
        if pattern.search(s):
            return True
    # Reject very short statements
    if len(s) < 20:
        return True
    return False


def _is_fragment(statement: str) -> bool:
    """
    Returns True if the control statement is a fragment —
    starts with a verb/modal without a named subject.
    Fragments start with: shall, must, will, is required, are required
    """
    s = statement.strip()
    fragment_starts = (
        "shall ", "must ", "will ", "is required ", "are required ",
        "should ", "may ", "would "
    )
    return any(s.lower().startswith(f) for f in fragment_starts)


# =============================================================================
#  Main validation and enrichment
# =============================================================================

def _validate_items(
    raw_items: list[dict],
    doc_type: DocumentType,
    doc_code: str,
) -> list[dict]:
    """
    Takes raw model output (normalised short-key format from ollama_client)
    and produces clean, enriched items ready to write to SharePoint.

    Steps:
      1. Reject non-controls (scope, definitions)
      2. Flag and skip fragments where subject cannot be recovered
      3. Assign ControlType using keyword rules
      4. Suggest EvidenceType where possible
      5. Force correct boolean values
      6. Build the final field set
    """
    result = []

    for raw in raw_items:
        # Raw items from ollama_client are normalised to:
        # {"statement": ..., "risk": ..., "role": ..., "clause": ...}
        # But they may also arrive in the old full-key format.
        stmt   = (raw.get("statement") or raw.get("control_statement") or
                  raw.get("responsibility_statement") or "").strip()
        risk   = (raw.get("risk")   or raw.get("risk_statement")      or "").strip()
        role   = (raw.get("role")   or raw.get("proposed_owner_role") or "").strip()
        clause = (raw.get("clause") or raw.get("iso_clause")          or "").strip()

        if not stmt or len(stmt) < 15:
            logger.debug(f"{doc_code}: skipped empty item")
            continue

        # Reject scope statements and definitions
        if _is_non_control(stmt):
            logger.debug(f"{doc_code}: rejected non-control: {stmt[:60]}")
            continue

        # Flag fragments — low confidence, flag as deficient
        fragment = _is_fragment(stmt)
        if fragment:
            confidence = 0.4
            completeness = "DEFICIENT"
            deficiency = "Fragment — subject missing from extracted sentence. Review source document."
        else:
            confidence = float(raw.get("confidence_score", 0.75))
            if confidence == 0:
                confidence = 0.75
            completeness = "COMPLETE"
            deficiency = None

        # Assign ControlType using keyword rules
        control_type = _assign_control_type(stmt)

        # Suggest EvidenceType using keyword rules
        suggested_evd = _suggest_evidence_type(stmt)

        # Build enriched item
        item: dict = {
            # Core identification
            "extraction_category": "Extraction" if doc_type != DocumentType.JD else "Orphan",
            "document_type":       doc_type.value,
            "confidence_score":    confidence,
            "completeness_flag":   completeness if suggested_evd else "DEFICIENT",
            "deficiency_reason":   deficiency or (None if suggested_evd else "Evidence type could not be determined — requires reviewer selection"),

            # Control fields
            "control_statement":   stmt,
            "control_type":        control_type,
            "risk_statement":      risk[:500] if risk else "",
            "proposed_owner_role": role[:200] if role else "",
            "iso_clause":          clause if clause else "",
            "source_type":         doc_type.value,

            # Evidence
            "evidence_type":              suggested_evd or "",
            "evidence_undefined":         suggested_evd is None,
            "evidence_undefined_reason":  None if suggested_evd else "Evidence type requires reviewer input — use Edit & Accept to specify.",

            # Booleans — always false for Policy/Contract/Regulatory
            # Only meaningful for Audit items
            "triggers_document_lifecycle": False,
            "is_repeated_finding":         False,
        }

        # For JD items, map to orphan fields instead
        if doc_type == DocumentType.JD:
            item["responsibility_statement"] = stmt
            item["orphan_direction"]         = "JD_to_Doc"
            item["orphan_classification"]    = "POTENTIAL_ORPHAN"
            item["orphan_reason"]            = risk or "JD responsibility may require a governing policy document."

        # For Audit items, restore the boolean fields
        if doc_type == DocumentType.AUDIT:
            item["finding_statement"]           = stmt
            item["finding_type"]               = "Finding"
            item["severity"]                   = raw.get("o", "Minor") if raw.get("o") in ("Critical", "Major", "Minor") else "Minor"
            item["gap_type"]                   = "Unknown"
            item["remediation_required"]       = risk[:500]
            item["triggers_document_lifecycle"] = False
            item["is_repeated_finding"]        = False

        result.append(item)

    logger.info(
        f"{doc_code}: {len(result)} items validated "
        f"({len(raw_items) - len(result)} rejected as non-controls)"
    )
    return result


# =============================================================================
#  Write to AI Review Queue
# =============================================================================

async def _write_to_queue(
    items: list[dict],
    doc_code: str,
    doc_type: DocumentType,
    web_url: str = "",
) -> int:
    from graph.client import create_list_item

    list_id = _get_queue_list_id()
    if not settings.is_list_configured(list_id):
        logger.warning("AI Review Queue list not configured")
        return 0

    VALID_ITEM_TYPES = {"Extraction", "Orphan", "Harmonisation"}
    written = 0

    for item in items:
        try:
            stmt = (
                item.get("control_statement")
                or item.get("responsibility_statement")
                or item.get("finding_statement")
                or item.get("obligation_statement")
                or "Untitled"
            )

            cat = item.get("extraction_category", "Extraction")
            if cat not in VALID_ITEM_TYPES:
                cat = "Orphan" if doc_type == DocumentType.JD else "Extraction"

            fields: dict = {
                "Title":              stmt[:255],
                "ItemType":           cat,
                "DocumentType":       item.get("document_type", doc_type.value),
                "SourceDocumentCode": doc_code,
                "SourceClause":       item.get("source_clause", "") or "",
                "ConfidenceScore":    item.get("confidence_score", 0.0),
                "ReviewStatus":       "Pending Review",
                "SourceType":         item.get("source_type", doc_type.value),
            }

            if web_url:
                fields["SourceDocumentUrl"] = web_url

            # Control fields
            def _s(v, limit=None):
                return (str(v)[:limit] if limit else str(v)) if v else None

            for k, v in {
                "ControlStatement":   _s(item.get("control_statement")),
                "RiskStatement":      _s(item.get("risk_statement"), 500),
                "ControlType":        item.get("control_type"),
                "ProposedOwnerRole":  _s(item.get("proposed_owner_role"), 255),
                "ISOClause":          item.get("iso_clause"),
                "CompletenessFlag":   item.get("completeness_flag"),
                "DeficiencyReason":   _s(item.get("deficiency_reason"), 500),
            }.items():
                if v:
                    fields[k] = v

            # Evidence fields
            if item.get("evidence_type"):
                fields["EvidenceType"] = item["evidence_type"]
            if item.get("evidence_description"):
                fields["EvidenceDescription"] = str(item["evidence_description"])[:500]
            if item.get("source_system"):
                fields["EvidenceSourceSystem"] = item["source_system"]
            if item.get("evidence_format"):
                fields["EvidenceFormat"] = item["evidence_format"]
            if item.get("evidence_frequency"):
                fields["EvidenceFrequency"] = item["evidence_frequency"]
            if item.get("evidence_collection_method"):
                fields["EvidenceCollectionMethod"] = item["evidence_collection_method"]
            if item.get("evidence_owner_role"):
                fields["EvidenceOwnerRole"] = item["evidence_owner_role"]
            if item.get("evidence_validation_criteria"):
                fields["EvidenceValidationCriteria"] = str(item["evidence_validation_criteria"])[:500]

            evidence_present = any(
                item.get(key)
                for key in [
                    "evidence_type",
                    "evidence_description",
                    "source_system",
                    "evidence_format",
                    "evidence_frequency",
                    "evidence_collection_method",
                    "evidence_owner_role",
                    "evidence_validation_criteria",
                ]
            )
            evidence_undefined = item.get("evidence_undefined")
            if evidence_undefined is None:
                evidence_undefined = not evidence_present
            fields["EvidenceUndefined"] = bool(evidence_undefined)
            if item.get("evidence_undefined_reason"):
                fields["EvidenceUndefinedReason"] = item["evidence_undefined_reason"]

            # Orphan fields
            if item.get("responsibility_statement"):
                fields.update({
                    "OrphanDirection":         item.get("orphan_direction", "JD_to_Doc"),
                    "ResponsibilityStatement": str(item.get("responsibility_statement", ""))[:500],
                    "OrphanClassification":    item.get("orphan_classification", "POTENTIAL_ORPHAN"),
                    "OrphanReason":            str(item.get("orphan_reason", ""))[:500],
                })

            # Audit fields
            if item.get("finding_statement"):
                fields.update({
                    "FindingType":               item.get("finding_type", "Finding"),
                    "Severity":                  item.get("severity", "Minor"),
                    "GapType":                   item.get("gap_type", "Unknown"),
                    "RemediationRequired":        str(item.get("remediation_required", ""))[:500],
                    "TriggersDocumentLifecycle":  False,
                    "IsRepeatedFinding":          False,
                })

            await create_list_item(list_id, _QUEUE_LIST_NAME, fields)
            written += 1

        except Exception as exc:
            logger.error(f"Failed to write queue item: {exc}")

    logger.info(f"Wrote {written}/{len(items)} items for {doc_code}")
    return written


# =============================================================================
#  Public API
# =============================================================================

_PROCEDURAL_DOC_TYPES = {DocumentType.POLICY}


async def _run_procedural_extraction(
    text: str,
    doc_code: str,
    doc_type: DocumentType,
    write_to_sharepoint: bool,
    web_url: str,
) -> int:
    """
    Extract procedural steps from a Policy document and index them.
    Returns count of steps written. Fires after the control extraction path.
    Always fails soft — never raises, never blocks the control extraction response.
    """
    if doc_type not in _PROCEDURAL_DOC_TYPES:
        return 0

    try:
        from agents.extractor.ollama_client import extract_procedural_steps
        from agents.nl_search.procedures_service import write_procedural_steps
        from agents.nl_search.vector_store import (
            delete_procedural_steps_by_document,
            embed_and_store_procedural_step,
        )

        steps = await extract_procedural_steps(text, doc_code)
        if not steps:
            logger.info(f"{doc_code}: no procedural steps extracted")
            return 0

        # Remove stale index entries before re-indexing
        await delete_procedural_steps_by_document(doc_code)

        steps_indexed = 0
        if write_to_sharepoint:
            written = await write_procedural_steps(steps, doc_code, doc_link=web_url)
            # write_procedural_steps attaches "sp_item_id" to each step dict
            for step in steps:
                step_id = step.get("sp_item_id") or f"{doc_code}-step-{step.get('step_number', 0)}"
                metadata = {
                    "document_code":  doc_code,
                    "document_title": step.get("document_title", doc_code),
                    "process_name":   step.get("process_name", ""),
                    "step_number":    str(step.get("step_number", 0)),
                    "section_ref":    step.get("section_ref", ""),
                    "roles_involved": step.get("roles_involved", ""),
                    "forms_referenced": step.get("forms_referenced", ""),
                }
                ok = await embed_and_store_procedural_step(
                    step_id, step["step_text"], metadata
                )
                if ok:
                    steps_indexed += 1
            logger.info(
                f"{doc_code}: {written} procedural steps written to SharePoint, "
                f"{steps_indexed} embedded"
            )
        else:
            # Not writing to SharePoint — still embed using a synthetic ID
            for step in steps:
                step_id = f"{doc_code}-step-{step.get('step_number', 0)}"
                metadata = {
                    "document_code": doc_code,
                    "process_name":  step.get("process_name", ""),
                    "step_number":   str(step.get("step_number", 0)),
                }
                ok = await embed_and_store_procedural_step(
                    step_id, step["step_text"], metadata
                )
                if ok:
                    steps_indexed += 1

        return steps_indexed

    except Exception as exc:
        logger.warning(f"{doc_code}: procedural extraction failed (non-fatal): {exc}")
        return 0


async def run_extraction_from_text(
    text: str,
    doc_code: str,
    write_to_sharepoint: bool = False,
    folder_path: Optional[str] = None,
    document_type_override: Optional[str] = None,
    web_url: str = "",
) -> ExtractionResponse:
    if document_type_override:
        try:
            doc_type = DocumentType(document_type_override)
        except ValueError:
            doc_type = classify_document("", doc_code, folder_path)
    else:
        doc_type = classify_document("", doc_code, folder_path)

    logger.info(f"Extraction: {doc_code} | {doc_type.value} | {len(text)} chars")

    if doc_type in NON_EXTRACTION_TYPES:
        return ExtractionResponse(
            source_document_code=doc_code,
            document_type=doc_type.value,
            total_extracted=0,
            complete_count=0,
            deficient_count=0,
            written_to_sharepoint=False,
            skipped_reason=f"Type '{doc_type.value}' is not an extraction target",
            items=[],
            procedural_steps_indexed=0,
        )

    raw_items = await run_extraction(text, doc_code, doc_type)
    items     = _validate_items(raw_items, doc_type, doc_code)

    complete  = sum(1 for i in items if i.get("completeness_flag") == "COMPLETE")
    deficient = sum(1 for i in items if i.get("completeness_flag") == "DEFICIENT")

    written = 0
    if write_to_sharepoint and items:
        written = await _write_to_queue(items, doc_code, doc_type, web_url=web_url)
        if written:
            try:
                from agents.classifier.service import run_classifier
                await run_classifier(triggered_by=f"system: extraction {doc_code}")
            except Exception as exc:
                logger.warning(f"Automatic classifier run after extraction failed for {doc_code}: {exc}")

    # Second output stream: procedural steps (Policy documents only, non-blocking)
    steps_indexed = await _run_procedural_extraction(
        text, doc_code, doc_type, write_to_sharepoint, web_url
    )

    return ExtractionResponse(
        source_document_code=doc_code,
        document_type=doc_type.value,
        total_extracted=len(items),
        complete_count=complete,
        deficient_count=deficient,
        written_to_sharepoint=written > 0,
        items=items,
        procedural_steps_indexed=steps_indexed,
    )


async def run_extraction_from_file(
    file_bytes: bytes,
    filename: str,
    doc_code: str,
    write_to_sharepoint: bool = False,
    folder_path: Optional[str] = None,
    web_url: str = "",
    document_type_override: Optional[str] = None,
) -> ExtractionResponse:
    fname = filename.lower()
    if fname.endswith(".pdf"):
        text = await extract_text_from_pdf(file_bytes)
    elif fname.endswith(".docx"):
        text = await extract_text_from_docx(file_bytes)
    elif fname.endswith(".doc"):
        text = extract_text_from_doc(file_bytes)
    elif fname.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(f"Unsupported file type: {filename}")

    return await run_extraction_from_text(
        text,
        doc_code,
        write_to_sharepoint,
        folder_path,
        document_type_override=document_type_override,
        web_url=web_url,
    )
