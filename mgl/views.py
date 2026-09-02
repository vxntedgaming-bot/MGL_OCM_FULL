from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from leagues.models import League
from leagues.services import active_league, ensure_premier_league
from managers.models import ManagerApplication
from mgl.standings import build_live_league_table
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
from .nav import COMPETITIONS, CUP_TABS, LIVE_COMPETITION_SLUGS, live_competition_choices
from .permissions import approved_manager, career_required, is_owner_or_admin, owner_admin_required
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
from .ufl_settings import allow_manager_auctions
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
        post.news_player = None
        post.is_press = post.category == NewsPost.PRESS
        post.logo_kind = "single"
        details = getattr(post, "details", None) or {}
        player_id = details.get("player_id") or details.get("player")
        if player_id and str(player_id).isdigit():
            from players.models import Player as NewsPlayer

            post.news_player = NewsPlayer.objects.filter(pk=int(player_id)).first()
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


def mgl_index(request):
    """
    /mgl/ is the manager area entry point, not a second homepage.
    """
    if request.user.is_authenticated:
        return redirect("manager_hub")
    return redirect("home")


def home(request):
    from mgl.season1 import UFL_STARTER_CLUB_TOTAL
    from mgl.season_history import current_season_number

    if approved_manager(request.user):
        return redirect("manager_hub")

    league = active_league()
    upcoming_qs = (
        Fixture.objects.filter(
            is_released=True,
            status="SCHEDULED",
        )
        .select_related(
            "home_team",
            "away_team",
            "league",
        )
        .order_by(F("scheduled_at").asc(nulls_last=True), "matchweek", "id")
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

    upcoming = list(upcoming_qs[:5])
    next_fixture = upcoming[0] if upcoming else None

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
    table = build_live_league_table(league)
    club_qs = Team.objects.filter(league__is_active=True)
    recent_transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")[:8]
    )
    matches_played_qs = Fixture.objects.filter(
        is_released=True,
        status="COMPLETED",
    )

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
                "title": row.player.name if row.player_id else "Balance movement",
                "detail": f"{frm} → {to} · {row.amount}",
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

    from auctions.models import PlayerAuction

    live_home_auctions = (
        PlayerAuction.objects.filter(status=PlayerAuction.LIVE)
        .select_related("player", "origin_team", "listed_by_manager")
        .order_by("ends_at")[:4]
    )
    featured_players = list(top_scorers)

    jobs_url = reverse("job_centre")
    apply_club_url = jobs_url
    join_mgl_url = reverse("manager_register")

    return render(
        request,
        "core/home.html",
        {
            "upcoming": upcoming,
            "next_fixture": next_fixture,
            "news": news,
            "recent_results": recent_results,
            "top_scorers": top_scorers,
            "league_count": League.objects.filter(is_active=True).count(),
            "club_count": club_qs.count(),
            "configured_club_total": UFL_STARTER_CLUB_TOTAL,
            "player_count": Player.objects.count(),
            "manager_count": club_qs.filter(manager__isnull=False).count(),
            "matches_played": matches_played_qs.count(),
            "current_season_number": current_season_number(),
            "unassigned_count": unassigned_players().count(),
            "free_agent_count": free_agent_qs().count(),
            "live_listing_count": PlayerListing.objects.filter(
                status=PlayerListing.LIVE
            ).count(),
            "recent_transfers": recent_transfers,
            "live_home_auctions": live_home_auctions,
            "featured_players": featured_players,
            "activity": activity,
            "active_league": league,
            "table": table,
            "apply_club_url": apply_club_url,
            "join_mgl_url": join_mgl_url,
        },
    )


