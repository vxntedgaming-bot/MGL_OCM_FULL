from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
import csv

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_super_league_1
from players.fc26_attributes import (
    ATTR_COLUMNS,
    CSV_ATTR_NAMES,
    apply_fc26_attributes,
    attribute_groups_for_player,
    parse_attr_value,
)
from players.models import Player
from teams.models import Team


RAW_CSV = Path("fc26_players_raw.csv")


def attr_csv(rows):
    fieldnames = [
        "player_id",
        "short_name",
        "long_name",
        "player_positions",
        "overall",
        "club_name",
        "work_rate",
        "player_face_url",
        *CSV_ATTR_NAMES,
    ]
    handle = NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    handle.close()
    return Path(handle.name)


def raw_row(player_id):
    with RAW_CSV.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("player_id")) == str(player_id):
                return row
    raise AssertionError(f"Missing FC26 row {player_id}")


class Fc26AttributeMappingTests(TestCase):
    def test_source_values_map_onto_player_fields(self):
        self.assertTrue(RAW_CSV.exists())
        cases = {
            "209331": {"fc_finishing": 94, "fc_sprint_speed": 89, "fc_gk_speed": None},
            "231747": {"fc_finishing": 92, "fc_sprint_speed": 97, "fc_dribbling": 92},
            "235212": {"fc_sprint_speed": 95, "fc_standing_tackle": 85, "fc_marking": 82},
            "203376": {"fc_heading": 88, "fc_marking": 91, "fc_standing_tackle": 91},
            "192985": {"fc_vision": 92, "fc_short_passing": 92, "fc_long_passing": 93},
            "212831": {"fc_gk_diving": 86, "fc_gk_speed": 56, "fc_reactions": 87},
        }
        for fc_id, expected in cases.items():
            source = raw_row(fc_id)
            player = Player(name="tmp", fc27_id=fc_id, position="ST")
            apply_fc26_attributes(player, source)
            for field, value in expected.items():
                self.assertEqual(getattr(player, field), value, f"{fc_id} {field}")
            for field, csv_name in ATTR_COLUMNS:
                self.assertEqual(
                    getattr(player, field),
                    parse_attr_value(source.get(csv_name)),
                    f"{fc_id} {field} != source {csv_name}",
                )


