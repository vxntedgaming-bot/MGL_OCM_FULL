from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from managers.models import ManagerApplication
from mgl.season1 import UFL_STARTER_CLUB_TOTAL
from mgl.season_history import current_season_number
from teams.models import Team


class PublicHomePageTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_anonymous_home_renders_design_and_nav(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn('class="mgl-nav-link is-active">HOME', html)
        for label in ("LEAGUES", "CLUBS", "FIXTURES", "TABLES", "STATISTICS", "JOBS"):
            self.assertIn(label, html)
        self.assertContains(page, "JOIN UFL / LOGIN")
        self.assertContains(page, reverse("manager_login"))
        self.assertContains(page, "LIVE ACTIVITY")
        self.assertContains(page, "EA FC")
        self.assertContains(page, "CAREER MODE")
        self.assertContains(page, "VIEW JOB OPENINGS")
        self.assertContains(page, "VIEW LEAGUE TABLE")
        self.assertContains(page, reverse("leagues_page"))
        self.assertContains(page, reverse("job_centre"))
        self.assertContains(page, reverse("manager_register"))
        self.assertContains(page, "HOW UFL WORKS")
        self.assertContains(page, "BECOME A MANAGER")
        self.assertContains(page, "BUILD YOUR LEGACY")
        self.assertContains(page, "READY TO TAKE")
        self.assertContains(page, "CREATE ACCOUNT")
        self.assertContains(page, "THE UFL EXPERIENCE")
        self.assertContains(page, "RECRUITMENT DRIVE")
        self.assertContains(page, "TOKENS SYSTEM")
        self.assertContains(page, "YOUR CLUB.")
        self.assertNotContains(page, reverse("recruitment_drive"))
        self.assertNotContains(page, reverse("manager_rewards"))
        self.assertNotContains(page, reverse("team_management"))
        self.assertNotContains(page, "48+")
        self.assertNotContains(page, "128+")

    def test_statistics_use_real_and_configured_values(self):
        page = self.client.get("/")
        self.assertEqual(page.context["manager_count"], Team.objects.filter(manager__isnull=False).count())
        self.assertEqual(page.context["matches_played"], 0)
        self.assertEqual(page.context["configured_club_total"], UFL_STARTER_CLUB_TOTAL)
        self.assertEqual(page.context["configured_club_total"], 38)
        self.assertEqual(page.context["current_season_number"], current_season_number())
        self.assertContains(page, "ACTIVE MANAGERS")
        self.assertContains(page, "MATCHES PLAYED")
        self.assertContains(page, "ACTIVE CLUBS")
        self.assertContains(page, f"SEASON {current_season_number()}")
        self.assertContains(page, "Premier League")
        self.assertContains(page, "Championship")
        self.assertContains(page, "League One")

    def test_jobs_and_tables_and_register_buttons(self):
        page = self.client.get("/")
        html = page.content.decode()
        self.assertIn(f'href="{reverse("job_centre")}"', html)
        self.assertNotIn(f'href="{reverse("manager_login")}?next={reverse("job_centre")}"', html)
        self.assertIn(f'href="{reverse("leagues_page")}"', html)
        self.assertIn(f'href="{reverse("manager_register")}"', html)

    @override_settings(DISCORD_INVITE_URL="https://discord.gg/ufl-home-test")
    def test_discord_uses_resolved_invite(self):
        page = self.client.get("/")
        self.assertContains(page, "https://discord.gg/ufl-home-test")
        self.assertContains(page, "JOIN DISCORD")

    @override_settings(DISCORD_INVITE_URL="")
    def test_empty_discord_uses_official_invite(self):
        page = self.client.get("/")
        self.assertContains(page, "JOIN DISCORD")
        self.assertContains(page, "https://discord.gg/rhKg6gmE8K")

    def test_anonymous_user_does_not_see_manager_chrome(self):
        page = self.client.get("/")
        nav = page.content.decode().split('<nav class="mgl-nav"', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn("MY TEAM", nav)
        self.assertNotIn("MARKET", nav)
        self.assertNotIn("CONTROL CENTRE", nav)
        self.assertNotIn("data-notify-dropdown", page.content.decode())

    def test_approved_manager_is_sent_to_hub(self):
        user = User.objects.create_user(username="home-mgr", password="test-pass-123")
        ManagerApplication.objects.create(
            user=user,
            display_name="Home Manager",
            gamertag="HOM1",
            status=ManagerApplication.APPROVED,
        )
        self.client.login(username="home-mgr", password="test-pass-123")
        page = self.client.get("/")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page["Location"], reverse("manager_hub"))
