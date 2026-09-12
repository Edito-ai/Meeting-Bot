"""Tracks who's in the call and when they joined/left by polling Meet's People panel.

NOTE: Google Meet's DOM/class names are obfuscated and rotate; the selectors below use
role/aria-label where possible for stability, but expect to maintain this as Meet's UI
evolves — that's an inherent cost of DOM scraping vs. a documented API.
"""
import re
import logging
from datetime import datetime, timezone

from playwright.sync_api import Page

from common import repo

logger = logging.getLogger("attendance_tracker")


def _open_people_panel(page: Page) -> None:
    try:
        page.get_by_role("button", name=re.compile("people", re.I)).click(timeout=5000)
    except Exception:
        logger.warning("Could not open People panel")


def _read_current_participants(page: Page) -> set[str]:
    try:
        items = page.locator('[role="listitem"]').all_inner_texts()
    except Exception:
        return set()

    names = set()
    for raw in items:
        name = raw.strip().split("\n")[0].strip()
        if name and not name.lower().startswith("no one"):
            names.add(name)
    return names


class AttendanceTracker:
    def __init__(self, meeting_id: str, page: Page):
        self.meeting_id = meeting_id
        self.page = page
        self.current: set[str] = set()

    def start(self) -> None:
        _open_people_panel(self.page)

    def poll_once(self) -> None:
        latest = _read_current_participants(self.page)
        now = datetime.now(timezone.utc)

        for name in latest - self.current:
            repo.record_participant_join(self.meeting_id, name, now)
        for name in self.current - latest:
            repo.record_participant_leave(self.meeting_id, name, now)

        self.current = latest

    def finalize(self) -> None:
        """Mark anyone still showing present as having left when the bot itself leaves."""
        now = datetime.now(timezone.utc)
        for name in self.current:
            repo.record_participant_leave(self.meeting_id, name, now)
        self.current = set()
