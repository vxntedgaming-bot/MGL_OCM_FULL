from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from auctions.models import PlayerAuction
from leagues.models import League
from players.models import Player
from teams.models import Team

from .market import (
    approve_listing,
    buy_listed_player,
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
    PlayerListing,
)
from managers.models import ManagerApplication
from managers.services import approve_manager_application, reject_manager_application

from .permissions import approved_manager, owner_admin_required
from .services import manager_for_user


def transfer_market(request):
    close_expired_auctions()
    auctions = (
        PlayerAuction.objects.filter(status=PlayerAuction.LIVE)
        .select_related("player", "winning_manager")
        .order_by("ends_at")
    )
    listings = (
        PlayerListing.objects.filter(status=PlayerListing.LIVE)
        .select_related("player", "team", "seller")
        .order_by("-created_at")
    )
    free_agent_count = Player.objects.filter(is_free_agent=True, mgl_team__isnull=True).count()
    free_agents = (
        Player.objects.filter(is_free_agent=True, mgl_team__isnull=True)
        .order_by("-overall", "name")[:12]
    )
    manager = manager_for_user(request.user)
    team = club_for_user(request.user)
    return render(
        request,
        "mgl/transfer_market.html",
        {
            "auctions": auctions,
            "listings": listings,
            "free_agents": free_agents,
            "free_agent_count": free_agent_count,
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
    leagues = (
        League.objects.filter(is_active=True)
        .prefetch_related("teams__manager")
        .order_by("name")
    )
    return render(request, "mgl/leagues.html", {"leagues": leagues})


def stats_page(request):
    top_scorers = (
        Player.objects.filter(goals__gt=0)
        .select_related("mgl_team")
        .order_by("-goals", "name")[:20]
    )
    recent_transfers = (
        MarketTransaction.objects.filter(status=MarketTransaction.COMPLETED)
        .select_related("player", "from_team", "to_team")
        .order_by("-created_at")[:15]
    )
    return render(
        request,
        "mgl/stats.html",
        {
            "top_scorers": top_scorers,
            "recent_transfers": recent_transfers,
            "club_count": Team.objects.count(),
            "player_count": Player.objects.count(),
            "free_agent_count": Player.objects.filter(is_free_agent=True, mgl_team__isnull=True).count(),
        },
    )


def job_centre(request):
    manager = manager_for_user(request.user)
    vacant = (
        Team.objects.filter(manager__isnull=True)
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
    ClubApplication.objects.create(
        manager=manager,
        team=team,
        message=request.POST.get("message", "").strip(),
    )
    messages.success(
        request,
        f"Application sent for {team.name}. An owner or admin will review it.",
    )
    return redirect("job_centre")


@owner_admin_required
@require_POST
def control_approve_manager(request, application_id):
    application = get_object_or_404(ManagerApplication, pk=application_id)
    try:
        approve_manager_application(application, request.user)
        messages.success(
            request,
            f"{application.display_name} is now an approved manager and starts with 50 tokens.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("control_centre")


@owner_admin_required
@require_POST
def control_reject_manager(request, application_id):
    application = get_object_or_404(ManagerApplication, pk=application_id)
    try:
        reject_manager_application(application, request.user)
        messages.success(request, f"{application.display_name} was rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("control_centre")


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
    recent_activity = MarketTransaction.objects.select_related(
        "player", "seller", "buyer"
    ).order_by("-created_at")[:20]
    return render(
        request,
        "mgl/control_centre.html",
        {
            "pending_managers": pending_managers,
            "pending_listings": pending_listings,
            "pending_jobs": pending_jobs,
            "live_auctions": live_auctions,
            "recent_activity": recent_activity,
            "teams": Team.objects.select_related("manager", "league").order_by("name"),
            "transactions": MarketTransaction.objects.select_related(
                "player", "seller", "buyer", "from_team", "to_team"
            )[:30],
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
    return redirect("control_centre")


@owner_admin_required
@require_POST
def control_reject_listing(request, listing_id):
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        reject_listing(listing, request.user)
        messages.success(request, "Listing rejected.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("control_centre")


@owner_admin_required
@require_POST
def control_close_auction(request, auction_id):
    auction = get_object_or_404(PlayerAuction, pk=auction_id)
    _, message = settle_auction(auction, reviewer=request.user)
    messages.success(request, message)
    return redirect("control_centre")


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
        return redirect("control_centre")
    new_manager = application.manager.user
    if club_for_user(new_manager):
        messages.error(request, "That manager already has a club.")
        return redirect("control_centre")
    team.manager = new_manager
    team.save(update_fields=["manager"])
    application.status = ApprovalStatus.APPROVED
    application.reviewed_at = timezone.now()
    application.reviewed_by = request.user
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    messages.success(
        request,
        f"{new_manager.username} is now manager of {team.name}. The squad and token balance remain with the club.",
    )
    return redirect("control_centre")


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
    messages.success(
        request,
        f"{application.manager.display_name}'s application for {application.team.name} was rejected.",
    )
    return redirect("control_centre")
