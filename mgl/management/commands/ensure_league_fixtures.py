from django.core.management.base import BaseCommand

from leagues.services import active_divisions
from mgl.fixtures_schedule import ensure_round_robin_fixtures


class Command(BaseCommand):
    help = (
        "Create missing 14-team single round-robin fixtures. "
        "Does not delete existing fixtures or change clubs/players."
    )

    def handle(self, *args, **options):
        for league in active_divisions():
            report = ensure_round_robin_fixtures(league)
            if report["reason"]:
                self.stdout.write(f"{league.short_name}: skipped — {report['reason']}")
                continue
            self.stdout.write(
                f"{league.short_name}: created {report['created']}, "
                f"already present {report['skipped_existing']}, total {report['total']}."
            )