class SyncFc26AttributesCommandTests(TestCase):
    def setUp(self):
        self.league = ensure_super_league_1()
        self.team = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
        )
        self.salah = Player.objects.create(
            name="Mohamed Salah Hamed Ghaly",
            fc27_id="209331",
            position="RM",
            overall=91,
            pace=89,
            shooting=88,
            mgl_team=self.team,
            is_free_agent=False,
            goals=12,
            assists=4,
        )
        self.mbappe = Player.objects.create(
            name="Kylian Mbappé Lottin",
            fc27_id="231747",
            position="ST",
            overall=91,
            is_free_agent=True,
        )
        self.hakimi = Player.objects.create(
            name="Achraf Hakimi Mouh",
            fc27_id="235212",
            position="RB",
            overall=89,
            is_free_agent=True,
        )
        self.alisson = Player.objects.create(
            name="Alisson",
            fc27_id="212831",
            position="GK",
            overall=89,
            is_free_agent=True,
        )

    def _rows_from_source(self, *ids):
        rows = []
        for fc_id in ids:
            source = raw_row(fc_id)
            row = {
                "player_id": source["player_id"],
                "short_name": source["short_name"],
                "long_name": source["long_name"],
                "player_positions": source["player_positions"],
                "overall": source["overall"],
                "club_name": source.get("club_name", ""),
                "work_rate": source.get("work_rate", ""),
                "player_face_url": source.get("player_face_url", ""),
            }
            for csv_name in CSV_ATTR_NAMES:
                row[csv_name] = source.get(csv_name, "")
            rows.append(row)
        return rows

    def test_attributes_only_matches_by_id_without_duplicates_or_mgl_overwrite(self):
        csv_path = attr_csv(self._rows_from_source("209331", "231747", "235212", "212831"))
        before = Player.objects.count()
        out = StringIO()
        call_command("sync_fc26_details", str(csv_path), attributes_only=True, stdout=out)
        report = out.getvalue()

        self.salah.refresh_from_db()
        self.mbappe.refresh_from_db()
        self.hakimi.refresh_from_db()
        self.alisson.refresh_from_db()

        self.assertEqual(Player.objects.count(), before)
        self.assertEqual(self.salah.name, "Mohamed Salah")
        self.assertEqual(self.mbappe.name, "Kylian Mbappé")
        self.assertEqual(self.hakimi.name, "Achraf Hakimi")
        self.assertEqual(self.salah.mgl_team_id, self.team.id)
        self.assertFalse(self.salah.is_free_agent)
        self.assertEqual(self.salah.overall, 91)
        self.assertEqual(self.salah.position, "RM")
        self.assertEqual(self.salah.pace, 89)
        self.assertEqual(self.salah.goals, 12)
        self.assertEqual(self.salah.fc_finishing, 94)
        self.assertEqual(self.salah.fc_sprint_speed, 89)
        self.assertEqual(self.mbappe.fc_sprint_speed, 97)
        self.assertEqual(self.hakimi.fc_standing_tackle, 85)
        self.assertEqual(self.alisson.fc_gk_diving, 86)
        self.assertEqual(self.alisson.fc_gk_speed, 56)
        self.assertIsNone(self.salah.fc_gk_speed)
        self.assertIn("Matched by ID:           4", report)
        self.assertIn("Unmatched players:       0", report)
        self.assertIn("Ambiguous matches:       0", report)
        self.assertIn("Complete attributes:     4", report)

        again = StringIO()
        call_command("sync_fc26_details", str(csv_path), attributes_only=True, stdout=again)
        self.assertEqual(Player.objects.count(), before)
        self.assertIn("Updated:                 0", again.getvalue())

    def test_name_club_position_fallback_is_unique_and_ambiguous_safe(self):
        unique = Player.objects.create(
            name="Unique Fallback",
            position="ST",
            overall=66,
            fc27_club="Free",
        )
        a = Player.objects.create(name="Alex Smith", position="CM", overall=70, fc27_club="Club A")
        b = Player.objects.create(name="Alex Smith", position="CM", overall=70, fc27_club="Club A")
        rows = self._rows_from_source("209331")
        rows[0]["player_id"] = "888001"
        rows[0]["short_name"] = "U. Fallback"
        rows[0]["long_name"] = "Unique Fallback"
        rows[0]["player_positions"] = "ST"
        rows[0]["overall"] = "66"
        rows[0]["club_name"] = "Free"
        twin = dict(rows[0])
        twin["player_id"] = "101"
        twin["short_name"] = "A. Smith"
        twin["long_name"] = "Alex Smith"
        twin["player_positions"] = "CM"
        twin["overall"] = "70"
        twin["club_name"] = "Club A"
        twin2 = dict(twin)
        twin2["player_id"] = "102"
        csv_path = attr_csv(rows + [twin, twin2])
        call_command("sync_fc26_details", str(csv_path), attributes_only=True, stdout=StringIO())
        unique.refresh_from_db()
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(unique.fc_finishing, 94)
        self.assertIsNone(a.fc_finishing)
        self.assertIsNone(b.fc_finishing)


class PlayerAttributeProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="attruser", password="test-pass-123")
        self.salah = Player.objects.create(
            name="Mohamed Salah",
            fc27_id="209331",
            position="RM",
            overall=91,
            pace=89,
            shooting=88,
            passing=86,
            dribbling=90,
            defending=45,
            physical=76,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.salah, raw_row("209331"))
        self.salah.save()
        self.gk = Player.objects.create(
            name="Alisson",
            fc27_id="212831",
            position="GK",
            overall=89,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.gk, raw_row("212831"))
        self.gk.save()
        self.mbappe = Player.objects.create(
            name="Kylian Mbappé",
            fc27_id="231747",
            position="ST",
            overall=91,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.mbappe, raw_row("231747"))
        self.mbappe.save()
        self.hakimi = Player.objects.create(
            name="Achraf Hakimi",
            fc27_id="235212",
            position="RB",
            overall=89,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.hakimi, raw_row("235212"))
        self.hakimi.save()
        self.vvd = Player.objects.create(
            name="Virgil van Dijk",
            fc27_id="203376",
            position="CB",
            overall=90,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.vvd, raw_row("203376"))
        self.vvd.save()
        self.kdb = Player.objects.create(
            name="Kevin De Bruyne",
            fc27_id="192985",
            position="CM",
            overall=87,
            is_free_agent=True,
        )
        apply_fc26_attributes(self.kdb, raw_row("192985"))
        self.kdb.save()
        self.bare = Player.objects.create(
            name="No Attributes Yet",
            position="CB",
            overall=60,
            is_free_agent=True,
        )

    def test_profile_renders_player_own_fc26_attributes(self):
        self.client.login(username="attruser", password="test-pass-123")
        salah = self.client.get(reverse("player_profile", args=[self.salah.id]))
        self.assertEqual(salah.status_code, 200)
        self.assertContains(salah, "PLAYER ATTRIBUTES")
        self.assertContains(salah, "Mohamed Salah")
        self.assertContains(salah, "Sprint Speed")
        self.assertContains(salah, "94")
        self.assertContains(salah, "Finishing")
        self.assertContains(salah, "mgl/cards/gold_card.png")
        self.assertContains(salah, "FREE AGENT")
        self.assertNotContains(salah, "Ghaly")
        self.assertNotContains(salah, "GOALKEEPING")

        mbappe = self.client.get(reverse("player_profile", args=[self.mbappe.id]))
        self.assertContains(mbappe, "Kylian Mbappé")
        self.assertContains(mbappe, "97")
        self.assertNotContains(mbappe, "Lottin")

        hakimi = self.client.get(reverse("player_profile", args=[self.hakimi.id]))
        self.assertContains(hakimi, "Achraf Hakimi")
        self.assertContains(hakimi, "Standing Tackle")
        self.assertContains(hakimi, "85")
        self.assertNotContains(hakimi, "Mouh")

        defender = self.client.get(reverse("player_profile", args=[self.vvd.id]))
        self.assertContains(defender, "Virgil van Dijk")
        self.assertContains(defender, "Defensive Awareness")
        self.assertContains(defender, "91")

        midfielder = self.client.get(reverse("player_profile", args=[self.kdb.id]))
        self.assertContains(midfielder, "Kevin De Bruyne")
        self.assertContains(midfielder, "Vision")
        self.assertContains(midfielder, "92")

        gk = self.client.get(reverse("player_profile", args=[self.gk.id]))
        self.assertContains(gk, "GOALKEEPING")
        self.assertContains(gk, "Diving")
        self.assertContains(gk, "86")
        self.assertContains(gk, "Speed")

        bare = self.client.get(reverse("player_profile", args=[self.bare.id]))
        self.assertContains(bare, "PLAYER ATTRIBUTES")
        self.assertContains(bare, "—")
        self.assertContains(bare, "Sprint Speed")

    def test_search_still_uses_recognised_display_name(self):
        self.client.login(username="attruser", password="test-pass-123")
        response = self.client.get(reverse("player_database"), {"search": "Salah"})
        self.assertContains(response, "MOHAMED SALAH")
        mbappe = self.client.get(reverse("player_database"), {"search": "Mbappe"})
        self.assertContains(mbappe, "KYLIAN MBAPPÉ")
        hakimi = self.client.get(reverse("player_database"), {"search": "Hakimi"})
        self.assertContains(hakimi, "ACHRAF HAKIMI")

    def test_groups_include_all_six_outfield_blocks(self):
        titles = [group["title"] for group in attribute_groups_for_player(self.salah)]
        self.assertEqual(
            titles,
            ["PACE", "SHOOTING", "PASSING", "DRIBBLING", "DEFENDING", "PHYSICAL"],
        )
        gk_titles = [group["title"] for group in attribute_groups_for_player(self.gk)]
        self.assertIn("GOALKEEPING", gk_titles)
