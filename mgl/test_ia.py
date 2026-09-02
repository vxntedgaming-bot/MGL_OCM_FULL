from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from players.models import Player
from teams.models import Team
from teams.official_ufl_clubs import ensure_official_ufl_clubs


class InformationArchitectureTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        ensure_premier_league()
        self.jobs = reverse("job_centre")

    def test_public_restricted_pages_redirect_to_job_offers(self):
        for name in (
            "live_auctions",
            "scouting",
            "player_database",
            "free_agents",
            "transfer_history",
            "transfer_requests",
            "recruitment_drive",
            "youth_academy",
            "fixture_list",
            "manager_hub",
            "team_management",
            "manager_notifications",
            "manager_profile",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302, name)
            self.assertEqual(response["Location"], self.jobs, name)

    def test_public_pages_remain_open(self):
        for name, kwargs in (
            ("home", None),
            ("leagues_page", None),
            ("job_centre", None),
            ("job_offers", None),
            ("clubs_index", None),
            ("public_transfers", None),
            ("transfer_market", None),
            ("live_activity", None),
            ("pressroom", None),
            ("league_stats", {"slug": "premier-league"}),
            ("hall_of_fame", None),
            ("manager_search", None),
            ("competition_page", {"slug": "phantom-cup"}),
            ("competition_page", {"slug": "champions-league"}),
            ("competition_page", {"slug": "europa-league"}),
            ("competition_page", {"slug": "conference-league"}),
        ):
            response = self.client.get(reverse(name, kwargs=kwargs))
            self.assertEqual(response.status_code, 200, name)

    def test_job_offers_alias(self):
        self.assertEqual(reverse("job_offers"), "/job-offers/")
        self.assertEqual(self.client.get("/job-offers/").status_code, 200)
        self.assertEqual(self.client.get("/job-centre/").status_code, 302)

    def test_matches_redirects_to_fixtures(self):
        response = self.client.get("/matches/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("fixture_list"))

    def test_global_shell_on_home(self):
        page = self.client.get("/")
        self.assertContains(page, "LIVE ACTIVITY")
        self.assertContains(page, "ufl-page-head", count=0)
        self.assertContains(page, "Ultimate Fantasy League")
        self.assertNotContains(page, "About MGL")
        self.assertNotContains(page, "FC Fantasy")

    def test_approved_manager_home_goes_to_hub(self):
        user = User.objects.create_user(username="mgr", password="test-pass-123")
        ManagerApplication.objects.create(
            user=user,
            display_name="Mgr",
            gamertag="MGR1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("20.00"),
        )
        self.client.login(username="mgr", password="test-pass-123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("manager_hub"))

    def test_page_header_on_league(self):
        page = self.client.get(reverse("leagues_page"))
        self.assertContains(page, "ufl-page-head")
        self.assertContains(page, "ALL LEAGUES")
        self.assertContains(page, "LIVE ACTIVITY")


class RecruitmentDriveTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        league = ensure_premier_league()
        self.user = User.objects.create_user(username="rec", password="test-pass-123")
        self.manager = ManagerApplication.objects.create(
            user=self.user,
            display_name="Rec",
            gamertag="REC1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("5.00"),
        )
        self.team = Team.objects.create(
            name="Recruit FC", short_name="RFC", league=league, manager=self.user
        )
        for index in range(6):
            Player.objects.create(
                name=f"Unsigned GK {index}",
                position="GK",
                overall=70 + index,
                fc27_id=f"gk{index}",
                is_free_agent=False,
            )

    def test_open_and_choose_one_player(self):
        from mgl.models import RecruitmentOpening
        from mgl.recruitment import choose_recruitment_player, open_recruitment_pack

        opening = open_recruitment_pack(self.user, "GK")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("4.00"))
        self.assertEqual(len(opening.player_ids), 3)
        chosen_id = opening.player_ids[0]
        other_ids = opening.player_ids[1:]
        choose_recruitment_player(self.user, opening.id, chosen_id)
        chosen = Player.objects.get(pk=chosen_id)
        self.assertEqual(chosen.mgl_team_id, self.team.id)
        for pk in other_ids:
            other = Player.objects.get(pk=pk)
            self.assertIsNone(other.mgl_team_id)
            self.assertFalse(other.is_free_agent)
        opening.refresh_from_db()
        self.assertEqual(opening.status, RecruitmentOpening.COMPLETED)

    def test_crafted_player_id_is_rejected(self):
        from mgl.recruitment import choose_recruitment_player, open_recruitment_pack

        opening = open_recruitment_pack(self.user, "GK")
        outsider = Player.objects.create(
            name="Not In Pack",
            position="GK",
            overall=68,
            fc27_id="out1",
            is_free_agent=False,
        )
        with self.assertRaises(ValueError):
            choose_recruitment_player(self.user, opening.id, outsider.id)

    def test_duplicate_open_does_not_double_debit(self):
        from mgl.recruitment import open_recruitment_pack

        open_recruitment_pack(self.user, "GK")
        with self.assertRaises(ValueError):
            open_recruitment_pack(self.user, "GK")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("4.00"))


class OfficialClubStructureTests(TestCase):
    def test_ensure_clubs_fills_missing_without_deleting(self):
        ensure_premier_league()
        result = ensure_official_ufl_clubs()
        self.assertEqual(result["counts"]["PL"], 14)
        self.assertEqual(result["counts"]["CH"], 14)
        self.assertEqual(result["counts"]["L1"], 14)
        again = ensure_official_ufl_clubs()
        self.assertEqual(len(again["created"]), 0)
