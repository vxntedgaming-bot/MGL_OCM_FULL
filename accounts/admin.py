from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class MGLUserAdmin(UserAdmin):

    fieldsets = UserAdmin.fieldsets + (
        (
            "MGL Information",
            {
                "fields": (
                    "role",
                    "discord_id",
                )
            },
        ),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "MGL Information",
            {
                "fields": (
                    "role",
                    "discord_id",
                )
            },
        ),
    )

    list_display = (
        "username",
        "email",
        "role",
        "is_active",
        "is_staff",
    )

    list_filter = (
        "role",
        "is_active",
        "is_staff",
    )

    search_fields = (
        "username",
        "email",
        "discord_id",
    )
