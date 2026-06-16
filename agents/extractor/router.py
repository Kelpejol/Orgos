# =============================================================================
# agents/extractor/router.py — Extractor agent FastAPI routes
# Phase 3: Real implementation — not a POC.
# POST /api/v1/agents/extract/text  — raw text input
# POST /api/v1/agents/extract/file  — PDF or DOCX file upload
# GET  /api/v1/agents/health/ollama — Ollama connectivity check
# Depends on: agents/extractor/service.py, agents/extractor/schemas.py,
#             agents/extractor/ollama_client.py, auth/validator.py
# =============================================================================

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from agents.extractor import schemas
from agents.extractor import service
from agents.extractor.ollama_client import check_ollama_connectivity
from auth.validator import CurrentUser, get_current_user, require_compliance_lead

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Agents — Extractor"])

# Max file size: 10MB (most policy documents are well under this)
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@router.post(
    "/extract/text",
    response_model=schemas.ExtractionResponse,
    summary="Extract controls from raw document text",
)
async def extract_from_text(
    request: schemas.ExtractionRequest,
    user: CurrentUser = Depends(require_compliance_lead),
) -> schemas.ExtractionResponse:
    """
    Submit raw document text for GRC extraction.

    The Extractor agent:
    1. Sends the text to the local Ollama LLM
    2. Receives structured {risk, control, evidence} triplets
    3. Validates each triplet against the ExtractionItem schema
    4. Optionally writes COMPLETE items to the AI Review Queue staging list

    Set write_to_sharepoint=true to write directly to SharePoint staging.
    DEFICIENT items are always returned in the response for human review
    regardless of this flag.
    """
    try:
        return await service.run_extraction_from_text(
            text=request.text,
            doc_code=request.source_document_code,
            write_to_sharepoint=request.write_to_sharepoint,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception(f"Extraction failed for {request.source_document_code}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Extraction failed: {exc}. "
                "Check that Ollama is running: ollama serve"
            ),
        )


@router.post(
    "/extract/file",
    response_model=schemas.ExtractionResponse,
    summary="Extract controls from an uploaded PDF or DOCX file",
)
async def extract_from_file(
    file: UploadFile = File(..., description="PDF, DOCX, DOC, or TXT policy document"),
    source_document_code: str = Form(
        ..., description="Document Register code e.g. DRG-ISMS-POL-ACP-01-25"
    ),
    write_to_sharepoint: bool = Form(
        default=False,
        description="Write COMPLETE items to AI Review Queue staging list",
    ),
    user: CurrentUser = Depends(require_compliance_lead),
) -> schemas.ExtractionResponse:
    """
    Upload a PDF or DOCX policy document for GRC extraction.

    Supported file types: .pdf, .docx, .doc, .txt
    Maximum file size: 10MB

    The pipeline:
    1. Read file bytes
    2. Extract text:
       - PDF: pypdf → Azure OCR fallback if < 100 chars
       - DOCX: mammoth → Azure OCR fallback if < 100 chars
       - DOC: RTF detection → striprtf; or OLE2 via olefile (no Azure fallback)
       - TXT: UTF-8 decode
    3. Send text to local Ollama LLM
    4. Return structured extraction results
    """
    if file.filename is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file must have a filename",
        )

    # Read file with size guard
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {len(file_bytes)} bytes exceeds limit of {MAX_FILE_SIZE_BYTES} bytes (10MB)",
        )

    try:
        return await service.run_extraction_from_file(
            file_bytes=file_bytes,
            filename=file.filename,
            doc_code=source_document_code,
            write_to_sharepoint=write_to_sharepoint,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception(f"File extraction failed for {file.filename}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Extraction failed: {exc}",
        )


@router.get(
    "/health/ollama",
    summary="Check LLM provider connectivity (Ollama or RunPod)",
)
async def ollama_health(
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    """
    Verify the active LLM provider is reachable.
    Returns provider name, status, and model/endpoint details.
    """
    return await check_ollama_connectivity()
