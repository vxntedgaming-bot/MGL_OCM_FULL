"""Live Activity helpers on top of the existing NewsPost model."""

import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Q

from mgl.models import ApprovalStatus, MatchSubmission, NewsPost, PressConference
from mgl.services import create_news, manager_for_user
from teams.models import Team

FOOTBALL_CATEGORIES = (NewsPost.RESULTS, NewsPost.TRANSFER)
KIND_RESULT = "result"
KIND_TRANSFER = "transfer"
KIND_SIGNING = "signing"

_RESULT_TITLE_RE = re.compile(
    r"^(?P<home>.+?)\s+(?P<hs>\d+)\s*[-–]\s*(?P<as>\d+)\s+(?P<away>.+)$"
)

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
        .select_related(
            "primary_team",
            "secondary_team",
            "primary_team__league",
            "secondary_team__league",
            "primary_team__manager",
            "secondary_team__manager",
        )
        .order_by("-created_at", "-id")
    )


TICKER_CATEGORIES = (
    NewsPost.RESULTS,
    NewsPost.TRANSFER,
    NewsPost.AUCTION,
    NewsPost.MANAGER,
    NewsPost.SIGNING,
    NewsPost.PRESS,
    NewsPost.FREE_AGENT,
    NewsPost.SCOUTING,
    NewsPost.REWARD,
)
NEWSROOM_FEED_ATTR = "data-newsroom-feed"


def published_ticker_activity():
    """Genuine published events for the global LIVE ACTIVITY bar."""
    return published_activity().filter(category__in=TICKER_CATEGORIES)


def extract_newsroom_feed(html):
    """Newsroom page HTML after the feed marker, excluding the global ticker."""
    start = html.find(NEWSROOM_FEED_ATTR)
    if start < 0:
        return ""
    return html[start:]


def extract_page_main(html):
    """Page body inside <main>, excluding the global header ticker."""
    start = html.find("<main")
    end = html.find("</main>")
    if start < 0:
        return html
    if end < 0:
        return html[start:]
    return html[start:end]


def _non_m2m_transfer_noise():
    """Hide listings, auctions, releases and free-agent copy from the feed.

    Those systems keep working on their own pages. Live Activity only
    shows completed manager-to-manager transfers and official results.
    """
    return (
        Q(title__icontains="listed for sale")
        | Q(body__icontains="listed for sale")
        | Q(title__icontains="auction")
        | Q(body__icontains="auction")
        | Q(title__icontains="free agent")
        | Q(body__icontains="free agent")
        | Q(title__icontains="released")
        | Q(body__icontains="released")
    )


def published_football_activity():
    """Official completed matches and manager-to-manager transfers only.

    Pending, rejected, unpublished, signing, auction, scouting and
    admin records are excluded here. Those systems are unchanged.
    """
    return (
        published_activity()
        .filter(category__in=FOOTBALL_CATEGORIES)
        .exclude(_non_m2m_transfer_noise())
    )


def activity_label(post):
    title = (post.title or "").lower()
    body = (post.body or "").lower()
    blob = f"{title} {body}"
    category = post.category
    if category == NewsPost.RESULTS:
        return "MATCH RESULT"
    if category == NewsPost.TRANSFER:
        if "released" in blob or "free agent" in blob:
            return "PLAYER RELEASED"
        if "listed" in blob:
            return "TRANSFER LISTED"
        return "TRANSFER"
    if category == NewsPost.AUCTION:
        if "sold" in blob or "winning" in blob or "joined" in blob:
            return "AUCTION WON"
        return "AUCTION STARTED"
    if category == NewsPost.FREE_AGENT:
        if "released" in blob:
            return "PLAYER RELEASED"
        return "FREE AGENT"
    if category == NewsPost.SIGNING:
        return "SIGNING"
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


def _display_name(user):
    if user is None:
        return ""
    application = manager_for_user(user)
    if application and application.display_name:
        return application.display_name
    return user.username


