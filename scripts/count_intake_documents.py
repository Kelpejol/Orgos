#!/usr/bin/env python3
# =============================================================================
# scripts/count_intake_documents.py — SharePoint intake census (read-only)
#
# Counts every document in the Compliance library (GRC MASTERY) and reconciles
# it against the Document Lifecycle pipeline, answering:
#
#   "How many documents are in SharePoint, and how many of them are meant to
#    reach the Document Lifecycle — how many already have, how many are left?"
#
# Uses the exact same traversal, eligibility and dedup rules as
# intake_sharepoint_to_lifecycle.py, so its "remaining" number is what the
# intake run would actually pick up. Reads only — never writes anything.
#
# Usage:
#   python3 scripts/count_intake_documents.py
#   python3 scripts/count_intake_documents.py --folder "Policies & SOPs"
#   python3 scripts/count_intake_documents.py --list-remaining
#   python3 scripts/count_intake_documents.py --list-unsupported
# =============================================================================

import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict
from typing import Optional

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_SCRIPTS_DIR))   # repo root
sys.path.insert(0, _SCRIPTS_DIR)                    # allow importing the intake module

import logging

from config import configure_logging, settings
from graph.client import startup, shutdown

configure_logging()
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("graph").setLevel(logging.WARNING)

import httpx

# Reuse the intake pipeline's own logic so counts match a real run exactly.
from intake_sharepoint_to_lifecycle import (
    LEGACY_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    existing_lifecycle_keys,
    existing_register_keys,
    get_headers,
    list_folder,
    load_checkpoint,
    resolve_compliance_drive,
)

# Everything intake will create a lifecycle card for — including legacy .doc,
# which is intaken with a FORMAT finding ("convert to .docx and re-upload").
INTAKE_EXTENSIONS = set(SUPPORTED_EXTENSIONS) | set(LEGACY_EXTENSIONS)


async def walk_all_files(drive_id: str, folder_name: str, folder_id: str) -> list[dict]:
    """Like intake's walk_folder, but keeps ALL files (any extension)."""
    items = await list_folder(drive_id, folder_id)
    files: list[dict] = []
    for item in items:
        name = item.get("name", "")
        if "folder" in item:
            files.extend(await walk_all_files(drive_id, f"{folder_name}/{name}", item["id"]))
            continue
        files.append({
            "id": item["id"],
            "name": name,
            "folder_path": folder_name,
            "top_folder": folder_name.split("/", 1)[0],
            "extension": os.path.splitext(name)[1].lower(),
            "web_url": item.get("webUrl", ""),
        })
    return files


