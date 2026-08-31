from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
    PressConference,
    NewsPost,
    RewardTransaction,
    MarketTransaction,
    PlayerListing,
    ScoutAssignment,
)
from .market import (
    AUCTION_DURATION_CHOICES,
    MAX_ACTIVE_CLUB_LISTINGS,
    active_market_listing_count,
    close_expired_auctions,
    club_for_user,
    create_free_agent_auction,
    create_manager_auction,
    token_balance_for_user,
)
from .nav import COMPETITIONS, LIVE_COMPETITION_SLUGS, live_competition_choices
from .permissions import approved_manager, is_owner_or_admin, owner_admin_required
from .player_state import (
    AUCTION,
    CLUB_PLAYER,
    FREE_AGENT,
    UNASSIGNED,
    free_agents as free_agent_qs,
    live_auction_player_ids,
    market_counts,
    unassigned_players,
)
from .services import manager_for_user
from .tenure import close_club_spell_for_user, open_club_spell, resign_manager_from_club
from .activity import record_manager_departure


def _post_int(post, key, default=0):
    try:
        return int(post.get(key, default))
    except (TypeError, ValueError):
        return default


def _querystring(request):
    query = request.GET.copy()
    query.pop("page", None)
    return query.urlencode()


def _attach_news_logos(posts):
    """Mark public news rows with the existing club objects for logo rendering."""
    for post in posts:
        primary = getattr(post, "primary_team", None)
        secondary = getattr(post, "secondary_team", None)
        post.logo_from = None
        post.logo_to = None
        post.logo_single = None
        post.logo_kind = "single"
        if post.category == NewsPost.RESULTS and primary and secondary:
            post.logo_from = primary
            post.logo_to = secondary
            post.logo_kind = "result"
        elif post.category == NewsPost.TRANSFER and primary and secondary:
            post.logo_from = secondary
            post.logo_to = primary
            post.logo_kind = "transfer"
        else:
            post.logo_single = primary or secondary
    return posts


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
    if approved_manager(request.user) and club_for_user(request.user):
        return redirect("manager_hub")

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

    news = _attach_news_logos(
        list(
            NewsPost.objects.filter(published=True)
            .select_related("primary_team", "secondary_team")
            .order_by("-created_at")[:6]
        )
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
    if league:
        club_qs = Team.objects.filter(league=league)
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
            "unassigned_count": unassigned_players().count(),
            "free_agent_count": free_agent_qs().count(),
            "live_listing_count": PlayerListing.objects.filter(
                status=PlayerListing.LIVE
            ).count(),
            "recent_transfers": recent_transfers,
            "activity": activity,
            "active_league": league,
            "table": table,
        },
    )


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

    from mgl.market import transfer_offer_context_for

    return render(
        request,
        "mgl/player_profile.html",
        {
            "player": player,
            "ownership_history": ownership_history,
            "totw_selections": totw_selections,
            "auction_requests": auction_requests,
            "attribute_groups": attribute_groups_for_player(player),
            **transfer_offer_context_for(request.user, player),
        },
    )


@login_required
def manager_notifications(request):
    manager = manager_for_user(request.user)
    is_control = getattr(request.user, "role", None) in ("OWNER", "ADMIN")
    if not manager and not is_control:
        messages.error(
            request,
            "You do not have a manager account.",
        )
        return redirect("manager_login")

    from mgl.notifications import inbox_for_user, mark_inbox_read

    inbox = inbox_for_user(request.user)
    mark_inbox_read(request.user)
    return render(
        request,
        "mgl/notifications.html",
        {
            "manager": manager,
            "notifications": inbox,
        },
    )


@login_required
@require_POST
def manager_notification_respond(request, notification_id):
    from django.core.exceptions import PermissionDenied
    from mgl.inbox_actions import (
        InboxActionError,
        notification_for_recipient,
        respond_to_inbox_notification,
    )

    manager = manager_for_user(request.user)
    is_control = getattr(request.user, "role", None) in ("OWNER", "ADMIN")
    if not manager and not is_control:
        messages.error(request, "You do not have a manager account.")
        return redirect("manager_login")

    notification = notification_for_recipient(request.user, notification_id)
    if notification is None:
        messages.error(request, "That notification does not belong to your account.")
        return redirect("manager_notifications")

    accept = (request.POST.get("action") or "").strip().lower() == "accept"
    reject = (request.POST.get("action") or "").strip().lower() == "reject"
    if not accept and not reject:
        messages.error(request, "Choose Accept or Reject.")
        return redirect("manager_notifications")
    try:
        respond_to_inbox_notification(request.user, notification, accept)
    except PermissionDenied:
        messages.error(request, "You are not allowed to action this notification.")
        return redirect("manager_notifications")
    except InboxActionError as exc:
        messages.error(request, str(exc))
        return redirect("manager_notifications")
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("manager_notifications")
    source = notification.source_key or ""
    if accept and source.startswith("admin-listing-"):
        messages.success(
            request,
            "Listing approved. The player is now live on the transfer market.",
        )
    elif accept:
        messages.success(
            request,
            "Response recorded. Owner/Admin approval is still required where applicable.",
        )
    else:
        messages.success(request, "You rejected this request.")
    return redirect("manager_notifications")


