#!/usr/bin/env python3
# =============================================================================
# scripts/sync_control_library.py — propose Control Register changes from the
# Control Library
#
# Reads every document, finds each control's defining document, and compares
# each definition with what is confirmed. New and changed definitions become
# Zone 1 review items; unchanged ones produce nothing. Dry run by default.
#
#   python scripts/sync_control_library.py                     # SharePoint, dry run
#   python scripts/sync_control_library.py --local .cdi_corpus  # a local copy
#   python scripts/sync_control_library.py --apply
# =============================================================================

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cdi.library import LibraryIndex                                  # noqa: E402
from control_register.sync import apply_sync, plan_resolutions, plan_sync  # noqa: E402
from scripts.cdi_library_census import collect_local, collect_sharepoint  # noqa: E402


async def _registers():
    from config import settings
    from graph.client import get_list_items

    register = await get_list_items(settings.control_register_list_id, "Control Register")
    queue = await get_list_items(settings.ai_review_queue_list_id, "AI Review Queue")
    return register, queue


async def _catalogue():
    from graph.exceptions import SharePointListNotConfiguredError
    from records_catalogue import service

    try:
        entries = await service.load()
    except SharePointListNotConfiguredError:
        return None
    # An empty list means the Catalogue hasn't been imported yet, not that
    # every record is missing — checking against it would flag them all.
    return entries or None


async def run(local: str | None, folder: str | None, apply: bool) -> int:
    from graph.client import shutdown, startup

    entries = collect_local(local) if local else await collect_sharepoint(folder)
    docs = [e.doc for e in entries if e.doc]
    unread = [e for e in entries if not e.doc]
    index = LibraryIndex(docs)
    print(f"Library: {len(docs)} documents read, {len(unread)} unreadable; "
          f"{len(index.defined_ids)} controls defined, {len(index.contested_ids)} contested.")

    await startup()
    try:
        register, queue = await _registers()
        from ownership.resolver import get_ownership_index
        owners = await get_ownership_index()
        plan = plan_sync(index, register, queue, owners.resolve)
        catalogue = await _catalogue()
        resolutions = plan_resolutions(index, queue, catalogue)

        print(f"\nAgainst the Control Register ({len(register)} rows):")
        print(f"  new or changed → review items: create {plan.count('create_item')}, "
              f"update {plan.count('update_item')}")
        print(f"  unchanged: {plan.unchanged} (refresh derived data on {plan.count('refresh_control')}, "
              f"close {plan.count('close_item')} stale review item(s))")
        print(f"  already waiting in the queue: {plan.already_queued}; "
              f"rejected earlier, unchanged since: {plan.declined}")
        print(f"  status re-checked against roles: {plan.count('refresh_status')} change(s)")
        if plan.contested:
            print(f"  NOT SYNCED — defined twice with equal authority: {', '.join(plan.contested)}")
        if plan.no_longer_defined:
            print(f"  confirmed but no longer defined by any document: {', '.join(plan.no_longer_defined)}")
        if catalogue is None:
            print("  Records Catalogue empty or not configured — REC citations not checked "
                  "(import it first: scripts/import_records_catalogue.py --apply)")
        print(f"  references that don't resolve → Zone 2: raise "
              f"{sum(a.kind == 'create_item' for a in resolutions)}, "
              f"close {sum(a.kind == 'close_item' for a in resolutions)} now resolved")
        if plan.duplicate_controls:
            print(f"  WARNING two live register rows share a Control ID: {', '.join(plan.duplicate_controls)}")

        plan.actions += resolutions
        if not apply:
            print("\nDry run — nothing written. Re-run with --apply to write.")
            return 0
        failures = await apply_sync(plan)
        print(f"\nWritten: {len(plan.actions) - len(failures)} change(s).")
        for line in failures:
            print(f"  FAILED {line}")
        return 1 if failures else 0
    finally:
        await shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the Control Library into review.")
    parser.add_argument("--local", help="read a local copy of the library instead of SharePoint")
    parser.add_argument("--folder", help="only this top-level library folder")
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.local, args.folder, args.apply)))


if __name__ == "__main__":
    main()
