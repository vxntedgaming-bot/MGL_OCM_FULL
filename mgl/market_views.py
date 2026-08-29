from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from auctions.models import PlayerAuction
from leagues.services import active_divisions, active_league
from players.models import Player
from teams.models import Team

from .market import (
    AUCTION_DURATION_CHOICES,
    approve_listing,
    buy_listed_player,
    cancel_listing,
    close_expired_auctions,
    club_for_user,
    list_player_for_sale,
    reject_listing,
    settle_auction,
    token_balance_for_user,
)
from .models import (
    ApprovalStatus,
    ClubApplication,
    MarketTransaction,
    NewsPost,
    PlayerListing,
    PressConference,
)
from managers.models import ManagerApplication
from managers.services import STARTING_TOKENS, approve_manager_application, reject_manager_application

from .job_applications import GAMES_PER_WEEK_CHOICES, parse_club_application
from .permissions import approved_manager, owner_admin_required
from .services import create_news, manager_for_user
from .site_cms import resolved_discord_invite
from .standings import build_league_table
from .player_state import club_players, free_agents as free_agent_qs, market_counts, unassigned_players
from .tenure import open_club_spell

# Admin-only selection filter over the unassigned FC26 pool.
# Does not create a second pool, change ratings, or toggle is_free_agent.
UNASSIGNED_OVR_FILTERS = (
    ("all", "All"),
    ("62-70", "62–70 OVR"),
    ("71-plus", "71+ OVR"),
    ("under-62", "Under 62 OVR"),
)
FREE_AGENT_OVR_FILTERS = UNASSIGNED_OVR_FILTERS
FREE_AGENT_OVR_FILTER_KEYS = {key for key, _label in UNASSIGNED_OVR_FILTERS}
DEFAULT_FREE_AGENT_OVR_FILTER = "62-70"
CONTROL_FREE_AGENT_LIMIT = 40


def parse_free_agent_ovr_filter(value):
    value = (value or "").strip()
    if value in {"71+", "71"}:
        value = "71-plus"
    if value in FREE_AGENT_OVR_FILTER_KEYS:
        return value
    return DEFAULT_FREE_AGENT_OVR_FILTER


def apply_free_agent_ovr_filter(queryset, ovr_filter):
    if ovr_filter == "62-70":
        return queryset.filter(overall__gte=62, overall__lte=70)
    if ovr_filter == "71-plus":
        return queryset.filter(overall__gte=71)
    if ovr_filter == "under-62":
        return queryset.filter(overall__lt=62)
    return queryset


def control_centre_redirect(request):
    ovr = parse_free_agent_ovr_filter(
        request.POST.get("ovr") or request.GET.get("ovr")
    )
    url = reverse("control_centre")
    if ovr:
        url = f"{url}?ovr={ovr}"
    return redirect(url)


def transfer_market(request):
    close_expired_auctions()
    auctions = (
        PlayerAuction.objects.filter(status=PlayerAuction.LIVE)
        .select_related("player", "player__mgl_team", "winning_manager", "listed_by_manager", "origin_team")
        .order_by("ends_at")
    )
    listings = (
        PlayerListing.objects.filter(status=PlayerListing.LIVE)
        .select_related("player", "player__mgl_team", "team", "seller")
        .order_by("-created_at")
    )
    counts = market_counts()
    free_agents = free_agent_qs().order_by("-overall", "name")[:12]
    manager = manager_for_user(request.user)
    team = club_for_user(request.user)
    return render(
        request,
        "mgl/transfer_market.html",
        {
            "auctions": auctions,
            "listings": listings,
            "free_agents": free_agents,
            "free_agent_count": counts["free_agents"],
            "unassigned_count": counts["unassigned"],
            "club_player_count": counts["club_players"],
            "manager": manager,
            "team": team,
            "token_balance": token_balance_for_user(request.user),
        },
    )


