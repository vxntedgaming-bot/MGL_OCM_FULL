"""Retryable Discord outbox.

Official DB writes happen first. This module only inserts and updates
DiscordEvent rows (and NewsPost.discord_sent after a successful send).
It must never write players, tokens, clubs, fixtures, jobs, transfers,
or StartingSquadLock.
"""

from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from mgl.discord_channels import CHANNEL_FOR_CATEGORY, channel_key_for_category
from mgl.models import DiscordEvent, NewsPost


MAX_ATTEMPTS = 20
BACKOFF_SECONDS = (10, 30, 60, 120, 300, 600, 900, 1800)

PERSONAL_TYPES = (
    "TRANSFER",
    "AUCTION",
    "PRESS",
    "MATCH",
    "RESULT",
    "ADMIN",
    "SCOUTING",
    "CLUB",
)


def backoff_seconds(attempt_count):
    """Delay after this many failed attempts. Attempt 1 → 10s, then longer."""
    if attempt_count <= 0:
        return BACKOFF_SECONDS[0]
    index = min(attempt_count - 1, len(BACKOFF_SECONDS) - 1)
    return BACKOFF_SECONDS[index]


def normalize_idempotency_key(value):
    key = str(value or "").strip()
    return key[:200] if key else None


def queue_discord_event(
    event_type,
    payload=None,
    *,
    channel_key="",
    news_post=None,
    idempotency_key=None,
):
    payload = payload or {}
    channel = channel_key or channel_key_for_category(event_type)
    key = normalize_idempotency_key(idempotency_key)
    if key:
        existing = DiscordEvent.objects.filter(idempotency_key=key).first()
        if existing:
            return existing
    try:
        return DiscordEvent.objects.create(
            event_type=event_type,
            channel_key=channel,
            payload=payload,
            news_post=news_post,
            status=DiscordEvent.PENDING,
            idempotency_key=key,
        )
    except IntegrityError:
        if key:
            return DiscordEvent.objects.get(idempotency_key=key)
        raise


def queue_personal_discord(
    user,
    notification_type,
    title,
    message,
    url="",
    *,
    idempotency_key=None,
):
    """Queue a personal Discord DM. Website/DB state is already committed."""
    discord_id = getattr(user, "discord_id", None)
    if not user or not discord_id:
        return None
    type_key = (notification_type or "").upper()
    if not any(key in type_key for key in PERSONAL_TYPES):
        return None
    text = "\n".join(
        part
        for part in (
            "UFL NOTIFICATION",
            title or "",
            message or "",
            f"VIEW ON WEBSITE → {url}" if url else "",
        )
        if part
    )
    return queue_discord_event(
        notification_type or "NOTICE",
        {
            "text": text,
            "title": title,
            "body": message,
            "discord_id": str(discord_id),
        },
        channel_key="DM",
        idempotency_key=idempotency_key,
    )


def queue_from_news(post, idempotency_key=None):
    if post is None or not post.published:
        return None
    key = normalize_idempotency_key(idempotency_key) or f"news:{post.pk}"
    existing = DiscordEvent.objects.filter(idempotency_key=key).first()
    if existing:
        return existing
    existing_news = DiscordEvent.objects.filter(news_post=post).first()
    if existing_news:
        return existing_news
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
        idempotency_key=key,
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
    """PENDING rows that are due now. Bot restart re-reads this queryset."""
    now = timezone.now()
    return list(
        DiscordEvent.objects.filter(status=DiscordEvent.PENDING)
        .filter(Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        .order_by("created_at", "id")[:limit]
    )


def mark_discord_sent(event):
    now = timezone.now()
    event.status = DiscordEvent.SENT
    event.sent_at = now
    event.last_attempt_at = now
    event.next_attempt_at = None
    event.error = ""
    event.attempt_count = (event.attempt_count or 0) + 1
    event.save(
        update_fields=[
            "status",
            "sent_at",
            "last_attempt_at",
            "next_attempt_at",
            "error",
            "attempt_count",
        ]
    )
    if event.news_post_id:
        NewsPost.objects.filter(pk=event.news_post_id, discord_sent=False).update(
            discord_sent=True
        )


def mark_discord_failed(event, error):
    now = timezone.now()
    event.last_attempt_at = now
    event.error = str(error or "")[:2000]
    event.attempt_count = (event.attempt_count or 0) + 1
    if event.attempt_count >= MAX_ATTEMPTS:
        event.status = DiscordEvent.FAILED
        event.next_attempt_at = None
    else:
        event.status = DiscordEvent.PENDING
        event.next_attempt_at = now + timedelta(seconds=backoff_seconds(event.attempt_count))
    event.save(
        update_fields=["status", "last_attempt_at", "next_attempt_at", "error", "attempt_count"]
    )


def retry_discord_event(event):
    """Owner/Admin manual retry. Queue only — does not send Discord or change football."""
    if event.status == DiscordEvent.SENT:
        raise ValueError("Sent Discord events cannot be retried.")
    event.status = DiscordEvent.PENDING
    event.next_attempt_at = timezone.now()
    event.save(update_fields=["status", "next_attempt_at"])
    return event


def event_payload_preview(event):
    """Safe fields for Control Centre. Never includes discord_id or credentials."""
    payload = event.payload or {}
    preview = {}
    for key in ("title", "body", "text", "news_id"):
        if key in payload:
            preview[key] = payload[key]
    return preview
