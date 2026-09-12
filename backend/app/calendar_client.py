"""Polls Google Calendar for upcoming demo events and resolves their Meet link."""
import os
import re
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Read+write on events (not full calendar access) - needed so the bot can add itself as a
# guest on each demo (see ensure_bot_invited), which is what lets Meet auto-admit it into
# the call instead of the host having to manually click "Admit" every time.
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarEvent(TypedDict):
    id: str
    title: str
    meet_url: str
    organizer_email: str | None
    attendees: list[str]
    start: datetime
    end: datetime | None


_MEET_URL_RE = re.compile(r"https://meet\.google\.com/[a-z0-9-]+", re.IGNORECASE)


def _parse_iso(value: str | None) -> datetime | None:
    """Google's dateTime strings are ISO8601 with an offset (e.g. '2026-09-12T10:00:00+05:30').
    Mongo needs real datetimes (not strings) to do range queries, so parse at the boundary."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _get_credentials() -> Credentials:
    """Loads the OAuth token produced by scripts/bootstrap_calendar_auth.py and refreshes
    it in place when it's expired. This is a personal Gmail account, not Google Workspace,
    so there's no domain-wide delegation available - a real user-consent OAuth login
    (done once, by hand) is the only way in, same idea as the Meet bot's own login."""
    token_path = os.environ["GOOGLE_CALENDAR_TOKEN_PATH"]
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return creds


def _get_service():
    return build("calendar", "v3", credentials=_get_credentials())


def _extract_meet_url(event: dict) -> str | None:
    entry_points = (event.get("conferenceData") or {}).get("entryPoints", [])
    for ep in entry_points:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]

    haystack = " ".join(
        filter(None, [event.get("location"), event.get("description"), event.get("hangoutLink")])
    )
    match = _MEET_URL_RE.search(haystack)
    if match:
        return match.group(0)
    return event.get("hangoutLink")


def fetch_upcoming_demo_events(window_minutes: int = 60) -> list[CalendarEvent]:
    service = _get_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    keyword = os.environ.get("DEMO_EVENT_KEYWORD", "demo").lower()

    now = datetime.now(timezone.utc)
    time_max = now + timedelta(minutes=window_minutes)

    result = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        )
        .execute()
    )

    events: list[CalendarEvent] = []
    for item in result.get("items", []):
        haystack = f"{item.get('summary', '')} {item.get('description', '')}".lower()
        if keyword not in haystack:
            continue

        meet_url = _extract_meet_url(item)
        start = _parse_iso((item.get("start") or {}).get("dateTime"))
        if not meet_url or not item.get("id") or not start:
            continue

        attendees = [a["email"] for a in item.get("attendees", []) if a.get("email")]

        events.append(
            CalendarEvent(
                id=item["id"],
                title=item.get("summary", "Untitled demo"),
                meet_url=meet_url,
                organizer_email=(item.get("organizer") or {}).get("email"),
                attendees=attendees,
                start=start,
                end=_parse_iso((item.get("end") or {}).get("dateTime")),
            )
        )
    return events


def ensure_bot_invited(event_id: str, attendees: list[str]) -> None:
    """Adds the Meet bot's own Google account as a guest on the calendar event, if it isn't
    already. Being an actual invited guest - not just someone with the Meet link - is what
    lets Google Meet auto-admit the bot straight into the call instead of showing "asking to
    join" and waiting for the host to click Admit every single time."""
    bot_email = os.environ.get("BOT_GOOGLE_EMAIL")
    if not bot_email or bot_email.lower() in [a.lower() for a in attendees]:
        return

    service = _get_service()
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")
    updated_attendees = [{"email": a} for a in attendees] + [{"email": bot_email}]
    service.events().patch(
        calendarId=calendar_id,
        eventId=event_id,
        body={"attendees": updated_attendees},
        sendUpdates="none",
    ).execute()
