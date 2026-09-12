FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# ffmpeg: faster-whisper/ctranslate2 shells out to it to decode the recorded .wav.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/common.txt requirements/transcription-worker.txt requirements/
RUN pip install --no-cache-dir -r requirements/transcription-worker.txt

COPY common ./common
COPY transcription_worker ./transcription_worker

CMD ["sh", "-c", "rq worker transcribe-audio --url \"$REDIS_URL\""]
