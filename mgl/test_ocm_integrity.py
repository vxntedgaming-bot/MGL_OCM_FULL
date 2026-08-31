from datetime import datetime, timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.match_official import unapprove_match_submission
from mgl.models import (
    ApprovalStatus,
    Fixture,
    GoalEvent,
    ManagerCareerStat,
    MatchSubmission,
    MonthlyAwardBatch,
    RewardTransaction,
    SiteChangeLog,
    TeamMatchStats,
    WeeklyAwardBatch,
)
from mgl.monthly_awards import approve_monthly_awards, run_monthly_awards
from mgl.standings import build_league_table
from mgl.weekly_awards import approve_weekly_awards, mgl_week_start, run_weekly_awards
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, tokens="20.00"):
    return ManagerApplication.objects.create(
        user=user,
        display_name=user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal(tokens),
    )


class OcmIntegrityTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("owner", User.OWNER)
        self.admin = _user("siteadmin", User.ADMIN)
        self.user_a = _user("kai")
        self.user_b = _user("rival")
        self.mgr_a = _manager(self.user_a)
        self.mgr_b = _manager(self.user_b)
        self.team_a = Team.objects.create(
            name="Integrity Home", short_name="IHM", league=self.league, manager=self.user_a
        )
        self.team_b = Team.objects.create(
            name="Integrity Away", short_name="IAW", league=self.league, manager=self.user_b
        )
        self.scorer = Player.objects.create(
            name="Integrity Striker", position="ST", overall=81, mgl_team=self.team_a
        )
        self.week_start = mgl_week_start(timezone.localdate() - timedelta(days=7))
        kickoff = timezone.make_aware(
            datetime.combine(self.week_start + timedelta(days=1), datetime.min.time())
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=3,
            scheduled_at=kickoff,
            is_released=True,
            status="SCHEDULED",
        )

    def _submit_and_confirm(self):
        self.client.login(username="kai", password="test-pass-123")
        self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            {
                "home_goals": "2",
                "away_goals": "0",
                "home_goal_1": str(self.scorer.id),
                "home_goal_2": str(self.scorer.id),
                "home_shots": "7",
                "away_shots": "2",
                "home_possession": "60",
                "away_possession": "40",
                "home_yellow_cards": "0",
                "away_yellow_cards": "0",
                "home_red_cards": "0",
                "away_red_cards": "0",
            },
        )
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        submission.opponent_response = ApprovalStatus.APPROVED
        submission.opponent_responded_by = self.user_b
        submission.save()
        return submission

    def _table_played(self, team):
        row = next(item for item in build_league_table(self.league) if item["team"].id == team.id)
        return row["played"], row["points"]

    def test_owner_override_approves_without_opponent_and_logs(self):
        self.client.login(username="kai", password="test-pass-123")
        self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            {
                "home_goals": "1",
                "away_goals": "0",
                "home_goal_1": str(self.scorer.id),
                "home_shots": "4",
                "away_shots": "1",
                "home_possession": "55",
                "away_possession": "45",
                "home_yellow_cards": "0",
                "away_yellow_cards": "0",
                "home_red_cards": "0",
                "away_red_cards": "0",
            },
        )
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.opponent_response, ApprovalStatus.PENDING)
        self.client.login(username="siteadmin", password="test-pass-123")
        blocked = self.client.post(
            reverse("control_approve_result", args=[submission.id]),
            {"override": "1"},
        )
        self.assertEqual(blocked.status_code, 302)
        submission.refresh_from_db()
        self.assertEqual(submission.status, ApprovalStatus.PENDING)
        self.client.login(username="owner", password="test-pass-123")
        self.client.post(
            reverse("control_approve_result", args=[submission.id]),
            {"override": "1"},
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, ApprovalStatus.APPROVED)
        self.assertTrue(submission.stats_applied)
        self.assertEqual(self._table_played(self.team_a), (1, 3))
        self.assertTrue(
            SiteChangeLog.objects.filter(action="match.approve", object_id=str(submission.pk)).exists()
        )
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, Decimal("21.00"))

    def test_official_result_rollback_reverses_stats_and_match_tokens(self):
        submission = self._submit_and_confirm()
        start_tokens = self.mgr_a.tokens
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        self.scorer.refresh_from_db()
        self.assertEqual(self.scorer.goals, 2)
        self.assertEqual(self._table_played(self.team_a), (1, 3))
        career = ManagerCareerStat.objects.get(manager=self.mgr_a)
        self.assertEqual(career.wins, 1)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens + Decimal("1.00"))
        credit = RewardTransaction.objects.get(
            manager=self.mgr_a,
            category="MATCH",
            reference=f"match:{self.fixture.id}:home",
            reversed_at__isnull=True,
        )
        self.assertEqual(credit.balance_before, start_tokens)
        self.assertEqual(credit.balance_after, start_tokens + Decimal("1.00"))
        ok, _ = unapprove_match_submission(submission, self.owner)
        self.assertTrue(ok)
        submission.refresh_from_db()
        self.scorer.refresh_from_db()
        self.fixture.refresh_from_db()
        career.refresh_from_db()
        self.assertEqual(submission.status, ApprovalStatus.REJECTED)
        self.assertFalse(submission.stats_applied)
        self.assertEqual(self.scorer.goals, 0)
        self.assertEqual(career.wins, 0)
        self.assertEqual(self.fixture.status, "SCHEDULED")
        self.assertEqual(self._table_played(self.team_a), (0, 0))
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens)
        credit.refresh_from_db()
        self.assertIsNotNone(credit.reversed_at)
        clawback = RewardTransaction.objects.get(reverses=credit)
        self.assertEqual(clawback.amount, Decimal("-1.00"))
        self.assertEqual(clawback.created_by, self.owner)
        self.assertEqual(clawback.balance_before, start_tokens + Decimal("1.00"))
        self.assertEqual(clawback.balance_after, start_tokens)
        self.assertTrue(SiteChangeLog.objects.filter(action="match.rollback").exists())
        self.assertEqual(
            RewardTransaction.objects.filter(
                manager=self.mgr_a, category="MATCH", reference=f"match:{self.fixture.id}:home"
            ).count(),
            1,
        )
        submission.status = ApprovalStatus.PENDING
        submission.save(update_fields=["status"])
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens + Decimal("1.00"))
        self.assertEqual(
            RewardTransaction.objects.filter(
                manager=self.mgr_a,
                category="MATCH",
                reference=f"match:{self.fixture.id}:home",
                reversed_at__isnull=True,
            ).count(),
            1,
        )

    def test_owner_token_adjust_writes_ledger_balances(self):
        self.client.login(username="owner", password="test-pass-123")
        before = self.mgr_a.tokens
        response = self.client.post(
            reverse("control_adjust_tokens"),
            {
                "manager_id": str(self.mgr_a.id),
                "amount": "2.50",
                "reason": "Owner correction",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, before + Decimal("2.50"))
        row = RewardTransaction.objects.get(manager=self.mgr_a, category="ADMIN")
        self.assertEqual(row.amount, Decimal("2.50"))
        self.assertEqual(row.balance_before, before)
        self.assertEqual(row.balance_after, before + Decimal("2.50"))
        self.assertEqual(row.created_by, self.owner)
        self.assertEqual(row.reason, "Owner correction")
        self.assertTrue(SiteChangeLog.objects.filter(action="token.adjust").exists())
        self.client.post(
            reverse("control_adjust_tokens"),
            {
                "manager_id": str(self.mgr_a.id),
                "amount": "-1.00",
                "reason": "Owner clawback",
            },
        )
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, before + Decimal("1.50"))
        debit = RewardTransaction.objects.filter(
            manager=self.mgr_a, category="ADMIN", reason="Owner clawback"
        ).get()
        self.assertEqual(debit.balance_before, before + Decimal("2.50"))
        self.assertEqual(debit.balance_after, before + Decimal("1.50"))
        tokens = self.client.get(reverse("control_tokens"))
        self.assertContains(tokens, "Owner correction")
        self.assertContains(tokens, "APPLY")
        scouting = self.client.get(reverse("control_scouting"))
        self.assertContains(scouting, "SCOUTING ACTIVITY")

    def test_weekly_awards_wait_for_admin_then_pay_once(self):
        second = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=4,
            scheduled_at=timezone.make_aware(
                datetime.combine(self.week_start + timedelta(days=3), datetime.min.time())
            ),
            is_released=True,
            status="COMPLETED",
        )
        for fixture, goals in ((self.fixture, 3), (second, 1)):
            submission = MatchSubmission.objects.create(
                fixture=fixture,
                submitted_by=self.user_a,
                status=ApprovalStatus.APPROVED,
                opponent_response=ApprovalStatus.APPROVED,
                stats_applied=True,
            )
            home = TeamMatchStats.objects.create(
                submission=submission, team=self.team_a, goals=goals
            )
            TeamMatchStats.objects.create(submission=submission, team=self.team_b, goals=0)
            for _ in range(goals):
                GoalEvent.objects.create(team_stats=home, player=self.scorer)
        start_tokens = self.mgr_a.tokens
        batch = run_weekly_awards(week_start=self.week_start)
        self.assertEqual(batch.status, WeeklyAwardBatch.PENDING_REVIEW)
        self.assertFalse(batch.completed)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens)
        approve_weekly_awards(batch, self.owner)
        batch.refresh_from_db()
        self.assertEqual(batch.status, WeeklyAwardBatch.APPROVED)
        self.assertTrue(batch.completed)
        self.mgr_a.refresh_from_db()
        self.assertGreater(self.mgr_a.tokens, start_tokens)
        paid = self.mgr_a.tokens
        approve_weekly_awards(batch, self.owner)
        run_weekly_awards(week_start=self.week_start)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, paid)
        self.assertEqual(
            RewardTransaction.objects.filter(
                manager=self.mgr_a, category="MOTW", reference=f"motw:{self.week_start.isoformat()}"
            ).count(),
            1,
        )

    def test_motw_requires_two_approved_matches(self):
        submission = MatchSubmission.objects.create(
            fixture=self.fixture,
            submitted_by=self.user_a,
            status=ApprovalStatus.APPROVED,
            opponent_response=ApprovalStatus.APPROVED,
        )
        home = TeamMatchStats.objects.create(submission=submission, team=self.team_a, goals=1)
        TeamMatchStats.objects.create(submission=submission, team=self.team_b, goals=0)
        GoalEvent.objects.create(team_stats=home, player=self.scorer)
        batch = run_weekly_awards(week_start=self.week_start)
        self.assertIsNone((batch.payload or {}).get("motw"))
        approve_weekly_awards(batch, self.owner)
        self.assertFalse(
            RewardTransaction.objects.filter(manager=self.mgr_a, category="MOTW").exists()
        )

    def test_monthly_awards_pay_once_after_review(self):
        month = self.week_start.replace(day=1)
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=8,
            scheduled_at=timezone.make_aware(datetime.combine(month + timedelta(days=2), datetime.min.time())),
            is_released=True,
            status="COMPLETED",
        )
        extra = Fixture.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            matchweek=9,
            scheduled_at=timezone.make_aware(datetime.combine(month + timedelta(days=5), datetime.min.time())),
            is_released=True,
            status="COMPLETED",
        )
        for item in (fixture, extra):
            submission = MatchSubmission.objects.create(
                fixture=item,
                submitted_by=self.user_a,
                status=ApprovalStatus.APPROVED,
                opponent_response=ApprovalStatus.APPROVED,
            )
            home = TeamMatchStats.objects.create(submission=submission, team=self.team_a, goals=2)
            TeamMatchStats.objects.create(submission=submission, team=self.team_b, goals=0)
            GoalEvent.objects.create(team_stats=home, player=self.scorer)
            GoalEvent.objects.create(team_stats=home, player=self.scorer)
        start_tokens = self.mgr_a.tokens
        batch = run_monthly_awards(month=month)
        self.assertEqual(batch.status, MonthlyAwardBatch.PENDING_REVIEW)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens)
        approve_monthly_awards(batch, self.owner)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens + Decimal("9.00"))
        approve_monthly_awards(batch, self.owner)
        self.mgr_a.refresh_from_db()
        self.assertEqual(self.mgr_a.tokens, start_tokens + Decimal("9.00"))
        self.assertEqual(
            RewardTransaction.objects.filter(
                manager=self.mgr_a, category="MOTM", reference=f"motm:{month.isoformat()}"
            ).count(),
            1,
        )
