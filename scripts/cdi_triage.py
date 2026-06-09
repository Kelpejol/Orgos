# =============================================================================
# scripts/cdi_triage.py — Phase 0 CDI Triage
# Walks all documents in GRC MASTERY, runs CDI Checker on each,
# sorts documents into three piles:
#   PASS  → creates Document Register entry directly
#   FAIL  → creates Document Lifecycle entry with CDI failures listed
#
# Usage:
#   python scripts/cdi_triage.py --dry-run
#   python scripts/cdi_triage.py --folder "Policies & SOPs" --limit 5
#   python scripts/cdi_triage.py --folder "Policies & SOPs"
#   python scripts/cdi_triage.py --reset
#
# Checkpoint: scripts/cdi_triage_checkpoint.json
# =============================================================================

import asyncio
import argparse
import json
import logging
import os
import sys
from datetime import date
from typing import Optional


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from config import settings, configure_logging
from graph.auth import get_graph_access_token
from graph.client import startup, shutdown, create_list_item, get_list_items
from agents.cdi_checker.service import run_cdi_check, extract_text

configure_logging()
logger = logging.getLogger(__name__)

CHECKPOINT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "cdi_triage_checkpoint.json"
)
SUPPORTED = {".pdf", ".docx", ".doc"}


# =============================================================================
#  Checkpoint
# =============================================================================

def load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_FILE):
        return {"processed_ids": [], "passed": [], "failed": [], "pass_count": 0, "fail_count": 0}
    try:
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    except Exception:
        return {"processed_ids": [], "passed": [], "failed": [], "pass_count": 0, "fail_count": 0}


def save_checkpoint(state: dict) -> None:
    try:
        with open(CHECKPOINT_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as exc:
        logger.warning(f"Could not save checkpoint: {exc}")


def reset_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("CDI triage checkpoint cleared.\n")


# =============================================================================
#  SharePoint helpers
# =============================================================================

async def get_headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def resolve_drive() -> tuple[str, str]:
    headers = await get_headers()
    base    = settings.graph_base_url
    url     = settings.compliance_site_url.rstrip("/")
    parts   = url.replace("https://", "").split("/", 1)
    hostname, path = parts[0], parts[1] if len(parts) > 1 else ""
    async with httpx.AsyncClient(timeout=30.0) as client:
        site = await client.get(f"{base}/sites/{hostname}:/{path}", headers=headers)
        site.raise_for_status()
        site_id = site.json()["id"]
        drives  = await client.get(f"{base}/sites/{site_id}/drives", headers=headers)
        drives.raise_for_status()
        drive_list = drives.json().get("value", [])
        drive_id = next(
            (d["id"] for d in drive_list if d.get("name") == settings.compliance_library_name),
            drive_list[0]["id"] if drive_list else None,
        )
    return site_id, drive_id


async def list_folder(drive_id: str, folder_id: Optional[str] = None) -> list[dict]:
    headers = await get_headers()
    url = (
        f"{settings.graph_base_url}/drives/{drive_id}/items/{folder_id}/children"
        if folder_id
        else f"{settings.graph_base_url}/drives/{drive_id}/root/children"
    )
    items = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        while url:
            resp = await client.get(url, headers=headers,
                                    params={"$top": 200, "$select": "id,name,size,folder,file,webUrl"})
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
    return items


async def walk_folder(drive_id: str, folder_name: str, folder_id: Optional[str] = None) -> list[dict]:
    items = await list_folder(drive_id, folder_id)
    files = []
    for item in items:
        name = item.get("name", "")
        if "folder" in item:
            sub = await walk_folder(drive_id, f"{folder_name}/{name}", item["id"])
            files.extend(sub)
        else:
            ext = os.path.splitext(name)[1].lower()
            if ext in SUPPORTED:
                files.append({
                    "id":          item["id"],
                    "name":        name,
                    "folder_path": folder_name,
                    "extension":   ext,
                    "web_url":     item.get("webUrl", ""),
                })
    return files


async def download_file(drive_id: str, item_id: str) -> bytes:
    headers = await get_headers()
    url = f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}/content"
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content


async def fetch_role_titles() -> list[str]:
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [i.get("fields", {}).get("Title", "") for i in items if i.get("fields", {}).get("Title")]
    except Exception:
        return []


async def resolve_owner_by_email(email: str) -> tuple[str, str]:
    """
    Resolve a Microsoft 365 email to (entra_oid, display_name) via Graph API.
    Returns ("", "") if the email cannot be resolved — lifecycle entry will
    fall back to showing 'System (CDI Triage)' and remain reassignable.
    """
    if not email:
        return "", ""
    try:
        headers = await get_headers()
        url = f"{settings.graph_base_url}/users/{email}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            oid  = data.get("id", "")
            name = data.get("displayName", "") or data.get("userPrincipalName", email)
            return oid, name
    except Exception as exc:
        logger.warning(f"Could not resolve owner email '{email}': {exc}")
        return "", ""


