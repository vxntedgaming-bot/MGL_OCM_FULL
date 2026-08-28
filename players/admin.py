from django.contrib import admin

from auctions.admin import release_players_to_auction
from mgl.services import release_player
from players.search import apply_player_search

from .models import Player


@admin.action(description="Release selected players to Free Agents")
def release_selected_players(modeladmin, request, queryset):
    for player in queryset.filter(mgl_team__isnull=False):
        release_player(player, player.mgl_team, source="ADMIN_RELEASE")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "overall", "mgl_team", "is_free_agent", "calculated_tier")
    list_filter = ("position", "mgl_team", "is_free_agent")
    search_fields = ("name", "fc27_club", "nationality", "fc27_id")
    ordering = ("-overall", "name")
    actions = (release_players_to_auction, release_selected_players)

    def get_search_results(self, request, queryset, search_term):
        if not search_term:
            return queryset, False
        queryset = apply_player_search(
            queryset,
            search_term,
            extra_fields=("fc27_club", "nationality", "fc27_id"),
        )
        return queryset, False
