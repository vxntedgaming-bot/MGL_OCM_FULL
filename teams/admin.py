from django.contrib import admin
from .models import Team
@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display=("name","short_name","league","manager","roster_count","roster_limit")
    list_filter=("league",)
    search_fields=("name","short_name")
    readonly_fields=("roster_count",)
    def roster_count(self,obj): return obj.players.count()
    roster_count.short_description="Roster"
