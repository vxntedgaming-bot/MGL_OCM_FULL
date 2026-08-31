from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from managers.models import ManagerApplication

from .models import (
    Fixture,
    MatchSubmission,
    ManagerWeek,
    TeamOfTheWeek,
    TOTWSelection,
)
from .services import (
    credit_manager,
    get_or_create_career,
    normalise_totw_position,
)


TOTW_SLOTS = [
    ("GK", "GK"),

    ("LB", "LB"),

    ("CB1", "CB"),
    ("CB2", "CB"),

    ("RB", "RB"),

    ("CM1", "CM"),
    ("CM2", "CM"),

    ("LM", "LM"),
    ("CAM", "CAM"),
    ("RM", "RM"),

    ("ST", "ST"),
]


def week_range(week_start):
    return week_start, week_start + timedelta(days=6)


def player_score(player, week_start, week_end):
    """
    Calculate a TOTW performance score from approved matches.

    This deliberately uses only approved match submissions.
    """

    score = 0.0

    goals = 0
    assists = 0
    appearances = 0
    defender_rating_total = 0.0
    defender_rating_count = 0
    saves = 0

    submissions = (
        MatchSubmission.objects
        .filter(
            status="APPROVED",
            fixture__scheduled_at__date__range=(
                week_start,
                week_end,
            ),
        )
        .prefetch_related(
            "team_stats__goal_events",
            "team_stats__assist_events",
            "team_stats__defender_ratings",
            "team_stats__gk_saves",
            "team_stats__player_ratings",
        )
    )

    for submission in submissions:

        participated = False

        for team_stats in submission.team_stats.all():

            for event in team_stats.goal_events.all():
                if event.player_id == player.id:
                    goals += 1
                    participated = True

            for event in team_stats.assist_events.all():
                if event.player_id == player.id:
                    assists += 1
                    participated = True

            for rating in team_stats.defender_ratings.all():
                if rating.player_id == player.id:
                    defender_rating_total += float(rating.rating)
                    defender_rating_count += 1
                    participated = True

            for save in team_stats.gk_saves.all():
                if save.player_id == player.id:
                    saves += save.saves
                    participated = True

            for rating in team_stats.player_ratings.all():
                if rating.player_id == player.id:
                    defender_rating_total += float(rating.rating)
                    defender_rating_count += 1
                    participated = True

        if participated:
            appearances += 1

    if appearances == 0:
        return 0.0

    score += goals * 6
    score += assists * 4
    score += appearances * 2

    if defender_rating_count:
        score += (
            defender_rating_total /
            defender_rating_count
        ) * 2

    score += saves * 0.5

    score += float(player.overall or 0) * 0.1

    return score


@transaction.atomic
def generate_totw(week_start):
    """
    Generate an unapproved Team of the Week.

    Admin must approve it before rewards are paid.
    """

    week_end = week_start + timedelta(days=6)

    totw, created = TeamOfTheWeek.objects.get_or_create(
        week_start=week_start,
        defaults={
            "formation": "4-2-3-1",
            "approved": False,
        },
    )

    if totw.approved:
        raise ValueError(
            "This Team of the Week has already been approved."
        )

    TOTWSelection.objects.filter(totw=totw).delete()

    from players.models import Player

    players = Player.objects.filter(
        mgl_team__isnull=False
    ).select_related(
        "mgl_team",
        "mgl_team__manager",
    )

    candidates = defaultdict(list)

    for player in players:

        position = normalise_totw_position(
            player.position
        )

        if position not in {
            "GK",
            "LB",
            "CB",
            "RB",
            "CM",
            "LM",
            "CAM",
            "RM",
            "ST",
        }:
            continue

        score = player_score(
            player,
            week_start,
            week_end,
        )

        candidates[position].append(
            (score, player)
        )

    selected_players = set()

    for slot, position in TOTW_SLOTS:

        available = [
            item
            for item in candidates[position]
            if item[1].id not in selected_players
        ]

        available.sort(
            key=lambda item: (
                item[0],
                item[1].overall or 0,
                item[1].name,
            ),
            reverse=True,
        )

        if not available:
            continue

        score, player = available[0]
        if score <= 0:
            continue

        TOTWSelection.objects.create(
            totw=totw,
            slot=slot,
            player=player,
            manager_reward=Decimal("0.20"),
        )

        selected_players.add(player.id)

    return totw


