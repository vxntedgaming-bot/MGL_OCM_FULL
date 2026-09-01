from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from auctions.models import PlayerAuction
from leagues.services import ensure_premier_league
from mgl.models import PlayerOwnershipHistory
from mgl.player_state import market_counts
from mgl.starting_squads import (
    EXPECTED_ASSIGNED,
    PLAYERS_PER_CLUB,
    SHAPE,
    TARGET_AVERAGE_OVR,
    TARGET_TOTAL_OVR,
    allocation_integrity_errors,
    apply_starting_squads,
    load_allocation,
    selected_players,
    validate_applied_squads,
)
from players.models import Player
from teams.models import Team
from teams.official_sl1 import OFFICIAL_SL1_SHORT_NAMES


class ApprovedAllocationFileTests(TestCase):
    def test_allocation_file_is_exactly_balanced(self):
        allocation = load_allocation()
        self.assertEqual(allocation_integrity_errors(allocation), [])
        selected = selected_players(allocation)
        self.assertEqual(len(selected), EXPECTED_ASSIGNED)
        self.assertEqual(len({str(player["fc27_id"]) for player in selected}), EXPECTED_ASSIGNED)
        self.assertEqual(len(allocation["squads"]), 14)
        for squad in allocation["squads"]:
            self.assertEqual(len(squad["players"]), PLAYERS_PER_CLUB)
            total = sum(int(player["overall"]) for player in squad["players"])
            self.assertEqual(total, TARGET_TOTAL_OVR)
            self.assertEqual(round(total / PLAYERS_PER_CLUB, 4), TARGET_AVERAGE_OVR)


class StartingSquadAssignmentTests(TestCase):
    def setUp(self):
        ensure_premier_league()
        self.allocation = load_allocation()
        selected = selected_players(self.allocation)
        Player.objects.bulk_create(
            [
                Player(
                    name=item["name"],
                    fc27_id=str(item["fc27_id"]),
                    position=item["position"],
                    overall=int(item["overall"]),
                    is_free_agent=False,
                )
                for item in selected
            ],
            batch_size=100,
        )
        self.spare = Player.objects.create(
            name="Spare Unassigned",
            fc27_id="999999999",
            position="ST",
            overall=66,
            is_free_agent=False,
        )
        self.ovr_before = dict(
            Player.objects.exclude(fc27_id="").values_list("fc27_id", "overall")
        )

    def test_dry_run_does_not_assign(self):
        report = apply_starting_squads(self.allocation, dry_run=True)
        self.assertTrue(report["ok"], report.get("problems"))
        self.assertFalse(report.get("applied"))
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        self.assertEqual(Player.objects.filter(is_free_agent=True).count(), 0)
        self.assertEqual(PlayerOwnershipHistory.objects.count(), 0)
        self.assertEqual(PlayerAuction.objects.count(), 0)
        self.spare.refresh_from_db()
        self.assertIsNone(self.spare.mgl_team_id)
        self.assertFalse(self.spare.is_free_agent)

    def test_apply_write_path_is_fenced(self):
        from django.core.management import CommandError

        with self.assertRaisesMessage(ValueError, "retired"):
            apply_starting_squads(self.allocation, dry_run=False)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
        self.assertEqual(PlayerOwnershipHistory.objects.count(), 0)
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("apply_starting_squads", apply=True, stdout=out)
        self.assertEqual(Player.objects.filter(mgl_team__isnull=False).count(), 0)
