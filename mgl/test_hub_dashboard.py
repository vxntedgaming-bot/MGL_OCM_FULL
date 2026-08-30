from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import ApprovalStatus, Fixture, MatchSubmission, TeamMatchStats
from players.models import Player
from teams.models import Team


def _user(username, **kwargs):
    return User.objects.create_user(username=username, password="test-pass-123", **kwargs)


def _manager(user, name=None):
    return ManagerApplication.objects.create(
        user=user,
        display_name=name or user.username,
        gamertag=user.username[:8],
        status=ManagerApplication.APPROVED,
    )


class ManagerHubDashboardTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = _user("dashmgr")
        self.manager = _manager(self.user, "Dash Manager")
        self.team = Team.objects.create(
            name="Dash United",
            short_name="DSH",
            league=self.league,
            manager=self.user,
        )
        self.rival = Team.objects.create(
            name="Dash Rival",
            short_name="DRV",
            league=self.league,
        )
        Player.objects.create(
            name="Dash Striker",
            position="ST",
            overall=80,
            mgl_team=self.team,
            goals=6,
            is_free_agent=False,
        )
        Player.objects.create(
            name="Dash Maker",
            position="CAM",
            overall=77,
            mgl_team=self.team,
            assists=2,
            is_free_agent=False,
        )
        self.outstanding = Fixture.objects.create(
            league=self.league,
            home_team=self.team,
            away_team=self.rival,
            matchweek=3,
            is_released=True,
            status="SCHEDULED",
        )
        completed = Fixture.objects.create(
            league=self.league,
            home_team=self.team,
            away_team=self.rival,
            matchweek=1,
            is_released=True,
            status="COMPLETED",
        )
        submission = MatchSubmission.objects.create(
            fixture=completed, status=ApprovalStatus.APPROVED
        )
        TeamMatchStats.objects.create(submission=submission, team=self.team, goals=3)
        TeamMatchStats.objects.create(submission=submission, team=self.rival, goals=1)

    def test_club_manager_sees_dashboard_structure(self):
        self.client.login(username="dashmgr", password="test-pass-123")
        response = self.client.get(reverse("manager_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "mgl-hub.css")
        self.assertContains(response, "Dash United")
        self.assertContains(response, "@dashmgr")
        self.assertContains(response, "PREMIER LEAGUE")
        self.assertContains(response, "Squad 2/30")
        self.assertContains(response, "POSITION")
        self.assertContains(response, "POINTS")
        self.assertContains(response, "GOAL DIFF")
        self.assertContains(response, "FORM")
        self.assertContains(response, ">W<")
        self.assertContains(response, "SQUAD")
        self.assertContains(response, "FIXTURES")
        self.assertContains(response, "LEAGUE TABLE")
        self.assertContains(response, "PROFILE")
        self.assertContains(response, reverse("team_management"))
        self.assertContains(response, reverse("fixture_list"))
        self.assertContains(response, reverse("leagues_page"))
        self.assertContains(response, reverse("manager_profile"))
        self.assertContains(response, reverse("manager_notifications"))
        self.assertContains(response, "1 Notification")
        self.assertNotContains(response, "data-notify-dropdown")
        self.assertNotContains(response, "ACTION REQUIRED")
        self.assertContains(response, "RESIGN")
        self.assertContains(response, f'href="{reverse("manager_hub")}?resign=1"')
        self.assertNotContains(response, "Club Profile")
        self.assertNotContains(response, "CLUB PROFILE")
        self.assertContains(response, reverse("transfer_market"))
        self.assertContains(response, reverse("free_agents"))
        self.assertContains(response, reverse("live_auctions"))
        self.assertContains(response, reverse("scouting"))
        self.assertContains(response, reverse("player_database"))
        self.assertContains(response, reverse("youth_academy"))
        self.assertContains(response, reverse("head_to_head"))
        self.assertContains(response, reverse("pressroom"))
        self.assertContains(response, reverse("historical_tables"))
        self.assertContains(response, "OUTSTANDING FIXTURES")
        self.assertContains(response, "ENTER RESULT")
        self.assertContains(response, reverse("submit_match", args=[self.outstanding.id]))
        self.assertContains(response, "Dash Striker")
        self.assertContains(response, "6 G")
        self.assertContains(response, "Dash Maker")
        self.assertContains(response, "2 A")
        self.assertContains(response, "3–1")
        self.assertContains(response, "RECENT RESULTS")
        self.assertNotContains(response, "NEW MANAGER? START HERE")
        self.assertNotContains(response, "Take over an official MGL club")
        self.assertNotContains(response, "PLAYER RECRUITMENT")
        self.assertNotContains(response, "PENDING ACTIONS")
        self.assertNotContains(response, "Propose Transfer")
        self.assertNotContains(response, "Recruitment Drive")

    def test_manager_without_club_sees_empty_states_and_jobs(self):
        vacant = _user("vacantmgr")
        _manager(vacant, "Vacant Manager")
        self.client.login(username="vacantmgr", password="test-pass-123")
        response = self.client.get(reverse("manager_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NO CLUB ASSIGNED")
        self.assertContains(response, "APPLY FOR A CLUB")
        self.assertContains(response, reverse("job_centre"))
        self.assertContains(response, reverse("manager_notifications"))
        self.assertContains(response, "Notifications")
        self.assertNotContains(response, "1 Notification")
        self.assertContains(response, "PERSONAL BALANCE")
        self.assertContains(response, "20.00 TKN")
        self.assertContains(response, "—")
        self.assertNotContains(response, "ENTER RESULT")

    def test_enter_result_hidden_when_match_already_submitted(self):
        MatchSubmission.objects.create(fixture=self.outstanding)
        self.client.login(username="dashmgr", password="test-pass-123")
        response = self.client.get(reverse("manager_hub"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OUTSTANDING FIXTURES")
        self.assertContains(response, "Dash Rival")
        self.assertNotContains(response, reverse("submit_match", args=[self.outstanding.id]))
        self.assertNotContains(response, "ENTER RESULT")

    def test_standings_use_approved_results(self):
        self.client.login(username="dashmgr", password="test-pass-123")
        response = self.client.get(reverse("manager_hub"))
        row = response.context["standings_row"]
        self.assertEqual(row["played"], 1)
        self.assertEqual(row["points"], 3)
        self.assertEqual(row["gd"], 2)
        self.assertEqual(row["position"], 1)
        self.assertEqual(list(response.context["form"]), ["W"])
        self.assertTrue(response.context["outstanding"][0].can_submit)

    def test_hub_resign_stay_leaves_assignment(self):
        self.client.login(username="dashmgr", password="test-pass-123")
        page = self.client.get(reverse("manager_hub") + "?resign=1")
        self.assertContains(page, "RESIGN FROM CLUB?")
        self.assertContains(page, "Are you sure you want to leave your current MGL club?")
        self.assertContains(page, "does not delete your account")
        self.assertContains(page, ">STAY<")
        self.assertContains(page, reverse("manager_hub"))
        stay = self.client.get(reverse("manager_hub"))
        self.assertNotContains(stay, "RESIGN FROM CLUB?")
        self.team.refresh_from_db()
        self.assertEqual(self.team.manager_id, self.user.id)

    def test_hub_resign_clears_club_and_keeps_account(self):
        tokens_before = self.manager.tokens
        self.client.login(username="dashmgr", password="test-pass-123")
        response = self.client.post(
            reverse("resign_from_club"),
            {"next": "hub"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("manager_hub"))
        self.team.refresh_from_db()
        self.user.refresh_from_db()
        self.manager.refresh_from_db()
        self.assertIsNone(self.team.manager_id)
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.manager.status, ManagerApplication.APPROVED)
        self.assertEqual(self.manager.tokens, tokens_before)
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "NO CLUB ASSIGNED")
        self.assertContains(hub, "APPLY FOR A CLUB")
        self.assertContains(hub, reverse("job_centre"))
        self.assertNotContains(hub, "RESIGN FROM CLUB?")
        self.assertEqual(self.team.players.count(), 2)
