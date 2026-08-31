"""Display helpers for the manager fixtures page. Does not change official results."""

from calendar import month_name
from collections import defaultdict
from datetime import date

from django.utils import timezone

from mgl.models import ApprovalStatus, FixtureReleaseBatch, MatchSubmission
from mgl.standings import build_live_league_table


STATUS_UPCOMING = "upcoming"
STATUS_LIVE = "live"
STATUS_SUBMITTED = "submitted"
STATUS_AWAITING = "awaiting"
STATUS_PENDING_ADMIN = "pending-admin"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_COMPLETED = "completed"


def club_standings(league, team):
    if not league or not team:
        return None, 0
    table = build_live_league_table(league)
    row = next((item for item in table if item["team"].id == team.id), None)
    return row, len(table)


def fixture_score(fixture, submission=None):
    submission = submission or getattr(fixture, "submission", None)
    if submission is None:
        return None, None
    try:
        stats = {row.team_id: row for row in submission.team_stats.all()}
    except Exception:
        return None, None
    home = stats.get(fixture.home_team_id)
    away = stats.get(fixture.away_team_id)
    return (
        home.goals if home is not None else None,
        away.goals if away is not None else None,
    )


def display_status(fixture, submission, viewer_id=None):
    if fixture.status == "CANCELLED":
        return STATUS_CANCELLED, "CANCELLED"
    if fixture.status == "LIVE":
        return STATUS_LIVE, "IN PROGRESS"
    if submission is None:
        if fixture.status == "COMPLETED":
            return STATUS_COMPLETED, "COMPLETED"
        return STATUS_UPCOMING, "UPCOMING"
    if submission.status == ApprovalStatus.APPROVED:
        return STATUS_APPROVED, "APPROVED"
    if submission.status == ApprovalStatus.REJECTED:
        return STATUS_REJECTED, "NEEDS CORRECTION"
    if submission.opponent_response == ApprovalStatus.REJECTED:
        return STATUS_REJECTED, "NEEDS CORRECTION"
    if submission.opponent_response == ApprovalStatus.APPROVED:
        return STATUS_PENDING_ADMIN, "PENDING ADMIN APPROVAL"
    if submission.opponent_response == ApprovalStatus.PENDING:
        if viewer_id and submission.submitted_by_id == viewer_id:
            return STATUS_AWAITING, "AWAITING OPPONENT CONFIRMATION"
        if viewer_id and viewer_id in {
            fixture.home_team.manager_id,
            fixture.away_team.manager_id,
        }:
            return STATUS_SUBMITTED, "STATS SUBMITTED"
        return STATUS_AWAITING, "AWAITING OPPONENT CONFIRMATION"
    if fixture.status == "COMPLETED":
        return STATUS_COMPLETED, "COMPLETED"
    return STATUS_SUBMITTED, "STATS SUBMITTED"


def is_official_result(fixture, submission):
    return bool(
        fixture.status == "COMPLETED"
        and submission is not None
        and submission.status == ApprovalStatus.APPROVED
    )


def annotate_fixtures(fixtures, team=None, viewer=None):
    fixture_list = list(fixtures)
    if not fixture_list:
        return fixture_list
    submissions = {
        row.fixture_id: row
        for row in MatchSubmission.objects.filter(
            fixture_id__in=[item.id for item in fixture_list]
        )
        .select_related("submitted_by")
        .prefetch_related("team_stats")
    }
    viewer_id = getattr(viewer, "id", None) if viewer is not None else None
    team_id = getattr(team, "id", None)
    for index, fixture in enumerate(fixture_list, start=1):
        submission = submissions.get(fixture.id)
        fixture.display_index = index
        fixture.is_home_for_club = bool(team_id and fixture.home_team_id == team_id)
        fixture.is_away_for_club = bool(team_id and fixture.away_team_id == team_id)
        fixture.opponent = None
        if team_id:
            fixture.opponent = (
                fixture.away_team
                if fixture.home_team_id == team_id
                else fixture.home_team
            )
        fixture.home_goals, fixture.away_goals = fixture_score(fixture, submission)
        fixture.display_status, fixture.display_status_label = display_status(
            fixture, submission, viewer_id
        )
        fixture.is_official = is_official_result(fixture, submission)
        fixture.can_enter_stats = (
            fixture.status == "SCHEDULED"
            and (
                submission is None
                or submission.status == ApprovalStatus.REJECTED
                or submission.opponent_response == ApprovalStatus.REJECTED
            )
        )
        fixture.submission_row = submission
    return fixture_list


