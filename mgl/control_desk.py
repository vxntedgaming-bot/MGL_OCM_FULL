"""Shared Owner/Admin Control Centre queues. Reuses existing OCM models only."""

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from auctions.models import PlayerAuction
from managers.models import ManagerApplication
from teams.models import Team

from mgl.market import club_for_user, transfer_offer_details, transfer_window_is_open
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    ManagerNotification,
    MarketTransaction,
    MatchSubmission,
    MonthlyAwardBatch,
    PlayerListing,
    PlayerReleaseRequest,
    RewardTransaction,
    ScoutAssignment,
    ScoutSquadException,
    SiteChangeLog,
    WeeklyAwardBatch,
)
from mgl.press import pending_press_reviews


def annotate_submissions(submissions):
    rows = list(submissions)
    for submission in rows:
        stats = {row.team_id: row for row in submission.team_stats.all()}
        fixture = submission.fixture
        home = stats.get(fixture.home_team_id)
        away = stats.get(fixture.away_team_id)
        submission.home_stats = home
        submission.away_stats = away
        submission.home_goals = getattr(home, "goals", 0)
        submission.away_goals = getattr(away, "goals", 0)
        submission.scoreline = (
            f"{fixture.home_team.name} {submission.home_goals}-"
            f"{submission.away_goals} {fixture.away_team.name}"
        )
    return rows


def pending_listings():
    rows = list(
        PlayerListing.objects.filter(
            status=PlayerListing.PENDING,
            reserved_buyer__isnull=False,
        )
        .select_related(
            "player",
            "team",
            "seller",
            "reserved_buyer",
            "reserved_buyer__user",
            "offered_player",
        )
        .prefetch_related("offered_players")
        .order_by("-id")
    )
    for listing in rows:
        listing.deal = transfer_offer_details(listing)
        listing.warnings = listing_warnings(listing)
    return rows


def listing_warnings(listing):
    warnings = []
    player = listing.player
    if player is None:
        warnings.append("Player record is missing.")
        return warnings
    if player.mgl_team_id and listing.team_id and player.mgl_team_id != listing.team_id:
        warnings.append("Player no longer belongs to the selling club.")
    buyer = listing.reserved_buyer
    buyer_club = club_for_user(buyer.user) if buyer and buyer.user_id else None
    if buyer_club and player.mgl_team_id == buyer_club.id:
        warnings.append("Buyer already owns this player.")
    if not transfer_window_is_open():
        warnings.append("Transfer window is closed.")
    if buyer and listing.asking_price and buyer.tokens < listing.asking_price:
        warnings.append("Buyer does not have enough tokens.")
    if listing.status != PlayerListing.PENDING:
        warnings.append("This listing is not waiting for approval.")
    return warnings


def pending_confirmed_results():
    return annotate_submissions(
        MatchSubmission.objects.filter(
            status=ApprovalStatus.PENDING,
            opponent_response=ApprovalStatus.APPROVED,
        )
        .select_related(
            "fixture__home_team",
            "fixture__away_team",
            "fixture__league",
            "submitted_by",
        )
        .prefetch_related(
            "team_stats__goal_events__player",
            "team_stats__assist_events__player",
            "team_stats__player_ratings__player",
            "team_stats__defender_ratings__player",
            "team_stats__gk_saves__player",
        )
        .order_by("-submitted_at")
    )


def disputed_results():
    return annotate_submissions(
        MatchSubmission.objects.filter(status=ApprovalStatus.PENDING)
        .exclude(opponent_response=ApprovalStatus.APPROVED)
        .select_related(
            "fixture__home_team",
            "fixture__away_team",
            "fixture__league",
            "submitted_by",
        )
        .prefetch_related("team_stats")
        .order_by("-submitted_at")
    )


def pending_counts_from(queues):
    counts = {
        "managers": queues["pending_managers"].count()
        if hasattr(queues["pending_managers"], "count")
        else len(queues["pending_managers"]),
        "listings": len(queues["pending_listings"]),
        "results": len(queues["pending_results"]),
        "jobs": queues["pending_jobs"].count()
        if hasattr(queues["pending_jobs"], "count")
        else len(queues["pending_jobs"]),
        "press": queues["pending_press"].count()
        if hasattr(queues["pending_press"], "count")
        else len(queues["pending_press"]),
        "auctions": queues["live_auctions"].count()
        if hasattr(queues["live_auctions"], "count")
        else len(queues["live_auctions"]),
        "awards": queues["pending_weekly"] + queues["pending_monthly"],
        "weekly": queues["pending_weekly"],
        "monthly": queues["pending_monthly"],
        "disputed": len(queues["disputed_results"]),
        "scouts": queues["active_scouts"],
        "scout_exceptions": len(queues.get("pending_scout_exceptions") or []),
        "releases": len(queues.get("pending_releases") or []),
    }
    counts["approvals"] = (
        counts["managers"]
        + counts["listings"]
        + counts["results"]
        + counts["jobs"]
        + counts["press"]
        + counts["awards"]
        + counts["releases"]
        + counts["scout_exceptions"]
    )
    return counts