@login_required
def transfer_requests(request):
    from mgl.market import transfer_window_is_open
    from mgl.permissions import is_owner_or_admin
    from mgl.transfer_requests import (
        completed_transfers_for,
        decorate_transfer_request,
        filter_requests,
        format_tokens,
        incoming_offer_count,
        incoming_transfer_requests,
        outgoing_transfer_requests,
        richest_assigned_managers,
        transfer_centre_stats,
    )

    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to review transfer requests.")
        return redirect("manager_hub")
    club = club_for_user(request.user)
    if not club:
        messages.error(request, "You need a club before you can manage transfer requests.")
        return redirect("manager_hub")

    status = (request.GET.get("status") or "all").strip().lower()
    show_all_completed = request.GET.get("completed") == "all"
    incoming = filter_requests(
        [decorate_transfer_request(row) for row in incoming_transfer_requests(club)],
        status,
    )
    outgoing = filter_requests(
        [decorate_transfer_request(row) for row in outgoing_transfer_requests(manager)],
        status,
    )
    completed = completed_transfers_for(
        club,
        all_clubs=is_owner_or_admin(request.user),
        limit=None if show_all_completed else 8,
    )
    for row in completed:
        row.fee_label = format_tokens(row.amount)
    return render(
        request,
        "mgl/transfer_requests.html",
        {
            "manager": manager,
            "club": club,
            "incoming": incoming,
            "outgoing": outgoing,
            "incoming_count": incoming_offer_count(club),
            "window_open": transfer_window_is_open(),
            "completed_transfers": completed,
            "show_all_completed": show_all_completed,
            "richest_managers": richest_assigned_managers(8),
            "transfer_stats": transfer_centre_stats(),
            "request_status": status,
        },
    )


@login_required
@require_POST
def respond_transfer_request(request, listing_id):
    from mgl.market import respond_to_transfer_offer

    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to review transfer requests.")
        return redirect("manager_hub")
    club = club_for_user(request.user)
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    if club is None or listing.team_id != club.id or listing.team.manager_id != request.user.id:
        raise PermissionDenied("You can only respond to transfer requests for your own club.")
    raw_action = (request.POST.get("action") or "").strip().lower()
    accept = raw_action in ("accept", "approve")
    reject = raw_action == "reject"
    if not accept and not reject:
        messages.error(request, "Choose Approve or Reject.")
        return redirect("transfer_requests")
    try:
        respond_to_transfer_offer(listing, request.user, accept)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("transfer_requests")
    if accept:
        messages.success(
            request,
            "Request accepted. The league office still has to approve the transfer.",
        )
    else:
        messages.success(request, "Transfer request rejected.")
    return redirect("transfer_requests")


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
    outstanding = []
    recent_results = []
    top_scorers = []
    top_assists = []
    squad = []
    league_position = None
    table = []

    standings_row = None
    league_size = 0
    form = []

    if team:
        team_fixtures = Fixture.objects.filter(
            Q(home_team=team) | Q(away_team=team)
        ).select_related(
            "home_team",
            "away_team",
            "home_team__manager",
            "away_team__manager",
            "league",
        )
        recent = team_fixtures.order_by("-id")[:10]
        outstanding = list(
            team_fixtures.filter(is_released=True, status="SCHEDULED").order_by(
                "matchweek", "id"
            )
        )
        submitted_ids = set(
            MatchSubmission.objects.filter(
                fixture_id__in=[fixture.id for fixture in outstanding]
            ).values_list("fixture_id", flat=True)
        )
        for fixture in outstanding:
            fixture.opponent = (
                fixture.away_team if fixture.home_team_id == team.id else fixture.home_team
            )
            fixture.can_submit = (
                approved_manager(request.user) is not None
                and request.user.id
                in {
                    fixture.home_team.manager_id,
                    fixture.away_team.manager_id,
                }
                and fixture.id not in submitted_ids
            )
        completed = list(
            team_fixtures.filter(status="COMPLETED")
            .prefetch_related("submission__team_stats")
            .order_by("-matchweek", "-id")[:5]
        )
        for fixture in completed:
            stats = {}
            try:
                stats = {
                    row.team_id: row.goals
                    for row in fixture.submission.team_stats.all()
                }
            except MatchSubmission.DoesNotExist:
                pass
            own = stats.get(team.id)
            opp_id = (
                fixture.away_team_id
                if fixture.home_team_id == team.id
                else fixture.home_team_id
            )
            opp = stats.get(opp_id)
            if own is None or opp is None:
                outcome = "—"
                mark = "—"
            elif own > opp:
                outcome = "W"
                mark = "✓"
            elif own < opp:
                outcome = "L"
                mark = "✕"
            else:
                outcome = "D"
                mark = "="
            fixture.home_goals = stats.get(fixture.home_team_id)
            fixture.away_goals = stats.get(fixture.away_team_id)
            fixture.outcome = outcome
            fixture.result_mark = mark
            fixture.result_line = (
                f"{fixture.home_team.name} {fixture.home_goals}–{fixture.away_goals} "
                f"{fixture.away_team.name}"
            )
            fixture.opponent = (
                fixture.away_team if fixture.home_team_id == team.id else fixture.home_team
            )
            fixture.venue = "H" if fixture.home_team_id == team.id else "A"
            recent_results.append(fixture)
        squad = list(
            team.players.order_by("position", "-overall", "name")
        )
        top_scorers = [p for p in squad if (p.goals or 0) > 0]
        top_scorers.sort(key=lambda p: (-p.goals, p.name))
        top_scorers = top_scorers[:5]
        top_assists = [p for p in squad if (p.assists or 0) > 0]
        top_assists.sort(key=lambda p: (-p.assists, p.name))
        top_assists = top_assists[:5]
        table = build_league_table(team.league)
        league_size = len(table)
        standings_row = next(
            (row for row in table if row["team"].id == team.id),
            None,
        )
        league_position = (
            standings_row["position"] if standings_row else None
        )
        form = [
            fixture.outcome
            for fixture in reversed(recent_results[:5])
            if fixture.outcome in {"W", "D", "L"}
        ]

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

    roster_count = len(squad) if team else 0
    token_balance = token_balance_for_user(request.user)
    from mgl.transfer_requests import incoming_offer_count

    incoming_transfer_count = incoming_offer_count(team)

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
            "incoming_transfer_count": incoming_transfer_count,
            "active_league": getattr(team, "league", None) or active_league(),
            "outstanding": outstanding,
            "outstanding_count": len(outstanding),
            "recent_results": recent_results,
            "top_scorers": top_scorers,
            "top_assists": top_assists,
            "squad": squad[:12],
            "league_position": league_position,
            "league_size": league_size,
            "standings_row": standings_row,
            "form": form,
            "table": table[:8],
            "confirm_resign": bool(team) and request.GET.get("resign") == "1",
        },
    )


