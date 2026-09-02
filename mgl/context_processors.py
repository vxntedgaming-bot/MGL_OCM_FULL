from django.db.utils import OperationalError, ProgrammingError
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from mgl.market import club_for_user, token_balance_for_user, transfer_window_is_open
from mgl.nav import nav_dropdowns_for_request, uses_signed_in_nav
from mgl.notifications import inbox_for_user, notifications_for_user
from mgl.services import manager_for_user
from mgl.site_cms import site_chrome
from mgl.transfer_requests import incoming_offer_count_for_user


def _current_season_context():
    try:
        from mgl.models import HistoricalSeason
        from mgl.season_history import current_season_number

        number = current_season_number()
        season = HistoricalSeason.objects.filter(number=number).only(
            "number", "year_label", "start_date", "end_date"
        ).first()
        label = ""
        if season:
            if season.start_date and season.end_date:
                label = f"{season.start_date:%b %Y} – {season.end_date:%b %Y}"
            elif season.year_label:
                label = season.year_label
        return {
            "mgl_current_season": number,
            "mgl_current_season_range": label,
        }
    except (OperationalError, ProgrammingError):
        return {"mgl_current_season": 1, "mgl_current_season_range": ""}


def mgl_nav(request):
    user = getattr(request, "user", None)
    is_control = False
    has_club = False
    signed_in_nav = False
    token_balance = None
    notifications = []
    unread_count = 0
    incoming_transfer_count = 0
    notify_items = []
    if user is not None and user.is_authenticated:
        is_control = getattr(user, "role", None) in [User.OWNER, User.ADMIN]
        has_club = club_for_user(user) is not None
        signed_in_nav = uses_signed_in_nav(user)
        if manager_for_user(user):
            token_balance = token_balance_for_user(user)
        if signed_in_nav:
            from mgl.runtime_tick import runtime_tick

            runtime_tick(user)
            inbox = inbox_for_user(user)
            notify_items = inbox[:12]
            unread_count = sum(1 for item in inbox if item.is_unread)
            notifications = notifications_for_user(user)
            incoming_transfer_count = incoming_offer_count_for_user(user)
    live_items = []
    live_latest = None
    try:
        from mgl.activity import ACTIVITY_EMOJI, published_ticker_activity

        ticker = list(published_ticker_activity()[:15])
        if ticker:
            live_latest = ticker[0].created_at
        for post in ticker:
            live_items.append(
                {
                    "title": post.title,
                    "url": reverse("live_activity"),
                    "emoji": ACTIVITY_EMOJI.get(post.category, "●"),
                }
            )
    except (OperationalError, ProgrammingError):
        live_items = []
        live_latest = None
    window_open = True
    try:
        window_open = transfer_window_is_open()
    except (OperationalError, ProgrammingError):
        window_open = True
    return {
        "mgl_is_control": is_control,
        "mgl_has_club": has_club,
        "mgl_signed_in_nav": signed_in_nav,
        "mgl_token_balance": token_balance,
        "mgl_now": timezone.now(),
        "mgl_nav_dropdowns": nav_dropdowns_for_request(request),
        "mgl_notifications": notifications,
        "mgl_notify_items": notify_items,
        "mgl_unread_notification_count": unread_count,
        "incoming_transfer_count": incoming_transfer_count,
        "mgl_live_items": live_items,
        "mgl_live_latest": live_latest,
        "window_open": window_open,
        **_current_season_context(),
        **site_chrome(),
    }
