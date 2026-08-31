"""Shared Owner/Admin Control Centre queues. Reuses existing OCM models only."""

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from auctions.models import PlayerAuction
from managers.models import ManagerApplication
from teams.models import Team

from mgl.market import transfer_offer_details, transfer_window_is_open
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    ManagerNotification,
    MarketTransaction,
    MatchSubmission,
    MonthlyAwardBatch,
    PlayerListing,
    RewardTransaction,
    ScoutAssignment,
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
    return rows


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
    }
    counts["approvals"] = (
        counts["managers"]
        + counts["listings"]
        + counts["results"]
        + counts["jobs"]
        + counts["press"]
        + counts["awards"]
    )
    return counts


def load_queues():
    pending_managers = ManagerApplication.objects.filter(
        status=ManagerApplication.PENDING
    ).select_related("user")
    pending_jobs = ClubApplication.objects.filter(
        status=ApprovalStatus.PENDING
    ).select_related("manager", "team")
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
    queues = {
        "pending_managers": pending_managers,
        "pending_listings": pending_listings(),
        "pending_results": pending_confirmed_results(),
        "disputed_results": disputed_results(),
        "pending_jobs": pending_jobs,
        "pending_press": pending_press_reviews(),
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
                "title": press.team.name if press.team_id else "MGL",
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
                "kind": "CLUB APPLICATION",
                "title": job.manager.display_name,
                "detail": "Pending Review",
                "meta": job.team.name,
                "when": job.created_at,
                "url": reverse("control_managers"),
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
        }
    )
    from players.models import Player

    context["player_count"] = Player.objects.filter(mgl_team__isnull=False).count()
    return context