def fixture_list(request):
    from mgl.fixture_display import (
        annotate_fixtures,
        calendar_months,
        club_standings,
        deadline_context,
        group_by_month,
        summary_for,
    )

    league = active_league()
    team = None
    if request.user.is_authenticated:
        team = (
            Team.objects.select_related("league")
            .filter(manager=request.user)
            .first()
        )

    divisions = list(
        League.objects.filter(is_active=True).order_by("display_order", "id")
    )
    admin_view = is_owner_or_admin(request.user) if request.user.is_authenticated else False
    if team and team.league_id and not admin_view:
        league = team.league
    elif request.GET.get("league"):
        picked = next(
            (row for row in divisions if str(row.id) == str(request.GET.get("league"))),
            None,
        )
        if picked is not None and (admin_view or not team):
            league = picked

    fixtures = (
        Fixture.objects.filter(is_released=True)
        .select_related(
            "home_team",
            "away_team",
            "home_team__manager",
            "away_team__manager",
            "league",
        )
        .order_by("matchweek", "scheduled_at", "id")
    )
    if league:
        fixtures = fixtures.filter(league=league)
    if team and not admin_view:
        fixtures = fixtures.filter(Q(home_team=team) | Q(away_team=team))

    viewer = request.user if request.user.is_authenticated else None
    fixtures = annotate_fixtures(fixtures, team, viewer)
    standings_row, league_size = (None, 0)
    if team:
        standings_row, league_size = club_standings(team.league, team)
    roster_count = team.players.count() if team else 0
    upcoming = [
        row
        for row in fixtures
        if not row.is_official
    ]
    results = [
        row
        for row in fixtures
        if row.is_official or row.submission_row is not None
    ]
    return render(
        request,
        "mgl/fixtures.html",
        {
            "fixtures": fixtures,
            "fixture_groups": group_by_month(upcoming or fixtures),
            "result_groups": group_by_month(results),
            "calendar_months": calendar_months(fixtures),
            "team": team,
            "active_league": league,
            "divisions": divisions,
            "admin_view": admin_view,
            "standings_row": standings_row,
            "league_size": league_size,
            "roster_count": roster_count,
            "summary": summary_for(fixtures, standings_row),
            "deadline_info": deadline_context(fixtures),
            "manager": approved_manager(request.user) if request.user.is_authenticated else None,
        },
    )


