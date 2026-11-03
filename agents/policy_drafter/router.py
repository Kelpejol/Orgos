# =============================================================================
# agents/policy_drafter/router.py
# POST /api/v1/agents/draft-document
#   1. Generate all sections via Ollama.
#   2. Build a formatted .docx with docx_builder (python-docx, no new library needed).
#   3. Run CDI check against the generated .docx immediately.
#   4. Create a Document Lifecycle entry with the CDI results.
#   5. Save the draft as a new file in the library (starting folder / New documents)
#      and point the entry at it. There is no download: the draft is opened in Word
#      from its card and edited where it lives, like every other document.
# =============================================================================

import io
import re
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from auth.validator import CurrentUser, get_current_user, require_compliance_lead
from agents.policy_drafter.service import draft_document, generate_doc_code_base
from agents.cdi_checker.service import run_cdi_check
from config import settings
from graph.client import (
    create_list_item,
    get_list_items,
    resolve_user,
    update_list_item,
)
from lifecycle.templates import InvalidTemplateError, TemplateNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agents", tags=["Document Drafter"])


# =============================================================================
#  Helpers
# =============================================================================

async def _resolve_display_name(entra_oid: str, fallback: str = "") -> str:
    fallback = (fallback or "").strip()
    if not entra_oid:
        return fallback
    try:
        resolved = await resolve_user(entra_oid)
        return (resolved.get("display_name") or "").strip() or fallback
    except Exception:
        return fallback


async def _write_lifecycle_owner_name(item_id: str, owner_oid: str, fallback: str = "") -> str:
    owner_name = await _resolve_display_name(owner_oid, fallback)
    if owner_name and item_id and settings.is_list_configured(settings.document_lifecycle_list_id):
        await update_list_item(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
            item_id,
            {"Owner": owner_name},
        )
    return owner_name


async def _next_disambiguator(base_prefix: str) -> str:
    """
    v06: a fresh code is just base_prefix (e.g. "DRG-QI-PRO-CDI") — no trailing
    serial/year. Query existing Document Lifecycle codes for an EXACT
    collision with base_prefix and, if found, return a numeric disambiguator
    to append directly to the ID ("2", "3", …) so the new code stays unique
    without inventing a parallel numbering scheme. Empty string ("") means no
    disambiguator is needed. Falls back to "" if the list is unconfigured or
    the query fails — collisions are rare enough that this is an acceptable
    degrade, not a silent data-loss risk.
    """
    try:
        items = await get_list_items(
            settings.document_lifecycle_list_id, "Document Lifecycle"
        )
        existing = {item.get("fields", {}).get("DocumentCode", "") for item in items}
        if base_prefix not in existing:
            return ""
        n = 2
        while f"{base_prefix}{n}" in existing:
            n += 1
        return str(n)
    except Exception:
        return ""


# =============================================================================
#  Request schema
# =============================================================================

class DraftRequest(BaseModel):
    title:             str
    doc_type:          str = "Policy"
    department:        str
    notes:             str = ""
    standards_mapping: str = ""
    trigger:           str = "Manual"
    linked_gap_id:     Optional[str] = None


# =============================================================================
#  POST /api/v1/agents/draft-document
# =============================================================================

