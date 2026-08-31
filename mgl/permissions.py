from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.models import User
from mgl.services import manager_for_user


def is_owner_or_admin(user):
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "role", None) in [User.OWNER, User.ADMIN]
    )


def owner_admin_required(view_func):
    """Only UFL OWNER or ADMIN users can access control pages."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("manager_login")
        if request.user.role not in [User.OWNER, User.ADMIN]:
            messages.error(
                request,
                "You do not have permission to access UFL Control.",
            )
            return redirect("manager_hub")
        return view_func(request, *args, **kwargs)

    return login_required(wrapper)


def site_manage_required(view_func):
    """Site Management is Owner/Admin only. Managers receive 403, not a hub redirect."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = reverse("manager_login")
            return redirect(f"{login_url}?next={request.path}")
        if not is_owner_or_admin(request.user):
            response = render(request, "mgl/site_manage/forbidden.html")
            response.status_code = 403
            return response
        return view_func(request, *args, **kwargs)

    return wrapper


def approved_manager(user):
    manager = manager_for_user(user)
    if not manager or manager.status != manager.APPROVED:
        return None
    return manager