@login_required
@transaction.atomic
def submit_match(request, fixture_id):
    from mgl.match_submit import MatchSubmitError, save_match_submission, submission_blocks_resubmit

    fixture = get_object_or_404(
        Fixture.objects.select_related(
            "home_team",
            "away_team",
        ),
        pk=fixture_id,
        is_released=True,
    )

    from mgl.fixture_display import side_review, workflow_step
    from mgl.models import ManagerNotification

    manager = approved_manager(request.user)
    admin_view = is_owner_or_admin(request.user)

    if not manager and not admin_view:
        messages.error(
            request,
            "You must be an approved manager to submit a result.",
        )
        return redirect("fixture_list")

    allowed_managers = [
        fixture.home_team.manager_id,
        fixture.away_team.manager_id,
    ]
    involved = request.user.id in allowed_managers

    if not involved and not admin_view:
        messages.error(
            request,
            "You can only submit a result for a fixture that involves your club.",
        )
        return redirect("fixture_list")

    existing = (
        MatchSubmission.objects.filter(fixture=fixture)
        .prefetch_related(
            "team_stats__goal_events__player",
            "team_stats__assist_events__player",
            "team_stats__defender_ratings__player",
            "team_stats__gk_saves__player",
        )
        .first()
    )
    readonly = bool(existing is not None and submission_blocks_resubmit(existing))

    if request.method == "POST":
        if not involved:
            messages.error(
                request,
                "You can only submit a result for a fixture that involves your club.",
            )
            return redirect("fixture_list")
        if readonly:
            messages.error(
                request,
                "This match has already been submitted.",
            )
            return redirect("fixture_list")
        try:
            submission = save_match_submission(fixture, request.user, request.POST)
        except MatchSubmitError as exc:
            messages.error(request, str(exc))
            return redirect("submit_match", fixture.id)
        from mgl.notifications import notify_opponent_of_score_submission

        notify_opponent_of_score_submission(fixture, submission, request.user)
        messages.success(
            request,
            "Match submitted to the opposing manager. Statistics stay unofficial until approved.",
        )
        return redirect("fixture_list")

    sides = []
    for team, prefix in (
        (fixture.home_team, "home"),
        (fixture.away_team, "away"),
    ):
        players = list(
            Player.objects.filter(mgl_team=team).order_by("position", "-overall", "name")
        )
        defenders = [row for row in players if row.position in {"CB", "LB", "RB", "LWB", "RWB"}]
        keepers = [row for row in players if (row.position or "").upper() == "GK"]
        side = {
            "team": team,
            "prefix": prefix,
            "label": "HOME" if prefix == "home" else "AWAY",
            "players": players,
            "defenders": defenders,
            "keepers": keepers,
        }
        if readonly:
            side = side_review(side, existing)
        sides.append(side)

    opponent_notice = None
    if (
        existing is not None
        and existing.opponent_response == "PENDING"
        and involved
        and existing.submitted_by_id != request.user.id
    ):
        opponent_notice = ManagerNotification.objects.filter(
            recipient=request.user,
            fixture=fixture,
            source_key=f"score-submitted-{fixture.pk}",
            response_status=ManagerNotification.PENDING,
        ).first()

    return render(
        request,
        "mgl/submit_match.html",
        {
            "fixture": fixture,
            "sides": sides,
            "card_choices": range(0, 12),
            "readonly": readonly,
            "submission": existing,
            "workflow_step": workflow_step(existing),
            "opponent_notice": opponent_notice,
            "can_submit": involved and not readonly,
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
            "question": question or "How pleased were you with the performance?",
            "team": (
                fixture.home_team
                if request.user.id == fixture.home_team.manager_id
                else fixture.away_team
            ),
            "trigger": PressConference.MATCH,
            "matchweek": fixture.matchweek,
        },
    )
    press = PressConference.objects.get(fixture=fixture, manager=request.user)
    from mgl.press import publish_press_answer

    try:
        publish_press_answer(press, answer)
        messages.success(
            request,
            "Your answer has been submitted and is awaiting Admin approval.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("pressroom")


@login_required
@require_POST
def release_my_player(request, player_id):
    from .services import release_player

    if approved_manager(request.user) is None:
        messages.error(request, "You do not have an approved manager profile.")
        return redirect("manager_hub")

    team = getattr(request.user, "managed_team", None)

    if not team:
        messages.error(request, "You do not manage a club.")
        return redirect("manager_hub")

    player = get_object_or_404(
        Player,
        pk=player_id,
        mgl_team=team,
    )

    try:
        release_player(
            player,
            team,
            source="MANAGER_RELEASE",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("team_management")

    messages.success(
        request,
        f"{player.name} released to Free Agents.",
    )
    return redirect("team_management")


FREE_AGENT_POSITION_GROUPS = {
    "DEFENDERS": ("CB", "LB", "RB", "LWB", "RWB"),
    "MIDFIELDERS": ("CDM", "CM", "CAM", "LM", "RM"),
    "ATTACKERS": ("LW", "RW", "ST", "CF"),
}


@login_required
def free_agents(request):
    search = request.GET.get("search", "").strip()
    position = request.GET.get("position", "").strip()
    min_ovr = request.GET.get("min_ovr", "").strip()
    max_ovr = request.GET.get("max_ovr", "").strip()
    nationality = request.GET.get("nationality", "").strip()
    min_age = request.GET.get("min_age", "").strip()
    max_age = request.GET.get("max_age", "").strip()
    sort = request.GET.get("sort", "-overall")
    per_page_raw = request.GET.get("per_page", "").strip()
    page_size = 40
    if per_page_raw.isdigit() and int(per_page_raw) in {10, 40, 80}:
        page_size = int(per_page_raw)
    all_free_agents = free_agent_qs()
    players = all_free_agents
    if search:
        players = apply_player_search(players, search)
    if position in FREE_AGENT_POSITION_GROUPS:
        players = players.filter(position__in=FREE_AGENT_POSITION_GROUPS[position])
    elif position:
        players = players.filter(position=position)
    if min_ovr.isdigit():
        players = players.filter(overall__gte=int(min_ovr))
    if max_ovr.isdigit():
        players = players.filter(overall__lte=int(max_ovr))
    if nationality:
        players = players.filter(nationality=nationality)
    if min_age.isdigit():
        players = players.filter(age__gte=int(min_age))
    if max_age.isdigit():
        players = players.filter(age__lte=int(max_age))
    allowed_sort = {
        "overall": "overall",
        "-overall": "-overall",
        "name": "name",
        "-name": "-name",
    }
    players = players.order_by(allowed_sort.get(sort, "-overall"), "name")
    page = Paginator(players, page_size).get_page(request.GET.get("page"))
    gk = {"GK"}
    line_counts = {
        "total": all_free_agents.count(),
        "keepers": all_free_agents.filter(position__in=gk).count(),
        "defenders": all_free_agents.filter(
            position__in=FREE_AGENT_POSITION_GROUPS["DEFENDERS"]
        ).count(),
        "midfielders": all_free_agents.filter(
            position__in=FREE_AGENT_POSITION_GROUPS["MIDFIELDERS"]
        ).count(),
        "attackers": all_free_agents.filter(
            position__in=FREE_AGENT_POSITION_GROUPS["ATTACKERS"]
        ).count(),
    }
    nations = sorted(
        {
            name
            for name in all_free_agents.exclude(nationality="")
            .values_list("nationality", flat=True)
            .distinct()
            if name
        }
    )
    return render(
        request,
        "mgl/free_agents.html",
        {
            "players": page,
            "page_obj": page,
            "search": search,
            "selected_position": position,
            "min_ovr": min_ovr,
            "max_ovr": max_ovr,
            "nationality": nationality,
            "min_age": min_age,
            "max_age": max_age,
            "selected_sort": sort,
            "per_page": page_size,
            "positions": [choice[0] for choice in Player.POSITION_CHOICES],
            "nations": nations,
            "line_counts": line_counts,
            "querystring": _querystring(request),
            "result_count": page.paginator.count,
            "can_sign": bool(club_for_user(request.user)),
        },
    )


@login_required
@require_POST
def sign_free_agent_view(request, player_id):
    from .services import sign_free_agent

    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to sign a Free Agent.")
        return redirect("free_agents")
    player = get_object_or_404(Player, pk=player_id)
    try:
        sign_free_agent(player, manager)
        messages.success(
            request,
            f"{player.name} signed for 0 TKN.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("free_agents")


@owner_admin_required
def unassigned_players_page(request):
    search = request.GET.get("search", "").strip()
    position = request.GET.get("position", "").strip()
    min_ovr = request.GET.get("min_ovr", "").strip()
    sort = request.GET.get("sort", "-overall")
    players = unassigned_players()
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
    counts = market_counts()
    return render(
        request,
        "mgl/unassigned_players.html",
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
            "market_counts": counts,
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
    confirm_resign = request.GET.get("resign") == "1" and team is not None
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
            "played": played,
            "win_rate": win_rate,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "confirm_resign": confirm_resign,
        },
    )


@login_required
@require_POST
def resign_from_club(request):
    manager = approved_manager(request.user)
    next_page = "manager_hub" if request.POST.get("next") == "hub" else "manager_profile"
    if not manager:
        messages.error(request, "You must be an approved manager to resign from a club.")
        return redirect(next_page)
    try:
        team = resign_manager_from_club(manager)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(next_page)
    messages.success(
        request,
        f"You have resigned from {team.name}. Your personal token balance is unchanged.",
    )
    record_manager_departure(request.user, team)
    return redirect(next_page)


PLAYER_DATABASE_FACE_FILTERS = (
    ("pace_min", "pace"),
    ("shooting_min", "shooting"),
    ("passing_min", "passing"),
    ("dribbling_min", "dribbling"),
    ("defending_min", "defending"),
    ("physical_min", "physical"),
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
    status = request.GET.get("status", "").strip().upper()
    nationality = request.GET.get("nationality", "").strip()
    min_skills = request.GET.get("min_skills", "").strip()
    min_weak_foot = request.GET.get("min_weak_foot", "").strip()
    preferred_foot = request.GET.get("preferred_foot", "").strip()

    players = Player.objects.select_related("mgl_team")
    total_player_count = Player.objects.count()

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
        players = players.filter(mgl_team__isnull=True, is_free_agent=True)
    elif club == "UNASSIGNED":
        players = players.filter(mgl_team__isnull=True, is_free_agent=False).exclude(
            id__in=live_auction_player_ids()
        )
    elif club.isdigit():
        players = players.filter(mgl_team_id=int(club))

    if status == "CLUB" or status == CLUB_PLAYER.replace(" ", "_"):
        players = players.filter(mgl_team__isnull=False)
    elif status in {"FREE_AGENT", "FA", FREE_AGENT.replace(" ", "_")}:
        players = players.filter(mgl_team__isnull=True, is_free_agent=True)
    elif status == UNASSIGNED:
        players = players.filter(mgl_team__isnull=True, is_free_agent=False).exclude(
            id__in=live_auction_player_ids()
        )
    elif status == AUCTION:
        players = players.filter(id__in=live_auction_player_ids())

    if position in FREE_AGENT_POSITION_GROUPS:
        players = players.filter(position__in=FREE_AGENT_POSITION_GROUPS[position])
    elif position:
        players = players.filter(position=position)

    if nationality:
        players = players.filter(nationality__iexact=nationality)

    if rating_min.isdigit():
        players = players.filter(overall__gte=int(rating_min))
    if rating_max.isdigit():
        players = players.filter(overall__lte=int(rating_max))
    if min_skills.isdigit():
        players = players.filter(skill_moves__gte=int(min_skills))
    if min_weak_foot.isdigit():
        players = players.filter(weak_foot__gte=int(min_weak_foot))
    if preferred_foot:
        players = players.filter(preferred_foot__iexact=preferred_foot)

    face_values = {}
    for param, field in PLAYER_DATABASE_FACE_FILTERS:
        raw = request.GET.get(param, "").strip()
        face_values[param] = raw
        if raw.isdigit():
            players = players.filter(**{f"{field}__gte": int(raw)})

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
    nationalities = (
        Player.objects.exclude(nationality="")
        .order_by("nationality")
        .values_list("nationality", flat=True)
        .distinct()
    )
    preferred_feet = (
        Player.objects.exclude(preferred_foot="")
        .order_by("preferred_foot")
        .values_list("preferred_foot", flat=True)
        .distinct()
    )

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
            "selected_status": status,
            "selected_nationality": nationality,
            "min_skills": min_skills,
            "min_weak_foot": min_weak_foot,
            "selected_foot": preferred_foot,
            "rating_min": rating_min,
            "rating_max": rating_max,
            "selected_sort": sort,
            "free_only": free_only,
            "clubs": Team.objects.order_by("name"),
            "positions": [choice[0] for choice in Player.POSITION_CHOICES],
            "nationalities": nationalities,
            "preferred_feet": preferred_feet,
            "querystring": _querystring(request),
            "result_count": page.paginator.count,
            "total_player_count": total_player_count,
            **face_values,
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
                "squad_size": 0,
                "total_ovr": 0,
                "available_spaces": 0,
                "token_balance": token_balance_for_user(request.user),
            },
        )

    from mgl.market import detach_live_club_auction_players
    from mgl.player_state import roster_occupancy

    detach_live_club_auction_players()
    players = list(
        team.players.select_related("mgl_team").order_by(
            "position",
            "-overall",
            "name",
        )
    )

    total_ovr = sum(player.overall for player in players)
    squad_size = roster_occupancy(team)
    available_spaces = max(0, team.roster_limit - squad_size)
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
            status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE],
        )
    }
    for player in players:
        player.current_listing = listings.get(player.id)
        player.current_auction = live_auctions.get(player.id)

    listing_action = (request.GET.get("list") or "").strip().lower()
    listing_player = None
    if listing_action in {"transfer", "auction", "release"}:
        try:
            listing_id = int(request.GET.get("player") or 0)
        except (TypeError, ValueError):
            listing_id = 0
        listing_player = next((player for player in players if player.id == listing_id), None)
        if listing_player is None:
            messages.error(request, "You can only manage players who belong to your club.")
            return redirect("team_management")
        if listing_action != "release" and (listing_player.current_listing or listing_player.current_auction):
            messages.error(request, "This player is already listed.")
            return redirect("team_management")

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

    def _line(position):
        pos = (position or "").upper()
        if pos in gk:
            return "keepers"
        if pos in defence:
            return "defenders"
        if pos in midfield:
            return "midfielders"
        if pos in attack:
            return "attackers"
        return "other"

    for player in players:
        player.line = _line(player.position)
    line_counts = {
        "attackers": sum(1 for player in players if player.line == "attackers"),
        "midfielders": sum(1 for player in players if player.line == "midfielders"),
        "defenders": sum(1 for player in players if player.line == "defenders"),
        "keepers": sum(1 for player in players if player.line == "keepers"),
    }
    age_counts = {
        "u23": sum(1 for player in players if player.age is not None and player.age < 23),
        "prime": sum(
            1
            for player in players
            if player.age is not None and 23 <= player.age <= 29
        ),
        "veteran": sum(1 for player in players if player.age is not None and player.age >= 30),
    }
    squad_positions = sorted(
        {player.position for player in players if player.position}
    )

    return render(
        request,
        "mgl/team_management.html",
        {
            "team": team,
            "players": players,
            "squad_size": squad_size,
            "total_ovr": total_ovr,
            "available_spaces": available_spaces,
            "squad_groups": squad_groups,
            "line_counts": line_counts,
            "age_counts": age_counts,
            "squad_positions": squad_positions,
            "token_balance": token_balance_for_user(request.user),
            "auction_durations": AUCTION_DURATION_CHOICES,
            "market_listing_count": active_market_listing_count(team),
            "market_listing_limit": MAX_ACTIVE_CLUB_LISTINGS,
            "listing_action": listing_action if listing_player else "",
            "listing_player": listing_player,
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
    """Legacy identity editor. Club display edits go through Site Management."""
    team = get_object_or_404(Team, pk=team_id)
    return redirect("site_management_team_edit", team_id=team.id)


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
    close_club_spell_for_user(old_manager, team, reason="REMOVED")

    messages.success(
        request,
        f"{old_manager.username} has left {team.name}. "
        f"The club remains intact and the manager keeps their token balance.",
    )
    record_manager_departure(old_manager, team)
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
            close_club_spell_for_user(old_manager, team, reason="REASSIGNED")
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
    from mgl.player_state import roster_occupancy

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
            "available_spaces": max(0, team.roster_limit - roster_occupancy(team)),
        },
    )


