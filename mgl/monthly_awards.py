"""Calendar-month awards from official approved matches. Tokens wait for admin review."""

from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from mgl.audit import log_ocm_action
from mgl.models import AssistEvent, GoalEvent, MatchSubmission, MonthlyAwardBatch
from mgl.notifications import notify_user
from mgl.services import credit_manager
from mgl.weekly_awards import MOTW_MIN_GAMES, _manager_for_team, _notify_reward


def month_start(day):
    return date(day.year, day.month, 1)


def completed_month_start(now=None):
    now = now or timezone.now()
    local = timezone.localtime(now).date()
    first = month_start(local)
    previous = first - timedelta(days=1)
    return month_start(previous)


def _month_range(start):
    last = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start, last


def _approved_submissions(start):
    first, last = _month_range(start)
    return (
        MatchSubmission.objects.filter(
            status="APPROVED",
            fixture__scheduled_at__date__range=(first, last),
        )
        .select_related("fixture", "fixture__home_team", "fixture__away_team")
        .prefetch_related("team_stats")
    )


def _stat_leader(start, event_model):
    first, last = _month_range(start)
    rows = list(
        event_model.objects.filter(
            team_stats__submission__status="APPROVED",
            team_stats__submission__fixture__scheduled_at__date__range=(first, last),
        )
        .values("player_id", "player__name", "team_stats__team_id")
        .annotate(total=Count("id"))
        .order_by("-total", "player__name")
    )
    if not rows or not rows[0]["total"]:
        return None
    top = rows[0]["total"]
    tied = [row for row in rows if row["total"] == top]
    from teams.models import Team

    candidates = []
    for row in tied:
        team = Team.objects.filter(pk=row["team_stats__team_id"]).select_related("manager").first()
        manager = _manager_for_team(team)
        candidates.append(
            {
                "player_id": row["player_id"],
                "player_name": row["player__name"],
                "total": row["total"],
                "team_id": row["team_stats__team_id"],
                "manager_id": manager.id if manager else None,
            }
        )
    return {
        "tied": len(candidates) > 1,
        "winner": candidates[0] if len(candidates) == 1 else None,
        "candidates": candidates,
    }


def _select_manager_of_month(start):
    stats = defaultdict(
        lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gd": 0}
    )
    for submission in _approved_submissions(start):
        fixture = submission.fixture
        team_rows = {row.team_id: row for row in submission.team_stats.all()}
        home = team_rows.get(fixture.home_team_id)
        away = team_rows.get(fixture.away_team_id)
        if not home or not away:
            continue
        pairs = (
            (fixture.home_team, home.goals, away.goals),
            (fixture.away_team, away.goals, home.goals),
        )
        for team, scored, conceded in pairs:
            manager = _manager_for_team(team)
            if manager is None:
                continue
            row = stats[manager.id]
            row["manager"] = manager
            row["team"] = team
            row["played"] += 1
            row["gd"] += scored - conceded
            if scored > conceded:
                row["wins"] += 1
            elif scored == conceded:
                row["draws"] += 1
            else:
                row["losses"] += 1
    ranked = []
    for row in stats.values():
        if row["played"] < MOTW_MIN_GAMES:
            continue
        points = row["wins"] * 3 + row["draws"]
        win_pct = row["wins"] / row["played"]
        ranked.append((win_pct, points, row["gd"], row["wins"], row["manager"].id, row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], -item[4]), reverse=True)
    top = ranked[0]
    tied = [
        item
        for item in ranked
        if item[0] == top[0] and item[1] == top[1] and item[2] == top[2] and item[3] == top[3]
    ]
    winner = ranked[0][-1]
    return {
        "manager_id": winner["manager"].id,
        "manager_name": winner["manager"].display_name,
        "wins": winner["wins"],
        "played": winner["played"],
        "tied": len(tied) > 1,
        "candidates": [
            {
                "manager_id": item[-1]["manager"].id,
                "manager_name": item[-1]["manager"].display_name,
            }
            for item in tied
        ],
    }


