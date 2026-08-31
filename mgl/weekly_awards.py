"""Sunday–Sunday weekly awards from approved MGL match data.

Calculation is automatic. Token payment waits for Owner/Admin review.
"""

from collections import defaultdict
from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from mgl.audit import log_ocm_action
from mgl.models import (
    AssistEvent,
    GoalEvent,
    MatchSubmission,
    WeeklyAwardBatch,
)
from mgl.notifications import notify_user
from mgl.services import credit_manager, get_or_create_career, manager_for_user
from mgl.totw_service import approve_totw, generate_totw


MOTW_MIN_GAMES = 2


def mgl_week_start(day):
    """Sunday date that opens the MGL week containing `day`."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def completed_week_start(now=None):
    """Week that ended at the most recent Sunday 00:00."""
    now = now or timezone.now()
    local = timezone.localtime(now)
    this_sunday = mgl_week_start(local.date())
    return this_sunday - timedelta(days=7)


def _approved_submissions(week_start):
    week_end = week_start + timedelta(days=6)
    return (
        MatchSubmission.objects.filter(
            status="APPROVED",
            fixture__scheduled_at__date__range=(week_start, week_end),
        )
        .select_related("fixture", "fixture__home_team", "fixture__away_team")
        .prefetch_related("team_stats")
    )


def _manager_for_team(team):
    if team is None or not team.manager_id:
        return None
    return manager_for_user(team.manager)


def _notify_reward(user, source_key, title, message, team=None):
    if user is None:
        return
    notify_user(
        user,
        source_key=source_key,
        notification_type="REWARD",
        title=title,
        message=message,
        actor="MGL Awards",
        team=team,
        action_label="",
        action_url="",
    )


def _notify_admins_review(batch):
    from django.contrib.auth import get_user_model

    UserModel = get_user_model()
    for admin in UserModel.objects.filter(role__in=[User.OWNER, User.ADMIN], is_active=True):
        notify_user(
            admin,
            source_key=f"weekly-review-{batch.week_start.isoformat()}",
            notification_type="AWARD",
            title="WEEKLY AWARDS READY FOR REVIEW",
            message=(
                f"Week of {batch.week_start.isoformat()} is calculated and waiting "
                "for Owner/Admin approval before tokens are released."
            ),
            actor="MGL Awards",
            action_url=reverse("control_centre") + "#awards",
            action_label="REVIEW",
        )


def _stat_leader_payload(week_start, event_model, related_name, category, title, amount):
    week_end = week_start + timedelta(days=6)
    rows = list(
        event_model.objects.filter(
            team_stats__submission__status="APPROVED",
            team_stats__submission__fixture__scheduled_at__date__range=(
                week_start,
                week_end,
            ),
        )
        .values("player_id", "player__name", "team_stats__team_id")
        .annotate(total=Count("id"))
        .order_by("-total", "player__name")
    )
    if not rows or not rows[0]["total"]:
        return None
    top_total = rows[0]["total"]
    tied = [row for row in rows if row["total"] == top_total]
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
    winner = candidates[0] if len(candidates) == 1 else None
    return {
        "category": category,
        "related_name": related_name,
        "title": title,
        "amount": str(amount),
        "tied": winner is None,
        "winner": winner,
        "candidates": candidates,
    }


def _select_manager_of_week(week_start):
    """Rank by win percentage then points. Minimum two approved matches."""
    stats = defaultdict(
        lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gd": 0, "team": None}
    )
    for submission in _approved_submissions(week_start):
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
        return None, False
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], -item[4]), reverse=True)
    top = ranked[0]
    tied = [
        item
        for item in ranked
        if item[0] == top[0] and item[1] == top[1] and item[2] == top[2] and item[3] == top[3]
    ]
    winner = ranked[0][-1]
    payload = {
        "manager_id": winner["manager"].id,
        "manager_name": winner["manager"].display_name,
        "wins": winner["wins"],
        "played": winner["played"],
        "tied": len(tied) > 1,
        "candidates": [
            {
                "manager_id": item[-1]["manager"].id,
                "manager_name": item[-1]["manager"].display_name,
                "wins": item[-1]["wins"],
                "played": item[-1]["played"],
            }
            for item in tied
        ],
    }
    return payload, len(tied) > 1


def _totw_payload(totw):
    if totw is None:
        return []
    rows = []
    for selection in totw.selections.select_related("player", "player__mgl_team"):
        team = selection.player.mgl_team
        manager = _manager_for_team(team)
        rows.append(
            {
                "player_id": selection.player_id,
                "player_name": selection.player.name,
                "slot": selection.slot,
                "manager_id": manager.id if manager else None,
                "team_id": team.id if team else None,
            }
        )
    return rows


@transaction.atomic
def run_weekly_awards(week_start=None, now=None):
    """Calculate the previous complete Sunday–Sunday week. Does not pay tokens."""
    if week_start is None:
        week_start = completed_week_start(now)
    batch, _created = WeeklyAwardBatch.objects.select_for_update().get_or_create(
        week_start=week_start
    )
    if batch.completed or batch.status in {
        WeeklyAwardBatch.PENDING_REVIEW,
        WeeklyAwardBatch.APPROVED,
        WeeklyAwardBatch.REJECTED,
        WeeklyAwardBatch.EMPTY,
    }:
        return batch

    if not _approved_submissions(week_start).exists():
        batch.notes = "No approved weekly activity"
        batch.status = WeeklyAwardBatch.EMPTY
        batch.completed = True
        batch.payload = {}
        batch.has_ties = False
        batch.save()
        return batch

    totw = None
    try:
        totw = generate_totw(week_start)
    except ValueError:
        from mgl.models import TeamOfTheWeek

        totw = TeamOfTheWeek.objects.filter(week_start=week_start).first()

    goals = _stat_leader_payload(
        week_start,
        GoalEvent,
        "goals",
        "GOALS",
        "MOST GOALS OF THE WEEK",
        Decimal("0.50"),
    )
    assists = _stat_leader_payload(
        week_start,
        AssistEvent,
        "assists",
        "ASSISTS",
        "MOST ASSISTS OF THE WEEK",
        Decimal("0.50"),
    )
    motw, motw_tied = _select_manager_of_week(week_start)
    totw_rows = _totw_payload(totw)
    has_ties = bool(
        (goals and goals.get("tied"))
        or (assists and assists.get("tied"))
        or motw_tied
    )
    notes = []
    if totw_rows:
        notes.append(f"TOTW {len(totw_rows)} players")
    if goals:
        names = ", ".join(item["player_name"] for item in goals["candidates"])
        notes.append(f"Goals {names} {goals['candidates'][0]['total']}")
        if goals["tied"]:
            notes.append("Goals tied — admin review")
    if assists:
        names = ", ".join(item["player_name"] for item in assists["candidates"])
        notes.append(f"Assists {names} {assists['candidates'][0]['total']}")
        if assists["tied"]:
            notes.append("Assists tied — admin review")
    if motw:
        notes.append(f"MOTW {motw['manager_name']}")
        if motw["tied"]:
            notes.append("MOTW tied — admin review")

    batch.payload = {
        "totw": totw_rows,
        "goals": goals,
        "assists": assists,
        "motw": motw,
    }
    batch.has_ties = has_ties
    batch.notes = " | ".join(notes) or "Calculated — awaiting review"
    batch.status = WeeklyAwardBatch.PENDING_REVIEW
    batch.completed = False
    batch.save()
    _notify_admins_review(batch)
    return batch


def _pay_leader(week_start, data):
    if not data or data.get("tied") or not data.get("winner"):
        return False
    winner = data["winner"]
    from managers.models import ManagerApplication
    from teams.models import Team

    manager = ManagerApplication.objects.filter(pk=winner.get("manager_id")).first()
    team = Team.objects.filter(pk=winner.get("team_id")).first()
    amount = Decimal(str(data["amount"]))
    if manager:
        credit_manager(
            manager,
            amount,
            f"{data['title']}: {winner['player_name']}",
            data["category"],
            reference=f"{data['category'].lower()}:{week_start.isoformat()}",
        )
        _notify_reward(
            manager.user,
            f"{data['category'].lower()}-{week_start.isoformat()}",
            data["title"],
            (
                f"Your player {winner['player_name']} recorded the most "
                f"{data['related_name']} this week. Reward: {amount} TOKENS."
            ),
            team=team,
        )
    return True


@transaction.atomic
def approve_weekly_awards(batch, reviewer):
    batch = WeeklyAwardBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.completed and batch.status == WeeklyAwardBatch.APPROVED:
        return batch
    if batch.status not in {WeeklyAwardBatch.PENDING_REVIEW, ""}:
        return batch

    week_start = batch.week_start
    payload = batch.payload or {}
    from mgl.models import ManagerWeek, TeamOfTheWeek

    totw = TeamOfTheWeek.objects.filter(week_start=week_start).first()
    if totw and totw.selections.exists() and not totw.approved:
        approve_totw(totw, reviewer)
        by_manager = defaultdict(list)
        for selection in totw.selections.select_related("player", "player__mgl_team"):
            team = selection.player.mgl_team
            manager = _manager_for_team(team)
            if manager:
                by_manager[manager.id].append((manager, team, selection.player.name))
        for rows in by_manager.values():
            manager, team, _ = rows[0]
            names = ", ".join(item[2] for item in rows)
            amount = Decimal("0.20") * len(rows)
            _notify_reward(
                manager.user,
                f"totw-{week_start.isoformat()}-{manager.id}",
                "MGL WEEKLY AWARDS",
                f"Team of the Week: {names} — +{amount} TOKENS.",
                team=team,
            )

    _pay_leader(week_start, payload.get("goals"))
    _pay_leader(week_start, payload.get("assists"))

    motw = payload.get("motw")
    if motw and not motw.get("tied"):
        from managers.models import ManagerApplication

        manager = ManagerApplication.objects.filter(pk=motw["manager_id"]).first()
        if manager:
            row, _ = ManagerWeek.objects.get_or_create(
                week_start=week_start,
                manager=manager,
                defaults={
                    "wins": motw.get("wins") or 0,
                    "reward": Decimal("1.00"),
                    "approved": False,
                },
            )
            row.reward = Decimal("1.00")
            row.wins = motw.get("wins") or 0
            row.save(update_fields=["reward", "wins"])
            if not row.approved:
                credit_manager(
                    row.manager,
                    Decimal("1.00"),
                    "Manager of the Week",
                    "MOTW",
                    reference=f"motw:{week_start.isoformat()}",
                )
                career = get_or_create_career(row.manager)
                career.manager_of_week += 1
                career.save(update_fields=["manager_of_week"])
                row.approved = True
                row.save(update_fields=["approved"])
            _notify_reward(
                row.manager.user,
                f"motw-{week_start.isoformat()}",
                "MGL MANAGER OF THE WEEK",
                f"Congratulations {row.manager.display_name}. Reward: 1.00 TOKEN.",
            )

    batch.status = WeeklyAwardBatch.APPROVED
    batch.completed = True
    batch.reviewed_by = reviewer
    batch.reviewed_at = timezone.now()
    batch.save()
    log_ocm_action(
        reviewer,
        action="weekly.approve",
        object_type="WeeklyAwardBatch",
        object_id=batch.pk,
        object_label=str(week_start),
        new_value="APPROVED",
        summary=f"Approved weekly awards for week of {week_start}.",
    )
    return batch


@transaction.atomic
def reject_weekly_awards(batch, reviewer):
    batch = WeeklyAwardBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == WeeklyAwardBatch.APPROVED:
        return batch
    batch.status = WeeklyAwardBatch.REJECTED
    batch.completed = True
    batch.reviewed_by = reviewer
    batch.reviewed_at = timezone.now()
    batch.save()
    log_ocm_action(
        reviewer,
        action="weekly.reject",
        object_type="WeeklyAwardBatch",
        object_id=batch.pk,
        object_label=str(batch.week_start),
        new_value="REJECTED",
        summary=f"Rejected weekly awards for week of {batch.week_start}.",
    )
    return batch


@transaction.atomic
def recalculate_weekly_awards(batch, reviewer):
    batch = WeeklyAwardBatch.objects.select_for_update().get(pk=batch.pk)
    if batch.status == WeeklyAwardBatch.APPROVED:
        raise ValueError("Approved weekly awards cannot be recalculated.")
    from mgl.models import TeamOfTheWeek

    totw = TeamOfTheWeek.objects.filter(week_start=batch.week_start, approved=False).first()
    if totw:
        totw.selections.all().delete()
        totw.delete()
    batch.status = ""
    batch.completed = False
    batch.has_ties = False
    batch.payload = {}
    batch.notes = ""
    batch.save()
    log_ocm_action(
        reviewer,
        action="weekly.recalculate",
        object_type="WeeklyAwardBatch",
        object_id=batch.pk,
        object_label=str(batch.week_start),
        summary=f"Recalculated weekly awards for week of {batch.week_start}.",
    )
    return run_weekly_awards(week_start=batch.week_start)


def maybe_run_weekly_awards(now=None):
    now = now or timezone.now()
    week_start = completed_week_start(now)
    existing = WeeklyAwardBatch.objects.filter(week_start=week_start).first()
    if existing and (
        existing.completed
        or existing.status
        in {
            WeeklyAwardBatch.PENDING_REVIEW,
            WeeklyAwardBatch.APPROVED,
            WeeklyAwardBatch.REJECTED,
            WeeklyAwardBatch.EMPTY,
        }
    ):
        return None
    close_at = timezone.make_aware(datetime.combine(week_start + timedelta(days=7), dt_time.min))
    if timezone.localtime(now) < timezone.localtime(close_at):
        return None
    return run_weekly_awards(week_start=week_start, now=now)
