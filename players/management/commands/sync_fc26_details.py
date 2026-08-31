import csv
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from players.fc26_attributes import (
    ATTR_FIELD_NAMES,
    CSV_ATTR_NAMES,
    apply_fc26_attributes,
    attribute_completeness,
)
from players.fc26_faces import is_http_url, is_sofifa_face_url
from players.fc26_names import display_name_from_row, fold_search_text, latin_name
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
NAME_FIELDS = ["name"]
ATTRIBUTE_FIELDS = ATTR_FIELD_NAMES + [
    "fc_work_rate",
    "date_of_birth",
    "age",
    "fc_playstyles",
    "fc_playstyle_plus",
]
BATCH_SIZE = 400
SQLITE_VAR_LIMIT = 900


class Command(BaseCommand):
    help = (
        "Sync FC26 details onto existing MGL players using fc27_id. "
        "Use --faces-only for headshots, --attributes-only for individual "
        "FC26 attributes and recognised display names. Never creates players "
        "and never changes MGL club, transfers, OVR, position or MGL stats."
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
            "--attributes-only",
            action="store_true",
            help=(
                "Only populate FC26 individual attributes and the recognised "
                "display name. Does not change faces, MGL ownership, OVR or position."
            ),
        )
        parser.add_argument(
            "--identity-only",
            action="store_true",
            help=(
                "Fill empty DOB, age, preferred foot, weak foot, skill moves, "
                "and playstyles only. Never overwrites a value that is already set."
            ),
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
        exclusive = [options["faces_only"], options["attributes_only"], options["identity_only"]]
        if sum(bool(flag) for flag in exclusive) > 1:
            raise CommandError("Use only one of --faces-only, --attributes-only, or --identity-only.")
        if options["identity_only"]:
            return self.handle_identity(options)
        if options["attributes_only"]:
            return self.handle_attributes(options)
        return self.handle_details(options)

    def handle_identity(self, options):
        from players.display import apply_fc26_identity

        csv_file = options["csv_file"]
        dry_run = options["dry_run"]
        rows = self.read_csv(
            csv_file,
            required={"player_id", "dob", "age", "preferred_foot", "weak_foot", "skill_moves"},
        )
        players_by_id, _missing = self.index_players()
        csv_by_id, skipped = self.index_csv_rows(rows)
        updated = 0
        unchanged = 0
        not_found = 0
        changed_players = []
        changed_fields = set()
        for fc_id, row in csv_by_id.items():
            player = players_by_id.get(fc_id)
            if player is None:
                not_found += 1
                continue
            fields = apply_fc26_identity(player, row)
            if fields:
                changed_players.append(player)
                changed_fields.update(fields)
                updated += 1
            else:
                unchanged += 1
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no rows written."))
        else:
            self.bulk_save(
                changed_players,
                sorted(changed_fields)
                or [
                    "date_of_birth",
                    "age",
                    "preferred_foot",
                    "weak_foot",
                    "skill_moves",
                    "fc_playstyles",
                    "fc_playstyle_plus",
                ],
            )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("FC26 identity fill complete."))
        self.stdout.write(f"Updated:   {updated}")
        self.stdout.write(f"Unchanged: {unchanged}")
        self.stdout.write(f"Not found: {not_found}")
        self.stdout.write(f"Skipped:   {skipped}")
        if changed_fields:
            self.stdout.write(f"Fields:    {', '.join(sorted(changed_fields))}")

    def handle_attributes(self, options):
        csv_file = options["csv_file"]
        dry_run = options["dry_run"]
        allow_name_fallback = not options["no_name_fallback"]
        rows = self.read_csv(
            csv_file,
            required={"player_id", "short_name", "long_name"} | set(CSV_ATTR_NAMES),
        )

        players_by_id, missing_id = self.index_players()
        csv_by_id, skipped = self.index_csv_rows(rows)
        name_index = defaultdict(list)
        if allow_name_fallback:
            for fc_id, row in csv_by_id.items():
                for key in self.attribute_row_keys(row):
                    name_index[key].append(fc_id)

        matched_id = 0
        matched_name = 0
        unmatched_players = 0
        ambiguous = 0
        updated = 0
        unchanged = 0
        names_updated = 0
        complete = 0
        partial = 0
        empty = 0
        changed_players = []
        changed_fields = set()
        seen = set()

        for fc_id, player in players_by_id.items():
            row = csv_by_id.get(fc_id)
            if row is None:
                unmatched_players += 1
                continue
            seen.add(player.pk)
            matched_id += 1
            fields = self.apply_attributes_and_name(player, row)
            status = attribute_completeness(player)
            if status == "complete":
                complete += 1
            elif status == "partial":
                partial += 1
            else:
                empty += 1
            if fields:
                changed_players.append(player)
                changed_fields.update(fields)
                updated += 1
                if "name" in fields:
                    names_updated += 1
            else:
                unchanged += 1

        unmatched_csv = sum(1 for fc_id in csv_by_id if fc_id not in players_by_id)

        if allow_name_fallback:
            for player in missing_id:
                if player.pk in seen:
                    continue
                match_id, reason = self.unique_attribute_match(player, name_index)
                if reason == "ambiguous":
                    ambiguous += 1
                    unmatched_players += 1
                    continue
                if match_id is None:
                    unmatched_players += 1
                    continue
                row = csv_by_id.get(match_id)
                if row is None:
                    unmatched_players += 1
                    continue
                matched_name += 1
                seen.add(player.pk)
                fields = self.apply_attributes_and_name(player, row)
                status = attribute_completeness(player)
                if status == "complete":
                    complete += 1
                elif status == "partial":
                    partial += 1
                else:
                    empty += 1
                if fields:
                    changed_players.append(player)
                    changed_fields.update(fields)
                    updated += 1
                    if "name" in fields:
                        names_updated += 1
                else:
                    unchanged += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no rows written."))
        else:
            self.bulk_save(changed_players, sorted(changed_fields) or ATTRIBUTE_FIELDS)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("FC26 attribute sync complete."))
        self.stdout.write(f"Matched by ID:           {matched_id}")
        self.stdout.write(f"Matched by name/club/pos: {matched_name}")
        self.stdout.write(f"Unmatched players:       {unmatched_players}")
        self.stdout.write(f"Unmatched CSV rows:      {unmatched_csv}")
        self.stdout.write(f"Ambiguous matches:       {ambiguous}")
        self.stdout.write(f"Updated:                 {updated}")
        self.stdout.write(f"Unchanged:               {unchanged}")
        self.stdout.write(f"Names updated:           {names_updated}")
        self.stdout.write(f"Complete attributes:     {complete}")
        self.stdout.write(f"Partial attributes:      {partial}")
        self.stdout.write(f"Empty attributes:        {empty}")
        self.stdout.write(f"Skipped CSV rows:        {skipped}")

    def handle_details(self, options):
        csv_file = options["csv_file"]
        faces_only = options["faces_only"]
        dry_run = options["dry_run"]
        allow_name_fallback = not options["no_name_fallback"]

        required = {"player_id", "player_face_url"}
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
                    "short_name",
                    "long_name",
                }
            )
            required.update(CSV_ATTR_NAMES)

        rows = self.read_csv(csv_file, required=required)

        updated = 0
        unchanged = 0
        not_found = 0
        skipped = 0
        name_assigned = 0
        name_ambiguous = 0
        changed_players = []
        changed_fields = set()

        players_by_id, missing_id = self.index_players()
        csv_by_id, skipped = self.index_csv_rows(rows)
        name_index = defaultdict(list)
        if allow_name_fallback:
            for fc_id, row in csv_by_id.items():
                for key in self.row_name_keys(row):
                    name_index[key].append(fc_id)

        seen_players = set()
        for fc_id, row in csv_by_id.items():
            player = players_by_id.get(fc_id)
            if player is None:
                not_found += 1
                continue
            seen_players.add(player.pk)
            fields = self.apply_row(player, row, faces_only=faces_only)
            if fields:
                changed_players.append(player)
                changed_fields.update(fields)
                updated += 1
            else:
                unchanged += 1

        if allow_name_fallback:
            for player in missing_id:
                if player.pk in seen_players:
                    continue
                if faces_only and self.has_face(player):
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
                fields = self.apply_row(player, row, faces_only=faces_only)
                if fields:
                    changed_players.append(player)
                    changed_fields.update(fields)
                    name_assigned += 1
                    updated += 1
                else:
                    unchanged += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no rows written."))
        else:
            if faces_only:
                fields = FACE_FIELDS
            else:
                fields = sorted(changed_fields) or (DETAIL_FIELDS + FACE_FIELDS + NAME_FIELDS + ATTRIBUTE_FIELDS)
            self.bulk_save(changed_players, fields)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("FC26 detail sync complete."))
        self.stdout.write(f"Updated:          {updated}")
        self.stdout.write(f"Unchanged:        {unchanged}")
        self.stdout.write(f"Not found:        {not_found}")
        self.stdout.write(f"Skipped:          {skipped}")
        self.stdout.write(f"Name fallback:    {name_assigned}")
        self.stdout.write(f"Name ambiguous:   {name_ambiguous}")

    def apply_attributes_and_name(self, player, row):
        changed = apply_fc26_attributes(player, row)
        display = display_name_from_row(row)
        if display and (player.name or "").strip() != display:
            player.name = display
            changed.append("name")
        return changed

    def apply_row(self, player, row, faces_only):
        changed = []
        if not faces_only:
            mapping = {
                "fc27_club": (row.get("club_name") or "").strip(),
                "nationality": (row.get("nationality_name") or "").strip(),
                "preferred_foot": (row.get("preferred_foot") or "").strip(),
                "weak_foot": self.number(row.get("weak_foot")),
                "skill_moves": self.number(row.get("skill_moves")),
                "height_cm": self.number_or_none(row.get("height_cm")),
                "weight_kg": self.number_or_none(row.get("weight_kg")),
            }
            for field, value in mapping.items():
                if getattr(player, field) != value:
                    setattr(player, field, value)
                    changed.append(field)
            changed.extend(self.apply_attributes_and_name(player, row))

        face_url = (row.get("player_face_url") or "").strip()
        if is_sofifa_face_url(face_url):
            if not self.has_url(player.player_face_url):
                player.player_face_url = face_url
                changed.append("player_face_url")
            if not self.has_url(player.image_url):
                player.image_url = face_url
                changed.append("image_url")
        return list(dict.fromkeys(changed))

    def unique_name_match(self, player, name_index):
        name = (player.name or "").strip().casefold()
        if not name or not player.position:
            return None
        key = (name, int(player.overall or 0), player.position)
        ids = list(dict.fromkeys(name_index.get(key, [])))
        if len(ids) != 1:
            return None
        return ids[0]

    def unique_attribute_match(self, player, name_index):
        name = fold_search_text(player.name)
        position = (player.position or "").strip()
        if not name or not position:
            return None, "unmatched"
        club = fold_search_text(player.fc27_club)
        overall = int(player.overall or 0)
        candidates = []
        for key in (
            ("npc", name, position, club),
            ("npo", name, position, overall),
        ):
            if key[0] == "npc" and not club:
                continue
            ids = list(dict.fromkeys(name_index.get(key, [])))
            if len(ids) == 1:
                return ids[0], "unique"
            if len(ids) > 1:
                candidates.extend(ids)
        if candidates:
            return None, "ambiguous"
        return None, "unmatched"

    def attribute_row_keys(self, row):
        position = self.primary_position(row.get("player_positions"))
        if not position:
            return []
        overall = self.number(row.get("overall"))
        club = fold_search_text(row.get("club_name"))
        names = []
        display = display_name_from_row(row)
        if display:
            names.append(display)
        for field in ("short_name", "long_name"):
            raw = (row.get(field) or "").strip()
            if raw:
                names.append(raw)
            latin = latin_name(raw)
            if latin:
                names.append(latin)
        keys = []
        seen = set()
        for name in names:
            folded = fold_search_text(name)
            if not folded or folded in seen:
                continue
            seen.add(folded)
            keys.append(("npc", folded, position, club))
            keys.append(("npo", folded, position, overall))
        return keys

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
        display = display_name_from_row(row)
        if display:
            keys.append((display.casefold(), overall, position))
        return keys

    def read_csv(self, csv_file, required):
        try:
            handle = open(csv_file, "r", encoding="utf-8-sig", newline="")
        except FileNotFoundError:
            raise CommandError(f"File not found: {csv_file}")
        with handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            missing = required - set(reader.fieldnames)
            if missing:
                raise CommandError(
                    "Missing CSV columns: " + ", ".join(sorted(missing))
                )
            return list(reader)

    def index_players(self):
        players_by_id = {}
        missing_id = []
        for player in Player.objects.all():
            fc_id = self.normalize_fc_id(player.fc27_id)
            if fc_id:
                players_by_id[fc_id] = player
            else:
                missing_id.append(player)
        return players_by_id, missing_id

    def index_csv_rows(self, rows):
        csv_by_id = {}
        skipped = 0
        for row in rows:
            fc_id = self.normalize_fc_id(row.get("player_id"))
            if not fc_id:
                skipped += 1
                continue
            csv_by_id[fc_id] = row
        return csv_by_id, skipped

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
        if not players or not fields:
            return
        batch = max(1, SQLITE_VAR_LIMIT // (len(fields) + 1))
        Player.objects.bulk_update(players, fields, batch_size=min(BATCH_SIZE, batch))

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