def player_profile(request, player_id):
    player = get_object_or_404(
        Player.objects.select_related("mgl_team", "mgl_team__league", "mgl_team__manager"),
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

    from auctions.models import PlayerAuction
    from mgl.market import transfer_offer_context_for
    from mgl.models import PlayerListing
    from mgl.player_state import LIVE_AUCTION_STATUSES, LIVE_LISTING_STATUSES
    from players.display import playstyles_for_player, player_age

    live_listing = (
        PlayerListing.objects.filter(player=player, status__in=LIVE_LISTING_STATUSES)
        .select_related("team", "seller")
        .first()
    )
    live_auction = (
        PlayerAuction.objects.filter(player=player, status__in=LIVE_AUCTION_STATUSES)
        .select_related("origin_team")
        .first()
    )
    playstyles, playstyle_plus = playstyles_for_player(player)
    club_manager = None
    if player.mgl_team_id and getattr(player.mgl_team, "manager_id", None):
        club_manager = manager_for_user(player.mgl_team.manager)

    return render(
        request,
        "mgl/player_profile.html",
        {
            "player": player,
            "player_age_value": player_age(player),
            "playstyles": playstyles,
            "playstyle_plus": playstyle_plus,
            "live_listing": live_listing,
            "live_auction": live_auction,
            "club_manager": club_manager,
            "ownership_history": ownership_history,
            "totw_selections": totw_selections,
            "auction_requests": auction_requests,
            "attribute_groups": attribute_groups_for_player(player),
            "recent_results": [],
            **transfer_offer_context_for(request.user, player),
        },
    )


def _notify_next(request):
    nxt = (request.POST.get("next") or request.META.get("HTTP_REFERER") or "").strip()
    if nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return reverse("manager_hub")


@career_required
def manager_notifications(request):
    manager = manager_for_user(request.user)
    is_control = getattr(request.user, "role", None) in ("OWNER", "ADMIN")
    if not manager and not is_control:
        messages.error(
            request,
            "You do not have a manager account.",
        )
        return redirect("manager_login")

    from mgl.notifications import NOTIFICATION_CATEGORIES, inbox_for_user

    selected_category = (request.GET.get("category") or "").strip()
    selected_tab = (request.GET.get("tab") or "").strip().lower()
    category_for_inbox = selected_category
    tab_map = {
        "transfers": "Transfers",
        "fixtures": "Matches",
        "club": "Club",
        "manager": "Career",
        "system": "Admin",
    }
    if not category_for_inbox and selected_tab in tab_map:
        category_for_inbox = tab_map[selected_tab]
    inbox = inbox_for_user(request.user, category=category_for_inbox)
    if selected_tab == "unread":
        inbox = [item for item in inbox if getattr(item, "is_unread", False)]
    for item in inbox:
        label = (getattr(item, "status_label", "") or "").upper()
        ntype = (getattr(item, "notification_type", "") or "").upper()
        if label in {"ACCEPTED", "APPROVED", "COMPLETED"}:
            item.tone = "success"
        elif label in {"REJECTED", "DECLINED", "FAILED"}:
            item.tone = "danger"
        elif label == "PENDING":
            item.tone = "warning"
        elif "TRANSFER" in ntype:
            item.tone = "info"
        elif "ADMIN" in ntype:
            item.tone = "special"
        else:
            item.tone = "info"
    return render(
        request,
        "mgl/notifications.html",
        {
            "manager": manager,
            "notifications": inbox,
            "notification_categories": NOTIFICATION_CATEGORIES,
            "selected_category": selected_category,
            "selected_tab": selected_tab,
            "inbox_tabs": (
                ("", "ALL"),
                ("unread", "UNREAD"),
                ("transfers", "TRANSFERS"),
                ("fixtures", "FIXTURES"),
                ("club", "CLUB"),
                ("manager", "MANAGER"),
                ("system", "SYSTEM"),
            ),
        },
    )


@login_required
def manager_verification(request):
    from mgl.verification import verification_snapshot

    snapshot = verification_snapshot(request.user)
    return render(
        request,
        "mgl/manager_verification.html",
        {
            "verification": snapshot,
            "manager": snapshot.get("identity"),
            "team": snapshot.get("club"),
        },
    )


@career_required
def notification_panel(request):
    manager = manager_for_user(request.user)
    is_control = getattr(request.user, "role", None) in ("OWNER", "ADMIN")
    if not manager and not is_control:
        return render(request, "mgl/includes/notify_panel.html", {"notifications": []})
    from mgl.notifications import inbox_for_user, unread_count_for_user

    return render(
        request,
        "mgl/includes/notify_panel.html",
        {
            "notifications": inbox_for_user(request.user)[:12],
            "mgl_unread_notification_count": unread_count_for_user(request.user, tick=False),
        },
    )


def unread_count_safe(user):
    from mgl.notifications import unread_count_for_user

    return unread_count_for_user(user)


@career_required
@require_POST
def notification_mark_all_read(request):
    from mgl.notifications import mark_inbox_read

    mark_inbox_read(request.user)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        from django.http import JsonResponse

        return JsonResponse({"ok": True, "unread": 0})
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "manager_hub")


@career_required
@require_POST
def notification_mark_read(request, notification_id):
    from mgl.notifications import mark_notification_read, unread_count_for_user

    mark_notification_read(request.user, notification_id)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        from django.http import JsonResponse

        return JsonResponse({"ok": True, "unread": unread_count_for_user(request.user)})
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "manager_hub")


