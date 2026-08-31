"""Schedule a minimum of four staggered press questions per 24 hours."""

import random
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from mgl.models import PressConference
from mgl.press import _pick_question, create_press_question
from mgl.services import manager_for_user
from teams.models import Team


DAILY_CATEGORIES = ("season", "squad", "tactics", "form", "transfers")
MIN_DAILY = 4
MIN_GAP_MINUTES = 90


def _club_for_user(user):
    return Team.objects.filter(manager=user).select_related("league").first()


def _window_count(user, now):
    start = now - timedelta(hours=24)
    end = now + timedelta(hours=24)
    return PressConference.objects.filter(manager=user).filter(
        Q(available_at__gte=start, available_at__lte=end)
        | Q(available_at__isnull=True, created_at__gte=start)
    ).count()


def _spread_times(now, count):
    if count <= 0:
        return []
    latest = now + timedelta(hours=20)
    earliest = now + timedelta(minutes=25)
    span = max(int((latest - earliest).total_seconds()), 60)
    times = []
    for index in range(count):
        jitter = random.randint(0, max(span // max(count, 1), 1))
        slot = earliest + timedelta(seconds=(span * index) // max(count, 1) + jitter)
        if times and slot - times[-1] < timedelta(minutes=MIN_GAP_MINUTES):
            slot = times[-1] + timedelta(minutes=MIN_GAP_MINUTES + random.randint(0, 40))
        times.append(slot)
    return times


def ensure_daily_press_for_user(user, now=None):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    application = manager_for_user(user)
    if application is None or application.status != application.APPROVED:
        return []
    team = _club_for_user(user)
    if team is None:
        return []
    now = now or timezone.now()
    needed = MIN_DAILY - _window_count(user, now)
    if needed <= 0:
        return []
    created = []
    for available_at in _spread_times(now, needed):
        category, key, question = _pick_question(DAILY_CATEGORIES, user)
        row = create_press_question(
            manager=user,
            team=team,
            question=question,
            question_key=f"daily-{key}-{int(available_at.timestamp())}",
            category=category,
            trigger=PressConference.DAILY,
            available_at=available_at,
            allow_multiple=True,
        )
        if row:
            created.append(row)
    return created
