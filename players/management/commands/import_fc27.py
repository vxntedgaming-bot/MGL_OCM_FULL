import csv

from django.core.management.base import BaseCommand, CommandError

from players.models import Player


class Command(BaseCommand):
    help = (
        "Import or update FC26/FC27 players from a CSV file. "
        "Never assigns an MGL club. New rows are unassigned free agents. "
        "fc27_club is stored as FC26 reference data only."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to the FC27 CSV file",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]

        try:
            file = open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline="",
            )
        except FileNotFoundError:
            raise CommandError(
                f"File not found: {csv_file}"
            )

        created = 0
        updated = 0
        skipped = 0

        with file:
            reader = csv.DictReader(file)

            required_columns = {
                "fc27_id",
                "name",
                "fc27_club",
                "nationality",
                "position",
                "overall",
                "pace",
                "shooting",
                "passing",
                "dribbling",
                "defending",
                "physical",
            }

            if not reader.fieldnames:
                raise CommandError("The CSV has no header row.")

            missing = required_columns - set(reader.fieldnames)

            if missing:
                raise CommandError(
                    "Missing CSV columns: "
                    + ", ".join(sorted(missing))
                )

            for row in reader:
                fc27_id = (row.get("fc27_id") or "").strip()
                name = (row.get("name") or "").strip()

                if not fc27_id or not name:
                    skipped += 1
                    continue

                defaults = {
                    "name": name,
                    "fc27_club": (
                        row.get("fc27_club") or ""
                    ).strip(),
                    "nationality": (
                        row.get("nationality") or ""
                    ).strip(),
                    "position": (
                        row.get("position") or ""
                    ).strip(),
                    "overall": self.number(row.get("overall")),
                    "pace": self.number(row.get("pace")),
                    "shooting": self.number(row.get("shooting")),
                    "passing": self.number(row.get("passing")),
                    "dribbling": self.number(row.get("dribbling")),
                    "defending": self.number(row.get("defending")),
                    "physical": self.number(row.get("physical")),
                    "age": self.number(row.get("age")) if "age" in row else None,
                }
                # FC26 club/name must never become MGL ownership.
                defaults.pop("mgl_team", None)
                defaults.pop("is_free_agent", None)

                player, was_created = Player.objects.update_or_create(
                    fc27_id=fc27_id,
                    defaults=defaults,
                )
                if was_created and (player.mgl_team_id or not player.is_free_agent):
                    player.mgl_team = None
                    player.is_free_agent = True
                    player.save(update_fields=["mgl_team", "is_free_agent"])

                if was_created:
                    created += 1
                else:
                    updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Import complete: {created} created, "
                f"{updated} updated, {skipped} skipped."
            )
        )

    @staticmethod
    def number(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0
