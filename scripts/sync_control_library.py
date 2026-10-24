#!/usr/bin/env python3
# =============================================================================
# scripts/sync_control_library.py — bring the registers in line with the
# approved library
#
# Does by hand what approving a document does (control_register/
# approved_library.py): reads every document the Document Register holds as
# current, from its published copy, and compares each control's definition
# with what is confirmed. New and changed definitions become Zone 1 review
# items; problems between approved documents become Zone 2 items; Blocked
# controls are re-checked against Org Roles. Drafts in the library
# folder are not read — they enter through Document Lifecycle.
#
# Use it to retry after an approval whose note says so, or after the Role
# Catalogue changes. Dry run by default.
#
#   python scripts/sync_control_library.py           # dry run
#   python scripts/sync_control_library.py --apply
#
# To survey the library folder itself (drafts included), without writing
# anything: python scripts/cdi_library_census.py
# =============================================================================

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run(apply: bool) -> int:
    from control_register.approved_library import sync_approved_library
    from graph.bulk import print_progress
    from graph.client import shutdown, startup

    await startup()
    try:
        r = await sync_approved_library(apply=apply, progress=print_progress("written"))
    finally:
        await shutdown()

    print(f"Approved library: {r['documents_read']} document(s) read.")
    for line in r["unreadable"]:
        print(f"  UNREADABLE {line}")
    for line in r["missed"]:
        print(f"  DOWNLOAD FAILED {line}")
    if r["no_published_copy"]:
        print(f"  current in the Register but no published copy recorded: "
              f"{', '.join(r['no_published_copy'])}")
    if r.get("reason"):
        print(f"\n{r['reason']} Re-run when SharePoint is reachable.")
        return 1

    print(f"\n{r['controls_defined']} control(s) defined.")
    print(f"  new or changed → review items: {r['new_or_changed']}")
    print(f"  unchanged: {r['unchanged']}")
    print(f"  status re-checked against roles: {r['status_changes']} change(s)")
    print(f"  problems between documents → Zone 2: raise {r['findings_raised']}, "
          f"close {r['findings_closed']} now resolved")
    if r["contested"]:
        print(f"  NOT SYNCED — defined twice with equal authority: {', '.join(r['contested'])}")
    if r["no_longer_defined"]:
        print(f"  confirmed but no longer defined by any approved document: "
              f"{', '.join(r['no_longer_defined'])}")
    if not r["catalogue_checked"]:
        print("  Records Catalogue empty or not configured — REC citations not checked "
              "(import it first: scripts/import_records_catalogue.py --apply)")

    if not apply:
        print("\nDry run — nothing written. Re-run with --apply to write.")
        return 0
    failures = r.get("failures") or []
    print(f"\nWritten: {r['actions'] - len(failures)} change(s).")
    for line in failures[:20]:
        print(f"  FAILED {line}")
    if failures:
        print("Re-run the same command to retry: what was written is not raised twice.")
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bring the registers in line with the approved library.")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.apply)))


if __name__ == "__main__":
    main()
