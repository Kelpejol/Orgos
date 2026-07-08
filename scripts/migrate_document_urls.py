# scripts/migrate_document_urls.py — One-time URL migration after library move.
#
# The compliance library moved from
#   https://dragnetnigeria.sharepoint.com/sites/compliance  (library "Documents")
# to
#   https://dragnetnigeria.sharepoint.com/sites/everybody   (library "DRAGNET DOCUMENT REPOSITORY")
#
# Stored URLs in the SharePoint lists still point at the old location, and the
# intake script dedupes by URL — so without this migration a re-run would
# re-intake every file as a duplicate.
#
# What it does:
#   1. Walks the NEW library's GRC MASTERY folder and builds
#      relative-path → webUrl and filename → webUrl maps.
#   2. Scans four lists for URLs pointing at the old site:
#        Document Lifecycle . SharePointFileUrl
#        Document Register  . SharePointUrl
#        Evidence Tracker   . EvidenceLink
#        AI Review Queue    . SourceDocumentUrl
#   3. Matches each old URL to a real file in the new library
#      (by relative path under GRC MASTERY first, then by filename)
#      and patches the list item. URLs are only ever rewritten to a
#      webUrl that was actually observed in the new library.
#
# Usage:
#   python scripts/migrate_document_urls.py --dry-run   (preview, no writes)
#   python scripts/migrate_document_urls.py             (apply)

import argparse
import asyncio
import logging
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from config import settings
from graph.auth import get_graph_access_token
from graph.client import get_list_items, shutdown, startup, update_list_item

logger = logging.getLogger("migrate_document_urls")

OLD_SITE_MARKERS = [
    "dragnetnigeria.sharepoint.com/sites/compliance",
]

STARTING_FOLDER = settings.compliance_starting_folder  # "GRC MASTERY"

# Files renamed during the library move: old relpath (lowercase) → new relpath
# (lowercase) under the starting folder. Verified manually against both libraries.
RENAMED_FILES = {
    "audit & risks/iso internal audit report/dragnet 2025 isms internal audit report.pdf":
        "audit & risks/iso internal audit report/drg 2025 isms internal audit report.pdf",
}

# (label, list_id_attr, list_name, url_field)
TARGETS = [
    ("Document Lifecycle", "document_lifecycle_list_id", "Document Lifecycle", "SharePointFileUrl"),
    ("Document Register", "document_register_list_id", "Document Register", "SharePointUrl"),
    ("Evidence Tracker", "evidence_tracker_list_id", "Evidence Tracker", "EvidenceLink"),
    ("AI Review Queue", "ai_review_queue_list_id", "AI Review Queue", "SourceDocumentUrl"),
]


async def _headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}"}


async def resolve_new_drive() -> str:
    url = settings.compliance_site_url.rstrip("/")
    hostname, _, path = url.replace("https://", "").partition("/")
    headers = await _headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{settings.graph_base_url}/sites/{hostname}:/{path}", headers=headers
        )
        resp.raise_for_status()
        site_id = resp.json()["id"]
        resp = await client.get(
            f"{settings.graph_base_url}/sites/{site_id}/drives", headers=headers
        )
        resp.raise_for_status()
        drives = resp.json().get("value", [])
    for drive in drives:
        if drive.get("name") == settings.compliance_library_name:
            return drive["id"]
    raise RuntimeError(
        f"Drive '{settings.compliance_library_name}' not found. "
        f"Available: {[d.get('name') for d in drives]}"
    )


async def walk_new_library(drive_id: str) -> tuple[dict, dict]:
    """Return (relpath → webUrl, filename → [webUrl, ...]) for every file
    under the starting folder in the new library."""
    by_relpath: dict[str, str] = {}
    by_name: dict[str, list[str]] = {}
    headers = await _headers()

    async with httpx.AsyncClient(timeout=60.0) as client:
        async def walk(item_path: str, rel_prefix: str) -> None:
            url = (
                f"{settings.graph_base_url}/drives/{drive_id}/root:/{item_path}:/children"
                "?$select=id,name,folder,file,webUrl&$top=200"
            )
            while url:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("value", []):
                    name = item["name"]
                    rel = f"{rel_prefix}{name}"
                    if "folder" in item:
                        await walk(f"{item_path}/{name}", f"{rel}/")
                    else:
                        by_relpath[rel.lower()] = item["webUrl"]
                        by_name.setdefault(name.lower(), []).append(item["webUrl"])
                url = data.get("@odata.nextLink")

        await walk(STARTING_FOLDER, "")

    return by_relpath, by_name


def is_old_url(url: str) -> bool:
    return any(marker in url for marker in OLD_SITE_MARKERS)


def old_url_to_relpath(url: str) -> str | None:
    """Extract the path relative to the starting folder from an old webUrl."""
    decoded = urllib.parse.unquote(url.split("?", 1)[0])
    marker = f"/{STARTING_FOLDER}/"
    idx = decoded.find(marker)
    if idx == -1:
        return None
    return decoded[idx + len(marker):].strip("/")