def load_queues():
    pending_managers = ManagerApplication.objects.filter(
        status=ManagerApplication.PENDING
    ).select_related("user")
    pending_jobs = ClubApplication.objects.filter(
        status=ApprovalStatus.PENDING
    ).select_related("manager", "manager__user", "team")
    live_auctions = PlayerAuction.objects.filter(
        status=PlayerAuction.LIVE
    ).select_related("player", "winning_manager")
    weekly_pending = WeeklyAwardBatch.objects.filter(
        status=WeeklyAwardBatch.PENDING_REVIEW, completed=False
    ).count()
    monthly_pending = MonthlyAwardBatch.objects.filter(
        status=MonthlyAwardBatch.PENDING_REVIEW, completed=False
    ).count()
    active_scouts = ScoutAssignment.objects.filter(
        status__in=[
            ScoutAssignment.PENDING,
            ScoutAssignment.READY,
            ScoutAssignment.OPENED,
        ]
    ).count()
    pending_releases = list(
        PlayerReleaseRequest.objects.filter(status=ApprovalStatus.PENDING)
        .select_related("player", "team", "manager")
        .order_by("-created_at")
    )
    pending_scout_exceptions = list(
        ScoutSquadException.objects.filter(status=ScoutSquadException.PENDING)
        .select_related("player", "manager", "manager__user", "club", "assignment")
        .order_by("-created_at")
    )
    queues = {
        "pending_managers": pending_managers,
        "pending_listings": pending_listings(),
        "pending_results": pending_confirmed_results(),
        "disputed_results": disputed_results(),
        "pending_jobs": pending_jobs,
        "pending_press": pending_press_reviews(),
        "pending_releases": pending_releases,
        "pending_scout_exceptions": pending_scout_exceptions,
        "live_auctions": live_auctions,
        "pending_weekly": weekly_pending,
        "pending_monthly": monthly_pending,
        "active_scouts": active_scouts,
    }
    queues["pending_counts"] = pending_counts_from(queues)
    return queues


def attention_items(queues, limit=8):
    items = []
    for submission in queues["pending_results"]:
        items.append(
            {
                "kind": "MATCH RESULT",
                "title": submission.scoreline,
                "detail": "Pending Admin Approval",
                "meta": f"{submission.fixture.home_team.name} vs {submission.fixture.away_team.name} · Opponent approved",
                "when": submission.submitted_at,
                "url": reverse("control_scores"),
            }
        )
    for listing in queues["pending_listings"]:
        deal = listing.deal or {}
        items.append(
            {
                "kind": "TRANSFER",
                "title": str(deal.get("player") or listing.player.name),
                "detail": "Pending Approval",
                "meta": (
                    f"{deal.get('current_club') or listing.team.name} → "
                    f"{deal.get('requesting_club') or listing.reserved_buyer.display_name}"
                    f" · {deal.get('amount') or listing.asking_price} TKN"
                    f" · SELLER RECEIVES {deal.get('seller_receives') or listing.asking_price}"
                    f" · BUYER RECEIVES {deal.get('buyer_receives') or listing.player.name}"
                    f" · BUYER {deal.get('buyer_manager') or listing.reserved_buyer.display_name}"
                ),
                "when": getattr(listing, "created_at", None) or timezone.now(),
                "url": reverse("control_transfers"),
            }
        )
    for press in queues["pending_press"]:
        items.append(
            {
                "kind": "PRESS CONFERENCE",
                "title": press.team.name if press.team_id else "UFL",
                "detail": "Pending Approval",
                "meta": press.question,
                "when": press.created_at,
                "url": reverse("control_press"),
            }
        )
    for app in queues["pending_managers"]:
        items.append(
            {
                "kind": "MANAGER APPLICATION",
                "title": app.display_name,
                "detail": "Pending Review",
                "meta": app.preferred_team or app.gamertag,
                "when": app.submitted_at,
                "url": reverse("control_managers"),
            }
        )
    for job in queues["pending_jobs"]:
        items.append(
            {
                "kind": "JOB APPLICATION",
                "title": job.manager.display_name,
                "detail": "Pending Review",
                "meta": job.team.name,
                "when": job.created_at,
                "url": reverse("control_managers"),
            }
        )
    for release in queues.get("pending_releases") or []:
        items.append(
            {
                "kind": "PLAYER RELEASE",
                "title": release.player.name,
                "detail": "Pending Approval",
                "meta": f"{release.team.name} · {release.manager.display_name}",
                "when": release.created_at,
                "url": reverse("control_pending"),
            }
        )
    for batch in WeeklyAwardBatch.objects.filter(
        status=WeeklyAwardBatch.PENDING_REVIEW, completed=False
    ).order_by("-week_start")[:3]:
        items.append(
            {
                "kind": "WEEKLY AWARDS",
                "title": f"Week of {batch.week_start.strftime('%d %b %Y')}",
                "detail": "Awaiting Owner/Admin review",
                "meta": batch.notes or "Calculated — awaiting review",
                "when": batch.created_at,
                "url": reverse("control_weekly_awards"),
            }
        )
    for batch in MonthlyAwardBatch.objects.filter(
        status=MonthlyAwardBatch.PENDING_REVIEW, completed=False
    ).order_by("-month_start")[:3]:
        items.append(
            {
                "kind": "MONTHLY AWARDS",
                "title": batch.month_start.strftime("%B %Y"),
                "detail": "Awaiting Owner/Admin review",
                "meta": batch.notes or "Calculated — awaiting review",
                "when": batch.created_at,
                "url": reverse("control_monthly_awards"),
            }
        )
    items.sort(key=lambda row: row["when"] or timezone.now(), reverse=True)
    return items[:limit]


