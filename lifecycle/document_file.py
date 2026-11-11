# =============================================================================
# lifecycle/document_file.py — the one file behind a Lifecycle item
#
# A document has ONE file: the one in the SharePoint library. OrgOS reads it, and
# every change OrgOS makes (Fix CDI issues, Use this role, an amendment, a cover,
# a conversion, the stamp at approval) is saved over that same file. SharePoint
# keeps each save in the file's version history, and anyone who opens the library
# sees what OrgOS sees. OrgOS keeps no copies of its own.
#
# The item remembers which file it is (drive and item ids, so a rename or a move
# in SharePoint does not lose it) and what the file held when it was last checked,
# in its FileState column. A file that has changed since was edited outside OrgOS
# — in Word, or straight in SharePoint — and is checked again
# (lifecycle/router.py::_sync_with_file).
# =============================================================================

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import settings
from graph import client as gc
from graph.exceptions import GraphAPIError, GraphNotFoundError

logger = logging.getLogger(__name__)

FILE_STATE = "FileState"                 # Document Lifecycle column: multiple lines of text, plain
NEW_DOCUMENTS_FOLDER = "New documents"   # in the library's starting folder: drafts with no file yet


class NoFile(Exception):
    """The item has no file, or its file is gone."""


@dataclass
class DocFile:
    drive_id: str
    item_id: str
    name: str
    web_url: str
    ctag: str = ""
    parent_id: str = ""
    modified: str = ""

    @classmethod
    def from_item(cls, item: dict) -> "DocFile":
        parent = item.get("parentReference") or {}
        return cls(
            drive_id=parent.get("driveId", ""), item_id=item.get("id", ""), name=item.get("name", ""),
            web_url=item.get("webUrl", ""), ctag=item.get("cTag") or item.get("eTag") or "",
            parent_id=parent.get("id", ""), modified=item.get("lastModifiedDateTime", ""))


def stored_state(fields: dict) -> dict:
    """What the item remembers about its file: {"drive", "item", "ctag", "digest", …}."""
    try:
        state = json.loads(fields.get(FILE_STATE) or "{}")
    except (TypeError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def state_json(f: DocFile, data: Optional[bytes] = None, **extra) -> str:
    state = {"drive": f.drive_id, "item": f.item_id, "ctag": f.ctag, **extra}
    if data is not None:
        state["digest"] = content_digest(data)
    return json.dumps(state)


def content_digest(data: bytes) -> str:
    """
    A fingerprint of what the document SAYS. For a Word file the properties SharePoint writes
    into the package itself (docProps/, customXml/) are left out: SharePoint rewrites them after
    a save, and that is not an edit.
    """
    h = hashlib.sha256()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in sorted(z.namelist()):
                if name.startswith(("docProps/", "customXml/")):
                    continue
                h.update(name.encode())
                h.update(z.read(name))
        return h.hexdigest()
    except (zipfile.BadZipFile, ValueError, KeyError):
        return hashlib.sha256(data).hexdigest()


async def locate(fields: dict) -> DocFile:
    """The item's file, by its ids when the item has them (they survive a rename or a move),
    else by its link."""
    state = stored_state(fields)
    if state.get("drive") and state.get("item"):
        try:
            return DocFile.from_item(await gc.get_drive_item(state["drive"], state["item"]))
        except GraphNotFoundError:
            logger.warning(f"The file {state['item']} is no longer in SharePoint; trying the item's link.")
    url = fields.get("SharePointFileUrl") or ""
    if not url:
        raise NoFile("There is no file yet.")
    try:
        return DocFile.from_item(await gc.sharepoint_item_metadata(url))
    except GraphNotFoundError as exc:
        raise NoFile("The document's file is no longer where OrgOS last saw it in SharePoint "
                     "(deleted, or moved before OrgOS recorded it).") from exc


async def read(f: DocFile) -> bytes:
    return await gc.download_drive_item(f.drive_id, f.item_id)


class FileLocked(Exception):
    """SharePoint refused the save because the file is checked out or open for editing in Word.
    The message says which, and what to do."""


_LOCK_WAITS = (2.0, 5.0)        # seconds: a lock left by Word closing a moment ago often clears


async def save(f: DocFile, data: bytes) -> DocFile:
    """Save `data` over the file: the same file, one new SharePoint version. A locked file is
    tried again briefly, then refused with FileLocked; nothing is saved."""
    for wait in (*_LOCK_WAITS, None):
        try:
            return DocFile.from_item(await gc.replace_drive_item_content(f.drive_id, f.item_id, data))
        except GraphAPIError as exc:
            if getattr(exc, "status_code", None) != 423:
                raise
            if wait is None:
                raise FileLocked(await why_locked(f)) from exc
            await asyncio.sleep(wait)


async def why_locked(f: DocFile) -> str:
    """Checked out (someone must check it in) or open in Word (close it, then wait a little)."""
    name = f.name or "The document"
    try:
        meta = await gc.get_drive_item(f.drive_id, f.item_id)
    except Exception:
        meta = {}
    who = ((meta.get("lastModifiedBy") or {}).get("user") or {}).get("displayName", "")
    when = str(meta.get("lastModifiedDateTime") or "")[:16].replace("T", " ")
    last = f" It was last saved by {who} at {when} (UTC)." if who and when else ""
    if (meta.get("publication") or {}).get("level") == "checkout":
        return (f"“{name}” is checked out in SharePoint, so nothing else can save it. Whoever checked it out "
                f"must check it in (in the library: select the file, then … → More → Check in).{last}")
    return (f"“{name}” is open for editing in Word (perhaps through Edit in Word), so SharePoint won't let "
            f"anything else save it. Close it in Word, wait a minute or two (SharePoint holds the lock briefly "
            f"after Word closes), then try again.{last}")


async def rename(f: DocFile, name: str) -> DocFile:
    return DocFile.from_item(await gc.rename_drive_item(f.drive_id, f.item_id, name))


async def create_new(filename: str, data: bytes) -> DocFile:
    """A file for a document that has none yet (a drafter draft, a manual entry): in the
    library's starting folder, under New documents, never over an existing file."""
    _, drive_id = await gc.resolve_compliance_drive()
    folder = f"{settings.compliance_starting_folder.strip('/')}/{NEW_DOCUMENTS_FOLDER}"
    return DocFile.from_item(await gc.create_drive_file(drive_id, folder, filename, data))


async def create_beside(f: DocFile, filename: str, data: bytes) -> DocFile:
    """A new file in the same folder as `f` (a file in another format replacing it)."""
    return DocFile.from_item(await gc.create_file_beside(f.drive_id, f.parent_id, filename, data))


def _when(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def may_have_changed(f: DocFile, fields: dict) -> bool:
    """
    Has the file moved on since the item last checked it? With a stored tag: the tag differs.
    Without one (an item from before FileState, or the column not added yet): the file was saved
    after the item last changed, since OrgOS updates the item after every save of its own.
    """
    state = stored_state(fields)
    if state.get("ctag"):
        return state["ctag"] != f.ctag
    saved, touched = _when(f.modified), _when(fields.get("Modified", ""))
    return bool(saved and touched and saved > touched)
