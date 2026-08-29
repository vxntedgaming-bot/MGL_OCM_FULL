from django.utils import timezone

from accounts.models import User
from mgl.market import club_for_user, token_balance_for_user
from mgl.nav import nav_dropdowns_for_request, uses_signed_in_nav
from mgl.notifications import notifications_for_user, unread_count_for_user
from mgl.services import manager_for_user
from mgl.site_cms import site_chrome


def mgl_nav(request):
    user = getattr(request, "user", None)
    is_control = False
    has_club = False
    signed_in_nav = False
    token_balance = None
    notifications = []
    unread_count = 0
    if user is not None and user.is_authenticated:
        is_control = getattr(user, "role", None) in [User.OWNER, User.ADMIN]
        has_club = club_for_user(user) is not None
        signed_in_nav = uses_signed_in_nav(user)
        if manager_for_user(user):
            token_balance = token_balance_for_user(user)
        if signed_in_nav:
            notifications = notifications_for_user(user)
            unread_count = unread_count_for_user(user)
    return {
        "mgl_is_control": is_control,
        "mgl_has_club": has_club,
        "mgl_signed_in_nav": signed_in_nav,
        "mgl_token_balance": token_balance,
        "mgl_now": timezone.now(),
        "mgl_nav_dropdowns": nav_dropdowns_for_request(request),
        "mgl_notifications": notifications,
        "mgl_unread_notification_count": unread_count,
        **site_chrome(),
    }
