from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from leagues.services import ensure_premier_league
from managers.models import ManagerApplication
from mgl.admin import approve_match_submission
from mgl.fixtures_schedule import (
    FIXTURES_PER_LEAGUE,
    GAMES_PER_TEAM,
    TEAMS_PER_LEAGUE,
    ensure_round_robin_fixtures,
    pair_key,
)
from mgl.models import (
    ApprovalStatus,
    AssistEvent,
    DefenderRating,
    Fixture,
    GKSave,
    GoalEvent,
    MatchSubmission,
)
from mgl.standings import build_league_table
from players.models import Player
from teams.models import Team


def _manager(user, display, tag):
    return ManagerApplication.objects.create(
        user=user,
        display_name=display,
        gamertag=tag,
        status=ManagerApplication.APPROVED,
        tokens=Decimal("20.00"),
    )


class DropdownStyleTests(TestCase):
    def test_every_nav_item_uses_the_league_dropdown_typeface(self):
        css = (Path(settings.BASE_DIR) / "core/static/core/css/mgl.css").read_text()
        block = css.split(".mgl-nav-item {", 1)[1].split("}", 1)[0]
        self.assertIn("font-family: var(--font-body);", block)
        self.assertIn("font-style: italic;", block)
        self.assertIn("font-size: 13px;", block)
        self.assertIn("text-transform: none;", block)
        sub = css.split(".mgl-nav-item--sub {", 1)[1].split("}", 1)[0]
        self.assertNotIn("font-family", sub)
        self.assertIn("padding-left: 28px;", sub)

    def test_dropdown_item_labels_use_league_title_case(self):
        from mgl.nav import NAV_DROPDOWNS, SIGNED_IN_NAV_DROPDOWNS

        for source in (NAV_DROPDOWNS, SIGNED_IN_NAV_DROPDOWNS):
            for menu in source:
                for item in menu["items"]:
                    label = item["label"]
                    self.assertNotEqual(label, label.upper(), label)

    def test_homepage_dropdown_items_share_one_class(self):
        response = Client(HTTP_HOST="127.0.0.1").get("/")
        html = response.content.decode()
        self.assertIn("mgl-nav-item--sub", html)
        self.assertGreater(html.count('class="mgl-nav-item'), 6)
        self.assertNotIn("WAITING ROOM", html)
        self.assertNotIn("/stats/compare/", html)


class LeagueStatsPageTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_three_league_stats_pages_load(self):
        for slug, heading in (
            ("premier-league", "PREMIER LEAGUE STATS"),
            ("championship", "CHAMPIONSHIP STATS"),
            ("league-one", "LEAGUE ONE STATS"),
        ):
            response = self.client.get(reverse("league_stats", kwargs={"slug": slug}))
            self.assertEqual(response.status_code, 200, slug)
            self.assertContains(response, heading)
            self.assertContains(response, "TOP GOAL SCORERS")
            self.assertContains(response, "TOP ASSISTS")
            self.assertContains(response, "TOP DEFENDERS")
            self.assertContains(response, "TOP GOALKEEPERS")
            self.assertContains(response, "NO STATISTICS AVAILABLE YET.")


class MatchSubmitAndApprovalTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="127.0.0.1")
        self.league = ensure_premier_league()
        self.home_user = User.objects.create_user(
            username="homemgr", password="test-pass-123"
        )
        self.away_user = User.objects.create_user(
            username="awaymgr", password="test-pass-123"
        )
        self.other_user = User.objects.create_user(
            username="othermgr", password="test-pass-123"
        )
        self.owner = User.objects.create_user(
            username="owner", password="test-pass-123", role=User.OWNER
        )
        _manager(self.home_user, "Home Mgr", "HMGR")
        _manager(self.away_user, "Away Mgr", "AMGR")
        _manager(self.other_user, "Other Mgr", "OMGR")
        self.home = Team.objects.create(
            name="Submit Home",
            short_name="SHM",
            league=self.league,
            manager=self.home_user,
        )
        self.away = Team.objects.create(
            name="Submit Away",
            short_name="SAW",
            league=self.league,
            manager=self.away_user,
        )
        self.other = Team.objects.create(
            name="Submit Other",
            short_name="SOT",
            league=self.league,
            manager=self.other_user,
        )
        self.home_st = Player.objects.create(
            name="Home Striker", position="ST", overall=80, mgl_team=self.home
        )
        self.home_cm = Player.objects.create(
            name="Home Mid", position="CM", overall=78, mgl_team=self.home
        )
        self.home_cb = Player.objects.create(
            name="Home Centre Back", position="CB", overall=76, mgl_team=self.home
        )
        self.home_gk = Player.objects.create(
            name="Home Keeper", position="GK", overall=75, mgl_team=self.home
        )
        self.away_st = Player.objects.create(
            name="Away Striker", position="ST", overall=79, mgl_team=self.away
        )
        self.away_cb = Player.objects.create(
            name="Away Centre Back", position="CB", overall=74, mgl_team=self.away
        )
        self.away_gk = Player.objects.create(
            name="Away Keeper", position="GK", overall=73, mgl_team=self.away
        )
        self.fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.home,
            away_team=self.away,
            matchweek=1,
            is_released=True,
            status="SCHEDULED",
        )
        self.other_fixture = Fixture.objects.create(
            league=self.league,
            home_team=self.other,
            away_team=self.away,
            matchweek=2,
            is_released=True,
            status="SCHEDULED",
        )

    def _payload(self, **extra):
        data = {
            "home_goals": "2",
            "away_goals": "1",
            "home_shots": "8",
            "away_shots": "5",
            "home_possession": "55",
            "away_possession": "45",
            "home_yellow_cards": "1",
            "away_yellow_cards": "0",
            "home_red_cards": "0",
            "away_red_cards": "0",
            "home_goal_1": str(self.home_st.id),
            "home_goal_2": str(self.home_st.id),
            "home_assist_1": str(self.home_cm.id),
            "home_assist_2": "",
            "away_goal_1": str(self.away_st.id),
            "away_assist_1": "",
            f"home_def_{self.home_cb.id}": "7.4",
            f"away_def_{self.away_cb.id}": "6.7",
            f"home_save_{self.home_gk.id}": "4",
            f"away_save_{self.away_gk.id}": "6",
        }
        data.update(extra)
        return data

    def test_manager_cannot_submit_another_club_fixture(self):
        self.client.login(username="homemgr", password="test-pass-123")
        url = reverse("submit_match", args=[self.other_fixture.id])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.post(url, self._payload())
        self.assertFalse(
            MatchSubmission.objects.filter(fixture=self.other_fixture).exists()
        )

    def test_form_generates_club_restricted_goal_and_assist_fields(self):
        self.client.login(username="homemgr", password="test-pass-123")
        page = self.client.get(reverse("submit_match", args=[self.fixture.id]))
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("mgl-match-submit.js", html)
        self.assertIn("js-goal-slots", html)
        self.assertIn("js-assist-slots", html)
        self.assertIn('name="home_goals"', html)
        self.assertIn('name="away_goals"', html)
        home_html = html.split('data-prefix="home"', 1)[1].split('data-prefix="away"', 1)[0]
        away_html = html.split('data-prefix="away"', 1)[1]
        home_select = home_html.split('class="js-player-options"', 1)[1].split("</select>", 1)[0]
        away_select = away_html.split('class="js-player-options"', 1)[1].split("</select>", 1)[0]
        self.assertIn(f'value="{self.home_st.id}"', home_select)
        self.assertIn(f'value="{self.home_cm.id}"', home_select)
        self.assertNotIn(f'value="{self.away_st.id}"', home_select)
        self.assertIn(f'value="{self.away_st.id}"', away_select)
        self.assertNotIn(f'value="{self.home_st.id}"', away_select)
        self.assertContains(page, f'name="home_def_{self.home_cb.id}"')
        self.assertContains(page, 'step="0.1"')
        self.assertContains(page, f'name="home_save_{self.home_gk.id}"')
        self.assertNotContains(page, f'name="home_def_{self.home_st.id}"')
        self.assertNotContains(page, f'name="home_save_{self.home_st.id}"')

    def test_players_must_belong_to_the_scoring_club(self):
        self.client.login(username="homemgr", password="test-pass-123")
        self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            self._payload(home_goal_1=str(self.away_st.id)),
        )
        self.assertFalse(MatchSubmission.objects.exists())

    def test_defender_ratings_reject_values_outside_0_to_10(self):
        self.client.login(username="homemgr", password="test-pass-123")
        url = reverse("submit_match", args=[self.fixture.id])
        for bad in ("10.1", "-0.1", "eleven"):
            MatchSubmission.objects.all().delete()
            self.client.post(url, self._payload(**{f"home_def_{self.home_cb.id}": bad}))
            self.assertFalse(MatchSubmission.objects.exists(), bad)

    def test_pending_result_does_not_update_official_statistics(self):
        self.client.login(username="homemgr", password="test-pass-123")
        response = self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            self._payload(),
            follow=True,
        )
        self.assertContains(response, "unofficial until approved")
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        self.assertEqual(submission.status, ApprovalStatus.PENDING)
        self.assertEqual(GoalEvent.objects.count(), 3)
        self.assertEqual(AssistEvent.objects.count(), 1)
        self.assertEqual(DefenderRating.objects.get(player=self.home_cb).rating, Decimal("7.4"))
        self.assertEqual(GKSave.objects.get(player=self.home_gk).saves, 4)
        stats = self.client.get(
            reverse("league_stats", kwargs={"slug": "premier-league"})
        )
        self.assertNotContains(stats, "Home Striker")
        self.assertNotContains(stats, "Home Keeper")
        self.home_st.refresh_from_db()
        self.assertEqual(self.home_st.goals, 0)
        table = build_league_table(self.league)
        home_row = next(row for row in table if row["team"].id == self.home.id)
        self.assertEqual(home_row["played"], 0)
        self.assertEqual(home_row["points"], 0)

    def test_approval_publishes_league_statistics(self):
        self.client.login(username="homemgr", password="test-pass-123")
        self.client.post(
            reverse("submit_match", args=[self.fixture.id]),
            self._payload(),
        )
        submission = MatchSubmission.objects.get(fixture=self.fixture)
        ok, _ = approve_match_submission(submission, self.owner)
        self.assertTrue(ok)
        self.home_st.refresh_from_db()
        self.assertEqual(self.home_st.goals, 2)
        self.home_cm.refresh_from_db()
        self.assertEqual(self.home_cm.assists, 1)
        pl = self.client.get(reverse("league_stats", kwargs={"slug": "premier-league"}))
        self.assertContains(pl, "Home Striker")
        self.assertContains(pl, "Home Mid")
        self.assertContains(pl, "Home Centre Back")
        self.assertContains(pl, "Home Keeper")
        self.assertContains(pl, "7.4")
        championship = self.client.get(
            reverse("league_stats", kwargs={"slug": "championship"})
        )
        self.assertNotContains(championship, "Home Striker")
        table = build_league_table(self.league)
        home_row = next(row for row in table if row["team"].id == self.home.id)
        self.assertEqual(home_row["played"], 1)
        self.assertEqual(home_row["points"], 3)
        self.assertEqual(home_row["gf"], 2)


