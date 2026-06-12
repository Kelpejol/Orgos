# =============================================================================
# jobs/scheduler.py — APScheduler setup
# Uses AsyncScheduler (APScheduler 3.x AsyncIOScheduler) so jobs share the
# event loop with FastAPI and can await Graph API calls directly.
# Started/stopped in main.py lifespan.
# =============================================================================

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Singleton — imported by main.py and any module that needs to add jobs
scheduler = AsyncIOScheduler(timezone="Africa/Lagos")


def start_scheduler() -> None:
    """Register all scheduled jobs and start the scheduler."""
    from jobs.scheduled_review import check_document_review_dates
    from jobs.sensitisation_deadline import check_sensitisation_deadlines
    from jobs.gap_analysis_job import run_scheduled_gap_analysis

    # Daily at 08:00 WAT — scan Document Register for documents due for review
    scheduler.add_job(
        check_document_review_dates,
        CronTrigger(hour=8, minute=0),
        id="document-review-check",
        replace_existing=True,
        misfire_grace_time=3600,   # Run even if missed by up to 1 hour
    )

    # Daily at 09:00 WAT — alert owners about sensitisation deadlines expiring soon
    scheduler.add_job(
        check_sensitisation_deadlines,
        CronTrigger(hour=9, minute=0),
        id="sensitisation-deadline-check",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Every 3 days — run Gap Analyzer against confirmed register data
    scheduler.add_job(
        run_scheduled_gap_analysis,
        IntervalTrigger(days=3),
        id="gap-analysis-three-day-check",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info(
        "APScheduler started — jobs: document-review-check (08:00 WAT), "
        "sensitisation-deadline-check (09:00 WAT), gap-analysis-three-day-check (every 3 days)"
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
