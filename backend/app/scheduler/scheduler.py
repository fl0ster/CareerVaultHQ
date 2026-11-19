"""Periodic jobs. Run with ``python -m app.scheduler.scheduler`` (see docker-compose).

The loop wakes up every ``SCHEDULER_SLEEP_SECONDS`` and lets each scheduled task decide
whether it is due. Tasks never run here; they are enqueued on the shared RQ queue and
executed by ``app.workers.worker``. Each scheduled task lives in its own module:

* :mod:`app.scheduler.evaluation` - catch-up ``evaluate_pending_jobs`` with backoff.
* :mod:`app.scheduler.cleanup` - daily ``cleanup_old_jobs``.
* :mod:`app.scheduler.scrape` - per-source ``scrape`` with jitter, planned in the DB.
* :mod:`app.scheduler.gmail` - ``check_rejection_mails`` while the Gmail monitor is on.
"""

from __future__ import annotations

import logging
import os
import time

from app.config import get_settings
from app.db import init_db
from app.queue import get_queue
from app.scheduler.cleanup import CLEANUP_JOB_ID, CLEANUP_TIMEOUT, CleanupScheduler
from app.scheduler.common import ACTIVE_STATUSES
from app.scheduler.common import aware as _aware
from app.scheduler.evaluation import EVALUATE_JOB_ID, EVALUATE_TIMEOUT, EvaluationScheduler
from app.scheduler.gmail import GMAIL_JOB_ID, GmailMonitorScheduler
from app.scheduler.scrape import SCRAPE_JOB_ID_PREFIX, SCRAPE_TIMEOUT, ScrapeScheduler

__all__ = [
    "ACTIVE_STATUSES",
    "CLEANUP_JOB_ID",
    "CLEANUP_TIMEOUT",
    "EVALUATE_JOB_ID",
    "EVALUATE_TIMEOUT",
    "GMAIL_JOB_ID",
    "SCRAPE_JOB_ID_PREFIX",
    "SCRAPE_TIMEOUT",
    "CleanupScheduler",
    "EvaluationScheduler",
    "GmailMonitorScheduler",
    "ScrapeScheduler",
    "_aware",
    "run_scheduler",
]

log = logging.getLogger(__name__)

SCHEDULER_SLEEP_SECONDS = int(os.getenv("SCHEDULER_SLEEP_SECONDS") or 60)


def run_scheduler() -> None:
    init_db()  # the scrape and Gmail schedulers keep their plan in the DB
    queue = get_queue()
    schedulers = [
        EvaluationScheduler(queue),
        CleanupScheduler(queue),
        ScrapeScheduler(queue),
        GmailMonitorScheduler(queue),
    ]
    while True:
        for scheduled in schedulers:
            try:
                scheduled.tick()
            except Exception:
                log.exception("Scheduler error in %s", type(scheduled).__name__)
        time.sleep(SCHEDULER_SLEEP_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if get_settings().debug else logging.INFO)
    log.info("Starting scheduler (every %ds)", SCHEDULER_SLEEP_SECONDS)
    run_scheduler()
