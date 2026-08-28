import csv

from django.core.management.base import BaseCommand, CommandError

from players.fc26_names import display_name_from_row
from players.models import Player


BATCH_SIZE = 400


class Command(BaseCommand):
    help = (
        "Update existing Player.name values to the recognised FC26 display "
        "name derived from short_name + long_name. Matches by fc27_id = "
        "player_id only. Does not create or delete players, and does not "
        "change ratings, clubs, faces, transfers or other fields."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to fc26_players_raw.csv",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count corrections without writing to the database.",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        dry_run = options["dry_run"]

        try:
            handle = open(csv_file, "r", encoding="utf-8-sig", newline="")
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_file}")

        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            required = {"player_id", "short_name", "long_name"}
            missing = required - set(reader.fieldnames)
            if missing:
                raise CommandError(
                    "Missing CSV columns: " + ", ".join(sorted(missing))
                )
            rows = list(reader)

        names_by_id = {}
        skipped = 0
        for row in rows:
            fc_id = self.normalize_fc_id(row.get("player_id"))
            display = display_name_from_row(row)
            if not fc_id or not display:
                skipped += 1
                continue
            names_by_id[fc_id] = display

        updated = 0
        unchanged = 0
        not_found = 0
        changed_players = []

        for player in Player.objects.exclude(fc27_id__isnull=True).exclude(fc27_id=""):
            fc_id = self.normalize_fc_id(player.fc27_id)
            display = names_by_id.get(fc_id)
            if display is None:
                not_found += 1
                continue
            if (player.name or "").strip() == display:
                unchanged += 1
                continue
            player.name = display
            changed_players.append(player)
            updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no rows written."))
        else:
            self.bulk_save(changed_players)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("FC26 display-name sync complete."))
        self.stdout.write(f"Updated:    {updated}")
        self.stdout.write(f"Unchanged:  {unchanged}")
        self.stdout.write(f"No CSV row: {not_found}")
        self.stdout.write(f"Skipped:    {skipped}")

    @staticmethod
    def bulk_save(players):
        if not players:
            return
        Player.objects.bulk_update(players, ["name"], batch_size=BATCH_SIZE)

    @staticmethod
    def normalize_fc_id(value):
        value = str(value or "").strip()
        if not value:
            return ""
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return value
