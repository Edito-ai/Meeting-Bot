"""Self-hosted speech-to-text via faster-whisper. Runs after each call ends to produce
a cleaner, more accurate transcript than Meet's live captions alone."""
import os

from faster_whisper import WhisperModel

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
    segments, _info = model.transcribe(audio_path, vad_filter=True)
    return [{"start": seg.start, "end": seg.end, "text": seg.text.strip()} for seg in segments]