@transaction.atomic
def approve_totw(totw, reviewer=None):
    """
    Approve TOTW and pay each selected player's manager exactly once.
    """

    totw = (
        TeamOfTheWeek.objects
        .select_for_update()
        .get(pk=totw.pk)
    )

    if totw.approved:
        raise ValueError(
            "This TOTW has already been approved."
        )

    selections = list(
        totw.selections.select_related(
            "player",
            "player__mgl_team",
            "player__mgl_team__manager",
        )
    )

    for selection in selections:

        team = selection.player.mgl_team

        if not team or not team.manager_id:
            continue

        try:
            manager = ManagerApplication.objects.get(
                user_id=team.manager_id
            )
        except ManagerApplication.DoesNotExist:
            continue

        credit_manager(
            manager,
            Decimal("0.20"),
            f"TOTW selection: {selection.player.name}",
            "TOTW",
            reference=f"totw:{totw.week_start.isoformat()}:{selection.player_id}",
        )

    totw.approved = True
    totw.save(update_fields=["approved"])

    return totw


@transaction.atomic
def generate_manager_of_week(week_start):
    """
    Calculate Manager of the Week from approved results.
    """

    week_end = week_start + timedelta(days=6)

    fixtures = (
        Fixture.objects
        .filter(
            status="COMPLETED",
            scheduled_at__date__range=(
                week_start,
                week_end,
            ),
        )
        .select_related(
            "home_team",
            "away_team",
            "home_team__manager",
            "away_team__manager",
            "submission",
        )
        .prefetch_related(
            "submission__team_stats",
        )
    )

    wins = defaultdict(int)

    for fixture in fixtures:

        try:
            submission = fixture.submission
        except MatchSubmission.DoesNotExist:
            continue

        if submission.status != "APPROVED":
            continue

        stats = {
            x.team_id: x
            for x in submission.team_stats.all()
        }

        home = stats.get(fixture.home_team_id)
        away = stats.get(fixture.away_team_id)

        if not home or not away:
            continue

        if home.goals > away.goals:
            if fixture.home_team.manager_id:
                wins[fixture.home_team.manager_id] += 1

        elif away.goals > home.goals:
            if fixture.away_team.manager_id:
                wins[fixture.away_team.manager_id] += 1

    ManagerWeek.objects.filter(
        week_start=week_start
    ).delete()

    rows = []

    for manager_user_id, win_count in wins.items():

        try:
            manager = ManagerApplication.objects.get(
                user_id=manager_user_id
            )
        except ManagerApplication.DoesNotExist:
            continue

        rows.append(
            ManagerWeek.objects.create(
                week_start=week_start,
                manager=manager,
                wins=win_count,
        reward=Decimal("1.00"),
                approved=False,
            )
        )

    rows.sort(
        key=lambda row: (
            row.wins,
            -row.manager.id,
        ),
        reverse=True,
    )

    return rows


@transaction.atomic
def approve_manager_of_week(manager_week):
    """
    Approve MOTW and award +1.00 token exactly once.
    """

    manager_week = (
        ManagerWeek.objects
        .select_for_update()
        .get(pk=manager_week.pk)
    )

    if manager_week.approved:
        raise ValueError(
            "Manager of the Week has already been approved."
        )

    credit_manager(
        manager_week.manager,
        Decimal("1.00"),
        "Manager of the Week",
        "MOTW",
        reference=f"motw:{manager_week.week_start.isoformat()}",
    )

    career = get_or_create_career(
        manager_week.manager
    )

    career.manager_of_week += 1
    career.save(update_fields=["manager_of_week"])

    manager_week.approved = True
    manager_week.save(update_fields=["approved"])

    return manager_week
