# =============================================================================
# scripts/reset_data.py — clear OrgOS's document-derived data to rebuild it from documents
#
# What it clears by default — everything that is REBUILT from the documents:
#     Document Register, AI Review Queue, Document Lifecycle, Control Register,
#     Evidence Tracker, Gap Analysis, and the chat search index (ChromaDB).
# What it keeps unless asked — records people made that NO document can rebuild:
#     Compliance Calendar, Contract Register, Strategic Risk Register  (--include-business-records)
#     Audit Log, the decision trail                                    (--include-audit-log)
# What it never touches: Org Roles (roles, aliases, members), the Records Catalogue,
#     the CDI reference and amendments, the CDT templates, the library folder itself.
#
# SAFETY
#   • Before anything is deleted, every item of every list it will clear is written to
#     backups/reset-<timestamp>/<list>.json, and every Lifecycle item's file and every
#     Register entry's published copy is downloaded beside them (files/ + manifest.json).
#     If the backup fails, NOTHING is deleted. scripts/restore_backup.py puts a list back.
#   • Deletes retry when SharePoint throttles (429) and refresh an expired token; any item
#     that still could not be deleted is listed, and the script exits non-zero.
#   • The intake checkpoint is moved into the backup, so the next intake re-reads the library.
#
# Usage:
#   python scripts/reset_data.py                          # dry run: counts only, nothing written
#   python scripts/reset_data.py --confirm                # back up, then clear
#   python scripts/reset_data.py --confirm --skip-chroma  # SharePoint only
#   python scripts/reset_data.py --confirm --include-business-records --include-audit-log
#
# Rebuild order afterwards is printed at the end (also in docs/GO-LIVE-CHECKLIST.md).
# =============================================================================

import asyncio
import json
import logging
import os
import shutil
import sys
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings
from graph.auth import get_graph_access_token, invalidate_token_cache

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKPOINT = os.path.join(ROOT, "scripts", "intake_lifecycle_checkpoint.json")

DOCUMENT_LISTS = [
    ("Document Register",  settings.document_register_list_id),
    ("AI Review Queue",    settings.ai_review_queue_list_id),
    ("Document Lifecycle", settings.document_lifecycle_list_id),
    ("Control Register",   settings.control_register_list_id),
    ("Evidence Tracker",   settings.evidence_tracker_list_id),
    ("Gap Analysis",       settings.gap_analysis_list_id),
]
BUSINESS_LISTS = [
    ("Compliance Calendar",     settings.compliance_calendar_list_id),
    ("Contract Register",       settings.contract_register_list_id),
    ("Strategic Risk Register", settings.strategic_risk_register_list_id),
]
AUDIT_LIST = [("Audit Log", settings.audit_log_list_id)]

CHROMA_COLLECTIONS = ["controls_v1", "procedures_v1"]
_RETRIES = 5

REBUILD = """
Rebuild, in order:
  1. Check Org Roles and the Records Catalogue are still there (the reset never touches them).
  2. python scripts/intake_sharepoint_to_lifecycle.py --owner-email <compliance lead>
     (the checkpoint was cleared, so every library file is read again).
  3. In OrgOS, per document: Review (role problems and Fix CDI issues, Convert to CDT,
     decisions on flagged checks) → Sensitisation → Approval. Approve each Standard before
     the procedures that carry out its controls.
  4. Approval reads the approved library: accept the controls in Extraction Review, decide
     Assignment & Ownership. If an approval note says the read failed:
     python scripts/sync_control_library.py --apply
  5. python scripts/sync_evidence_obligations.py, then set each record's check frequency.
  6. Run gap analysis (Gap Analysis page) and rebuild the chat index
     (python scripts/rebuild_chat_index.py --apply).
  Work done in Review before the reset is in the backup's files/ folder (manifest.json says
  which document each file is): upload it on the new Lifecycle card rather than redo it.
"""


