# =============================================================================
# doc_standards/service.py — what the Document Standards endpoints need
#
#   standard_view()   the standard, for the page: generated from the SAME data
#                     the checks read, so what an author is told is what is
#                     enforced.
#   build_context()   the cross-document knowledge a check can use (Register,
#                     Records Catalogue, the library) — each piece optional,
#                     and each failure to fetch it reported, never hidden.
#   plan_conversion() read a file, pick its template, build and prove.
# =============================================================================

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from cdi.library import LibraryIndex, _base_code
from cdi.model import ParsedDocument
from config import settings
from doc_standards.checks import CHECKS, NOT_BUILT_REASONS, Context, reference
from doc_standards.convert import ConversionPlan, convert_document
from lifecycle.schemas import CdtCoverFacts

logger = logging.getLogger(__name__)

# Cloudflare cuts a request off at about 100 seconds; stay well inside it.
CONTEXT_TIMEOUT_SECONDS = 60

# What each document type's main section holds (CDI Procedure §7.3, section 4.0).
_MAIN_CONTENT = {"POL": "Commitments", "STD": "Requirements (the controls)", "PRO": "Steps",
                 "SPEC": "Steps", "GDL": "Recommendations"}
_DEFINES_CONTROLS = {
    "STD": "Yes. A Standard is where controls are defined, each with a Control ID and every field of the control record.",
    "PRO": "Only where the family has no Standard (CDI 5.2). Otherwise it carries out the Standard's controls by ID "
           "and does not restate them with changes.",
    "SPEC": "Only where the family has no Standard. Otherwise it carries out the Standard's controls by ID.",
    "POL": "No. A Policy gives authority and intent; it carries no tools, steps or controls (V04).",
    "GDL": "No. Guidelines give recommendations (use should and may).",
}
_ALL = ["V01", "V02", "V03", "V04", "V13", "V15", "V18", "V19", "V20", "V21", "V23", "V24"]
_CONTROL_CHECKS = ["V08", "V09", "V10", "V11", "V12", "V14", "V22"]
_ROLE_CHECKS = ["V05", "V06", "V07"]
_STEP_CHECKS = ["V16", "V17"]


def _applies(type_code: str) -> list[str]:
    ids = list(_ALL) + _ROLE_CHECKS
    if type_code == "STD":
        ids += _CONTROL_CHECKS
    elif type_code in ("PRO", "SPEC"):
        ids += _CONTROL_CHECKS + _STEP_CHECKS     # when it defines controls; V16/V17 for its steps
    return sorted(set(ids))


def standard_view() -> dict:
    ref = reference()
    checks = []
    for c in ref["checks"]:
        built = c["id"] in CHECKS
        checks.append({**c, "built": built, "needs": "" if built else NOT_BUILT_REASONS.get(c["id"], "Not built yet.")})
    types = []
    for t in ref["annex_b"]["document_types"]:
        types.append({**t, "main_content": _MAIN_CONTENT.get(t["code"], "—"),
                      "defines_controls": _DEFINES_CONTROLS.get(t["code"], "No. This is a supporting document or a record."),
                      "applies": _applies(t["code"])})
    return {"source": ref["source"], "checks": checks, "types": types,
            "required_sections": ref["required_sections"],
            "register_fields": ref["annex_a_register_fields"],
            "control_fields": ref["annex_c_control_fields"],
            "reference_data": {k: v for k, v in ref["annex_b"].items() if k != "document_types"},
            "amendments": [a for a in ref.get("amendments", []) if a["status"] == "applied"],
            "built": sum(1 for c in checks if c["built"]), "total": len(checks)}


async def _register_rows() -> Optional[list]:
    from graph.client import get_list_items
    if not settings.is_list_configured(settings.document_register_list_id):
        return None
    return await get_list_items(settings.document_register_list_id, "Document Register")