@router.post("/draft-document")
async def draft_document_endpoint(
    body: DraftRequest,
    user: CurrentUser = Depends(require_compliance_lead),
) -> dict:
    """
    1. Compute the next serial for this doc code base (auto-increment).
    2. Generate all sections via Ollama.
    3. Build a formatted .docx (server-side, python-docx — no new technology needed).
    4. Run CDI check against the generated .docx.
    5. Create a Document Lifecycle entry.
    6. Save the draft as a new file in the library and point the entry at it, so
       it is opened in Word from its card: never downloaded.
    """
    logger.info(f"Document Drafter requested: '{body.title}' by {user.name}")

    # ── 1: Avoid a code collision (v06 has no serial/year to fall back on) ───
    base_prefix   = generate_doc_code_base(body.department, body.doc_type, body.title)
    disambiguator = await _next_disambiguator(base_prefix)
    logger.info(f"Doc code base: {base_prefix}, disambiguator: {disambiguator or '(none)'}")

    # ── 2 + 3: Generate sections via Ollama + build .docx on the master ──────
    # template for this document type (v06 — see lifecycle/templates.py).
    try:
        draft = await draft_document(
            title=             body.title,
            doc_type=          body.doc_type,
            department=        body.department,
            notes=             body.notes,
            standards_mapping= body.standards_mapping,
            disambiguator=     disambiguator,
        )
        logger.info(f"Draft + docx built: {draft['doc_code']}")
    except TemplateNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"No master CDT template is set up for document type '{body.doc_type}': {exc}",
        )
    except InvalidTemplateError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"The master CDT template for '{body.doc_type}' is broken and cannot be used: {exc}",
        )
    except Exception as exc:
        logger.exception("Document Drafter generation failed")
        raise HTTPException(
            status_code=503,
            detail=f"Document generation failed: {exc}. Check that Ollama is running.",
        )

    docx_buffer: Optional[io.BytesIO] = draft.pop("docx_buffer", None)
    docx_bytes = docx_buffer.read() if docx_buffer else b""
    # V23: a file is named as its title, with no status, version or date.
    filename   = (re.sub(r'[\\/:*?"<>|]+', "", draft["title"]).strip() or draft["doc_code"]) + ".docx"
    cdt_cover        = draft.pop("cdt_cover", None)
    cdt_history      = draft.pop("revision_history", None)

    # ── 4: Run CDI check against the generated .docx ─────────────────────────
    cdi_result: dict = {}
    cdi_status        = "Pending"
    cdi_failures_json = ""
    if docx_bytes:
        try:
            cdi_result = await run_cdi_check(
                file_bytes=docx_bytes,
                filename=filename,
                doc_code=draft["doc_code"],
            )
            if cdi_result.get("error"):
                cdi_status = "Error"
            elif cdi_result.get("passed"):
                cdi_status = "Passed"
            else:
                cdi_status = "Failed"
                cdi_failures_json = json.dumps([
                    {"check": c["check_id"], "detail": c["finding"], "fix": c.get("proposed_fix", "")}
                    for c in cdi_result.get("checks", []) if c["result"] == "FAIL"
                ])
            logger.info(
                f"CDI check on AI draft {draft['doc_code']}: "
                f"{cdi_status} — {cdi_result.get('fail_count', 0)} failures"
            )
        except Exception as exc:
            logger.warning(f"CDI check on AI draft failed: {exc}")
            cdi_status = "Error"

    # ── 5: Create the Document Lifecycle entry; its file is saved below ──────
    owner_name = await _resolve_display_name(user.oid, user.name)

    lifecycle_fields: dict = {
        "Title":            body.title,
        "DocumentCode":     draft["doc_code"],
        "DocumentType":     body.doc_type,
        "Department":       body.department,
        "Stage":            "Review",
        "Trigger":          body.trigger,
        "AIGenerated":      True,
        "Revised":          False,
        "OwnerEntraId":     user.oid,
        "Owner":            owner_name,
        "CDIStatus":        cdi_status,
        "StandardsMapping": draft["standards_mapping"],  # always non-empty
        "Notes": (
            f"AI-generated draft — {draft['doc_code']}. "
            f"CDI check on draft: {cdi_status} "
            f"({cdi_result.get('pass_count', 0)} passed, {cdi_result.get('fail_count', 0)} failed). "
            f"Open it in Word from this card and revise it there."
        ),
    }
    if cdi_failures_json:
        lifecycle_fields["CDIFailures"] = cdi_failures_json
    if body.linked_gap_id:
        lifecycle_fields["LinkedGapId"] = body.linked_gap_id
    try:
        lifecycle_item = await create_list_item(
            settings.document_lifecycle_list_id,
            "Document Lifecycle",
            lifecycle_fields,
        )
        lifecycle_id = str(lifecycle_item["id"])
        try:
            await _write_lifecycle_owner_name(lifecycle_id, user.oid, owner_name)
        except Exception as exc:
            logger.warning(
                f"Lifecycle entry {lifecycle_id} created, but Owner text field "
                f"could not be populated: {exc}"
            )
        logger.info(f"Lifecycle entry created: {lifecycle_id} for {draft['doc_code']}")
    except Exception as exc:
        logger.exception("Failed to create lifecycle entry")
        raise HTTPException(
            status_code=500,
            detail=f"Draft generated but lifecycle entry creation failed: {exc}",
        )

    # CDT (v06): seed the cover facts + initial revision-history row as a
    # SEPARATE, best-effort write — never bundled into the create above. An
    # admin must have added the CDTCoverFacts/RevisionHistory columns to the
    # Document Lifecycle list; if not yet, this simply doesn't land, and the
    # draft itself is unaffected (SharePoint would otherwise reject the WHOLE
    # item creation over one unrecognised field).
    if cdt_cover is not None or cdt_history is not None:
        try:
            cdt_fields: dict = {}
            if cdt_cover is not None:
                cdt_fields["CDTCoverFacts"] = json.dumps(cdt_cover)
            if cdt_history is not None:
                cdt_fields["RevisionHistory"] = json.dumps(cdt_history)
            await update_list_item(
                settings.document_lifecycle_list_id, "Document Lifecycle", lifecycle_id, cdt_fields,
            )
        except Exception as exc:
            logger.info(
                f"Lifecycle entry {lifecycle_id} created, but CDT cover facts were not "
                f"seeded (are the 'CDTCoverFacts'/'RevisionHistory' columns present "
                f"on the Document Lifecycle list yet?): {exc}"
            )

    # ── 6: The draft's file, in the library: one file, edited where it lives ──
    from lifecycle import document_file
    from lifecycle.router import _cdi_check_file, _office_edit_url, _remember_file
    file_url = ""
    if docx_bytes:
        try:
            saved = await document_file.create_new(filename, docx_bytes)
            await _remember_file(lifecycle_id, saved, {}, docx_bytes)
            file_url = saved.web_url
            # The same checks every file change gets, the role check included.
            status_, failures = await _cdi_check_file(lifecycle_id, docx_bytes, saved.name)
            if status_ != "Error":
                await update_list_item(settings.document_lifecycle_list_id, "Document Lifecycle", lifecycle_id,
                                       {"CDIStatus": status_, "CDIFailures": failures})
        except Exception as exc:
            logger.exception(f"Draft {draft['doc_code']}: its file could not be saved to the library")
            raise HTTPException(status_code=503, detail=(
                f"The draft was written and its card created (item {lifecycle_id}), but its file could not "
                f"be saved to SharePoint: {exc}. Upload a file on the card, or delete the card and try again."))

    cdi_summary = {
        "status":     cdi_status,
        "pass_count": cdi_result.get("pass_count", 0),
        "fail_count": cdi_result.get("fail_count", 0),
        "failures": [
            {"check": c["check_id"], "detail": c["finding"], "fix": c.get("proposed_fix", "")}
            for c in cdi_result.get("checks", []) if c.get("result") == "FAIL"
        ] if cdi_result else [],
    }

    return {
        "lifecycle_id": lifecycle_id,
        "doc_code":     draft["doc_code"],
        "title":        draft["title"],
        "sections":     draft["sections"],
        "full_text":    draft["full_text"],
        "file_url":     file_url,
        "edit_url":     _office_edit_url(file_url) if file_url else "",
        "filename":     filename,
        "cdi_check":    cdi_summary,
    }
