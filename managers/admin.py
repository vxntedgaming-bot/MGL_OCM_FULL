from django.contrib import admin

from .models import ManagerApplication
from .services import approve_manager_application, reject_manager_application


@admin.action(description="Approve selected manager applications")
def approve_manager_applications(modeladmin, request, queryset):
    for application in queryset:
        if application.status != ManagerApplication.PENDING:
            continue
        approve_manager_application(application, request.user)


@admin.action(description="Reject selected manager applications")
def reject_manager_applications(modeladmin, request, queryset):
    for application in queryset:
        if application.status != ManagerApplication.PENDING:
            continue
        reject_manager_application(application, request.user)


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
