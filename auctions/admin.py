from django.contrib import admin, messages
from django.utils import timezone
from datetime import timedelta

from players.models import Player

from .models import PlayerAuction, AuctionBid, TokenTransaction


@admin.action(description="Release selected players to auction")
def release_players_to_auction(modeladmin, request, queryset):
    created = 0
    skipped = 0

    for player in queryset:

        if not player.is_free_agent:
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

        PlayerAuction.objects.create(
            player=player,
            created_by=request.user,
            starting_bid=1,
            minimum_increment=1,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(hours=24),
            status=PlayerAuction.LIVE,
        )

        created += 1

    if created:
        messages.success(
            request,
            f"{created} player(s) released to auction."
        )

    if skipped:
        messages.warning(
            request,
            f"{skipped} player(s) skipped because they are already "
            f"owned or already have an active auction."
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
        "status",
        "winning_manager",
        "winning_bid",
        "created_at",
    )


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
