#!/usr/bin/env python3
# =============================================================================
# scripts/fix_intake_types.py — correct the document type of intake items
#
# Intake used to guess a document's type from loose text in its folder and file
# name ('form' matched 'Information', so every document in the Control of
# Documented Information folder became a Form). The type is now read from the
# document code. This corrects the Lifecycle items already created and still
# in Review. Approved items are never touched.
#
#   python scripts/fix_intake_types.py           # dry run — lists the changes
#   python scripts/fix_intake_types.py --apply
# =============================================================================

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run(apply: bool) -> int:
    from config import settings
    from graph.client import get_list_items, shutdown, startup, update_list_item
    from scripts.intake_sharepoint_to_lifecycle import document_type_from_code

    await startup()
    try:
        items = await get_list_items(settings.document_lifecycle_list_id, "Document Lifecycle")
        changes = []
        for item in items:
            f = item.get("fields") or {}
            if f.get("Stage") != "Review" or f.get("ApprovalStatus") == "Approved":
                continue
            want = document_type_from_code(f.get("DocumentCode") or "")
            have = (f.get("DocumentType") or "").strip()
            if want and want != have:
                changes.append((str(item["id"]), f.get("DocumentCode"), have, want))
        for _, code, have, want in changes:
            print(f"  {code}: {have or '(none)'} → {want}")
        print(f"{len(changes)} item(s) to correct.")
        if not apply:
            print("Dry run — nothing written. Re-run with --apply.")
            return 0
        for item_id, _, _, want in changes:
            await update_list_item(settings.document_lifecycle_list_id, "Document Lifecycle",
                                   item_id, {"DocumentType": want})
        print(f"Corrected {len(changes)}.")
        return 0
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args().apply)))
