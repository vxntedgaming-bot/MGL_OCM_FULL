from django.core.management.base import BaseCommand, CommandError

from mgl.season1 import CONFIRM_PHRASE, format_preview, preview_season1_bootstrap


class Command(BaseCommand):
    help = (
        "Preview the controlled UFL Season 1 38-club bootstrap. "
        "Default is dry-run only. Production apply stays blocked."
    )

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=20260901)
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=True,
            help="Preview only (default). No writes.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Rejected. Season 1 apply is blocked until the Owner authorises it.",
        )
        parser.add_argument("--confirm", default="")

    def handle(self, *args, **options):
        report = preview_season1_bootstrap(seed=options["seed"])
        self.stdout.write(format_preview(report))
        if options["apply"]:
            raise CommandError(
                "Season 1 apply is blocked. The Owner must explicitly authorise "
                f"the production bootstrap later. Confirmation phrase would be {CONFIRM_PHRASE!r}."
            )
        self.stdout.write(self.style.WARNING("DRY RUN ONLY — no clubs, players, or locks were changed."))
