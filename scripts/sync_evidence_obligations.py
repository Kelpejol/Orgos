#!/usr/bin/env python3
# =============================================================================
# scripts/sync_evidence_obligations.py — run the 07:30 evidence job now
#
# Creates the evidence obligations for every confirmed control's records,
# refreshes changed ones (including the schedule each document states),
# retires ones no control names any more, starts the schedules whose Control
# owner role now has someone in it, then brings
# every obligation's state up to today. Safe to re-run: nothing is created twice.
#
#   python scripts/sync_evidence_obligations.py
# =============================================================================

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run() -> int:
    from evidence.service import refresh_states, start_clocks, sync_obligations
    from graph.client import shutdown, startup

    await startup()
    try:
        synced = await sync_obligations()
        print(f"Obligations: {synced['create']} created, {synced['update']} updated, "
              f"{synced['retire']} retired.")
        for line in synced["failures"][:20]:
            print(f"  FAILED {line}")
        clocks = await start_clocks()
        print(f"Schedules started: {clocks['started']} ({clocks['failed']} failed).")
        states = await refresh_states()
        print(f"States: {states['changed']} updated, {states['failed']} failed.")
        return 1 if synced["failures"] or states["failed"] or clocks["failed"] else 0
    finally:
        await shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
