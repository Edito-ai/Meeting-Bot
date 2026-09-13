"""RQ job: join a Meet call, capture attendance + captions + audio for its duration,
then hand off to transcription. Run as: rq worker join-meeting --url $REDIS_URL
"""
import logging
import time
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

from common import repo
from common.queue import QUEUE_TRANSCRIBE, get_queue
from common.slack import notify_session_invalid

from .join_meeting import (
    launch_authenticated_context,
    join_meeting,
    post_identification_message,
    is_call_still_active,
    is_session_signed_in,
    leave_meeting,
)
from .attendance_tracker import AttendanceTracker
from .caption_scraper import CaptionScraper
from .audio_recorder import start_recording, stop_recording

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("meet_worker")

POLL_INTERVAL_SECONDS = 5
MAX_MEETING_SECONDS = 2 * 60 * 60  # hard safety cap so a stuck session can't run forever


def join_meeting_job(meeting_id: str, meet_url: str) -> None:
    logger.info("Joining meeting %s at %s", meeting_id, meet_url)

    with sync_playwright() as playwright:
        context = launch_authenticated_context(playwright)
        try:
            page, joined_at = join_meeting(context, meet_url)
            repo.mark_joined(meeting_id, joined_at)
            post_identification_message(page)

            recording_proc, audio_path = start_recording(meeting_id)
            attendance = AttendanceTracker(meeting_id, page)
            attendance.start()
            captions = CaptionScraper(meeting_id, page)
            captions.start()

            started = time.monotonic()
            while is_call_still_active(page):
                attendance.poll_once()
                captions.poll_once(attendance.current)

                if time.monotonic() - started > MAX_MEETING_SECONDS:
                    logger.warning("Meeting %s hit max duration cap, leaving", meeting_id)
                    leave_meeting(page)
                    break

                time.sleep(POLL_INTERVAL_SECONDS)

            attendance.finalize()
            captions.finalize(attendance.current)
            stop_recording(recording_proc)

            left_at = datetime.now(timezone.utc)
            repo.mark_left(meeting_id, left_at, audio_path)
            repo.set_meeting_status(meeting_id, "transcribing")

            get_queue(QUEUE_TRANSCRIBE).enqueue(
                "transcription_worker.worker.transcribe_job",
                meeting_id,
                audio_path,
                job_timeout="30m",
            )
            logger.info("Left meeting %s, queued transcription of %s", meeting_id, audio_path)
        except Exception as exc:
            logger.exception("Join-meeting job failed for %s", meeting_id)
            repo.set_meeting_status(meeting_id, "failed", failure_reason=str(exc))
        finally:
            context.close()


def check_session_health_job() -> None:
    """Periodic job (enqueued by backend/app/scheduler.py) that verifies the bot's saved
    Google session still works, without waiting for a real demo to fail first. Runs on the
    same RQ queue as join_meeting_job, so it's never processing at the same time as an
    active call - important since the persistent Chrome profile can only be opened by one
    Chromium process at a time."""
    logger.info("Running session health check")
    with sync_playwright() as playwright:
        context = launch_authenticated_context(playwright)
        try:
            alive = is_session_signed_in(context)
        finally:
            context.close()

    if alive:
        logger.info("Session health check passed")
    else:
        logger.error("Session health check FAILED - Google session is signed out")
        notify_session_invalid(
            "Meet bot's Google session is signed out. Re-run scripts/bootstrap_auth.py "
            "and redeploy secrets/chrome-profile/ before the next demo."
        )
