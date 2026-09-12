"""Records the meeting's audio via ffmpeg reading from the PulseAudio null-sink monitor
that the container's Chromium output is routed to (set up in entrypoint.sh)."""
import os
import signal
import subprocess
from pathlib import Path


def start_recording(meeting_id: str) -> tuple[subprocess.Popen, str]:
    output_dir = Path(os.environ.get("AUDIO_OUTPUT_DIR", "/opt/broll-notetaker/data/audio"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / f"{meeting_id}.wav")

    monitor_source = os.environ.get("PULSE_MONITOR_SOURCE", "meet_sink.monitor")

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-f", "pulse", "-i", monitor_source,
            "-ac", "1", "-ar", "16000",
            output_path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc, output_path


def stop_recording(proc: subprocess.Popen) -> None:
    proc.send_signal(signal.SIGINT)  # graceful stop so ffmpeg flushes/finalizes the file
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
