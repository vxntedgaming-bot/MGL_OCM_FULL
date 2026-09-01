from decimal import Decimal
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from leagues.models import League
from leagues.services import CHAMPIONSHIP_SHORT, LEAGUE_ONE_SHORT, PREMIER_SHORT, ensure_premier_league
from managers.models import ManagerApplication
from mgl.models import RewardTransaction, StartingSquadLock, StartingSquadProposal
from mgl.season1 import (
    APPLY_BLOCKED_REASON,
    CONFIRM_PHRASE,
    UFL_STARTER_CLUB_TOTAL,
    apply_season1_bootstrap,
    preview_season1_bootstrap,
    proposed_clubs,
)
from mgl.starting_squads import apply_starting_squads
from mgl.ufl_settings import UFL_SQUAD_SHAPE, effective_roster_limit, max_squad_size
from players.models import Player
from teams.models import Team
from teams.official_sl1 import OFFICIAL_SL1_SHORT_NAMES


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


class Season1BootstrapTests(TestCase):
    def setUp(self):
        self.owner = _user("s1-owner", User.OWNER)
        self.admin = _user("s1-admin", User.ADMIN)
        self.manager_user = _user("s1-mgr")
        self.manager = _manager(self.manager_user, "33.50")
        premier = ensure_premier_league()
        self.test_club = Team.objects.filter(league=premier).first()
        if self.test_club is None:
            self.test_club = Team.objects.create(
                name="Test United",
                short_name="TUN",
                league=premier,
                manager=self.manager_user,
            )
        else:
            self.test_club.manager = self.manager_user
            self.test_club.save(update_fields=["manager"])
        self.player = Player.objects.create(
            name="Identity Keep",
            fc27_id="fc-keep-1",
            position="ST",
            overall=67,
            mgl_team=self.test_club,
            is_free_agent=False,
        )
        self.unrelated = League.objects.create(name="MLS", short_name="MLS", season="1", is_active=False)
        self.kept = Team.objects.create(name="MLS Hold", short_name="MLH", league=self.unrelated)
        self.client = Client(HTTP_HOST="127.0.0.1")

    def test_preview_does_not_write(self):
        before_teams = list(Team.objects.order_by("id").values_list("id", "name", "manager_id"))
        before_players = list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "mgl_team_id"))
        tokens = self.manager.tokens
        report = preview_season1_bootstrap(seed=7)
        self.assertTrue(report["ok"])
        self.assertEqual(report["planned_total"], 38)
        self.assertEqual(report["planned_counts"][PREMIER_SHORT], 16)
        self.assertEqual(report["planned_counts"][CHAMPIONSHIP_SHORT], 14)
        self.assertEqual(report["planned_counts"][LEAGUE_ONE_SHORT], 8)
        self.assertTrue(report["apply_blocked"])
        self.assertGreaterEqual(report["players_to_unassign"], 1)
        self.assertEqual(
            list(Team.objects.order_by("id").values_list("id", "name", "manager_id")),
            before_teams,
        )
        self.assertEqual(
            list(Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "mgl_team_id")),
            before_players,
        )
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, tokens)
        self.assertFalse(RewardTransaction.objects.exists())

    def test_command_dry_run_and_apply_flag_are_safe(self):
        out = StringIO()
        call_command("ufl_season1_bootstrap", stdout=out)
        self.assertIn("PREVIEW", out.getvalue())
        self.assertIn("DRY RUN ONLY", out.getvalue())
        self.assertEqual(self.player.mgl_team_id, self.test_club.id)
        with self.assertRaises(CommandError):
            call_command("ufl_season1_bootstrap", apply=True, stdout=StringIO())
        self.player.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.test_club.id)

    def test_production_apply_remains_blocked(self):
        with self.assertRaisesMessage(ValueError, "blocked"):
            apply_season1_bootstrap(self.owner, confirm=True, seed=3, allow_apply=False)
        self.player.refresh_from_db()
        self.assertEqual(self.player.mgl_team_id, self.test_club.id)

    def test_isolated_apply_builds_38_clubs_and_preserves_identity(self):
        tokens = self.manager.tokens
        identity = (self.player.fc27_id, self.player.overall, self.player.name)
        result = apply_season1_bootstrap(self.owner, confirm=True, seed=11, allow_apply=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["created"], 38)
        self.assertEqual(Team.objects.filter(is_ufl_starter=True).count(), UFL_STARTER_CLUB_TOTAL)
        self.assertEqual(Team.objects.filter(is_ufl_starter=True, league__short_name=PREMIER_SHORT).count(), 16)
        self.assertEqual(Team.objects.filter(is_ufl_starter=True, league__short_name=CHAMPIONSHIP_SHORT).count(), 14)
        self.assertEqual(Team.objects.filter(is_ufl_starter=True, league__short_name=LEAGUE_ONE_SHORT).count(), 8)
        self.assertFalse(Team.objects.filter(is_ufl_starter=True, manager__isnull=False).exists())
        self.assertFalse(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).exists())
        self.assertTrue(Team.objects.filter(pk=self.kept.pk).exists())
        self.player.refresh_from_db()
        self.assertIsNone(self.player.mgl_team_id)
        self.assertFalse(self.player.is_free_agent)
        self.assertEqual((self.player.fc27_id, self.player.overall, self.player.name), identity)
        self.manager.refresh_from_db()
        self.assertEqual(self.manager.tokens, tokens)
        self.assertFalse(RewardTransaction.objects.exists())
        for team in Team.objects.filter(is_ufl_starter=True):
            self.assertEqual(team.players.count(), 0)
            self.assertEqual(effective_roster_limit(team), 30)

    def test_apply_requires_owner_and_confirm(self):
        with self.assertRaisesMessage(ValueError, "Only the Owner"):
            apply_season1_bootstrap(self.admin, confirm=True, allow_apply=True)
        with self.assertRaisesMessage(ValueError, "explicit confirmation"):
            apply_season1_bootstrap(self.owner, confirm=False, allow_apply=True)
        self.assertTrue(Team.objects.filter(pk=self.test_club.pk).exists())

    def test_random_seed_changes_club_names(self):
        first = [row["name"] for row in proposed_clubs(seed=1)]
        second = [row["name"] for row in proposed_clubs(seed=99)]
        self.assertEqual(len(first), 38)
        self.assertNotEqual(first, second)
        self.assertEqual([row["name"] for row in proposed_clubs(seed=1)], first)

    def test_legacy_paths_cannot_bypass(self):
        with self.assertRaisesMessage(ValueError, "retired"):
            apply_starting_squads(dry_run=False)
        with self.assertRaises(CommandError):
            call_command("generate_balanced_squads")
        with self.assertRaises(CommandError):
            call_command("apply_starting_squads", apply=True)

    def test_control_shows_preview_and_refuses_apply(self):
        self.client.login(username="s1-owner", password="test-pass-123")
        page = self.client.get(reverse("control_season_controls"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "38-CLUB STARTER STRUCTURE")
        self.assertContains(page, APPLY_BLOCKED_REASON)
        posted = self.client.post(
            reverse("control_season_controls"),
            {"action": "season1_bootstrap", "confirm_text": CONFIRM_PHRASE},
        )
        self.assertEqual(posted.status_code, 302)
        self.assertTrue(Team.objects.filter(pk=self.test_club.pk).exists())
        retired = self.client.post(
            reverse("control_season_controls"),
            {"action": "ensure_clubs", "confirm_text": "ENSURE CLUBS"},
        )
        self.assertEqual(retired.status_code, 302)
        self.assertEqual(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).count(), 14)

    def test_shape_and_roster_constants(self):
        self.assertEqual(sum(count for _pos, count in UFL_SQUAD_SHAPE), 30)
        self.assertEqual(max_squad_size(), 30)
        self.assertNotIn(("CB", 5), UFL_SQUAD_SHAPE)
