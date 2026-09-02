"""Canonical public page URLs for the website and Discord outbox payloads.

Does not send Discord messages. Does not create records.
"""

from django.urls import reverse

from mgl.club_urls import club_page_url
from mgl.nav import COMPETITIONS, LIVE_COMPETITION_SLUGS


def player_url(player_or_id):
    pk = getattr(player_or_id, "pk", player_or_id)
    if not pk:
        return ""
    return reverse("player_profile", args=[pk])


def club_url(team):
    if team is None:
        return ""
    return club_page_url(team)


def league_url(league=None, slug=""):
    if slug:
        return reverse("competition_page", kwargs={"slug": slug})
    short = (getattr(league, "short_name", "") or "").upper()
    for competition_slug, code in LIVE_COMPETITION_SLUGS.items():
        if code == short:
            return reverse("competition_page", kwargs={"slug": competition_slug})
    return reverse("leagues_all")


def cup_url(slug):
    if slug in COMPETITIONS and slug != "cups":
        return reverse("cups_detail", kwargs={"slug": slug})
    return reverse("cups_hub")


def job_url():
    return reverse("job_centre")


def transfer_url():
    return reverse("public_transfers")


def page_links_for_news(post):
    """Buttons a Discord client can attach without a second database."""
    links = [
        {"label": "VIEW ACTIVITY", "url": reverse("live_activity")},
    ]
    category = (getattr(post, "category", "") or "").upper()
    details = getattr(post, "details", None) or {}
    if getattr(post, "primary_team_id", None):
        links.append({"label": "VIEW CLUB", "url": club_url(post.primary_team)})
        league = getattr(post.primary_team, "league", None)
        if league is not None:
            links.append({"label": "VIEW LEAGUE", "url": league_url(league)})
    player_id = details.get("player_id") or details.get("player")
    if player_id and str(player_id).isdigit():
        links.append({"label": "VIEW PLAYER", "url": player_url(int(player_id))})
    if category in {"TRANSFER", "TRANSFERS", "AUCTION", "AUCTIONS"}:
        links.append({"label": "VIEW TRANSFER", "url": transfer_url()})
    if category in {"RESULTS", "RESULT", "MATCH"}:
        links.append({"label": "VIEW LEAGUE", "url": reverse("leagues_page")})
    if category in {"JOBS", "JOB", "APPOINTMENT"}:
        links.append({"label": "VIEW JOB", "url": job_url()})
    cup_slug = details.get("competition_slug") or details.get("cup_slug")
    if cup_slug:
        links.append({"label": "VIEW COMPETITION", "url": cup_url(cup_slug)})
    seen = set()
    unique = []
    for item in links:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)
    return unique
