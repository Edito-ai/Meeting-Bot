import json
import os

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a sales-ops assistant that turns raw demo-call transcripts into \
crisp internal notes for a B2B sales team. Be specific and factual - only include things \
actually said in the transcript. Never invent details. If something is unclear, omit it \
rather than guessing."""

NOTES_SCHEMA_INSTRUCTIONS = """Return ONLY a JSON object with exactly these keys:
{
  "summary": "2-4 sentence plain-English summary of the call",
  "key_points": ["short bullet", "..."],
  "objections": ["any concerns/objections/hesitations the prospect raised", "..."],
  "action_items": ["concrete follow-up task, ideally with an owner", "..."],
  "next_steps": ["agreed next step, e.g. 'send pricing by Friday'", "..."]
}
Use empty arrays for sections with nothing relevant. Do not wrap the JSON in markdown fences."""


def build_transcript_text(segments: list[dict]) -> str:
    lines = []
    for seg in segments:
        speaker = seg.get("speaker") or "Unknown"
        lines.append(f"[{speaker}]: {seg['text']}")
    return "\n".join(lines)


def build_attendance_text(participants: list[dict]) -> str:
    lines = []
    for p in participants:
        leave = p.get("leave_at") or "still in call / not recorded"
        lines.append(f"- {p['name']}: joined {p['join_at']}, left {leave}")
    return "\n".join(lines) if lines else "(no attendance data captured)"


def generate_notes(meeting_title: str, transcript_segments: list[dict], participants: list[dict]) -> dict:
    transcript_text = build_transcript_text(transcript_segments)
    attendance_text = build_attendance_text(participants)

    user_message = f"""Meeting: {meeting_title}

Attendance:
{attendance_text}

Transcript:
{transcript_text}

{NOTES_SCHEMA_INSTRUCTIONS}"""

    response = httpx.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            # Optional OpenRouter attribution headers, harmless to include.
            "HTTP-Referer": os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000"),
            "X-Title": "Broll Meet Notetaker",
        },
        json={
            "model": os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=120,
    )
    response.raise_for_status()

    # Free models don't always honor response_format strictly, so parse defensively -
    # strip markdown fences if the model wrapped the JSON in one anyway.
    raw_text = response.json()["choices"][0]["message"]["content"].strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.lower().startswith("json"):
            raw_text = raw_text[4:]
    parsed = json.loads(raw_text.strip())

    return {
        "summary": parsed.get("summary", ""),
        "key_points": parsed.get("key_points", []),
        "objections": parsed.get("objections", []),
        "action_items": parsed.get("action_items", []),
        "next_steps": parsed.get("next_steps", []),
        "raw_model_output": parsed,
    }
