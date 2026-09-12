# Image for both the "backend" (dashboard + API + calendar scheduler) and "notes-worker"
# services - same code, docker-compose.yml just overrides the command for notes-worker.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend

COPY requirements/common.txt requirements/backend.txt requirements/
RUN pip install --no-cache-dir -r requirements/backend.txt

COPY common ./common
COPY backend ./backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
