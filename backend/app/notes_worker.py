"""RQ job: reconciled transcript -> OpenRouter notes -> MongoDB -> Slack.
Run as: rq worker generate-notes --url $REDIS_URL
"""
import logging
import os

from common import repo

from .notes_generator import generate_notes
from .slack import notify_notes_ready

logger = logging.getLogger("notes_worker")


def generate_notes_job(meeting_id: str) -> None:
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        logger.error("Meeting %s not found, skipping notes generation", meeting_id)
        return

    repo.set_meeting_status(meeting_id, "summarizing")

    segments = repo.list_transcript_segments(meeting_id, source="whisper") or repo.list_transcript_segments(
        meeting_id, source="caption"
    )
    participants = repo.list_participants(meeting_id)

    try:
        notes = generate_notes(meeting["title"], segments, participants)
        repo.upsert_notes(meeting_id, notes)
        repo.set_meeting_status(meeting_id, "completed")

        base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")
        notify_notes_ready(meeting["title"], f"{base_url}/meetings/{meeting_id}", notes["summary"])
        logger.info("Notes generated for meeting %s", meeting_id)
    except Exception as exc:
        logger.exception("Notes generation failed for meeting %s", meeting_id)
        repo.set_meeting_status(meeting_id, "failed", failure_reason=str(exc))
