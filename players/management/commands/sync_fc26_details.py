import csv
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from players.fc26_faces import is_http_url, is_sofifa_face_url
from players.models import Player


POSITION_MAP = {
    "GK": "GK",
    "CB": "CB",
    "LB": "LB",
    "RB": "RB",
    "LWB": "LWB",
    "RWB": "RWB",
    "CDM": "CDM",
    "LDM": "CDM",
    "RDM": "CDM",
    "CM": "CM",
    "LCM": "CM",
    "RCM": "CM",
    "CAM": "CAM",
    "LAM": "CAM",
    "RAM": "CAM",
    "LM": "LM",
    "RM": "RM",
    "LW": "LW",
    "RW": "RW",
    "LF": "CF",
    "RF": "CF",
    "CF": "CF",
    "ST": "ST",
    "LS": "ST",
    "RS": "ST",
}

DETAIL_FIELDS = [
    "fc27_club",
    "nationality",
    "preferred_foot",
    "weak_foot",
    "skill_moves",
    "height_cm",
    "weight_kg",
]
FACE_FIELDS = ["player_face_url", "image_url"]
BATCH_SIZE = 400


class Command(BaseCommand):
    help = (
        "Sync FC26 details onto existing MGL players using fc27_id. "
        "Use --faces-only to populate player_face_url / image_url without "
        "touching other fields."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            type=str,
            help="Path to fc26_players_raw.csv",
        )
        parser.add_argument(
            "--faces-only",
            action="store_true",
            help="Only fill empty player_face_url / image_url fields.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count matches without writing to the database.",
        )
        parser.add_argument(
            "--no-name-fallback",
            action="store_true",
            help="Never match by name. Default already requires a unique name+OVR+position.",
        )

    def handle(self, *args, **options):
        csv_file = options["csv_file"]
        faces_only = options["faces_only"]
        dry_run = options["dry_run"]
        allow_name_fallback = not options["no_name_fallback"]

        try:
            handle = open(
                csv_file,
                "r",
                encoding="utf-8-sig",
                newline="",
            )
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_file}")

        updated = 0
        unchanged = 0
        not_found = 0
        skipped = 0
        name_assigned = 0
        name_ambiguous = 0
        changed_players = []

        with handle:
            reader = csv.DictReader(handle)

            required = {
                "player_id",
                "player_face_url",
            }
            if not faces_only:
                required.update(
                    {
                        "club_name",
                        "nationality_name",
                        "preferred_foot",
                        "weak_foot",
                        "skill_moves",
                        "height_cm",
                        "weight_kg",
                    }
                )

            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")

            missing = required - set(reader.fieldnames)
            if missing:
                raise CommandError(
                    "Missing CSV columns: " + ", ".join(sorted(missing))
                )

            rows = list(reader)

        players_by_id = {}
        missing_id = []
        for player in Player.objects.all():
            fc_id = self.normalize_fc_id(player.fc27_id)
            if fc_id:
                players_by_id[fc_id] = player
            else:
                missing_id.append(player)

        csv_by_id = {}
        name_index = defaultdict(list)

        for row in rows:
            fc_id = self.normalize_fc_id(row.get("player_id"))
            if not fc_id:
                skipped += 1
                continue
            csv_by_id[fc_id] = row
            if allow_name_fallback:
                for key in self.row_name_keys(row):
                    name_index[key].append(fc_id)

        seen_players = set()
        for fc_id, row in csv_by_id.items():
            player = players_by_id.get(fc_id)
            if player is None:
                not_found += 1
                continue
            seen_players.add(player.pk)
            if self.apply_row(player, row, faces_only=faces_only):
                changed_players.append(player)
                updated += 1
            else:
                unchanged += 1

        if allow_name_fallback:
            for player in missing_id:
                if player.pk in seen_players:
                    continue
                if self.has_face(player):
                    unchanged += 1
                    continue
                match_id = self.unique_name_match(player, name_index)
                if match_id is None:
                    name_ambiguous += 1
                    continue
                row = csv_by_id.get(match_id)
                if row is None:
                    name_ambiguous += 1
                    continue
                if self.apply_row(player, row, faces_only=True):
                    changed_players.append(player)
                    name_assigned += 1
                    updated += 1
                else:
                    unchanged += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no rows written."))
        else:
            fields = FACE_FIELDS if faces_only else DETAIL_FIELDS + FACE_FIELDS
            self.bulk_save(changed_players, fields)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("FC26 detail sync complete."))
        self.stdout.write(f"Updated:          {updated}")
        self.stdout.write(f"Unchanged:        {unchanged}")
        self.stdout.write(f"Not found:        {not_found}")
        self.stdout.write(f"Skipped:          {skipped}")
        self.stdout.write(f"Name fallback:    {name_assigned}")
        self.stdout.write(f"Name ambiguous:   {name_ambiguous}")

    def apply_row(self, player, row, faces_only):
        dirty = False
        if not faces_only:
            player.fc27_club = (row.get("club_name") or "").strip()
            player.nationality = (row.get("nationality_name") or "").strip()
            player.preferred_foot = (row.get("preferred_foot") or "").strip()
            player.weak_foot = self.number(row.get("weak_foot"))
            player.skill_moves = self.number(row.get("skill_moves"))
            player.height_cm = self.number_or_none(row.get("height_cm"))
            player.weight_kg = self.number_or_none(row.get("weight_kg"))
            dirty = True

        face_url = (row.get("player_face_url") or "").strip()
        if is_sofifa_face_url(face_url):
            if not self.has_url(player.player_face_url):
                player.player_face_url = face_url
                dirty = True
            if not self.has_url(player.image_url):
                player.image_url = face_url
                dirty = True
        return dirty

    def unique_name_match(self, player, name_index):
        name = (player.name or "").strip().casefold()
        if not name or not player.position:
            return None
        key = (name, int(player.overall or 0), player.position)
        ids = list(dict.fromkeys(name_index.get(key, [])))
        if len(ids) != 1:
            return None
        return ids[0]

    def row_name_keys(self, row):
        overall = self.number(row.get("overall"))
        position = self.primary_position(row.get("player_positions"))
        if not position:
            return []
        keys = []
        for field in ("long_name", "short_name"):
            name = (row.get(field) or "").strip().casefold()
            if name:
                keys.append((name, overall, position))
        return keys

    @staticmethod
    def primary_position(value):
        for pos in (value or "").split(","):
            mapped = POSITION_MAP.get(pos.strip().upper())
            if mapped:
                return mapped
        return ""

    @staticmethod
    def has_url(value):
        return is_http_url(value)

    def has_face(self, player):
        return self.has_url(player.player_face_url) or self.has_url(player.image_url)

    @staticmethod
    def normalize_fc_id(value):
        value = str(value or "").strip()
        if not value:
            return ""
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return value

    @staticmethod
    def bulk_save(players, fields):
        if not players:
            return
        Player.objects.bulk_update(players, fields, batch_size=BATCH_SIZE)

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
