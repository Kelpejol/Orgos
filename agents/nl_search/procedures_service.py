# =============================================================================
# agents/nl_search/procedures_service.py — SharePoint Procedural Steps Index
#
# Manages the ProceduralStepsIndex SharePoint list. This list stores structured
# how-to content extracted from approved procedure documents.
#
# Key invariant: steps are replaced on re-index, never accumulated.
# Before writing new steps for a document, delete all existing rows for that
# DocumentCode. This ensures the index always reflects the current approved version.
#
# Steps do NOT go through review zones — they are informational content from
# already-approved documents. The document approval is the governance.
# =============================================================================

import logging
from typing import Optional

from config import settings
from graph.client import (
    create_list_item,
    get_list_items,
    soft_delete_list_item,
)

logger = logging.getLogger(__name__)

_LIST_NAME = "Procedural Steps Index"


def _get_list_id() -> str:
    return settings.procedural_steps_list_id


def _is_configured() -> bool:
    return settings.is_list_configured(_get_list_id())


# =============================================================================
#  Write
# =============================================================================

async def write_procedural_steps(
    steps: list[dict],
    doc_code: str,
    doc_title: str = "",
    doc_link: str = "",
) -> int:
    """
    Write procedural steps to SharePoint for a document.
    Deletes existing steps for this doc_code first (replace, not accumulate).
    Returns count of steps written.
    Also stores the SharePoint item ID on each step dict (key: "sp_item_id")
    so the caller can use it as the ChromaDB document ID.
    """
    if not _is_configured():
        logger.info("Procedural Steps list not configured — skipping SharePoint write")
        return 0

    # Delete stale entries first
    deleted = await delete_steps_for_document(doc_code)
    if deleted:
        logger.info(f"Replaced {deleted} stale steps for {doc_code}")

    written = 0
    for step in steps:
        try:
            fields: dict = {
                "Title":             f"{step.get('process_name', 'Process')} — Step {step.get('step_number', 0)}",
                "DocumentCode":      doc_code,
                "DocumentTitle":     doc_title or doc_code,
                "SectionRef":        step.get("section_ref") or "",
                "ProcessName":       step.get("process_name") or "",
                "StepNumber":        int(step.get("step_number") or 0),
                "StepText":          step.get("step_text") or "",
                "RolesInvolved":     step.get("roles_involved") or "",
                "FormsReferenced":   step.get("forms_referenced") or "",
                "SystemsReferenced": step.get("systems_referenced") or "",
                "Keywords":          step.get("keywords") or "",
            }
            if doc_link:
                fields["DocumentLink"] = doc_link

            created = await create_list_item(_get_list_id(), _LIST_NAME, fields)
            # Attach the SharePoint item ID so vector_store can use it as ChromaDB ID
            sp_id = str(created.get("id") or created.get("fields", {}).get("id", ""))
            step["sp_item_id"] = sp_id
            written += 1

        except Exception as exc:
            logger.error(
                f"Failed to write procedural step {step.get('step_number')} "
                f"for {doc_code}: {exc}"
            )

    logger.info(f"Wrote {written}/{len(steps)} procedural steps for {doc_code}")
    return written


# =============================================================================
#  Delete
# =============================================================================

async def delete_steps_for_document(doc_code: str) -> int:
    """
    Soft-delete all procedural steps for a given document code.
    Returns count of items deleted.
    Note: soft_delete_list_item sets Status=Withdrawn; we filter these out on read.
    """
    if not _is_configured():
        return 0

    try:
        items = await get_list_items(
            list_id=_get_list_id(),
            list_name=_LIST_NAME,
            odata_filter=f"fields/DocumentCode eq '{doc_code}'",
            select_fields="id,fields/DocumentCode",
        )
        count = 0
        for item in items:
            item_id = item.get("id") or item.get("fields", {}).get("id")
            if item_id:
                await soft_delete_list_item(_get_list_id(), _LIST_NAME, str(item_id))
                count += 1
        return count
    except Exception as exc:
        logger.warning(f"delete_steps_for_document {doc_code} failed: {exc}")
        return 0


