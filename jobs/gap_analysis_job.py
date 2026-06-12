# =============================================================================
# jobs/gap_analysis_job.py — Scheduled Gap Analyzer
# Runs every 3 days via APScheduler.
# =============================================================================

import logging

from config import settings
from agents.gap_analyzer.service import run_gap_analysis

logger = logging.getLogger(__name__)


async def run_scheduled_gap_analysis() -> None:
    """
    Scheduled job: run Gap Analyzer against confirmed register data.
    The service deduplicates open/in-progress gaps, so repeated scheduled runs
    should add only newly discovered gaps.
    """
    if not settings.is_list_configured(settings.gap_analysis_list_id):
        logger.debug("Scheduled Gap Analyzer: Gap Analysis list not configured — skipping")
        return

    logger.info("Scheduled Gap Analyzer: starting")
    try:
        summary = await run_gap_analysis(triggered_by="system: scheduled 3-day job")
        logger.info(f"Scheduled Gap Analyzer complete: {summary}")
    except Exception as exc:
        logger.exception(f"Scheduled Gap Analyzer failed: {exc}")