def competition_page(request, slug):
    if slug in {"mls", "waiting-room"}:
        raise Http404("This competition is not an active MGL division.")
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
            name = league.public_name or name
    return render(
        request,
        "mgl/competition.html",
        {
            "competition_name": name,
            "competition_slug": slug,
            "league": league,
            "table": table,
            "is_live": bool(league),
            "competition_choices": live_competition_choices(),
            "selector_kind": "tables",
            "selector_label": "League tables",
        },
    )


HISTORY_RECORD_LABELS = (
    "League Winner",
    "Cup Winner",
    "Manager of the Season",
    "Team of the Season",
    "Golden Boot",
    "Top Assists",
)


def historical_tables(request):
    league = active_league()
    history_seasons = [
        {
            "number": number,
            "records": [
                {"label": label, "value": "To be recorded"}
                for label in HISTORY_RECORD_LABELS
            ],
        }
        for number in (1, 2)
    ]
    return render(
        request,
        "mgl/historical_tables.html",
        {
            "active_league": league,
            "table": build_league_table(league),
            "history_seasons": history_seasons,
        },
    )


def head_to_head(request):
    from mgl.site_cms import get_content

    return _feature_page(
        request,
        "Head to Head",
        "STATS & HISTORY",
        get_content("community.h2h_intro"),
    )


