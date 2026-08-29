"""Live Activity helpers on top of the existing NewsPost model."""

from mgl.models import NewsPost
from mgl.services import create_news

ACTIVITY_EMOJI = {
    NewsPost.RESULTS: "🔥",
    NewsPost.TRANSFER: "🚨",
    NewsPost.AUCTION: "🔨",
    NewsPost.FREE_AGENT: "🟢",
    NewsPost.MANAGER: "👔",
    NewsPost.SIGNING: "✍️",
    NewsPost.PRESS: "🎙️",
    NewsPost.SCOUTING: "🔍",
    NewsPost.REWARD: "⭐",
}

ACTIVITY_HEADLINE = {
    NewsPost.RESULTS: "MATCH RESULT",
    NewsPost.TRANSFER: "TRANSFER CONFIRMED",
    NewsPost.AUCTION: "AUCTION LIVE",
    NewsPost.FREE_AGENT: "FREE AGENT",
    NewsPost.MANAGER: "NEW MANAGER",
    NewsPost.SIGNING: "FREE SIGNING",
    NewsPost.PRESS: "PRESS CONFERENCE",
    NewsPost.SCOUTING: "SCOUTING",
    NewsPost.REWARD: "REWARD",
}


def published_activity():
    return (
        NewsPost.objects.filter(published=True)
        .order_by("-created_at", "-id")
    )


def activity_label(post):
    return ACTIVITY_HEADLINE.get(post.category, post.get_category_display())


def activity_emoji(post):
    return ACTIVITY_EMOJI.get(post.category, "📣")


def record_activity(category, title, body, publish=True):
    """Create official live activity. Call only after the existing approval/action."""
    return create_news(category, title, body, publish=publish)
