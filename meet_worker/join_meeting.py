"""Handles the actual Playwright mechanics of joining/leaving a Google Meet call.

Google actively fights scripted logins (captchas, "browser may not be secure"), so
rather than automating the login form on every join, we authenticate ONCE manually
(see scripts/bootstrap_auth.py) and reuse the saved Chrome profile. A full persistent
profile (not just a storage_state cookie dump) is what we reuse here - Google's risk
engine trusts a consistent device profile far longer than bare cookies replayed into a
fresh context every launch, which used to get the session flagged and bounced to a
"Sign in" page within a day or two of production use.
"""
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger("join_meeting")

CHROME_PROFILE_DIR = os.environ.get(
    "GOOGLE_CHROME_PROFILE_DIR", "/opt/broll-notetaker/secrets/chrome-profile"
)
BOT_DISPLAY_NAME = os.environ.get("BOT_DISPLAY_NAME", "Broll Notetaker (Recording)")


def _click_if_present(locator, timeout: int = 5000) -> bool:
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.click()
        return True
    except PlaywrightTimeoutError:
        return False


def launch_authenticated_context(playwright: Playwright) -> BrowserContext:
    if not os.path.isdir(CHROME_PROFILE_DIR) or not os.listdir(CHROME_PROFILE_DIR):
        raise RuntimeError(
            f"No saved Chrome profile at {CHROME_PROFILE_DIR}. "
            "Run scripts/bootstrap_auth.py locally once and copy secrets/chrome-profile/ into "
            "/opt/broll-notetaker/secrets/."
        )

    # launch_persistent_context (not launch() + new_context(storage_state=...)) is what makes
    # the login stick - see the module docstring for why.
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=CHROME_PROFILE_DIR,
        headless=False,  # Meet degrades/blocks headless Chromium; we run under Xvfb instead.
        permissions=["microphone", "camera"],
        args=[
            "--use-fake-ui-for-media-stream",  # auto-accept mic/cam permission prompts
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    return context


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
        # 45s, not 15s: on a resource-constrained VM the lobby (camera/mic preview, name
        # field) can take a while to finish rendering before the button is click-stable -
        # confirmed via debug screenshot that the button was present and normal-looking, just
        # not yet actionable when a 15s attempt timed out.
        join_button.click(timeout=45_000)
    except PlaywrightTimeoutError:
        # Join button never showed up at all - most likely Google blocked the reused auth
        # state with a re-verification/sign-in screen. Dump what was actually on screen so
        # this is debuggable after the fact instead of a bare timeout.
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


def is_session_signed_in(context: BrowserContext) -> bool:
    """Lightweight probe for the periodic health-check job: loads Meet without joining
    anything and checks whether Google bounced us to a sign-in page, which is exactly
    what happens once the saved Chrome profile's session dies (see module docstring)."""
    page = context.new_page()
    try:
        page.goto("https://meet.google.com/landing", wait_until="domcontentloaded", timeout=30_000)
        return "accounts.google.com" not in page.url and "sign in" not in page.title().lower()
    finally:
        page.close()
