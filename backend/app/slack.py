from common.slack import post_message


def notify_notes_ready(meeting_title: str, dashboard_url: str, summary: str) -> None:
    text = f"*Demo notes ready: {meeting_title}*\n{summary}\n<{dashboard_url}|View full notes>"
    post_message(text)
