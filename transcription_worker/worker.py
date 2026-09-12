"""RQ job: audio file -> whisper transcript -> speaker reconciliation -> MongoDB ->
enqueue notes generation. Run as: rq worker transcribe-audio --url $REDIS_URL
"""
import logging

from common import repo
from common.queue import QUEUE_GENERATE_NOTES, get_queue

from .reconcile import assign_speakers
from .transcribe import transcribe_audio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("transcription_worker")


def transcribe_job(meeting_id: str, audio_file_path: str) -> None:
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        logger.error("Meeting %s not found, skipping transcription", meeting_id)
        return

    try:
        raw_segments = transcribe_audio(audio_file_path)
        caption_segments = repo.list_transcript_segments(meeting_id, source="caption")
        recording_start = meeting["actual_join_at"]

        annotated = assign_speakers(raw_segments, caption_segments, recording_start)
        for seg in annotated:
            repo.add_transcript_segment(
                meeting_id,
                seg["text"],
                seg["started_at"],
                speaker=seg["speaker"],
                ended_at=seg["ended_at"],
                source="whisper",
            )

        get_queue(QUEUE_GENERATE_NOTES).enqueue(
            "app.notes_worker.generate_notes_job",
            meeting_id,
            job_timeout="10m",
        )
        logger.info(
            "Transcribed meeting %s (%d segments), queued notes generation",
            meeting_id,
            len(annotated),
        )
    except Exception as exc:
        logger.exception("Transcription failed for meeting %s", meeting_id)
        repo.set_meeting_status(meeting_id, "failed", failure_reason=str(exc))