def weekly_payout_preview(batch):
    payload = batch.payload or {}
    managers = {}

    def bucket(manager_id, name=""):
        key = manager_id or name or "unknown"
        row = managers.get(key)
        if row is None:
            row = {
                "manager_id": manager_id,
                "name": name or "Manager",
                "totw_count": 0,
                "totw": Decimal("0.00"),
                "goals": Decimal("0.00"),
                "assists": Decimal("0.00"),
                "motw": Decimal("0.00"),
            }
            managers[key] = row
        if name and row["name"] == "Manager":
            row["name"] = name
        return row

    for item in payload.get("totw") or []:
        if not item.get("manager_id"):
            continue
        row = bucket(item.get("manager_id"))
        row["totw_count"] += 1
        row["totw"] += Decimal("0.20")
    goals = payload.get("goals") or {}
    winner = goals.get("winner") or {}
    if winner and not goals.get("tied") and winner.get("manager_id"):
        bucket(winner.get("manager_id"))["goals"] = Decimal("0.50")
    assists = payload.get("assists") or {}
    winner = assists.get("winner") or {}
    if winner and not assists.get("tied") and winner.get("manager_id"):
        bucket(winner.get("manager_id"))["assists"] = Decimal("0.50")
    motw = payload.get("motw") or {}
    if motw and not motw.get("tied") and motw.get("manager_id"):
        row = bucket(motw.get("manager_id"), motw.get("manager_name") or "")
        row["motw"] = Decimal("1.00")
    ids = [row["manager_id"] for row in managers.values() if row["manager_id"]]
    names = {
        item.id: item.display_name
        for item in ManagerApplication.objects.filter(pk__in=ids)
    }
    rows = []
    for row in managers.values():
        if row["manager_id"] and row["name"] == "Manager":
            row["name"] = names.get(row["manager_id"], "Manager")
        row["total"] = row["totw"] + row["goals"] + row["assists"] + row["motw"]
        rows.append(row)
    rows.sort(key=lambda item: item["total"], reverse=True)
    return rows


def control_shell_context(request, section, queues=None):
    queues = queues or load_queues()
    return {
        "pending_counts": queues["pending_counts"],
        "control_section": section,
        "is_owner": getattr(request.user, "role", None) == getattr(request.user, "OWNER", "OWNER"),
        "window_open": transfer_window_is_open(),
        "league_status": "Active",
    }


def merge_control_shell(request, section, extra=None):
    context = control_shell_context(request, section)
    if extra:
        context.update(extra)
    return context


