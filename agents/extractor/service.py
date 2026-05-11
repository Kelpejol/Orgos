# =============================================================================
# agents/extractor/service.py — Extractor agent orchestration
# Updated for multi-type extraction per DRG-QI-REF-EXRL-01-26.
# Reads documents, classifies them, routes to correct extraction pipeline,
# writes results to AI Review Queue staging list.
# Depends on: agents/extractor/ollama_client.py, agents/extractor/schemas.py,
#             graph/client.py, config.py
# =============================================================================

import io
import logging
from typing import Optional

from pydantic import ValidationError

from agents.extractor.ollama_client import (
    DocumentType,
    NON_EXTRACTION_TYPES,
    classify_document,
    run_extraction,
)
from agents.extractor.schemas import (
    CompletenessFlag,
    ExtractionItem,
    ExtractionResponse,
    ItemDocumentType,
    OrphanItem,
    RegulatoryItem,
    AuditItem,
)
from config import settings

logger = logging.getLogger(__name__)

# AI Review Queue staging list — populated from config after Tier 2 lists created
def _get_queue_list_id() -> str:
    return settings.ai_review_queue_list_id

_QUEUE_LIST_NAME = "AI Review Queue"


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from a PDF using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages.append(f"[Page {i+1}]\n{text}")
        if not pages:
            raise ValueError(
                "PDF contains no extractable text. "
                "It may be a scanned image — OCR not yet implemented."
            )
        full = "\n\n".join(pages)
        logger.info(f"PDF: extracted {len(full)} chars from {len(reader.pages)} pages")
        return full
    except ImportError as exc:
        raise RuntimeError("pypdf not installed. Run: pip install pypdf") from exc


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from a DOCX using python-docx."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full = "\n".join(paragraphs)
        logger.info(f"DOCX: extracted {len(full)} chars")
        return full
    except ImportError as exc:
        raise RuntimeError("python-docx not installed. Run: pip install python-docx") from exc


def _validate_items(raw_items: list[dict], doc_type: DocumentType, doc_code: str) -> list[dict]:
    """
    Validate raw extraction items against the correct schema for the document type.
    Invalid items are logged and skipped — never crash the whole extraction.
    Returns list of validated dicts (re-serialised from Pydantic for consistency).
    """
    valid = []
    schema_map = {
        DocumentType.POLICY:     ExtractionItem,
        DocumentType.CONTRACT:   ExtractionItem,
        DocumentType.JD:         OrphanItem,
        DocumentType.REGULATORY: RegulatoryItem,
        DocumentType.AUDIT:      AuditItem,
    }
    schema = schema_map.get(doc_type)

    for i, raw in enumerate(raw_items):
        # Always set document_type and extraction_category if missing
        raw.setdefault("document_type", doc_type.value)
        raw.setdefault("extraction_category", "Extraction")
        raw.setdefault("confidence_score", 0.5)

        if schema is None:
            valid.append(raw)
            continue

        try:
            item = schema.model_validate(raw)
            valid.append(item.model_dump())
        except ValidationError as exc:
            logger.warning(f"{doc_code} item {i} validation failed — kept as raw: {exc}")
            valid.append(raw)  # Keep raw rather than drop — human reviews it

    return valid


