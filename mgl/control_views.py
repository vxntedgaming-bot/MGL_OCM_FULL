"""Dedicated Owner/Admin Control Centre pages. Actions stay on existing POST views."""

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone

from auctions.models import PlayerAuction
from managers.models import ManagerApplication
from teams.models import Team

from mgl.control_desk import (
    control_dashboard_context,
    control_shell_context,
    load_queues,
    weekly_payout_preview,
)
from mgl.market import AUCTION_DURATION_CHOICES
from mgl.models import (
    ManagerNotification,
    MarketTransaction,
    MonthlyAwardBatch,
    RewardTransaction,
    ScoutAssignment,
    SiteChangeLog,
    WeeklyAwardBatch,
)
from mgl.permissions import owner_admin_required
from mgl.player_state import market_counts, unassigned_players


@owner_admin_required
def control_centre(request):
    from mgl.market import detach_live_club_auction_players

    detach_live_club_auction_players()
    return render(request, "mgl/control_centre.html", control_dashboard_context(request))


@owner_admin_required
def control_pending(request):
    queues = load_queues()
    inbox_type = (request.GET.get("type") or "all").strip().lower()
    search = (request.GET.get("q") or "").strip().lower()
    inbox = []
    for submission in queues["pending_results"]:
        inbox.append(
            {
                "kind": "SCORE",
                "title": submission.scoreline,
                "submitted_by": submission.submitted_by.username if submission.submitted_by else "—",
                "club": submission.fixture.home_team.name,
                "when": submission.submitted_at,
                "status": "PENDING",
                "url": reverse("control_scores"),
            }
        )
    for listing in queues["pending_listings"]:
        inbox.append(
            {
                "kind": "TRANSFER",
                "title": str((listing.deal or {}).get("player") or listing.player.name),
                "submitted_by": listing.reserved_buyer.display_name if listing.reserved_buyer else "—",
                "club": listing.team.name,
                "when": getattr(listing, "created_at", None),
                "status": "PENDING",
                "url": reverse("control_transfers"),
            }
        )
    for press in queues["pending_press"]:
        inbox.append(
            {
                "kind": "PRESS",
                "title": press.question,
                "submitted_by": press.manager.username if press.manager_id else "—",
                "club": press.team.name if press.team_id else "MGL",
                "when": press.created_at,
                "status": "PENDING",
                "url": reverse("control_press"),
            }
        )
    for app in queues["pending_managers"]:
        inbox.append(
            {
                "kind": "MANAGER APPLICATION",
                "title": app.display_name,
                "submitted_by": app.user.username if app.user_id else app.display_name,
                "club": app.preferred_team or "—",
                "when": app.submitted_at,
                "status": "PENDING",
                "url": reverse("control_managers"),
            }
        )
    for job in queues["pending_jobs"]:
        inbox.append(
            {
                "kind": "MANAGER APPLICATION",
                "title": job.manager.display_name,
                "submitted_by": job.manager.display_name,
                "club": job.team.name,
                "when": job.created_at,
                "status": "PENDING",
                "url": reverse("control_managers"),
            }
        )
    if inbox_type == "scores":
        inbox = [row for row in inbox if row["kind"] == "SCORE"]
    elif inbox_type == "transfers":
        inbox = [row for row in inbox if row["kind"] == "TRANSFER"]
    elif inbox_type == "press":
        inbox = [row for row in inbox if row["kind"] == "PRESS"]
    elif inbox_type in {"managers", "applications"}:
        inbox = [row for row in inbox if row["kind"] == "MANAGER APPLICATION"]
    if search:
        inbox = [
            row
            for row in inbox
            if search in " ".join(
                [row["kind"], row["title"], row["submitted_by"], row["club"]]
            ).lower()
        ]
    inbox.sort(key=lambda row: row["when"] or timezone.now(), reverse=True)
    context = control_shell_context(request, "pending", queues)
    context.update(
        {
            "pending_managers": queues["pending_managers"],
            "pending_listings": queues["pending_listings"],
            "pending_results": queues["pending_results"],
            "disputed_results": queues["disputed_results"],
            "pending_jobs": queues["pending_jobs"],
            "pending_press": queues["pending_press"],
            "weekly_award_batches": WeeklyAwardBatch.objects.filter(
                status=WeeklyAwardBatch.PENDING_REVIEW
            ).order_by("-week_start"),
            "monthly_award_batches": MonthlyAwardBatch.objects.filter(
                status=MonthlyAwardBatch.PENDING_REVIEW
            ).order_by("-month_start"),
            "inbox": inbox,
            "inbox_type": inbox_type,
            "search": request.GET.get("q") or "",
        }
    )
    return render(request, "mgl/control_pending.html", context)


