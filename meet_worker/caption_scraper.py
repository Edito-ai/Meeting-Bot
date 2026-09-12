"""Best-effort real-time transcript from Meet's live captions (speaker-attributed,
zero extra infra). This is a fallback/cross-check layer — the authoritative transcript
comes from the Transcription Worker re-running faster-whisper on the full audio
recording after the call ends, since live captions can drop words under noise/accents.
"""
import re
import logging
from datetime import datetime, timezone

from playwright.sync_api import Page

from common import repo

logger = logging.getLogger("caption_scraper")


def enable_captions(page: Page) -> None:
    try:
        page.get_by_role("button", name=re.compile("turn on captions", re.I)).click(timeout=5000)
    except Exception:
        logger.warning("Could not enable captions (may already be on, or Meet's UI changed)")


def _read_caption_lines(page: Page) -> list[str]:
    try:
        region = page.locator('[aria-label="Captions"]')
        text = region.inner_text(timeout=1000)
    except Exception:
        return []
    return [line.strip() for line in text.split("\n") if line.strip()]


def _split_speaker(line: str, known_names: set[str]) -> tuple[str | None, str]:
    for name in known_names:
        if line.startswith(name):
            rest = line[len(name):].lstrip(":- ").strip()
            if rest:
                return name, rest
    return None, line


class CaptionScraper:
    """Meet's caption box shows one utterance that keeps growing word-by-word while someone
    talks (e.g. "Hello!" -> "Hello! Hello," -> "Hello! Hello, hello."), then either stabilizes
    or gets replaced once they stop. Naively saving every poll's raw text would save every
    intermediate growth step as a separate "new" segment - so instead we track one pending
    buffer and only commit it once it stops changing (or gets replaced by something that isn't
    a continuation of it), which collapses all of that into a single final segment.
    """

    def __init__(self, meeting_id: str, page: Page):
        self.meeting_id = meeting_id
        self.page = page
        self.pending_text: str = ""
        self.pending_started_at: datetime | None = None
        self.last_raw: str = ""

    def start(self) -> None:
        enable_captions(self.page)

    def _current_blob(self) -> str:
        try:
            region = self.page.locator('[aria-label="Captions"]')
            return region.inner_text(timeout=1000).strip()
        except Exception:
            return ""

    def _commit_pending(self, known_names: set[str]) -> None:
        if self.pending_text and self.pending_started_at:
            speaker, text = _split_speaker(self.pending_text, known_names)
            repo.add_transcript_segment(
                self.meeting_id, text, self.pending_started_at, speaker=speaker, source="caption"
            )
        self.pending_text = ""
        self.pending_started_at = None

    def poll_once(self, known_names: set[str]) -> None:
        now = datetime.now(timezone.utc)
        current = self._current_blob()

        if current == self.last_raw:
            # Unchanged since last poll - the utterance has stabilized, commit it once
            # (harmless no-op on repeated polls since pending_text gets cleared after commit).
            self._commit_pending(known_names)
        elif self.pending_text and current.startswith(self.pending_text):
            # Still the same utterance growing - extend the buffer, keep the original start time.
            self.pending_text = current
        else:
            # Genuinely new content - commit whatever was pending first, then start fresh.
            self._commit_pending(known_names)
            self.pending_text = current
            self.pending_started_at = now

        self.last_raw = current

    def finalize(self, known_names: set[str]) -> None:
        """Flush any still-growing caption text when the call ends, so the last thing said
        isn't lost just because it never had a chance to stabilize."""
        self._commit_pending(known_names)
