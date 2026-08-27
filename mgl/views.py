from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from players.models import Player
from teams.models import Team

from .models import (
    Fixture,
    MatchSubmission,
    TeamMatchStats,
    GoalEvent,
    AssistEvent,
    DefenderRating,
    GKSave,
    PressConference,
    NewsPost,
    RewardTransaction,
)
from .services import manager_for_user


def _post_int(post, key, default=0):
    try:
        return int(post.get(key, default))
    except (TypeError, ValueError):
        return default


def mgl_index(request):
    """
    /mgl/ is the manager area entry point, not a second homepage.
    """
    if request.user.is_authenticated:
        return redirect("manager_hub")
    return redirect("home")


def home(request):
    upcoming = (
        Fixture.objects
        .filter(
            is_released=True,
            status="SCHEDULED",
        )
        .select_related(
            "home_team",
            "away_team",
            "league",
        )[:5]
    )

    news = (
        NewsPost.objects
        .filter(published=True)
        .order_by("-created_at")[:6]
    )

    recent_results = []
    completed = (
        Fixture.objects
        .filter(
            is_released=True,
            status="COMPLETED",
        )
        .select_related(
            "home_team",
            "away_team",
        )
        .prefetch_related(
            "submission__team_stats",
        )
        .order_by("-id")[:5]
    )

    for fixture in completed:
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
        recent_results.append(fixture)

    top_scorers = (
        Player.objects
        .filter(goals__gt=0)
        .select_related("mgl_team")
        .order_by("-goals", "name")[:5]
    )

    return render(
        request,
        "core/home.html",
        {
            "upcoming": upcoming,
            "news": news,
            "recent_results": recent_results,
            "top_scorers": top_scorers,
            "league_count": League.objects.filter(is_active=True).count(),
            "club_count": Team.objects.count(),
            "player_count": Player.objects.count(),
        },
    )


@login_required
def player_profile(request, player_id):
    player = get_object_or_404(
        Player.objects.select_related("mgl_team"),
        pk=player_id,
    )

    ownership_history = (
        player.ownership_history
        .select_related("team", "manager")
        .order_by("-created_at")
    )

    totw_selections = (
        player.totw_selections
        .select_related("totw")
        .order_by("-totw__week_start")
    )

    auction_requests = (
        player.auction_requests
        .select_related("manager")
        .order_by("-submitted_at")
    )

    return render(
        request,
        "mgl/player_profile.html",
        {
            "player": player,
            "ownership_history": ownership_history,
            "totw_selections": totw_selections,
            "auction_requests": auction_requests,
        },
    )


@login_required
def manager_hub(request):
    manager = manager_for_user(request.user)

    if not manager:
        messages.error(
            request,
            "You do not have a manager account.",
        )
        return redirect("manager_login")

    team = getattr(request.user, "managed_team", None)
    recent = []

    if team:
        recent = (
            Fixture.objects
            .filter(Q(home_team=team) | Q(away_team=team))
            .order_by("-id")[:10]
        )

    rewards = (
        RewardTransaction.objects
        .filter(manager=manager)
        .order_by("-created_at")[:10]
    )

    roster_count = team.players.count() if team else 0

    return render(
        request,
        "mgl/manager_hub.html",
        {
            "manager": manager,
            "team": team,
            "recent": recent,
            "rewards": rewards,
            "roster_count": roster_count,
        },
    )


@login_required
def fixture_list(request):
    fixtures = (
        Fixture.objects
        .filter(is_released=True)
        .select_related(
            "home_team",
            "away_team",
            "league",
        )
    )

    return render(
        request,
        "mgl/fixtures.html",
        {
            "fixtures": fixtures,
        },
    )