@owner_admin_required
def control_scores(request):
    queues = load_queues()
    context = control_shell_context(request, "scores", queues)
    context.update(
        {
            "pending_results": queues["pending_results"],
            "disputed_results": queues["disputed_results"],
        }
    )
    return render(request, "mgl/control_scores.html", context)


@owner_admin_required
def control_transfers(request):
    queues = load_queues()
    context = control_shell_context(request, "transfers", queues)
    context["pending_listings"] = queues["pending_listings"]
    return render(request, "mgl/control_transfers.html", context)


@owner_admin_required
def control_press(request):
    queues = load_queues()
    context = control_shell_context(request, "press", queues)
    context["pending_press"] = queues["pending_press"]
    return render(request, "mgl/control_press.html", context)


@owner_admin_required
def control_weekly_awards(request):
    queues = load_queues()
    batches = list(WeeklyAwardBatch.objects.order_by("-week_start")[:16])
    for batch in batches:
        batch.payouts = weekly_payout_preview(batch)
    context = control_shell_context(request, "weekly", queues)
    context["weekly_award_batches"] = batches
    return render(request, "mgl/control_weekly_awards.html", context)


@owner_admin_required
def control_monthly_awards(request):
    queues = load_queues()
    context = control_shell_context(request, "monthly", queues)
    context["monthly_award_batches"] = MonthlyAwardBatch.objects.order_by("-month_start")[:16]
    return render(request, "mgl/control_monthly_awards.html", context)


@owner_admin_required
def control_managers(request):
    queues = load_queues()
    context = control_shell_context(request, "managers", queues)
    context.update(
        {
            "pending_managers": queues["pending_managers"],
            "pending_jobs": queues["pending_jobs"],
        }
    )
    return render(request, "mgl/control_managers.html", context)


@owner_admin_required
def control_tokens(request):
    queues = load_queues()
    from django.db.models import Q

    search = (request.GET.get("q") or "").strip()
    managers = ManagerApplication.objects.select_related("user").order_by("display_name")
    selected = None
    if request.GET.get("manager_id"):
        selected = get_object_or_404(ManagerApplication, pk=request.GET.get("manager_id"))
    if search and selected is None:
        selected = managers.filter(
            Q(display_name__icontains=search)
            | Q(gamertag__icontains=search)
            | Q(user__username__icontains=search)
        ).first()
    ledger = RewardTransaction.objects.select_related(
        "manager", "manager__user", "fixture", "created_by"
    ).order_by("-created_at")
    market_rows = MarketTransaction.objects.select_related(
        "player", "seller", "buyer", "from_team", "to_team", "approved_by"
    ).order_by("-created_at")
    if selected:
        ledger = ledger.filter(manager=selected)
        market_rows = market_rows.filter(Q(seller=selected) | Q(buyer=selected))
    context = control_shell_context(request, "tokens", queues)
    context.update(
        {
            "token_managers": managers,
            "selected_manager": selected,
            "search": search,
            "recent_rewards": ledger[:60],
            "transactions": market_rows[:40],
        }
    )
    return render(request, "mgl/control_tokens.html", context)


@owner_admin_required
def control_scouting(request):
    queues = load_queues()
    context = control_shell_context(request, "scouting", queues)
    context["recent_scouts"] = (
        ScoutAssignment.objects.select_related("manager", "manager__user", "player", "club")
        .prefetch_related("reports")
        .order_by("-started_at")[:40]
    )
    return render(request, "mgl/control_scouting.html", context)