async def run_census(folder_filter: Optional[str], list_remaining: bool, list_unsupported: bool) -> None:
    await startup()
    try:
        print("\n" + "=" * 78)
        print("OrgOS — SharePoint → Document Lifecycle census  (read-only)")
        print(f"Library: {settings.compliance_library_name} / {settings.compliance_starting_folder}")
        if folder_filter:
            print(f"FOLDER FILTER: {folder_filter}")
        print("=" * 78 + "\n")

        print("Connecting to Compliance SharePoint...")
        _, drive_id = await resolve_compliance_drive()

        headers = await get_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            root_resp = await client.get(
                f"{settings.graph_base_url}/drives/{drive_id}/root:/{settings.compliance_starting_folder}",
                headers=headers,
                params={"$select": "id,name"},
            )
            root_resp.raise_for_status()
            root_id = root_resp.json()["id"]

        print("Loading Document Lifecycle and Document Register for reconciliation...")
        lifecycle_codes, lifecycle_urls = await existing_lifecycle_keys()
        register_codes, register_urls = await existing_register_keys()
        checkpoint = load_checkpoint()
        processed_ids = set(checkpoint.get("processed_ids", []))

        print("Scanning folders (this walks every subfolder)...\n")

        root_items = await list_folder(drive_id, root_id)
        root_loose_files: list[dict] = []
        all_files: list[dict] = []

        for item in root_items:
            name = item.get("name", "")
            if "folder" in item:
                if folder_filter and folder_filter.lower() not in name.lower():
                    continue
                all_files.extend(await walk_all_files(drive_id, name, item["id"]))
            elif not folder_filter:
                # Files sitting directly at the GRC MASTERY root — the intake
                # script never scans these (it only recurses into folders).
                root_loose_files.append({
                    "name": name,
                    "extension": os.path.splitext(name)[1].lower(),
                })

        # ── Classify every file the way the intake run would ─────────────────
        for f in all_files:
            f["eligible"]     = f["extension"] in INTAKE_EXTENSIONS
            f["legacy"]       = f["extension"] in LEGACY_EXTENSIONS
            f["in_lifecycle"] = bool(f["web_url"]) and f["web_url"] in lifecycle_urls
            f["in_register"]  = bool(f["web_url"]) and f["web_url"] in register_urls
            f["processed"]    = f["id"] in processed_ids
            f["remaining"]    = (
                f["eligible"]
                and not f["processed"]
                and not f["in_lifecycle"]
                and not f["in_register"]
            )

        # ── Per top-level folder breakdown ────────────────────────────────────
        by_folder: dict[str, list[dict]] = defaultdict(list)
        for f in all_files:
            by_folder[f["top_folder"]].append(f)

        header = (
            f"  {'Folder':38s} {'Total':>5s} {'Eligible':>8s} "
            f"{'In pipeline':>11s} {'Remaining':>9s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for folder in sorted(by_folder):
            fs = by_folder[folder]
            total      = len(fs)
            eligible   = sum(1 for f in fs if f["eligible"])
            in_pipe    = sum(1 for f in fs if f["eligible"] and not f["remaining"])
            remaining  = sum(1 for f in fs if f["remaining"])
            label = folder if len(folder) <= 38 else folder[:35] + "..."
            print(f"  {label:38s} {total:5d} {eligible:8d} {in_pipe:11d} {remaining:9d}")

        # ── Totals ────────────────────────────────────────────────────────────
        total_files   = len(all_files)
        eligible      = [f for f in all_files if f["eligible"]]
        legacy        = [f for f in eligible if f["legacy"]]
        unsupported   = [f for f in all_files if not f["eligible"]]
        in_lifecycle  = [f for f in eligible if f["in_lifecycle"]]
        in_register   = [f for f in eligible if f["in_register"] and not f["in_lifecycle"]]
        processed     = [f for f in eligible if f["processed"] and not f["in_lifecycle"] and not f["in_register"]]
        remaining     = [f for f in eligible if f["remaining"]]

        print("\n" + "-" * 78)
        print("Totals")
        print(f"  Files in SharePoint (all types):        {total_files}")
        print(f"  Eligible for lifecycle:                 {len(eligible)}  "
              f"(.pdf/.docx: {len(eligible) - len(legacy)}, legacy .doc: {len(legacy)})")
        print(f"    Already in Document Lifecycle (URL):  {len(in_lifecycle)}")
        print(f"    Already in Document Register (URL):   {len(in_register)}")
        print(f"    In intake checkpoint (processed):     {len(processed)}")
        print(f"    REMAINING to intake:                  {len(remaining)}")
        print(f"  Not eligible (other file types):        {len(unsupported)}")

        if legacy:
            print(f"    NOTE: legacy .doc files are intaken with a FORMAT finding — "
                  "the card asks the owner to convert to .docx and re-upload.")

        if unsupported:
            ext_counts = Counter(f["extension"] or "(none)" for f in unsupported)
            breakdown = ", ".join(f"{ext}: {n}" for ext, n in ext_counts.most_common())
            print(f"    By extension: {breakdown}")

        if root_loose_files:
            print(f"\n  ⚠ {len(root_loose_files)} file(s) sit at the {settings.compliance_starting_folder} "
                  "root, outside any folder.")
            print("    The intake script only scans folders — move these into a folder to include them:")
            for f in root_loose_files:
                print(f"      - {f['name']}")

        # Cross-check with the pipeline lists themselves
        print(f"\n  Document Lifecycle list:                "
              f"{len(lifecycle_urls)} item(s) with a file URL, {len(lifecycle_codes)} with a doc code")
        print(f"  Document Register (Active/Under Review): "
              f"{len(register_urls)} item(s) with a URL, {len(register_codes)} with a code")

        if list_remaining and remaining:
            print("\n" + "-" * 78)
            print(f"Remaining to intake ({len(remaining)}):")
            for f in sorted(remaining, key=lambda x: (x["top_folder"], x["name"])):
                tag = "  [legacy .doc — will be flagged for conversion]" if f["legacy"] else ""
                print(f"  - {f['folder_path']}/{f['name']}{tag}")

        if list_unsupported and unsupported:
            print("\n" + "-" * 78)
            print(f"Not eligible ({len(unsupported)}):")
            for f in sorted(unsupported, key=lambda x: (x["top_folder"], x["name"])):
                print(f"  - {f['folder_path']}/{f['name']}")

        print("\nRead-only census complete — nothing was created or modified.")
        if remaining:
            print(f"To intake the {len(remaining)} remaining document(s):")
            print("  python3 scripts/intake_sharepoint_to_lifecycle.py --dry-run")
            print("  python3 scripts/intake_sharepoint_to_lifecycle.py")
        print()

    finally:
        await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Count SharePoint compliance documents and reconcile against the Document Lifecycle (read-only).",
    )
    parser.add_argument("--folder", type=str, default=None,
                        help="Only count one top-level folder (substring match), e.g. --folder 'Policies'")
    parser.add_argument("--list-remaining", action="store_true",
                        help="List every file still waiting to be intaken")
    parser.add_argument("--list-unsupported", action="store_true",
                        help="List every file skipped for its file type")
    args = parser.parse_args()
    asyncio.run(run_census(args.folder, args.list_remaining, args.list_unsupported))


if __name__ == "__main__":
    main()