@login_required
@transaction.atomic
def submit_match(request, fixture_id):
    fixture = get_object_or_404(
        Fixture.objects.select_related(
            "home_team",
            "away_team",
        ),
        pk=fixture_id,
        is_released=True,
    )

    manager = manager_for_user(request.user)

    if not manager:
        messages.error(
            request,
            "You must have a manager account.",
        )
        return redirect("fixture_list")

    allowed_managers = [
        fixture.home_team.manager_id,
        fixture.away_team.manager_id,
    ]

    if request.user.id not in allowed_managers:
        messages.error(
            request,
            "Only the two managers in this fixture can submit the match.",
        )
        return redirect("fixture_list")

    if MatchSubmission.objects.filter(fixture=fixture).exists():
        messages.error(
            request,
            "This match has already been submitted.",
        )
        return redirect("fixture_list")

    if request.method == "POST":
        sub = MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=request.user,
        )

        for team in [fixture.home_team, fixture.away_team]:
            prefix = "home_" if team == fixture.home_team else "away_"

            ts = TeamMatchStats.objects.create(
                submission=sub,
                team=team,
                goals=_post_int(request.POST, prefix + "goals", 0),
                shots=_post_int(request.POST, prefix + "shots", 0),
                possession=_post_int(request.POST, prefix + "possession", 50),
            )

            for pid in request.POST.getlist(prefix + "goal_players"):
                player = get_object_or_404(
                    Player,
                    pk=pid,
                    mgl_team=team,
                )
                GoalEvent.objects.create(
                    team_stats=ts,
                    player=player,
                )

            for pid in request.POST.getlist(prefix + "assist_players"):
                player = get_object_or_404(
                    Player,
                    pk=pid,
                    mgl_team=team,
                )
                AssistEvent.objects.create(
                    team_stats=ts,
                    player=player,
                )

            defenders = Player.objects.filter(
                mgl_team=team,
                position__in=["CB", "LB", "RB", "LWB", "RWB"],
            )

            for player in defenders:
                value = request.POST.get(f"{prefix}def_{player.id}")
                if value not in (None, ""):
                    DefenderRating.objects.create(
                        team_stats=ts,
                        player=player,
                        rating=value,
                    )

            keepers = Player.objects.filter(
                mgl_team=team,
                position="GK",
            )

            for player in keepers:
                value = request.POST.get(f"{prefix}save_{player.id}")
                if value not in (None, ""):
                    GKSave.objects.create(
                        team_stats=ts,
                        player=player,
                        saves=value,
                    )

        messages.success(
            request,
            "Match submitted to Admin for approval.",
        )
        return redirect("fixture_list")

    teams = []
    for team in [fixture.home_team, fixture.away_team]:
        players = list(
            Player.objects
            .filter(mgl_team=team)
            .order_by("position", "-overall", "name")
        )
        teams.append((team, players))

    return render(
        request,
        "mgl/submit_match.html",
        {
            "fixture": fixture,
            "teams": teams,
        },
    )


@login_required
@require_POST
def press_conference(request, fixture_id):
    fixture = get_object_or_404(Fixture, pk=fixture_id)
    manager = manager_for_user(request.user)

    if not manager:
        return redirect("fixture_list")

    if request.user.id not in [
        fixture.home_team.manager_id,
        fixture.away_team.manager_id,
    ]:
        return redirect("fixture_list")

    answer = request.POST.get("answer", "").strip()
    question = request.POST.get("question", "").strip()

    if not answer:
        messages.error(request, "Please answer the question.")
        return redirect("fixture_list")

    PressConference.objects.update_or_create(
        fixture=fixture,
        manager=request.user,
        defaults={
            "question": question,
            "answer": answer,
            "status": "PENDING",
        },
    )

    messages.success(
        request,
        "Press conference submitted for Admin approval.",
    )
    return redirect("fixture_list")


@login_required
@require_POST
def release_my_player(request, player_id):
    from .services import release_player

    team = getattr(request.user, "managed_team", None)

    if not team:
        messages.error(request, "You do not manage a club.")
        return redirect("manager_hub")

    player = get_object_or_404(
        Player,
        pk=player_id,
        mgl_team=team,
    )

    release_player(
        player,
        team,
        source="MANAGER_RELEASE",
    )

    messages.success(
        request,
        f"{player.name} released to Free Agents.",
    )
    return redirect("team_management")


@login_required
def free_agents(request):
    players = (
        Player.objects
        .filter(
            is_free_agent=True,
            mgl_team__isnull=True,
        )
        .order_by("-overall", "name")
    )

    return render(
        request,
        "mgl/free_agents.html",
        {
            "players": players,
        },
    )


@login_required
def manager_profile(request):
    manager = manager_for_user(request.user)

    if not manager:
        return redirect("manager_login")

    career = getattr(manager, "career", None)
    trophies = manager.trophies.all() if manager else []
    rewards = (
        RewardTransaction.objects
        .filter(manager=manager)
        .order_by("-created_at")[:20]
    )

    return render(
        request,
        "mgl/profile.html",
        {
            "manager": manager,
            "career": career,
            "trophies": trophies,
            "rewards": rewards,
        },
    )


@login_required
def player_database(request):
    tier = request.GET.get("tier", "").upper()
    search = request.GET.get("search", "").strip()

    players = Player.objects.all()

    if tier == "GOLD":
        players = players.filter(overall__gte=75)
    elif tier == "SILVER":
        players = players.filter(overall__gte=65, overall__lte=74)
    elif tier == "BRONZE":
        players = players.filter(overall__gte=63, overall__lte=64)

    if search:
        players = players.filter(
            Q(name__icontains=search) |
            Q(fc27_club__icontains=search) |
            Q(position__icontains=search)
        )

    players = players.order_by("-overall", "name")

    return render(
        request,
        "mgl/player_database.html",
        {
            "players": players,
            "selected_tier": tier,
            "search": search,
        },
    )


