from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import Fixture
from teams.models import Team


def _manager(user, display, tag):
    return ManagerApplication.objects.create(
        user=user,
        display_name=display,
        gamertag=tag,
        status=ManagerApplication.APPROVED,
    )


class ManagerFixturesPageTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.home_user = User.objects.create_user(
            username="fxhome", password="test-pass-123"
        )
        self.away_user = User.objects.create_user(
            username="fxaway", password="test-pass-123"
        )
        self.other_user = User.objects.create_user(
            username="fxother", password="test-pass-123"
        )
        _manager(self.home_user, "Home Mgr", "HFX")
        _manager(self.away_user, "Away Mgr", "AFX")
        _manager(self.other_user, "Other Mgr", "OFX")
        self.home = Team.objects.create(
            name="Fixture Home", short_name="FXH", league=self.league, manager=self.home_user
        )
        self.away = Team.objects.create(
            name="Fixture Away", short_name="FXA", league=self.league, manager=self.away_user
        )
        self.other = Team.objects.create(
            name="Fixture Other", short_name="FXO", league=self.league, manager=self.other_user
        )
        self.own = Fixture.objects.create(
            league=self.league,
            home_team=self.home,
            away_team=self.away,
            matchweek=1,
            is_released=True,
            status="SCHEDULED",
        )
        self.foreign = Fixture.objects.create(
            league=self.league,
            home_team=self.other,
            away_team=self.away,
            matchweek=2,
            is_released=True,
            status="SCHEDULED",
        )

    def test_anonymous_fixtures_page_is_public(self):
        response = self.client.get(reverse("fixture_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mgl-fixtures.css")
        self.assertContains(response, "Fixture Home")
        self.assertContains(response, "Fixture Other")

    def test_empty_released_copy_stays(self):
        Fixture.objects.all().delete()
        response = self.client.get(reverse("fixture_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NO FIXTURES HAVE BEEN RELEASED YET")

    def test_manager_only_sees_assigned_club_fixtures(self):
        self.client.login(username="fxhome", password="test-pass-123")
        response = self.client.get(reverse("fixture_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fixture Home")
        self.assertContains(response, "Fixture Away")
        self.assertNotContains(response, "Fixture Other")
        self.assertContains(response, reverse("fixture_stats", args=[self.own.id]))
        self.assertNotContains(response, reverse("fixture_stats", args=[self.foreign.id]))

    def test_manager_cannot_open_another_club_stats_page(self):
        self.client.login(username="fxhome", password="test-pass-123")
        response = self.client.get(reverse("fixture_stats", args=[self.foreign.id]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("fixture_list"))

    def test_stats_alias_opens_existing_submit_form(self):
        self.client.login(username="fxhome", password="test-pass-123")
        page = self.client.get(reverse("fixture_stats", args=[self.own.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'name="home_goals"')
        self.assertContains(page, 'data-prefix="home"')
        self.assertContains(page, "BACK TO FIXTURES")
        self.assertContains(page, "mgl-match-submit.js")