async def _write_to_queue(
    items: list[dict],
    doc_code: str,
    doc_type: DocumentType,
) -> int:
    """
    Write extraction items to the AI Review Queue staging list in SharePoint.
    Returns number successfully written.
    """
    from graph.client import create_list_item
    from graph.exceptions import SharePointListNotConfiguredError

    list_id = _get_queue_list_id()
    if not settings.is_list_configured(list_id):
        logger.warning(
            "AI Review Queue list not configured — "
            "set AI_REVIEW_QUEUE_LIST_ID in .env after creating the list."
        )
        return 0

    written = 0
    for item in items:
        try:
            title = (
                item.get("control_statement")
                or item.get("responsibility_statement")
                or item.get("finding_statement")
                or item.get("obligation_statement")
                or "Untitled item"
            )
            fields = {
                "Title":              title[:255],
                "ItemType":           item.get("extraction_category", "Extraction"),
                "DocumentType":       item.get("document_type", doc_type.value),
                "SourceDocumentCode": doc_code,
                "SourceClause":       item.get("source_clause", "") or "",
                "ConfidenceScore":    item.get("confidence_score", 0.0),
                "ReviewStatus":       "Pending Review",
            }

            # Control fields
            if item.get("control_statement"):
                fields.update({
                    "ControlStatement":  item.get("control_statement", ""),
                    "RiskStatement":     item.get("risk_statement", ""),
                    "ControlType":       item.get("control_type", ""),
                    "ProposedOwnerRole": item.get("proposed_owner_role", ""),
                    "ISOClause":         item.get("iso_clause", ""),
                    "SourceType":        item.get("source_type", "Policy"),
                    "CompletenessFlag":  item.get("completeness_flag", "DEFICIENT"),
                })
                if item.get("deficiency_reason"):
                    fields["DeficiencyReason"] = item["deficiency_reason"]
                if item.get("evidence_type"):
                    fields["EvidenceType"] = item["evidence_type"]
                if item.get("evidence_description"):
                    fields["EvidenceDescription"] = item["evidence_description"][:500]
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
                    fields["EvidenceValidationCriteria"] = item["evidence_validation_criteria"][:500]
                if item.get("evidence_undefined"):
                    fields["EvidenceUndefined"] = True
                if item.get("evidence_undefined_reason"):
                    fields["EvidenceUndefinedReason"] = item["evidence_undefined_reason"]

            # Orphan fields
            if item.get("responsibility_statement"):
                fields.update({
                    "OrphanDirection":        item.get("orphan_direction", "JD_to_Doc"),
                    "ResponsibilityStatement":item.get("responsibility_statement", "")[:500],
                    "OrphanClassification":   item.get("orphan_classification", ""),
                    "OrphanReason":           item.get("orphan_reason", "")[:500],
                })

            # Regulatory fields
            if item.get("obligation_statement") and doc_type == DocumentType.REGULATORY:
                fields.update({
                    "Authority":            item.get("authority", ""),
                    "ObligationDeadline":   item.get("deadline", ""),
                    "ObligationRecurrence": item.get("recurrence", ""),
                })
                if item.get("standards_reference"):
                    fields["StandardReference"] = item["standards_reference"]

            # Audit fields
            if item.get("finding_statement"):
                fields.update({
                    "FindingType":              item.get("finding_type", "Finding"),
                    "Severity":                 item.get("severity", "Minor"),
                    "GapType":                  item.get("gap_type", "Unknown"),
                    "RemediationRequired":      item.get("remediation_required", "")[:500],
                    "TriggersDocumentLifecycle":item.get("triggers_document_lifecycle", False),
                    "IsRepeatedFinding":        item.get("is_repeated_finding", False),
                })
                if item.get("standard_reference"):
                    fields["StandardReference"] = item["standard_reference"]

            await create_list_item(list_id, _QUEUE_LIST_NAME, fields)
            written += 1

        except Exception as exc:
            logger.error(f"Failed to write queue item: {exc}")

    logger.info(f"Wrote {written}/{len(items)} items to AI Review Queue for {doc_code}")
    return written


async def run_extraction_from_text(
    text: str,
    doc_code: str,
    write_to_sharepoint: bool = False,
    folder_path: Optional[str] = None,
    document_type_override: Optional[str] = None,
) -> ExtractionResponse:
    """
    Full extraction pipeline for plain text input.
    Classifies document type, runs correct extraction, optionally writes to queue.
    """
    # Determine document type
    if document_type_override:
        try:
            doc_type = DocumentType(document_type_override)
        except ValueError:
            doc_type = classify_document("", doc_code, folder_path)
    else:
        doc_type = classify_document("", doc_code, folder_path)

    logger.info(f"Extraction starting: {doc_code} | type={doc_type.value} | chars={len(text)}")

    # Skip non-extraction targets
    if doc_type in NON_EXTRACTION_TYPES:
        return ExtractionResponse(
            source_document_code=doc_code,
            document_type=doc_type.value,
            total_extracted=0,
            complete_count=0,
            deficient_count=0,
            written_to_sharepoint=False,
            skipped_reason=f"Document type '{doc_type.value}' is not an extraction target",
            items=[],
        )

    raw_items = await run_extraction(text, doc_code, doc_type)
    items = _validate_items(raw_items, doc_type, doc_code)

    # Count complete vs deficient (only applies to policy/contract items)
    complete = sum(
        1 for i in items
        if i.get("completeness_flag") == "COMPLETE"
    )
    deficient = sum(
        1 for i in items
        if i.get("completeness_flag") == "DEFICIENT"
    )

    written = 0
    if write_to_sharepoint and items:
        written = await _write_to_queue(items, doc_code, doc_type)

    return ExtractionResponse(
        source_document_code=doc_code,
        document_type=doc_type.value,
        total_extracted=len(items),
        complete_count=complete,
        deficient_count=deficient,
        written_to_sharepoint=written > 0,
        items=items,
    )


async def run_extraction_from_file(
    file_bytes: bytes,
    filename: str,
    doc_code: str,
    write_to_sharepoint: bool = False,
    folder_path: Optional[str] = None,
) -> ExtractionResponse:
    """
    Full extraction pipeline for uploaded file.
    Supports PDF, DOCX, TXT.
    """
    fname_lower = filename.lower()
    if fname_lower.endswith(".pdf"):
        text = extract_text_from_pdf(file_bytes)
    elif fname_lower.endswith(".docx"):
        text = extract_text_from_docx(file_bytes)
    elif fname_lower.endswith(".txt"):
        text = file_bytes.decode("utf-8", errors="replace")
    else:
        raise ValueError(
            f"Unsupported file type: {filename}. Supported: PDF, DOCX, TXT."
        )

    return await run_extraction_from_text(
        text, doc_code, write_to_sharepoint, folder_path
    )