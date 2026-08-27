from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from accounts.models import User
from mgl.services import manager_for_user


def owner_admin_required(view_func):
    """Only MGL OWNER or ADMIN users can access control pages."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("manager_login")
        if request.user.role not in [User.OWNER, User.ADMIN]:
            messages.error(
                request,
                "You do not have permission to access MGL Control.",
            )
            return redirect("manager_hub")
        return view_func(request, *args, **kwargs)

    return login_required(wrapper)


def approved_manager(user):
    manager = manager_for_user(user)
    if not manager or manager.status != manager.APPROVED:
        return None
    return manager
