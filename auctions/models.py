from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class PlayerAuction(models.Model):
    PENDING = "PENDING"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (LIVE, "Live"),
        (ENDED, "Ended"),
        (CANCELLED, "Cancelled"),
    ]

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.CASCADE,
        related_name="auctions",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="player_auctions_created",
    )

    starting_bid = models.PositiveIntegerField(
        default=1,
    )

    minimum_increment = models.PositiveIntegerField(
        default=1,
    )

    starts_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    ends_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=PENDING,
    )

    winning_manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="won_auctions",
    )

    winning_bid = models.PositiveIntegerField(
        default=0,
    )

    FREE_AGENT = "FREE_AGENT"
    CLUB = "CLUB"
    LISTING_KIND_CHOICES = [
        (FREE_AGENT, "Free agent"),
        (CLUB, "Club player"),
    ]

    listing_kind = models.CharField(
        max_length=20,
        choices=LISTING_KIND_CHOICES,
        default=FREE_AGENT,
    )
    listed_by_manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listed_auctions",
    )
    origin_team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="origin_auctions",
    )
    duration_minutes = models.PositiveIntegerField(default=30)

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def remaining(self, now=None):
        now = now or timezone.now()
        if not self.ends_at:
            return None
        if self.ends_at <= now:
            return timedelta(0)
        return self.ends_at - now

    def is_expired(self, now=None):
        now = now or timezone.now()
        return bool(self.ends_at and self.ends_at <= now)

    def __str__(self):
        return f"{self.player.name} Auction - {self.status}"


class AuctionBid(models.Model):

    auction = models.ForeignKey(
        PlayerAuction,
        on_delete=models.CASCADE,
        related_name="bids",
    )

    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="auction_bids",
    )

    amount = models.PositiveIntegerField()

    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auction_bids",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-amount", "-created_at"]

    def __str__(self):
        return (
            f"{self.manager.display_name} - "
            f"{self.amount} tokens"
        )


class TokenTransaction(models.Model):

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"

    TYPE_CHOICES = [
        (CREDIT, "Credit"),
        (DEBIT, "Debit"),
        (REFUND, "Refund"),
        (ADJUSTMENT, "Adjustment"),
    ]

    manager = models.ForeignKey(
        "managers.ManagerApplication",
        on_delete=models.CASCADE,
        related_name="token_transactions",
    )

    amount = models.IntegerField()

    transaction_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
    )

    description = models.CharField(
        max_length=255,
        blank=True,
    )

    auction = models.ForeignKey(
        PlayerAuction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="token_transactions",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return (
            f"{self.manager.display_name}: "
            f"{self.amount} tokens"
        )
