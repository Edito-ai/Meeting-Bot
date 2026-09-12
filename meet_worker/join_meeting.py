"""Handles the actual Playwright mechanics of joining/leaving a Google Meet call.

Google actively fights scripted logins (captchas, "browser may not be secure"), so
rather than automating the login form on every join, we authenticate ONCE manually
(see scripts/bootstrap_auth.py) and reuse the saved storage_state (cookies/localStorage).
"""
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("join_meeting")

STORAGE_STATE_PATH = os.environ.get(
    "GOOGLE_AUTH_STATE_PATH", "/opt/broll-notetaker/secrets/google-auth-state.json"
)
BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "Broll Notetaker (Recording)")


def _click_if_present(locator, timeout: int = 5000) -> bool:
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.click()
        return True
    except PlaywrightTimeoutError:
        return False


def launch_authenticated_context(playwright: Playwright) -> tuple[Browser, BrowserContext]:
    if not os.path.exists(STORAGE_STATE_PATH):
        raise RuntimeError(
            f"No saved Google auth state at {STORAGE_STATE_PATH}. "
            "Run scripts/bootstrap_auth.py locally once and copy the output into /opt/broll-notetaker/secrets/."
        )

    browser = playwright.chromium.launch(
        headless=False,  # Meet degrades/blocks headless Chromium; we run under Xvfb instead.
        args=[
            "--use-fake-ui-for-media-stream",  # auto-accept mic/cam permission prompts
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    context = browser.new_context(
        storage_state=STORAGE_STATE_PATH,
        permissions=["microphone", "camera"],
    )
    return browser, context


def join_meeting(context: BrowserContext, meet_url: str) -> tuple[Page, datetime]:
    page = context.new_page()
    page.goto(meet_url, wait_until="domcontentloaded")

    # If the bot's own account is already connected to this call - e.g. the worker process
    # crashed last time without leaving cleanly - Meet shows "Switch here" instead of the
    # normal join screen. Reclaim that stale session before continuing.
    switch_button = page.get_by_role("button", name=re.compile("switch here", re.I))
    if _click_if_present(switch_button, timeout=5000):
        page.wait_for_timeout(2000)

    _click_if_present(page.get_by_role("button", name=re.compile("turn off microphone", re.I)))
    _click_if_present(page.get_by_role("button", name=re.compile("turn off camera", re.I)))

    name_input = page.get_by_placeholder(re.compile("your name", re.I))
    try:
        name_input.wait_for(state="visible", timeout=3000)
        name_input.fill(BOT_DISPLAY_NAME)
    except PlaywrightTimeoutError:
        pass

    join_button = page.get_by_role("button", name=re.compile(r"^(join now|ask to join)$", re.I))
    try:
        join_button.click(timeout=15000)
    except PlaywrightTimeoutError:
        # Join button never showed up - most likely Google blocked the reused auth state
        # with a re-verification/sign-in screen. Dump what was actually on screen so this
        # is debuggable after the fact instead of a bare timeout.
        debug_dir = Path(os.environ.get("AUDIO_OUTPUT_DIR", "/app/data/audio")).parent / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(debug_dir / "join_failure.png"))
        (debug_dir / "join_failure.html").write_text(page.content(), encoding="utf-8")
        logger.error("Join button never appeared. Page title=%r url=%r - see %s", page.title(), page.url, debug_dir)
        raise

    # Confirm we're actually in the call.
    page.get_by_role("button", name=re.compile("leave call", re.I)).wait_for(timeout=60_000)
    return page, datetime.now(timezone.utc)


def post_identification_message(page: Page) -> None:
    message = (
        f"\U0001F44B {BOT_DISPLAY_NAME} here — I'm recording audio and taking notes "
        "for this call so the team doesn't have to. Reach out to your Broll host with questions."
    )
    try:
        page.get_by_role("button", name=re.compile("chat with everyone", re.I)).click(timeout=5000)
        chat_input = page.get_by_role("textbox", name=re.compile("send a message", re.I))
        chat_input.fill(message)
        chat_input.press("Enter")
    except PlaywrightTimeoutError:
        logger.warning("Could not post identification chat message")


def is_call_still_active(page: Page) -> bool:
    """True while the bot is still in the call (i.e. hasn't been removed/ended)."""
    try:
        return page.get_by_role("button", name=re.compile("leave call", re.I)).is_visible()
    except Exception:
        return False


def leave_meeting(page: Page) -> None:
    if not _click_if_present(page.get_by_role("button", name=re.compile("leave call", re.I)), timeout=5000):
        logger.warning("Leave call button not found, closing page instead")
