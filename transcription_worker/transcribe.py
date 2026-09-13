"""Self-hosted speech-to-text via faster-whisper. Runs after each call ends to produce
a cleaner, more accurate transcript than Meet's live captions alone."""
import logging
import os

from faster_whisper import WhisperModel

logger = logging.getLogger("transcribe")

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(
            os.environ.get("WHISPER_MODEL_SIZE", "medium"),
            device=os.environ.get("WHISPER_DEVICE", "cpu"),
            compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        )
    return _model


def transcribe_audio(audio_path: str) -> list[dict]:
    model = _get_model()
    # No `language=` pin - our calls switch between English and Hindi/Hinglish call to
    # call, so we let Whisper auto-detect per file. The default only samples one ~30s
    # window for that guess though, which is unreliable if it lands on silence/crosstalk
    # right after the bot joins - language_detection_segments samples several windows
    # across the file and votes, which is far more robust for a call whose language
    # isn't known ahead of time.
    segments, info = model.transcribe(
        audio_path,
        vad_filter=True,
        language_detection_segments=3,
        language_detection_threshold=0.5,
    )
    logger.info(
        "Detected language=%s (probability=%.2f) for %s",
        info.language,
        info.language_probability,
        audio_path,
    )
    return [{"start": seg.start, "end": seg.end, "text": seg.text.strip()} for seg in segments]
