"""Dedicated Owner/Admin Control Centre pages. Actions stay on existing POST views."""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.models import User
from auctions.models import PlayerAuction
from managers.models import ManagerApplication
from teams.models import Team

from mgl.control_desk import (
    control_dashboard_context,
    control_shell_context,
    load_queues,
    monthly_history_rows,
    scouting_movement_rows,
    weekly_history_rows,
    weekly_payout_preview,
)
from mgl.market import AUCTION_DURATION_CHOICES
from mgl.discord_queue import event_payload_preview, retry_discord_event
from mgl.models import (
    DiscordEvent,
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
                "club": press.team.name if press.team_id else "UFL",
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
                "kind": "JOB APPLICATION",
                "title": job.manager.display_name,
                "submitted_by": job.manager.display_name,
                "club": job.team.name,
                "when": job.created_at,
                "status": "PENDING",
                "url": reverse("control_managers"),
            }
        )
    for release in queues.get("pending_releases") or []:
        inbox.append(
            {
                "kind": "RELEASE",
                "title": release.player.name,
                "submitted_by": release.manager.display_name,
                "club": release.team.name,
                "when": release.created_at,
                "status": "PENDING",
                "url": reverse("control_pending"),
                "approve_url": reverse("control_approve_release", args=[release.pk]),
                "reject_url": reverse("control_reject_release", args=[release.pk]),
            }
        )
    if inbox_type == "scores":
        inbox = [row for row in inbox if row["kind"] == "SCORE"]
    elif inbox_type == "transfers":
        inbox = [row for row in inbox if row["kind"] == "TRANSFER"]
    elif inbox_type == "press":
        inbox = [row for row in inbox if row["kind"] == "PRESS"]
    elif inbox_type in {"managers", "applications", "jobs"}:
        inbox = [
            row
            for row in inbox
            if row["kind"] in {"MANAGER APPLICATION", "JOB APPLICATION"}
        ]
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
    manager_clubs = {}
    for team in Team.objects.exclude(manager_id=None).select_related("manager"):
        application = getattr(team.manager, "manager_application", None)
        if application:
            manager_clubs[application.id] = team.name
    for batch in batches:
        batch.payouts = weekly_payout_preview(batch)
        for payout in batch.payouts:
            payout["club"] = manager_clubs.get(payout.get("manager_id"), "—")
    history_rows, total_tokens = weekly_history_rows(batches)
    selected_week = (request.GET.get("week") or "").strip()
    search = (request.GET.get("q") or "").strip().lower()
    week_options = []
    for batch in batches:
        label = batch.week_start.strftime("%d %b %Y") if batch.week_start else ""
        if label and label not in week_options:
            week_options.append(label)
    if selected_week:
        history_rows = [row for row in history_rows if row["week"] == selected_week]
    if search:
        history_rows = [
            row
            for row in history_rows
            if search in " ".join([row["manager"], row["award"], row["club"]]).lower()
        ]
    context = control_shell_context(request, "weekly", queues)
    context.update(
        {
            "weekly_award_batches": batches,
            "history_rows": history_rows,
            "week_options": week_options,
            "selected_week": selected_week,
            "search": request.GET.get("q") or "",
            "total_tokens": total_tokens,
        }
    )
    return render(request, "mgl/control_weekly_awards.html", context)


