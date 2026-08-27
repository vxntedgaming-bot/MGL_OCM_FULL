import csv

from django.core.management.base import BaseCommand, CommandError

from players.models import Player


class Command(BaseCommand):
    help = "Safely sync FC26 details onto existing MGL players using fc27_id."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to fc26_players_raw.csv",
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
            raise CommandError(f"File not found: {csv_file}")

        updated = 0
        not_found = 0
        skipped = 0

        with file:
            reader = csv.DictReader(file)

            required = {
                "player_id",
                "club_name",
                "nationality_name",
                "preferred_foot",
                "weak_foot",
                "skill_moves",
                "height_cm",
                "weight_kg",
                "player_face_url",
            }

            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")

            missing = required - set(reader.fieldnames)

            if missing:
                raise CommandError(
                    "Missing CSV columns: "
                    + ", ".join(sorted(missing))
                )

            for row in reader:
                fc_id = (row.get("player_id") or "").strip()

                if not fc_id:
                    skipped += 1
                    continue

                try:
                    player = Player.objects.get(fc27_id=fc_id)
                except Player.DoesNotExist:
                    not_found += 1
                    continue

                player.fc27_club = (
                    row.get("club_name") or ""
                ).strip()

                player.nationality = (
                    row.get("nationality_name") or ""
                ).strip()

                player.preferred_foot = (
                    row.get("preferred_foot") or ""
                ).strip()

                player.weak_foot = self.number(
                    row.get("weak_foot")
                )

                player.skill_moves = self.number(
                    row.get("skill_moves")
                )

                player.height_cm = self.number_or_none(
                    row.get("height_cm")
                )

                player.weight_kg = self.number_or_none(
                    row.get("weight_kg")
                )

                player.player_face_url = (
                    row.get("player_face_url") or ""
                ).strip()

                player.save(
                    update_fields=[
                        "fc27_club",
                        "nationality",
                        "preferred_foot",
                        "weak_foot",
                        "skill_moves",
                        "height_cm",
                        "weight_kg",
                        "player_face_url",
                    ]
                )

                updated += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"FC26 detail sync complete."
            )
        )
        self.stdout.write(f"Updated:   {updated}")
        self.stdout.write(f"Not found: {not_found}")
        self.stdout.write(f"Skipped:   {skipped}")

    @staticmethod
    def number(value):
        try:
            return int(float(value or 0))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def number_or_none(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None
