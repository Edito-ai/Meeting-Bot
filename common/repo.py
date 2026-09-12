"""Shared data-access helpers used by every service (backend, meet_worker, transcription_worker).

Every document uses a plain UUID string as _id (never a raw ObjectId) so results are
JSON-serializable as-is and so callers can keep treating ids as opaque strings. Reads
normalize Mongo's `_id` field to `id` to match what the rest of the app (templates,
routes, RQ job payloads) expects.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import get_db


def _new_id() -> str:
    return str(uuid.uuid4())


def _normalize(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return doc


def _normalize_all(docs) -> list[dict]:
    return [_normalize(d) for d in docs]


# --- meetings ---


def get_meeting(meeting_id: str) -> dict | None:
    return _normalize(get_db().meetings.find_one({"_id": meeting_id}))


def list_meetings(limit: int = 50) -> list[dict]:
    cursor = get_db().meetings.find().sort("scheduled_start", -1).limit(limit)
    return _normalize_all(cursor)


def find_meeting_by_calendar_event(calendar_event_id: str) -> dict | None:
    return _normalize(get_db().meetings.find_one({"calendar_event_id": calendar_event_id}))


def create_meeting(
    calendar_event_id: str,
    title: str,
    meet_url: str,
    organizer_email: str | None,
    scheduled_start: datetime,
    scheduled_end: datetime | None,
) -> str:
    meeting_id = _new_id()
    now = datetime.now(timezone.utc)
    get_db().meetings.insert_one(
        {
            "_id": meeting_id,
            "calendar_event_id": calendar_event_id,
            "title": title,
            "meet_url": meet_url,
            "organizer_email": organizer_email,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "actual_join_at": None,
            "actual_leave_at": None,
            "status": "scheduled",
            "audio_file_path": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return meeting_id


def find_due_meetings(join_lead_minutes: int, max_late_minutes: int) -> list[dict]:
    """Meetings still 'scheduled' whose join time has arrived (and haven't been missed by
    more than max_late_minutes)."""
    now = datetime.now(timezone.utc)
    cursor = get_db().meetings.find(
        {
            "status": "scheduled",
            "scheduled_start": {
                "$lte": now + timedelta(minutes=join_lead_minutes),
                "$gte": now - timedelta(minutes=max_late_minutes),
            },
        }
    )
    return _normalize_all(cursor)


def set_meeting_status(meeting_id: str, status: str, failure_reason: str | None = None) -> None:
    get_db().meetings.update_one(
        {"_id": meeting_id},
        {"$set": {"status": status, "failure_reason": failure_reason, "updated_at": datetime.now(timezone.utc)}},
    )


def mark_joined(meeting_id: str, joined_at: datetime) -> None:
    get_db().meetings.update_one(
        {"_id": meeting_id},
        {
            "$set": {
                "status": "in_progress",
                "actual_join_at": joined_at,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


def mark_left(meeting_id: str, left_at: datetime, audio_file_path: str | None) -> None:
    get_db().meetings.update_one(
        {"_id": meeting_id},
        {
            "$set": {
                "actual_leave_at": left_at,
                "audio_file_path": audio_file_path,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )


# --- participants ---


def record_participant_join(meeting_id: str, name: str, join_at: datetime) -> str:
    participant_id = _new_id()
    get_db().participants.insert_one(
        {
            "_id": participant_id,
            "meeting_id": meeting_id,
            "name": name,
            "join_at": join_at,
            "leave_at": None,
            "created_at": datetime.now(timezone.utc),
        }
    )
    return participant_id


def record_participant_leave(meeting_id: str, name: str, leave_at: datetime) -> None:
    # Mirrors the old SQL: close the most recent still-open row for this name in this meeting.
    doc = get_db().participants.find_one(
        {"meeting_id": meeting_id, "name": name, "leave_at": None},
        sort=[("join_at", -1)],
    )
    if doc:
        get_db().participants.update_one({"_id": doc["_id"]}, {"$set": {"leave_at": leave_at}})


def list_participants(meeting_id: str) -> list[dict]:
    cursor = get_db().participants.find({"meeting_id": meeting_id}).sort("join_at", 1)
    return _normalize_all(cursor)


# --- transcript segments ---


def add_transcript_segment(
    meeting_id: str,
    text: str,
    started_at: datetime,
    speaker: str | None = None,
    ended_at: datetime | None = None,
    source: str = "whisper",
) -> None:
    get_db().transcript_segments.insert_one(
        {
            "_id": _new_id(),
            "meeting_id": meeting_id,
            "speaker": speaker,
            "text": text,
            "started_at": started_at,
            "ended_at": ended_at,
            "source": source,
            "created_at": datetime.now(timezone.utc),
        }
    )


def list_transcript_segments(meeting_id: str, source: str | None = None) -> list[dict]:
    query: dict[str, Any] = {"meeting_id": meeting_id}
    if source:
        query["source"] = source
    cursor = get_db().transcript_segments.find(query).sort("started_at", 1)
    return _normalize_all(cursor)


# --- notes ---


def upsert_notes(meeting_id: str, notes: dict[str, Any]) -> None:
    get_db().notes.update_one(
        {"meeting_id": meeting_id},
        {
            "$set": {
                "summary": notes["summary"],
                "key_points": notes.get("key_points", []),
                "objections": notes.get("objections", []),
                "action_items": notes.get("action_items", []),
                "next_steps": notes.get("next_steps", []),
                "raw_model_output": notes.get("raw_model_output"),
            },
            "$setOnInsert": {
                "_id": _new_id(),
                "meeting_id": meeting_id,
                "created_at": datetime.now(timezone.utc),
            },
        },
        upsert=True,
    )


def get_notes(meeting_id: str) -> dict | None:
    return _normalize(get_db().notes.find_one({"meeting_id": meeting_id}))
