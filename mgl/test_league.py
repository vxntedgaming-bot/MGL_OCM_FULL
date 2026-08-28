from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from leagues.services import ensure_super_league_1
from managers.models import ManagerApplication
from mgl.models import ApprovalStatus, Fixture, MatchSubmission, TeamMatchStats
from mgl.standings import build_league_table
from teams.models import Team


class SuperLeagueOneTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_migrate_seeds_premier_league_and_lower_divisions(self):
        sl1 = League.objects.get(short_name="PL")
        self.assertEqual(sl1.name, "Premier League")
        self.assertTrue(sl1.is_active)
        self.assertEqual(
            set(League.objects.filter(is_active=True).values_list("short_name", flat=True)),
            {"PL", "CH", "L1"},
        )

        home = self.client.get("/")
        self.assertContains(home, "PREMIER LEAGUE")
        self.assertNotContains(home, "Super League 2")
        self.assertNotContains(home, "MLS")
        leagues = self.client.get("/leagues/")
        self.assertContains(leagues, "PREMIER LEAGUE")
        self.assertContains(leagues, "CHAMPIONSHIP")
        self.assertContains(leagues, "LEAGUE ONE")
        self.assertNotContains(leagues, "Super League 2")
        self.assertNotContains(leagues, "href=\"/leagues/mls/\"")
        stats = self.client.get("/stats/")
        self.assertContains(stats, "TOP GOAL SCORERS")
        self.assertContains(stats, "TOP ASSISTERS")
        self.assertContains(stats, "TOP DEFENDERS")
        self.assertContains(stats, "TOP GOALKEEPERS")
        self.assertContains(stats, "TOP MANAGERS")
        self.assertNotContains(stats, "Super League 2")
        self.assertNotContains(stats, "PTS")

    def test_ensure_moves_clubs_and_hides_sl2(self):
        sl1 = ensure_super_league_1()
        sl2 = League.objects.create(
            name="Super League 2",
            short_name="SL2",
            season="1",
            is_active=True,
        )
        club_a = Team.objects.create(name="Alpha FC", short_name="AFC", league=sl1, tokens=Decimal("50.00"))
        club_b = Team.objects.create(name="Beta FC", short_name="BFC", league=sl2, tokens=Decimal("41.00"))
        Fixture.objects.create(
            league=sl2,
            home_team=club_a,
            away_team=club_b,
            is_released=True,
        )

        league = ensure_super_league_1()
        sl1.refresh_from_db()
        sl2.refresh_from_db()
        club_a.refresh_from_db()
        club_b.refresh_from_db()

        self.assertEqual(league.id, sl1.id)
        self.assertTrue(sl1.is_active)
        self.assertFalse(sl2.is_active)
        self.assertEqual(League.objects.filter(short_name="SL2").count(), 1)
        self.assertEqual(club_a.league_id, sl1.id)
        self.assertEqual(club_b.league_id, sl2.id)
        self.assertEqual(club_b.tokens, Decimal("41.00"))
        self.assertEqual(Fixture.objects.get(home_team=club_a).league_id, sl2.id)
        self.assertGreaterEqual(Team.objects.filter(league=sl1).count(), 15)

        page = self.client.get("/leagues/")
        self.assertContains(page, "PREMIER LEAGUE")
        self.assertContains(page, "Alpha FC")
        self.assertNotContains(page, "Beta FC")
        self.assertNotContains(page, "Super League 2")
        home = self.client.get("/")
        self.assertContains(home, "PREMIER LEAGUE")
        self.assertNotContains(home, "Super League 2")
        jobs = self.client.get("/jobs/")
        self.assertContains(jobs, "Alpha FC")
        self.assertNotContains(jobs, "Super League 2")

    def test_table_includes_all_clubs_and_approved_results(self):
        league = ensure_super_league_1()
        home_club = Team.objects.create(name="Home FC", short_name="HFC", league=league)
        away_club = Team.objects.create(name="Away FC", short_name="AFC", league=league)
        idle = Team.objects.create(name="Idle FC", short_name="IFC", league=league)
        fixture = Fixture.objects.create(
            league=league,
            home_team=home_club,
            away_team=away_club,
            is_released=True,
            status="COMPLETED",
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            status=ApprovalStatus.APPROVED,
        )
        TeamMatchStats.objects.create(submission=submission, team=home_club, goals=2)
        TeamMatchStats.objects.create(submission=submission, team=away_club, goals=1)

        table = build_league_table(league)
        by_id = {row["team"].id: row for row in table}
        self.assertGreaterEqual(len(table), 17)
        self.assertEqual(table[0]["team"].id, home_club.id)
        self.assertEqual(table[0]["played"], 1)
        self.assertEqual(table[0]["wins"], 1)
        self.assertEqual(table[0]["gf"], 2)
        self.assertEqual(table[0]["ga"], 1)
        self.assertEqual(table[0]["gd"], 1)
        self.assertEqual(table[0]["points"], 3)
        self.assertEqual(by_id[idle.id]["played"], 0)
        self.assertEqual(by_id[idle.id]["points"], 0)
        self.assertEqual(by_id[away_club.id]["played"], 1)
        self.assertEqual(by_id[away_club.id]["points"], 0)
        self.assertEqual(by_id[away_club.id]["gd"], -1)

        page = self.client.get("/leagues/")
        self.assertContains(page, "Home FC")
        self.assertContains(page, "Idle FC")
        self.assertContains(page, "PTS")

    def test_self_fixture_is_invalid_and_ignored_in_table(self):
        league = ensure_super_league_1()
        club = Team.objects.create(name="Solo FC", short_name="SFC", league=league)
        fixture = Fixture(
            league=league,
            home_team=club,
            away_team=club,
            is_released=True,
            status="COMPLETED",
        )
        with self.assertRaises(ValidationError):
            fixture.full_clean()
        fixture.save()
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            status=ApprovalStatus.APPROVED,
        )
        TeamMatchStats.objects.create(submission=submission, team=club, goals=1)
        table = build_league_table(league)
        solo = next(row for row in table if row["team"].id == club.id)
        self.assertEqual(solo["played"], 0)
        self.assertEqual(solo["points"], 0)

    def test_manager_hub_shows_premier_league(self):
        league = ensure_super_league_1()
        user = User.objects.create_user(username="mgr", password="test-pass-123")
        ManagerApplication.objects.create(
            user=user,
            display_name="Mgr",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
        )
        Team.objects.create(
            name="Hub FC",
            short_name="HFC",
            league=league,
            manager=user,
            tokens=Decimal("50.00"),
        )
        self.client.login(username="mgr", password="test-pass-123")
        response = self.client.get(reverse("manager_hub"))
        self.assertContains(response, "PREMIER LEAGUE")
        self.assertContains(response, "HFC")
        self.assertContains(response, "PERSONAL BALANCE")
        self.assertContains(response, "20.00 TKN")
        self.assertNotContains(response, "50.00 TKN")
        self.assertEqual(self.client.get(reverse("control_centre")).status_code, 302)
        self.assertEqual(
            self.client.get(reverse("control_centre"))["Location"],
            reverse("manager_hub"),
        )