# =============================================================================
#  SharePoint with retries
# =============================================================================

class Graph:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.token = ""

    async def _headers(self) -> dict:
        if not self.token:
            self.token = await get_graph_access_token()
        return {"Authorization": f"Bearer {self.token}"}

    async def call(self, method: str, url: str) -> httpx.Response:
        for attempt in range(_RETRIES):
            resp = await self.client.request(method, url, headers=await self._headers())
            if resp.status_code == 401 and attempt == 0:
                invalidate_token_cache()
                self.token = ""
                continue
            if resp.status_code in (429, 503, 504):
                wait = float(resp.headers.get("Retry-After") or 2 ** attempt)
                await asyncio.sleep(min(wait, 60))
                continue
            return resp
        return resp

    def _list_url(self, list_id: str) -> str:
        return f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}/lists/{list_id}"

    async def all_items(self, list_id: str) -> list[dict]:
        url = f"{self._list_url(list_id)}/items?$expand=fields&$top=999"
        items: list[dict] = []
        while url:
            resp = await self.call("GET", url)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return items

    async def delete(self, list_id: str, item_id: str) -> bool:
        resp = await self.call("DELETE", f"{self._list_url(list_id)}/items/{item_id}")
        return resp.status_code in (200, 204, 404)


# =============================================================================
#  Backup
# =============================================================================

def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in " ._-" else "_" for c in name).strip() or "file"


async def backup(graph: Graph, lists: list[tuple[str, str]], folder: str) -> dict[str, list[dict]]:
    """Write every item of every list to folder/<list>.json, and download the documents' files.
    Raises on any failure to read a list: a reset without a complete backup does not happen."""
    os.makedirs(folder, exist_ok=True)
    snapshot: dict[str, list[dict]] = {}
    for name, list_id in lists:
        if not settings.is_list_configured(list_id):
            continue
        items = await graph.all_items(list_id)
        snapshot[name] = items
        with open(os.path.join(folder, f"{_safe(name)}.json"), "w", encoding="utf-8") as fh:
            json.dump({"list": name, "list_id": list_id, "taken": datetime.now().isoformat(),
                       "items": items}, fh, ensure_ascii=False, indent=1)
        logger.info(f"  backed up {name}: {len(items)} item(s)")
    await _backup_files(snapshot, os.path.join(folder, "files"))
    return snapshot


async def _backup_files(snapshot: dict[str, list[dict]], folder: str) -> None:
    """Each Lifecycle item's current file (its working copy holds the Review work) and each
    Register entry's published copy. A file that can't be downloaded is listed, not fatal."""
    from graph import client as gc
    os.makedirs(folder, exist_ok=True)
    manifest, missed = [], []
    sources = [("Document Lifecycle", "SharePointFileUrl"), ("Document Register", "SharePointUrl")]
    await gc.startup()
    try:
        for list_name, column in sources:
            for item in snapshot.get(list_name, []):
                f = item.get("fields") or {}
                url = f.get(column)
                if not url:
                    continue
                name = f"{list_name.split()[-1].lower()}-{item['id']}-{_safe(f.get('DocumentCode') or f.get('Title') or 'document')}"
                try:
                    data, content_type = await gc.download_file_from_sharepoint(url)
                    ext = ".pdf" if "pdf" in (content_type or "") else ".docx"
                    with open(os.path.join(folder, name + ext), "wb") as fh:
                        fh.write(data)
                    manifest.append({"file": name + ext, "list": list_name, "item": item["id"],
                                     "code": f.get("DocumentCode", ""), "title": f.get("Title", ""),
                                     "stage": f.get("Stage", ""), "url": url})
                except Exception as exc:
                    missed.append({"list": list_name, "item": item["id"], "url": url, "error": str(exc)[:200]})
    finally:
        await gc.shutdown()
    with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump({"files": manifest, "not_downloaded": missed}, fh, ensure_ascii=False, indent=1)
    logger.info(f"  files: {len(manifest)} saved, {len(missed)} could not be downloaded (listed in manifest.json)")


