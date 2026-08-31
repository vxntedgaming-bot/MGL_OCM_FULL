"""Retryable Discord outbox. Official DB writes happen first; Discord never rolls them back."""

from django.utils import timezone

from mgl.models import DiscordEvent, NewsPost


CHANNEL_FOR_CATEGORY = {
    NewsPost.RESULTS: "NEWS",
    NewsPost.TRANSFER: "TRANSFER",
    NewsPost.AUCTION: "AUCTIONS",
    NewsPost.FREE_AGENT: "FREE_AGENTS",
    NewsPost.PRESS: "PRESS",
    NewsPost.MANAGER: "NEWS",
    NewsPost.SIGNING: "NEWS",
    NewsPost.SCOUTING: "NEWS",
    NewsPost.REWARD: "NEWS",
}


def queue_discord_event(event_type, payload=None, *, channel_key="", news_post=None):
    payload = payload or {}
    channel = channel_key or CHANNEL_FOR_CATEGORY.get(event_type, "NEWS")
    return DiscordEvent.objects.create(
        event_type=event_type,
        channel_key=channel,
        payload=payload,
        news_post=news_post,
        status=DiscordEvent.PENDING,
    )


def queue_from_news(post):
    if post is None or not post.published:
        return None
    if DiscordEvent.objects.filter(news_post=post).exists():
        return None
    body = post.body or ""
    title = post.title or ""
    if post.category == NewsPost.PRESS:
        text = format_press_discord(post)
    else:
        text = f"**{title}**\n{body}".strip()
    return queue_discord_event(
        post.category,
        {
            "title": title,
            "body": body,
            "text": text,
            "news_id": post.pk,
        },
        news_post=post,
    )


def format_press_discord(post):
    details = post.details or {}
    manager = details.get("manager") or ""
    club = details.get("club") or (post.primary_team.name if post.primary_team_id else "")
    question = details.get("question") or ""
    answer = details.get("answer") or post.body or ""
    url = details.get("url") or ""
    lines = [
        "UFL PRESS CONFERENCE",
        "",
        manager,
        club,
        "",
        f"Q — {question}".strip(),
        "",
        f"A — {answer}".strip(),
        "",
        "VIEW ON UFL WEBSITE",
    ]
    if url:
        lines.append(url)
    return "\n".join(line for line in lines if line is not None)


def pending_discord_events(limit=10):
    return list(
        DiscordEvent.objects.filter(status=DiscordEvent.PENDING).order_by("created_at", "id")[:limit]
    )


def mark_discord_sent(event):
    now = timezone.now()
    event.status = DiscordEvent.SENT
    event.sent_at = now
    event.last_attempt_at = now
    event.error = ""
    event.attempt_count = (event.attempt_count or 0) + 1
    event.save(
        update_fields=["status", "sent_at", "last_attempt_at", "error", "attempt_count"]
    )
    if event.news_post_id:
        NewsPost.objects.filter(pk=event.news_post_id, discord_sent=False).update(
            discord_sent=True
        )


def mark_discord_failed(event, error):
    now = timezone.now()
    event.status = DiscordEvent.PENDING
    event.last_attempt_at = now
    event.error = str(error or "")[:2000]
    event.attempt_count = (event.attempt_count or 0) + 1
    if event.attempt_count >= 20:
        event.status = DiscordEvent.FAILED
    event.save(update_fields=["status", "last_attempt_at", "error", "attempt_count"])
