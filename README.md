# Broll Meet Notetaker

Self-hosted bot that watches for scheduled demo calls, joins the Google Meet automatically,
records attendance (who joined/left and when) and the full conversation, then generates
structured notes — all built in-house, no third-party meeting-bot SaaS, no containers.
Every service runs as a plain Python process (via systemd) directly on your server.

## How it works

1. **Backend** (FastAPI, `backend/`) polls Google Calendar every 30s for upcoming events
   matching `DEMO_EVENT_KEYWORD`. When a matching event's start time is ~`JOIN_LEAD_MINUTES`
   away, it enqueues a join job on Redis.
2. **meet-worker** (`meet_worker/`) picks up the job, joins the Meet using Playwright under a
   virtual display (Xvfb), mutes its own mic/camera, posts a chat message identifying itself,
   then for the rest of the call: tracks who's present via the People panel, scrapes live
   captions for a rough speaker-attributed transcript, and records the full audio via ffmpeg
   reading from a PulseAudio null sink.
3. **transcription-worker** (`transcription_worker/`) re-transcribes the recorded audio with
   self-hosted `faster-whisper` for accuracy, and reconciles it with the caption-derived
   speaker labels.
4. **notes-worker** (same code as the backend, run as a separate process) sends the reconciled
   transcript + attendance log to a free model via OpenRouter and produces a structured
   summary, then posts it to Slack if configured.
5. Everything lands in MongoDB and is browsable at `/` (dashboard) or `/api/meetings` (JSON).

Six long-running processes in total, each kept alive by systemd: `broll-xvfb`,
`broll-pulseaudio`, `broll-backend`, `broll-notes-worker`, `broll-meet-worker`,
`broll-transcription-worker` — plus natively-installed MongoDB and Redis.

## One-time setup (Ubuntu/Debian server)

### 1. Copy the repo to the server
```bash
sudo mkdir -p /opt/broll-notetaker
sudo cp -r . /opt/broll-notetaker   # or git clone directly into that path
```
Everything below assumes this path — it's hardcoded into the systemd units in `systemd/`.

### 2. Google Calendar access (for the Backend to see scheduled demos)
If demos land on a **personal Gmail account** (not Google Workspace), there's no domain-wide
delegation available, so this uses a one-time OAuth login instead:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project (or reuse
   one) and enable the **Google Calendar API** (APIs & Services > Library).
2. Configure the **OAuth consent screen**: User type "External", add the Gmail account
   (the one whose calendar has the demos) as a test user.
3. Create an **OAuth 2.0 Client ID** (APIs & Services > Credentials > Create Credentials),
   type "Desktop app". Download the JSON and save it as
   `secrets/google-oauth-client.json` **locally** (not on the server yet).
4. Run this locally — it opens a browser, log in as the Gmail account and grant calendar
   read access:
   ```bash
   pip install google-auth-oauthlib google-api-python-client
   python scripts/bootstrap_calendar_auth.py
   ```
   This saves `secrets/google-calendar-token.json` locally; copy it to the server in step 4.

**Heads up:** while the OAuth consent screen stays in "Testing" status (the default, no
Google review needed), this token expires after 7 days and you'll need to re-run
`bootstrap_calendar_auth.py`. To avoid that, submit the app for Google's verification review
(required since `calendar.readonly` is a "sensitive" scope) to move it to "In production" —
worth doing once the bot is working, more setup than a personal project strictly needs.

If demos ever move to a **Google Workspace** account instead, swap `calendar_client.py` back
to a service account with domain-wide delegation — no 7-day expiry, but only works for a
Workspace-managed calendar, not a personal Gmail one.

### 3. Bot Google account (for meet-worker to actually join calls)
Create a dedicated Google account for the bot (e.g. `notes@trybroll.com`). Google blocks
scripted logins, so authenticate it once by hand, **on your own laptop, not the server**
(it needs a real display):
```bash
pip install playwright
playwright install chromium
python scripts/bootstrap_auth.py
```
This opens a real browser — log into the bot account, then press Enter. It saves
`secrets/google-auth-state.json` locally; copy that file to the server in the next step.

### 4. Environment + secrets on the server
```bash
cd /opt/broll-notetaker
cp .env.example .env
# fill in DB password, OPENROUTER_API_KEY, Slack webhook (optional), etc.
```
Then place on the server:
- `/opt/broll-notetaker/secrets/google-calendar-token.json` (from step 2)
- `/opt/broll-notetaker/secrets/google-auth-state.json` (copied from step 3)

### 5. Run the setup script (packages, MongoDB, Redis, venv, Playwright's Chromium)
```bash
sudo ./scripts/setup_server.sh
```

### 6. Install and start everything
```bash
sudo ./scripts/install_services.sh
```
Dashboard: `http://<server-ip>:8000`

### Updating after a code change
```bash
git pull   # or re-copy files
/opt/broll-notetaker/.venv/bin/pip install -r requirements.txt   # if deps changed
sudo systemctl restart broll-backend broll-notes-worker broll-meet-worker broll-transcription-worker
```

## Verification checklist
- Create a test Calendar event a few minutes out, titled with your `DEMO_EVENT_KEYWORD`, with
  a Google Meet link. Confirm it shows up at `/` shortly after (backend discovers it within 30s).
- Confirm meet-worker joins on time and posts its identification message in the call's chat.
- Join the test call yourself from another account; confirm the attendance table on the
  meeting's detail page shows your join time (and leave time once you exit).
- After the call ends, confirm `data/audio/<meeting_id>.wav` exists, then check the transcript
  and generated notes appear on the meeting's detail page within a couple minutes.

## Known limitations (MVP / Phase 1)
- Free OpenRouter models have tighter rate limits and can be slower/less consistent than paid
  ones — if notes generation starts failing/timing out under real usage, either switch
  `OPENROUTER_MODEL` to a paid model (no code change needed, same API) or add retry/backoff in
  `notes_worker.py`.
- Only one meeting at a time — `broll-meet-worker` is a single process pinned to one Xvfb
  display (`:99`) and one PulseAudio sink. Handling concurrent demo calls (Phase 2) means
  templating the meet-worker + Xvfb + PulseAudio units per instance (different display numbers,
  different sinks) — more setup work without Docker's built-in isolation.
- Meet's DOM (people panel, captions, buttons) isn't a stable public API — selectors in
  `meet_worker/*.py` use `aria-label`/role where possible but may need updates if Google
  changes the UI.
- Live captions give rough speaker attribution; Whisper gives accurate text. Fully accurate
  diarization (Phase 2/3) would need a dedicated model (e.g. pyannote.audio) instead of the
  caption-timestamp-matching heuristic in `transcription_worker/reconcile.py`.
- The bot always identifies itself in the meeting chat on join — this is intentional
  (recording-consent transparency), not a bug to "fix" by removing it.

## Repo layout
```
backend/                  FastAPI dashboard + API + in-process calendar scheduler + notes worker
meet_worker/               Playwright bot: join, attendance, captions, audio recording
transcription_worker/      faster-whisper re-transcription + speaker reconciliation
common/                    Shared DB + queue helpers used by all services
scripts/init_db.py           Creates MongoDB indexes (run once by setup_server.sh, also self-heals on backend startup)
scripts/setup_server.sh      One-time server setup (packages, DB, venv, Playwright browser)
scripts/install_services.sh Installs + starts the systemd units in systemd/
scripts/bootstrap_auth.py    One-time manual Google login helper (run locally, not on server)
systemd/                    One .service unit per long-running process
requirements.txt             Single shared virtualenv for every service
```
