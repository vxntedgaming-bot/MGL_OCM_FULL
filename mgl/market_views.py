import uuid
from decimal import Decimal, InvalidOperation

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
    cancel_listing,
    cancel_live_auction,
    close_expired_auctions,
    club_for_user,
    create_listed_purchase_offer,
    create_transfer_offer,
    detach_live_club_auction_players,
    list_player_for_sale,
    locked_squad_player_ids,
    reject_listing,
    settle_auction,
    token_balance_for_user,
    transfer_offer_details,
    transfer_window_is_open,
)
from .models import (
    ApprovalStatus,
    ClubApplication,
    Fixture,
    ManagerNotification,
    MarketTransaction,
    MatchSubmission,
    NewsPost,
    PlayerListing,
    PressConference,
    RewardTransaction,
    ScoutAssignment,
    SiteChangeLog,
    WeeklyAwardBatch,
    MonthlyAwardBatch,
)
from managers.models import ManagerApplication
from managers.services import STARTING_TOKENS, approve_manager_application, reject_manager_application

from .job_applications import (
    GAMES_PER_WEEK_CHOICES,
    JOBS_DISCORD_INVITE,
    parse_club_application,
)
from .nav import live_competition_choices
from .permissions import approved_manager, owner_admin_required
from .services import create_news, manager_for_user
from .standings import build_live_league_table
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
    from mgl.transfer_requests import completed_transfers_for

    listing_list = list(listings)
    listed_clubs = sorted(
        {listing.team for listing in listing_list if listing.team_id},
        key=lambda club: club.name,
    )
    listed_tokens = sum(
        (listing.asking_price for listing in listing_list),
        Decimal("0"),
    )
    latest_transfers = completed_transfers_for(None, all_clubs=True, limit=8)
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
            "window_open": transfer_window_is_open(),
            "listed_clubs": listed_clubs,
            "listed_tokens": listed_tokens,
            "latest_transfers": latest_transfers,
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
            f"{player.name} is now listed for {listing.asking_price} tokens.",
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
def request_player_transfer(request, player_id):
    manager = approved_manager(request.user)
    player = get_object_or_404(Player.objects.select_related("mgl_team"), pk=player_id)
    next_url = request.POST.get("next") or reverse("player_profile", args=[player.id])
    if not manager:
        messages.error(request, "You must be an approved manager to buy a player.")
        return redirect(next_url)
    try:
        listing = create_transfer_offer(
            player,
            manager,
            request.POST.get("asking_price") or request.POST.get("amount"),
        )
        messages.success(
            request,
            f"Transfer request sent for {player.name} "
            f"({listing.asking_price} TKN). The current club manager must respond, "
            "and Owner/Admin approval is still required.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(next_url)


@login_required
def purchase_listing(request, listing_id):
    manager = approved_manager(request.user)
    listing = get_object_or_404(
        PlayerListing.objects.select_related("player", "team", "seller", "team__manager"),
        pk=listing_id,
    )
    if not manager:
        messages.error(request, "You must be an approved manager to buy a player.")
        return redirect("transfer_market")
    buyer_club = club_for_user(request.user)
    if not buyer_club:
        messages.error(request, "You must manage a club to buy a player.")
        return redirect("transfer_market")
    if listing.team_id == buyer_club.id:
        messages.error(request, "You cannot buy your own player.")
        return redirect("transfer_market")
    if listing.status != PlayerListing.LIVE:
        messages.error(request, "This player is not available for purchase.")
        return redirect("transfer_market")

    if request.method == "POST":
        offered_ids = [
            value
            for value in request.POST.getlist("offered_players")
            if str(value).strip()
        ]
        if not offered_ids:
            single = (request.POST.get("offered_player") or "").strip()
            if single:
                offered_ids = [single]
        offered = [get_object_or_404(Player, pk=player_id) for player_id in offered_ids]
        try:
            created = create_listed_purchase_offer(
                listing,
                manager,
                request.POST.get("asking_price") or request.POST.get("amount") or "",
                offered_players=offered,
            )
            messages.success(
                request,
                f"Transfer offer sent to {created.seller.display_name}.",
            )
            return redirect("manager_hub")
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("purchase_listing", listing_id)

    seller_squad = list(
        listing.team.players.select_related("mgl_team").order_by(
            "position",
            "-overall",
            "name",
        )
    )
    buyer_squad = list(
        buyer_club.players.select_related("mgl_team").order_by(
            "position",
            "-overall",
            "name",
        )
    )
    locked_ids = locked_squad_player_ids(buyer_club)
    for player in buyer_squad:
        player.swap_locked = player.id in locked_ids
        player.swap_eligible = not player.swap_locked
    return render(
        request,
        "mgl/purchase_listing.html",
        {
            "listing": listing,
            "player": listing.player,
            "selling_team": listing.team,
            "buying_team": buyer_club,
            "seller": listing.seller,
            "manager": manager,
            "seller_squad": seller_squad,
            "buyer_squad": buyer_squad,
            "token_balance": token_balance_for_user(request.user),
        },
    )


@login_required
@require_POST
def buy_player(request, listing_id):
    manager = approved_manager(request.user)
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    buyer_club = club_for_user(request.user)
    if (
        manager
        and buyer_club
        and listing.team_id != buyer_club.id
        and listing.status == PlayerListing.LIVE
    ):
        return redirect("purchase_listing", listing.id)
    messages.error(request, "Listed players must be bought through the BUY page.")
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
                {"league": league, "table": build_live_league_table(league)}
                for league in divisions
            ],
            "competition_choices": live_competition_choices(),
            "competition_slug": "",
            "selector_kind": "tables",
            "selector_label": "League tables",
        },
    )


