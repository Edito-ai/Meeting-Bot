"""Run this ONCE, locally (needs a real browser), to let the bot read the Google
Calendar of a personal Gmail account (not a Workspace one - no domain-wide delegation
possible, so this uses a real OAuth login instead).

Prerequisites (see README.md for the click-path):
  1. A Google Cloud project with the Calendar API enabled.
  2. An OAuth consent screen configured (User type: External, your Gmail added as a
     test user).
  3. An OAuth Client ID of type "Desktop app", downloaded as JSON and saved at
     secrets/google-oauth-client.json.

Usage:
    pip install google-auth-oauthlib google-api-python-client
    python scripts/bootstrap_calendar_auth.py

This opens a browser - log in as the Gmail account whose calendar has the demos, and
grant access (read+write on events - the bot adds itself as a guest on each demo so
Meet auto-admits it instead of needing a manual "Admit" click). Saves
secrets/google-calendar-token.json; copy that file onto the server at
/opt/broll-notetaker/secrets/google-calendar-token.json.

NOTE: while the OAuth consent screen is in "Testing" status, Google expires this token
after 7 days of the app being unverified - see the "Google Calendar access" section in
README.md for what your options are (re-run this weekly, or submit for verification).
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"
CLIENT_SECRET_PATH = SECRETS_DIR / "google-oauth-client.json"
TOKEN_PATH = SECRETS_DIR / "google-calendar-token.json"


def main() -> None:
    if not CLIENT_SECRET_PATH.exists():
        raise SystemExit(
            f"Missing {CLIENT_SECRET_PATH}.\n"
            "Download it from Google Cloud Console > APIs & Services > Credentials > "
            "your OAuth 2.0 Client ID (type: Desktop app)."
        )

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"Saved calendar access token to {TOKEN_PATH}")
    print("Copy this file to the server at /opt/broll-notetaker/secrets/google-calendar-token.json")


if __name__ == "__main__":
    main()