@career_required
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
        return redirect(_notify_next(request))

    accept = (request.POST.get("action") or "").strip().lower() == "accept"
    reject = (request.POST.get("action") or "").strip().lower() == "reject"
    if not accept and not reject:
        messages.error(request, "Choose Accept or Reject.")
        return redirect(_notify_next(request))
    try:
        respond_to_inbox_notification(request.user, notification, accept)
    except PermissionDenied:
        messages.error(request, "You are not allowed to action this notification.")
        return redirect(_notify_next(request))
    except InboxActionError as exc:
        messages.error(request, str(exc))
        return redirect(_notify_next(request))
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(_notify_next(request))
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
    return redirect(_notify_next(request))


@career_required
def transfer_requests(request):
    from mgl.market import close_expired_auctions
    from mgl.transfer_requests import completed_transfers_for

    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to review transfer requests.")
        return redirect("manager_hub")
    club = club_for_user(request.user)
    if not club:
        messages.error(request, "You need a club before you can manage transfer requests.")
        return redirect("manager_hub")

    close_expired_auctions()
    from mgl.transfer_requests import incoming_transfer_requests, outgoing_transfer_requests

    incoming = incoming_transfer_requests(club)
    outgoing = outgoing_transfer_requests(manager)
    completed = completed_transfers_for(club)
    return render(
        request,
        "mgl/transfer_requests.html",
        {
            "manager": manager,
            "club": club,
            "incoming_offers": incoming,
            "outgoing_offers": outgoing,
            "completed_transfers": completed,
        },
    )


@career_required
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
    counter = raw_action == "counter"
    withdraw = raw_action == "withdraw"
    if not accept and not reject and not counter and not withdraw:
        messages.error(request, "Choose Accept, Reject, Counter or Withdraw.")
        return redirect("transfer_requests")
    try:
        if counter:
            from mgl.market import counter_transfer_offer

            counter_transfer_offer(
                listing,
                request.user,
                request.POST.get("asking_price") or listing.asking_price,
                message=request.POST.get("message", ""),
            )
            messages.success(request, "Counter-offer sent. Negotiation history was preserved.")
            return redirect("transfer_requests")
        if withdraw:
            from mgl.market import withdraw_transfer_offer

            if listing.reserved_buyer_id != manager.id:
                raise PermissionDenied("You can only withdraw your own offer.")
            withdraw_transfer_offer(listing, manager)
            messages.success(request, "Offer withdrawn. Ownership did not change.")
            return redirect("transfer_requests")
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


@career_required
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
        table = build_live_league_table(team.league)
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

    from mgl.player_state import roster_occupancy
    from mgl.ufl_settings import effective_roster_limit

    roster_count = roster_occupancy(team) if team else 0
    roster_limit = effective_roster_limit(team) if team else 30
    if team and squad:
        listed_ids = set(
            PlayerListing.objects.filter(
                team=team,
                player_id__in=[player.id for player in squad],
                status__in=[PlayerListing.LIVE, PlayerListing.OFFER, PlayerListing.PENDING],
            ).values_list("player_id", flat=True)
        )
        squad = [player for player in squad if player.id not in listed_ids][:12]
    else:
        squad = squad[:12]
    token_balance = token_balance_for_user(request.user)
    from mgl.transfer_requests import incoming_offer_count

    incoming_transfer_count = incoming_offer_count(team)

    from auctions.models import PlayerAuction
    from mgl.models import ScoutAssignment
    from mgl.ufl_settings import press_per_24h
    from django.utils import timezone
    from datetime import timedelta

    next_fixture = outstanding[0] if outstanding else None
    active_scout = (
        ScoutAssignment.objects.filter(
            manager=manager,
            status__in=[
                ScoutAssignment.PENDING,
                ScoutAssignment.READY,
                ScoutAssignment.OPENED,
            ],
        )
            .select_related("player")
            .order_by("-started_at")
            .first()
    )
    my_live_auctions = list(
        PlayerAuction.objects.filter(
            listed_by_manager=manager,
            status=PlayerAuction.LIVE,
        )
        .select_related("player")
        .order_by("ends_at")[:3]
    )
    press_used = PressConference.objects.filter(
        manager=request.user,
        created_at__gte=timezone.now() - timedelta(hours=24),
    ).count()
    press_remaining = max(0, press_per_24h() - press_used)

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
            "roster_limit": roster_limit,
            "token_balance": token_balance,
            "incoming_transfer_count": incoming_transfer_count,
            "active_league": getattr(team, "league", None) or active_league(),
            "outstanding": outstanding,
            "outstanding_count": len(outstanding),
            "recent_results": recent_results,
            "top_scorers": top_scorers,
            "top_assists": top_assists,
            "squad": squad,
            "league_position": league_position,
            "league_size": league_size,
            "standings_row": standings_row,
            "form": form,
            "table": table[:8],
            "confirm_resign": bool(team) and request.GET.get("resign") == "1",
            "next_fixture": next_fixture,
            "active_scout": active_scout,
            "my_live_auctions": my_live_auctions,
            "press_remaining": press_remaining,
        },
    )


