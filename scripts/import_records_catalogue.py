#!/usr/bin/env python3
# =============================================================================
# scripts/import_records_catalogue.py — load the Enterprise Records Catalogue
# workbook into the OrgOS "Records Catalogue" SharePoint list
#
# Dry run by default: prints what would be created and updated, writes nothing.
# With --apply it upserts by Record ID. It never deletes; records missing from
# the workbook are listed so Records Governance can decide.
#
#   python scripts/import_records_catalogue.py                       # dry run
#   python scripts/import_records_catalogue.py --apply
#   python scripts/import_records_catalogue.py path/to/catalogue.xlsx --apply
# =============================================================================

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.client import get_list_items, shutdown, startup          # noqa: E402
from records_catalogue import service                               # noqa: E402
from records_catalogue.workbook import WorkbookError, read_catalogue  # noqa: E402

DEFAULT_WORKBOOK = "docs/Enterprise Records Catalogue - Production Candidate.xlsx"


async def run(path: str, apply: bool) -> int:
    try:
        with open(path, "rb") as fh:
            entries = read_catalogue(fh.read())
    except (OSError, WorkbookError) as exc:
        print(f"Cannot read the Catalogue: {exc}")
        return 1

    gate_open = sum(e.disposition_gate()[0] for e in entries)
    print(f"Workbook: {len(entries)} records "
          f"({sum(e.withdrawn for e in entries)} withdrawn, "
          f"{gate_open} cleared for automated disposition)")
    for status, n in Counter(e.retention_validation for e in entries).most_common():
        print(f"  retention {status or '(blank)'}: {n}")

    await startup()
    try:
        existing = await get_list_items(service._list_id(), service.LIST_NAME, top=999)
        plan = service.plan_import(existing, entries)
        print(f"\nSharePoint list holds {len(existing)} items.")
        print(f"  create {len(plan.create)}, update {len(plan.update)}, unchanged {plan.unchanged}")
        if plan.not_in_workbook:
            print(f"  kept, not in this workbook: {', '.join(plan.not_in_workbook)}")
        if plan.duplicates_in_list:
            print(f"  WARNING duplicate Record IDs already in the list: {', '.join(plan.duplicates_in_list)}")

        if not apply:
            print("\nDry run — nothing written. Re-run with --apply to write.")
            return 0
        await service.apply_import(plan)
        print(f"\nWritten: {len(plan.create)} created, {len(plan.update)} updated.")
        return 0
    finally:
        await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the Enterprise Records Catalogue into OrgOS.")
    parser.add_argument("workbook", nargs="?", default=DEFAULT_WORKBOOK)
    parser.add_argument("--apply", action="store_true", help="write to SharePoint (default: dry run)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.workbook, args.apply)))


if __name__ == "__main__":
    main()