class RoundRobinFixtureTests(TestCase):
    def test_fourteen_team_league_gets_91_unique_fixtures(self):
        league = League.objects.create(
            name="Round Robin Test",
            short_name="RRT",
            season="1",
            is_active=True,
        )
        teams = [
            Team.objects.create(
                name=f"RR Club {index:02d}",
                short_name=f"R{index:02d}",
                league=league,
            )
            for index in range(TEAMS_PER_LEAGUE)
        ]
        first = ensure_round_robin_fixtures(league)
        self.assertEqual(first["created"], FIXTURES_PER_LEAGUE)
        self.assertEqual(first["total"], FIXTURES_PER_LEAGUE)
        second = ensure_round_robin_fixtures(league)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped_existing"], FIXTURES_PER_LEAGUE)
        self.assertEqual(
            Fixture.objects.filter(league=league).count(), FIXTURES_PER_LEAGUE
        )
        pairs = [
            pair_key(home_id, away_id)
            for home_id, away_id in Fixture.objects.filter(league=league).values_list(
                "home_team_id", "away_team_id"
            )
        ]
        self.assertEqual(len(pairs), FIXTURES_PER_LEAGUE)
        self.assertEqual(len(set(pairs)), FIXTURES_PER_LEAGUE)
        for team in teams:
            played = Fixture.objects.filter(league=league).filter(
                Q(home_team=team) | Q(away_team=team)
            ).count()
            self.assertEqual(played, GAMES_PER_TEAM, team.name)
        self.assertTrue(
            all(row.lineup_deadline is None for row in Fixture.objects.filter(league=league))
        )

    def test_does_not_invent_fixtures_without_fourteen_clubs(self):
        league = League.objects.create(
            name="Thin Division",
            short_name="THN",
            season="1",
            is_active=True,
        )
        Team.objects.create(name="Only Club", short_name="ONL", league=league)
        report = ensure_round_robin_fixtures(league)
        self.assertEqual(report["created"], 0)
        self.assertIn("need 14", report["reason"])
        self.assertEqual(Fixture.objects.filter(league=league).count(), 0)