@career_required
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


@career_required
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
        outfield = [
            row
            for row in players
            if row not in defenders and row not in keepers
        ]
        side = {
            "team": team,
            "prefix": prefix,
            "label": "HOME" if prefix == "home" else "AWAY",
            "players": players,
            "defenders": defenders,
            "keepers": keepers,
            "outfield": outfield,
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


@career_required
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


@career_required
@require_POST
def release_my_player(request, player_id):
    from .services import request_player_release

    manager = approved_manager(request.user)
    if manager is None:
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
        request_player_release(player, team, manager)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("team_management")

    messages.success(
        request,
        f"{player.name} has been released and is now a genuine UFL Free Agent. Signing cost: 0.",
    )
    return redirect("team_management")


FREE_AGENT_POSITION_GROUPS = {
    "DEFENDERS": ("CB", "LB", "RB", "LWB", "RWB"),
    "MIDFIELDERS": ("CDM", "CM", "CAM", "LM", "RM"),
    "ATTACKERS": ("LW", "RW", "ST", "CF"),
}


@career_required
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


@career_required
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
            f"{player.name} signed for 0.",
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


@career_required
def manager_profile(request):
    manager = manager_for_user(request.user)

    if not manager:
        return redirect("manager_login")

    if request.method == "POST" and request.POST.get("action") == "link_discord":
        raw = (request.POST.get("discord_id") or "").strip()
        if raw and not raw.isdigit():
            messages.error(request, "Discord User ID must be the numeric ID, not a username.")
            return redirect("manager_profile")
        if raw:
            taken = User.objects.filter(discord_id=raw).exclude(pk=request.user.pk).exists()
            if taken:
                messages.error(request, "That Discord User ID is already linked to another UFL account.")
                return redirect("manager_profile")
        request.user.discord_id = raw or None
        request.user.save(update_fields=["discord_id"])
        messages.success(
            request,
            "Discord account linked." if raw else "Discord account unlinked.",
        )
        return redirect("manager_profile")

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
            "is_own_profile": True,
        },
    )


@career_required
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
        f"You have resigned from {team.name}. Your personal balance is unchanged.",
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


@career_required
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
        players = players.filter(mgl_team__isnull=True, released_at__isnull=False)
    elif club == "UNASSIGNED":
        players = players.filter(mgl_team__isnull=True, released_at__isnull=True).exclude(
            id__in=live_auction_player_ids()
        )
    elif club.isdigit():
        players = players.filter(mgl_team_id=int(club))

    if status == "CLUB" or status == CLUB_PLAYER.replace(" ", "_"):
        players = players.filter(mgl_team__isnull=False)
    elif status in {"FREE_AGENT", "FA", FREE_AGENT.replace(" ", "_")}:
        players = players.filter(mgl_team__isnull=True, released_at__isnull=False)
    elif status == UNASSIGNED:
        players = players.filter(mgl_team__isnull=True, released_at__isnull=True).exclude(
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
            "ovr_groups": (
                ("48–60", "48", "60"),
                ("60–70", "60", "70"),
                ("70–80", "70", "80"),
                ("80–93", "80", "93"),
            ),
            **face_values,
        },
    )


@career_required
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


def _recent_results_for_team(team, limit=5):
    if not team:
        return []
    completed = list(
        Fixture.objects.filter(
            Q(home_team=team) | Q(away_team=team),
            status="COMPLETED",
        )
        .select_related("home_team", "away_team", "league")
        .prefetch_related("submission__team_stats")
        .order_by("-matchweek", "-id")[:limit]
    )
    results = []
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
            fixture.away_team_id if fixture.home_team_id == team.id else fixture.home_team_id
        )
        opp = stats.get(opp_id)
        if own is None or opp is None:
            outcome = "—"
        elif own > opp:
            outcome = "W"
        elif own < opp:
            outcome = "L"
        else:
            outcome = "D"
        fixture.home_goals = stats.get(fixture.home_team_id)
        fixture.away_goals = stats.get(fixture.away_team_id)
        fixture.outcome = outcome
        fixture.opponent = (
            fixture.away_team if fixture.home_team_id == team.id else fixture.home_team
        )
        fixture.venue = "H" if fixture.home_team_id == team.id else "A"
        results.append(fixture)
    return results


