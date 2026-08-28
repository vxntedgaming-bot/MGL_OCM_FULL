from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from players.fc26_faces import card_face_src, sofifa_url_for_size
from players.models import Player


SALAH_FACE = "https://cdn.sofifa.net/players/209/331/26_120.png"
MBAPPE_FACE = "https://cdn.sofifa.net/players/231/747/26_120.png"
BELLINGHAM_FACE = "https://cdn.sofifa.net/players/252/371/26_120.png"

CSV_HEADER = (
    "player_id,short_name,long_name,player_positions,overall,"
    "club_name,nationality_name,preferred_foot,weak_foot,skill_moves,"
    "height_cm,weight_kg,player_face_url"
)


def write_csv(rows):
    handle = NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8")
    handle.write(CSV_HEADER + "\n")
    for row in rows:
        handle.write(row + "\n")
    handle.close()
    return Path(handle.name)


class SyncFc26DetailsFaceTests(TestCase):
    def setUp(self):
        self.salah = Player.objects.create(
            name="Mohamed Salah Hamed Ghaly",
            fc27_id="209331",
            position="RM",
            overall=91,
            nationality="Old",
            is_free_agent=True,
        )
        self.mbappe = Player.objects.create(
            name="Kylian Mbappé Lottin",
            fc27_id="231747",
            position="ST",
            overall=91,
            is_free_agent=True,
        )
        self.jude = Player.objects.create(
            name="Jude Victor William Bellingham",
            fc27_id="252371",
            position="CAM",
            overall=90,
        )
        self.jobe = Player.objects.create(
            name="Jobe Samuel Patrick Bellingham",
            fc27_id="270964",
            position="CM",
            overall=74,
        )

    def test_faces_only_matches_fc27_id_and_skips_other_fields(self):
        csv_path = write_csv(
            [
                "209331,M. Salah,Mohamed Salah Hamed Ghaly,RM,91,Liverpool,Egypt,Left,3,4,175,71,"
                + SALAH_FACE,
                "231747,K. Mbappé,Kylian Mbappé Lottin,ST,91,Real Madrid,France,Right,4,5,182,75,"
                + MBAPPE_FACE,
                "252371,J. Bellingham,Jude Victor William Bellingham,CAM,90,Real Madrid,England,Right,4,4,186,75,"
                + BELLINGHAM_FACE,
                "270964,Jobe Bellingham,Jobe Samuel Patrick Bellingham,CM,74,Dortmund,England,Right,3,3,186,76,"
                + "https://cdn.sofifa.net/players/270/964/26_120.png",
            ]
        )
        out = StringIO()
        call_command("sync_fc26_details", str(csv_path), faces_only=True, stdout=out)

        self.salah.refresh_from_db()
        self.mbappe.refresh_from_db()
        self.jude.refresh_from_db()
        self.jobe.refresh_from_db()

        self.assertEqual(self.salah.player_face_url, SALAH_FACE)
        self.assertEqual(self.salah.image_url, SALAH_FACE)
        self.assertEqual(self.mbappe.player_face_url, MBAPPE_FACE)
        self.assertEqual(self.jude.player_face_url, BELLINGHAM_FACE)
        self.assertNotEqual(self.jobe.player_face_url, BELLINGHAM_FACE)
        self.assertEqual(self.salah.nationality, "Old")
        self.assertIn("Updated:          4", out.getvalue())

    def test_does_not_overwrite_existing_valid_face(self):
        existing = "https://cdn.sofifa.net/players/209/331/26_120.png"
        self.salah.player_face_url = existing
        self.salah.image_url = "https://example.com/custom-salah.png"
        self.salah.save(update_fields=["player_face_url", "image_url"])
        csv_path = write_csv(
            [
                "209331,M. Salah,Mohamed Salah Hamed Ghaly,RM,91,Liverpool,Egypt,Left,3,4,175,71,"
                + "https://cdn.sofifa.net/players/000/000/26_120.png",
            ]
        )
        call_command("sync_fc26_details", str(csv_path), faces_only=True, stdout=StringIO())
        self.salah.refresh_from_db()
        self.assertEqual(self.salah.player_face_url, existing)
        self.assertEqual(self.salah.image_url, "https://example.com/custom-salah.png")

    def test_similar_names_without_id_are_not_guessed(self):
        alex_a = Player.objects.create(name="Alex Smith", position="CM", overall=70)
        alex_b = Player.objects.create(name="Alex Smith", position="CM", overall=70)
        csv_path = write_csv(
            [
                "101,A. Smith,Alex Smith,CM,70,Club A,England,Right,3,3,180,75,"
                + "https://cdn.sofifa.net/players/000/101/26_120.png",
                "102,A. Smith,Alex Smith,CM,70,Club B,England,Right,3,3,181,76,"
                + "https://cdn.sofifa.net/players/000/102/26_120.png",
            ]
        )
        call_command("sync_fc26_details", str(csv_path), faces_only=True, stdout=StringIO())
        alex_a.refresh_from_db()
        alex_b.refresh_from_db()
        self.assertEqual(alex_a.player_face_url, "")
        self.assertEqual(alex_b.player_face_url, "")

    def test_unique_name_overall_position_fallback_only_without_fc_id(self):
        unique = Player.objects.create(
            name="Unique Fallback",
            position="ST",
            overall=66,
        )
        csv_path = write_csv(
            [
                "888001,U. Fallback,Unique Fallback,ST,66,Free,Spain,Right,3,3,180,75,"
                + "https://cdn.sofifa.net/players/888/001/26_120.png",
            ]
        )
        call_command("sync_fc26_details", str(csv_path), faces_only=True, stdout=StringIO())
        unique.refresh_from_db()
        self.assertEqual(
            unique.player_face_url,
            "https://cdn.sofifa.net/players/888/001/26_120.png",
        )


class PlayerFaceDisplayTests(TestCase):
    def test_card_uses_same_origin_proxy_for_sofifa_urls(self):
        player = Player.objects.create(
            name="Mohamed Salah Hamed Ghaly",
            fc27_id="209331",
            position="RM",
            overall=91,
            player_face_url=SALAH_FACE,
            image_url=SALAH_FACE,
            is_free_agent=True,
        )
        self.assertEqual(
            card_face_src(player, "standard"),
            reverse("player_face_image", args=[player.pk]),
        )
        self.assertEqual(
            card_face_src(player, "small"),
            reverse("player_face_image", args=[player.pk]) + "?s=60",
        )
        self.assertEqual(
            sofifa_url_for_size(SALAH_FACE, "60"),
            "https://cdn.sofifa.net/players/209/331/26_60.png",
        )

    @override_settings(MEDIA_ROOT="/tmp/mgl-face-test-media")
    def test_face_proxy_serves_cached_png_and_rejects_unknown_hosts(self):
        png = b"\x89PNG\r\n\x1a\n" + b"cached"
        player = Player.objects.create(
            name="Kylian Mbappé Lottin",
            fc27_id="231747",
            position="ST",
            overall=91,
            player_face_url=MBAPPE_FACE,
        )
        with patch("players.fc26_faces.fetch_sofifa_png", return_value=png):
            response = self.client.get(reverse("player_face_image", args=[player.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, png)

        bare = Player.objects.create(name="No Face", overall=50, position="CB")
        missing = self.client.get(reverse("player_face_image", args=[bare.pk]))
        self.assertEqual(missing.status_code, 404)
