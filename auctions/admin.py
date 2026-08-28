from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied

from mgl.market import create_free_agent_auction, settle_auction
from players.models import Player

from .models import PlayerAuction, AuctionBid, TokenTransaction


@admin.action(description="Release selected players to auction")
def release_players_to_auction(modeladmin, request, queryset):
    created = 0
    skipped = 0

    for player in queryset:

        if player.is_free_agent or player.mgl_team_id:
            skipped += 1
            continue

        existing_live = PlayerAuction.objects.filter(
            player=player,
            status__in=[
                PlayerAuction.PENDING,
                PlayerAuction.LIVE,
            ],
        ).exists()

        if existing_live:
            skipped += 1
            continue

        try:
            create_free_agent_auction(
                player,
                request.user,
                720,
                starting_bid=1,
            )
        except (ValueError, PermissionDenied):
            skipped += 1
            continue

        created += 1

    if created:
        messages.success(
            request,
            f"{created} player(s) released to auction."
        )

    if skipped:
        messages.warning(
            request,
            f"{skipped} player(s) skipped because they are a Free Agent, "
            f"already owned, or already have an active auction."
        )


@admin.register(PlayerAuction)
class PlayerAuctionAdmin(admin.ModelAdmin):

    list_display = (
        "player",
        "status",
        "starting_bid",
        "minimum_increment",
        "winning_manager",
        "winning_bid",
        "starts_at",
        "ends_at",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "player__name",
        "winning_manager__display_name",
    )

    readonly_fields = (
        "winning_manager",
        "winning_bid",
        "created_at",
    )

    actions = ("close_selected_auctions",)

    @admin.action(description="Close selected auctions and assign winners")
    def close_selected_auctions(self, request, queryset):
        closed = 0
        for auction in queryset:
            settle_auction(auction, reviewer=request.user)
            closed += 1
        self.message_user(request, f"Closed {closed} auction(s).")


@admin.register(AuctionBid)
class AuctionBidAdmin(admin.ModelAdmin):

    list_display = (
        "auction",
        "manager",
        "amount",
        "created_at",
    )

    list_filter = (
        "created_at",
    )

    search_fields = (
        "manager__display_name",
        "auction__player__name",
    )

    readonly_fields = (
        "created_at",
    )


@admin.register(TokenTransaction)
class TokenTransactionAdmin(admin.ModelAdmin):

    list_display = (
        "manager",
        "amount",
        "transaction_type",
        "auction",
        "description",
        "created_at",
    )

    list_filter = (
        "transaction_type",
        "created_at",
    )

    search_fields = (
        "manager__display_name",
        "description",
    )

    readonly_fields = (
        "created_at",
    )
