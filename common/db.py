import os

from pymongo import ASCENDING, MongoClient
from pymongo.database import Database

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        # tz_aware=True so dates read back are timezone-aware UTC datetimes, matching
        # the datetime.now(timezone.utc) values the app writes everywhere else.
        _client = MongoClient(os.environ["MONGODB_URI"], tz_aware=True)
    return _client


def get_db() -> Database:
    return get_client()[os.environ.get("MONGODB_DB", "broll_notetaker")]


def ensure_indexes() -> None:
    """Safe to call repeatedly (e.g. on every backend startup) - create_index is idempotent."""
    db = get_db()
    db.meetings.create_index("calendar_event_id", unique=True)
    db.meetings.create_index([("status", ASCENDING), ("scheduled_start", ASCENDING)])
    db.participants.create_index("meeting_id")
    db.transcript_segments.create_index([("meeting_id", ASCENDING), ("started_at", ASCENDING)])
    db.notes.create_index("meeting_id", unique=True)
