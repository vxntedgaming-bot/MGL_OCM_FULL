"""Live Activity helpers on top of the existing NewsPost model."""

from mgl.models import NewsPost
from mgl.services import create_news, manager_for_user

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


def published_activity():
    return (
        NewsPost.objects.filter(published=True)
        .order_by("-created_at", "-id")
    )


def activity_label(post):
    title = (post.title or "").lower()
    body = (post.body or "").lower()
    blob = f"{title} {body}"
    category = post.category
    if category == NewsPost.RESULTS:
        return "RESULT APPROVED"
    if category == NewsPost.TRANSFER:
        if "released" in blob or "free agent" in blob:
            return "PLAYER RELEASED"
        if "listed" in blob:
            return "TRANSFER LISTED"
        return "TRANSFER APPROVED"
    if category == NewsPost.AUCTION:
        if "sold" in blob or "winning" in blob or "joined" in blob:
            return "AUCTION WON"
        return "AUCTION STARTED"
    if category == NewsPost.FREE_AGENT:
        if "released" in blob:
            return "PLAYER RELEASED"
        return "FREE AGENT"
    if category == NewsPost.SIGNING:
        return "FREE AGENT SIGNING"
    if category == NewsPost.MANAGER:
        if any(word in blob for word in ("left", "resign", "depart")):
            return "MANAGER DEPARTURE"
        return "MANAGER APPOINTED"
    if category == NewsPost.PRESS:
        return "PRESS CONFERENCE"
    if category == NewsPost.SCOUTING:
        return "SCOUTING"
    if category == NewsPost.REWARD:
        return "REWARD"
    return post.get_category_display()


def activity_emoji(post):
    label = activity_label(post)
    if label == "AUCTION WON":
        return "✅"
    if label == "MANAGER DEPARTURE":
        return "👋"
    if label == "PLAYER RELEASED":
        return "🟢"
    return ACTIVITY_EMOJI.get(post.category, "📣")


def record_activity(category, title, body, publish=True):
    """Create official live activity. Call only after the existing approval/action."""
    return create_news(category, title, body, publish=publish)


def record_manager_departure(user, team):
    if user is None or team is None:
        return None
    application = manager_for_user(user)
    name = application.display_name if application else user.username
    return create_news(
        NewsPost.MANAGER,
        f"{name} has left {team.name}",
        f"{name} has left {team.name}. The squad, tokens and club history remain intact.",
    )