def stats_page(request):
    from mgl.league_stats import render_league_stats

    return render_league_stats(request, "premier-league")


def league_stats_page(request, slug):
    from mgl.league_stats import render_league_stats

    return render_league_stats(request, slug)


def _jobs_latest_result():
    latest_result = (
        Fixture.objects.filter(is_released=True, status="COMPLETED")
        .select_related("home_team", "away_team", "league")
        .prefetch_related("submission__team_stats")
        .order_by("-id")
        .first()
    )
    if not latest_result:
        return None
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
    return latest_result


def job_centre(request):
    manager = manager_for_user(request.user)
    vacant = (
        Team.objects.filter(manager__isnull=True, league__is_active=True)
        .select_related("league")
        .prefetch_related("players")
        .order_by("league__display_order", "league__name", "name")
    )
    pending_team_ids = set()
    if manager:
        pending_team_ids = set(
            manager.club_applications.filter(
                status=ApprovalStatus.PENDING
            ).values_list("team_id", flat=True)
        )
    can_apply = bool(
        manager
        and manager.status != ManagerApplication.REJECTED
        and not club_for_user(request.user)
    )
    job_leagues = []
    seen_leagues = set()
    for team in vacant:
        if team.league_id and team.league_id not in seen_leagues:
            seen_leagues.add(team.league_id)
            job_leagues.append(team.league)
    return render(
        request,
        "mgl/job_centre.html",
        {
            "vacant_clubs": vacant,
            "job_leagues": job_leagues,
            "manager": manager,
            "pending_team_ids": pending_team_ids,
            "has_club": bool(club_for_user(request.user)),
            "can_apply": can_apply,
            "games_per_week_choices": GAMES_PER_WEEK_CHOICES,
            "jobs_discord_invite": JOBS_DISCORD_INVITE,
            "join_discord": request.GET.get("join_discord") == "1",
            "window_open": transfer_window_is_open(),
            "latest_result": _jobs_latest_result(),
        },
    )