def compare_players(request):
    raise Http404("Player comparison has been removed.")


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
    from mgl.market import transfer_window_is_open

    transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .select_related("player", "from_team", "to_team", "seller", "buyer")
        .order_by("-created_at")
    )
    page = Paginator(transfers, 30).get_page(request.GET.get("page"))
    latest_result = (
        Fixture.objects.filter(is_released=True, status="COMPLETED")
        .select_related("home_team", "away_team")
        .prefetch_related("submission__team_stats")
        .order_by("-id")
        .first()
    )
    if latest_result:
        try:
            stats = {
                row.team_id: row.goals
                for row in latest_result.submission.team_stats.all()
            }
            latest_result.home_goals = stats.get(latest_result.home_team_id)
            latest_result.away_goals = stats.get(latest_result.away_team_id)
        except MatchSubmission.DoesNotExist:
            latest_result.home_goals = None
            latest_result.away_goals = None
    return render(
        request,
        "mgl/transfer_history.html",
        {
            "transfers": page,
            "page_obj": page,
            "window_open": transfer_window_is_open(),
            "completed_count": page.paginator.count,
            "latest_result": latest_result,
        },
    )


@login_required
def scouting(request):
    from mgl.scouting import (
        BRONZE,
        ELITE,
        GOLD,
        MAX_LEVEL,
        SILVER,
        SQUAD_FULL_MESSAGE,
        TIER_RANGES,
        complete_ready_assignments,
        cooldown_hours,
        dispatch_scout,
        format_hours,
        hours_saved,
        hours_saved_label,
        manager_scout_level,
        next_upgrade,
        open_scout_pack,
        release_scout_player,
        remaining_wait,
        scout_positions,
        scout_region_menu,
        scout_times,
        send_scout_to_team,
        upgrade_scout,
    )
    from mgl.market import club_for_user
    from mgl.regions import REGION_NATIONS, region_label
    from mgl.player_state import roster_occupancy

    manager = manager_for_user(request.user)
    if not manager:
        return redirect("manager_login")
    if request.method == "POST":
        action = request.POST.get("action")
        assignment_id = request.POST.get("assignment")
        assignment = None
        if assignment_id and str(assignment_id).isdigit():
            assignment = ScoutAssignment.objects.filter(
                pk=int(assignment_id),
                manager=manager,
            ).first()
        try:
            if action == "upgrade":
                profile, level, cost = upgrade_scout(manager)
                messages.success(
                    request,
                    f"Scouting network upgraded to Level {level} for {cost} tokens.",
                )
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
            elif action == "open_pack":
                opened = open_scout_pack(manager, assignment)
                return redirect(f"{reverse('scouting')}?pack={opened.id}")
            elif action == "send_to_team":
                report = send_scout_to_team(manager, assignment)
                messages.success(
                    request,
                    f"{report.player.name} joined {report.club.name}.",
                )
            elif action == "release_player":
                release_scout_player(manager, assignment)
                messages.success(request, "Player released back to the unreleased pool.")
            else:
                messages.error(request, "Unknown scouting action.")
        except ValueError as exc:
            messages.error(request, str(exc))
            if assignment_id:
                return redirect(f"{reverse('scouting')}?pack={assignment_id}")
        return redirect("scouting")

    _ready, notices = complete_ready_assignments(manager)
    for notice in notices:
        if notice == SQUAD_FULL_MESSAGE or "enough tokens" in notice.lower():
            messages.error(request, notice)
        elif notice.lower().startswith("no available") or "must manage a club" in notice.lower():
            messages.warning(request, notice)
        else:
            messages.success(request, notice)

    scout_level = manager_scout_level(manager)
    now = timezone.now()
    team = club_for_user(request.user)
    roster_count = roster_occupancy(team) if team else 0
    roster_full = bool(team) and roster_count >= 30
    panels = []
    for tier, label in ((BRONZE, "Bronze"), (SILVER, "Silver"), (GOLD, "Gold"), (ELITE, "Elite")):
        current = (
            ScoutAssignment.objects.filter(
                manager=manager,
                tier=tier,
                status__in=[
                    ScoutAssignment.PENDING,
                    ScoutAssignment.READY,
                    ScoutAssignment.OPENED,
                ],
            )
            .order_by("-started_at")
            .first()
        )
        wait = remaining_wait(current, now=now) if current else None
        ready = bool(current) and current.status in {
            ScoutAssignment.READY,
            ScoutAssignment.OPENED,
        }
        hours = cooldown_hours(tier, scout_level)
        panels.append(
            {
                "tier": tier,
                "label": label,
                "range": TIER_RANGES[tier],
                "hours": hours,
                "hours_label": format_hours(hours),
                "hours_short": f"{hours}h",
                "current": current,
                "remaining": wait,
                "ready": ready,
                "available": current is None and not roster_full,
            }
        )
    active = (
        ScoutAssignment.objects.filter(
            manager=manager,
            status__in=[
                ScoutAssignment.PENDING,
                ScoutAssignment.READY,
                ScoutAssignment.OPENED,
            ],
        )
        .select_related("player")
        .order_by("ready_at")
    )
    for item in active:
        item.region_display = region_label(item.region)
        item.remaining = remaining_wait(item, now=now)
    reports = manager.scout_reports.select_related("player", "player__mgl_team", "club")[:20]
    for report in reports:
        report.region_display = region_label(report.region)

    pack = None
    pack_raw = request.GET.get("pack", "").strip()
    if pack_raw.isdigit():
        pack = ScoutAssignment.objects.filter(
            pk=int(pack_raw),
            manager=manager,
            status__in=[ScoutAssignment.READY, ScoutAssignment.OPENED],
        ).select_related("player").first()
        if pack:
            pack.region_display = region_label(pack.region)

    region_guide = [
        (group, [(key, label, sorted(REGION_NATIONS.get(key, ()))) for key, label in items])
        for group, items in scout_region_menu()
        if group
    ]

    return render(
        request,
        "mgl/scouting.html",
        {
            "manager": manager,
            "token_balance": token_balance_for_user(request.user),
            "scout_level": scout_level,
            "max_level": MAX_LEVEL,
            "hours_saved": hours_saved(scout_level),
            "hours_saved_label": hours_saved_label(scout_level),
            "current_times": scout_times(scout_level),
            "upgrade": next_upgrade(scout_level),
            "panels": panels,
            "region_menu": scout_region_menu(),
            "region_guide": region_guide,
            "positions": scout_positions(),
            "reports": reports,
            "active_scouts": active,
            "pack": pack,
            "club": team,
            "roster_count": roster_count,
            "roster_full": roster_full,
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
            request.POST.get("starting_bid"),
        )
        messages.success(request, f"{player.name} is now in auction.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("team_management")


@login_required
@require_POST
def auction_free_agent(request, player_id):
    if getattr(request.user, "role", None) not in [User.OWNER, User.ADMIN]:
        return HttpResponseForbidden(
            "Only an owner or admin can release an unassigned player to auction."
        )
    player = get_object_or_404(Player, pk=player_id)
    try:
        auction = create_free_agent_auction(
            player,
            request.user,
            request.POST.get("duration"),
            request.POST.get("starting_bid"),
        )
        messages.success(
            request,
            f"{player.name} is live in auction until {auction.ends_at}.",
        )
    except PermissionDenied as exc:
        return HttpResponseForbidden(str(exc))
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(request.POST.get("next") or "unassigned_players")


def youth_academy(request):
    return _feature_page(
        request,
        "Youth Academy",
        "MARKET",
        "Youth Academy is not live yet. The FC26 player pool already includes every registered player available to MGL.",
    )