def _season_label(league):
    if league is None:
        return ""
    name = getattr(league, "public_name", None) or league.name
    season = (getattr(league, "season", None) or "").strip()
    if not season:
        return name
    if season.lower().startswith("season"):
        return f"{name} · {season}"
    return f"{name} · Season {season}"


def _match_for_result(post):
    if post.category != NewsPost.RESULTS or not post.created_at:
        return None
    window = timedelta(minutes=5)
    matches = list(
        MatchSubmission.objects.filter(
            status=ApprovalStatus.APPROVED,
            reviewed_at__gte=post.created_at - window,
            reviewed_at__lte=post.created_at + window,
        ).select_related(
            "fixture__home_team__manager",
            "fixture__away_team__manager",
            "fixture__home_team__league",
            "fixture__away_team__league",
            "fixture__league",
        )[:3]
    )
    if len(matches) != 1:
        return None
    return matches[0]


def _parse_result_title(post):
    match = _RESULT_TITLE_RE.match((post.title or "").strip())
    if not match:
        return None
    return {
        "home_name": match.group("home").strip(),
        "away_name": match.group("away").strip(),
        "home_score": match.group("hs"),
        "away_score": match.group("as"),
    }


def _football_kind(post):
    if post.category == NewsPost.RESULTS:
        return KIND_RESULT
    if post.category == NewsPost.SIGNING:
        return KIND_SIGNING
    if post.category == NewsPost.TRANSFER:
        blob = f"{post.title or ''} {post.body or ''}".lower()
        if "listed for sale" in blob or "auction" in blob:
            return None
        if "free agent" in blob or "released" in blob:
            return None
        return KIND_TRANSFER
    return None


def _team_named(teams, name):
    needle = (name or "").strip().lower()
    if not needle:
        return None
    for team in teams or []:
        if (getattr(team, "name", "") or "").strip().lower() == needle:
            return team
    return None


