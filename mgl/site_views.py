"""Public club, news, live activity and pressroom views. Reuses existing models."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from leagues.services import active_divisions, active_league
from mgl.activity import activity_emoji, activity_label, published_activity
from mgl.models import Fixture, MatchSubmission, NewsPost, PressConference
from mgl.press import publish_press_answer, published_press
from mgl.standings import build_league_table
from teams.models import Team


def _querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _annotate_fixture_scores(fixtures):
    rows = []
    for fixture in fixtures:
        home_goals = None
        away_goals = None
        try:
            stats = {
                row.team_id: row.goals
                for row in fixture.submission.team_stats.all()
            }
            home_goals = stats.get(fixture.home_team_id)
            away_goals = stats.get(fixture.away_team_id)
        except MatchSubmission.DoesNotExist:
            pass
        fixture.home_goals = home_goals
        fixture.away_goals = away_goals
        rows.append(fixture)
    return rows


def clubs_index(request):
    divisions = active_divisions()
    clubs = (
        Team.objects.select_related("league", "manager")
        .order_by("league__name", "name")
    )
    return render(
        request,
        "mgl/clubs.html",
        {
            "clubs": clubs,
            "divisions": divisions,
            "active_league": active_league(),
        },
    )


def club_page(request, short_name):
    team = get_object_or_404(
        Team.objects.select_related("league", "manager"),
        short_name__iexact=short_name,
    )
    players = (
        team.players.select_related("mgl_team")
        .order_by("position", "-overall", "name")
    )
    fixtures = (
        Fixture.objects.filter(Q(home_team=team) | Q(away_team=team), is_released=True)
        .select_related("home_team", "away_team", "league")
        .prefetch_related("submission__team_stats")
        .order_by("-matchweek", "-id")[:16]
    )
    fixtures = _annotate_fixture_scores(fixtures)
    upcoming = [row for row in fixtures if row.status == "SCHEDULED"]
    results = [row for row in fixtures if row.status == "COMPLETED"]
    table = build_league_table(team.league) if team.league_id else []
    position = next(
        (row["position"] for row in table if row["team"].id == team.id),
        None,
    )
    is_own_club = (
        request.user.is_authenticated and team.manager_id == request.user.id
    )
    return render(
        request,
        "mgl/club_page.html",
        {
            "team": team,
            "players": players,
            "upcoming": upcoming,
            "results": results,
            "table": table,
            "league_position": position,
            "is_own_club": is_own_club,
        },
    )


def news_centre(request):
    tab = request.GET.get("tab", "latest")
    if tab not in {"latest", "activity", "pressroom", "official"}:
        tab = "latest"
    latest = published_activity()[:20]
    activity = published_activity()[:20]
    press = published_press()[:12]
    official = published_activity().exclude(category=NewsPost.PRESS)[:20]
    return render(
        request,
        "mgl/news.html",
        {
            "tab": tab,
            "latest": latest,
            "activity": activity,
            "press_articles": press,
            "official": official,
        },
    )


def live_activity(request):
    posts = published_activity()
    paginator = Paginator(posts, 20)
    page = paginator.get_page(request.GET.get("page") or 1)
    items = [
        {
            "post": post,
            "emoji": activity_emoji(post),
            "label": activity_label(post),
        }
        for post in page.object_list
    ]
    return render(
        request,
        "mgl/live_activity.html",
        {
            "page": page,
            "items": items,
            "querystring": _querystring(request),
        },
    )


def pressroom(request):
    articles = published_press()
    paginator = Paginator(articles, 12)
    page = paginator.get_page(request.GET.get("page") or 1)
    pending = []
    if request.user.is_authenticated:
        pending = list(
            PressConference.objects.filter(
                manager=request.user,
                status="PENDING",
            )
            .select_related("team", "fixture")
            .order_by("-created_at")
        )
    return render(
        request,
        "mgl/pressroom.html",
        {
            "page": page,
            "pending": pending,
        },
    )


@login_required
@require_POST
def answer_press(request, press_id):
    press = get_object_or_404(PressConference, pk=press_id, manager=request.user)
    try:
        publish_press_answer(press, request.POST.get("answer", ""))
        messages.success(request, "Your press conference is now in the MGL Pressroom.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("pressroom")
