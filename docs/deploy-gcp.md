# Deploying to a GCP VM with Docker

Everything (dashboard, both queue workers, the meet-bot) runs as one `docker compose`
stack on a single VM, talking to your existing hosted MongoDB Atlas + Upstash Redis.
Open the dashboard at `http://<vm-ip>:8000` — the bots keep running in the background
regardless of whether you have that tab open.

## 1. Create the VM

Whisper's `medium` model plus a live Chromium session need real memory - `e2-medium` will
swap and stall. Use at least `e2-standard-4` (4 vCPU / 16GB RAM).

```bash
gcloud compute instances create broll-notetaker \
  --zone=us-central1-a \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --boot-disk-size=60GB \
  --tags=broll-notetaker
```

Open the dashboard port. Restrict `--source-ranges` to your own IP if you can — `0.0.0.0/0`
exposes the dashboard to the whole internet with no auth in front of it:

```bash
gcloud compute firewall-rules create allow-broll-dashboard \
  --allow=tcp:8000 \
  --target-tags=broll-notetaker \
  --source-ranges=<your-ip>/32
```

## 2. Install Docker on the VM

```bash
gcloud compute ssh broll-notetaker --zone=us-central1-a
```
Then, on the VM:
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
```

## 3. Copy the repo and secrets onto the VM

From your local machine (not the VM):
```bash
gcloud compute scp --recurse . broll-notetaker:~/broll-notetaker --zone=us-central1-a
```

The two Google secrets are generated **locally**, same as the non-Docker setup in the main
README — Google blocks scripted logins, so these still need a real browser on your laptop:
- `scripts/bootstrap_calendar_auth.py` -> `secrets/google-calendar-token.json`
- `scripts/bootstrap_auth.py` -> `secrets/chrome-profile/` (a full persistent Chrome
  profile, not just a cookie dump — see the comment in `meet_worker/join_meeting.py` for
  why that matters for how long the login survives)

Make sure both end up in `~/broll-notetaker/secrets/` on the VM (the `scp --recurse` above
carries them over if they already existed locally when you ran it; otherwise copy them up
after generating them).

A periodic job checks whether this session is still signed in and posts to Slack if it
isn't (`SESSION_HEALTHCHECK_INTERVAL_MINUTES` in `.env`, default every 4h) — so you find out
and can re-run `bootstrap_auth.py` before it silently costs a real demo.

## 4. Configure environment

On the VM:
```bash
cd ~/broll-notetaker
cp .env.example .env
nano .env
```

Fill in at least:
- `OPENROUTER_API_KEY`
- `GOOGLE_CALENDAR_ID`, `DEMO_EVENT_KEYWORD`, `BOT_GOOGLE_EMAIL`, `BOT_DISPLAY_NAME`
- `PUBLIC_BASE_URL=http://<vm-external-ip>:8000` (used in links posted to Slack)
- `SLACK_WEBHOOK_URL` / `SLACK_ENABLED` if you want notes posted to Slack

`MONGODB_URI` and `REDIS_URL` should point at your actual hosted MongoDB Atlas / Upstash
Redis instances (whatever you're already using) - `docker-compose.yml` does not run local
Mongo/Redis containers, it passes these straight through from `.env`.

Leave `GOOGLE_CALENDAR_TOKEN_PATH`, `GOOGLE_CHROME_PROFILE_DIR`, and `AUDIO_OUTPUT_DIR` as-is -
`docker-compose.yml` overrides those three to point at the in-container paths regardless of
what's in `.env`.

## 5. Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
```

Dashboard: `http://<vm-external-ip>:8000`

## 6. Day-to-day operations

```bash
docker compose logs -f backend           # dashboard/API/scheduler
docker compose logs -f meet-worker        # bot join/leave, attendance, recording
docker compose logs -f transcription-worker
docker compose logs -f notes-worker

# after a git pull / code change:
docker compose build && docker compose up -d

# restart just one service:
docker compose restart backend
```

## Notes / limitations carried over from the non-Docker design

- Still **one meeting at a time** - `meet-worker` is a single container pinned to one
  virtual display and one virtual sound card, same constraint as the systemd version.
  Running two overlapping demos means scaling `meet-worker` replicas with per-instance
  display/sink numbers, which this compose file doesn't do out of the box.
- The 7-day OAuth token expiry for calendar access (while the Google OAuth consent screen is
  in "Testing" mode) still applies - see the main README for the option to submit for
  verification.
- No TLS/auth in front of the dashboard by default. If this ever needs to be reachable
  without VPN/IP-allowlisting, put a reverse proxy (e.g. Caddy, which gets you free
  auto-renewing HTTPS for a real domain in a couple of lines) in front of port 8000 and add
  basic auth there, rather than exposing 8000 directly to the internet.