@career_required
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

    from mgl.ufl_settings import effective_roster_limit

    total_ovr = sum(player.overall for player in players)
    squad_size = roster_occupancy(team)
    roster_limit = effective_roster_limit(team)
    available_spaces = max(0, roster_limit - squad_size)
    listings = {
        listing.player_id: listing
        for listing in PlayerListing.objects.filter(
            team=team,
            status__in=[PlayerListing.PENDING, PlayerListing.LIVE, PlayerListing.OFFER],
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
    from players.display import player_age as resolve_age

    ages = [resolve_age(player) for player in players]
    age_counts = {
        "u23": sum(1 for age in ages if age is not None and age < 23),
        "prime": sum(1 for age in ages if age is not None and 23 <= age <= 29),
        "veteran": sum(1 for age in ages if age is not None and age >= 30),
    }
    squad_positions = sorted(
        {player.position for player in players if player.position}
    )

    listed_players = [player for player in players if player.current_listing]
    active_players = [player for player in players if not player.current_listing]

    return render(
        request,
        "mgl/team_management.html",
        {
            "team": team,
            "players": active_players,
            "listed_players": listed_players,
            "active_count": len(active_players),
            "squad_size": squad_size,
            "roster_limit": roster_limit,
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
            "allow_manager_auctions": allow_manager_auctions(),
            "listing_action": listing_action if listing_player else "",
            "listing_player": listing_player,
            "recent_results": _recent_results_for_team(team),
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
        f"The club remains intact and the manager keeps their balance.",
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
    from mgl.ufl_settings import effective_roster_limit

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
            "available_spaces": max(0, effective_roster_limit(team) - roster_occupancy(team)),
        },
    )


def competition_page(request, slug):
    if slug in {"mls", "waiting-room"}:
        raise Http404("This competition is not an active UFL division.")
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
            table = build_live_league_table(league)
            name = league.public_name or name
    coming_soon = slug in {
        "cups",
        "phantom-cup",
        "champions-league",
        "europa-league",
        "conference-league",
    }
    cup_tabs = CUP_TABS.get(slug, ())
    allowed_tabs = {item[0] for item in cup_tabs} or {
        "overview",
        "groups",
        "fixtures",
        "bracket",
        "table",
        "clubs",
        "stats",
        "history",
    }
    cup_tab = (request.GET.get("tab") or "overview").strip().lower()
    if cup_tab not in allowed_tabs:
        cup_tab = "overview"
    cup_catalog = (
        {
            "slug": "champions-league",
            "name": COMPETITIONS["champions-league"],
            "description": "16 teams. 4 groups of 4. 8 teams qualify for the knockout stages.",
            "status": "published",
            "status_label": "UFL CUP",
            "format": "Groups + knockout",
            "team_count": 16,
            "winner": None,
            "season": None,
            "action_label": "VIEW COMPETITION →",
        },
        {
            "slug": "europa-league",
            "name": COMPETITIONS["europa-league"],
            "description": "8 teams. 2 groups of 4. 4 teams qualify for the knockout stages.",
            "status": "published",
            "status_label": "UFL CUP",
            "format": "Groups + knockout",
            "team_count": 8,
            "winner": None,
            "season": None,
            "action_label": "VIEW COMPETITION →",
        },
        {
            "slug": "conference-league",
            "name": COMPETITIONS["conference-league"],
            "description": "8 teams. 2 groups of 4. 4 teams qualify for the knockout stages.",
            "status": "published",
            "status_label": "UFL CUP",
            "format": "Groups + knockout",
            "team_count": 8,
            "winner": None,
            "season": None,
            "action_label": "VIEW COMPETITION →",
        },
        {
            "slug": "phantom-cup",
            "name": COMPETITIONS["phantom-cup"],
            "description": "Knockout stages. Draws and results appear when the office starts the cup.",
            "status": "published",
            "status_label": "UFL CUP",
            "format": "Knockout",
            "team_count": None,
            "winner": None,
            "season": None,
            "action_label": "VIEW COMPETITION →",
        },
    )
    league_fixtures = []
    top_scorers = []
    top_assists = []
    if league:
        from mgl.fixture_display import fixture_score
        from players.models import Player as LeaguePlayer

        league_fixtures = list(
            Fixture.objects.filter(league=league, is_released=True)
            .select_related("home_team", "away_team", "league")
            .prefetch_related("submission__team_stats")
            .order_by("matchweek", "scheduled_at", "id")
        )
        for row in league_fixtures:
            home_goals, away_goals = fixture_score(row)
            row.public_home_goals = home_goals
            row.public_away_goals = away_goals
        league_players = LeaguePlayer.objects.filter(
            mgl_team__league=league
        ).select_related("mgl_team")
        top_scorers = list(
            league_players.filter(goals__gt=0).order_by("-goals", "name")[:8]
        )
        top_assists = list(
            league_players.filter(assists__gt=0).order_by("-assists", "name")[:8]
        )
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
            "coming_soon": coming_soon,
            "cup_tab": cup_tab,
            "cup_tabs": cup_tabs,
            "cup_copy": {
                "phantom-cup": {
                    "description": "Knockout stages. Draws, fixtures and results appear when the office starts the cup.",
                    "meta": ["KNOCKOUT"],
                    "has_groups": False,
                },
                "champions-league": {
                    "description": "16 teams. 4 groups of 4. 8 teams qualify for the knockout stages.",
                    "meta": ["16 TEAMS", "4 GROUPS", "KNOCKOUT"],
                    "has_groups": True,
                },
                "europa-league": {
                    "description": "8 teams. 2 groups of 4. 4 teams qualify for the knockout stages.",
                    "meta": ["8 TEAMS", "2 GROUPS", "KNOCKOUT"],
                    "has_groups": True,
                },
                "conference-league": {
                    "description": "8 teams. 2 groups of 4. 4 teams qualify for the knockout stages.",
                    "meta": ["8 TEAMS", "2 GROUPS", "KNOCKOUT"],
                    "has_groups": True,
                },
            }.get(slug, {}),
            "league_fixtures": league_fixtures,
            "top_scorers": top_scorers,
            "top_assists": top_assists,
            "official_cups": cup_catalog,
            "live_cups": [cup for cup in cup_catalog if cup["status"] == "live"],
            "won_cups": [cup for cup in cup_catalog if cup["status"] == "complete"],
            "upcoming_cups": [cup for cup in cup_catalog if cup["status"] == "upcoming"],
        },
    )