def group_by_month(fixtures):
    dated = []
    undated = []
    for fixture in fixtures:
        if fixture.scheduled_at:
            dated.append(fixture)
        else:
            undated.append(fixture)
    dated.sort(key=lambda row: (row.scheduled_at, row.matchweek, row.id))
    groups = []
    current_key = None
    current_rows = []
    for fixture in dated:
        key = (fixture.scheduled_at.year, fixture.scheduled_at.month)
        if key != current_key:
            if current_rows:
                year, month = current_key
                groups.append(
                    {
                        "label": f"{month_name[month].upper()} {year}",
                        "fixtures": current_rows,
                    }
                )
            current_key = key
            current_rows = [fixture]
        else:
            current_rows.append(fixture)
    if current_rows:
        year, month = current_key
        groups.append(
            {
                "label": f"{month_name[month].upper()} {year}",
                "fixtures": current_rows,
            }
        )
    if undated:
        groups.append({"label": "DATE TBC", "fixtures": undated})
    return groups


def calendar_months(fixtures):
    buckets = defaultdict(list)
    for fixture in fixtures:
        if not fixture.scheduled_at:
            continue
        when = timezone.localtime(fixture.scheduled_at)
        buckets[(when.year, when.month)].append(fixture)
    months = []
    for year, month in sorted(buckets):
        first = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1).toordinal() - first.toordinal()
        else:
            last_day = date(year, month + 1, 1).toordinal() - first.toordinal()
        by_day = defaultdict(list)
        for fixture in buckets[(year, month)]:
            by_day[timezone.localtime(fixture.scheduled_at).day].append(fixture)
        weeks = []
        week = [None] * first.weekday()
        for day in range(1, last_day + 1):
            week.append({"day": day, "fixtures": by_day.get(day, [])})
            if len(week) == 7:
                weeks.append(week)
                week = []
        if week:
            week.extend([None] * (7 - len(week)))
            weeks.append(week)
        months.append(
            {
                "label": f"{month_name[month].upper()} {year}",
                "weeks": weeks,
            }
        )
    return months


def summary_for(fixtures, standings_row=None):
    total = len(fixtures)
    played = sum(1 for row in fixtures if row.is_official)
    remaining = max(0, total - played)
    goals = 0
    goal_matches = 0
    if standings_row and standings_row.get("played"):
        goals = standings_row.get("gf") or 0
        goal_matches = standings_row["played"]
    else:
        for row in fixtures:
            if not row.is_official:
                continue
            if row.home_goals is None or row.away_goals is None:
                continue
            goals += row.home_goals + row.away_goals
            goal_matches += 1
    average = (goals / goal_matches) if goal_matches else 0.0
    played_pct = int(round((played / total) * 100)) if total else 0
    remaining_pct = int(round((remaining / total) * 100)) if total else 0
    return {
        "total": total,
        "played": played,
        "remaining": remaining,
        "played_pct": played_pct,
        "remaining_pct": remaining_pct,
        "average_goals": f"{average:.2f}",
    }


def deadline_context(fixtures):
    now = timezone.now()
    batch = (
        FixtureReleaseBatch.objects.filter(is_released=True)
        .order_by("-batch_number")
        .first()
    )
    deadline = None
    batch_number = None
    if batch:
        batch_number = batch.batch_number
        deadline = batch.deadline
    if deadline is None:
        upcoming = [
            row.lineup_deadline
            for row in fixtures
            if getattr(row, "lineup_deadline", None)
        ]
        if upcoming:
            future = [item for item in upcoming if item >= now]
            deadline = min(future) if future else max(upcoming)
    if batch_number is None:
        numbers = [row.release_batch for row in fixtures if row.release_batch]
        batch_number = max(numbers) if numbers else None
    released_count = len(fixtures)
    days_left = None
    approaching = False
    passed = False
    if deadline is not None:
        delta = deadline - now
        days_left = max(0, delta.days)
        approaching = 0 < delta.total_seconds() <= 3 * 24 * 3600
        passed = delta.total_seconds() < 0
    return {
        "batch_number": batch_number,
        "released_count": released_count,
        "deadline": deadline,
        "days_left": days_left,
        "approaching": approaching,
        "passed": passed,
        "has_deadline": deadline is not None,
    }


def workflow_step(submission):
    if submission is None:
        return 1
    if submission.status == ApprovalStatus.APPROVED:
        return 5
    if submission.status == ApprovalStatus.REJECTED:
        return 1
    if submission.opponent_response == ApprovalStatus.REJECTED:
        return 1
    if submission.opponent_response == ApprovalStatus.APPROVED:
        return 5
    if submission.opponent_response == ApprovalStatus.PENDING:
        return 4
    return 1


def side_review(side, submission):
    if submission is None:
        return side
    stats = next(
        (row for row in submission.team_stats.all() if row.team_id == side["team"].id),
        None,
    )
    side["stats"] = stats
    if stats is None:
        return side
    side["scorers"] = list(stats.goal_events.all())
    side["assists"] = list(stats.assist_events.all())
    side["ratings"] = list(stats.defender_ratings.all())
    side["saves"] = list(stats.gk_saves.all())
    return side
