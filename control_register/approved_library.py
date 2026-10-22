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
# The library folder still decides WHO defines each control — approved
# documents decide WHAT the definition says. Procedures restate their
# Standard's controls in short form; approved before the Standard, a
# procedure's short copy would otherwise be taken as the definition. A control
# whose defining document is still in Lifecycle waits for it: nothing is
# raised from the copy, and a procedure citing it is not flagged as citing an
# undefined control. A control no document defines anywhere still is.
#
# One run at a time per process, so two approvals finishing together cannot
# queue the same control twice.
# =============================================================================

from __future__ import annotations

import asyncio
import logging
import os
import time
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
# library-folder file id → (lastModified, parse or None if unreadable)
_folder_parsed: dict[str, tuple[str, Optional[ParsedDocument]]] = {}
# When the library was last read in full. A gate check that must answer within a
# request uses the library only if it has been read recently (see is_warm).
_library_read_at: float = 0.0
WARM_FOR_SECONDS = 1800


def is_warm() -> bool:
    return _library_read_at > 0 and time.monotonic() - _library_read_at < WARM_FOR_SECONDS


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


async def load_library_folder(concurrency: int = 4) -> tuple[list[ParsedDocument], list[str]]:
    """Every readable document in the library folder, drafts included — used
    only to tell who defines each control. Returns (documents, download failures)."""
    from cdi.parser import parse_document
    from scripts.intake_sharepoint_to_lifecycle import (
        configured_intake_roots, download_file, resolve_compliance_drive, walk_folder)

    _, drive_id = await resolve_compliance_drive()
    files = []
    for root in await configured_intake_roots(drive_id, None):
        files.extend(await walk_folder(drive_id, root["name"], root["id"]))
    docs: list[ParsedDocument] = []
    missed: list[str] = []
    gate = asyncio.Semaphore(concurrency)

    async def read(f: dict) -> None:
        modified = f.get("modified") or ""
        cached = _folder_parsed.get(f["id"])
        if cached and cached[0] == modified and modified:
            if cached[1]:
                docs.append(cached[1])
            return
        async with gate:
            try:
                data, _ = await download_file(drive_id, f["id"])
            except Exception as exc:
                missed.append(f"{f['folder_path']}/{f['name']}: {exc}")
                return
        try:
            doc = parse_document(data, f["name"])
        except Exception:
            doc = None                      # unreadable files define nothing
        _folder_parsed[f["id"]] = (modified, doc)
        if doc:
            docs.append(doc)

    await asyncio.gather(*(read(f) for f in files))
    global _library_read_at
    if not missed:
        _library_read_at = time.monotonic()
    return docs, missed


def _same_document(a: ParsedDocument, b: ParsedDocument) -> bool:
    if a.header.code and b.header.code:
        return _base_code(a.header.code) == _base_code(b.header.code)
    return a.filename.lower() == b.filename.lower()


def awaiting_definition(approved: LibraryIndex,
                        folder_docs: list[ParsedDocument]) -> tuple[dict[str, str], set[str]]:
    """
    (Control ID → its defining document, for controls the approved documents
    state but whose defining document is not approved yet; every Control ID
    any document states). The folder copy of an approved document is replaced
    by its published copy.
    """
    others = [d for d in folder_docs
              if not any(_same_document(d, a) for a in approved.documents)]
    full = LibraryIndex(approved.documents + others)
    approved_ids = {id(d) for d in approved.documents}
    out = {}
    for cid in approved.defined_ids:
        definer = full.definition(cid)
        if definer and id(definer[0]) not in approved_ids:
            out[cid] = document_label(definer[0])
    return out, set(full.stated_by)


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


def _summary_for(doc: Optional[ParsedDocument], plan, awaiting: dict,
                 index: Optional[LibraryIndex] = None) -> dict:
    """What the run means for one document — for its lifecycle item."""
    if doc is None:
        return {}
    own = {c.control_id for c in doc.controls}
    waits = {}
    for cid in sorted(own | set(doc.implemented_ids)):
        if cid in awaiting:
            waits.setdefault(awaiting[cid], []).append(cid)
    raised = [a for a in plan.actions
              if a.kind in ("create_item", "update_item") and a.control_id in own]
    return {
        "document": document_label(doc),
        "role": doc.role.value,
        # Controls this document is the definition of — not the short copies a
        # procedure carries of its Standard's controls.
        "defines": sum(1 for cid in own
                       if index is None or ((index.definition(cid) or (None,))[0] is doc
                                            and cid not in awaiting)),
        "states": len(own),
        "carries_out": len(doc.implemented_ids),
        "raised_for_review": len(raised),
        "awaiting": waits,          # defining document → control IDs waiting for its approval
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
        folder_docs, folder_missed = await load_library_folder()
        if folder_missed:
            result["missed"] = folder_missed
            result["reason"] = (f"{len(folder_missed)} library file(s) could not be downloaded, so OrgOS "
                                "cannot tell which document defines each control. Nothing was written.")
            return result
        awaiting, defined_anywhere = awaiting_definition(index, folder_docs)

        plan = plan_sync(index, register, queue, owners.resolve)
        plan.actions = [a for a in plan.actions
                        if a.control_id not in awaiting or a.kind == "refresh_status"]
        new_or_changed = plan.count("create_item") + plan.count("update_item")
        catalogue = await _catalogue()
        resolutions = [
            a for a in plan_resolutions(index, queue, catalogue)
            if not (a.kind == "create_item" and (
                # defined in a document still in Lifecycle: it will be, not an error
                (a.control_id.startswith("CITES-UNDEFINED:")
                 and a.control_id.rsplit(":", 1)[1] in defined_anywhere)
                # compared against a procedure's copy, not the real definition
                or (a.control_id.startswith("COPY-DIFFERS:")
                    and a.control_id.rsplit(":", 1)[1] in awaiting)))
        ]
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
            "awaiting_definition": awaiting,
            "focus": _summary_for(focus, plan, awaiting, index),
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
