"""Redis client utilities for LAB 05."""

import os
from functools import lru_cache

from redis.asyncio import Redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@lru_cache
def get_redis() -> Redis:
    """
    Получить singleton-клиент Redis.

    TODO (опционально):
    - добавить retry policy / timeouts
    - добавить namespace/prefix
    """
    return Redis.from_url(REDIS_URL, decode_responses=True)
