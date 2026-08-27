from django.core.management.base import BaseCommand

from mgl.market import close_expired_auctions


class Command(BaseCommand):
    help = "Settle live auctions whose end time has passed."

    def handle(self, *args, **options):
        closed = close_expired_auctions()
        self.stdout.write(self.style.SUCCESS(f"Closed {closed} expired auction(s)."))