def historical_tables(request):
    from mgl.permissions import is_owner_or_admin
    from mgl.season_history import page_context

    selected = request.GET.get("season")
    show_full = request.GET.get("table") == "full"
    context = page_context(selected, show_full_table=show_full)
    context["can_manage_seasons"] = is_owner_or_admin(request.user)
    context["is_hall_of_fame"] = True
    return render(request, "mgl/historical_tables.html", context)


def hall_of_fame(request):
    return historical_tables(request)


@career_required
def youth_academy(request):
    return render(
        request,
        "mgl/youth_academy.html",
        {
            "page_title": "Youth Academy — UFL",
            "section": "MARKET",
            "section_url_name": "transfer_market",
            "heading": "YOUTH ACADEMY",
            "kicker": "COMING SOON",
            "body": "The UFL Youth Academy is not open yet. No academy players or results are generated here. Use Scouting and Recruitment Drive for the current player pipeline.",
        },
    )


def fixture_detail(request, fixture_id):
    fixture = get_object_or_404(
        Fixture.objects.select_related(
            "home_team",
            "away_team",
            "home_team__manager",
            "away_team__manager",
            "league",
        ),
        pk=fixture_id,
        is_released=True,
    )
    submission = (
        MatchSubmission.objects.filter(fixture=fixture)
        .prefetch_related(
            "team_stats__goal_events__player",
            "team_stats__assist_events__player",
            "team_stats__defender_ratings__player",
            "team_stats__gk_saves__player",
            "team_stats__player_ratings__player",
        )
        .first()
    )
    home_stats = None
    away_stats = None
    official = False
    if submission:
        official = submission.status == ApprovalStatus.APPROVED
        by_team = {row.team_id: row for row in submission.team_stats.all()}
        home_stats = by_team.get(fixture.home_team_id)
        away_stats = by_team.get(fixture.away_team_id)
    can_submit = False
    if request.user.is_authenticated and approved_manager(request.user):
        involved = request.user.id in {
            fixture.home_team.manager_id,
            fixture.away_team.manager_id,
        }
        can_submit = involved and fixture.status == "SCHEDULED" and (
            submission is None or submission.status != ApprovalStatus.APPROVED
        )
    return render(
        request,
        "mgl/fixture_detail.html",
        {
            "fixture": fixture,
            "submission": submission,
            "home_stats": home_stats,
            "away_stats": away_stats,
            "official": official,
            "can_submit": can_submit,
        },
    )


