# scripts/rerun_cdi_checks.py — Re-run the CDI check on Document Lifecycle items.
#
# Use after the CDI checker logic improves (smarter deterministic rules,
# AI second-opinion) so stored CDIStatus / CDIFailures reflect the current
# checker rather than whichever version ran at intake time.
#
# For every lifecycle item whose SharePointFileUrl points into the compliance
# library: download the file, run run_cdi_check with the item's DocumentCode,
# and PATCH CDIStatus + CDIFailures (and Trigger, matching intake semantics:
# "CDI Fix" when failed, "SharePoint Intake" otherwise).
#
# Usage:
#   python scripts/rerun_cdi_checks.py --dry-run     (report, no writes)
#   python scripts/rerun_cdi_checks.py               (apply)
#   python scripts/rerun_cdi_checks.py --only-failed (skip items already Passed)

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from config import settings
from graph.auth import get_graph_access_token
from graph.client import get_list_items, shutdown, startup, update_list_item
from agents.cdi_checker.service import run_cdi_check

logger = logging.getLogger("rerun_cdi")

LIFECYCLE_LIST_NAME = "Document Lifecycle"


def cdi_failures_json(checks: list[dict]) -> str:
    """Same shape the intake script stores: failed checks only."""
    failed = [
        {
            "check": c.get("check_id", ""),
            "detail": str(c.get("detail", ""))[:400],
            "fix": str(c.get("proposed_fix", ""))[:400],
        }
        for c in checks
        if c.get("result") == "FAIL"
    ]
    return json.dumps(failed) if failed else ""


async def fetch_role_titles() -> list[str]:
    if not settings.is_list_configured(settings.role_register_list_id):
        return []
    try:
        items = await get_list_items(settings.role_register_list_id, "Role Register")
        return [
            i["fields"]["Title"]
            for i in items
            if i.get("fields", {}).get("Title")
        ]
    except Exception as exc:
        logger.warning(f"Could not load Role Register titles: {exc}")
        return []


async def resolve_drive(client: httpx.AsyncClient, headers: dict) -> str:
    url = settings.compliance_site_url.rstrip("/")
    hostname, _, path = url.replace("https://", "").partition("/")
    r = await client.get(f"{settings.graph_base_url}/sites/{hostname}:/{path}", headers=headers)
    r.raise_for_status()
    site_id = r.json()["id"]
    r = await client.get(f"{settings.graph_base_url}/sites/{site_id}/drives", headers=headers)
    r.raise_for_status()
    for d in r.json().get("value", []):
        if d.get("name") == settings.compliance_library_name:
            return d["id"]
    raise RuntimeError(f"Drive '{settings.compliance_library_name}' not found")


def filename_from_url(url: str) -> str:
    decoded = urllib.parse.unquote(url.split("?", 1)[0])
    return decoded.rstrip("/").rsplit("/", 1)[-1]


async def main(dry_run: bool, only_failed: bool) -> None:
    await startup()
    try:
        role_titles = await fetch_role_titles()
        print(f"Role Register titles loaded: {len(role_titles)}")

        items = await get_list_items(settings.document_lifecycle_list_id, LIFECYCLE_LIST_NAME)
        print(f"Lifecycle items: {len(items)}")

        token = await get_graph_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        stats = {"Passed": 0, "Failed": 0, "Error": 0, "skipped": 0}
        rescued_total = 0

        async with httpx.AsyncClient(timeout=120.0) as client:
            drive_id = await resolve_drive(client, headers)

            for i, item in enumerate(items, 1):
                f = item.get("fields", {})
                title = str(f.get("Title", ""))[:52]
                url = str(f.get("SharePointFileUrl") or "")
                old_status = str(f.get("CDIStatus", ""))

                if only_failed and old_status == "Passed":
                    stats["skipped"] += 1
                    continue
                if not url:
                    stats["skipped"] += 1
                    print(f"[{i}/{len(items)}] {title:<52} SKIP (no file URL)")
                    continue

                filename = filename_from_url(url)
                path = f"{settings.compliance_starting_folder}/{filename}"
                try:
                    # refresh token lazily — long runs outlive the first one
                    token = await get_graph_access_token()
                    headers = {"Authorization": f"Bearer {token}"}
                    dl = await client.get(
                        f"{settings.graph_base_url}/drives/{drive_id}/root:/{path}:/content",
                        headers=headers,
                        follow_redirects=True,
                    )
                    dl.raise_for_status()
                except Exception as exc:
                    stats["Error"] += 1
                    print(f"[{i}/{len(items)}] {title:<52} DOWNLOAD FAILED: {str(exc)[:60]}")
                    continue

                result = await run_cdi_check(
                    dl.content, filename, str(f.get("DocumentCode", "")), role_titles
                )
                if result.get("error"):
                    new_status = "Error"
                    failures = json.dumps([{
                        "check": "CDI",
                        "detail": result["error"],
                        "fix": "Fix the parsing issue, then upload the controlled version in Review.",
                    }])
                elif result.get("passed"):
                    new_status, failures = "Passed", ""
                else:
                    new_status = "Failed"
                    failures = cdi_failures_json(result.get("checks", []))

                rescued = sum(
                    1 for c in result.get("checks", [])
                    if str(c.get("note", "")).startswith("Confirmed by AI review")
                )
                rescued_total += rescued
                stats[new_status] += 1

                change = f"{old_status or '—'} → {new_status}"
                extra = f" | AI-rescued {rescued} check(s)" if rescued else ""
                print(f"[{i}/{len(items)}] {title:<52} {change}"
                      f" ({result.get('pass_count', 0)}/{result.get('total_checks', 0)}){extra}")

                if not dry_run:
                    fields = {
                        "CDIStatus": new_status,
                        "CDIFailures": failures,
                        "Trigger": "CDI Fix" if new_status == "Failed" else "SharePoint Intake",
                    }
                    await update_list_item(
                        settings.document_lifecycle_list_id, LIFECYCLE_LIST_NAME,
                        item["id"], fields,
                    )

        print("\n" + "=" * 70)
        print("DRY RUN — nothing written" if dry_run else "APPLIED")
        print(f"  Passed:  {stats['Passed']}")
        print(f"  Failed:  {stats['Failed']}")
        print(f"  Error:   {stats['Error']}")
        print(f"  Skipped: {stats['skipped']}")
        print(f"  Checks rescued by AI second-opinion: {rescued_total}")
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-failed", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(dry_run=args.dry_run, only_failed=args.only_failed))
