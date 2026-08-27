from django.contrib import admin
from django.utils import timezone

from .models import ManagerApplication


@admin.action(description="Approve selected manager applications")
def approve_manager_applications(modeladmin, request, queryset):
    for application in queryset:
        application.status = ManagerApplication.APPROVED
        application.reviewed_at = timezone.now()
        application.reviewed_by = request.user

        user = application.user
        user.role = user.MANAGER
        user.is_active = True
        user.save()

        if application.tokens == 0:
            application.tokens = 50.00

        application.save()


@admin.action(description="Reject selected manager applications")
def reject_manager_applications(modeladmin, request, queryset):
    for application in queryset:
        application.status = ManagerApplication.REJECTED
        application.reviewed_at = timezone.now()
        application.reviewed_by = request.user
        application.save()


@admin.register(ManagerApplication)
class ManagerApplicationAdmin(admin.ModelAdmin):

    list_display = (
        "display_name",
        "gamertag",
        "preferred_team",
        "tokens",
        "status",
        "submitted_at",
    )

    list_filter = (
        "status",
        "submitted_at",
    )

    search_fields = (
        "display_name",
        "gamertag",
        "preferred_team",
        "user__username",
        "user__email",
    )

    readonly_fields = (
        "submitted_at",
        "reviewed_at",
        "reviewed_by",
    )

    actions = (
        approve_manager_applications,
        reject_manager_applications,
    )
