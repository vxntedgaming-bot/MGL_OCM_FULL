from django.core.management.base import BaseCommand, CommandError

from mgl.starting_squads import apply_starting_squads, format_validation_report


class Command(BaseCommand):
    help = (
        "LEGACY / FENCED. The official UFL starting-squad path is Control Centre "
        "generate → Owner approve. This command cannot assign players."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Rejected. Legacy 14×26 apply cannot bypass Control Centre.",
        )

    def handle(self, *args, **options):
        if options["apply"]:
            raise CommandError(
                "apply_starting_squads --apply is disabled. Official starting "
                "squads are generated and approved in Control Centre."
            )
        try:
            report = apply_starting_squads(dry_run=True)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(format_validation_report(report))
        self.stdout.write(
            self.style.WARNING(
                "LEGACY DRY RUN ONLY — no players were assigned. "
                "Use Control → Season → Starting Squads."
            )
        )
