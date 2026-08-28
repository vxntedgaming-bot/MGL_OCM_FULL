from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from leagues.models import League
from mgl.models import Fixture
from players.models import Player
from teams.models import Team
from teams.official_sl1 import (
    OFFICIAL_SL1_CLUBS,
    OFFICIAL_SL1_SHORT_NAMES,
    ensure_official_sl1_clubs,
)


class OfficialSuperLeagueOneClubTests(TestCase):
    def test_migration_creates_exactly_the_14_official_clubs(self):
        league = League.objects.get(short_name="PL")
        clubs = list(Team.objects.filter(league=league).order_by("name"))
        self.assertEqual(len(clubs), 14)
        self.assertEqual(
            {(club.name, club.short_name) for club in clubs},
            set(OFFICIAL_SL1_CLUBS),
        )
        for club in clubs:
            self.assertEqual(club.tokens, Decimal("50.00"))
            self.assertIsNone(club.manager_id)
        self.assertEqual(League.objects.filter(short_name="SL2").count(), 0)
        self.assertEqual(Fixture.objects.count(), 0)
        self.assertEqual(Player.objects.count(), 0)

    def test_ensure_is_idempotent_and_preserves_tokens(self):
        arsenal = Team.objects.get(short_name="ARS")
        arsenal.tokens = Decimal("41.00")
        arsenal.save(update_fields=["tokens"])

        ensure_official_sl1_clubs()
        ensure_official_sl1_clubs()

        self.assertEqual(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).count(), 14)
        self.assertEqual(Team.objects.count(), 14)
        arsenal.refresh_from_db()
        self.assertEqual(arsenal.tokens, Decimal("41.00"))
        self.assertEqual(arsenal.league.short_name, "PL")
        self.assertIsNone(arsenal.manager_id)

    def test_populate_command_does_not_duplicate_or_invent_extra_records(self):
        call_command(
            "populate_super_league_1",
            skip_import=True,
            skip_squads=True,
            stdout=StringIO(),
        )
        call_command(
            "populate_super_league_1",
            skip_import=True,
            skip_squads=True,
            stdout=StringIO(),
        )
        self.assertEqual(Team.objects.count(), 14)
        self.assertEqual(League.objects.filter(is_active=True).count(), 3)
        self.assertEqual(League.objects.filter(short_name="SL2").count(), 0)
        self.assertEqual(Fixture.objects.count(), 0)
        self.assertEqual(Player.objects.count(), 0)

    def test_official_squad_generation_skips_non_official_and_filled_clubs(self):
        official = list(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES))
        arsenal = Team.objects.get(short_name="ARS")
        for team in official:
            if team.id == arsenal.id:
                continue
            Player.objects.create(
                name=f"Kept {team.short_name}",
                position="ST",
                overall=70,
                mgl_team=team,
                is_free_agent=False,
            )
        outsider = Team.objects.create(
            name="Outsider FC",
            short_name="OUT",
            league=arsenal.league,
        )
        positions = [
            "GK", "GK",
            "CB", "CB", "CB", "CB",
            "LB", "LB",
            "RB", "RB",
            "CDM", "CDM", "CM", "CM",
            "CAM", "CAM",
            "LM", "LM", "LW",
            "RM", "RM", "RW",
            "ST", "ST", "ST", "CF",
        ]
        for index, position in enumerate(positions):
            Player.objects.create(
                name=f"FA {index}",
                position=position,
                overall=64 + (index % 10),
                is_free_agent=True,
            )

        call_command("generate_balanced_squads", official_sl1=True, stdout=StringIO())

        self.assertEqual(arsenal.players.count(), 26)
        self.assertTrue(all(64 <= player.overall <= 73 for player in arsenal.players.all()))
        self.assertEqual(outsider.players.count(), 0)
        self.assertEqual(
            Player.objects.filter(mgl_team=arsenal).count()
            + Player.objects.filter(mgl_team__isnull=False).exclude(mgl_team=arsenal).count()
            + Player.objects.filter(is_free_agent=True, mgl_team__isnull=True).count(),
            Player.objects.count(),
        )
        for team in official:
            if team.id == arsenal.id:
                continue
            team.refresh_from_db()
            self.assertEqual(team.players.count(), 1)
