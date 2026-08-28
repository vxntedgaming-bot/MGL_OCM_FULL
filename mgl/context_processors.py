from django.utils import timezone

from accounts.models import User
from mgl.market import club_for_user, token_balance_for_user
from mgl.nav import nav_dropdowns_for_request
from mgl.services import manager_for_user


def mgl_nav(request):
    user = getattr(request, "user", None)
    is_control = False
    has_club = False
    token_balance = None
    if user is not None and user.is_authenticated:
        is_control = getattr(user, "role", None) in [User.OWNER, User.ADMIN]
        has_club = club_for_user(user) is not None
        if manager_for_user(user):
            token_balance = token_balance_for_user(user)
    return {
        "mgl_is_control": is_control,
        "mgl_has_club": has_club,
        "mgl_token_balance": token_balance,
        "mgl_now": timezone.now(),
        "mgl_nav_dropdowns": nav_dropdowns_for_request(request),
    }
