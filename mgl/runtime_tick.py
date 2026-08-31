"""Lightweight per-request work: weekly awards catch-up and daily press."""

from django.db.utils import OperationalError, ProgrammingError

from mgl.press_schedule import ensure_daily_press_for_user
from mgl.weekly_awards import maybe_run_weekly_awards


def runtime_tick(user=None):
    try:
        maybe_run_weekly_awards()
    except (OperationalError, ProgrammingError):
        return
    try:
        ensure_daily_press_for_user(user)
    except (OperationalError, ProgrammingError, ValueError):
        return