@login_required
@require_POST
def apply_for_club(request, team_id):
    manager = manager_for_user(request.user)
    if not manager:
        messages.error(request, "Create an account before applying for a club.")
        return redirect("manager_register")
    if manager.status == ManagerApplication.REJECTED:
        messages.error(request, "Your manager application was rejected.")
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
    return redirect(f"{reverse('job_centre')}?join_discord=1")


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
    detach_live_club_auction_players()
    pending_managers = ManagerApplication.objects.filter(
        status=ManagerApplication.PENDING
    ).select_related("user")
    pending_listings = list(
        PlayerListing.objects.filter(
            status=PlayerListing.PENDING,
            reserved_buyer__isnull=False,
        ).select_related(
            "player",
            "team",
            "seller",
            "reserved_buyer",
            "reserved_buyer__user",
            "offered_player",
        ).prefetch_related("offered_players")
    )
    for listing in pending_listings:
        listing.deal = transfer_offer_details(listing)
    pending_results = list(
        MatchSubmission.objects.filter(
            status=ApprovalStatus.PENDING,
            opponent_response=ApprovalStatus.APPROVED,
        )
        .select_related(
            "fixture__home_team",
            "fixture__away_team",
            "submitted_by",
        )
        .prefetch_related("team_stats")
        .order_by("-submitted_at")
    )
    disputed_results = list(
        MatchSubmission.objects.filter(status=ApprovalStatus.PENDING)
        .exclude(opponent_response=ApprovalStatus.APPROVED)
        .select_related(
            "fixture__home_team",
            "fixture__away_team",
            "submitted_by",
        )
        .prefetch_related("team_stats")
        .order_by("-submitted_at")
    )
    for submission in pending_results + disputed_results:
        rows = {row.team_id: row for row in submission.team_stats.all()}
        fixture = submission.fixture
        home = rows.get(fixture.home_team_id)
        away = rows.get(fixture.away_team_id)
        submission.home_goals = getattr(home, "goals", 0)
        submission.away_goals = getattr(away, "goals", 0)
        submission.scoreline = (
            f"{fixture.home_team.name} {submission.home_goals}-"
            f"{submission.away_goals} {fixture.away_team.name}"
        )
    pending_jobs = ClubApplication.objects.filter(
        status=ApprovalStatus.PENDING
    ).select_related("manager", "team")
    live_auctions = PlayerAuction.objects.filter(status=PlayerAuction.LIVE).select_related("player")
    from mgl.press import pending_press_reviews

    pending_press = pending_press_reviews()
    recent_activity = MarketTransaction.objects.select_related(
        "player", "seller", "buyer", "from_team", "to_team", "approved_by"
    ).order_by("-created_at")[:20]
    pending_counts = {
        "managers": pending_managers.count(),
        "listings": len(pending_listings),
        "results": len(pending_results),
        "jobs": pending_jobs.count(),
        "press": pending_press.count(),
        "auctions": live_auctions.count(),
        "awards": WeeklyAwardBatch.objects.filter(
            status=WeeklyAwardBatch.PENDING_REVIEW, completed=False
        ).count()
        + MonthlyAwardBatch.objects.filter(
            status=MonthlyAwardBatch.PENDING_REVIEW, completed=False
        ).count(),
        "disputed": len(disputed_results),
    }
    pending_counts["approvals"] = (
        pending_counts["managers"]
        + pending_counts["listings"]
        + pending_counts["results"]
        + pending_counts["jobs"]
        + pending_counts["press"]
        + pending_counts["awards"]
    )
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
            "pending_results": pending_results,
            "disputed_results": disputed_results,
            "pending_jobs": pending_jobs,
            "pending_press": pending_press,
            "pending_counts": pending_counts,
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
            "recent_rewards": RewardTransaction.objects.select_related(
                "manager", "manager__user", "fixture", "created_by"
            ).order_by("-created_at")[:40],
            "weekly_award_batches": WeeklyAwardBatch.objects.order_by("-week_start")[:12],
            "monthly_award_batches": MonthlyAwardBatch.objects.order_by("-month_start")[:12],
            "ocm_audit_log": SiteChangeLog.objects.select_related("user").order_by("-created_at")[:25],
            "is_owner": request.user.role == request.user.OWNER,
            "recent_notifications": ManagerNotification.objects.select_related(
                "recipient", "team", "player"
            ).order_by("-created_at")[:40],
            "recent_scouts": ScoutAssignment.objects.select_related(
                "manager", "manager__user", "player", "club"
            ).prefetch_related("reports").order_by("-started_at")[:25],
            "token_managers": ManagerApplication.objects.select_related("user").order_by(
                "display_name"
            ),
        },
    )


