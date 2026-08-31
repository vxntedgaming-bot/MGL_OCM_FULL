from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.models import (
    ApprovalStatus,
    AssistEvent,
    Fixture,
    GoalEvent,
    ManagerNotification,
    MatchSubmission,
    PressConference,
    RewardTransaction,
    TeamMatchStats,
    WeeklyAwardBatch,
)
from mgl.notifications import inbox_for_user, unread_count_for_user
from mgl.press import create_press_question, submit_press_answer
from mgl.press_schedule import ensure_daily_press_for_user
from mgl.weekly_awards import mgl_week_start, run_weekly_awards
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(
        username=username,
        password="test-pass-123",
        role=role,
    )


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class NotificationBellTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.user = _user("bellmgr")
        self.manager = _manager(self.user)
        self.team = Team.objects.create(
            name="Bell United",
            short_name="BEL",
            league=self.league,
            manager=self.user,
        )

    def test_logged_out_home_has_no_bell(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertNotContains(home, "data-notify-dropdown")

    def test_logged_in_manager_sees_bell_and_badge(self):
        create_press_question(
            manager=self.user,
            team=self.team,
            question="How pleased were you with the performance?",
            question_key="bell_press",
            category="performance",
            trigger=PressConference.MATCH,
        )
        self.client.login(username="bellmgr", password="test-pass-123")
        hub = self.client.get(reverse("manager_hub"))
        self.assertContains(hub, "data-notify-dropdown")
        self.assertContains(hub, "mgl-notify-count")
        self.assertContains(hub, reverse("notification_panel"))
        panel = self.client.get(reverse("notification_panel"))
        self.assertEqual(panel.status_code, 200)
        self.assertContains(panel, "PRESS CONFERENCE")
        self.assertContains(panel, "MARK ALL AS READ")
        self.assertContains(panel, "TYPE YOUR ANSWER")

    def test_mark_one_and_mark_all_read(self):
        notice = ManagerNotification.objects.create(
            recipient=self.user,
            source_key="admin-bell-1",
            notification_type="ADMIN",
            title="LEAGUE NOTE",
            message="Fixture update.",
        )
        ManagerNotification.objects.create(
            recipient=self.user,
            source_key="admin-bell-2",
            notification_type="ADMIN",
            title="SECOND NOTE",
            message="Another update.",
        )
        self.assertEqual(unread_count_for_user(self.user), 2)
        self.client.login(username="bellmgr", password="test-pass-123")
        marked = self.client.post(reverse("notification_mark_read", args=[notice.id]))
        self.assertEqual(marked.status_code, 302)
        self.assertEqual(unread_count_for_user(self.user), 1)
        self.client.post(reverse("notification_mark_all_read"))
        self.assertEqual(unread_count_for_user(self.user), 0)


class MatchTokenRewardTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
        self.team_a = Team.objects.create(
            name="Arsenal Test",
            short_name="ATX",
            league=self.league,
            manager=self.user_a,
        )
        self.team_b = Team.objects.create(
            name="Chelsea Test",
            short_name="CTX",
            league=self.league,
            manager=self.user_b,
        )
        self.home_st = Player.objects.create(
            name="Home Striker",
            position="ST",
            overall=81,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.away_st = Player.objects.create(
            name="Away Striker",
            position="ST",
            overall=79,
            mgl_team=self.team_b,
            is_free_agent=False,
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=4,
            is_released=True,
            status="SCHEDULED",
        )

    def test_admin_approve_pays_both_managers_once(self):
        self.client.login(username="kai", password="test-pass-123")
        posted = self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            {
                "home_goals": "2",
                "away_goals": "1",
                "home_goal_1": str(self.home_st.id),
                "home_goal_2": str(self.home_st.id),
                "away_goal_1": str(self.away_st.id),
                "home_shots": "8",
                "away_shots": "4",
                "home_possession": "55",
                "away_possession": "45",
                "home_yellow_cards": "0",
                "away_yellow_cards": "0",
                "home_red_cards": "0",
                "away_red_cards": "0",
            },
        )
        self.assertEqual(posted.status_code, 302)
        notice = ManagerNotification.objects.get(
            recipient=self.user_b,
            source_key=f"score-submitted-{self.fixture.pk}",
        )
        self.client.login(username="rival", password="test-pass-123")
        panel = self.client.get(reverse("notification_panel"))
        self.assertContains(panel, "ACCEPT")
        self.assertContains(panel, "REJECT")
        self.client.post(
            reverse("manager_notification_respond", args=[notice.id]),
            {"action": "accept"},
        )
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("21.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("21.00"))
        self.assertEqual(
            RewardTransaction.objects.filter(
                reference=f"match:{self.fixture.id}:home"
            ).count(),
            1,
        )
        self.assertEqual(
            RewardTransaction.objects.filter(
                reference=f"match:{self.fixture.id}:away"
            ).count(),
            1,
        )
        from mgl.services import credit_manager

        credit_manager(
            self.mgr_a,
            Decimal("1.00"),
            "Approved league match",
            "MATCH",
            self.fixture,
            reference=f"match:{self.fixture.id}:home",
        )
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("21.00"))
        self.assertEqual(self.mgr_b.tokens, Decimal("21.00"))


class PressTokenRewardTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.owner = _user("owner", role=User.OWNER)
        self.user = _user("kai")
        self.manager = _manager(self.user, "20.00")
        self.team = Team.objects.create(
            name="Arsenal Test",
            short_name="ATX",
            league=self.league,
            manager=self.user,
        )

    def test_answer_pays_half_token_once(self):
        press = create_press_question(
            manager=self.user,
            team=self.team,
            question="How important was that result?",
            question_key="press_pay",
            category="performance",
            trigger=PressConference.MATCH,
        )
        submit_press_answer(press, "We controlled the game.")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("20.50"))
        self.assertEqual(
            RewardTransaction.objects.filter(reference=f"press:{press.pk}").count(),
            1,
        )
        with self.assertRaises(ValueError):
            submit_press_answer(press, "Trying again.")
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("20.50"))

        from mgl.press import approve_press_conference

        approve_press_conference(press, reviewer=self.owner)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, Decimal("20.50"))


class DailyPressScheduleTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.user = _user("pressmgr")
        self.manager = _manager(self.user)
        self.team = Team.objects.create(
            name="Press United",
            short_name="PRS",
            league=self.league,
            manager=self.user,
        )

    def test_four_staggered_questions_are_hidden_until_due(self):
        created = ensure_daily_press_for_user(self.user)
        self.assertEqual(len(created), 4)
        times = [row.available_at for row in created]
        self.assertTrue(all(times))
        self.assertEqual(len(times), len(set(times)))
        inbox_titles = [item.title for item in inbox_for_user(self.user)]
        self.assertNotIn("PRESS CONFERENCE", inbox_titles)
        due = created[0]
        due.available_at = timezone.now() - timedelta(minutes=1)
        due.save(update_fields=["available_at"])
        titles = [item.title for item in inbox_for_user(self.user)]
        self.assertIn("PRESS CONFERENCE", titles)
        again = ensure_daily_press_for_user(self.user)
        self.assertEqual(again, [])


class WeeklyAwardTests(TestCase):
    def setUp(self):
        self.league = ensure_premier_league()
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a, "20.00")
        self.mgr_b = _manager(self.user_b, "20.00")
        self.team_a = Team.objects.create(
            name="Arsenal Test",
            short_name="ATX",
            league=self.league,
            manager=self.user_a,
        )
        self.team_b = Team.objects.create(
            name="Chelsea Test",
            short_name="CTX",
            league=self.league,
            manager=self.user_b,
        )
        self.scorer = Player.objects.create(
            name="Weekly Striker",
            position="ST",
            overall=84,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        self.maker = Player.objects.create(
            name="Weekly Maker",
            position="CM",
            overall=82,
            mgl_team=self.team_a,
            is_free_agent=False,
        )
        week = mgl_week_start(timezone.localdate() - timedelta(days=7))
        kickoff = timezone.make_aware(
            datetime.combine(week + timedelta(days=1), datetime.min.time())
        )
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=2,
            scheduled_at=kickoff,
            is_released=True,
            status="COMPLETED",
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.APPROVED,
            opponent_response=ApprovalStatus.APPROVED,
        )
        home = TeamMatchStats.objects.create(
            submission=submission, team=self.team_a, goals=3
        )
        TeamMatchStats.objects.create(submission=submission, team=self.team_b, goals=0)
        GoalEvent.objects.create(team_stats=home, player=self.scorer)
        GoalEvent.objects.create(team_stats=home, player=self.scorer)
        AssistEvent.objects.create(team_stats=home, player=self.maker)
        self.week_start = week

    def test_weekly_awards_pay_once(self):
        first = run_weekly_awards(week_start=self.week_start)
        self.assertTrue(first.completed)
        self.mgr_a.refresh_from_db()
        self.mgr_b.refresh_from_db()
        self.assertGreaterEqual(self.mgr_a.tokens, Decimal("21.70"))
        self.assertEqual(self.mgr_b.tokens, Decimal("20.00"))
        self.assertTrue(
            RewardTransaction.objects.filter(
                manager=self.mgr_a,
                category="GOALS",
                reference=f"goals:{self.week_start.isoformat()}",
            ).exists()
        )
        self.assertTrue(
            RewardTransaction.objects.filter(
                manager=self.mgr_a,
                category="ASSISTS",
                reference=f"assists:{self.week_start.isoformat()}",
            ).exists()
        )
        self.assertTrue(
            RewardTransaction.objects.filter(
                manager=self.mgr_a,
                category="MOTW",
                reference=f"motw:{self.week_start.isoformat()}",
            ).exists()
        )
        totw_pay = RewardTransaction.objects.filter(
            manager=self.mgr_a, category="TOTW"
        ).count()
        self.assertGreaterEqual(totw_pay, 1)
        tokens_after = self.mgr_a.tokens
        second = run_weekly_awards(week_start=self.week_start)
        self.assertEqual(second.id, first.id)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, tokens_after)
        self.assertEqual(
            WeeklyAwardBatch.objects.filter(week_start=self.week_start).count(), 1
        )