# =============================================================================
#  Chat index
# =============================================================================

def clear_chromadb(dry_run: bool) -> None:
    chroma_dir = settings.chroma_persist_dir
    if not os.path.exists(chroma_dir):
        logger.info(f"  ChromaDB: directory '{chroma_dir}' not found — nothing to clear")
        return
    if dry_run:
        logger.info(f"  ChromaDB: collections {CHROMA_COLLECTIONS} would be cleared (dry run)")
        return
    try:
        import chromadb
        client = chromadb.PersistentClient(path=chroma_dir)
        for name in CHROMA_COLLECTIONS:
            try:
                client.delete_collection(name)
                logger.info(f"  ChromaDB: deleted collection '{name}'")
            except Exception:
                logger.info(f"  ChromaDB: collection '{name}' did not exist — skipped")
    except Exception as exc:
        logger.warning(f"  ChromaDB: could not clear via client — removing the directory: {exc}")
        shutil.rmtree(chroma_dir, ignore_errors=True)


# =============================================================================
#  Main
# =============================================================================

async def main() -> int:
    args = sys.argv[1:]
    dry_run = "--confirm" not in args
    skip_chroma, chroma_only = "--skip-chroma" in args, "--chroma-only" in args
    lists = list(DOCUMENT_LISTS)
    if "--include-business-records" in args:
        lists += BUSINESS_LISTS
    if "--include-audit-log" in args:
        lists += AUDIT_LIST

    print("\n" + "=" * 64)
    print("  OrgOS reset — clears document-derived data to rebuild it from documents")
    print("  Kept: Org Roles, Records Catalogue" +
          ("" if "--include-business-records" in args else ", Calendar, Contracts, Strategic Risks") +
          ("" if "--include-audit-log" in args else ", Audit Log"))
    print("=" * 64)
    if dry_run:
        print("\n  DRY RUN — counts only. Pass --confirm to back up and clear.\n")
    else:
        print("\n  *** LIVE RUN — a full backup is taken first; then the lists are cleared ***\n")
        if input("  Type 'yes' to proceed: ").strip().lower() != "yes":
            print("  Aborted.")
            return 1

    failures: list[str] = []
    if not chroma_only:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            graph = Graph(client)
            if dry_run:
                for name, list_id in lists:
                    if settings.is_list_configured(list_id):
                        logger.info(f"  {name}: {len(await graph.all_items(list_id))} item(s) would be cleared")
            else:
                folder = os.path.join(ROOT, "backups", f"reset-{datetime.now():%Y%m%d-%H%M%S}")
                print(f"Backing up to {folder} …")
                try:
                    snapshot = await backup(graph, lists, folder)
                except Exception as exc:
                    print(f"\n  BACKUP FAILED ({exc}). Nothing was deleted.")
                    return 2
                print("\nClearing:")
                for name, list_id in lists:
                    items = snapshot.get(name, [])
                    left = [i["id"] for i in items if not await graph.delete(list_id, i["id"])]
                    failures += [f"{name} item {i}" for i in left]
                    logger.info(f"  {name}: {len(items) - len(left)} cleared" + (f", {len(left)} NOT cleared" if left else ""))
                if os.path.exists(CHECKPOINT):
                    shutil.move(CHECKPOINT, os.path.join(folder, os.path.basename(CHECKPOINT)))
                    logger.info("  intake checkpoint moved into the backup: the next intake reads the whole library")

    if not skip_chroma:
        print("\nChat index:")
        clear_chromadb(dry_run)

    if failures:
        print(f"\n  {len(failures)} item(s) could not be cleared — run the reset again to finish:")
        for line in failures[:50]:
            print(f"    {line}")
        return 3
    print("\n  Dry run complete." if dry_run else "\n  Reset complete.")
    if not dry_run:
        print(REBUILD)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