def manager_public_profile(request, username):
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    profile_user = get_object_or_404(UserModel, username=username)
    manager = manager_for_user(profile_user)
    if not manager or manager.status != ManagerApplication.APPROVED:
        raise Http404("Manager not found.")
    if request.user.is_authenticated and request.user.username == username:
        return redirect("manager_profile")
    career = getattr(manager, "career", None)
    trophies = manager.trophies.all() if manager else []
    team = Team.objects.filter(manager=profile_user).select_related("league").first()
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
            "rewards": [],
            "team": team,
            "token_balance": None,
            "played": played,
            "win_rate": win_rate,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "confirm_resign": False,
            "is_own_profile": False,
        },
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


def public_completed_transfers(request):
    from mgl.market import close_expired_auctions, transfer_window_is_open
    from mgl.transfer_requests import (
        completed_transfer_queryset,
        decorate_completed_transfer,
    )

    close_expired_auctions()
    transfers = completed_transfer_queryset()
    page = Paginator(transfers, 30).get_page(request.GET.get("page"))
    for row in page.object_list:
        decorate_completed_transfer(row)
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
            "is_personal": False,
        },
    )


@career_required
def transfer_history(request):
    from mgl.market import close_expired_auctions, transfer_window_is_open
    from mgl.transfer_requests import (
        completed_transfers_for,
        incoming_transfer_requests,
        outgoing_transfer_requests,
    )

    close_expired_auctions()
    club = club_for_user(request.user)
    manager = approved_manager(request.user)
    incoming = incoming_transfer_requests(club) if club else []
    outgoing = outgoing_transfer_requests(manager) if manager else []
    completed = completed_transfers_for(club) if club else []
    return render(
        request,
        "mgl/manager_transfer_history.html",
        {
            "club": club,
            "incoming_offers": incoming,
            "outgoing_offers": outgoing,
            "completed_transfers": completed,
            "window_open": transfer_window_is_open(),
        },
    )


@career_required
def recruitment_drive(request):
    from mgl.recruitment import (
        pack_choices,
        pending_opening_for,
        players_for_opening,
    )

    manager = approved_manager(request.user)
    team = club_for_user(request.user)
    opening = pending_opening_for(manager)
    return render(
        request,
        "mgl/recruitment_drive.html",
        {
            "manager": manager,
            "team": team,
            "packs": pack_choices(manager),
            "opening": opening,
            "candidates": players_for_opening(opening),
            "token_balance": token_balance_for_user(request.user),
            "select_count": (
                opening.pack.select_count
                if opening and opening.pack_id
                else 1
            ),
            "result_count": (
                len(opening.player_ids)
                if opening
                else 3
            ),
        },
    )


