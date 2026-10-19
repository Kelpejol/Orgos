# =============================================================================
# graph/bulk.py — run many SharePoint writes a few at a time, with progress
#
# One list item is one Graph call, so loading hundreds of items one after
# another takes many minutes with no sign of life. This runs them with a small
# fixed concurrency (Graph throttling, 429, is already retried by
# graph.client._request) and reports progress as it goes. A failed write is
# collected, never allowed to stop the others.
# =============================================================================

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

Progress = Callable[[int, int], None]


async def run_writes(
    writes: list[tuple[str, Callable[[], Awaitable]]],
    concurrency: int = 4,
    progress: Optional[Progress] = None,
    every: int = 25,
) -> list[str]:
    """
    `writes`: (label, zero-argument coroutine function). Returns one
    "label: error" line per failure. `progress(done, total)` is called every
    `every` completions and at the end.
    """
    total = len(writes)
    gate = asyncio.Semaphore(concurrency)
    failures: list[str] = []
    done = 0

    async def one(label: str, call: Callable[[], Awaitable]) -> None:
        nonlocal done
        async with gate:
            try:
                await call()
            except Exception as exc:
                failures.append(f"{label}: {exc}")
        done += 1
        if progress and (done % every == 0 or done == total):
            progress(done, total)

    await asyncio.gather(*(one(label, call) for label, call in writes))
    return failures


def print_progress(what: str) -> Progress:
    def report(done: int, total: int) -> None:
        print(f"  {what}: {done}/{total}", flush=True)
    return report
