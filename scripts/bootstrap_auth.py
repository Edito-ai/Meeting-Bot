"""Run this ONCE, locally, on a machine with a real display (NOT inside Docker).

Google actively blocks scripted logins (captchas, "this browser may not be secure"),
so instead of automating the login form, this opens a real Chromium window for you to
log into the bot's dedicated Google account by hand. The authenticated session is then
saved to secrets/google-auth-state.json, which the meet-worker container mounts
read-only and reuses for every future join — no further manual login needed unless
Google invalidates the session (then just re-run this).

Usage:
    pip install playwright
    playwright install chromium
    python scripts/bootstrap_auth.py

Afterwards, copy the generated secrets/google-auth-state.json onto the server, into
/opt/broll-notetaker/secrets/ (see README.md).
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "secrets" / "google-auth-state.json"


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://accounts.google.com/")

        print("A browser window has opened.")
        print("1. Log into the bot's Google account (BOT_GOOGLE_EMAIL in .env).")
        print("2. Then visit https://meet.google.com/ once to confirm access.")
        input("Press Enter here once you're fully logged in... ")

        context.storage_state(path=str(OUTPUT_PATH))
        print(f"Saved session to {OUTPUT_PATH}")
        browser.close()


if __name__ == "__main__":
    main()