@owner_admin_required
def control_monthly_awards(request):
    queues = load_queues()
    batches = list(MonthlyAwardBatch.objects.order_by("-month_start")[:16])
    history_rows = monthly_history_rows(batches)
    selected_month = (request.GET.get("month") or "").strip()
    search = (request.GET.get("q") or "").strip().lower()
    month_options = []
    for batch in batches:
        label = batch.month_start.strftime("%B %Y") if batch.month_start else ""
        if label and label not in month_options:
            month_options.append(label)
    if selected_month:
        history_rows = [row for row in history_rows if row["month"] == selected_month]
    if search:
        history_rows = [
            row
            for row in history_rows
            if search in " ".join([str(row["manager"]), row["award"], row["club"]]).lower()
        ]
    context = control_shell_context(request, "monthly", queues)
    context.update(
        {
            "monthly_award_batches": batches,
            "history_rows": history_rows,
            "month_options": month_options,
            "selected_month": selected_month,
            "search": request.GET.get("q") or "",
        }
    )
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
    assignments = list(
        ScoutAssignment.objects.select_related("manager", "manager__user", "player", "club")
        .prefetch_related("reports")
        .order_by("-started_at")[:80]
    )
    movement_rows = scouting_movement_rows(assignments)
    search = (request.GET.get("q") or "").strip().lower()
    selected_from = (request.GET.get("from") or "").strip()
    selected_to = (request.GET.get("to") or "").strip()
    selected_position = (request.GET.get("position") or "").strip()
    if search:
        movement_rows = [
            row
            for row in movement_rows
            if search in " ".join([row["player"], row["to_label"], row["from_label"]]).lower()
        ]
    if selected_from:
        movement_rows = [row for row in movement_rows if row["from_label"] == selected_from]
    if selected_to:
        movement_rows = [row for row in movement_rows if row["to_label"] == selected_to]
    if selected_position:
        movement_rows = [row for row in movement_rows if row["position"] == selected_position]
    context = control_shell_context(request, "scouting", queues)
    context.update(
        {
            "pending_scout_exceptions": queues.get("pending_scout_exceptions") or [],
            "recent_scouts": assignments[:40],
            "movement_rows": movement_rows,
            "search": request.GET.get("q") or "",
            "selected_from": selected_from,
            "selected_to": selected_to,
            "selected_position": selected_position,
            "from_options": sorted({row["from_label"] for row in scouting_movement_rows(assignments)}),
            "to_options": sorted({row["to_label"] for row in scouting_movement_rows(assignments) if row["to_label"]}),
            "position_options": sorted({row["position"] for row in scouting_movement_rows(assignments) if row["position"] != "—"}),
        }
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

    from players.models import Player

    detach_live_club_auction_players()
    queues = load_queues()
    ovr_filter = parse_free_agent_ovr_filter(request.GET.get("ovr"))
    selected_position = (request.GET.get("position") or "all").strip()
    search = (request.GET.get("q") or "").strip()
    unassigned_pool = unassigned_players()
    filtered_unassigned = apply_free_agent_ovr_filter(unassigned_pool, ovr_filter)
    if selected_position and selected_position != "all":
        filtered_unassigned = filtered_unassigned.filter(position=selected_position)
    if search:
        filtered_unassigned = filtered_unassigned.filter(name__icontains=search)
    next_query = f"?ovr={ovr_filter}"
    if selected_position and selected_position != "all":
        next_query += f"&position={selected_position}"
    context = control_shell_context(request, "auctions", queues)
    live = list(queues["live_auctions"])
    manager_auctions = [
        auction for auction in live if getattr(auction, "listing_kind", "") == PlayerAuction.CLUB
    ]
    office_auctions = [
        auction for auction in live if getattr(auction, "listing_kind", "") != PlayerAuction.CLUB
    ]
    context.update(
        {
            "live_auctions": live,
            "manager_auctions": manager_auctions,
            "office_auctions": office_auctions,
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
            "control_next": f"{reverse('control_auctions')}{next_query}",
            "auction_durations": AUCTION_DURATION_CHOICES,
            "position_choices": Player.POSITION_CHOICES,
            "selected_position": selected_position,
            "search": search,
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
    log_user = (request.GET.get("user") or "").strip()
    log_date = (request.GET.get("date") or "").strip()
    kind = (request.GET.get("kind") or "").strip().upper()
    logs = SiteChangeLog.objects.select_related("user").order_by("-created_at")
    if search:
        logs = logs.filter(
            Q(summary__icontains=search)
            | Q(object_label__icontains=search)
            | Q(user__username__icontains=search)
        )
    if action:
        logs = logs.filter(action__icontains=action)
    if log_user:
        logs = logs.filter(user__username=log_user)
    if log_date:
        logs = logs.filter(created_at__date=log_date)
    if kind == "TOKEN":
        logs = logs.filter(
            Q(action__icontains="token")
            | Q(action__icontains="reward")
            | Q(summary__icontains="token")
            | Q(summary__icontains="TKN")
        )
    elif kind == "ADMIN":
        logs = logs.filter(user__role=User.ADMIN)
    elif kind == "OWNER":
        logs = logs.filter(user__role=User.OWNER)
    elif kind == "MANAGER":
        logs = logs.filter(
            Q(user__role=User.MANAGER)
            | Q(summary__icontains="manager")
            | Q(action__icontains="manager")
        )
    elif kind == "CLUB":
        logs = logs.filter(Q(summary__icontains="club") | Q(action__icontains="club"))
    token_activity = RewardTransaction.objects.select_related(
        "manager", "manager__user"
    ).order_by("-created_at")[:60]
    context = control_shell_context(request, "logs", queues)
    context["ocm_audit_log"] = logs[:80]
    context["log_search"] = search
    context["log_action"] = action
    context["log_user"] = log_user
    context["log_date"] = log_date
    context["log_kind"] = kind
    context["action_options"] = list(
        SiteChangeLog.objects.exclude(action="").values_list("action", flat=True).distinct()[:40]
    )
    context["user_options"] = list(
        SiteChangeLog.objects.exclude(user__username__isnull=True)
        .exclude(user__username="")
        .values_list("user__username", flat=True)
        .distinct()[:40]
    )
    context["recent_activity"] = MarketTransaction.objects.select_related(
        "player", "seller", "buyer", "from_team", "to_team", "approved_by"
    ).order_by("-created_at")[:40]
    context["token_activity"] = token_activity
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
    from django.contrib import messages
    from django.shortcuts import redirect

    from mgl.models import HistoricalSeason
    from mgl.permissions import is_owner
    from mgl.season_history import ensure_active_season

    if request.method == "POST" and request.POST.get("action") == "ensure_clubs":
        messages.error(
            request,
            "The 42-club ENSURE CLUBS helper is retired. Use the Season 1 preview. "
            "No clubs were changed.",
        )
        return redirect("control_season_controls")
    if request.method == "POST" and request.POST.get("action") == "season1_bootstrap":
        if not is_owner(request.user):
            messages.error(request, "Only the Owner can apply the Season 1 club bootstrap.")
            return redirect("control_season_controls")
        from mgl.season1 import APPLY_BLOCKED_REASON, CONFIRM_PHRASE

        if (request.POST.get("confirm_text") or "").strip().upper() != CONFIRM_PHRASE:
            messages.error(request, f"Type {CONFIRM_PHRASE} to confirm. No clubs were changed.")
            return redirect("control_season_controls")
        messages.error(request, APPLY_BLOCKED_REASON + " No clubs were changed.")
        return redirect("control_season_controls")

    ensure_active_season()
    from mgl.season1 import preview_season1_bootstrap

    queues = load_queues()
    context = control_shell_context(request, "season_controls", queues)
    context["active_season"] = (
        HistoricalSeason.objects.filter(status=HistoricalSeason.ACTIVE).order_by("-number").first()
    )
    context["is_owner"] = is_owner(request.user)
    context["season1_preview"] = preview_season1_bootstrap()
    return render(request, "mgl/control_season_controls.html", context)


@owner_admin_required
def control_league(request):
    from mgl.market import transfer_window_is_open
    from mgl.season_history import current_season_number
    from mgl.site_cms import get_content, settings_fields

    queues = load_queues()
    fields = settings_fields()
    context = control_shell_context(request, "league", queues)
    context.update(
        {
            "site_name": get_content("settings.site_name"),
            "site_tagline": get_content("settings.site_tagline"),
            "window_open": transfer_window_is_open(),
            "settings_fields": fields,
            "settings_values": {field.key: get_content(field.key) for field in fields},
            "league_teams": Team.objects.select_related("league", "manager").order_by("name"),
            "current_season_number": current_season_number(),
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


def _starting_proposal_view(proposal):
    from mgl.ufl_starting import PLAYERS_PER_CLUB, POSITIONS, SHAPE_COUNTS, squads_from_payload

    if proposal is None:
        return None
    squads = squads_from_payload(proposal.payload or {})
    clubs = []
    for squad in squads:
        grouped = squad.by_position()
        by_position = []
        for position in POSITIONS:
            players = grouped.get(position, [])
            required = SHAPE_COUNTS[position]
            by_position.append(
                {
                    "code": position,
                    "required": required,
                    "have": len(players),
                    "ok": len(players) == required,
                    "players": players,
                }
            )
        clubs.append(
            {
                "squad": squad,
                "by_position": by_position,
                "total_have": len(squad.players),
                "total_required": PLAYERS_PER_CLUB,
                "total_ok": len(squad.players) == PLAYERS_PER_CLUB,
            }
        )
    return {
        "proposal": proposal,
        "clubs": clubs,
        "checks": (proposal.validation or {}).get("checks") or [],
        "problems": (proposal.validation or {}).get("problems") or [],
        "can_approve": proposal.status == proposal.DRAFT
        and bool((proposal.validation or {}).get("ok")),
    }


@owner_admin_required
def control_starting_squads(request):
    from django.contrib import messages
    from django.shortcuts import redirect

    from mgl.models import StartingSquadProposal
    from mgl.permissions import is_owner
    from mgl.ufl_starting import (
        OFFICIAL_STRUCTURE,
        PLAYERS_PER_CLUB,
        approve_proposal,
        create_proposal,
        reject_proposal,
        season_lock,
    )

    owner = is_owner(request.user)
    if request.method == "POST":
        action = request.POST.get("action")
        proposal_id = request.POST.get("proposal")
        proposal = None
        if proposal_id and str(proposal_id).isdigit():
            proposal = StartingSquadProposal.objects.filter(pk=int(proposal_id)).first()
        try:
            if action in {"generate", "regenerate"}:
                if not owner:
                    raise ValueError("Only the Owner can generate a starting-squad proposal.")
                seed_raw = (request.POST.get("seed") or "").strip()
                seed = int(seed_raw) if seed_raw.isdigit() else None
                include_fa = request.POST.get("include_free_agents") == "1"
                created = create_proposal(
                    request.user,
                    seed=seed,
                    include_free_agents=include_fa,
                )
                messages.success(
                    request,
                    f"Proposal {created.pk} generated. Live squads were not changed.",
                )
                return redirect("control_starting_squads")
            if not owner:
                raise ValueError("Only the Owner can change starting-squad proposals.")
            if proposal is None:
                raise ValueError("That proposal was not found.")
            if action == "reject":
                reject_proposal(proposal, request.user)
                messages.success(request, f"Proposal {proposal.pk} rejected. Live squads were not changed.")
            elif action == "approve":
                if request.POST.get("confirm_approval") != "1":
                    raise ValueError("Approval requires explicit confirmation.")
                approved = approve_proposal(proposal, request.user, confirm=True)
                messages.success(
                    request,
                    f"Proposal {approved.pk} approved. Starting squads are now live.",
                )
            else:
                raise ValueError("Unknown starting-squad action.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("control_starting_squads")

    queues = load_queues()
    context = control_shell_context(request, "starting_squads", queues)
    selected_id = request.GET.get("proposal")
    selected = None
    if selected_id and str(selected_id).isdigit():
        selected = StartingSquadProposal.objects.filter(pk=int(selected_id)).first()
    if selected is None:
        selected = StartingSquadProposal.objects.order_by("-id").first()
    context.update(
        {
            "is_owner": owner,
            "lock": season_lock(),
            "history": StartingSquadProposal.objects.select_related("created_by", "approved_by")[:20],
            "selected": _starting_proposal_view(selected),
            "official_structure": OFFICIAL_STRUCTURE,
            "official_squad_size": PLAYERS_PER_CLUB,
        }
    )
    return render(request, "mgl/control_starting_squads.html", context)


@owner_admin_required
def control_recruitment(request):
    from django.contrib import messages
    from django.shortcuts import redirect

    from mgl.models import RecruitmentPack
    from mgl.recruitment import ensure_default_packs, save_recruitment_pack

    ensure_default_packs()
    if request.method == "POST":
        pack_id = request.POST.get("pack_id")
        pack = None
        if pack_id and str(pack_id).isdigit():
            pack = RecruitmentPack.objects.filter(pk=int(pack_id)).first()
        try:
            save_recruitment_pack(
                actor=request.user,
                pack=pack,
                code=request.POST.get("code"),
                name=request.POST.get("name"),
                pack_type=request.POST.get("pack_type") or "POSITION",
                active=request.POST.get("active") == "1",
                token_cost=request.POST.get("token_cost"),
                result_count=request.POST.get("result_count"),
                select_count=request.POST.get("select_count"),
                min_ovr=request.POST.get("min_ovr"),
                max_ovr=request.POST.get("max_ovr"),
                positions=request.POST.get("positions"),
                opening_limit=request.POST.get("opening_limit"),
                sort_order=request.POST.get("sort_order") or 0,
            )
            messages.success(request, "Recruitment pack saved.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("control_recruitment")

    queues = load_queues()
    context = control_shell_context(request, "recruitment", queues)
    context["packs"] = RecruitmentPack.objects.order_by("sort_order", "name", "id")
    return render(request, "mgl/control_recruitment.html", context)


@owner_admin_required
def control_scout_config(request):
    from django.contrib import messages
    from django.shortcuts import redirect

    from mgl.models import LeagueSettings, ScoutLevelConfig
    from mgl.scouting import ensure_default_scout_levels, save_scout_level_config
    from mgl.ufl_settings import get_league_settings

    ensure_default_scout_levels()
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "league":
                if not request.user.role in (User.OWNER, User.ADMIN):
                    raise ValueError("Only the Owner or Admin can edit scout settings.")
                settings = get_league_settings()
                if isinstance(settings, LeagueSettings):
                    settings.scout_can_recruit = request.POST.get("scout_can_recruit") == "1"
                    settings.scout_result_count = int(request.POST.get("scout_result_count") or 4)
                    settings.scout_select_count = int(request.POST.get("scout_select_count") or 1)
                    settings.updated_by = request.user
                    settings.save(
                        update_fields=[
                            "scout_can_recruit",
                            "scout_result_count",
                            "scout_select_count",
                            "updated_by",
                        ]
                    )
                messages.success(request, "Scout league settings saved.")
            else:
                save_scout_level_config(
                    actor=request.user,
                    level=request.POST.get("level"),
                    upgrade_cost=request.POST.get("upgrade_cost"),
                    time_reduction_percent=request.POST.get("time_reduction_percent"),
                    result_count=request.POST.get("result_count"),
                    select_count=request.POST.get("select_count"),
                )
                messages.success(request, "Scout level saved.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("control_scout_config")

    queues = load_queues()
    context = control_shell_context(request, "scout_config", queues)
    context["levels"] = ScoutLevelConfig.objects.order_by("level")
    context["league_settings"] = get_league_settings()
    return render(request, "mgl/control_scout_config.html", context)


def _outbox_queryset(status=""):
    events = DiscordEvent.objects.select_related("news_post").order_by("-created_at", "-id")
    status = (status or "").strip().upper()
    if status in {DiscordEvent.PENDING, DiscordEvent.SENT, DiscordEvent.FAILED}:
        events = events.filter(status=status)
    return events


@owner_admin_required
def control_discord_outbox(request):
    queues = load_queues()
    status = (request.GET.get("status") or "").strip().upper()
    events = _outbox_queryset(status)
    context = control_shell_context(request, "discord_outbox", queues)
    context.update(
        {
            "events": events[:200],
            "outbox_status": status,
            "outbox_counts": {
                "all": DiscordEvent.objects.count(),
                "PENDING": DiscordEvent.objects.filter(status=DiscordEvent.PENDING).count(),
                "SENT": DiscordEvent.objects.filter(status=DiscordEvent.SENT).count(),
                "FAILED": DiscordEvent.objects.filter(status=DiscordEvent.FAILED).count(),
            },
        }
    )
    return render(request, "mgl/control_discord_outbox.html", context)


@owner_admin_required
def control_discord_outbox_detail(request, event_id):
    queues = load_queues()
    event = get_object_or_404(DiscordEvent, pk=event_id)
    context = control_shell_context(request, "discord_outbox", queues)
    context.update(
        {
            "event": event,
            "payload_preview": event_payload_preview(event),
            "can_retry": event.status != DiscordEvent.SENT,
        }
    )
    return render(request, "mgl/control_discord_outbox_detail.html", context)


@owner_admin_required
@require_POST
def control_discord_outbox_retry(request, event_id):
    event = get_object_or_404(DiscordEvent, pk=event_id)
    try:
        retry_discord_event(event)
        messages.success(
            request,
            f"Discord event {event.pk} queued for retry. No football data was changed.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("control_discord_outbox_detail", event_id=event.pk)
