# =============================================================================
# control_register/approved_library.py — controls enter OrgOS through approval
#
# The approved library is every document the Document Register holds as
# current, read from its published copy:
#   Active        — approved and in force
#   Under Review  — a revision is in flight; the approved version still governs
# Withdrawn and Superseded documents, and anything not yet approved, are not
# part of it. Drafts never reach the registers.
#
# Approving a document re-reads the approved library and brings the registers
# in line (control_register/sync.py): the document's new and changed controls
# go to Extraction Review by Control ID, and what the approved documents get
# wrong between them — a procedure citing a control no approved document
# defines, an edited copy, an unknown Record ID — goes to Assignment &
# Ownership. Every comparison is against approved documents only.
#
# One run at a time per process, so two approvals finishing together cannot
# queue the same control twice.
# =============================================================================

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote, urlparse

from cdi.library import LibraryIndex, _base_code, document_label
from cdi.model import ParsedDocument
from config import settings

logger = logging.getLogger(__name__)

CURRENT = {"Active", "Under Review"}
_READABLE = (".docx", ".pdf")

# (published URL, register row's Modified) → parse. A re-publish changes the
# row, so a stale parse is never reused; an unchanged library is read once.
_parsed: dict[tuple[str, str], ParsedDocument] = {}
_lock = asyncio.Lock()


@dataclass
class ApprovedLibrary:
    documents: list[ParsedDocument] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)     # "code: reason" — the file can't be parsed
    missed: list[str] = field(default_factory=list)         # "code: reason" — the download failed
    no_file: list[str] = field(default_factory=list)        # current, but no published copy recorded


def _filename(url: str, code: str) -> str:
    name = os.path.basename(unquote(urlparse(url).path))
    return name if name.lower().endswith(_READABLE) else f"{code or 'document'}.docx"


async def load_approved_library(concurrency: int = 4) -> ApprovedLibrary:
    from cdi.parser import parse_document
    from cdi.reader import UnsupportedDocument
    from graph.client import download_file_from_sharepoint, get_list_items

    rows = await get_list_items(settings.document_register_list_id, "Document Register")
    lib = ApprovedLibrary()
    current = []
    for row in rows:
        f = row.get("fields") or {}
        if (f.get("Status") or "").strip() not in CURRENT:
            continue
        code = (f.get("DocumentCode") or f.get("Title") or "").strip()
        url = (f.get("SharePointUrl") or "").strip()
        if not url:
            lib.no_file.append(code)
            continue
        current.append((code, url, str(f.get("Modified") or row.get("lastModifiedDateTime") or "")))

    gate = asyncio.Semaphore(concurrency)

    async def read(code: str, url: str, modified: str) -> None:
        key = (url, modified)
        if key in _parsed:
            lib.documents.append(_parsed[key])
            return
        async with gate:
            try:
                data, _ = await download_file_from_sharepoint(url)
            except Exception as exc:
                lib.missed.append(f"{code}: {exc}")
                return
        try:
            doc = parse_document(data, _filename(url, code))
        except UnsupportedDocument as exc:
            lib.unreadable.append(f"{code}: {exc}")
            return
        except Exception as exc:
            lib.unreadable.append(f"{code}: {type(exc).__name__}: {exc}")
            return
        _parsed[key] = doc
        lib.documents.append(doc)

    await asyncio.gather(*(read(*c) for c in current))
    return lib


async def _catalogue():
    from graph.exceptions import SharePointListNotConfiguredError
    from records_catalogue import service

    try:
        entries = await service.load()
    except SharePointListNotConfiguredError:
        return None
    # An empty list means the Catalogue hasn't been imported yet, not that
    # every record is missing — checking against it would flag them all.
    return entries or None


def _summary_for(doc: Optional[ParsedDocument], plan) -> dict:
    """What the run means for one document — for its lifecycle item."""
    if doc is None:
        return {}
    own = {c.control_id for c in doc.controls}
    raised = [a for a in plan.actions
              if a.kind in ("create_item", "update_item") and a.control_id in own]
    return {
        "document": document_label(doc),
        "role": doc.role.value,
        "defines": len(doc.controls),
        "carries_out": len(doc.implemented_ids),
        "raised_for_review": len(raised),
    }


async def sync_approved_library(focus_code: str = "", apply: bool = True,
                                progress=None) -> dict:
    """
    Read the approved library and bring the registers in line. Returns a
    summary; with `focus_code`, also what it found in that document.
    Nothing is written when a published copy failed to download: its
    controls would look undefined and pending items would close wrongly.
    """
    from control_register.sync import apply_sync, plan_resolutions, plan_sync
    from graph.client import get_list_items
    from ownership.resolver import get_ownership_index

    async with _lock:
        lib = await load_approved_library()
        result: dict = {
            "documents_read": len(lib.documents),
            "unreadable": lib.unreadable,
            "missed": lib.missed,
            "no_published_copy": lib.no_file,
            "written": False,
        }
        index = LibraryIndex(lib.documents)
        focus = next((d for d in lib.documents
                      if focus_code and _base_code(d.header.code) == _base_code(focus_code)), None)
        if lib.missed:
            result["reason"] = (f"{len(lib.missed)} approved document(s) could not be downloaded, "
                                "so the approved library is incomplete. Nothing was written.")
            return result

        register = await get_list_items(settings.control_register_list_id, "Control Register")
        queue = await get_list_items(settings.ai_review_queue_list_id, "AI Review Queue")
        owners = await get_ownership_index()
        plan = plan_sync(index, register, queue, owners.resolve)
        new_or_changed = plan.count("create_item") + plan.count("update_item")
        catalogue = await _catalogue()
        resolutions = plan_resolutions(index, queue, catalogue)
        plan.actions += resolutions

        result.update({
            "controls_defined": len(index.defined_ids),
            "contested": plan.contested,
            "new_or_changed": new_or_changed,
            "unchanged": plan.unchanged,
            "status_changes": plan.count("refresh_status"),
            "findings_raised": sum(a.kind == "create_item" for a in resolutions),
            "findings_closed": sum(a.kind == "close_item" for a in resolutions),
            "no_longer_defined": plan.no_longer_defined,
            "catalogue_checked": catalogue is not None,
            "focus": _summary_for(focus, plan),
            "actions": len(plan.actions),
        })
        if focus_code and focus is None:
            result["focus_missing"] = (f"{focus_code} is not among the approved documents read "
                                       "(no published copy, or it could not be read).")
        if not apply:
            return result
        failures = await apply_sync(plan, progress=progress)
        result["written"] = True
        result["failures"] = failures
        return result
