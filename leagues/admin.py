from django.contrib import admin
from .models import League


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "season", "is_active")
    list_filter = ("is_active", "season")
    search_fields = ("name", "short_name")
