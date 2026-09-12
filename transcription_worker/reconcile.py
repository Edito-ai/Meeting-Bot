"""Assigns speaker names to Whisper's audio-only segments by borrowing the nearest
in-time speaker label from the live-caption transcript (which Meet attributes to a
speaker for us). Whisper gives accuracy; captions give (rough) speaker attribution."""
from datetime import datetime, timedelta

MATCH_TOLERANCE_SECONDS = 10


def assign_speakers(
    whisper_segments: list[dict],
    caption_segments: list[dict],
    recording_start: datetime,
) -> list[dict]:
    out = []
    for seg in whisper_segments:
        started_at = recording_start + timedelta(seconds=seg["start"])
        ended_at = recording_start + timedelta(seconds=seg["end"])

        speaker = None
        best_delta = None
        for cap in caption_segments:
            if not cap.get("speaker"):
                continue
            delta = abs((cap["started_at"] - started_at).total_seconds())
            if delta <= MATCH_TOLERANCE_SECONDS and (best_delta is None or delta < best_delta):
                best_delta = delta
                speaker = cap["speaker"]

        out.append({**seg, "speaker": speaker, "started_at": started_at, "ended_at": ended_at})
    return out
