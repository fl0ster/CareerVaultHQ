"""RQ worker entrypoint for the LaTeX -> PDF queue (app/tasks/latex.py).

Run alongside the API (same image, same /data volume, same Redis):

    python -m app.workers.latex2pdf           # blocks, processes jobs forever
    python -m app.workers.latex2pdf --burst   # drain the queue and exit

Only the plain ``Worker`` is used (fork per job, no scheduler) to stay light on a Pi 2.
"""

from __future__ import annotations

import logging
import sys

from rq import Queue, Worker

from app.config import get_settings
from app.queue import get_redis


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    burst = "--burst" in argv

    settings = get_settings()
    logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)

    connection = get_redis()
    queue = Queue(settings.latex_queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(burst=burst, with_scheduler=False)


if __name__ == "__main__":
    main()
