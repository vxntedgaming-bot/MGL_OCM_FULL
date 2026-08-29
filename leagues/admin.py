from django.contrib import admin
from .models import League


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "public_name", "season", "is_active", "display_order")
    list_filter = ("is_active", "season")
    search_fields = ("name", "short_name", "display_name")
    readonly_fields = ("name", "short_name")
