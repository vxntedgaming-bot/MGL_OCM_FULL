"""Live Activity helpers on top of the existing NewsPost model."""

from datetime import timedelta

from mgl.models import ApprovalStatus, MatchSubmission, NewsPost, PressConference
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
        .select_related("primary_team", "secondary_team")
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


def _unique_teams(*teams):
    seen = set()
    ordered = []
    for team in teams:
        if team is None:
            continue
        pk = getattr(team, "pk", None)
        if not pk or pk in seen:
            continue
        seen.add(pk)
        ordered.append(team)
        if len(ordered) >= 2:
            break
    return ordered


def linked_teams(post):
    """Badges from stored Team FKs on the NewsPost."""
    return _unique_teams(
        getattr(post, "primary_team", None),
        getattr(post, "secondary_team", None),
    )


def _press_conference_teams(post):
    if post.category != NewsPost.PRESS:
        return []
    body = post.body or ""
    if "Q:" not in body:
        return []
    question_block, _, answer_block = body.partition("\n\nA:")
    question = question_block.replace("Q:", "", 1).strip()
    qs = PressConference.objects.filter(
        question=question,
        status=ApprovalStatus.APPROVED,
    ).select_related("team")
    answer = answer_block.strip()
    if answer:
        qs = qs.filter(answer=answer)
    press = qs.first()
    if press is None:
        return []
    return _unique_teams(press.team)


def _approved_fixture_teams(post):
    if post.category != NewsPost.RESULTS or not post.created_at:
        return []
    window = timedelta(minutes=5)
    matches = list(
        MatchSubmission.objects.filter(
            status=ApprovalStatus.APPROVED,
            reviewed_at__gte=post.created_at - window,
            reviewed_at__lte=post.created_at + window,
        ).select_related("fixture__home_team", "fixture__away_team")[:3]
    )
    if len(matches) != 1:
        return []
    fixture = matches[0].fixture
    return _unique_teams(fixture.home_team, fixture.away_team)


def teams_mentioned(text, teams=None):
    """Legacy fallback: match existing Team.name values inside published copy."""
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


def teams_for_post(post, catalog=None):
    """Prefer stored Team FKs, then related event rows, then name fallback."""
    linked = linked_teams(post)
    if linked:
        return linked
    related = _press_conference_teams(post) or _approved_fixture_teams(post)
    if related:
        return related
    return teams_mentioned(f"{post.title}\n{post.body}", catalog)


def activity_payloads(posts):
    teams = list(Team.objects.all())
    items = []
    for post in posts:
        items.append(
            {
                "post": post,
                "emoji": activity_emoji(post),
                "label": activity_label(post),
                "teams": teams_for_post(post, teams),
            }
        )
    return items


def record_activity(category, title, body, publish=True, team=None, secondary_team=None):
    """Create official live activity. Call only after the existing approval/action."""
    return create_news(
        category,
        title,
        body,
        publish=publish,
        team=team,
        secondary_team=secondary_team,
    )


def record_manager_departure(user, team):
    if user is None or team is None:
        return None
    application = manager_for_user(user)
    name = application.display_name if application else user.username
    return create_news(
        NewsPost.MANAGER,
        f"{name} has left {team.name}",
        f"{name} has left {team.name}. The squad, tokens and club history remain intact.",
        team=team,
    )
