from django.contrib import admin
from .models import Player
from auctions.admin import release_players_to_auction
from mgl.services import release_player
@admin.action(description="Release selected players to Free Agents")
def release_selected_players(modeladmin,request,queryset):
    for player in queryset.filter(mgl_team__isnull=False): release_player(player,player.mgl_team,source="ADMIN_RELEASE")
@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display=("name","position","overall","mgl_team","is_free_agent","calculated_tier")
    list_filter=("position","mgl_team","is_free_agent")
    search_fields=("name","fc27_club","nationality")
    ordering=("-overall","name")
    actions=(release_players_to_auction,release_selected_players)