def _filename_from_url(old_url: str, relpath: str | None) -> str | None:
    """Best-effort filename: relpath tail, `file=` query param (Doc.aspx
    web-viewer links), or the URL path tail."""
    if relpath:
        return relpath.rsplit("/", 1)[-1]
    query = urllib.parse.urlparse(old_url).query
    file_param = urllib.parse.parse_qs(query).get("file", [])
    if file_param:
        return file_param[0].strip()
    decoded = urllib.parse.unquote(old_url.split("?", 1)[0])
    tail = decoded.rstrip("/").rsplit("/", 1)[-1]
    return tail if "." in tail and not tail.lower().endswith(".aspx") else None


def match_new_url(old_url: str, by_relpath: dict, by_name: dict) -> tuple[str | None, str]:
    """Return (new_url or None, how)."""
    relpath = old_url_to_relpath(old_url)
    if relpath:
        key = RENAMED_FILES.get(relpath.lower(), relpath.lower())
        if key in by_relpath:
            return by_relpath[key], "relpath" if key == relpath.lower() else "renamed"

    filename = _filename_from_url(old_url, relpath)
    candidates = by_name.get(filename.lower(), []) if filename else []
    if len(candidates) == 1:
        return candidates[0], "filename"
    if len(candidates) > 1:
        return None, f"AMBIGUOUS:{filename.lower()}"
    return None, "no match in new library"


async def migrate(dry_run: bool) -> None:
    print("Resolving new compliance library…")
    drive_id = await resolve_new_drive()
    print(f"  drive_id = {drive_id}")

    print(f"Walking '{STARTING_FOLDER}' in the new library…")
    by_relpath, by_name = await walk_new_library(drive_id)
    print(f"  {len(by_relpath)} files found in new library\n")

    total_patched = total_unmatched = total_skipped = 0

    for label, attr, list_name, url_field in TARGETS:
        list_id = getattr(settings, attr)
        if not settings.is_list_configured(list_id):
            print(f"[{label}] list not configured — skipping")
            continue

        items = await get_list_items(list_id, list_name)
        old_items = []
        for item in items:
            url = str(item.get("fields", {}).get(url_field) or "").strip()
            if url and is_old_url(url):
                old_items.append((item, url))

        print(f"[{label}] {len(items)} items, {len(old_items)} with old URLs in {url_field}")

        # First pass: resolve what we can directly; group ambiguous ones by filename.
        resolved: list[tuple[dict, str, str, str]] = []   # (item, old_url, new_url, how)
        ambiguous: dict[str, list[tuple[dict, str]]] = {}
        for item, old_url in old_items:
            new_url, how = match_new_url(old_url, by_relpath, by_name)
            if new_url:
                resolved.append((item, old_url, new_url, how))
            elif how.startswith("AMBIGUOUS:"):
                ambiguous.setdefault(how.split(":", 1)[1], []).append((item, old_url))
            else:
                resolved.append((item, old_url, "", how))

        # Second pass: the same filename existing N times in the new library with
        # N list items referencing it means the library holds N genuine copies.
        # Pair them one-to-one (stable order) so every copy's URL ends up stored —
        # which is what the intake dedupe needs to skip all of them.
        for filename, group in ambiguous.items():
            candidates = sorted(by_name.get(filename, []))
            group = sorted(group, key=lambda pair: int(pair[0]["id"]))
            if len(group) == len(candidates):
                for (item, old_url), new_url in zip(group, candidates):
                    resolved.append((item, old_url, new_url, "paired duplicate copy"))
            else:
                for item, old_url in group:
                    resolved.append((
                        item, old_url, "",
                        f"ambiguous — {len(candidates)} copies vs {len(group)} items",
                    ))

        for item, old_url, new_url, how in sorted(resolved, key=lambda r: int(r[0]["id"])):
            fields = item.get("fields", {})
            ident = (
                fields.get("DocumentCode")
                or fields.get("Title")
                or f"item {item['id']}"
            )
            if not new_url:
                print(f"  ✗ #{item['id']:>4} {str(ident)[:50]:<50} UNMATCHED — {how}")
                total_unmatched += 1
                continue
            if dry_run:
                print(f"  ~ #{item['id']:>4} {str(ident)[:50]:<50} would patch ({how})")
            else:
                await update_list_item(list_id, list_name, item["id"], {url_field: new_url})
                print(f"  ✓ #{item['id']:>4} {str(ident)[:50]:<50} patched ({how})")
            total_patched += 1

        total_skipped += len(items) - len(old_items)
        print()

    mode = "DRY RUN — nothing written" if dry_run else "APPLIED"
    print("=" * 70)
    print(f"{mode}")
    print(f"  URLs {'to patch' if dry_run else 'patched'}: {total_patched}")
    print(f"  Unmatched (need manual review): {total_unmatched}")
    print(f"  Items already fine / no URL:    {total_skipped}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    async def run() -> None:
        await startup()
        try:
            await migrate(dry_run=args.dry_run)
        finally:
            await shutdown()

    asyncio.run(run())


if __name__ == "__main__":
    main()
