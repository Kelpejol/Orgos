# scripts/rerun_cdi_checks.py — check every open Lifecycle document again, with the current rules.
#
# Use after the checks change (or after a restore), so each card's stored result, and the code,
# title, type, department and standards it carries, are what the CURRENT checks read from the
# document's file. It does exactly what OrgOS does when a file changes in SharePoint
# (lifecycle/router.py::_sync_with_file, forced): the CDI checks, the role check, the code, title,
# type and standards re-read from the file, and the card's FileState recorded. The file itself is
# never changed. Approved documents are skipped.
#
#   python scripts/rerun_cdi_checks.py --dry-run     (lists the cards, writes nothing)
#   python scripts/rerun_cdi_checks.py               (check them all again)
#   python scripts/rerun_cdi_checks.py --limit 8     (first 8 only)

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
from graph.client import get_list_items, shutdown, startup

logger = logging.getLogger("rerun_cdi")


async def run(dry_run: bool, limit: int | None) -> int:
    from lifecycle.router import _LIST_NAME, _get_list_id, _sync_with_file

    await startup()
    try:
        if not settings.is_list_configured(_get_list_id()):
            print("DOCUMENT_LIFECYCLE_LIST_ID is not configured.")
            return 1
        items = await get_list_items(_get_list_id(), _LIST_NAME)
        todo = [i for i in items
                if (i.get("fields") or {}).get("ApprovalStatus") != "Approved"
                and (i.get("fields") or {}).get("SharePointFileUrl")]
        if limit:
            todo = todo[:limit]
        print(f"{len(todo)} open document(s) with a file ({len(items)} cards in all).")
        checked = failed = 0
        for n, item in enumerate(todo, 1):
            fields = item.get("fields") or {}
            label = fields.get("DocumentCode") or fields.get("Title") or item.get("id")
            if dry_run:
                print(f"  [{n}/{len(todo)}] would check {label}")
                continue
            before = fields.get("CDIStatus")
            if await _sync_with_file(str(item["id"]), fields, force=True):
                checked += 1
                print(f"  [{n}/{len(todo)}] {label}: {before} -> {fields.get('CDIStatus')}")
            else:
                failed += 1
                print(f"  [{n}/{len(todo)}] {label}: NOT checked (file unreachable, or the checker errored)")
        if not dry_run:
            print(f"\nChecked {checked}; {failed} could not be checked.")
        return 1 if failed else 0
    finally:
        await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(run(args.dry_run, args.limit)))


if __name__ == "__main__":
    main()
