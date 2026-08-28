from django.core.management.base import BaseCommand, CommandError

from mgl.starting_squads import apply_starting_squads, format_validation_report


class Command(BaseCommand):
    help = (
        "Assign the approved 14×26 starting squads from the verified dry-run "
        "allocation. Default is a dry-run. Does not change ratings, IDs, faces, "
        "treasuries, or manager balances, and does not create auctions."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the 364 club assignments. Default is dry-run only.",
        )

    def handle(self, *args, **options):
        dry_run = not options["apply"]
        try:
            report = apply_starting_squads(dry_run=dry_run)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(format_validation_report(report))
        if not report.get("ok"):
            raise CommandError("Validation failed. No production assignment was applied.")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN ONLY — no players were assigned."))
            return
        self.stdout.write(self.style.SUCCESS(report.get("message") or "Starting squads applied."))