# =============================================================================
#  Create entries on pass/fail
# =============================================================================

async def create_document_register_entry(
    filename: str,
    doc_code: str,
    web_url: str,
    owner_oid: str = "",
    owner_name: str = "",
) -> None:
    """CDI PASS — document enters Document Register directly."""
    fields: dict = {
        "Title":         filename,
        "DocumentCode":  doc_code,
        "Status":        "Active",
        "EffectiveDate": date.today().isoformat(),
        "SharePointUrl": web_url,
        "Source":        "CDI Triage Phase 0",
    }
    if owner_oid:
        fields["OwnerEntraId"] = owner_oid
    if owner_name:
        fields["Owner"] = owner_name
    try:
        await create_list_item(settings.document_register_list_id, "Document Register", fields)
        logger.info(f"Document Register entry created for: {doc_code}")
    except Exception as exc:
        logger.error(f"Failed to create Document Register entry for {doc_code}: {exc}")


async def create_lifecycle_entry(
    filename: str,
    doc_code: str,
    web_url: str,
    cdi_failures: list[dict],
    owner_oid: str = "",
    owner_name: str = "",
) -> None:
    """CDI FAIL — document enters Document Lifecycle with failures listed."""
    failures_json = json.dumps([
        {
            "check":  f["check_id"],
            "detail": f["finding"],
            "fix":    f.get("proposed_fix", ""),
        }
        for f in cdi_failures if f["result"] == "FAIL"
    ])

    # Use the supplied owner if available; fall back to a meaningful system label
    # so the card shows "System (CDI Triage)" rather than "Unassigned" and the
    # amber Claim/Reassign button appears for anyone to pick it up.
    effective_owner_name = owner_name or "System (CDI Triage)"

    fields: dict = {
        "Title":             filename,
        "DocumentCode":      doc_code,
        "Stage":             "Review",
        "Trigger":           "CDI Fix",
        "AIGenerated":       False,
        "Revised":           True,   # file is already in SharePoint — it IS the revised version
        "CDIFailures":       failures_json,
        "SharePointFileUrl": web_url,
        "Owner":             effective_owner_name,
        "Notes": (
            f"Entered via Phase 0 CDI triage. "
            f"{len([f for f in cdi_failures if f['result'] == 'FAIL'])} CDI failures to resolve."
        ),
    }
    if owner_oid:
        fields["OwnerEntraId"] = owner_oid

    try:
        await create_list_item(settings.document_lifecycle_list_id, "Document Lifecycle", fields)
        logger.info(f"Document Lifecycle entry created for: {doc_code} ({len(cdi_failures)} failures)")
    except Exception as exc:
        logger.error(f"Failed to create Lifecycle entry for {doc_code}: {exc}")


# =============================================================================
#  Main
# =============================================================================


