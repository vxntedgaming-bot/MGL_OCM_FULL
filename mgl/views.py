from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from leagues.models import League
from leagues.services import active_league, ensure_premier_league
from managers.models import ManagerApplication
from mgl.standings import build_league_table
from players.models import Player
from players.search import apply_player_search
from players.fc26_attributes import attribute_groups_for_player
from teams.models import Team

from .models import (
    ApprovalStatus,
    ClubApplication,
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
    MarketTransaction,
    PlayerListing,
    ScoutAssignment,
)
from .market import (
    AUCTION_DURATION_CHOICES,
    close_expired_auctions,
    club_for_user,
    create_free_agent_auction,
    create_manager_auction,
    token_balance_for_user,
)
from .nav import COMPETITIONS, LIVE_COMPETITION_SLUGS
from .permissions import approved_manager, owner_admin_required
from .services import manager_for_user
from .tenure import close_club_spell_for_user, open_club_spell


def _post_int(post, key, default=0):
    try:
        return int(post.get(key, default))
    except (TypeError, ValueError):
        return default


def _querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _feature_page(request, title, kicker, body):
    return render(
        request,
        "mgl/feature_unavailable.html",
        {
            "title": title,
            "kicker": kicker,
            "body": body,
        },
    )


def mgl_index(request):
    """
    /mgl/ is the manager area entry point, not a second homepage.
    """
    if request.user.is_authenticated:
        return redirect("manager_hub")
    return redirect("home")


