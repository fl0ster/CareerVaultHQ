"""Redis connection and RQ queue shared by the API (producer) and the worker (consumer)."""

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_queue() -> Queue:
    """FastAPI dependency. Tests override this with a fakeredis-backed queue."""
    return Queue(get_settings().latex_queue_name, connection=get_redis())

def get_scrapper_queue() -> Queue:
    """FastAPI dependency. Tests override this with a fakeredis-backed queue."""
    return Queue(get_settings().scrapper_queue_name, connection=get_redis())
