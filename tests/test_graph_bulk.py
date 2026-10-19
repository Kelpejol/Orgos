# tests/test_graph_bulk.py — many writes, a few at a time, failures collected

import asyncio

from graph.bulk import run_writes


async def test_writes_run_bounded_report_progress_and_collect_failures():
    running = peak = 0
    seen = []

    def make(n):
        async def call():
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.001)
            running -= 1
            if n == 3:
                raise RuntimeError("boom")
        return call

    failures = await run_writes([(f"item {n}", make(n)) for n in range(10)], concurrency=4,
                                progress=lambda d, t: seen.append((d, t)), every=5)
    assert peak <= 4
    assert failures == ["item 3: boom"]
    assert seen == [(5, 10), (10, 10)]