def completed_deal_payload(post, teams=None):
    """Build a completed-deal card from the snapshot stored at approval.

    Returns None for older transfer posts that have no deal snapshot so
    those cards keep the original simple layout.
    """
    details = getattr(post, "details", None) or {}
    if not isinstance(details, dict) or not details.get("deal"):
        return None
    try:
        amount = Decimal(str(details.get("amount") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        amount = Decimal("0")
    swaps = details.get("swaps") or []
    if not isinstance(swaps, list):
        swaps = []
    target = details.get("target") or {}
    if not isinstance(target, dict):
        target = {}
    selling_club = details.get("selling_club") or ""
    buying_club = details.get("buying_club") or ""
    target_list = [target] if target.get("name") else []
    swap_list = [row for row in swaps if isinstance(row, dict) and row.get("name")]
    selling_team = _team_named(teams, selling_club) or getattr(post, "secondary_team", None)
    buying_team = _team_named(teams, buying_club) or getattr(post, "primary_team", None)
    return {
        "selling_club": selling_club,
        "buying_club": buying_club,
        "selling_team": selling_team,
        "buying_team": buying_team,
        "target": target,
        "swaps": swap_list,
        "is_swap": bool(swap_list),
        "amount": amount,
        "amount_display": f"{amount:.2f}",
        "has_fee": amount > 0,
        "payer": buying_club,
        "seller_in": swap_list,
        "seller_out": target_list,
        "buyer_in": target_list,
        "buyer_out": swap_list,
    }


def _player_name(post):
    title = (post.title or "").strip()
    for suffix in (" transferred", " signed", " listed for sale"):
        if title.lower().endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def activity_payloads(posts):
    teams = list(Team.objects.select_related("league", "manager"))
    items = []
    for post in posts:
        kind = _football_kind(post)
        related = teams_for_post(post, teams)
        home = post.primary_team
        away = post.secondary_team
        if kind == KIND_RESULT and len(related) >= 2:
            home, away = related[0], related[1]
        parsed = _parse_result_title(post) if kind == KIND_RESULT else None
        submission = _match_for_result(post) if kind == KIND_RESULT else None
        fixture = getattr(submission, "fixture", None) if submission else None
        league = None
        if fixture is not None:
            league = fixture.league
            home = fixture.home_team
            away = fixture.away_team
        elif home is not None:
            league = getattr(home, "league", None)
        elif away is not None:
            league = getattr(away, "league", None)
        home_manager = _display_name(getattr(home, "manager", None)) if home else ""
        away_manager = _display_name(getattr(away, "manager", None)) if away else ""
        if fixture is not None:
            home_manager = _display_name(fixture.home_team.manager)
            away_manager = _display_name(fixture.away_team.manager)
        headline = post.title
        home_name = getattr(home, "name", "") if home else ""
        away_name = getattr(away, "name", "") if away else ""
        home_score = ""
        away_score = ""
        if parsed:
            home_name = parsed["home_name"]
            away_name = parsed["away_name"]
            home_score = parsed["home_score"]
            away_score = parsed["away_score"]
            headline = f"{home_name} {home_score} - {away_score} {away_name}"
        player_name = _player_name(post) if kind in (KIND_TRANSFER, KIND_SIGNING) else ""
        from_club = getattr(away, "name", "") if kind == KIND_TRANSFER and away else ""
        to_club = getattr(home, "name", "") if kind in (KIND_TRANSFER, KIND_SIGNING) and home else ""
        if kind == KIND_TRANSFER and not from_club and post.body:
            joined = re.search(
                r"joined (?P<to>.+?) from (?P<fr>.+?)\.",
                post.body,
                re.IGNORECASE,
            )
            if joined:
                to_club = to_club or joined.group("to").strip()
                from_club = joined.group("fr").strip()
        if kind == KIND_SIGNING and not to_club and post.body:
            signed = re.search(
                r"(?:joined|signed for) (?P<club>.+?)(?: on a free signing)?\.",
                post.body,
                re.IGNORECASE,
            )
            if signed:
                to_club = signed.group("club").strip()
        meta_line = _season_label(league)
        matchweek = getattr(fixture, "matchweek", None) if fixture is not None else None
        if kind == KIND_RESULT and matchweek:
            gw = f"Gameweek {matchweek}"
            meta_line = f"{meta_line} · {gw}" if meta_line else gw
        deal = completed_deal_payload(post, teams) if kind == KIND_TRANSFER else None
        if deal:
            from_club = deal["selling_club"] or from_club
            to_club = deal["buying_club"] or to_club
            player_name = deal.get("target", {}).get("name") or player_name
        items.append(
            {
                "post": post,
                "emoji": activity_emoji(post),
                "label": activity_label(post),
                "teams": related,
                "kind": kind or "other",
                "headline": headline,
                "home_name": home_name,
                "away_name": away_name,
                "home_score": home_score,
                "away_score": away_score,
                "home_manager": home_manager,
                "away_manager": away_manager,
                "player_name": player_name,
                "from_club": from_club,
                "to_club": to_club,
                "meta_line": meta_line,
                "occurred_at": post.created_at,
                "deal": deal,
                "subtitle": (
                    "MATCH COMPLETED"
                    if kind == KIND_RESULT
                    else "TRANSFER COMPLETED"
                    if kind == KIND_TRANSFER and deal
                    else "Transfer completed"
                    if kind == KIND_TRANSFER
                    else ""
                ),
            }
        )
    return items


def record_activity(
    category,
    title,
    body,
    publish=True,
    team=None,
    secondary_team=None,
    details=None,
    discord_idempotency_key=None,
):
    """Create official live activity. Call only after the existing approval/action."""
    return create_news(
        category,
        title,
        body,
        publish=publish,
        team=team,
        secondary_team=secondary_team,
        details=details,
        discord_idempotency_key=discord_idempotency_key,
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
        discord_idempotency_key=f"manager.depart:{team.pk}:{getattr(user, 'pk', 'user')}",
    )
