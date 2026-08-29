"""Live Activity helpers on top of the existing NewsPost model."""

from mgl.models import NewsPost
from mgl.services import create_news, manager_for_user
from teams.models import Team

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


def teams_mentioned(text, teams=None):
    """Resolve club badges from existing Team names in a published update."""
    blob = text or ""
    if not blob:
        return []
    catalog = list(teams) if teams is not None else list(Team.objects.all())
    found = []
    haystack = blob
    for team in sorted(catalog, key=lambda row: len(row.name or ""), reverse=True):
        name = team.name or ""
        if len(name) < 3:
            continue
        if name in haystack:
            found.append(team)
            haystack = haystack.replace(name, " " * len(name))
        if len(found) >= 2:
            break
    return found


def activity_payloads(posts):
    teams = list(Team.objects.all())
    items = []
    for post in posts:
        items.append(
            {
                "post": post,
                "emoji": activity_emoji(post),
                "label": activity_label(post),
                "teams": teams_mentioned(f"{post.title}\n{post.body}", teams),
            }
        )
    return items


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
