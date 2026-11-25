"""RQ worker entrypoint for the single background queue (LaTeX -> PDF compiles and web
scraping / parsing jobs share one queue so only one worker process runs on the Pi).

Run alongside the API (same image, same /data volume, same Redis):

    python -m app.workers.worker           # blocks, processes jobs forever
    python -m app.workers.worker --burst   # drain the queue and exit

Only the plain ``Worker`` is used (fork per job, no scheduler) to stay light on a Pi 2.
"""

from __future__ import annotations

import logging
import sys

from rq import Queue, Worker

from app.config import get_settings
from app.db import init_db
from app.llm_calls import load_model_overrides
from app.queue import get_redis


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    burst = "--burst" in argv

    settings = get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)

    init_db()
    load_model_overrides(settings.openrouter_models_file)  # fail fast on an invalid override file
    connection = get_redis()
    queue = Queue(settings.queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(burst=burst, with_scheduler=False)


if __name__ == "__main__":
    main()
