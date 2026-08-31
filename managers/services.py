from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import ManagerApplication


STARTING_TOKENS = Decimal("20.00")


@transaction.atomic
def approve_manager_application(application, reviewer):
    application = (
        ManagerApplication.objects.select_for_update()
        .select_related("user")
        .get(pk=application.pk)
    )
    if application.status != ManagerApplication.PENDING:
        raise ValueError("This application is no longer pending.")

    application.status = ManagerApplication.APPROVED
    application.reviewed_at = timezone.now()
    application.reviewed_by = reviewer
    if application.tokens is None or application.tokens == 0:
        application.tokens = STARTING_TOKENS
    application.save(
        update_fields=["status", "reviewed_at", "reviewed_by", "tokens"]
    )

    user = application.user
    user.role = user.MANAGER
    user.is_active = True
    user.save(update_fields=["role", "is_active"])
    from django.urls import reverse
    from mgl.notifications import notify_user

    notify_user(
        user,
        source_key=f"manager-approved-{application.pk}",
        notification_type="ADMIN",
        title="MANAGER APPROVED",
        message="Your manager application was approved. You can now apply for a club.",
        actor="UFL Admin",
        action_url=reverse("job_centre"),
        action_label="JOB CENTRE",
    )
    return application


@transaction.atomic
def reject_manager_application(application, reviewer):
    application = ManagerApplication.objects.select_for_update().get(pk=application.pk)
    if application.status != ManagerApplication.PENDING:
        raise ValueError("This application is no longer pending.")

    application.status = ManagerApplication.REJECTED
    application.reviewed_at = timezone.now()
    application.reviewed_by = reviewer
    application.save(update_fields=["status", "reviewed_at", "reviewed_by"])
    from mgl.notifications import notify_user

    notify_user(
        application.user,
        source_key=f"manager-rejected-{application.pk}",
        notification_type="ADMIN",
        title="MANAGER APPLICATION REJECTED",
        message="Your manager application was rejected.",
        actor="UFL Admin",
    )
    return application
