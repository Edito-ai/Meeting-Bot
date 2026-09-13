"""Run this ONCE, locally, on a machine with a real display (NOT inside Docker).

Google actively blocks scripted logins (captchas, "this browser may not be secure"),
so instead of automating the login form, this opens a real Chromium window for you to
log into the bot's dedicated Google account by hand. The authenticated session is saved
as a full persistent Chrome profile (not just a storage_state cookie dump) into
secrets/chrome-profile/, which the meet-worker container mounts read-write and reuses
for every future join.

A full profile (not just cookies+localStorage) matters here: Google's risk engine trusts
a consistent device profile a lot more than bare cookies replayed into a brand-new
browser context on every launch, so sessions survive much longer this way. It still
isn't permanent - Google can and will invalidate it eventually (device/IP change,
inactivity, security checkup) - so re-run this whenever meet_worker's session
health-check job reports it dead.

Usage:
    pip install playwright
    playwright install chromium
    python scripts/bootstrap_auth.py

Afterwards, copy the generated secrets/chrome-profile/ directory onto the server, into
/opt/broll-notetaker/secrets/ (see README.md).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "secrets" / "chrome-profile"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(OUTPUT_DIR),
            headless=False,
        )
        page = context.new_page()
        page.goto("https://accounts.google.com/")

        print("A browser window has opened.")
        print("1. Log into the bot's Google account (BOT_GOOGLE_EMAIL in .env).")
        print("2. Then visit https://meet.google.com/ once to confirm access.")
        input("Press Enter here once you're fully logged in... ")

        print(f"Session saved to {OUTPUT_DIR} (persistent Chrome profile).")
        context.close()


if __name__ == "__main__":
    main()
