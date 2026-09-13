"""Slack webhook notifications, shared by backend and meet_worker (e.g. the session
health-check job needs to alert from inside the meet-worker container)."""
import logging
import os

import httpx

logger = logging.getLogger("slack")


def post_message(text: str) -> None:
    if os.environ.get("SLACK_ENABLED", "false").lower() != "true":
        return
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    try:
        httpx.post(webhook_url, json={"text": text}, timeout=10)
    except httpx.HTTPError as exc:
        logger.warning("Failed to post Slack notification: %s", exc)


def notify_session_invalid(reason: str) -> None:
    post_message(f"*:warning: Meet bot Google session check failed*\n{reason}")