@owner_admin_required
def control_auctions(request):
    from mgl.market import detach_live_club_auction_players
    from mgl.market_views import (
        CONTROL_FREE_AGENT_LIMIT,
        FREE_AGENT_OVR_FILTERS,
        apply_free_agent_ovr_filter,
        parse_free_agent_ovr_filter,
    )

    detach_live_club_auction_players()
    queues = load_queues()
    ovr_filter = parse_free_agent_ovr_filter(request.GET.get("ovr"))
    unassigned_pool = unassigned_players()
    filtered_unassigned = apply_free_agent_ovr_filter(unassigned_pool, ovr_filter)
    context = control_shell_context(request, "auctions", queues)
    context.update(
        {
            "live_auctions": queues["live_auctions"],
            "ended_auctions": PlayerAuction.objects.filter(
                status__in=[PlayerAuction.ENDED, PlayerAuction.CANCELLED]
            )
            .select_related("player", "winning_manager")
            .order_by("-ends_at")[:20],
            "free_agents": filtered_unassigned.order_by("-overall", "name")[:CONTROL_FREE_AGENT_LIMIT],
            "free_agent_ovr_filter": ovr_filter,
            "free_agent_ovr_filters": FREE_AGENT_OVR_FILTERS,
            "free_agent_match_count": filtered_unassigned.count(),
            "free_agent_total_count": unassigned_pool.count(),
            "market_counts": market_counts(),
            "control_next": f"{reverse('control_auctions')}?ovr={ovr_filter}",
            "auction_durations": AUCTION_DURATION_CHOICES,
        }
    )
    return render(request, "mgl/control_auctions.html", context)


@owner_admin_required
def control_clubs(request):
    queues = load_queues()
    context = control_shell_context(request, "clubs", queues)
    context["teams"] = (
        Team.objects.select_related("manager", "league")
        .annotate(squad_size=Count("players"))
        .order_by("name")
    )
    return render(request, "mgl/control_clubs.html", context)


@owner_admin_required
def control_notifications(request):
    queues = load_queues()
    context = control_shell_context(request, "notifications", queues)
    context["recent_notifications"] = ManagerNotification.objects.select_related(
        "recipient", "team", "player"
    ).order_by("-created_at")[:80]
    return render(request, "mgl/control_notifications.html", context)


@owner_admin_required
def control_logs(request):
    queues = load_queues()
    search = (request.GET.get("q") or "").strip()
    action = (request.GET.get("action") or "").strip()
    logs = SiteChangeLog.objects.select_related("user").order_by("-created_at")
    if search:
        logs = logs.filter(
            Q(summary__icontains=search)
            | Q(object_label__icontains=search)
            | Q(user__username__icontains=search)
        )
    if action:
        logs = logs.filter(action__icontains=action)
    context = control_shell_context(request, "logs", queues)
    context["ocm_audit_log"] = logs[:80]
    context["log_search"] = search
    context["log_action"] = action
    context["recent_activity"] = MarketTransaction.objects.select_related(
        "player", "seller", "buyer", "from_team", "to_team", "approved_by"
    ).order_by("-created_at")[:40]
    return render(request, "mgl/control_logs.html", context)


@owner_admin_required
def control_season_history(request):
    from mgl.models import HistoricalSeason

    queues = load_queues()
    context = control_shell_context(request, "season_history", queues)
    context["seasons"] = HistoricalSeason.objects.select_related(
        "league_winner", "top_scorer", "top_assists_player", "manager_of_season"
    ).order_by("-number")
    return render(request, "mgl/control_season_history.html", context)


@owner_admin_required
def control_season_controls(request):
    from mgl.models import HistoricalSeason
    from mgl.season_history import ensure_active_season

    ensure_active_season()
    queues = load_queues()
    context = control_shell_context(request, "season_controls", queues)
    context["active_season"] = (
        HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).order_by("-number").first()
    )
    return render(request, "mgl/control_season_controls.html", context)


@owner_admin_required
def control_league(request):
    from mgl.market import transfer_window_is_open
    from mgl.site_cms import get_content

    queues = load_queues()
    context = control_shell_context(request, "league", queues)
    context.update(
        {
            "site_name": get_content("settings.site_name"),
            "site_tagline": get_content("settings.site_tagline"),
            "window_open": transfer_window_is_open(),
            "reward_rates": {
                "totw": "0.20 per TOTW player",
                "top_goals": "0.50",
                "top_assists": "0.50",
                "motw": "1.00",
                "motm": "6.00",
                "potm": "3.00",
                "press": "0.50",
            },
        }
    )
    return render(request, "mgl/control_league.html", context)