# =============================================================================
#  Read
# =============================================================================

async def get_steps_for_document(doc_code: str) -> list[dict]:
    """Fetch all active procedural steps for a document. Used by procedural_search."""
    if not _is_configured():
        return []
    try:
        items = await get_list_items(
            list_id=_get_list_id(),
            list_name=_LIST_NAME,
            odata_filter=(
                f"fields/DocumentCode eq '{doc_code}' "
                "and fields/Status ne 'Withdrawn'"
            ),
            select_fields=(
                "id,fields/DocumentCode,fields/DocumentTitle,fields/SectionRef,"
                "fields/ProcessName,fields/StepNumber,fields/StepText,"
                "fields/RolesInvolved,fields/FormsReferenced,"
                "fields/SystemsReferenced,fields/Keywords,fields/DocumentLink"
            ),
        )
        return [_map_item(i) for i in items]
    except Exception as exc:
        logger.warning(f"get_steps_for_document {doc_code} failed: {exc}")
        return []


async def get_steps_for_process(
    doc_code: str,
    process_name: str,
) -> list[dict]:
    """
    Fetch all steps for a specific process within a document, sorted by StepNumber.
    Used by procedural_search to expand a semantic hit into the full workflow.
    """
    if not _is_configured():
        return []
    try:
        items = await get_list_items(
            list_id=_get_list_id(),
            list_name=_LIST_NAME,
            odata_filter=(
                f"fields/DocumentCode eq '{doc_code}' "
                f"and fields/ProcessName eq '{process_name}' "
                "and fields/Status ne 'Withdrawn'"
            ),
            select_fields=(
                "id,fields/ProcessName,fields/StepNumber,fields/StepText,"
                "fields/RolesInvolved,fields/FormsReferenced,"
                "fields/SystemsReferenced,fields/SectionRef,fields/DocumentTitle,"
                "fields/Keywords,fields/DocumentLink"
            ),
        )
        mapped = [_map_item(i) for i in items]
        return sorted(mapped, key=lambda s: s.get("step_number") or 0)
    except Exception as exc:
        logger.warning(
            f"get_steps_for_process {doc_code}/{process_name} failed: {exc}"
        )
        return []


async def get_all_steps_paginated(top: int = 200) -> list[dict]:
    """
    Return all active procedural steps (up to top). Used by rebuild endpoint.
    """
    if not _is_configured():
        return []
    try:
        items = await get_list_items(
            list_id=_get_list_id(),
            list_name=_LIST_NAME,
            odata_filter="fields/Status ne 'Withdrawn'",
            select_fields=(
                "id,fields/DocumentCode,fields/DocumentTitle,fields/ProcessName,"
                "fields/StepNumber,fields/StepText,fields/RolesInvolved,"
                "fields/FormsReferenced,fields/SystemsReferenced,fields/Keywords,"
                "fields/SectionRef,fields/DocumentLink"
            ),
            top=top,
        )
        return [_map_item(i) for i in items]
    except Exception as exc:
        logger.warning(f"get_all_steps_paginated failed: {exc}")
        return []


def _map_item(item: dict) -> dict:
    f = item.get("fields", item)
    return {
        "id":                str(item.get("id") or f.get("id", "")),
        "document_code":     f.get("DocumentCode", ""),
        "document_title":    f.get("DocumentTitle", ""),
        "section_ref":       f.get("SectionRef", ""),
        "process_name":      f.get("ProcessName", ""),
        "step_number":       int(f.get("StepNumber") or 0),
        "step_text":         f.get("StepText", ""),
        "roles_involved":    f.get("RolesInvolved", ""),
        "forms_referenced":  f.get("FormsReferenced", ""),
        "systems_referenced":f.get("SystemsReferenced", ""),
        "keywords":          f.get("Keywords", ""),
        "document_link":     f.get("DocumentLink", ""),
    }
