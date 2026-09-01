"""Lightweight per-request work: weekly/monthly awards catch-up and daily press."""

from django.db.utils import OperationalError, ProgrammingError

from mgl.monthly_awards import maybe_run_monthly_awards
from mgl.press_schedule import ensure_daily_press_for_user
from mgl.weekly_awards import maybe_run_weekly_awards


def runtime_tick(user=None):
    try:
        maybe_run_weekly_awards()
        maybe_run_monthly_awards()
    except (OperationalError, ProgrammingError):
        return
    try:
        from mgl.scouting import complete_due_scouts

        complete_due_scouts()
    except (OperationalError, ProgrammingError, ValueError):
        pass
    try:
        ensure_daily_press_for_user(user)
    except (OperationalError, ProgrammingError, ValueError):
        return
