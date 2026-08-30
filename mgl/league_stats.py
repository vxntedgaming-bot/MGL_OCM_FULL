"""League statistics from approved match submissions only."""

from django.db.models import Avg, Count, Q, Sum
from django.http import Http404
from django.shortcuts import render

from leagues.models import League
from leagues.services import ensure_premier_league
from mgl.models import ApprovalStatus, ManagerCareerStat
from mgl.nav import live_competition_choices
from players.models import Player

STATS_SLUGS = {
    "premier-league": ("PL", "Premier League"),
    "championship": ("CH", "Championship"),
    "league-one": ("L1", "League One"),
}


def league_for_stats_slug(slug):
    ensure_premier_league()
    mapping = STATS_SLUGS.get(slug)
    if not mapping:
        raise Http404("Unknown league statistics page.")
    short, name = mapping
    league = League.objects.filter(short_name__iexact=short, is_active=True).first()
    if league is None:
        raise Http404("This division is not active.")
    return league, name, slug


def _event_filter(league, prefix):
    return Q(
        **{
            f"{prefix}__team_stats__submission__status": ApprovalStatus.APPROVED,
            f"{prefix}__team_stats__submission__fixture__league": league,
        }
    )


def build_league_stats(league):
    goal_filter = _event_filter(league, "goal_events")
    assist_filter = _event_filter(league, "assist_events")
    def_filter = _event_filter(league, "defender_ratings")
    gk_filter = _event_filter(league, "gk_saves")
    top_scorers = (
        Player.objects.filter(goal_filter)
        .select_related("mgl_team")
        .annotate(stat_value=Count("goal_events", filter=goal_filter))
        .filter(stat_value__gt=0)
        .order_by("-stat_value", "name")[:20]
    )
    top_assisters = (
        Player.objects.filter(assist_filter)
        .select_related("mgl_team")
        .annotate(stat_value=Count("assist_events", filter=assist_filter))
        .filter(stat_value__gt=0)
        .order_by("-stat_value", "name")[:20]
    )
    top_defenders = (
        Player.objects.filter(def_filter)
        .select_related("mgl_team")
        .annotate(
            avg_def=Avg("defender_ratings__rating", filter=def_filter),
            def_apps=Count("defender_ratings", filter=def_filter),
        )
        .order_by("-avg_def", "-def_apps", "name")[:20]
    )
    top_keepers = (
        Player.objects.filter(gk_filter)
        .select_related("mgl_team")
        .annotate(total_saves=Sum("gk_saves__saves", filter=gk_filter))
        .order_by("-total_saves", "name")[:20]
    )
    top_managers = (
        ManagerCareerStat.objects.select_related("manager", "manager__user")
        .filter(Q(wins__gt=0) | Q(draws__gt=0) | Q(losses__gt=0) | Q(trophies__gt=0))
        .order_by("-wins", "-trophies", "manager__display_name")[:20]
    )
    return {
        "league": league,
        "top_scorers": top_scorers,
        "top_assisters": top_assisters,
        "top_defenders": top_defenders,
        "top_keepers": top_keepers,
        "top_managers": top_managers,
        "stats_slugs": STATS_SLUGS,
    }


def render_league_stats(request, slug="premier-league"):
    league, name, slug = league_for_stats_slug(slug)
    context = build_league_stats(league)
    context.update(
        {
            "competition_name": name,
            "competition_slug": slug,
            "competition_choices": live_competition_choices(),
            "selector_kind": "stats",
            "selector_label": "League statistics",
        }
    )
    return render(request, "mgl/stats.html", context)
