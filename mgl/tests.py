from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse, NoReverseMatch

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.models import NewsPost, RewardTransaction
from teams.models import Team


class PhaseAClientTestCase(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")


class HomeAndUrlTests(PhaseAClientTestCase):
    def test_home_url_is_unique_and_root(self):
        self.assertEqual(reverse("home"), "/")
        with self.assertRaises(NoReverseMatch):
            reverse("home", kwargs={"unused": 1})

    def test_homepage_loads_without_hardcoded_fixtures(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "NAPOLI")
        self.assertContains(response, "No upcoming fixtures have been released.")
        self.assertContains(response, "NO PUBLISHED NEWS YET")

    def test_homepage_uses_published_news(self):
        NewsPost.objects.create(
            category=NewsPost.RESULTS,
            title="Official MGL Result",
            body="Approved.",
            published=True,
        )
        response = self.client.get("/")
        self.assertContains(response, "Official MGL Result")

    def test_mgl_index_redirects_anonymous_users_home(self):
        response = self.client.get("/mgl/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")

    def test_mgl_index_redirects_authenticated_users_to_hub(self):
        user = User.objects.create_user(
            username="manager1",
            password="test-pass-123",
        )
        ManagerApplication.objects.create(
            user=user,
            display_name="Manager One",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
        )
        self.client.login(username="manager1", password="test-pass-123")
        response = self.client.get("/mgl/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manager_hub"))


class AuthAndTeamTests(PhaseAClientTestCase):
    def test_team_management_redirects_when_logged_out(self):
        response = self.client.get("/mgl/team/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_logout_get_is_not_allowed(self):
        response = self.client.get("/logout/")
        self.assertEqual(response.status_code, 405)

    def test_logout_post_works(self):
        User.objects.create_user(
            username="manager1",
            password="test-pass-123",
        )
        self.client.login(username="manager1", password="test-pass-123")
        response = self.client.post("/logout/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")
        follow = self.client.get("/mgl/hub/")
        self.assertEqual(follow.status_code, 302)
        self.assertIn("/login/", follow["Location"])


class RewardsAndSquadTests(PhaseAClientTestCase):
    def test_rewards_page_shows_token_history(self):
        user = User.objects.create_user(
            username="manager1",
            password="test-pass-123",
        )
        manager = ManagerApplication.objects.create(
            user=user,
            display_name="Manager One",
            gamertag="M1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("51.00"),
        )
        RewardTransaction.objects.create(
            manager=manager,
            amount=Decimal("1.00"),
            reason="Approved league match",
            category="MATCH",
        )
        self.client.login(username="manager1", password="test-pass-123")
        response = self.client.get(reverse("manager_rewards"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, ">k<")
        self.assertContains(response, "Approved league match")
        self.assertContains(response, "51.00")

    def test_admin_squad_page_renders(self):
        admin = User.objects.create_user(
            username="owner1",
            password="test-pass-123",
            role=User.OWNER,
        )
        league = League.objects.create(
            name="Super League 1",
            short_name="SL1",
            season="1",
        )
        team = Team.objects.create(
            name="Test FC",
            short_name="TFC",
            league=league,
        )
        self.client.login(username="owner1", password="test-pass-123")
        response = self.client.get(
            reverse("club_squad_admin", args=[team.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "TEST FC SQUAD")
        self.assertContains(response, "This club currently has no players.")


class ConnectedRouteSmokeTests(PhaseAClientTestCase):
    def test_public_and_login_routes_do_not_500(self):
        for url in [
            "/",
            "/login/",
            "/register/",
            "/admin/login/",
            "/leagues/",
            "/leagues/premier-league/",
            "/stats/",
            "/stats/history/",
            "/stats/compare/",
            "/stats/premier-league/",
            "/stats/championship/",
            "/stats/league-one/",
            "/stats/managers/",
            "/market/",
            "/market/transfers/",
            "/market/scouting/",
            "/jobs/",
        ]:
            response = self.client.get(url)
            self.assertLess(response.status_code, 500, url)
            self.assertNotEqual(response.status_code, 500, url)

    def test_removed_academy_and_head_to_head_routes_are_gone(self):
        self.assertEqual(self.client.get("/market/youth-academy/").status_code, 404)
        self.assertEqual(self.client.get("/stats/head-to-head/").status_code, 404)

    def test_protected_routes_redirect_instead_of_500(self):
        for name, args in [
            ("manager_hub", []),
            ("team_management", []),
            ("player_database", []),
            ("free_agents", []),
            ("manager_profile", []),
            ("manager_notifications", []),
            ("manager_rewards", []),
            ("live_auctions", []),
            ("club_management_admin", []),
        ]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 302, name)
            self.assertIn("/login/", response["Location"], name)
