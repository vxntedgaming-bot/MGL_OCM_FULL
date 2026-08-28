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

    def test_apply_assigns_14_balanced_squads(self):
        out = StringIO()
        call_command("apply_starting_squads", apply=True, stdout=out)
        after = validate_applied_squads()
        self.assertTrue(after["ok"], after.get("problems"))
        counts = market_counts()
        self.assertEqual(counts["club_players"], EXPECTED_ASSIGNED)
        self.assertEqual(counts["free_agents"], 0)
        self.assertEqual(counts["auctions"], 0)
        self.assertEqual(counts["unassigned"], 1)
        assigned_ids = list(
            Player.objects.filter(mgl_team__isnull=False).values_list("fc27_id", flat=True)
        )
        self.assertEqual(len(assigned_ids), EXPECTED_ASSIGNED)
        self.assertEqual(len(set(assigned_ids)), EXPECTED_ASSIGNED)
        self.assertEqual(PlayerAuction.objects.count(), 0)
        self.assertEqual(
            PlayerOwnershipHistory.objects.filter(source="INITIAL_SQUAD").count(),
            EXPECTED_ASSIGNED,
        )
        self.spare.refresh_from_db()
        self.assertIsNone(self.spare.mgl_team_id)
        self.assertFalse(self.spare.is_free_agent)
        for fc27_id, overall in self.ovr_before.items():
            self.assertEqual(Player.objects.get(fc27_id=fc27_id).overall, overall)

        for short in OFFICIAL_SL1_SHORT_NAMES:
            club = Team.objects.get(short_name=short)
            players = list(club.players.all())
            self.assertEqual(len(players), PLAYERS_PER_CLUB)
            total = sum(player.overall for player in players)
            self.assertEqual(total, TARGET_TOTAL_OVR)
            self.assertEqual(round(total / PLAYERS_PER_CLUB, 4), TARGET_AVERAGE_OVR)
            self.assertEqual(str(club.tokens), "50.00")
            shape = {}
            for player in players:
                shape[player.position] = shape.get(player.position, 0) + 1
            self.assertEqual(shape, SHAPE)
        repeat = apply_starting_squads(self.allocation, dry_run=True)
        self.assertFalse(repeat["ok"])
        self.assertTrue(any("already has players" in item for item in repeat["problems"]))
