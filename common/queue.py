import os

from redis import Redis
from rq import Queue

QUEUE_JOIN_MEETING = "join-meeting"
QUEUE_TRANSCRIBE = "transcribe-audio"
QUEUE_GENERATE_NOTES = "generate-notes"

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    return _redis


def get_queue(name: str) -> Queue:
    return Queue(name, connection=get_redis())
