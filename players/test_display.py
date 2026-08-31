from datetime import date

from django.test import SimpleTestCase, TestCase

from players.display import parse_playstyles, player_age, star_rating
from players.models import Player


class PlayerAgeTests(SimpleTestCase):
    def test_uses_stored_age_when_no_dob(self):
        self.assertEqual(player_age(type("P", (), {"age": 24, "date_of_birth": None})()), 24)

    def test_calculates_age_from_dob(self):
        player = type("P", (), {"age": 99, "date_of_birth": date(2000, 1, 1)})()
        self.assertEqual(player_age(player, today=date(2026, 8, 31)), 26)

    def test_dob_before_birthday_this_year(self):
        player = type("P", (), {"age": None, "date_of_birth": date(2000, 12, 1)})()
        self.assertEqual(player_age(player, today=date(2026, 8, 31)), 25)

    def test_missing_age_is_none(self):
        self.assertIsNone(player_age(type("P", (), {"age": None, "date_of_birth": None})()))


class StarAndPlaystyleTests(SimpleTestCase):
    def test_star_rating(self):
        self.assertEqual(star_rating(4), "★★★★☆")
        self.assertEqual(star_rating(5), "★★★★★")
        self.assertEqual(star_rating(None), "")

    def test_parse_playstyles_splits_plus(self):
        styles, plus = parse_playstyles("Technical, Rapid, Finesse Shot+")
        self.assertEqual(styles, ["Technical", "Rapid"])
        self.assertEqual(plus, ["Finesse Shot+"])


class PlayerDisplayModelTests(TestCase):
    def test_player_age_reads_model_fields(self):
        stored = Player.objects.create(name="Aged", position="ST", overall=70, age=22)
        self.assertEqual(player_age(stored), 22)
        born = Player.objects.create(
            name="Born",
            position="CM",
            overall=71,
            date_of_birth=date(1998, 6, 1),
        )
        self.assertEqual(player_age(born, today=date(2026, 8, 31)), 28)