async def run_triage(
    folder_filter: Optional[str] = None,
    dry_run: bool = False,
    limit: Optional[int] = None,
    owner_email: Optional[str] = None,
) -> None:
    await startup()

    checkpoint    = load_checkpoint()
    processed_ids = set(checkpoint.get("processed_ids", []))

    print("\n" + "="*60)
    print("OrgOS — CDI Triage (Phase 0)")
    if dry_run:       print("MODE: DRY RUN")
    if folder_filter: print(f"FOLDER FILTER: {folder_filter}")
    if limit:         print(f"BATCH LIMIT: {limit}")
    if owner_email:   print(f"OWNER EMAIL: {owner_email}")
    if processed_ids: print(f"RESUMING — {len(processed_ids)} already processed")
    print("="*60 + "\n")

    try:
        print("Connecting to Compliance SharePoint...")
        site_id, drive_id = await resolve_drive()
        role_titles        = await fetch_role_titles()
        print(f"Connected. {len(role_titles)} roles loaded from Role Register.\n")

        # Resolve the owner who triggered this triage run
        owner_oid, owner_name = await resolve_owner_by_email(owner_email or "")
        if owner_email and owner_oid:
            print(f"Owner resolved: {owner_name} ({owner_oid})\n")
        elif owner_email:
            print(f"WARNING: Could not resolve '{owner_email}' — lifecycle entries will show 'System (CDI Triage)'\n")

        # Find root folder
        headers = await get_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            root_resp = await client.get(
                f"{settings.graph_base_url}/drives/{drive_id}/root:/{settings.compliance_starting_folder}",
                headers=headers, params={"$select": "id,name"},
            )
            root_resp.raise_for_status()
            root_id = root_resp.json()["id"]

        # Walk folders
        all_files = []
        top_items = await list_folder(drive_id, root_id)
        for item in top_items:
            if "folder" not in item:
                continue
            folder_name = item["name"]
            if folder_filter and folder_filter.lower() not in folder_name.lower():
                continue
            folder_files = await walk_folder(drive_id, folder_name, item["id"])
            all_files.extend(folder_files)

        remaining = [f for f in all_files if f["id"] not in processed_ids]
        if limit:
            remaining = remaining[:limit]

        print(f"Files found:     {len(all_files)}")
        print(f"Already done:    {len(processed_ids)}")
        print(f"This batch:      {len(remaining)}\n")

        passed_count = 0
        failed_count = 0

        for i, file_info in enumerate(remaining, 1):
            filename    = file_info["name"]
            file_id     = file_info["id"]
            web_url     = file_info.get("web_url", "")
            doc_code    = os.path.splitext(filename)[0].upper().replace(" ", "-").replace("_", "-")[:60]
            prefix      = f"[{i}/{len(remaining)}]"

            print(f"  {prefix} {filename[:55]}")

            if dry_run:
                processed_ids.add(file_id)
                checkpoint["processed_ids"] = list(processed_ids)
                save_checkpoint(checkpoint)
                continue

            try:
                file_bytes = await download_file(drive_id, file_id)
                result     = await run_cdi_check(file_bytes, filename, doc_code, role_titles)

                if result.get("error"):
                    print(f"              → ERROR: {result['error']}")
                    processed_ids.add(file_id)
                elif result["passed"]:
                    print(f"              → PASS  ({result['pass_count']}/{result['total_checks']} checks)")
                    await create_document_register_entry(
                        filename, doc_code, web_url,
                        owner_oid=owner_oid, owner_name=owner_name,
                    )
                    passed_count += 1
                else:
                    fails = [c for c in result["checks"] if c["result"] == "FAIL"]
                    print(f"              → FAIL  ({result['fail_count']} failures — enters Lifecycle for fix)")
                    await create_lifecycle_entry(
                        filename, doc_code, web_url, fails,
                        owner_oid=owner_oid, owner_name=owner_name,
                    )
                    failed_count += 1

                processed_ids.add(file_id)
                checkpoint["processed_ids"] = list(processed_ids)
                checkpoint["pass_count"]    = checkpoint.get("pass_count", 0) + (1 if result.get("passed") else 0)
                checkpoint["fail_count"]    = checkpoint.get("fail_count", 0) + (0 if result.get("passed") else 1)
                save_checkpoint(checkpoint)

            except Exception as exc:
                print(f"              → EXCEPTION: {str(exc)[:60]}")
                logger.exception(f"CDI triage error for {filename}")

            await asyncio.sleep(1)

        print(f"\n{'='*60}")
        print("BATCH COMPLETE")
        print(f"  Passed (→ Document Register):   {passed_count}")
        print(f"  Failed (→ Document Lifecycle):  {failed_count}")
        remaining_after = len(all_files) - len(processed_ids)
        if remaining_after > 0:
            print(f"  Still remaining: {remaining_after}")
        print("="*60 + "\n")

    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="CDI Triage — Phase 0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/cdi_triage.py --owner-email you@dragnet-solutions.com
  python scripts/cdi_triage.py --owner-email you@dragnet-solutions.com --folder "Policies"
  python scripts/cdi_triage.py --dry-run
  python scripts/cdi_triage.py --reset
        """,
    )
    parser.add_argument("--dry-run",     action="store_true",
                        help="Preview files without running checks or creating entries")
    parser.add_argument("--folder",      type=str, default=None,
                        help="Only process files in folders matching this name")
    parser.add_argument("--limit",       type=int, default=None,
                        help="Stop after processing this many files")
    parser.add_argument("--reset",       action="store_true",
                        help="Clear the checkpoint file and start fresh")
    parser.add_argument("--owner-email", type=str, default=None,
                        help="M365 email of the person running the triage. "
                             "Lifecycle entries created for CDI-failing docs will be "
                             "attributed to this person so they appear on their "
                             "Review column and can be reassigned. "
                             "E.g. --owner-email firstname.lastname@dragnet-solutions.com")
    args = parser.parse_args()

    if args.reset:
        reset_checkpoint()

    asyncio.run(run_triage(
        folder_filter=args.folder,
        dry_run=args.dry_run,
        limit=args.limit,
        owner_email=args.owner_email,
    ))