@career_required
@require_POST
def open_recruitment_pack(request):
    from mgl.recruitment import open_recruitment_pack as open_pack

    try:
        opening = open_pack(request.user, request.POST.get("pack_code"))
        count = len(opening.player_ids)
        select = opening.pack.select_count if opening.pack_id else 1
        messages.success(
            request,
            f"Pack opened. Choose {select} of the {count} players.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("recruitment_drive")


@career_required
@require_POST
def choose_recruitment_player(request, opening_id):
    from mgl.recruitment import choose_recruitment_player as choose_player

    try:
        opening = choose_player(
            request.user, opening_id, request.POST.get("player_id")
        )
        if opening.chosen_player_id:
            messages.success(
                request,
                f"{opening.chosen_player.name} has joined your club.",
            )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("recruitment_drive")


@career_required
def scouting(request):
    from mgl.scouting import (
        BRONZE,
        ELITE,
        GOLD,
        MAX_LEVEL,
        SILVER,
        SQUAD_FULL_MESSAGE,
        TIER_RANGES,
        add_to_watchlist,
        choose_scout_player,
        complete_ready_assignments,
        cooldown_hours,
        dispatch_scout,
        file_scout_report,
        format_hours,
        get_or_create_scout_profile,
        hours_saved,
        hours_saved_label,
        manager_scout_level,
        next_upgrade,
        open_scout_pack,
        players_for_assignment,
        remaining_wait,
        scout_availability_label,
        scout_positions,
        scout_region_menu,
        scout_times,
        send_scout_to_team,
        upgrade_scout,
        watchlist_for,
    )
    from mgl.market import club_for_user
    from mgl.permissions import is_owner_or_admin
    from mgl.regions import REGION_NATIONS, country_menu, region_label
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
                    f"Scouting network upgraded to Level {level} for {cost}.",
                )
            elif action == "dispatch":
                assignment = dispatch_scout(
                    manager,
                    request.POST.get("tier"),
                    request.POST.get("region", ""),
                    request.POST.get("position", ""),
                    country=request.POST.get("country", ""),
                )
                messages.success(
                    request,
                    f"{assignment.get_tier_display()} scout dispatched. Report ready at {assignment.ready_at}.",
                )
            elif action == "choose_scout":
                chosen = choose_scout_player(
                    manager,
                    assignment.id if assignment else request.POST.get("assignment"),
                    request.POST.get("player_id"),
                )
                if chosen.player_id:
                    messages.success(
                        request,
                        f"{chosen.player.name} has joined your club.",
                    )
            elif action == "open_pack":
                opened = open_scout_pack(manager, assignment)
                return redirect(f"{reverse('scouting')}?pack={opened.id}")
            elif action == "send_to_team":
                if not is_owner_or_admin(request.user):
                    raise ValueError("Scouting discovers players. It does not acquire them.")
                report = send_scout_to_team(manager, assignment, actor=request.user)
                messages.success(
                    request,
                    f"League office assigned {report.player.name} to {report.club.name}.",
                )
            elif action in {"release_player", "file_report"}:
                report = file_scout_report(manager, assignment)
                messages.success(
                    request,
                    f"Scout report filed for {report.player.name}. Ownership unchanged.",
                )
            elif action == "watchlist":
                if assignment and assignment.player_id:
                    if assignment.status == ScoutAssignment.OPENED:
                        report = file_scout_report(manager, assignment, watchlist=True)
                        messages.success(
                            request,
                            f"{report.player.name} added to your watchlist. Scout report filed. Scouting does not transfer ownership.",
                        )
                    else:
                        add_to_watchlist(manager, assignment.player)
                        messages.success(
                            request,
                            f"{assignment.player.name} added to your private scouting watchlist. Scouting does not transfer ownership.",
                        )
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
    from mgl.ufl_settings import effective_roster_limit

    roster_count = roster_occupancy(team) if team else 0
    roster_full = bool(team) and roster_count >= effective_roster_limit(team)
    scout_busy = ScoutAssignment.objects.filter(
        manager=manager,
        status__in=[
            ScoutAssignment.PENDING,
            ScoutAssignment.READY,
            ScoutAssignment.OPENED,
        ],
    ).exists()
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
                "available": current is None and team is not None and not scout_busy,
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
            pack.availability_label = (
                scout_availability_label(pack.player) if pack.player_id else ""
            )

    ready_assignment = (
        ScoutAssignment.objects.filter(manager=manager, status=ScoutAssignment.READY)
        .order_by("-ready_at", "-id")
        .first()
    )
    if pack and pack.status == ScoutAssignment.READY:
        ready_assignment = pack
    scout_candidates = players_for_assignment(ready_assignment) if ready_assignment else []

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
            "country_menu": country_menu(),
            "region_guide": region_guide,
            "positions": scout_positions(),
            "reports": reports,
            "active_scouts": active,
            "scout_busy": scout_busy,
            "pack": pack,
            "ready_assignment": ready_assignment,
            "scout_candidates": scout_candidates,
            "club": team,
            "roster_count": roster_count,
            "roster_full": roster_full,
            "roster_limit": effective_roster_limit(team) if team else 0,
            "watchlist": [
                {
                    "row": row,
                    "availability": scout_availability_label(row.player),
                }
                for row in watchlist_for(manager)
            ],
            "scout_profile": get_or_create_scout_profile(manager),
            "can_admin_assign_scout": is_owner_or_admin(request.user),
        },
    )


@career_required
@require_POST
def list_player_for_auction(request, player_id):
    from mgl.ufl_settings import allow_manager_auctions

    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to auction a player.")
        return redirect("team_management")
    if not allow_manager_auctions():
        messages.error(
            request,
            "Only the league office can create auctions. List the player on the Transfer Market instead.",
        )
        return redirect("team_management")
    player = get_object_or_404(Player, pk=player_id)
    try:
        create_manager_auction(
            player,
            manager,
            request.POST.get("duration"),
            request.POST.get("starting_bid") or 1,
        )
        messages.success(
            request,
            f"{player.name} is now in auction. Listing fee 0.1 TKN charged (not refunded).",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("team_management")


@career_required
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


