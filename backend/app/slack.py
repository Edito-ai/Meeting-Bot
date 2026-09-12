import os

import httpx


def notify_notes_ready(meeting_title: str, dashboard_url: str, summary: str) -> None:
    if os.environ.get("SLACK_ENABLED", "false").lower() != "true":
        return
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    text = f"*Demo notes ready: {meeting_title}*\n{summary}\n<{dashboard_url}|View full notes>"
    try:
        httpx.post(webhook_url, json={"text": text}, timeout=10)
    except httpx.HTTPError as exc:
        import logging

        logging.getLogger("slack").warning("Failed to post Slack notification: %s", exc)
