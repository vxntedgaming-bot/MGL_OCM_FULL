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
from mgl.club_urls import club_page_url, club_slug
from mgl.press import (
    create_appointment_press,
    create_press_question,
    maybe_create_odd_matchday_interview,
)
from mgl.press_questions import QUESTION_BANK
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
        self.assertContains(response, club_page_url(self.vacant))
        self.assertContains(response, "VACANT / NO MANAGER")
        self.assertContains(response, self.vacant.name)
        self.assertNotContains(response, "50.00 TKN")
        self.assertNotContains(response, "APPLY & JOIN DISCORD")
        self.assertContains(response, "mgl-jobs.css")
        self.assertNotContains(response, "<details")
        self.assertContains(response, "APPLY FOR")
        self.assertNotContains(response, reverse("apply_for_club", args=[self.occupied.id]))
        slug_page = self.client.get(club_page_url(self.vacant))
        self.assertEqual(slug_page.status_code, 200)
        short_page = self.client.get(reverse("club_page", args=[self.vacant.short_name]))
        self.assertEqual(short_page.status_code, 200)

    def test_logged_in_manager_sees_apply_form_on_each_vacant_card(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.get(reverse("job_centre"))
        self.assertContains(response, "APPLY FOR")
        self.assertContains(response, "EA ID / GAMERTAG")
        self.assertContains(response, "DISCORD USERNAME")
        self.assertContains(response, "GAMES PER WEEK")
        self.assertContains(response, "REFERRED BY")
        self.assertContains(response, "new gen console")
        self.assertContains(response, "APPLY &amp; JOIN DISCORD")
        self.assertContains(response, reverse("apply_for_club", args=[self.vacant.id]))
        self.assertNotContains(response, "<details")
        self.assertNotContains(response, reverse("apply_for_club", args=[self.occupied.id]))

    def test_user_can_apply_for_vacant_club(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(
            reverse("apply_for_club", args=[self.vacant.id]),
            JOB_APPLY,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("job_centre") + "?join_discord=1")
        app = ClubApplication.objects.get(manager=self.manager, team=self.vacant)
        self.assertEqual(app.status, ApprovalStatus.PENDING)
        self.assertEqual(app.gamertag, "EAID1")
        self.assertEqual(app.discord_username, "discorduser")
        self.assertTrue(app.new_gen_confirmed)
        self.vacant.refresh_from_db()
        self.assertIsNone(self.vacant.manager_id)
        joined = self.client.get(reverse("job_centre") + "?join_discord=1")
        self.assertContains(joined, "https://discord.gg/Jmf29wBafP")
        self.assertContains(joined, "Application sent")
        self.assertNotContains(joined, "YOUR APPLICATIONS")
        self.assertNotContains(joined, ">STATUS</h2>")
        self.assertNotContains(joined, 'class="table-row"')

    def test_pending_application_does_not_render_status_bar_for_any_role(self):
        public = self.client.get(reverse("job_centre"))
        self.assertEqual(public.status_code, 200)
        self.assertNotContains(public, "YOUR APPLICATIONS")
        self.assertNotContains(public, ">STATUS</h2>")
        self.assertNotContains(public, 'class="table-row"')

        self.client.login(username="applicant", password="test-pass-123")
        self.client.post(reverse("apply_for_club", args=[self.vacant.id]), JOB_APPLY)
        app = ClubApplication.objects.get(manager=self.manager, team=self.vacant)
        self.assertEqual(app.status, ApprovalStatus.PENDING)

        manager_jobs = self.client.get(reverse("job_centre"))
        self.assertNotContains(manager_jobs, "YOUR APPLICATIONS")
        self.assertNotContains(manager_jobs, ">STATUS</h2>")
        self.assertNotContains(manager_jobs, 'class="table-row"')
        self.assertContains(manager_jobs, "Your application is pending Owner/Admin review.")
        hub = self.client.get(reverse("manager_hub"))
        self.assertNotContains(hub, "YOUR APPLICATIONS")
        self.assertNotContains(hub, ">STATUS</h2>")

        _manager(self.owner)
        _user("jobs-admin", role=User.ADMIN)
        for username in ("owner", "jobs-admin"):
            self.client.logout()
            self.client.login(username=username, password="test-pass-123")
            staff_jobs = self.client.get(reverse("job_centre"))
            self.assertNotContains(staff_jobs, "YOUR APPLICATIONS")
            self.assertNotContains(staff_jobs, ">STATUS</h2>")
            self.assertNotContains(staff_jobs, 'class="table-row"')

        self.client.logout()
        self.client.login(username="owner", password="test-pass-123")
        control = self.client.get(reverse("control_centre"))
        self.assertContains(control, self.vacant.name)
        inbox = self.client.get(reverse("manager_notifications"))
        self.assertContains(inbox, "CLUB APPLICATION")
        self.assertContains(inbox, self.vacant.name)
        self.assertEqual(
            ClubApplication.objects.filter(manager=self.manager, team=self.vacant).count(),
            1,
        )

    def test_application_requires_required_fields(self):
        self.client.login(username="applicant", password="test-pass-123")
        response = self.client.post(reverse("apply_for_club", args=[self.vacant.id]), {})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("join_discord", response["Location"])
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

    def test_clubless_approved_manager_sees_jobs_nav_and_vacancies(self):
        self.client.login(username="applicant", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, ">JOBS</a>")
        self.assertContains(hub, reverse("job_centre"))
        jobs = self.client.get(reverse("job_centre"))
        self.assertEqual(jobs.status_code, 200)
        self.assertContains(jobs, "mgl-nav-link is-active")
        self.assertContains(jobs, self.vacant.name)
        self.assertContains(jobs, "APPLY FOR")
        self.assertNotContains(jobs, "REGISTER TO APPLY")
        self.assertNotContains(jobs, "YOU ALREADY MANAGE A CLUB")

    def test_owner_still_reaches_job_centre_and_control(self):
        self.client.login(username="owner", password="test-pass-123")
        jobs = self.client.get(reverse("job_centre"))
        self.assertEqual(jobs.status_code, 200)
        self.assertContains(jobs, ">JOBS</a>")
        self.assertContains(jobs, reverse("job_centre"))
        self.assertContains(jobs, reverse("control_centre"))
        self.assertContains(jobs, self.vacant.name)

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
        self.assertContains(page, "SQUAD STAR")
        self.assertContains(page, reverse("player_profile", args=[player.id]))
        self.assertContains(page, "mgl-player-card")
        self.assertContains(page, "mgl-player-card-grid")
        self.assertNotContains(page, "mgl-squad-table-head")
        self.assertNotContains(page, "mgl-squad-row")
        self.assertNotContains(page, ">POS</span>")
        self.assertContains(page, "VACANT")
        self.assertNotContains(page, "TOKEN BALANCE")
        self.assertNotContains(page, "RELEASE")
        pretty = self.client.get("/clubs/%s/" % club_slug(self.vacant))
        self.assertEqual(pretty.status_code, 200)
        self.assertContains(pretty, "SQUAD STAR")
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
        self.user_c = _user("idleone")
        self.user_d = _user("idletwo")
        _manager(self.user_c)
        _manager(self.user_d)
        self.team_c = Team.objects.create(
            name="Idle One", short_name="IOX", league=self.league, manager=self.user_c
        )
        self.team_d = Team.objects.create(
            name="Idle Two", short_name="ITW", league=self.league, manager=self.user_d
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
            opponent_response=ApprovalStatus.APPROVED,
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
        self.assertContains(activity, "RESULT")
        self.assertContains(activity, "Gameweek 1")

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

    def test_pending_questions_are_unique_across_managers(self):
        first = create_press_question(
            manager=self.user_a,
            team=self.team_a,
            question="What was the key to today's victory?",
            question_key="win_key",
            category="win",
            trigger=PressConference.MATCH,
        )
        clash = create_press_question(
            manager=self.user_b,
            team=self.team_b,
            question="What was the key to today's victory?",
            question_key="win_key",
            category="win",
            trigger=PressConference.MATCH,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(clash)

    def test_question_bank_keys_are_unique(self):
        keys = []
        for questions in QUESTION_BANK.values():
            keys.extend(key for key, _text in questions)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertGreaterEqual(len(keys), 80)

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
        activity = self.client.get(reverse("live_activity"))
        self.assertNotContains(activity, "MANAGER APPOINTED")
        self.assertContains(activity, "SIGNING")
        self.assertContains(activity, "Free Signing")

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
        activity = self.client.get(reverse("live_activity"))
        self.assertNotContains(activity, "AUCTION STARTED")
        self.assertNotContains(activity, "Pool Player")


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
        self.assertContains(hub, "THE REMAINING GAMES LEFT TO PLAY")
        self.assertContains(hub, "Gameweek")
        self.assertContains(hub, "Own Striker")
        self.assertContains(hub, "4 G")
        self.assertContains(hub, "Own Maker")
        self.assertContains(hub, "3 A")
        self.assertContains(hub, "TOP SCORERS")
        self.assertContains(hub, "TOP ASSISTS")
        self.assertContains(hub, "RECENT RESULTS")
        self.assertNotContains(hub, "Other Striker")
        self.assertContains(hub, "W")
        self.assertContains(hub, 'data-nav-dropdown="my-club"')
        self.assertContains(hub, "RESIGN")
        self.assertNotContains(hub, "Club Profile")
        self.assertContains(hub, reverse("manager_notifications"))
        self.assertContains(hub, reverse("team_management"))
        self.assertContains(hub, reverse("submit_match", args=[hub.context["outstanding"][0].id]))
        self.assertNotContains(hub, "Recruitment Drive")
        self.assertNotContains(hub, "PLAYER RECRUITMENT")
        self.assertNotContains(hub, "PENDING ACTIONS")
        self.assertNotContains(hub, "Propose Transfer")
        self.assertNotContains(hub, reverse("control_centre"))
        self.assertNotContains(hub, "UNASSIGNED PLAYERS")

    def test_member_without_club_keeps_public_home(self):
        member = _user("fan")
        _manager(member)
        self.client.login(username="fan", password="test-pass-123")
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertContains(home, "COMPETE.")
        self.assertContains(home, "LIVE ACTIVITY")
        self.assertNotContains(home, "MGL CLUBS")


class NewsAndTablePublicTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        ensure_premier_league()

    def test_league_table_club_is_clickable_and_clubs_grid_removed(self):
        tables = self.client.get(reverse("leagues_page"))
        self.assertEqual(tables.status_code, 200)
        self.assertContains(tables, "LEAGUE TABLES")
        arsenal = Team.objects.get(short_name="ARS")
        self.assertContains(tables, club_page_url(arsenal))
        self.assertContains(tables, "/clubs/arsenal/")
        self.assertNotContains(tables, "MANAGER VACANT")
        self.assertNotContains(tables, "50.00 TKN")

    def test_news_tabs_and_public_fixtures(self):
        news = self.client.get(reverse("news_centre"))
        self.assertEqual(news.status_code, 302)
        self.assertEqual(news["Location"], reverse("live_activity"))
        self.assertEqual(self.client.get(reverse("live_activity")).status_code, 200)
        self.assertEqual(self.client.get(reverse("pressroom")).status_code, 200)
        self.assertEqual(self.client.get(reverse("fixture_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("clubs_index")).status_code, 200)
