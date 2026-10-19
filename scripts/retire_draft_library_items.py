#!/usr/bin/env python3
# =============================================================================
# scripts/retire_draft_library_items.py — one-off: retire review items raised
# from the library folder's drafts
#
# Before controls entered through approval (control_register/approved_library
# .py), the library sync read every file in ORGOS CONTROL LIBRARY — all of
# them drafts. Its review items still pending are retired here as Superseded,
# with a note saying why. Decided items, and items from the old extractor, are
# left alone. Each document's controls come back for review when it is
# approved in Document Lifecycle.
#
#   python scripts/retire_draft_library_items.py           # dry run
#   python scripts/retire_draft_library_items.py --apply
# =============================================================================

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NOTE = ("Raised from a draft in the library folder, before controls entered through "
        "approval. This document's controls are raised again when it is approved in "
        "Document Lifecycle.")


def from_library_sync(fields: dict) -> bool:
    # Zone 1 definitions carry their candidate; Zone 2 findings a resolution key.
    return bool(fields.get("CandidateJson") or fields.get("ResolutionKey"))


async def run(apply: bool) -> int:
    from config import settings
    from control_register.sync import PENDING
    from graph.bulk import print_progress, run_writes
    from graph.client import get_list_items, shutdown, startup, update_list_item

    await startup()
    try:
        queue = await get_list_items(settings.ai_review_queue_list_id, "AI Review Queue")
        retire = [i for i in queue
                  if from_library_sync(i.get("fields") or {})
                  and ((i.get("fields") or {}).get("ReviewStatus") or "").strip() in PENDING]
        by_doc = Counter((i["fields"].get("SourceDocumentCode") or "?") for i in retire)
        print(f"{len(retire)} pending item(s) from the library sync to retire:")
        for doc, n in by_doc.most_common():
            print(f"  {n:4}  {doc}")
        if not apply:
            print("\nDry run — nothing written. Re-run with --apply to retire them.")
            return 0
        writes = [(str(i["id"]), (lambda i=i: update_list_item(
            settings.ai_review_queue_list_id, "AI Review Queue", str(i["id"]),
            {"ReviewStatus": "Superseded", "CascadeResult": NOTE}))) for i in retire]
        failures = await run_writes(writes, progress=print_progress("retired"))
        for line in failures[:20]:
            print(f"  FAILED {line}")
        print(f"Retired {len(retire) - len(failures)}.")
        return 1 if failures else 0
    finally:
        await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    sys.exit(asyncio.run(run(parser.parse_args().apply)))


if __name__ == "__main__":
    main()
