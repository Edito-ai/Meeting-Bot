import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from common import repo
from common.db import ensure_indexes

from .scheduler import run_scheduler_loop

logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    task = asyncio.create_task(run_scheduler_loop())
    yield
    task.cancel()


app = FastAPI(title="Broll Meet Notetaker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
def dashboard_home(request: Request):
    meetings = repo.list_meetings(limit=100)
    return templates.TemplateResponse(request, "meetings_list.html", {"meetings": meetings})


@app.get("/meetings/{meeting_id}")
def meeting_detail(request: Request, meeting_id: str):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        return templates.TemplateResponse(
            request, "not_found.html", {"meeting_id": meeting_id}, status_code=404
        )
    participants = repo.list_participants(meeting_id)
    segments = repo.list_transcript_segments(meeting_id)
    notes = repo.get_notes(meeting_id)
    return templates.TemplateResponse(
        request,
        "meeting_detail.html",
        {
            "meeting": meeting,
            "participants": participants,
            "segments": segments,
            "notes": notes,
        },
    )


# --- JSON API (for programmatic access / future CRM integration) ---


@app.get("/api/meetings")
def api_list_meetings():
    return repo.list_meetings(limit=100)


@app.get("/api/meetings/{meeting_id}")
def api_meeting_detail(meeting_id: str):
    meeting = repo.get_meeting(meeting_id)
    if not meeting:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "meeting": meeting,
        "participants": repo.list_participants(meeting_id),
        "transcript": repo.list_transcript_segments(meeting_id),
        "notes": repo.get_notes(meeting_id),
    }


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
