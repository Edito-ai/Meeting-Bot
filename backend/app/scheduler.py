"""Background loop (runs inside the FastAPI process) that watches Google Calendar
for upcoming demo events and enqueues a join job for the meet-worker right when it's
due. Polling + "is it time yet" are checked together each tick, so this is self-healing
across restarts (no separate delayed-job scheduler needed)."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from common import repo
from common.queue import QUEUE_JOIN_MEETING, get_queue

from .calendar_client import CalendarEvent, ensure_bot_invited, fetch_upcoming_demo_events

logger = logging.getLogger("scheduler")

POLL_INTERVAL_SECONDS = 30
DISCOVERY_WINDOW_MINUTES = 60
JOIN_LEAD_MINUTES = int(os.environ.get("JOIN_LEAD_MINUTES", "1"))
# If we somehow missed the join window by more than this, don't join late/confuse attendees.
MAX_LATE_JOIN_MINUTES = 5

# How often to verify the bot's Google session still works, so a dead session (Google
# invalidated it) gets caught and alerted on hours before it'd otherwise silently fail a
# real demo join. See meet_worker.worker.check_session_health_job.
SESSION_HEALTHCHECK_INTERVAL_MINUTES = int(os.environ.get("SESSION_HEALTHCHECK_INTERVAL_MINUTES", "240"))
_last_healthcheck_at: datetime | None = None


def _upsert_meeting(event: CalendarEvent) -> None:
    if repo.find_meeting_by_calendar_event(event["id"]):
        return
    repo.create_meeting(
        calendar_event_id=event["id"],
        title=event["title"],
        meet_url=event["meet_url"],
        organizer_email=event["organizer_email"],
        scheduled_start=event["start"],
        scheduled_end=event["end"],
    )
    try:
        ensure_bot_invited(event["id"], event["attendees"])
    except Exception:
        # Not fatal - the join still works, it'll just show "asking to join" and need a
        # manual Admit instead of walking straight in.
        logger.exception("Could not add bot as a calendar guest for event %s", event["id"])


def _enqueue_due_meetings() -> None:
    due = repo.find_due_meetings(JOIN_LEAD_MINUTES, MAX_LATE_JOIN_MINUTES)
    queue = get_queue(QUEUE_JOIN_MEETING)
    for meeting in due:
        repo.set_meeting_status(meeting["id"], "joining")
        queue.enqueue(
            "meet_worker.worker.join_meeting_job",
            meeting["id"],
            meeting["meet_url"],
            job_timeout="30m",
        )
        logger.info("Enqueued join job for meeting %s", meeting["id"])


def _maybe_enqueue_session_healthcheck() -> None:
    global _last_healthcheck_at
    now = datetime.now(timezone.utc)
    if _last_healthcheck_at is not None and now - _last_healthcheck_at < timedelta(
        minutes=SESSION_HEALTHCHECK_INTERVAL_MINUTES
    ):
        return
    _last_healthcheck_at = now
    # Enqueued on the same queue meet-worker's single RQ worker processes join jobs from,
    # so this can never run at the same time as an active call (it'd otherwise fight over
    # the persistent Chrome profile, which only one Chromium process can hold at a time).
    get_queue(QUEUE_JOIN_MEETING).enqueue(
        "meet_worker.worker.check_session_health_job",
        job_timeout="5m",
    )
    logger.info("Enqueued Google session health check")


def _tick() -> None:
    try:
        events = fetch_upcoming_demo_events(DISCOVERY_WINDOW_MINUTES)
        for event in events:
            _upsert_meeting(event)
        _enqueue_due_meetings()
        _maybe_enqueue_session_healthcheck()
    except Exception:
        logger.exception("Scheduler tick failed")


async def run_scheduler_loop() -> None:
    logger.info("Scheduler loop starting, polling every %ss", POLL_INTERVAL_SECONDS)
    while True:
        await asyncio.to_thread(_tick)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
