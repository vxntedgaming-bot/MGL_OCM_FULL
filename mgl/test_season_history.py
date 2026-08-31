from datetime import date
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import (
    ApprovalStatus,
    AssistEvent,
    Fixture,
    GoalEvent,
    HistoricalSeason,
    MatchSubmission,
    SeasonTableRow,
    TeamMatchStats,
)
from mgl.season_history import current_season_number, finalise_season, start_next_season
from mgl.standings import build_league_table, build_live_league_table
from players.models import Player
from teams.models import Team


def _user(username, role=User.MANAGER):
    return User.objects.create_user(username=username, password="test-pass-123", role=role)


def _manager(user, name=None):
    return ManagerApplication.objects.create(
        user=user,
        display_name=name or user.username.title(),
        gamertag=user.username[:8].upper(),
        status=ManagerApplication.APPROVED,
        tokens=Decimal("40.00"),
    )


class SeasonHistoryTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.owner = _user("hist-owner", User.OWNER)
        self.admin = _user("hist-admin", User.ADMIN)
        self.manager_user = _user("hist-manager")
        self.mgr = _manager(self.manager_user, "Hist Manager")
        self.home = Team.objects.create(
            name="History Home", short_name="HHM", league=self.league, manager=self.manager_user
        )
        self.away = Team.objects.create(
            name="History Away", short_name="HAW", league=self.league
        )
        self.striker = Player.objects.create(
            name="History Striker", position="ST", overall=82, mgl_team=self.home, age=22
        )
        self.mid = Player.objects.create(
            name="History Mid", position="CM", overall=78, mgl_team=self.home, age=27
        )

    def _approved_match(self, home, away, home_goals, away_goals, *, scorer=None, assister=None, season=1, week=1):
        fixture = Fixture.objects.create(
            league=self.league,
            home_team=home,
            away_team=away,
            matchweek=week,
            is_released=True,
            status="COMPLETED",
            season_number=season,
        )
        submission = MatchSubmission.objects.create(
            fixture=fixture,
            status=ApprovalStatus.APPROVED,
        )
        home_stats = TeamMatchStats.objects.create(
            submission=submission, team=home, goals=home_goals
        )
        TeamMatchStats.objects.create(submission=submission, team=away, goals=away_goals)
        if scorer:
            for _ in range(home_goals):
                GoalEvent.objects.create(team_stats=home_stats, player=scorer)
        if assister:
            AssistEvent.objects.create(team_stats=home_stats, player=assister)
        return fixture

    def test_public_history_uses_active_season_and_empty_awards(self):
        page = self.client.get(reverse("historical_tables"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "SEASON 1")
        self.assertContains(page, "ACTIVE SEASON")
        self.assertContains(page, "To be recorded")
        self.assertContains(page, "NOT YET RECORDED")
        self.assertContains(page, reverse("leagues_page"))
        self.assertNotContains(page, "SEASON 2")

    def test_season_selector_loads_selected_season(self):
        page = self.client.get(reverse("historical_tables"), {"season": "1"})
        self.assertContains(page, "SEASON 1")
        self.assertContains(page, 'href="?season=1"')

    def test_manager_cannot_edit_history(self):
        self.client.login(username="hist-manager", password="test-pass-123")
        page = self.client.get(reverse("season_management"))
        self.assertEqual(page.status_code, 403)
        self.client.login(username="hist-manager", password="test-pass-123")
        posted = self.client.post(
            reverse("season_management"),
            {"action": "finalise", "season_id": "1"},
        )
        self.assertEqual(posted.status_code, 403)
        self.assertFalse(HistoricalSeason.objects.filter(status=HistoricalSeason.FINALIZED).exists())

    def test_owner_and_admin_can_open_season_management(self):
        for username in ("hist-owner", "hist-admin"):
            self.client.login(username=username, password="test-pass-123")
            page = self.client.get(reverse("season_management"))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "FINALISE SEASON")

    def test_finalise_creates_snapshot_from_approved_results_only(self):
        self._approved_match(self.home, self.away, 3, 0, scorer=self.striker, assister=self.mid, week=1)
        pending = Fixture.objects.create(
            league=self.league,
            home_team=self.away,
            away_team=self.home,
            matchweek=2,
            is_released=True,
            status="COMPLETED",
            season_number=1,
        )
        pending_sub = MatchSubmission.objects.create(
            fixture=pending, status=ApprovalStatus.PENDING
        )
        TeamMatchStats.objects.create(submission=pending_sub, team=self.away, goals=8)
        TeamMatchStats.objects.create(submission=pending_sub, team=self.home, goals=0)

        self.client.login(username="hist-owner", password="test-pass-123")
        response = self.client.post(
            reverse("season_management"),
            {
                "action": "finalise",
                "season_id": "1",
                "year_label": "2026",
                "start_date": "2026-08-01",
                "end_date": "2027-05-01",
                "cup_winner": str(self.away.id),
                "tots_formation": "4-2-3-1",
                "tots_ST": str(self.striker.id),
            },
        )
        self.assertEqual(response.status_code, 302)
        season = HistoricalSeason.objects.get(number=1)
        self.assertEqual(season.status, HistoricalSeason.FINALIZED)
        self.assertTrue(season.is_locked)
        self.assertEqual(season.league_winner_id, self.home.id)
        self.assertEqual(season.top_scorer_id, self.striker.id)
        self.assertEqual(season.top_scorer_goals, 3)
        self.assertEqual(season.top_assists_player_id, self.mid.id)
        self.assertEqual(season.cup_winner_id, self.away.id)
        self.assertEqual(season.games_played, 1)
        self.assertEqual(season.table_rows.get(position=1).team_id, self.home.id)
        self.assertEqual(season.table_rows.get(position=1).points, 3)
        self.assertEqual(season.tots_picks.get(slot="ST").player_id, self.striker.id)

        history = self.client.get(reverse("historical_tables"), {"season": "1"})
        self.assertContains(history, "History Home")
        self.assertContains(history, "History Striker")
        self.assertContains(history, "3 GOALS")
        self.assertContains(history, "4-2-3-1")
        self.assertContains(history, "COMPLETED")
        self.assertNotContains(history, "ACTIVE SEASON")

    def test_snapshot_does_not_change_when_next_season_starts(self):
        self._approved_match(self.home, self.away, 2, 0, scorer=self.striker, week=1)
        season = HistoricalSeason.objects.create(
            number=1, status=HistoricalSeason.ACTIVE, league=self.league
        )
        owner = self.owner
        finalise_season(season, owner)
        frozen_points = season.table_rows.get(position=1).points
        frozen_goals = season.top_scorer_goals
        self._approved_match(self.home, self.away, 5, 0, scorer=self.striker, week=2, season=1)
        season.refresh_from_db()
        self.assertEqual(season.table_rows.get(position=1).points, frozen_points)
        self.assertEqual(season.top_scorer_goals, frozen_goals)

        next_season = start_next_season(owner)
        self.assertEqual(next_season.number, 2)
        self.assertEqual(next_season.status, HistoricalSeason.ACTIVE)
        self.assertEqual(current_season_number(), 2)
        self._approved_match(self.away, self.home, 1, 0, week=1, season=2)
        live = build_live_league_table(self.league)
        away_row = next(row for row in live if row["team"].id == self.away.id)
        self.assertEqual(away_row["points"], 3)
        season.refresh_from_db()
        self.assertEqual(season.table_rows.get(position=1).team_id, self.home.id)
        self.assertEqual(season.table_rows.get(position=1).points, frozen_points)
        mixed = build_league_table(self.league)
        self.assertGreater(sum(row["played"] for row in mixed), away_row["played"])

        page = self.client.get(reverse("historical_tables"))
        self.assertContains(page, "SEASON 1")
        self.assertContains(page, "SEASON 2")
        self.assertContains(page, "VIEW SEASON")
        past = self.client.get(reverse("historical_tables"), {"season": "1"})
        self.assertContains(past, "History Home")
        self.assertContains(past, "COMPLETED")

    def test_admin_can_finalise_and_manager_cannot_start_next(self):
        self._approved_match(self.home, self.away, 1, 0, scorer=self.striker)
        self.client.login(username="hist-admin", password="test-pass-123")
        response = self.client.post(
            reverse("season_management"),
            {"action": "finalise", "season_id": "1", "tots_formation": "4-3-3"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(HistoricalSeason.objects.get(number=1).is_finalized)
        self.client.login(username="hist-manager", password="test-pass-123")
        blocked = self.client.post(
            reverse("season_management"),
            {"action": "start_next", "season_id": "1"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(HistoricalSeason.objects.filter(number=2).exists())
        self.client.login(username="hist-admin", password="test-pass-123")
        started = self.client.post(
            reverse("season_management") + "?season=1",
            {"action": "start_next", "season_id": "1"},
        )
        self.assertEqual(started.status_code, 302)
        self.assertTrue(HistoricalSeason.objects.filter(number=2, status=HistoricalSeason.ACTIVE).exists())

    def test_owner_can_unlock_locked_history_admin_cannot(self):
        season = HistoricalSeason.objects.create(
            number=1,
            status=HistoricalSeason.FINALIZED,
            is_locked=True,
            league=self.league,
            league_winner_name="History Home",
        )
        SeasonTableRow.objects.create(
            season=season,
            position=1,
            team=self.home,
            team_name="History Home",
            points=9,
        )
        self.client.login(username="hist-admin", password="test-pass-123")
        denied = self.client.post(
            reverse("season_management"),
            {"action": "unlock", "season_id": "1"},
        )
        self.assertEqual(denied.status_code, 302)
        season.refresh_from_db()
        self.assertTrue(season.is_locked)
        self.client.login(username="hist-owner", password="test-pass-123")
        allowed = self.client.post(
            reverse("season_management"),
            {"action": "unlock", "season_id": "1"},
        )
        self.assertEqual(allowed.status_code, 302)
        season.refresh_from_db()
        self.assertFalse(season.is_locked)