async def _library_documents(parsed: ParsedDocument) -> list[ParsedDocument]:
    """The approved documents and the library's drafts — except other copies of THIS document."""
    from control_register.approved_library import load_approved_library, load_library_folder
    approved, (folder, missed) = await asyncio.gather(load_approved_library(), load_library_folder())
    if missed or approved.missed:
        raise RuntimeError(f"{len(missed) + len(approved.missed)} library file(s) could not be downloaded")
    same = lambda d: (d.header.code and parsed.header.code and _base_code(d.header.code) == _base_code(parsed.header.code)
                      and (d.header.title or "").strip().lower() == (parsed.header.title or "").strip().lower())
    return [d for d in approved.documents + folder if not same(d)]


_warming: Optional[asyncio.Task] = None


def start_warming() -> None:
    """Read the library in the background so a later check can use it without waiting."""
    global _warming
    if _warming is not None and not _warming.done():
        return

    async def run() -> None:
        try:
            from control_register.approved_library import load_approved_library, load_library_folder
            await asyncio.gather(load_approved_library(), load_library_folder())
        except Exception:
            logger.exception("Reading the library in the background failed")

    _warming = asyncio.create_task(run())


async def build_context(parsed: ParsedDocument, *, wait_for_library: bool = True) -> tuple[Context, list[str]]:
    """
    The context for checking `parsed`, and a plain-words note for anything missing.

    `wait_for_library=False` is for a check that sits inside a request which must
    answer promptly (a Lifecycle gate): it uses the library only if it has been
    read recently, and otherwise starts reading it in the background and says so.
    """
    ctx, notes = Context(), []
    try:
        ctx.register = await _register_rows()
        if ctx.register is None:
            notes.append("The Document Register is not configured, so parents and uniqueness were not looked up.")
    except Exception as exc:
        notes.append(f"The Document Register could not be read ({exc}).")
    try:
        from control_register.approved_library import _catalogue
        ctx.catalogue = await _catalogue()
        if ctx.catalogue is None:
            notes.append("The Records Catalogue is empty or not configured, so Record IDs were not looked up.")
    except Exception as exc:
        notes.append(f"The Records Catalogue could not be read ({exc}).")
    try:
        from groups import service as groups_service
        from doc_standards.roles import RoleBook
        ctx.roles = RoleBook.from_groups(await groups_service.list_groups())
    except Exception as exc:
        notes.append(f"Org Roles could not be read ({exc}), so the roles a document names were not checked.")
    from control_register.approved_library import is_warm
    if not wait_for_library and not is_warm():
        start_warming()
        notes.append("The library is being read for the first time, so checks that compare this document with "
                     "others did not run. Check again in a minute or two.")
        return ctx, notes
    try:
        others = await asyncio.wait_for(_library_documents(parsed), CONTEXT_TIMEOUT_SECONDS)
        ctx.index = LibraryIndex([*others, parsed])
    except asyncio.TimeoutError:
        notes.append("Reading the library took too long. Run the check again in a minute: what was read is kept, "
                     "so the next attempt is faster.")
    except Exception as exc:
        notes.append(f"The library could not be read ({exc}), so checks that compare this document with others "
                     "could not run.")
    return ctx, notes


async def plan_conversion(file_bytes: bytes, filename: str,
                          existing_cover: Optional[CdtCoverFacts] = None) -> ConversionPlan:
    """Read the file, load the master template for its type, build and prove the conversion."""
    from lifecycle.templates import InvalidTemplateError, TemplateNotFoundError, load_master_template
    first = await asyncio.to_thread(convert_document, file_bytes, filename, None, existing_cover)
    if not first.doc_type:
        return first                                   # refused before a template was needed — say why
    try:
        master = await load_master_template(first.doc_type)
    except (TemplateNotFoundError, InvalidTemplateError) as exc:
        first.ok = False
        first.reason = f"The {first.doc_type} master template could not be used: {exc}"
        return first
    return await asyncio.to_thread(convert_document, file_bytes, filename, master, existing_cover)