@login_required
def rewards(request):
    manager = manager_for_user(request.user)

    if not manager:
        return redirect("manager_login")

    rewards = (
        RewardTransaction.objects
        .filter(manager=manager)
        .select_related("fixture")
        .order_by("-created_at")
    )

    return render(
        request,
        "mgl/rewards.html",
        {
            "manager": manager,
            "rewards": rewards,
        },
    )


@login_required
def team_management(request):
    team = getattr(request.user, "managed_team", None)

    if not team:
        return render(
            request,
            "mgl/team_management.html",
            {
                "team": None,
                "players": [],
                "total_ovr": 0,
                "available_spaces": 0,
            },
        )

    players = list(
        team.players.all().order_by(
            "position",
            "-overall",
            "name",
        )
    )

    total_ovr = sum(player.overall for player in players)
    available_spaces = max(0, team.roster_limit - len(players))

    return render(
        request,
        "mgl/team_management.html",
        {
            "team": team,
            "players": players,
            "total_ovr": total_ovr,
            "available_spaces": available_spaces,
        },
    )


def owner_admin_required(view_func):
    """
    Only MGL OWNER or ADMIN users can access club administration.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.user.role not in [User.OWNER, User.ADMIN]:
            messages.error(
                request,
                "You do not have permission to access Club Management.",
            )
            return redirect("manager_hub")
        return view_func(request, *args, **kwargs)

    return login_required(wrapper)


@owner_admin_required
def club_management_admin(request):
    teams = (
        Team.objects
        .select_related("league", "manager")
        .prefetch_related("players")
        .order_by("name")
    )

    return render(
        request,
        "mgl/admin_club_management.html",
        {
            "teams": teams,
        },
    )


@owner_admin_required
def edit_club_admin(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related("league"),
        pk=team_id,
    )

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        short_name = request.POST.get("short_name", "").strip()

        if not name:
            messages.error(request, "Club name cannot be empty.")
            return redirect("edit_club_admin", team_id=team.id)

        if not short_name:
            messages.error(request, "Short name cannot be empty.")
            return redirect("edit_club_admin", team_id=team.id)

        team.name = name
        team.short_name = short_name

        if request.FILES.get("logo"):
            team.logo = request.FILES["logo"]

        team.save()

        messages.success(
            request,
            f"{team.name} has been updated successfully.",
        )
        return redirect("club_management_admin")

    return render(
        request,
        "mgl/edit_club_admin.html",
        {
            "team": team,
        },
    )


@owner_admin_required
@require_POST
@transaction.atomic
def remove_club_manager(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related("manager"),
        pk=team_id,
    )

    old_manager = team.manager

    if not old_manager:
        messages.warning(
            request,
            f"{team.name} already has no manager.",
        )
        return redirect("club_management_admin")

    team.manager = None
    team.save(update_fields=["manager"])

    messages.success(
        request,
        f"{old_manager.username} has left {team.name}. "
        f"The club remains intact and is now available.",
    )
    return redirect("club_management_admin")


@owner_admin_required
def change_club_manager(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related("manager"),
        pk=team_id,
    )

    approved_applications = (
        ManagerApplication.objects
        .filter(status=ManagerApplication.APPROVED)
        .select_related("user")
        .order_by("display_name")
    )

    available_managers = []

    for application in approved_applications:
        user = application.user
        if hasattr(user, "managed_team"):
            current_team = user.managed_team
            if current_team and current_team.id != team.id:
                continue
        available_managers.append(application)

    if request.method == "POST":
        application_id = request.POST.get("manager_application")
        application = get_object_or_404(
            ManagerApplication.objects.select_related("user"),
            pk=application_id,
            status=ManagerApplication.APPROVED,
        )
        new_manager = application.user

        if hasattr(new_manager, "managed_team"):
            existing_team = new_manager.managed_team
            if existing_team and existing_team.id != team.id:
                messages.error(
                    request,
                    f"{new_manager.username} is already managing "
                    f"{existing_team.name}.",
                )
                return redirect("change_club_manager", team_id=team.id)

        old_manager = team.manager
        team.manager = new_manager
        team.save(update_fields=["manager"])

        if old_manager:
            messages.success(
                request,
                f"{team.name} is now managed by {new_manager.username}. "
                f"The previous manager has been removed.",
            )
        else:
            messages.success(
                request,
                f"{new_manager.username} has been appointed manager "
                f"of {team.name}.",
            )

        return redirect("club_management_admin")

    return render(
        request,
        "mgl/change_club_manager.html",
        {
            "team": team,
            "available_managers": available_managers,
        },
    )


@owner_admin_required
def club_squad_admin(request, team_id):
    team = get_object_or_404(
        Team.objects.select_related("manager", "league"),
        pk=team_id,
    )

    players = list(
        team.players
        .all()
        .order_by("position", "-overall", "name")
    )

    return render(
        request,
        "mgl/admin_club_squad.html",
        {
            "team": team,
            "players": players,
            "available_spaces": max(0, team.roster_limit - len(players)),
        },
    )
