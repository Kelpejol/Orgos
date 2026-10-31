# =============================================================================
# jobs/scheduler.py — APScheduler setup
# Uses AsyncScheduler (APScheduler 3.x AsyncIOScheduler) so jobs share the
# event loop with FastAPI and can await Graph API calls directly.
# Started/stopped in main.py lifespan.
# =============================================================================

import logging
import os
import tempfile

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Singleton — imported by main.py and any module that needs to add jobs
scheduler = AsyncIOScheduler(timezone="Africa/Lagos")

# Only ONE process on the server runs the jobs. With several uvicorn workers each would start
# its own scheduler and every job would run once per worker (duplicate gaps, duplicate reviews).
_LOCK_PATH = os.path.join(tempfile.gettempdir(), "orgos-scheduler.lock")
_lock_handle = None


def _claim_scheduler_lock() -> bool:
    global _lock_handle
    try:
        import fcntl
    except ImportError:                      # not a POSIX host: nothing to share the jobs with
        return True
    handle = open(_LOCK_PATH, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_handle = handle                    # held for the life of the process
    return True


def start_scheduler() -> None:
    """Register all scheduled jobs and start the scheduler (in one process only)."""
    if not _claim_scheduler_lock():
        logger.info("APScheduler not started in this process: another worker runs the jobs.")
        return
    from jobs.scheduled_review import check_document_review_dates
    from jobs.sensitisation_deadline import check_sensitisation_deadlines
    from jobs.gap_analysis_job import run_scheduled_gap_analysis
    from evidence.service import run_daily as run_evidence_daily

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

    # Daily at 07:30 WAT — reconcile evidence obligations with the controls and
    # write each one's state (Due soon, Late, Missing, Stale…) so the Power
    # Automate flows on the Evidence Tracker list notify owners
    scheduler.add_job(
        run_evidence_daily,
        CronTrigger(hour=7, minute=30),
        id="evidence-obligations-daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Every third day at 06:30 WAT — run Gap Analyzer against confirmed register data. A calendar
    # rule, not "3 days after start": an interval restarted its count at every app restart.
    scheduler.add_job(
        run_scheduled_gap_analysis,
        CronTrigger(day="*/3", hour=6, minute=30),
        id="gap-analysis-three-day-check",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info(
        "APScheduler started — jobs: evidence-obligations-daily (07:30 WAT), "
        "document-review-check (08:00 WAT), "
        "sensitisation-deadline-check (09:00 WAT), gap-analysis-three-day-check (every third day, 06:30 WAT)"
    )


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")
