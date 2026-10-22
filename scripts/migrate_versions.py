#!/usr/bin/env python3
# =============================================================================
# scripts/migrate_versions.py — one version number, written plain
#
# OrgOS used to write a document's version in the Document Register as "R01",
# "R02"… while its cover said "01", "02". CDI has one field, Version, with no
# "R" (§14). New approvals write it plain; this rewrites the entries that
# already carry the old form. Nothing else about an entry changes.
#
#   python scripts/migrate_versions.py           # dry run — lists every change
#   python scripts/migrate_versions.py --apply
# =============================================================================

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def migrated(value: str) -> str:
    """'R02' → '02'. Anything that is not an old R-version is left exactly as it is."""
    from lifecycle.versioning import display_version, parse_version
    text = str(value or "").strip()
    if text[:1].lower() == "r" and parse_version(text) is not None:
        return display_version(text)
    return text


async def run(apply: bool) -> int:
    from config import settings
    from graph.client import get_list_items, shutdown, startup, update_list_item

    await startup()
    try:
        rows = await get_list_items(settings.document_register_list_id, "Document Register")
        changes = []
        for row in rows:
            f = row.get("fields") or {}
            old = str(f.get("CurrentVersion") or "").strip()
            new = migrated(old)
            if old and new != old:
                changes.append((str(row["id"]), f.get("DocumentCode") or f.get("Title") or "?", old, new))
        for _, code, old, new in changes:
            print(f"  {code}: {old} → {new}")
        print(f"{len(changes)} of {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} to change.")
        if not apply:
            print("Dry run — nothing written. Re-run with --apply.")
            return 0
        for item_id, _, _, new in changes:
            await update_list_item(settings.document_register_list_id, "Document Register", item_id,
                                   {"CurrentVersion": new})
        print(f"Changed {len(changes)}.")
        return 0
    finally:
        await shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    sys.exit(asyncio.run(run(parser.parse_args().apply)))
