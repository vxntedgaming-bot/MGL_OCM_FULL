from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from auctions.models import PlayerAuction
from mgl.models import PlayerOwnershipHistory
from mgl.player_state import live_auction_player_ids, market_counts
from players.models import Player


class Command(BaseCommand):
    help = (
        "Relabel unused FC26 players as UNASSIGNED (is_free_agent=False). "
        "Does not assign clubs, create auctions, change ratings, IDs, or faces. "
        "Real Free Agents (no-bid auctions / club releases) are left alone."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the flag correction. Default is a dry-run count only.",
        )

    def handle(self, *args, **options):
        no_bid_ids = PlayerAuction.objects.filter(
            listing_kind=PlayerAuction.FREE_AGENT,
            status=PlayerAuction.ENDED,
            winning_bid=0,
        ).values_list("player_id", flat=True)
        released_ids = PlayerOwnershipHistory.objects.filter(
            player__mgl_team__isnull=True,
            player__is_free_agent=True,
        ).values_list("player_id", flat=True)
        live_ids = live_auction_player_ids()
        qs = (
            Player.objects.filter(mgl_team__isnull=True, is_free_agent=True)
            .exclude(id__in=no_bid_ids)
            .exclude(id__in=released_ids)
            .exclude(id__in=live_ids)
        )
        before_count = Player.objects.count()
        before_unique = (
            Player.objects.exclude(fc27_id="")
            .exclude(fc27_id__isnull=True)
            .values("fc27_id")
            .distinct()
            .count()
        )
        before_sum = Player.objects.aggregate(total=Sum("overall"))["total"] or 0
        to_fix = qs.count()
        self.stdout.write(f"Players: {before_count}")
        self.stdout.write(f"Unique fc27_id: {before_unique}")
        self.stdout.write(f"OVR sum: {before_sum}")
        self.stdout.write(f"Mislabelled unused rows to set UNASSIGNED: {to_fix}")
        self.stdout.write(f"Current market: {market_counts()}")
        if not options["apply"]:
            self.stdout.write(self.style.WARNING("DRY RUN — no rows were updated. Pass --apply to write flags."))
            return
        with transaction.atomic():
            updated = qs.update(is_free_agent=False)
            after_count = Player.objects.count()
            after_unique = (
                Player.objects.exclude(fc27_id="")
                .exclude(fc27_id__isnull=True)
                .values("fc27_id")
                .distinct()
                .count()
            )
            after_sum = Player.objects.aggregate(total=Sum("overall"))["total"] or 0
            assigned = Player.objects.filter(mgl_team__isnull=False).count()
            if after_count != before_count or after_unique != before_unique or after_sum != before_sum:
                raise CommandError(
                    "Safety abort: player count, unique fc27_id, or OVR sum changed."
                )
            if assigned:
                self.stdout.write(self.style.WARNING(f"Assigned club players left untouched: {assigned}"))
        self.stdout.write(self.style.SUCCESS(f"Set is_free_agent=False on {updated} unused players."))
        self.stdout.write(f"Market after: {market_counts()}")
        self.stdout.write("No clubs, auctions, tokens, ratings, IDs, or faces were changed.")
