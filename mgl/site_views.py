"""Public club, news, live activity and pressroom views. Reuses existing models."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from leagues.services import active_divisions, active_league
from mgl.activity import activity_payloads, published_football_activity
from mgl.club_urls import resolve_club
from mgl.models import ApprovalStatus, Fixture, MatchSubmission, PressConference
from mgl.press import publish_press_answer, published_press
from mgl.standings import build_live_league_table
from mgl.services import manager_for_user
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


def club_page(request, slug):
    team = resolve_club(slug)
    players = list(
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
    table = build_live_league_table(team.league) if team.league_id else []
    position = next(
        (row["position"] for row in table if row["team"].id == team.id),
        None,
    )
    is_own_club = (
        request.user.is_authenticated and team.manager_id == request.user.id
    )
    from mgl.market import club_for_user
    from mgl.models import MarketTransaction
    from mgl.permissions import approved_manager

    viewer_manager = approved_manager(request.user) if request.user.is_authenticated else None
    viewer_club = club_for_user(request.user) if viewer_manager else None
    can_buy_from_club = bool(
        viewer_manager
        and viewer_club
        and not is_own_club
        and team.manager_id
    )
    overalls = [player.overall or 0 for player in players]
    avg_overall = round(sum(overalls) / len(overalls)) if overalls else None
    top_players = sorted(players, key=lambda row: (-(row.overall or 0), row.name))[:6]
    club_transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .filter(Q(from_team=team) | Q(to_team=team))
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")[:12]
    )
    club_tab = (request.GET.get("tab") or "overview").strip().lower()
    if club_tab not in {"overview", "squad", "fixtures", "transfers", "stats", "history"}:
        club_tab = "overview"
    from mgl.page_links import league_url

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
            "can_buy_from_club": can_buy_from_club,
            "viewer_manager": viewer_manager,
            "avg_overall": avg_overall,
            "top_players": top_players,
            "club_transfers": club_transfers,
            "club_tab": club_tab,
            "club_manager": manager_for_user(team.manager) if team.manager_id else None,
            "league_href": league_url(team.league) if team.league_id else reverse("leagues_page"),
        },
    )


def news_centre(request):
    tab = (request.GET.get("tab") or "").strip().lower()
    if tab == "pressroom":
        return redirect("pressroom")
    return redirect("live_activity")


def live_activity(request):
    posts = published_football_activity()
    paginator = Paginator(posts, 20)
    page = paginator.get_page(request.GET.get("page") or 1)
    items = activity_payloads(page.object_list)
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
    for press in page.object_list:
        application = manager_for_user(press.manager)
        press.manager_name = application.display_name if application else press.manager.username
    return render(
        request,
        "mgl/pressroom.html",
        {
            "page": page,
        },
    )


@login_required
def answer_press(request, press_id):
    press = get_object_or_404(PressConference, pk=press_id, manager=request.user)
    application = manager_for_user(request.user)
    press.manager_name = application.display_name if application else request.user.username
    if press.status == ApprovalStatus.APPROVED:
        messages.info(request, "This press conference has already been published.")
        return redirect("pressroom")
    if press.status == ApprovalStatus.REJECTED:
        messages.info(request, "This press conference was rejected.")
        return redirect("pressroom")
    awaiting_approval = bool(press.answer)
    form_answer = request.POST.get("answer", "") if request.method == "POST" else ""
    if request.method == "POST":
        if awaiting_approval:
            messages.info(request, "Your answer is already awaiting Admin approval.")
            return redirect("pressroom")
        try:
            publish_press_answer(press, request.POST.get("answer", ""))
            messages.success(
                request,
                "Your answer has been submitted and is awaiting Admin approval.",
            )
            return redirect("pressroom")
        except ValueError as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "mgl/press_answer.html",
        {
            "press": press,
            "form_answer": form_answer,
            "awaiting_approval": awaiting_approval,
        },
    )


def ufl_rules(request):
    return render(request, "mgl/rules.html")
