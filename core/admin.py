from django.contrib import admin

from .models import Club


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "manager",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "name",
        "manager__username",
    )

    list_filter = (
        "manager",
        "created_at",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
