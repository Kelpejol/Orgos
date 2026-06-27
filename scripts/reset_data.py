# =============================================================================
# scripts/reset_data.py — Hard-delete all SharePoint list data (except Role Register)
#                         and wipe ChromaDB collections.
#
# Usage:
#   python scripts/reset_data.py              # dry run — shows counts, no deletions
#   python scripts/reset_data.py --confirm    # live run — deletes everything
#   python scripts/reset_data.py --confirm --skip-chroma   # SharePoint only
#   python scripts/reset_data.py --confirm --chroma-only   # ChromaDB only
#
# ROLE REGISTER IS NEVER TOUCHED.
# =============================================================================

import asyncio
import logging
import shutil
import sys
import os

import httpx

# Allow running from repo root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_settings
from graph.auth import get_graph_access_token

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

settings = get_settings()

# Lists to clear — Role Register is intentionally excluded
LISTS_TO_CLEAR = [
    ("Document Register",       settings.document_register_list_id),
    ("Compliance Calendar",     settings.compliance_calendar_list_id),
    ("Contract Register",       settings.contract_register_list_id),
    ("AI Review Queue",         settings.ai_review_queue_list_id),
    ("Document Lifecycle",      settings.document_lifecycle_list_id),
    ("Control Register",        settings.control_register_list_id),
    ("Evidence Tracker",        settings.evidence_tracker_list_id),
    ("Audit Log",               settings.audit_log_list_id),
    ("Strategic Risk Register", settings.strategic_risk_register_list_id),
    ("Gap Analysis",            settings.gap_analysis_list_id),
]

# ChromaDB collections to wipe
CHROMA_COLLECTIONS = ["controls_v1", "procedures_v1"]


# =============================================================================
#  SharePoint helpers
# =============================================================================

async def _get_all_item_ids(client: httpx.AsyncClient, token: str, list_id: str) -> list[str]:
    """Fetch every item ID in a list, following @odata.nextLink pages."""
    url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/lists/{list_id}/items?$select=id&$top=999"
    )
    headers = {"Authorization": f"Bearer {token}"}
    ids: list[str] = []

    while url:
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return []  # list not provisioned yet — nothing to clear
        resp.raise_for_status()
        data = resp.json()
        ids.extend(item["id"] for item in data.get("value", []))
        url = data.get("@odata.nextLink")

    return ids


async def _hard_delete_item(client: httpx.AsyncClient, token: str, list_id: str, item_id: str) -> bool:
    """Hard-delete a single SharePoint list item via Graph API."""
    url = (
        f"{settings.graph_base_url}/sites/{settings.sharepoint_site_id}"
        f"/lists/{list_id}/items/{item_id}"
    )
    resp = await client.delete(url, headers={"Authorization": f"Bearer {token}"})
    return resp.status_code in (200, 204)


async def clear_sharepoint_list(
    client: httpx.AsyncClient,
    token: str,
    list_name: str,
    list_id: str,
    dry_run: bool,
) -> int:
    """Fetch all items in a list and hard-delete them. Returns deleted count."""
    if not settings.is_list_configured(list_id):
        logger.info(f"  {list_name}: not configured (placeholder) — skipping")
        return 0

    ids = await _get_all_item_ids(client, token, list_id)

    if not ids:
        logger.info(f"  {list_name}: 0 items — nothing to delete")
        return 0

    if dry_run:
        logger.info(f"  {list_name}: {len(ids)} items would be deleted (dry run)")
        return len(ids)

    deleted = 0
    errors  = 0
    for item_id in ids:
        ok = await _hard_delete_item(client, token, list_id, item_id)
        if ok:
            deleted += 1
        else:
            errors += 1

    status = f"{deleted} deleted"
    if errors:
        status += f", {errors} errors"
    logger.info(f"  {list_name}: {status}")
    return deleted


# =============================================================================
#  ChromaDB helpers
# =============================================================================

def clear_chromadb(dry_run: bool) -> None:
    """Delete and recreate both ChromaDB collections."""
    chroma_dir = settings.chroma_persist_dir

    if not os.path.exists(chroma_dir):
        logger.info(f"  ChromaDB: directory '{chroma_dir}' not found — nothing to clear")
        return

    if dry_run:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=chroma_dir)
            collections = client.list_collections()
            total = sum(c.count() for c in collections)
            names = [c.name for c in collections]
            logger.info(
                f"  ChromaDB: would delete {total} vectors across "
                f"{len(collections)} collection(s): {names} (dry run)"
            )
        except Exception as exc:
            logger.info(f"  ChromaDB: directory exists at '{chroma_dir}' (dry run — {exc})")
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
        logger.info(f"  ChromaDB: cleared (directory kept at '{chroma_dir}')")
    except Exception as exc:
        logger.warning(f"  ChromaDB: could not clear via client — falling back to directory wipe: {exc}")
        shutil.rmtree(chroma_dir, ignore_errors=True)
        logger.info(f"  ChromaDB: directory '{chroma_dir}' removed")


# =============================================================================
#  Main
# =============================================================================

async def main() -> None:
    args      = sys.argv[1:]
    dry_run   = "--confirm" not in args
    skip_chroma  = "--skip-chroma"  in args
    chroma_only  = "--chroma-only"  in args

    print()
    print("=" * 60)
    print("  OrgOS Data Reset")
    print("  ROLE REGISTER WILL NOT BE TOUCHED")
    print("=" * 60)

    if dry_run:
        print("\n  DRY RUN — pass --confirm to execute\n")
    else:
        print("\n  *** LIVE RUN — THIS IS IRREVERSIBLE ***\n")
        confirm = input("  Type 'yes' to proceed: ").strip().lower()
        if confirm != "yes":
            print("  Aborted.")
            return

    print()

    # ── SharePoint ────────────────────────────────────────────────
    if not chroma_only:
        print("SharePoint lists:")
        token = await get_graph_access_token()
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
            total_sp = 0
            for list_name, list_id in LISTS_TO_CLEAR:
                count = await clear_sharepoint_list(client, token, list_name, list_id, dry_run)
                total_sp += count

        action = "would be deleted" if dry_run else "deleted"
        print(f"\n  Total SharePoint items {action}: {total_sp}")

    # ── ChromaDB ──────────────────────────────────────────────────
    if not skip_chroma:
        print("\nChromaDB:")
        clear_chromadb(dry_run)

    print()
    if dry_run:
        print("  Dry run complete. Run with --confirm to execute.")
    else:
        print("  Reset complete. The app will start fresh on next load.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
