from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from managers.models import ManagerApplication
from mgl.models import Fixture, MarketTransaction, SiteChangeLog, SiteContent
from mgl.site_cms import get_content
from players.models import Player
from teams.badges import static_badge_path
from teams.models import Team


def _png(name="logo.png"):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (16, 16), color=(255, 92, 0)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class SiteManagementTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = (
            League.objects.filter(short_name="PL").order_by("id").first()
            or League.objects.create(
                name="Premier League",
                short_name="PL",
                season="1",
                is_active=True,
            )
        )
        self.owner = User.objects.create_user(
            username="owner",
            password="test-pass-123",
            role=User.OWNER,
        )
        self.admin = User.objects.create_user(
            username="admin",
            password="test-pass-123",
            role=User.ADMIN,
        )
        self.manager_user = User.objects.create_user(
            username="manager",
            password="test-pass-123",
            role=User.MANAGER,
        )
        self.mgr = ManagerApplication.objects.create(
            user=self.manager_user,
            display_name="Manager One",
            gamertag="MGR1",
            status=ManagerApplication.APPROVED,
            tokens=Decimal("50.00"),
        )
        self.team = Team.objects.create(
            name="QA Test Club",
            short_name="QTC",
            league=self.league,
            manager=self.manager_user,
            tokens=Decimal("50.00"),
        )
        self.club_player = Player.objects.create(
            name="Club Player",
            position="ST",
            overall=70,
            mgl_team=self.team,
            is_free_agent=False,
            appearances=3,
            goals=2,
        )
        self.unassigned = Player.objects.create(
            name="Unassigned Pool",
            position="CM",
            overall=66,
            mgl_team=None,
            is_free_agent=False,
        )
        self.free_agent = Player.objects.create(
            name="Free Agent",
            position="CB",
            overall=64,
            mgl_team=None,
            is_free_agent=True,
        )
        self.other = Team.objects.create(
            name="QA Other FC",
            short_name="QOF",
            league=self.league,
            tokens=Decimal("50.00"),
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team,
            away_team=self.other,
            is_released=True,
        )
        self.transfer = MarketTransaction.objects.create(
            player=self.club_player,
            from_team=self.team,
            to_team=self.other,
            amount=Decimal("5.00"),
            transaction_type=MarketTransaction.SALE,
            status=MarketTransaction.COMPLETED,
        )

    def _login(self, user):
        self.client.login(username=user.username, password="test-pass-123")

    def test_owner_can_open_site_management(self):
        self._login(self.owner)
        response = self.client.get(reverse("site_management"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SITE MANAGEMENT")
        self.assertContains(response, "TEAMS")
        self.assertContains(response, "WEBSITE CONTENT")
        self.assertContains(response, "SITE SETTINGS")
        self.assertContains(response, "LEAGUES")

    def test_admin_can_open_site_management(self):
        self._login(self.admin)
        self.assertEqual(self.client.get(reverse("site_management")).status_code, 200)
        self.assertEqual(self.client.get(reverse("site_management_teams")).status_code, 200)
        self.assertEqual(self.client.get(reverse("site_management_content")).status_code, 200)
        self.assertEqual(self.client.get(reverse("site_management_settings")).status_code, 200)
        self.assertEqual(self.client.get(reverse("site_management_leagues")).status_code, 200)

    def test_manager_receives_403(self):
        self._login(self.manager_user)
        for name, kwargs in (
            ("site_management", {}),
            ("site_management_teams", {}),
            ("site_management_team_edit", {"team_id": self.team.id}),
            ("site_management_content", {}),
            ("site_management_content_section", {"section": "home"}),
            ("site_management_settings", {}),
            ("site_management_leagues", {}),
            ("site_management_league_edit", {"league_id": self.league.id}),
        ):
            response = self.client.get(reverse(name, kwargs=kwargs))
            self.assertEqual(response.status_code, 403, name)
            self.assertContains(response, "PERMISSION DENIED", status_code=403)

    def test_public_user_cannot_access(self):
        response = self.client.get(reverse("site_management"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("manager_login"), response["Location"])

    def test_control_centre_shows_site_management_card(self):
        self._login(self.owner)
        response = self.client.get(reverse("control_centre"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("site_management"))
        self.assertContains(response, "SITE MANAGEMENT")

    def test_team_display_identity_changes_without_touching_relationships(self):
        self._login(self.owner)
        original_pk = self.team.pk
        original_tokens = self.team.tokens
        original_manager_id = self.team.manager_id
        original_league_id = self.team.league_id
        original_player_id = self.club_player.pk
        original_fixture_id = self.fixture.pk
        original_transfer_id = self.transfer.pk
        original_count = Team.objects.count()

        response = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": "QA Arsenal",
                "short_name": "QAR",
                "description": "North London club.",
            },
        )
        self.assertEqual(response.status_code, 302)

        self.team.refresh_from_db()
        self.club_player.refresh_from_db()
        self.unassigned.refresh_from_db()
        self.free_agent.refresh_from_db()
        self.fixture.refresh_from_db()
        self.transfer.refresh_from_db()
        self.mgr.refresh_from_db()

        self.assertEqual(self.team.pk, original_pk)
        self.assertEqual(self.team.name, "QA Arsenal")
        self.assertEqual(self.team.short_name, "QAR")
        self.assertEqual(self.team.description, "North London club.")
        self.assertEqual(self.team.tokens, original_tokens)
        self.assertEqual(self.team.manager_id, original_manager_id)
        self.assertEqual(self.team.league_id, original_league_id)
        self.assertEqual(Team.objects.count(), original_count)
        self.assertEqual(self.club_player.pk, original_player_id)
        self.assertEqual(self.club_player.mgl_team_id, original_pk)
        self.assertFalse(self.club_player.is_free_agent)
        self.assertEqual(self.club_player.appearances, 3)
        self.assertEqual(self.club_player.goals, 2)
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.free_agent.mgl_team_id)
        self.assertTrue(self.free_agent.is_free_agent)
        self.assertEqual(self.fixture.pk, original_fixture_id)
        self.assertEqual(self.fixture.home_team_id, original_pk)
        self.assertEqual(self.transfer.pk, original_transfer_id)
        self.assertEqual(self.transfer.from_team_id, original_pk)
        self.assertEqual(self.mgr.tokens, Decimal("50.00"))
        self.assertTrue(
            SiteChangeLog.objects.filter(
                action="team.name",
                object_id=str(original_pk),
            ).exists()
        )
        self.assertIn("QA Arsenal", SiteChangeLog.objects.get(action="team.name").summary)

    def test_team_logo_upload_keeps_primary_key(self):
        self._login(self.owner)
        original_pk = self.team.pk
        response = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": self.team.name,
                "short_name": self.team.short_name,
                "description": "",
                "logo": _png(),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.pk, original_pk)
        self.assertTrue(self.team.logo)
        self.assertTrue(
            SiteChangeLog.objects.filter(action="team.logo", object_id=str(original_pk)).exists()
        )

    def test_preview_does_not_save_team(self):
        self._login(self.owner)
        self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "preview",
                "name": "Should Not Save",
                "short_name": "SNS",
                "description": "preview only",
            },
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "QA Test Club")
        self.assertEqual(self.team.short_name, "QTC")

    def test_owner_can_edit_content_and_it_appears_on_home(self):
        self._login(self.owner)
        marker = "UNIQUE CMS HERO SUBTITLE 4921"
        response = self.client.post(
            reverse("site_management_content_section", args=["home"]),
            {
                "action": "save",
                "home.hero_title": "COMPETE. MANAGE. WIN.",
                "home.hero_subtitle": marker,
                "home.about_us": get_content("home.about_us"),
                "home.league_intro": get_content("home.league_intro"),
                "home.news_intro": get_content("home.news_intro"),
                "home.join_title": get_content("home.join_title"),
                "home.join_text": get_content("home.join_text"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SiteContent.objects.filter(key="home.hero_subtitle").count(), 1)
        self.assertEqual(get_content("home.hero_subtitle"), marker)
        self.assertTrue(SiteChangeLog.objects.filter(object_label="Hero Subtitle").exists())

        self.client.logout()
        home = self.client.get("/")
        self.assertContains(home, marker)
        self.assertContains(home, "COMPETE.")

    def test_admin_can_edit_content(self):
        self._login(self.admin)
        self.client.post(
            reverse("site_management_content_section", args=["jobs"]),
            {
                "action": "save",
                "jobs.page_intro": "Admin jobs intro.",
                "jobs.application_instructions": get_content("jobs.application_instructions"),
            },
        )
        self.assertEqual(get_content("jobs.page_intro"), "Admin jobs intro.")
        jobs = self.client.get(reverse("job_centre"))
        self.assertContains(jobs, "VACANT CLUBS")
        self.assertNotContains(jobs, "Admin jobs intro.")

    def test_manager_cannot_edit_content(self):
        self._login(self.manager_user)
        response = self.client.post(
            reverse("site_management_content_section", args=["home"]),
            {"action": "save", "home.hero_title": "Hacked"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(get_content("home.hero_title"), "COMPETE. MANAGE. WIN.")
        self.assertFalse(SiteContent.objects.filter(key="home.hero_title").exists())

    def test_missing_content_falls_back_and_save_does_not_duplicate(self):
        self.assertFalse(SiteContent.objects.filter(key="home.about_us").exists())
        self.assertEqual(
            get_content("home.about_us"),
            "Premium competitive EA FC career football. Real managers. Official clubs. One squad across the website and the game.",
        )
        self._login(self.owner)
        payload = {
            "action": "save",
            "home.hero_title": "COMPETE. MANAGE. WIN.",
            "home.hero_subtitle": get_content("home.hero_subtitle"),
            "home.about_us": "Saved about copy.",
            "home.league_intro": get_content("home.league_intro"),
            "home.news_intro": get_content("home.news_intro"),
            "home.join_title": get_content("home.join_title"),
            "home.join_text": get_content("home.join_text"),
        }
        self.client.post(reverse("site_management_content_section", args=["home"]), payload)
        payload["home.about_us"] = "Saved about copy again."
        self.client.post(reverse("site_management_content_section", args=["home"]), payload)
        self.assertEqual(SiteContent.objects.filter(key="home.about_us").count(), 1)
        self.assertEqual(get_content("home.about_us"), "Saved about copy again.")

    @override_settings(DISCORD_INVITE_URL="")
    def test_discord_url_saves_and_empty_hides_buttons(self):
        home = self.client.get("/")
        self.assertNotContains(home, "JOIN DISCORD")
        self._login(self.owner)
        self.client.post(
            reverse("site_management_settings"),
            {
                "action": "save",
                "settings.site_name": "Meta Gaming League",
                "settings.site_tagline": "Online Career Mode",
                "settings.contact_email": "",
                "settings.discord_invite_url": "https://discord.gg/mgl-test-invite",
                "settings.discord_display_text": "DISCORD",
                "settings.social_x_url": "",
                "settings.social_youtube_url": "",
                "settings.social_instagram_url": "",
            },
        )
        self.assertEqual(
            get_content("settings.discord_invite_url"),
            "https://discord.gg/mgl-test-invite",
        )
        self.assertTrue(
            SiteChangeLog.objects.filter(action="settings.discord_invite_url").exists()
        )
        self.client.logout()
        home = self.client.get("/")
        self.assertContains(home, "https://discord.gg/mgl-test-invite")
        self.assertContains(home, "JOIN DISCORD")

        self._login(self.owner)
        self.client.post(
            reverse("site_management_settings"),
            {
                "action": "save",
                "settings.site_name": "Meta Gaming League",
                "settings.site_tagline": "Online Career Mode",
                "settings.contact_email": "",
                "settings.discord_invite_url": "",
                "settings.discord_display_text": "DISCORD",
                "settings.social_x_url": "",
                "settings.social_youtube_url": "",
                "settings.social_instagram_url": "",
            },
        )
        self.client.logout()
        hidden = self.client.get("/")
        self.assertNotContains(hidden, "JOIN DISCORD")
        self.assertNotContains(hidden, "https://discord.gg/mgl-test-invite")

    def test_league_display_edit_keeps_id_and_does_not_duplicate(self):
        self._login(self.owner)
        original_pk = self.league.pk
        original_name = self.league.name
        original_short = self.league.short_name
        original_count = League.objects.count()
        response = self.client.post(
            reverse("site_management_league_edit", args=[self.league.id]),
            {
                "action": "save",
                "display_name": "MGL Premier",
                "description": "Top division copy.",
                "display_order": "5",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.league.refresh_from_db()
        self.assertEqual(self.league.pk, original_pk)
        self.assertEqual(self.league.name, original_name)
        self.assertEqual(self.league.short_name, original_short)
        self.assertEqual(self.league.display_name, "MGL Premier")
        self.assertEqual(self.league.description, "Top division copy.")
        self.assertEqual(self.league.display_order, 5)
        self.assertEqual(League.objects.count(), original_count)
        self.assertEqual(self.team.league_id, original_pk)
        tables = self.client.get(reverse("leagues_page"))
        self.assertContains(tables, "MGL PREMIER")
        self.assertContains(tables, "Top division copy.")

    def test_mgl_player_states_untouched_after_site_management(self):
        self._login(self.owner)
        self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": "Renamed Club",
                "short_name": self.team.short_name,
                "description": "",
            },
        )
        self.client.post(
            reverse("site_management_settings"),
            {
                "action": "save",
                "settings.site_name": "Meta Gaming League",
                "settings.site_tagline": "Online Career Mode",
                "settings.contact_email": "office@example.com",
                "settings.discord_invite_url": "",
                "settings.discord_display_text": "DISCORD",
                "settings.social_x_url": "",
                "settings.social_youtube_url": "",
                "settings.social_instagram_url": "",
            },
        )
        self.unassigned.refresh_from_db()
        self.free_agent.refresh_from_db()
        self.club_player.refresh_from_db()
        self.team.refresh_from_db()
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.free_agent.mgl_team_id)
        self.assertTrue(self.free_agent.is_free_agent)
        self.assertEqual(self.club_player.mgl_team_id, self.team.id)
        self.assertFalse(self.club_player.is_free_agent)
        self.assertEqual(self.team.tokens, Decimal("50.00"))
        self.assertEqual(self.team.players.count(), 1)

    def _render_logo(self, team):
        return Template("{% load mgl_ui %}{% team_logo team 'md' %}").render(
            Context({"team": team})
        )

    def _assert_identity_untouched(self, team_pk, player_pk, fixture_pk, transfer_pk):
        self.team.refresh_from_db()
        self.club_player.refresh_from_db()
        self.unassigned.refresh_from_db()
        self.free_agent.refresh_from_db()
        self.fixture.refresh_from_db()
        self.transfer.refresh_from_db()
        self.assertEqual(self.team.pk, team_pk)
        self.assertEqual(self.club_player.pk, player_pk)
        self.assertEqual(self.club_player.mgl_team_id, team_pk)
        self.assertFalse(self.club_player.is_free_agent)
        self.assertIsNone(self.unassigned.mgl_team_id)
        self.assertFalse(self.unassigned.is_free_agent)
        self.assertIsNone(self.free_agent.mgl_team_id)
        self.assertTrue(self.free_agent.is_free_agent)
        self.assertEqual(self.fixture.pk, fixture_pk)
        self.assertEqual(self.fixture.home_team_id, team_pk)
        self.assertEqual(self.transfer.pk, transfer_pk)
        self.assertEqual(self.transfer.from_team_id, team_pk)

    def test_uploaded_logo_survives_name_and_short_name_changes(self):
        self._login(self.owner)
        team_pk = self.team.pk
        player_pk = self.club_player.pk
        fixture_pk = self.fixture.pk
        transfer_pk = self.transfer.pk
        upload = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": self.team.name,
                "short_name": self.team.short_name,
                "description": "",
                "logo": _png("kept.png"),
            },
        )
        self.assertEqual(upload.status_code, 302)
        self.team.refresh_from_db()
        stored_logo = self.team.logo.name
        self.assertTrue(stored_logo)

        name_change = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": "QA Renamed Club",
                "short_name": self.team.short_name,
                "description": "Updated description.",
            },
        )
        self.assertEqual(name_change.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.logo.name, stored_logo)
        self.assertIn(self.team.logo.url, self._render_logo(self.team))
        self.assertNotIn("core/img/clubs/", self._render_logo(self.team))

        short_change = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": "QA Renamed Club",
                "short_name": "ARS",
                "description": "Updated description.",
            },
        )
        # Official Arsenal still holds ARS, so first free that code if needed.
        if short_change.status_code != 302:
            arsenal = Team.objects.filter(short_name__iexact="ARS").exclude(pk=self.team.pk).first()
            self.assertIsNotNone(arsenal)
            freed = self.client.post(
                reverse("site_management_team_edit", args=[arsenal.id]),
                {
                    "action": "save",
                    "name": arsenal.name,
                    "short_name": "ARX",
                    "description": arsenal.description or "",
                },
            )
            self.assertEqual(freed.status_code, 302)
            short_change = self.client.post(
                reverse("site_management_team_edit", args=[self.team.id]),
                {
                    "action": "save",
                    "name": "QA Renamed Club",
                    "short_name": "ARS",
                    "description": "Updated description.",
                },
            )
        self.assertEqual(short_change.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.logo.name, stored_logo)
        self.assertEqual(self.team.short_name, "ARS")
        html = self._render_logo(self.team)
        self.assertIn(self.team.logo.url, html)
        self.assertNotIn("core/img/clubs/ARS.svg", html)
        self.assertTrue(SiteChangeLog.objects.filter(action="team.logo", object_id=str(team_pk)).exists())
        self.assertTrue(SiteChangeLog.objects.filter(action="team.name", object_id=str(team_pk)).exists())
        self.assertTrue(SiteChangeLog.objects.filter(action="team.short_name", object_id=str(team_pk)).exists())
        self._assert_identity_untouched(team_pk, player_pk, fixture_pk, transfer_pk)

    def test_changed_short_name_cannot_display_another_team_logo(self):
        self._login(self.owner)
        arsenal = Team.objects.filter(badge_code="ARS").first()
        self.assertIsNotNone(arsenal)
        self.assertEqual(static_badge_path(arsenal), "core/img/clubs/ARS.svg")
        self.assertEqual(self.team.badge_code, "")
        self.assertEqual(static_badge_path(self.team), "")

        if arsenal.short_name.upper() == "ARS":
            freed = self.client.post(
                reverse("site_management_team_edit", args=[arsenal.id]),
                {
                    "action": "save",
                    "name": arsenal.name,
                    "short_name": "ARX",
                    "description": arsenal.description or "",
                },
            )
            self.assertEqual(freed.status_code, 302)
            arsenal.refresh_from_db()
            self.assertEqual(arsenal.short_name, "ARX")
            self.assertEqual(arsenal.badge_code, "ARS")
            self.assertEqual(static_badge_path(arsenal), "core/img/clubs/ARS.svg")

        team_pk = self.team.pk
        player_pk = self.club_player.pk
        fixture_pk = self.fixture.pk
        transfer_pk = self.transfer.pk
        response = self.client.post(
            reverse("site_management_team_edit", args=[self.team.id]),
            {
                "action": "save",
                "name": self.team.name,
                "short_name": "ARS",
                "description": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.short_name, "ARS")
        self.assertEqual(self.team.badge_code, "")
        self.assertEqual(static_badge_path(self.team), "")
        html = self._render_logo(self.team)
        self.assertNotIn("core/img/clubs/ARS.svg", html)
        self.assertNotIn("core/img/clubs/", html)
        self.assertIn("ARS", html)
        self.assertTrue(SiteChangeLog.objects.filter(action="team.short_name", object_id=str(team_pk)).exists())
        self._assert_identity_untouched(team_pk, player_pk, fixture_pk, transfer_pk)

    def test_legacy_club_editor_redirects_to_site_management(self):
        self._login(self.owner)
        response = self.client.get(reverse("edit_club_admin", args=[self.team.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            reverse("site_management_team_edit", args=[self.team.id]),
        )
        posted = self.client.post(
            reverse("edit_club_admin", args=[self.team.id]),
            {"name": "Hacked", "short_name": "HCK"},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertEqual(
            posted["Location"],
            reverse("site_management_team_edit", args=[self.team.id]),
        )
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "QA Test Club")
        self.assertEqual(self.team.short_name, "QTC")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, reverse("site_management_teams"))
        self.assertNotContains(control, reverse("edit_club_admin", args=[self.team.id]))
        clubs = self.client.get(reverse("club_management_admin"))
        self.assertContains(clubs, reverse("site_management_team_edit", args=[self.team.id]))
        self.assertNotContains(clubs, reverse("edit_club_admin", args=[self.team.id]))
        self.assertContains(clubs, "EDIT IDENTITY")
