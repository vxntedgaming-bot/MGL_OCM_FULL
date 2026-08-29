from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.market import create_free_agent_auction, settle_auction
from mgl.models import (
    ApprovalStatus,
    ClubApplication,
    Fixture,
    GoalEvent,
    MatchSubmission,
    NewsPost,
    PressConference,
    TeamMatchStats,
)
from mgl.press import (
    create_appointment_press,
    create_press_question,
    maybe_create_odd_matchday_interview,
)
from mgl.services import sign_free_agent
from players.models import Player
from teams.models import Team


JOB_APPLY = {
    "gamertag": "EAID1",
    "discord_username": "discorduser",
    "games_per_week": "3",
    "new_gen_confirmed": "on",
}


def _user(username, role=User.MANAGER, **kwargs):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
        **kwargs,
    )


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class JobCentreExperienceTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user = _user("applicant")
        self.manager = _manager(self.user)
        self.vacant = Team.objects.filter(short_name="TOT").first() or Team.objects.create(
            name="Tottenham Hotspur",
            short_name="TOT",
            league=self.league,
            tokens=Decimal("50.00"),
        )
        self.vacant.manager = None
        self.vacant.tokens = Decimal("50.00")
        self.vacant.save()
        self.occupied = Team.objects.filter(short_name="ARS").first() or Team.objects.create(
            name="Arsenal",
            short_name="ARS",
            league=self.league,
        )
        self.boss = _user("boss")
        _manager(self.boss)
        self.occupied.manager = self.boss
        self.occupied.save()

    def test_jobs_hides_treasury_and_shows_view_squad(self):
        response = self.client.get(reverse("job_centre"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VIEW SQUAD")
        self.assertContains(response, reverse("club_page", args=[self.vacant.short_name]))
        self.assertNotContains(response, "50.00 TKN")
        self.assertContains(response, "APPLY FOR TOT")

    def test_user_can_apply_for_vacant_club(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            JOB_APPLY,
        )
        self.assertEqual(response.status_code, 302)
        app = ClubApplication.objects.get(manager=self.manager, team=self.vacant)
        self.assertEqual(app.status, ApprovalStatus.PENDING)
        self.assertEqual(app.gamertag, "EAID1")
        self.assertEqual(app.discord_username, "discorduser")
        self.assertTrue(app.new_gen_confirmed)
        self.vacant.refresh_from_db()
        self.assertIsNone(self.vacant.manager_id)

    def test_application_requires_required_fields(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(reverse("apply_for_club", args=[self.vacant.id]), {})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClubApplication.objects.filter(manager=self.manager).exists())

    def test_cannot_apply_for_occupied_club(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(
            reverse("apply_for_club", args=[self.occupied.id]),
            JOB_APPLY,
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            ClubApplication.objects.filter(manager=self.manager, team=self.occupied).exists()
        )

    def test_manager_cannot_apply_when_already_assigned(self):
        self.vacant.manager = self.user
        self.vacant.save()
        other = Team.objects.filter(short_name="CHE").first() or Team.objects.create(
            name="Chelsea",
            short_name="CHE",
            league=self.league,
        )
        other.manager = None
        other.save()
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(
            reverse("apply_for_club", args=[other.id]),
            JOB_APPLY,
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(ClubApplication.objects.filter(manager=self.manager, team=other).exists())

    def test_public_club_page_shows_squad_without_edit(self):
        player = Player.objects.create(
            name="Squad Star",
            position="ST",
            overall=81,
            mgl_team=self.vacant,
            is_free_agent=False,
        )
        page = self.client.get(reverse("club_page", args=[self.vacant.short_name]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Squad Star")
        self.assertContains(page, reverse("player_profile", args=[player.id]))
        self.assertNotContains(page, "TOKEN BALANCE")
        self.assertNotContains(page, "RELEASE")
        public_player = self.client.get(reverse("player_profile", args=[player.id]))
        self.assertEqual(public_player.status_code, 200)


class LiveActivityAndPressTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(
            name="Arsenal Test", short_name="ATX", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Chelsea Test", short_name="CTX", league=self.league, manager=self.user_b
        )
        self.scorer = Player.objects.create(
            name="Home Striker",
            position="ST",
            overall=80,
            mgl_team=self.team_a,
            is_free_agent=False,
        )

    def _pending_match(self, matchweek=1):
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=matchweek,
            is_released=True,
            status="SCHEDULED",
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.PENDING,
        )
        home_stats = TeamMatchStats.objects.create(
            submission=submission, team=self.team_a, goals=3, shots=10, possession=55
        )
        TeamMatchStats.objects.create(
            submission=submission, team=self.team_b, goals=2, shots=8, possession=45
        )
        GoalEvent.objects.create(team_stats=home_stats, player=self.scorer)
        return fixture, submission

    def test_pending_result_creates_no_official_activity(self):
        self._pending_match()
        self.assertFalse(NewsPost.objects.filter(category=NewsPost.RESULTS).exists())
        page = self.client.get(reverse("live_activity"))
        self.assertNotContains(page, "Arsenal Test 3")

    def test_approved_result_creates_activity_and_press(self):
        fixture, submission = self._pending_match(matchweek=1)
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        news = NewsPost.objects.get(category=NewsPost.RESULTS)
        self.assertTrue(news.published)
        self.assertIn("Arsenal Test", news.title)
        self.assertTrue(
            PressConference.objects.filter(
                manager=self.user_a, trigger=PressConference.MATCH, fixture=fixture
            ).exists()
        )
        self.assertTrue(
            PressConference.objects.filter(
                trigger=PressConference.ODD_MATCHDAY, matchweek=1
            ).exists()
        )
        activity = self.client.get(reverse("live_activity"))
        self.assertContains(activity, "MATCH RESULT")

    def test_odd_matchday_does_not_repeat_same_manager_in_cycle(self):
        fixture, submission = self._pending_match(matchweek=1)
        approve_match_submission(submission, self.owner)
        first = PressConference.objects.get(trigger=PressConference.ODD_MATCHDAY, matchweek=1)
        fixture2 = Fixture.objects.create(
            league=self.league,
            home_team=self.team_b,
            away_team=self.team_a,
            matchweek=1,
            is_released=True,
            status="COMPLETED",
        )
        self.assertIsNone(maybe_create_odd_matchday_interview(fixture2))
        self.assertEqual(
            PressConference.objects.filter(trigger=PressConference.ODD_MATCHDAY, matchweek=1).count(),
            1,
        )
        fixture3 = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=3,
            is_released=True,
            status="COMPLETED",
        )
        second = maybe_create_odd_matchday_interview(fixture3)
        self.assertIsNotNone(second)
        self.assertNotEqual(second.manager_id, first.manager_id)

    def test_same_pending_question_is_not_duplicated(self):
        first = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How pleased were you with the performance?",
            question_key="perf_pleased",
            category="performance",
            trigger=PressConference.MATCH,
        )
        duplicate = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="How pleased were you with the performance?",
            question_key="perf_pleased",
            category="performance",
            trigger=PressConference.MATCH,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)

    def test_new_manager_gets_appointment_question(self):
        press = create_appointment_press(self.user_a, self.team_a)
        self.assertIsNotNone(press)
        self.assertEqual(press.trigger, PressConference.APPOINTMENT)
        self.assertIn("Arsenal Test", press.question)

    def test_approved_transfer_and_appointment_create_activity(self):
        vacant = Team.objects.create(
            name="Vacant Test", short_name="VTX", league=self.league
        )
        newbie = _user("newbie")
        mgr = _manager(newbie)
        ClubApplication.objects.create(
            manager=mgr,
            team=vacant,
            status=ApprovalStatus.PENDING,
            gamertag="NEW",
            discord_username="new",
            games_per_week="3",
            new_gen_confirmed=True,
        )
        self.client.login(username="owner", password="test-pass-123")
        job = ClubApplication.objects.get(manager=mgr, team=vacant)
        self.client.post(reverse("control_approve_job", args=[job.id]))
        vacant.refresh_from_db()
        self.assertEqual(vacant.manager_id, newbie.id)
        self.assertTrue(NewsPost.objects.filter(category=NewsPost.MANAGER).exists())
        self.assertTrue(
            PressConference.objects.filter(
                manager=newbie, trigger=PressConference.APPOINTMENT
            ).exists()
        )
        fa = Player.objects.create(name="Free Signing", position="ST", overall=66, is_free_agent=True)
        sign_free_agent(fa, self.mgr_a)
        self.assertTrue(NewsPost.objects.filter(category=NewsPost.SIGNING).exists())

    def test_auction_no_bid_creates_free_agent_activity(self):
        player = Player.objects.create(
            name="Pool Player", position="CB", overall=64, is_free_agent=False
        )
        auction = create_free_agent_auction(player, self.owner, 30)
        self.assertTrue(NewsPost.objects.filter(category=NewsPost.AUCTION, title__icontains="Pool Player").exists())
        auction.ends_at = timezone.now()
        auction.save(update_fields=["ends_at"])
        settle_auction(auction, reviewer=self.owner)
        player.refresh_from_db()
        self.assertTrue(player.is_free_agent)
        self.assertTrue(
            NewsPost.objects.filter(category=NewsPost.FREE_AGENT, body__icontains="no bids").exists()
        )


class ManagerHubExperienceTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = _user("hubmgr")
        self.manager = _manager(self.user)
        self.team = Team.objects.create(
            name="Hub United", short_name="HUB", league=self.league, manager=self.user
        )
        self.rival = Team.objects.create(
            name="Rival FC", short_name="RIV", league=self.league
        )
        self.scorer = Player.objects.create(
            name="Own Striker",
            position="ST",
            overall=78,
            mgl_team=self.team,
            goals=4,
            appearances=5,
            is_free_agent=False,
        )
        self.maker = Player.objects.create(
            name="Own Maker",
            position="CAM",
            overall=76,
            mgl_team=self.team,
            assists=3,
            is_free_agent=False,
        )
        Player.objects.create(
            name="Other Striker",
            position="ST",
            overall=82,
            mgl_team=self.rival,
            goals=9,
            is_free_agent=False,
        )
        for week in range(1, 9):
            Fixture.objects.create(
                league=self.league,
                home_team=self.team if week % 2 else self.rival,
                away_team=self.rival if week % 2 else self.team,
                matchweek=week,
                is_released=True,
                status="SCHEDULED",
            )
        for week in range(10, 15):
            fixture = Fixture.objects.create(
                league=self.league,
                home_team=self.team,
                away_team=self.rival,
                matchweek=week,
                is_released=True,
                status="COMPLETED",
            )
            submission = MatchSubmission.objects.create(
                fixture=fixture, status=ApprovalStatus.APPROVED
            )
            TeamMatchStats.objects.create(submission=submission, team=self.team, goals=2)
            TeamMatchStats.objects.create(submission=submission, team=self.rival, goals=1)

    def test_assigned_manager_homepage_becomes_hub(self):
        self.client.login(username="hubmgr", password="test-pass-123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 302)
        self.assertEqual(home["Location"], reverse("manager_hub"))
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "Hub United")
        self.assertContains(hub, "MGL MANAGER HUB")
        self.assertContains(hub, "OUTSTANDING FIXTURES — 8")
        self.assertContains(hub, "Own Striker")
        self.assertContains(hub, "4 GLS")
        self.assertContains(hub, "Own Maker")
        self.assertContains(hub, "3 AST")
        self.assertNotContains(hub, "Other Striker")
        self.assertContains(hub, "W")
        self.assertNotContains(hub, reverse("control_centre"))

    def test_member_without_club_keeps_public_home(self):
        member = _user("fan")
        _manager(member)
        self.client.login(username="fan", password="test-pass-123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "COMPETE.")


class NewsAndTablePublicTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        ensure_premier_league()

    def test_league_table_club_is_clickable_and_clubs_grid_removed(self):
        tables = self.client.get(reverse("leagues_page"))
        self.assertEqual(tables.status_code, 200)
        self.assertContains(tables, "LEAGUE TABLES")
        self.assertContains(tables, reverse("club_page", args=["ARS"]))
        self.assertNotContains(tables, "MANAGER VACANT")

    def test_news_tabs_and_public_fixtures(self):
        self.assertEqual(self.client.get(reverse("news_centre")).status_code, 200)
        self.assertEqual(self.client.get(reverse("live_activity")).status_code, 200)
        self.assertEqual(self.client.get(reverse("pressroom")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fixture_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("clubs_index")).status_code, 200)
