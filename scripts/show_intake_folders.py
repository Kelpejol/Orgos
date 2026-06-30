#!/usr/bin/env python3
"""
scripts/show_intake_folders.py — Show which SharePoint folder each of the
100 intaked documents came from.

Reads the intake checkpoint for drive item IDs, looks up each item's
parentReference via Graph API (no downloads), and prints a folder breakdown.

Usage:
  python3 scripts/show_intake_folders.py
"""

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from config import configure_logging, settings
from graph.auth import get_graph_access_token
from graph.client import startup, shutdown

configure_logging()
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("graph").setLevel(logging.WARNING)

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_FILE = os.path.join(_SCRIPTS_DIR, "intake_lifecycle_checkpoint.json")


async def get_headers() -> dict:
    token = await get_graph_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def resolve_compliance_drive() -> str:
    headers = await get_headers()
    base = settings.graph_base_url
    url = settings.compliance_site_url.rstrip("/")
    parts = url.replace("https://", "").split("/", 1)
    hostname, path = parts[0], (parts[1] if len(parts) > 1 else "")
    async with httpx.AsyncClient(timeout=30.0) as client:
        site_resp = await client.get(f"{base}/sites/{hostname}:/{path}", headers=headers)
        site_resp.raise_for_status()
        site_id = site_resp.json()["id"]
        drives_resp = await client.get(f"{base}/sites/{site_id}/drives", headers=headers)
        drives_resp.raise_for_status()
        drives = drives_resp.json().get("value", [])
    return next(
        (d["id"] for d in drives if d.get("name") == settings.compliance_library_name),
        drives[0]["id"] if drives else "",
    )


def parse_folder(parent_ref: dict) -> str:
    path = parent_ref.get("path", "")
    marker = f"/{settings.compliance_starting_folder}/"
    idx = path.find(marker)
    if idx >= 0:
        return path[idx + len(marker):]
    marker2 = f"/{settings.compliance_starting_folder}"
    idx2 = path.find(marker2)
    if idx2 >= 0:
        remainder = path[idx2 + len(marker2):]
        return remainder.lstrip("/") or settings.compliance_starting_folder
    return path.split("/root:/", 1)[-1] if "/root:/" in path else path


async def get_item_meta_batch(drive_id: str, item_ids: list[str]) -> dict[str, dict]:
    """Fetch parentReference for each item_id. Returns {item_id: meta}."""
    headers = await get_headers()
    results = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        for item_id in item_ids:
            try:
                resp = await client.get(
                    f"{settings.graph_base_url}/drives/{drive_id}/items/{item_id}",
                    headers=headers,
                    params={"$select": "id,name,webUrl,parentReference"},
                )
                resp.raise_for_status()
                results[item_id] = resp.json()
            except Exception as exc:
                results[item_id] = {"_error": str(exc)}
            await asyncio.sleep(0.15)  # gentle rate limiting
    return results


async def main() -> None:
    await startup()
    try:
        if not os.path.exists(CHECKPOINT_FILE):
            print("No checkpoint file found.")
            return

        with open(CHECKPOINT_FILE) as f:
            checkpoint = json.load(f)

        created = checkpoint.get("created", [])
        skipped = checkpoint.get("skipped", [])
        failed = checkpoint.get("failed", [])

        if not created:
            print("No created entries in checkpoint.")
            return

        print(f"Looking up folder info for {len(created)} created documents...\n")
        drive_id = await resolve_compliance_drive()

        drive_ids = [e["id"] for e in created]
        meta_map = await get_item_meta_batch(drive_id, drive_ids)

        # Build folder → [filenames] map
        folder_map: dict[str, list[str]] = defaultdict(list)
        errors = []
        for entry in created:
            meta = meta_map.get(entry["id"], {})
            if "_error" in meta:
                errors.append((entry["name"], meta["_error"]))
                folder_map["(lookup failed)"].append(entry["name"])
                continue
            folder = parse_folder(meta.get("parentReference", {})) or "(root)"
            folder_map[folder].append(entry["name"])

        # Print folder breakdown
        print("=" * 72)
        print(f"FOLDER BREAKDOWN — {len(created)} documents across {len(folder_map)} folders")
        print("=" * 72)
        for folder in sorted(folder_map.keys()):
            files = sorted(folder_map[folder])
            print(f"\n[{len(files)} files]  GRC MASTERY/{folder}")
            for f in files:
                print(f"  {f}")

        # Print totals
        print("\n" + "=" * 72)
        print(f"TOTALS")
        print(f"  Created:  {len(created)}")
        print(f"  Skipped:  {len(skipped)}")
        print(f"  Failed:   {len(set(e['name'] for e in failed))}")
        print("=" * 72)

    finally:
        await shutdown()


if __name__ == "__main__":
    asyncio.run(main())