@owner_admin_required
@require_POST
def control_approve_listing(request, listing_id):
    listing = get_object_or_404(PlayerListing, pk=listing_id)
    try:
        listing = approve_listing(listing, request.user)
        if listing.status == PlayerListing.SOLD:
            messages.success(
                request,
                f"{listing.player.name} transfer is complete after Owner/Admin approval.",
            )
        else:
            messages.success(
                request,
                f"{listing.player.name} is now live on the transfer market.",
            )
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_approve_result(request, submission_id):
    from mgl.admin import approve_match_submission

    submission = get_object_or_404(MatchSubmission, pk=submission_id)
    override = (
        request.POST.get("override") == "1"
        and getattr(request.user, "role", None) == request.user.OWNER
    )
    ok, message = approve_match_submission(submission, request.user, override=override)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_result(request, submission_id):
    from mgl.admin import reject_match_submission

    submission = get_object_or_404(MatchSubmission, pk=submission_id)
    ok, message = reject_match_submission(submission, request.user)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_rollback_result(request, submission_id):
    from mgl.match_official import unapprove_match_submission

    submission = get_object_or_404(MatchSubmission, pk=submission_id)
    ok, message = unapprove_match_submission(submission, request.user)
    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_approve_weekly_awards(request, batch_id):
    from mgl.weekly_awards import approve_weekly_awards

    batch = get_object_or_404(WeeklyAwardBatch, pk=batch_id)
    try:
        approve_weekly_awards(batch, request.user)
        messages.success(request, "Weekly awards approved. Token rewards released once.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_reject_weekly_awards(request, batch_id):
    from mgl.weekly_awards import reject_weekly_awards

    batch = get_object_or_404(WeeklyAwardBatch, pk=batch_id)
    reject_weekly_awards(batch, request.user)
    messages.success(request, "Weekly awards rejected. Tokens were not released.")
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_recalculate_weekly_awards(request, batch_id):
    from mgl.weekly_awards import recalculate_weekly_awards

    batch = get_object_or_404(WeeklyAwardBatch, pk=batch_id)
    try:
        recalculate_weekly_awards(batch, request.user)
        messages.success(request, "Weekly awards recalculated. Review the new draft.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_approve_monthly_awards(request, batch_id):
    from mgl.monthly_awards import approve_monthly_awards

    batch = get_object_or_404(MonthlyAwardBatch, pk=batch_id)
    approve_monthly_awards(batch, request.user)
    messages.success(request, "Monthly awards approved. Token rewards released once.")
    return control_centre_redirect(request)


@owner_admin_required
@require_POST
def control_adjust_tokens(request):
    from mgl.audit import log_ocm_action
    from mgl.services import credit_manager, debit_manager

    reason = (request.POST.get("reason") or "").strip()
    try:
        amount = Decimal(str(request.POST.get("amount") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        messages.error(request, "Enter a valid token amount.")
        return control_centre_redirect(request)
    if amount == 0:
        messages.error(request, "Token adjustments must be a non-zero amount.")
        return control_centre_redirect(request)
    if not reason:
        messages.error(request, "Record a reason for every token adjustment.")
        return control_centre_redirect(request)
    manager = get_object_or_404(ManagerApplication, pk=request.POST.get("manager_id"))
    reference = f"admin:{request.user.id}:{uuid.uuid4().hex[:12]}"
    before = Decimal(manager.tokens)
    if amount > 0:
        row = credit_manager(
            manager,
            amount,
            reason,
            category="ADMIN",
            reference=reference,
            created_by=request.user,
        )
    else:
        row = debit_manager(
            manager,
            abs(amount),
            reason,
            category="ADMIN",
            reference=reference,
            created_by=request.user,
            allow_negative=True,
        )
    manager.refresh_from_db()
    log_ocm_action(
        request.user,
        action="token.adjust",
        object_type="RewardTransaction",
        object_id=row.pk,
        object_label=manager.display_name,
        old_value=str(before),
        new_value=str(manager.tokens),
        summary=f"{request.user.username} adjusted {manager.display_name} by {amount}: {reason}",
    )
    messages.success(
        request,
        f"{manager.display_name}: {before} → {manager.tokens} tokens.",
    )
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
def control_cancel_auction(request, auction_id):
    auction = get_object_or_404(PlayerAuction, pk=auction_id)
    try:
        _, message = cancel_live_auction(auction, reviewer=request.user)
        messages.success(request, message)
    except ValueError as exc:
        messages.error(request, str(exc))
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
    if application.manager.status == ManagerApplication.PENDING:
        try:
            approve_manager_application(application.manager, request.user)
        except ValueError:
            pass
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
    from mgl.audit import log_ocm_action

    log_ocm_action(
        request.user,
        action="job.approve",
        object_type="ClubApplication",
        object_id=application.pk,
        object_label=team.name,
        new_value="APPROVED",
        summary=f"Appointed {application.manager.display_name} to {team.name}.",
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
