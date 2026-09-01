from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import ApprovalStatus, Fixture, MatchSubmission, TeamMatchStats
from teams.models import Team


def _manager(user, display, tag):
    return ManagerApplication.objects.create(
        user=user,
        display_name=display,
        gamertag=tag,
        status=ManagerApplication.APPROVED,
        tokens=Decimal("20.00"),
    )


class UFLSiteStructureTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = User.objects.create_user(username="structmgr", password="test-pass-123")
        self.other = User.objects.create_user(username="structother", password="test-pass-123")
        _manager(self.user, "Struct Manager", "STM")
        _manager(self.other, "Other Manager", "OTM")
        self.home = Team.objects.create(
            name="Struct Home",
            short_name="STH",
            league=self.league,
            manager=self.user,
        )
        self.away = Team.objects.create(
            name="Struct Away",
            short_name="STA",
            league=self.league,
            manager=self.other,
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.home,
            away_team=self.away,
            matchweek=4,
            is_released=True,
            status="SCHEDULED",
        )
        self.completed = Fixture.objects.create(
            league=self.league,
            home_team=self.home,
            away_team=self.away,
            matchweek=1,
            is_released=True,
            status="COMPLETED",
        )
        submission = MatchSubmission.objects.create(
            fixture=self.completed,
            status=ApprovalStatus.APPROVED,
        )
        TeamMatchStats.objects.create(submission=submission, team=self.home, goals=2)
        TeamMatchStats.objects.create(submission=submission, team=self.away, goals=1)

    def test_public_home_stays_isolated(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        nav = page.content.decode().split('<nav class="mgl-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("MY TEAM", nav)
        self.assertNotIn("MARKET", nav)
        self.assertNotIn("Youth Academy", nav)
        self.assertNotIn('data-nav-dropdown="stats"', nav)
        self.assertNotIn('data-nav-dropdown="history"', nav)
        self.assertIn("JOBS", nav)

    def test_youth_academy_is_coming_soon_for_managers(self):
        self.assertEqual(self.client.get(reverse("youth_academy")).status_code, 302)
        self.client.login(username="structmgr", password="test-pass-123")
        page = self.client.get(reverse("youth_academy"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "COMING SOON")
        self.assertContains(page, "YOUTH ACADEMY")
        self.assertContains(page, 'data-nav-dropdown="market"')

    def test_new_cup_pages_load_without_fake_results(self):
        for slug, needle in (
            ("phantom-cup", "Knockout stages"),
            ("champions-league", "16 teams. 4 groups of 4"),
            ("europa-league", "8 teams. 2 groups of 4"),
            ("conference-league", "8 teams. 2 groups of 4"),
        ):
            page = self.client.get(reverse("competition_page", kwargs={"slug": slug}))
            self.assertEqual(page.status_code, 200, slug)
            self.assertContains(page, needle)
            self.assertContains(page, "NO LIVE COMPETITION DATA")
            self.assertContains(page, 'data-nav-dropdown="cups"')

    def test_fixture_detail_uses_stored_result(self):
        page = self.client.get(reverse("fixture_detail", args=[self.completed.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "2–1")
        self.assertContains(page, "Struct Home")
        self.assertContains(page, "Struct Away")
        self.assertContains(page, "OFFICIAL")
        scheduled = self.client.get(reverse("fixture_detail", args=[self.fixture.id]))
        self.assertEqual(scheduled.status_code, 200)
        self.assertNotContains(scheduled, "ENTER RESULT")
        self.client.login(username="structmgr", password="test-pass-123")
        own = self.client.get(reverse("fixture_detail", args=[self.fixture.id]))
        self.assertContains(own, "ENTER RESULT")
        self.assertContains(own, reverse("submit_match", args=[self.fixture.id]))
        self.assertContains(own, reverse("fixture_stats", args=[self.fixture.id]))

    def test_public_manager_profile_and_search(self):
        search = self.client.get(reverse("manager_search"))
        self.assertEqual(search.status_code, 200)
        self.assertContains(search, reverse("manager_public_profile", args=["structmgr"]))
        page = self.client.get(reverse("manager_public_profile", args=["structmgr"]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Struct Manager")
        self.assertNotContains(page, "RESIGN FROM CLUB")
        self.assertNotContains(page, "LINK DISCORD")
        self.client.login(username="structmgr", password="test-pass-123")
        own = self.client.get(reverse("manager_public_profile", args=["structmgr"]))
        self.assertEqual(own.status_code, 302)
        self.assertEqual(own["Location"], reverse("manager_profile"))

    def test_hall_of_fame_and_signed_in_header_tree(self):
        fame = self.client.get(reverse("hall_of_fame"))
        self.assertEqual(fame.status_code, 200)
        self.assertContains(fame, "HALL OF FAME")
        self.assertContains(fame, "Puskás Award")
        self.assertContains(fame, "To be recorded")
        self.client.login(username="structmgr", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        html = hub.content.decode().split('<nav class="mgl-nav"', 1)[1].split("</nav>", 1)[0]
        for label in (
            "MY TEAM",
            "Team Management",
            "MARKET",
            "Transfers",
            "Transfer Market",
            "Free Agents",
            "Recruitment Drive",
            "Scouting",
            "Youth Academy",
            "Auctions",
            "Player Database",
            "LEAGUES",
            "ALL LEAGUES",
            "Premier League",
            "Championship",
            "League One",
            "CUPS",
            "Phantom Cup",
            "UFL Champions League",
            "JOB CENTRE",
            "STATS",
            "Premier League Stats",
            "HISTORY",
            "Hall of Fame",
            "Manager Search",
        ):
            self.assertIn(label, html)
        self.assertIn(reverse("team_management"), html)
        self.assertIn(reverse("fixture_list"), html)
        self.assertIn(reverse("public_transfers"), html)
        self.assertIn(reverse("transfer_market"), html)
        self.assertIn(reverse("free_agents"), html)
        self.assertIn(reverse("recruitment_drive"), html)
        self.assertIn(reverse("scouting"), html)
        self.assertIn(reverse("youth_academy"), html)
        self.assertIn(reverse("live_auctions"), html)
        self.assertIn(reverse("player_database"), html)
        self.assertIn(reverse("leagues_page"), html)
        self.assertIn(reverse("competition_page", kwargs={"slug": "premier-league"}), html)
        self.assertIn(reverse("competition_page", kwargs={"slug": "phantom-cup"}), html)
        self.assertIn(reverse("job_centre"), html)
        self.assertIn(reverse("league_stats", kwargs={"slug": "premier-league"}), html)
        self.assertIn(reverse("hall_of_fame"), html)
        self.assertIn(reverse("manager_search"), html)
        self.assertIn(reverse("fixture_detail", args=[self.completed.id]), hub.content.decode())