@transaction.atomic
def run_monthly_awards(month=None, now=None):
    if month is None:
        month = completed_month_start(now)
    batch, _ = MonthlyAwardBatch.objects.select_for_update().get_or_create(month_start=month)
    if batch.completed or batch.status in {
        MonthlyAwardBatch.PENDING_REVIEW,
        MonthlyAwardBatch.APPROVED,
        MonthlyAwardBatch.REJECTED,
        MonthlyAwardBatch.EMPTY,
    }:
        return batch
    if not _approved_submissions(month).exists():
        batch.status = MonthlyAwardBatch.EMPTY
        batch.completed = True
        batch.notes = "No approved monthly activity"
        batch.save()
        return batch
    motm = _select_manager_of_month(month)
    potm = _stat_leader(month, GoalEvent)
    if potm is None:
        potm = _stat_leader(month, AssistEvent)
        if potm:
            potm["source"] = "assists"
    elif potm:
        potm["source"] = "goals"
    has_ties = bool((motm and motm.get("tied")) or (potm and potm.get("tied")))
    notes = []
    if motm:
        notes.append(f"MOTM {motm['manager_name']}")
        if motm["tied"]:
            notes.append("MOTM tied — admin review")
    if potm and potm.get("winner"):
        notes.append(f"POTM {potm['winner']['player_name']}")
    elif potm and potm.get("tied"):
        notes.append("POTM tied — admin review")
    batch.payload = {"motm": motm, "potm": potm}
    batch.has_ties = has_ties
    batch.notes = " | ".join(notes) or "Calculated — awaiting review"
    batch.status = MonthlyAwardBatch.PENDING_REVIEW
    batch.completed = False
    batch.save()
    for admin in User.objects.filter(role__in=[User.OWNER, User.ADMIN], is_active=True):
        notify_user(
            admin,
            source_key=f"monthly-review-{month.isoformat()}",
            notification_type="AWARD",
            title="MONTHLY AWARDS READY FOR REVIEW",
            message=(
                f"Awards for {month.strftime('%B %Y')} are calculated and waiting "
                "for Owner/Admin approval before tokens are released."
            ),
            actor="MGL Awards",
            action_url=reverse("control_monthly_awards"),
            action_label="REVIEW",
        )
    return batch


@transaction.atomic
def approve_monthly_awards(batch, reviewer):
    batch = MonthlyAwardBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.completed and batch.status == MonthlyAwardBatch.APPROVED:
        return batch
    if batch.status not in {MonthlyAwardBatch.PENDING_REVIEW, ""}:
        return batch
    payload = batch.payload or {}
    month = batch.month_start
    motm = payload.get("motm") or {}
    if motm and not motm.get("tied"):
        from managers.models import ManagerApplication

        manager = ManagerApplication.objects.filter(pk=motm.get("manager_id")).first()
        if manager:
            credit_manager(
                manager,
                Decimal("6.00"),
                "Manager of the Month",
                "MOTM",
                reference=f"motm:{month.isoformat()}",
            )
            _notify_reward(
                manager.user,
                f"motm-{month.isoformat()}",
                "MGL MANAGER OF THE MONTH",
                f"Congratulations {manager.display_name}. Reward: 6.00 TOKENS.",
            )
    potm = payload.get("potm") or {}
    winner = potm.get("winner") if not potm.get("tied") else None
    if winner and winner.get("manager_id"):
        from managers.models import ManagerApplication
        from teams.models import Team

        manager = ManagerApplication.objects.filter(pk=winner["manager_id"]).first()
        team = Team.objects.filter(pk=winner.get("team_id")).first()
        if manager:
            credit_manager(
                manager,
                Decimal("3.00"),
                f"Player of the Month: {winner['player_name']}",
                "POTM",
                reference=f"potm:{month.isoformat()}",
            )
            _notify_reward(
                manager.user,
                f"potm-{month.isoformat()}",
                "MGL PLAYER OF THE MONTH",
                (
                    f"Your player {winner['player_name']} is Player of the Month. "
                    "Reward: 3.00 TOKENS."
                ),
                team=team,
            )
    batch.status = MonthlyAwardBatch.APPROVED
    batch.completed = True
    batch.reviewed_by = reviewer
    batch.reviewed_at = timezone.now()
    batch.save()
    log_ocm_action(
        reviewer,
        action="monthly.approve",
        object_type="MonthlyAwardBatch",
        object_id=batch.pk,
        object_label=str(month),
        new_value="APPROVED",
        summary=f"Approved monthly awards for {month.strftime('%B %Y')}.",
    )
    return batch


def maybe_run_monthly_awards(now=None):
    now = now or timezone.now()
    month = completed_month_start(now)
    existing = MonthlyAwardBatch.objects.filter(month_start=month).first()
    if existing and (
        existing.completed
        or existing.status
        in {
            MonthlyAwardBatch.PENDING_REVIEW,
            MonthlyAwardBatch.APPROVED,
            MonthlyAwardBatch.REJECTED,
            MonthlyAwardBatch.EMPTY,
        }
    ):
        return None
    first_of_this = month_start(timezone.localtime(now).date())
    close_at = timezone.make_aware(datetime.combine(first_of_this, dt_time.min))
    if timezone.localtime(now) < timezone.localtime(close_at):
        return None
    return run_monthly_awards(month=month, now=now)
