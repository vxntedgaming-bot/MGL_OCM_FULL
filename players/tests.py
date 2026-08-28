from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from players.fc26_faces import (
    card_face_src,
    sofifa_id_from_url,
    sofifa_url_for_size,
    sofifa_variant_urls,
)
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
            head = self.client.head(reverse("player_face_image", args=[player.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, png)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head["Content-Type"], "image/png")

        bare = Player.objects.create(name="No Face", overall=50, position="CB")
        missing = self.client.get(reverse("player_face_image", args=[bare.pk]))
        self.assertEqual(missing.status_code, 404)

    def test_sofifa_year_variants_stay_on_the_same_player_path(self):
        urls = sofifa_variant_urls(SALAH_FACE, "120")
        self.assertEqual(urls[0], SALAH_FACE)
        self.assertIn("https://cdn.sofifa.net/players/209/331/25_120.png", urls)
        self.assertTrue(all("/209/331/" in url for url in urls))
        self.assertFalse(any("/233/988/" in url for url in urls))
        self.assertTrue(all(sofifa_id_from_url(url) == 209331 for url in urls))

    def test_sofifa_padding_variants_stay_on_the_same_numeric_id(self):
        stored = "https://cdn.sofifa.net/players/079/985/26_120.png"
        urls = sofifa_variant_urls(stored, "120")
        self.assertEqual(sofifa_id_from_url(stored), 79985)
        self.assertIn("https://cdn.sofifa.net/players/079/985/26_120.png", urls)
        self.assertIn("https://cdn.sofifa.net/players/79/985/26_120.png", urls)
        self.assertTrue(all(sofifa_id_from_url(url) == 79985 for url in urls))
        self.assertFalse(any("/080/985/" in url for url in urls))
        self.assertFalse(any("/233/988/" in url for url in urls))

    @override_settings(MEDIA_ROOT="/tmp/mgl-face-year-fallback-media")
    def test_proxy_uses_same_id_older_sofifa_year_when_26_is_missing(self):
        png = b"\x89PNG\r\n\x1a\n" + b"year25"
        player = Player.objects.create(
            name="Abdelkarim Hassan",
            fc27_id="239861",
            position="LB",
            overall=73,
            player_face_url="https://cdn.sofifa.net/players/239/861/26_120.png",
            image_url="https://cdn.sofifa.net/players/239/861/26_120.png",
        )
        stored = player.player_face_url

        def fake_fetch(url, attempts=3):
            if url.endswith("/239/861/25_120.png"):
                return png
            return None

        with patch("players.fc26_faces.fetch_sofifa_png", side_effect=fake_fetch):
            response = self.client.get(reverse("player_face_image", args=[player.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, png)
        player.refresh_from_db()
        self.assertEqual(player.player_face_url, stored)
        self.assertEqual(player.fc27_id, "239861")
        self.assertEqual(player.overall, 73)
        self.assertEqual(player.position, "LB")
        self.assertEqual(Player.objects.filter(fc27_id="239861").count(), 1)

    @override_settings(MEDIA_ROOT="/tmp/mgl-face-missing-media")
    def test_proxy_stays_404_when_this_player_has_no_sofifa_portrait(self):
        player = Player.objects.create(
            name="Vágner Norteiro",
            fc27_id="233988",
            position="RB",
            overall=69,
            player_face_url="https://cdn.sofifa.net/players/233/988/26_120.png",
        )
        with patch("players.fc26_faces.fetch_sofifa_png", return_value=None) as fetch:
            response = self.client.get(reverse("player_face_image", args=[player.pk]))
            self.assertEqual(response.status_code, 404)
            first_calls = fetch.call_count
            again = self.client.get(reverse("player_face_image", args=[player.pk]))
        self.assertEqual(again.status_code, 404)
        self.assertGreater(first_calls, 0)
        self.assertEqual(fetch.call_count, first_calls)
        fetched_ids = {sofifa_id_from_url(call.args[0]) for call in fetch.call_args_list}
        self.assertEqual(fetched_ids, {233988})
        player.refresh_from_db()
        self.assertEqual(
            player.player_face_url,
            "https://cdn.sofifa.net/players/233/988/26_120.png",
        )
        self.assertEqual(player.fc27_id, "233988")
        self.assertEqual(Player.objects.filter(name="Vágner Norteiro").count(), 1)


class Fc26DisplayNameTests(TestCase):
    def test_short_name_plus_long_name_yields_recognised_names(self):
        from players.fc26_names import fc26_display_name, name_matches_query

        cases = [
            ("M. Salah", "Mohamed Salah Hamed Ghalyمحمد صلاح", "Mohamed Salah"),
            ("K. Mbappé", "Kylian Mbappé Lottin", "Kylian Mbappé"),
            ("A. Hakimi", "Achraf Hakimi Mouhأشرف حكيمي", "Achraf Hakimi"),
            ("J. Bellingham", "Jude Victor William Bellingham", "Jude Bellingham"),
            ("E. Haaland", "Erling Braut Håland", "Erling Haaland"),
            ("K. De Bruyne", "Kevin De Bruyne", "Kevin De Bruyne"),
            ("Rodri", "Rodrigo Hernández Cascante", "Rodri"),
            ("Bruno Fernandes", "Bruno Miguel Borges Fernandes", "Bruno Fernandes"),
            ("Vini Jr.", "Vinicius José Paixão de Oliveira Junior", "Vini Jr."),
            ("Cristiano Ronaldo", "Cristiano Ronaldo dos Santos Aveiro", "Cristiano Ronaldo"),
            ("J. St. Juste", "Jeremiah Israël St. Juste", "Jeremiah St. Juste"),
            ("A. Rabiot", "Adrien Rabiot-Provost", "Adrien Rabiot"),
            ("N. Kanté", "N'Golo Kanté", "N'Golo Kanté"),
        ]
        for short_name, long_name, expected in cases:
            self.assertEqual(
                fc26_display_name(short_name, long_name),
                expected,
                msg=short_name,
            )

        self.assertTrue(name_matches_query("Kylian Mbappé", "Mbappe"))
        self.assertTrue(name_matches_query("Kylian Mbappé", "Mbappé"))
        self.assertTrue(name_matches_query("Mohamed Salah", "Salah"))
        self.assertTrue(name_matches_query("Achraf Hakimi", "Hakimi"))
        self.assertFalse(name_matches_query("Mohamed Salah", "Ghaly"))
        self.assertFalse(name_matches_query("Kylian Mbappé", "Lottin"))
        self.assertFalse(name_matches_query("Achraf Hakimi", "Mouh"))

    def test_names_only_sync_updates_existing_rows_without_duplicates(self):
        salah = Player.objects.create(
            name="Mohamed Salah Hamed Ghaly",
            fc27_id="209331",
            position="RM",
            overall=91,
            nationality="Egypt",
            pace=89,
        )
        mbappe = Player.objects.create(
            name="Kylian Mbappé Lottin",
            fc27_id="231747",
            position="ST",
            overall=91,
            shooting=90,
        )
        hakimi = Player.objects.create(
            name="Achraf Hakimi Mouh",
            fc27_id="235212",
            position="RB",
            overall=89,
            defending=80,
        )
        csv_path = write_csv(
            [
                "209331,M. Salah,Mohamed Salah Hamed Ghaly,RM,91,Liverpool,Egypt,Left,3,4,175,71,"
                + SALAH_FACE,
                "231747,K. Mbappé,Kylian Mbappé Lottin,ST,91,Real Madrid,France,Right,4,5,182,75,"
                + MBAPPE_FACE,
                "235212,A. Hakimi,Achraf Hakimi Mouh,RB,89,PSG,Morocco,Right,3,3,181,73,"
                + "https://cdn.sofifa.net/players/235/212/26_120.png",
            ]
        )
        before = Player.objects.count()
        out = StringIO()
        call_command("sync_fc26_names", str(csv_path), stdout=out)

        salah.refresh_from_db()
        mbappe.refresh_from_db()
        hakimi.refresh_from_db()

        self.assertEqual(salah.name, "Mohamed Salah")
        self.assertEqual(mbappe.name, "Kylian Mbappé")
        self.assertEqual(hakimi.name, "Achraf Hakimi")
        self.assertEqual(salah.overall, 91)
        self.assertEqual(salah.pace, 89)
        self.assertEqual(mbappe.shooting, 90)
        self.assertEqual(hakimi.defending, 80)
        self.assertEqual(salah.nationality, "Egypt")
        self.assertEqual(Player.objects.count(), before)
        self.assertEqual(
            Player.objects.filter(fc27_id__in=["209331", "231747", "235212"]).count(),
            3,
        )
        self.assertIn("Updated:    3", out.getvalue())

        again = StringIO()
        call_command("sync_fc26_names", str(csv_path), stdout=again)
        self.assertEqual(Player.objects.count(), before)
        self.assertIn("Updated:    0", again.getvalue())
        self.assertIn("Unchanged:  3", again.getvalue())


class PlayerDisplayNameSearchTests(TestCase):
    def setUp(self):
        from accounts.models import User

        self.user = User.objects.create_user(username="namesearch", password="test-pass-123")
        self.salah = Player.objects.create(
            name="Mohamed Salah",
            fc27_id="209331",
            position="RM",
            overall=91,
            is_free_agent=True,
        )
        self.mbappe = Player.objects.create(
            name="Kylian Mbappé",
            fc27_id="231747",
            position="ST",
            overall=91,
            is_free_agent=True,
        )
        self.hakimi = Player.objects.create(
            name="Achraf Hakimi",
            fc27_id="235212",
            position="RB",
            overall=89,
            is_free_agent=True,
        )

    def test_player_database_search_is_accent_insensitive(self):
        self.client.login(username="namesearch", password="test-pass-123")
        cases = [
            ("Salah", "MOHAMED SALAH", "Ghaly"),
            ("Mbappe", "KYLIAN MBAPPÉ", "Lottin"),
            ("Mbappé", "KYLIAN MBAPPÉ", "Lottin"),
            ("Hakimi", "ACHRAF HAKIMI", "Mouh"),
        ]
        for query, expected, old_name in cases:
            response = self.client.get(reverse("player_database"), {"search": query})
            self.assertEqual(response.status_code, 200, query)
            self.assertContains(response, expected)
            self.assertNotContains(response, old_name)
            self.assertContains(response, "mgl-player-card")

    def test_profile_uses_recognised_display_name(self):
        self.client.login(username="namesearch", password="test-pass-123")
        salah = self.client.get(reverse("player_profile", args=[self.salah.id]))
        self.assertContains(salah, "Mohamed Salah")
        self.assertNotContains(salah, "Ghaly")
        mbappe = self.client.get(reverse("player_profile", args=[self.mbappe.id]))
        self.assertContains(mbappe, "Kylian Mbappé")
        self.assertNotContains(mbappe, "Lottin")
        hakimi = self.client.get(reverse("player_profile", args=[self.hakimi.id]))
        self.assertContains(hakimi, "Achraf Hakimi")
        self.assertNotContains(hakimi, "Mouh")
