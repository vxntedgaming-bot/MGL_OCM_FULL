"""Apply or reverse official match statistics exactly once per submission."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from accounts.models import User
from managers.models import ManagerApplication
from mgl.audit import log_ocm_action
from mgl.models import (
    ApprovalStatus,
    DefenderRating,
    GKSave,
    HistoricalSeason,
    MatchSubmission,
    NewsPost,
    PlayerMatchRating,
)
from mgl.services import create_news, credit_manager, debit_manager, get_or_create_career
from players.models import Player


def season_is_locked(season_number):
    return HistoricalSeason.objects.filter(
        number=season_number,
        is_locked=True,
    ).exists()


def _match_result(home_stats, away_stats):
    if home_stats.goals == away_stats.goals:
        return "DRAW"
    if home_stats.goals > away_stats.goals:
        return "HOME_WIN"
    return "AWAY_WIN"


def _load_stats(sub):
    fixture = sub.fixture
    stats = list(
        sub.team_stats.select_related("team").prefetch_related(
            "goal_events__player",
            "assist_events__player",
            "defender_ratings__player",
            "gk_saves__player",
            "player_ratings__player",
        )
    )
    home_stats = next((row for row in stats if row.team_id == fixture.home_team_id), None)
    away_stats = next((row for row in stats if row.team_id == fixture.away_team_id), None)
    return stats, home_stats, away_stats


def _manager_for_team(team):
    if not team or not team.manager_id:
        return None
    return ManagerApplication.objects.filter(user_id=team.manager_id).first()


def _career_delta(result, side):
    if result == "DRAW":
        return "draws"
    if (result == "HOME_WIN" and side == "home") or (result == "AWAY_WIN" and side == "away"):
        return "wins"
    return "losses"


def _adjust_career(manager, field, delta):
    if manager is None:
        return
    career = get_or_create_career(manager)
    value = max(0, getattr(career, field, 0) + delta)
    setattr(career, field, value)
    career.save(update_fields=[field])


def _refresh_average_rating(player_id):
    player = Player.objects.filter(pk=player_id).first()
    if player is None:
        return
    approved = {"team_stats__submission__status": ApprovalStatus.APPROVED}
    values = []
    def_avg = DefenderRating.objects.filter(player_id=player_id, **approved).aggregate(
        avg=Avg("rating")
    )["avg"]
    extra = PlayerMatchRating.objects.filter(player_id=player_id, **approved).aggregate(
        avg=Avg("rating")
    )["avg"]
    gk = GKSave.objects.filter(
        player_id=player_id, rating__isnull=False, **approved
    ).aggregate(avg=Avg("rating"))["avg"]
    for value in (def_avg, extra, gk):
        if value is not None:
            values.append(Decimal(str(value)))
    player.average_rating = (
        (sum(values) / len(values)).quantize(Decimal("0.01")) if values else Decimal("0.00")
    )
    player.save(update_fields=["average_rating"])


def _touch_players(stats):
    ids = set()
    for team_stats in stats:
        for event in team_stats.goal_events.all():
            ids.add(event.player_id)
        for event in team_stats.assist_events.all():
            ids.add(event.player_id)
        for row in team_stats.defender_ratings.all():
            ids.add(row.player_id)
        for row in team_stats.gk_saves.all():
            ids.add(row.player_id)
        for row in team_stats.player_ratings.all():
            ids.add(row.player_id)
    return ids


def apply_match_statistics(sub):
    """Increment player and manager career totals from this submission. Idempotent."""
    if sub.stats_applied:
        return
    stats, home_stats, away_stats = _load_stats(sub)
    if not home_stats or not away_stats:
        raise ValueError("Both teams must have match statistics before approval.")
    result = _match_result(home_stats, away_stats)
    touched = _touch_players(stats)
    for team_stats in stats:
        for event in team_stats.goal_events.all():
            player = event.player
            player.goals = (player.goals or 0) + 1
            player.save(update_fields=["goals"])
        for event in team_stats.assist_events.all():
            player = event.player
            player.assists = (player.assists or 0) + 1
            player.save(update_fields=["assists"])
    for player_id in touched:
        player = Player.objects.get(pk=player_id)
        player.appearances = (player.appearances or 0) + 1
        player.save(update_fields=["appearances"])
        _refresh_average_rating(player_id)
    fixture = sub.fixture
    _adjust_career(_manager_for_team(fixture.home_team), _career_delta(result, "home"), 1)
    _adjust_career(_manager_for_team(fixture.away_team), _career_delta(result, "away"), 1)
    sub.stats_applied = True
    sub.save(update_fields=["stats_applied"])


def reverse_match_statistics(sub):
    """Undo player and manager career totals from this submission. Idempotent."""
    if not sub.stats_applied:
        return
    stats, home_stats, away_stats = _load_stats(sub)
    if home_stats and away_stats:
        result = _match_result(home_stats, away_stats)
        fixture = sub.fixture
        _adjust_career(_manager_for_team(fixture.home_team), _career_delta(result, "home"), -1)
        _adjust_career(_manager_for_team(fixture.away_team), _career_delta(result, "away"), -1)
        for team_stats in stats:
            for event in team_stats.goal_events.all():
                player = event.player
                player.goals = max(0, (player.goals or 0) - 1)
                player.save(update_fields=["goals"])
            for event in team_stats.assist_events.all():
                player = event.player
                player.assists = max(0, (player.assists or 0) - 1)
                player.save(update_fields=["assists"])
        for player_id in _touch_players(stats):
            player = Player.objects.get(pk=player_id)
            player.appearances = max(0, (player.appearances or 0) - 1)
            player.save(update_fields=["appearances"])
            _refresh_average_rating(player_id)
    sub.stats_applied = False
    sub.save(update_fields=["stats_applied"])


def reverse_match_tokens(sub, reviewer=None):
    """Claw back the +1 match rewards without deleting the original ledger rows."""
    from mgl.models import RewardTransaction

    fixture = sub.fixture
    now = timezone.now()
    for manager, side in (
        (_manager_for_team(fixture.home_team), "home"),
        (_manager_for_team(fixture.away_team), "away"),
    ):
        if manager is None:
            continue
        original = RewardTransaction.objects.select_for_update().filter(
            manager=manager,
            category="MATCH",
            reference=f"match:{fixture.id}:{side}",
            reversed_at__isnull=True,
        ).first()
        if original is None:
            continue
        debit_manager(
            manager,
            original.amount,
            f"Rollback: {original.reason}",
            category="MATCH",
            fixture=fixture,
            reference=f"match-rollback:{original.id}",
            created_by=reviewer,
            reverses=original,
            allow_negative=True,
        )
        original.reversed_at = now
        original.save(update_fields=["reversed_at"])


def _pay_match_tokens(sub):
    fixture = sub.fixture
    home_manager = _manager_for_team(fixture.home_team)
    away_manager = _manager_for_team(fixture.away_team)
    if home_manager:
        credit_manager(
            home_manager,
            Decimal("1.00"),
            "Approved league match",
            "MATCH",
            fixture,
            reference=f"match:{fixture.id}:home",
        )
    if away_manager and (
        home_manager is None or away_manager.id != home_manager.id
    ):
        credit_manager(
            away_manager,
            Decimal("1.00"),
            "Approved league match",
            "MATCH",
            fixture,
            reference=f"match:{fixture.id}:away",
        )


@transaction.atomic
def approve_match_submission(sub, reviewer, override=False):
    """Approve one match exactly once. Official stats, table, and tokens update here."""
    sub = (
        MatchSubmission.objects.select_for_update()
        .select_related("fixture", "fixture__home_team", "fixture__away_team")
        .get(pk=sub.pk)
    )
    if sub.status == ApprovalStatus.APPROVED:
        return False, "Match is no longer pending."
    if sub.status != ApprovalStatus.PENDING:
        return False, "Match is no longer pending."
    is_owner = getattr(reviewer, "role", None) == User.OWNER
    if sub.opponent_response != ApprovalStatus.APPROVED:
        if not (override and is_owner):
            return False, "The opposing manager must approve this result first."
    fixture = sub.fixture
    if season_is_locked(fixture.season_number):
        return False, "This season is locked. Unlock it before changing official results."
    stats, home_stats, away_stats = _load_stats(sub)
    if not home_stats or not away_stats:
        raise ValueError("Both teams must have match statistics before approval.")

    apply_match_statistics(sub)
    _pay_match_tokens(sub)

    sub.status = ApprovalStatus.APPROVED
    sub.reviewed_by = reviewer
    sub.reviewed_at = timezone.now()
    sub.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    fixture.status = "COMPLETED"
    fixture.save(update_fields=["status"])

    create_news(
        NewsPost.RESULTS,
        (
            f"{fixture.home_team.name} "
            f"{home_stats.goals}–{away_stats.goals} "
            f"{fixture.away_team.name}"
        ),
        (
            f"Result approved by Admin.\n"
            f"Gameweek {fixture.matchweek}.\n\n"
            f"{fixture.home_team.name} {home_stats.goals}–{away_stats.goals} "
            f"{fixture.away_team.name}\n\n"
            f"Shots: {home_stats.shots} - {away_stats.shots}\n"
            f"Possession: {home_stats.possession}% - "
            f"{away_stats.possession}%"
        ),
        team=fixture.home_team,
        secondary_team=fixture.away_team,
    )
    from mgl.press import create_match_press_questions, maybe_create_odd_matchday_interview

    create_match_press_questions(fixture, home_stats, away_stats)
    maybe_create_odd_matchday_interview(fixture)

    from django.urls import reverse

    from mgl.models import ManagerNotification
    from mgl.notifications import close_admin_result_notices, notify_user

    close_admin_result_notices(sub, ManagerNotification.ACCEPTED)
    scoreline = (
        f"{fixture.home_team.name} {home_stats.goals}–{away_stats.goals} "
        f"{fixture.away_team.name}"
    )
    for manager_user, club in (
        (fixture.home_team.manager, fixture.home_team),
        (fixture.away_team.manager, fixture.away_team),
    ):
        notify_user(
            manager_user,
            source_key=f"score-approved-{sub.pk}",
            notification_type="SCORE",
            title="RESULT APPROVED",
            message=f"{scoreline} has been approved and is now official. +1.00 TOKEN awarded.",
            actor="UFL Admin",
            action_url=reverse("fixture_list"),
            action_label="VIEW FIXTURES",
            team=club,
        )
    log_ocm_action(
        reviewer,
        action="match.approve",
        object_type="MatchSubmission",
        object_id=sub.pk,
        object_label=scoreline,
        new_value="APPROVED",
        summary=(
            f"Approved {scoreline}"
            + (" (owner override)" if override and is_owner else "")
            + "."
        ),
    )
    return True, "Match approved successfully."


@transaction.atomic
def reject_match_submission(sub, reviewer):
    sub = (
        MatchSubmission.objects.select_for_update()
        .select_related("fixture__home_team", "fixture__away_team", "submitted_by")
        .get(pk=sub.pk)
    )
    if sub.status == ApprovalStatus.APPROVED:
        return unapprove_match_submission(sub, reviewer)
    if sub.status != ApprovalStatus.PENDING:
        return False, "Match is no longer pending."
    if sub.opponent_response != ApprovalStatus.APPROVED:
        return False, (
            "The opposing manager must approve this result before the league office can reject it."
        )
    sub.status = ApprovalStatus.REJECTED
    sub.reviewed_by = reviewer
    sub.reviewed_at = timezone.now()
    sub.save(update_fields=["status", "reviewed_by", "reviewed_at"])

    from django.urls import reverse

    from mgl.models import ManagerNotification
    from mgl.notifications import close_admin_result_notices, notify_user

    close_admin_result_notices(sub, ManagerNotification.REJECTED)
    fixture = sub.fixture
    message = (
        f"{fixture.home_team.name} vs {fixture.away_team.name} "
        "was rejected by the league office. Submit a corrected result."
    )
    notify_user(
        sub.submitted_by,
        source_key=f"score-rejected-{sub.pk}",
        notification_type="SCORE",
        title="RESULT REJECTED",
        message=message,
        actor="UFL Admin",
        action_url=reverse("submit_match", args=[fixture.pk]),
        action_label="RESUBMIT",
        team=(
            fixture.home_team
            if sub.submitted_by_id == fixture.home_team.manager_id
            else fixture.away_team
        ),
        fixture=fixture,
    )
    log_ocm_action(
        reviewer,
        action="match.reject",
        object_type="MatchSubmission",
        object_id=sub.pk,
        object_label=f"{fixture.home_team.name} vs {fixture.away_team.name}",
        new_value="REJECTED",
        summary=f"Rejected {fixture.home_team.name} vs {fixture.away_team.name}.",
    )
    return True, "Match rejected. The submitting manager can resubmit."


@transaction.atomic
def unapprove_match_submission(sub, reviewer):
    """Owner/Admin rollback of an official result. Stats and match tokens reverse. Ledger stays."""
    sub = (
        MatchSubmission.objects.select_for_update()
        .select_related("fixture__home_team", "fixture__away_team", "submitted_by")
        .get(pk=sub.pk)
    )
    if sub.status != ApprovalStatus.APPROVED:
        return False, "Only an official result can be rolled back."
    fixture = sub.fixture
    if season_is_locked(fixture.season_number):
        return False, "This season is locked. Unlock it before changing official results."
    reverse_match_statistics(sub)
    reverse_match_tokens(sub, reviewer)
    sub.status = ApprovalStatus.REJECTED
    sub.reviewed_by = reviewer
    sub.reviewed_at = timezone.now()
    sub.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    fixture.status = "SCHEDULED"
    fixture.save(update_fields=["status"])
    from django.urls import reverse

    from mgl.notifications import notify_user

    notify_user(
        sub.submitted_by,
        source_key=f"score-unapproved-{sub.pk}",
        notification_type="SCORE",
        title="RESULT ROLLED BACK",
        message=(
            f"{fixture.home_team.name} vs {fixture.away_team.name} "
            "was removed from the official record. Submit a corrected result."
        ),
        actor="UFL Admin",
        action_url=reverse("submit_match", args=[fixture.pk]),
        action_label="RESUBMIT",
        team=fixture.home_team,
        fixture=fixture,
    )
    log_ocm_action(
        reviewer,
        action="match.rollback",
        object_type="MatchSubmission",
        object_id=sub.pk,
        object_label=f"{fixture.home_team.name} vs {fixture.away_team.name}",
        old_value="APPROVED",
        new_value="REJECTED",
        summary=f"Rolled back official result {fixture.home_team.name} vs {fixture.away_team.name}.",
    )
    return True, "Official result rolled back. The table and player statistics were reversed."