def weekly_history_rows(batches):
    rows = []
    total = Decimal("0.00")
    for batch in batches:
        week = batch.week_start.strftime("%d %b %Y") if batch.week_start else "—"
        date = batch.week_start.strftime("%d/%m/%Y") if batch.week_start else "—"
        for payout in getattr(batch, "payouts", []) or []:
            club = payout.get("club") or "—"
            manager = payout.get("name") or "Manager"
            awards = []
            if payout.get("motw"):
                awards.append(("Manager of the Week", payout["motw"]))
            if payout.get("goals"):
                awards.append(("Top Goal Scorer", payout["goals"]))
            if payout.get("assists"):
                awards.append(("Top Assist", payout["assists"]))
            if payout.get("totw"):
                awards.append(("Team of the Week", payout["totw"]))
            if not awards and payout.get("total"):
                awards.append(("Weekly Reward", payout["total"]))
            for award, tokens in awards:
                total += Decimal(str(tokens))
                rows.append(
                    {
                        "week": week,
                        "manager": manager,
                        "club": club,
                        "award": award,
                        "tokens": tokens,
                        "date": date,
                    }
                )
    return rows, total


def monthly_history_rows(batches):
    rows = []
    for batch in batches:
        month = batch.month_start.strftime("%B %Y") if batch.month_start else "—"
        date = batch.month_start.strftime("%d/%m/%Y") if batch.month_start else "—"
        payload = batch.payload or {}
        motm = payload.get("motm") or {}
        if motm:
            rows.append(
                {
                    "month": month,
                    "manager": motm.get("manager_name") or motm,
                    "club": motm.get("club_name") or "—",
                    "award": "Manager of the Month",
                    "tokens": "6",
                    "date": date,
                }
            )
        potm = payload.get("potm") or {}
        if potm:
            rows.append(
                {
                    "month": month,
                    "manager": potm.get("manager_name") or potm.get("player_name") or potm,
                    "club": potm.get("club_name") or "—",
                    "award": "Player of the Month",
                    "tokens": "3",
                    "date": date,
                }
            )
    return rows


def scouting_movement_rows(assignments):
    rows = []
    for assignment in assignments:
        report = next(iter(assignment.reports.all()), None)
        if not assignment.player_id:
            continue
        club = assignment.club or getattr(report, "club", None)
        recruited = bool(report and report.recruited)
        rows.append(
            {
                "player": assignment.player.name,
                "position": assignment.player.position or assignment.position or "—",
                "from_label": "Free Agent",
                "to_label": club.name if club and recruited else (club.name if club else "—"),
                "move_type": "SIGNED" if recruited else ("DISCOVERED" if report else assignment.status),
                "date": (assignment.completed_at or assignment.started_at).strftime("%d/%m/%Y")
                if (assignment.completed_at or assignment.started_at)
                else "—",
                "club_name": club.name if club else "",
            }
        )
    return rows


def control_dashboard_context(request):
    queues = load_queues()
    context = control_shell_context(request, "dashboard", queues)
    context.update(
        {
            "pending_managers": queues["pending_managers"],
            "pending_listings": queues["pending_listings"],
            "pending_results": queues["pending_results"],
            "disputed_results": queues["disputed_results"],
            "pending_jobs": queues["pending_jobs"],
            "pending_press": queues["pending_press"],
            "live_auctions": queues["live_auctions"],
            "attention_items": attention_items(queues),
            "teams": Team.objects.select_related("manager", "league").order_by("name"),
            "recent_activity": MarketTransaction.objects.select_related(
                "player", "seller", "buyer", "from_team", "to_team", "approved_by"
            ).order_by("-created_at")[:8],
            "club_count": Team.objects.count(),
            "manager_count": ManagerApplication.objects.filter(
                status=ManagerApplication.APPROVED
            ).count(),
            "census": {
                "clubs": Team.objects.count(),
                "managers": ManagerApplication.objects.filter(
                    status=ManagerApplication.APPROVED
                ).count(),
                "assigned_players": Team.objects.none(),
            },
            "recent_audit": SiteChangeLog.objects.select_related("user").order_by(
                "-created_at"
            )[:10],
        }
    )
    from players.models import Player
    from mgl.player_state import free_agents
    from mgl.season_history import current_season_number

    context["player_count"] = Player.objects.filter(mgl_team__isnull=False).count()
    context["unsigned_count"] = free_agents().count()
    context["current_season_number"] = current_season_number()
    from mgl.models import DiscordEvent

    context["discord_pending_count"] = DiscordEvent.objects.filter(
        status=DiscordEvent.PENDING
    ).count()
    context["discord_failed_count"] = DiscordEvent.objects.filter(
        status=DiscordEvent.FAILED
    ).count()
    return context