def home(request):
    league = active_league()
    upcoming_qs = Fixture.objects.filter(
        is_released=True,
        status="SCHEDULED",
    ).select_related(
        "home_team",
        "away_team",
        "league",
    )
    completed_qs = Fixture.objects.filter(
        is_released=True,
        status="COMPLETED",
    ).select_related(
        "home_team",
        "away_team",
    ).prefetch_related(
        "submission__team_stats",
    ).order_by("-id")
    if league:
        upcoming_qs = upcoming_qs.filter(league=league)
        completed_qs = completed_qs.filter(league=league)

    upcoming = upcoming_qs[:5]

    news = (
        NewsPost.objects
        .filter(published=True)
        .order_by("-created_at")[:6]
    )

    recent_results = []
    completed = completed_qs[:5]

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
    table = build_league_table(league)
    club_qs = Team.objects.all()
    showcase_clubs = []
    if league:
        club_qs = Team.objects.filter(league=league)
        showcase_clubs = list(
            league.teams.select_related("manager").order_by("name")
        )
    recent_transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")[:8]
    )
    matches_played_qs = Fixture.objects.filter(
        is_released=True,
        status="COMPLETED",
    )
    if league:
        matches_played_qs = matches_played_qs.filter(league=league)

    appointments = (
        ClubApplication.objects.filter(status=ApprovalStatus.APPROVED)
        .select_related("manager", "team")
        .order_by("-created_at")[:6]
    )
    activity = []
    for post in news:
        activity.append(
            {
                "kind": post.get_category_display(),
                "title": post.title,
                "detail": post.category.replace("_", " ").title(),
                "when": post.created_at,
            }
        )
    for row in recent_transfers:
        frm = row.from_team.short_name if row.from_team_id else "FA"
        to = row.to_team.short_name if row.to_team_id else "—"
        activity.append(
            {
                "kind": "TRANSFER",
                "title": row.player.name if row.player_id else "Token movement",
                "detail": f"{frm} → {to} · {row.amount} TKN",
                "when": row.created_at,
            }
        )
    for fixture in recent_results:
        if fixture.home_goals is not None and fixture.away_goals is not None:
            detail = f"{fixture.home_goals} - {fixture.away_goals}"
        else:
            detail = "Full time"
        activity.append(
            {
                "kind": "RESULT",
                "title": f"{fixture.home_team.name} vs {fixture.away_team.name}",
                "detail": detail,
                "when": fixture.scheduled_at,
            }
        )
    for app in appointments:
        activity.append(
            {
                "kind": "APPOINTMENT",
                "title": f"{app.manager.display_name} appointed",
                "detail": app.team.name,
                "when": app.reviewed_at or app.created_at,
            }
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
            "club_count": club_qs.count(),
            "player_count": Player.objects.count(),
            "manager_count": club_qs.filter(manager__isnull=False).count(),
            "matches_played": matches_played_qs.count(),
            "free_agent_count": Player.objects.filter(
                is_free_agent=True,
                mgl_team__isnull=True,
            ).count(),
            "live_listing_count": PlayerListing.objects.filter(
                status=PlayerListing.LIVE
            ).count(),
            "recent_transfers": recent_transfers,
            "showcase_clubs": showcase_clubs,
            "activity": activity,
            "active_league": league,
            "table": table,
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
            "attribute_groups": attribute_groups_for_player(player),
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

    team = (
        Team.objects.select_related("league")
        .filter(manager=request.user)
        .first()
    )
    recent = []
    pending_actions = []

    if team:
        recent = (
            Fixture.objects
            .filter(Q(home_team=team) | Q(away_team=team))
            .order_by("-id")[:10]
        )
        pending_listings = PlayerListing.objects.filter(
            team=team,
            status=PlayerListing.PENDING,
        ).count()
        if pending_listings:
            pending_actions.append(f"{pending_listings} player sale(s) waiting for admin approval")
        pending_matches = MatchSubmission.objects.filter(
            fixture__in=Fixture.objects.filter(Q(home_team=team) | Q(away_team=team)),
            status="PENDING",
        ).count()
        if pending_matches:
            pending_actions.append(f"{pending_matches} match result(s) waiting for approval")

    rewards = (
        RewardTransaction.objects
        .filter(manager=manager)
        .order_by("-created_at")[:8]
    )
    transfers = (
        MarketTransaction.objects
        .filter(Q(seller=manager) | Q(buyer=manager))
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")[:8]
    )

    roster_count = team.players.count() if team else 0
    token_balance = token_balance_for_user(request.user)

    return render(
        request,
        "mgl/manager_hub.html",
        {
            "manager": manager,
            "team": team,
            "recent": recent,
            "rewards": rewards,
            "transfers": transfers,
            "roster_count": roster_count,
            "token_balance": token_balance,
            "pending_actions": pending_actions,
            "active_league": getattr(team, "league", None) or active_league(),
        },
    )


@login_required
def fixture_list(request):
    league = active_league()
    fixtures = (
        Fixture.objects
        .filter(is_released=True)
        .select_related(
            "home_team",
            "away_team",
            "league",
        )
    )
    if league:
        fixtures = fixtures.filter(league=league)
    team = getattr(request.user, "managed_team", None)

    return render(
        request,
        "mgl/fixtures.html",
        {
            "fixtures": fixtures,
            "team": team,
            "active_league": league,
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
    search = request.GET.get("search", "").strip()
    position = request.GET.get("position", "").strip()
    min_ovr = request.GET.get("min_ovr", "").strip()
    sort = request.GET.get("sort", "-overall")
    players = Player.objects.filter(
        is_free_agent=True,
        mgl_team__isnull=True,
    )
    if search:
        players = apply_player_search(players, search)
    if position:
        players = players.filter(position=position)
    if min_ovr.isdigit():
        players = players.filter(overall__gte=int(min_ovr))
    allowed_sort = {
        "overall": "overall",
        "-overall": "-overall",
        "name": "name",
        "-name": "-name",
    }
    players = players.order_by(allowed_sort.get(sort, "-overall"), "name")
    page = Paginator(players, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "mgl/free_agents.html",
        {
            "players": page,
            "page_obj": page,
            "search": search,
            "selected_position": position,
            "min_ovr": min_ovr,
            "selected_sort": sort,
            "positions": [choice[0] for choice in Player.POSITION_CHOICES],
            "querystring": _querystring(request),
            "result_count": page.paginator.count,
            "auction_durations": AUCTION_DURATION_CHOICES,
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
    team = club_for_user(request.user)
    spells = manager.club_spells.select_related("team").order_by("-started_at")
    applications = manager.club_applications.select_related("team").order_by("-created_at")[:12]
    played = 0
    win_rate = None
    if career:
        played = career.wins + career.draws + career.losses
        if played:
            win_rate = round(100 * career.wins / played, 1)
    goals_for = 0
    goals_against = 0
    if team:
        own_stats = TeamMatchStats.objects.filter(
            team=team,
            submission__status=ApprovalStatus.APPROVED,
        )
        for row in own_stats:
            goals_for += row.goals
        conceded = TeamMatchStats.objects.filter(
            submission__status=ApprovalStatus.APPROVED,
        ).filter(
            Q(submission__fixture__home_team=team) | Q(submission__fixture__away_team=team)
        ).exclude(team=team)
        for row in conceded:
            goals_against += row.goals

    return render(
        request,
        "mgl/profile.html",
        {
            "manager": manager,
            "career": career,
            "trophies": trophies,
            "rewards": rewards,
            "team": team,
            "token_balance": token_balance_for_user(request.user),
            "spells": spells,
            "applications": applications,
            "played": played,
            "win_rate": win_rate,
            "goals_for": goals_for,
            "goals_against": goals_against,
        },
    )


@login_required
def player_database(request):
    tier = request.GET.get("tier", "").upper()
    search = request.GET.get("search", "").strip()
    club = request.GET.get("club", "").strip()
    position = request.GET.get("position", "").strip()
    rating_min = request.GET.get("rating_min", "").strip()
    rating_max = request.GET.get("rating_max", "").strip()
    sort = request.GET.get("sort", "-overall")
    free_only = request.GET.get("free") == "1"

    players = Player.objects.select_related("mgl_team")

    if tier == "GOLD":
        players = players.filter(overall__gte=75)
    elif tier == "SILVER":
        players = players.filter(overall__gte=65, overall__lt=75)
    elif tier == "BRONZE":
        players = players.filter(overall__lt=65)

    if search:
        players = apply_player_search(
            players,
            search,
            extra_fields=(
                "fc27_club",
                "position",
                "nationality",
                "mgl_team__name",
                "mgl_team__short_name",
            ),
        )

    if club == "FA" or free_only:
        players = players.filter(mgl_team__isnull=True)
    elif club.isdigit():
        players = players.filter(mgl_team_id=int(club))

    if position:
        players = players.filter(position=position)

    if rating_min.isdigit():
        players = players.filter(overall__gte=int(rating_min))
    if rating_max.isdigit():
        players = players.filter(overall__lte=int(rating_max))

    allowed_sort = {
        "overall": "overall",
        "-overall": "-overall",
        "name": "name",
        "-name": "-name",
    }
    order = allowed_sort.get(sort, "-overall")
    players = players.order_by(order, "name")

    paginator = Paginator(players, 24)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "mgl/player_database.html",
        {
            "players": page,
            "page_obj": page,
            "selected_tier": tier,
            "search": search,
            "selected_club": club,
            "selected_position": position,
            "rating_min": rating_min,
            "rating_max": rating_max,
            "selected_sort": sort,
            "free_only": free_only,
            "clubs": Team.objects.order_by("name"),
            "positions": [choice[0] for choice in Player.POSITION_CHOICES],
            "querystring": _querystring(request),
            "result_count": page.paginator.count,
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
    transfers = (
        MarketTransaction.objects
        .filter(Q(seller=manager) | Q(buyer=manager))
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")
    )
    token_balance = token_balance_for_user(request.user)

    return render(
        request,
        "mgl/rewards.html",
        {
            "manager": manager,
            "rewards": rewards,
            "transfers": transfers,
            "token_balance": token_balance,
            "team": club_for_user(request.user),
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
                "token_balance": token_balance_for_user(request.user),
            },
        )

    players = list(
        team.players.select_related("mgl_team").order_by(
            "position",
            "-overall",
            "name",
        )
    )

    total_ovr = sum(player.overall for player in players)
    available_spaces = max(0, team.roster_limit - len(players))
    listings = {
        listing.player_id: listing
        for listing in PlayerListing.objects.filter(
            team=team,
            status__in=[PlayerListing.PENDING, PlayerListing.LIVE],
        )
    }
    from auctions.models import PlayerAuction

    close_expired_auctions()
    live_auctions = {
        auction.player_id: auction
        for auction in PlayerAuction.objects.filter(
            player_id__in=[player.id for player in players],
            status=PlayerAuction.LIVE,
        )
    }
    for player in players:
        player.current_listing = listings.get(player.id)
        player.current_auction = live_auctions.get(player.id)

    gk = {"GK"}
    defence = {"CB", "LB", "RB", "LWB", "RWB"}
    midfield = {"CDM", "CM", "CAM", "LM", "RM"}
    attack = {"LW", "RW", "ST", "CF"}
    squad_groups = [
        ("GOALKEEPERS", [player for player in players if player.position in gk]),
        ("DEFENDERS", [player for player in players if player.position in defence]),
        ("MIDFIELDERS", [player for player in players if player.position in midfield]),
        ("FORWARDS", [player for player in players if player.position in attack]),
    ]
    ungrouped = [
        player
        for player in players
        if player.position not in gk | defence | midfield | attack
    ]
    if ungrouped:
        squad_groups.append(("SQUAD", ungrouped))

    return render(
        request,
        "mgl/team_management.html",
        {
            "team": team,
            "players": players,
            "total_ovr": total_ovr,
            "available_spaces": available_spaces,
            "squad_groups": squad_groups,
            "token_balance": token_balance_for_user(request.user),
            "auction_durations": AUCTION_DURATION_CHOICES,
        },
    )


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
    close_club_spell_for_user(old_manager, team)

    messages.success(
        request,
        f"{old_manager.username} has left {team.name}. "
        f"The club remains intact and the manager keeps their token balance.",
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
            close_club_spell_for_user(old_manager, team)
        open_club_spell(application, team)

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


def competition_page(request, slug):
    if slug == "mls":
        raise Http404("MLS is not an active MGL competition.")
    name = COMPETITIONS.get(slug)
    if not name:
        raise Http404("Unknown competition")
    ensure_premier_league()
    short = LIVE_COMPETITION_SLUGS.get(slug)
    league = None
    table = None
    if short:
        league = League.objects.filter(
            short_name__iexact=short, is_active=True
        ).prefetch_related("teams__manager").first()
        if league:
            table = build_league_table(league)
    return render(
        request,
        "mgl/competition.html",
        {
            "competition_name": name,
            "competition_slug": slug,
            "league": league,
            "table": table,
            "is_live": bool(league),
        },
    )


def historical_tables(request):
    league = active_league()
    return render(
        request,
        "mgl/historical_tables.html",
        {
            "active_league": league,
            "table": build_league_table(league),
        },
    )


def head_to_head(request):
    return _feature_page(
        request,
        "Head to Head",
        "STATS & HISTORY",
        "Head-to-head records will appear here after official Premier League matches are played and approved. No exhibition results are invented.",
    )


def compare_players(request):
    return _feature_page(
        request,
        "Compare",
        "STATS & HISTORY",
        "Player comparison is not live yet. Open any player profile from All Players or Free Agents to view their recognised FC26 name, card and attributes.",
    )


def manager_search(request):
    search = request.GET.get("q", "").strip()
    managers = (
        ManagerApplication.objects.filter(status=ManagerApplication.APPROVED)
        .select_related("user")
        .order_by("display_name")
    )
    if search:
        managers = managers.filter(
            Q(display_name__icontains=search)
            | Q(gamertag__icontains=search)
            | Q(user__username__icontains=search)
        )
    return render(
        request,
        "mgl/manager_search.html",
        {
            "search": search,
            "managers": managers,
        },
    )


def transfer_history(request):
    transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .select_related("player", "from_team", "to_team", "seller", "buyer")
        .order_by("-created_at")
    )
    page = Paginator(transfers, 30).get_page(request.GET.get("page"))
    return render(
        request,
        "mgl/transfer_history.html",
        {
            "transfers": page,
            "page_obj": page,
        },
    )


@login_required
def scouting(request):
    from mgl.scouting import (
        BRONZE,
        GOLD,
        SILVER,
        TIER_BASE_HOURS,
        TIER_RANGES,
        UPGRADE_COSTS,
        complete_ready_assignments,
        cooldown_hours,
        dispatch_scout,
        get_or_create_scout_profile,
        level_for,
        remaining_wait,
        scout_nationalities,
        scout_positions,
        upgrade_scout,
    )

    manager = manager_for_user(request.user)
    if not manager:
        return redirect("manager_login")
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "upgrade":
                profile, level, cost = upgrade_scout(manager, request.POST.get("tier"))
                messages.success(request, f"Scout upgraded to level {level} for {cost} tokens.")
            elif action == "dispatch":
                assignment = dispatch_scout(
                    manager,
                    request.POST.get("tier"),
                    request.POST.get("region", ""),
                    request.POST.get("position", ""),
                )
                messages.success(
                    request,
                    f"{assignment.get_tier_display()} scout dispatched. Report ready at {assignment.ready_at}.",
                )
            else:
                messages.error(request, "Unknown scouting action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("scouting")

    complete_ready_assignments(manager)
    profile = get_or_create_scout_profile(manager)
    now = timezone.now()
    panels = []
    for tier, label in ((BRONZE, "Bronze"), (SILVER, "Silver"), (GOLD, "Gold")):
        level = level_for(profile, tier)
        current = (
            ScoutAssignment.objects.filter(
                manager=manager, tier=tier, status=ScoutAssignment.PENDING
            )
            .order_by("-started_at")
            .first()
        )
        wait = remaining_wait(current, now=now) if current else None
        nxt = level + 1
        panels.append(
            {
                "tier": tier,
                "label": label,
                "range": TIER_RANGES[tier],
                "base_hours": TIER_BASE_HOURS[tier],
                "level": level,
                "cooldown_hours": cooldown_hours(tier, level),
                "next_cost": UPGRADE_COSTS.get(nxt),
                "current": current,
                "remaining": wait,
                "available": current is None or (wait is not None and wait.total_seconds() <= 0),
            }
        )
    reports = manager.scout_reports.select_related("player", "player__mgl_team")[:20]
    return render(
        request,
        "mgl/scouting.html",
        {
            "manager": manager,
            "token_balance": token_balance_for_user(request.user),
            "panels": panels,
            "nationalities": scout_nationalities(),
            "positions": scout_positions(),
            "reports": reports,
        },
    )


@login_required
@require_POST
def list_player_for_auction(request, player_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to auction a player.")
        return redirect("team_management")
    player = get_object_or_404(Player, pk=player_id)
    try:
        create_manager_auction(
            player,
            manager,
            request.POST.get("duration"),
            request.POST.get("starting_bid") or 1,
        )
        messages.success(request, f"{player.name} is now in auction.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("team_management")


@owner_admin_required
@require_POST
def auction_free_agent(request, player_id):
    player = get_object_or_404(Player, pk=player_id)
    try:
        auction = create_free_agent_auction(
            player,
            request.user,
            request.POST.get("duration"),
            request.POST.get("starting_bid") or 1,
        )
        messages.success(
            request,
            f"{player.name} is live in auction until {auction.ends_at}.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or "free_agents")


def youth_academy(request):
    return _feature_page(
        request,
        "Youth Academy",
        "MARKET",
        "Youth Academy is not live yet. The FC26 player pool already includes every registered player available to MGL.",
    )