@login_required
@require_POST
def sell_player(request, player_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to sell a player.")
        return redirect("team_management")
    player = get_object_or_404(Player, pk=player_id)
    try:
        listing = list_player_for_sale(player, manager, request.POST.get("asking_price"))
        messages.success(
            request,
            f"{player.name} listed for {listing.asking_price} tokens. "
            "An owner or admin must approve the listing before it goes live.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("team_management")


@login_required
@require_POST
def cancel_player_listing(request, listing_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to withdraw a listing.")
        return redirect("team_management")
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        cancel_listing(listing, manager)
        messages.success(request, f"{listing.player.name} is no longer listed.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("team_management")


@login_required
@require_POST
def buy_player(request, listing_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "You must be an approved manager to buy a player.")
        return redirect("transfer_market")
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        buy_listed_player(listing, manager)
        messages.success(request, f"{listing.player.name} is now at your club.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("transfer_market")


def leagues_page(request):
    divisions = active_divisions()
    premier = next((row for row in divisions if row.short_name == "PL"), None)
    return render(
        request,
        "mgl/leagues.html",
        {
            "divisions": divisions,
            "leagues": divisions,
            "active_league": premier or active_league(),
            "tables": [
                {"league": league, "table": build_league_table(league)}
                for league in divisions
            ],
        },
    )


def stats_page(request):
    from mgl.league_stats import render_league_stats

    return render_league_stats(request, "premier-league")


def league_stats_page(request, slug):
    from mgl.league_stats import render_league_stats

    return render_league_stats(request, slug)


def job_centre(request):
    manager = manager_for_user(request.user)
    vacant = (
        Team.objects.filter(manager__isnull=True, league__is_active=True)
        .select_related("league")
        .prefetch_related("players")
        .order_by("name")
    )
    my_apps = []
    if manager:
        my_apps = manager.club_applications.select_related("team").order_by("-created_at")[:10]
    return render(
        request,
        "mgl/job_centre.html",
        {
            "vacant_clubs": vacant,
            "manager": manager,
            "my_applications": my_apps,
            "has_club": bool(club_for_user(request.user)),
            "games_per_week_choices": GAMES_PER_WEEK_CHOICES,
        },
    )


@login_required
@require_POST
def apply_for_club(request, team_id):
    manager = approved_manager(request.user)
    if not manager:
        messages.error(request, "Your manager application must be approved first.")
        return redirect("job_centre")
    if club_for_user(request.user):
        messages.error(request, "You already manage a club.")
        return redirect("job_centre")
    team = get_object_or_404(Team, pk=team_id, manager__isnull=True)
    if ClubApplication.objects.filter(
        manager=manager,
        team=team,
        status=ApprovalStatus.PENDING,
    ).exists():
        messages.info(request, f"You already have a pending application for {team.name}.")
        return redirect("job_centre")
    payload = parse_club_application(request.POST)
    if payload["errors"]:
        for error in payload["errors"]:
            messages.error(request, error)
        return redirect("job_centre")
    if manager.gamertag != payload["gamertag"]:
        manager.gamertag = payload["gamertag"]
        manager.save(update_fields=["gamertag"])
    ClubApplication.objects.create(
        manager=manager,
        team=team,
        gamertag=payload["gamertag"],
        discord_username=payload["discord_username"],
        games_per_week=payload["games_per_week"],
        referred_by=payload["referred_by"],
        new_gen_confirmed=payload["new_gen_confirmed"],
        message=request.POST.get("message", "").strip(),
    )
    messages.success(
        request,
        f"Application sent for {team.name}. An owner or admin will review it. You have not been appointed yet.",
    )
    invite = resolved_discord_invite()
    if invite:
        return redirect(invite)
    return redirect("job_centre")


@owner_admin_required
@require_POST
def control_approve_manager(request, application_id):
    application = get_object_or_404(ManagerApplication, pk=application_id)
    try:
        approve_manager_application(application, request.user)
        messages.success(
            request,
            f"{application.display_name} is now an approved manager and starts with {STARTING_TOKENS} tokens.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_manager(request, application_id):
    application = get_object_or_404(ManagerApplication, pk=application_id)
    try:
        reject_manager_application(application, request.user)
        messages.success(request, f"{application.display_name} was rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
def control_centre(request):
    pending_managers = ManagerApplication.objects.filter(
        status=ManagerApplication.PENDING
    ).select_related("user")
    pending_listings = PlayerListing.objects.filter(
        status=PlayerListing.PENDING
    ).select_related("player", "team", "seller")
    pending_jobs = ClubApplication.objects.filter(
        status=ApprovalStatus.PENDING
    ).select_related("manager", "team")
    live_auctions = PlayerAuction.objects.filter(status=PlayerAuction.LIVE).select_related("player")
    from mgl.press import pending_press_reviews

    pending_press = pending_press_reviews()
    recent_activity = MarketTransaction.objects.select_related(
        "player", "seller", "buyer"
    ).order_by("-created_at")[:20]
    ovr_filter = parse_free_agent_ovr_filter(request.GET.get("ovr"))
    unassigned_pool = unassigned_players()
    filtered_unassigned = apply_free_agent_ovr_filter(unassigned_pool, ovr_filter)
    free_agent_match_count = filtered_unassigned.count()
    free_agents = filtered_unassigned.order_by("-overall", "name")[:CONTROL_FREE_AGENT_LIMIT]
    counts = market_counts()
    return render(
        request,
        "mgl/control_centre.html",
        {
            "pending_managers": pending_managers,
            "pending_listings": pending_listings,
            "pending_jobs": pending_jobs,
            "pending_press": pending_press,
            "live_auctions": live_auctions,
            "recent_activity": recent_activity,
            "teams": Team.objects.select_related("manager", "league").order_by("name"),
            "transactions": MarketTransaction.objects.select_related(
                "player", "seller", "buyer", "from_team", "to_team"
            )[:30],
            "free_agents": free_agents,
            "free_agent_ovr_filter": ovr_filter,
            "free_agent_ovr_filters": FREE_AGENT_OVR_FILTERS,
            "free_agent_match_count": free_agent_match_count,
            "free_agent_total_count": unassigned_pool.count(),
            "market_counts": counts,
            "control_next": f"{reverse('control_centre')}?ovr={ovr_filter}",
            "auction_durations": AUCTION_DURATION_CHOICES,
        },
    )


@owner_admin_required
@require_POST
def control_approve_listing(request, listing_id):
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        approve_listing(listing, request.user)
        messages.success(request, f"{listing.player.name} is now live on the transfer market.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_listing(request, listing_id):
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        reject_listing(listing, request.user)
        messages.success(request, "Listing rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_close_auction(request, auction_id):
    auction = get_object_or_404(PlayerAuction, pk=auction_id)
    _, message = settle_auction(auction, reviewer=request.user)
    messages.success(request, message)
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_approve_job(request, application_id):
    from django.utils import timezone

    application = get_object_or_404(
        ClubApplication.objects.select_related("manager__user", "team"),
        pk=application_id,
        status=ApprovalStatus.PENDING,
    )
    team = application.team
    if team.manager_id:
        messages.error(request, f"{team.name} already has a manager.")
        return control_centre_redirect(request)
    new_manager = application.manager.user
    if club_for_user(new_manager):
        messages.error(request, "That manager already has a club.")
        return control_centre_redirect(request)
    team.manager = new_manager
    team.save(update_fields=["manager"])
    open_club_spell(application.manager, team)
    application.status = ApprovalStatus.APPROVED
    application.reviewed_at = timezone.now()
    application.reviewed_by = request.user
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    from mgl.press import create_appointment_press

    create_news(
        NewsPost.MANAGER,
        f"{application.manager.display_name} appointed",
        f"{application.manager.display_name} has been appointed as manager of {team.name}.",
        team=team,
    )
    create_appointment_press(new_manager, team)
    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        new_manager,
        source_key=f"job-approved-{application.pk}",
        notification_type="ADMIN",
        title="CLUB APPOINTMENT",
        message=f"You have been appointed as manager of {team.name}.",
        actor="MGL Admin",
        action_url=reverse("manager_hub"),
        action_label="OPEN HUB",
        team=team,
    )
    messages.success(
        request,
        f"{new_manager.username} is now manager of {team.name}. Token balance stays with the manager.",
    )
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_job(request, application_id):
    from django.utils import timezone

    application = get_object_or_404(
        ClubApplication.objects.select_related("manager", "team"),
        pk=application_id,
        status=ApprovalStatus.PENDING,
    )
    application.status = ApprovalStatus.REJECTED
    application.reviewed_at = timezone.now()
    application.reviewed_by = request.user
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        application.manager.user,
        source_key=f"job-rejected-{application.pk}",
        notification_type="ADMIN",
        title="CLUB APPLICATION REJECTED",
        message=f"Your application for {application.team.name} was rejected.",
        actor="MGL Admin",
        action_url=reverse("job_centre"),
        action_label="JOB CENTRE",
        team=application.team,
    )
    messages.success(
        request,
        f"{application.manager.display_name}'s application for {application.team.name} was rejected.",
    )
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_approve_press(request, press_id):
    from mgl.notifications import notify_user
    from mgl.press import approve_press_conference

    press = get_object_or_404(PressConference, pk=press_id)
    try:
        approve_press_conference(press, reviewer=request.user)
        notify_user(
            press.manager,
            source_key=f"press-approved-{press.pk}",
            notification_type="ADMIN",
            title="PRESS CONFERENCE PUBLISHED",
            message="Your interview is now live in the MGL Pressroom.",
            actor="MGL Admin",
            action_url=reverse("pressroom"),
            action_label="OPEN PRESSROOM",
            team=press.team,
        )
        messages.success(request, "Press conference published to the Pressroom.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_press(request, press_id):
    from mgl.notifications import notify_user
    from mgl.press import reject_press_conference

    press = get_object_or_404(PressConference, pk=press_id)
    try:
        reject_press_conference(press, reviewer=request.user)
        notify_user(
            press.manager,
            source_key=f"press-rejected-{press.pk}",
            notification_type="ADMIN",
            title="PRESS CONFERENCE REJECTED",
            message="Your press conference answer was not published.",
            actor="MGL Admin",
            action_url=reverse("manager_hub"),
            action_label="OPEN HUB",
            team=press.team,
        )
        messages.success(request, "Press conference rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)
