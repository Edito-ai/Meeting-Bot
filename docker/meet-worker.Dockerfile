# Base image ships Chromium + all of Playwright's system deps prebuilt, so we don't have
# to hand-roll the (large) list of apt packages Chromium needs to run headed.
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# xvfb: virtual display Chromium runs against (Meet degrades/blocks true headless Chromium).
# pulseaudio: virtual sound card so ffmpeg can capture the tab's call audio.
# ffmpeg: records the PulseAudio null-sink monitor to a .wav file for the call's duration.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb pulseaudio ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/common.txt requirements/meet-worker.txt requirements/
RUN pip install --no-cache-dir -r requirements/meet-worker.txt

COPY common ./common
COPY meet_worker ./meet_worker

COPY docker/meet-worker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
