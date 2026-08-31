"""Sunday–Sunday weekly awards from approved MGL match data."""

from collections import defaultdict
from datetime import datetime, time as dt_time, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from mgl.models import (
    AssistEvent,
    GoalEvent,
    MatchSubmission,
    WeeklyAwardBatch,
)
from mgl.notifications import notify_user
from mgl.services import credit_manager, get_or_create_career, manager_for_user
from mgl.totw_service import approve_totw, generate_totw


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


def _award_stat_leader(week_start, event_model, related_name, category, title, amount):
    week_end = week_start + timedelta(days=6)
    rows = (
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
    top = rows.first()
    if not top or not top["total"]:
        return None
    from teams.models import Team

    team = Team.objects.filter(pk=top["team_stats__team_id"]).select_related("manager").first()
    manager = _manager_for_team(team)
    player_name = top["player__name"]
    if manager:
        credit_manager(
            manager,
            amount,
            f"{title}: {player_name}",
            category,
            reference=f"{category.lower()}:{week_start.isoformat()}",
        )
        _notify_reward(
            manager.user,
            f"{category.lower()}-{week_start.isoformat()}",
            title,
            f"Your player {player_name} recorded the most {related_name} this week. Reward: {amount} TOKENS.",
            team=team,
        )
    return top


@transaction.atomic
def run_weekly_awards(week_start=None, now=None):
    """Calculate and pay the previous complete Sunday–Sunday week exactly once."""
    if week_start is None:
        week_start = completed_week_start(now)
    batch, created = WeeklyAwardBatch.objects.get_or_create(week_start=week_start)
    if batch.completed:
        return batch

    notes = []
    totw = None
    try:
        totw = generate_totw(week_start)
        if totw.selections.exists() and not totw.approved:
            approve_totw(totw)
    except ValueError:
        from mgl.models import TeamOfTheWeek

        totw = TeamOfTheWeek.objects.filter(week_start=week_start).first()
    if totw and totw.selections.exists():
        notes.append(f"TOTW {totw.selections.count()} players")
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

    goals = _award_stat_leader(
        week_start,
        GoalEvent,
        "goals",
        "GOALS",
        "MOST GOALS OF THE WEEK",
        Decimal("0.50"),
    )
    if goals:
        notes.append(f"Goals {goals['player__name']} {goals['total']}")
    assists = _award_stat_leader(
        week_start,
        AssistEvent,
        "assists",
        "ASSISTS",
        "MOST ASSISTS OF THE WEEK",
        Decimal("0.50"),
    )
    if assists:
        notes.append(f"Assists {assists['player__name']} {assists['total']}")

    winner = _select_manager_of_week(week_start)
    if winner:
        from mgl.models import ManagerWeek

        row, _ = ManagerWeek.objects.get_or_create(
            week_start=week_start,
            manager=winner["manager"],
            defaults={
                "wins": winner["wins"],
                "reward": Decimal("1.00"),
                "approved": False,
            },
        )
        row.reward = Decimal("1.00")
        row.wins = winner["wins"]
        row.save(update_fields=["reward", "wins"])
        if not row.approved:
            # Pay 1.00 via credit_manager reference, then mark approved without the 0.50 path.
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
        notes.append(f"MOTW {row.manager.display_name}")

    batch.notes = " | ".join(notes) or "No approved weekly activity"
    batch.completed = True
    batch.save(update_fields=["notes", "completed"])
    return batch


def _select_manager_of_week(week_start):
    """Rank by win percentage and points, requiring at least one approved match."""
    stats = defaultdict(lambda: {"played": 0, "wins": 0, "draws": 0, "losses": 0, "gd": 0, "team": None})
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
        if row["played"] < 1:
            continue
        points = row["wins"] * 3 + row["draws"]
        win_pct = row["wins"] / row["played"]
        ranked.append((win_pct, points, row["gd"], row["wins"], row["manager"].id, row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], -item[4]), reverse=True)
    return ranked[0][-1]


def maybe_run_weekly_awards(now=None):
    now = now or timezone.now()
    week_start = completed_week_start(now)
    existing = WeeklyAwardBatch.objects.filter(week_start=week_start).first()
    if existing and existing.completed:
        return None
    close_at = timezone.make_aware(datetime.combine(week_start + timedelta(days=7), dt_time.min))
    if timezone.localtime(now) < timezone.localtime(close_at):
        return None
    return run_weekly_awards(week_start=week_start, now=now)
