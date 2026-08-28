from django.test import TestCase

from mgl.starting_pool import (
    CLUB_COUNT,
    NEEDED_BY_POSITION,
    PLAYERS_PER_CLUB,
    SHAPE_COUNTS,
    PoolPlayer,
    build_starting_pool,
    format_plan_report,
)


def _grouped_pool(extra=4, overall=67):
    grouped = {}
    next_id = 1
    for pos, needed in NEEDED_BY_POSITION.items():
        grouped[pos] = []
        for index in range(needed + extra):
            grouped[pos].append(
                PoolPlayer(
                    id=next_id,
                    fc27_id=str(100000 + next_id),
                    name=f"{pos} {index}",
                    position=pos,
                    overall=overall,
                )
            )
            next_id += 1
    return grouped


def _mixed_pool():
    grouped = {}
    next_id = 1
    for pos, needed in NEEDED_BY_POSITION.items():
        grouped[pos] = []
        count = needed + 8
        for index in range(count):
            overall = 64 + (index % 7)
            grouped[pos].append(
                PoolPlayer(
                    id=next_id,
                    fc27_id=str(200000 + next_id),
                    name=f"{pos}-{index}",
                    position=pos,
                    overall=overall,
                )
            )
            next_id += 1
    return grouped


class StartingAuctionPoolTests(TestCase):
    def test_identical_ovr_pool_is_exactly_equal(self):
        plan = build_starting_pool(_grouped_pool(), seed=20260828, max_attempts=20)
        self.assertTrue(plan.exact, plan.notes)
        selected = plan.selected
        self.assertEqual(len(selected), 364)
        self.assertEqual(len({player.id for player in selected}), 364)
        self.assertEqual(len({player.fc27_id for player in selected}), 364)
        self.assertEqual(min(player.overall for player in selected), 67)
        self.assertEqual(max(player.overall for player in selected), 67)
        totals = {squad.total_ovr for squad in plan.squads}
        self.assertEqual(totals, {26 * 67})
        self.assertEqual(len(plan.squads), CLUB_COUNT)
        for squad in plan.squads:
            self.assertEqual(len(squad.players), PLAYERS_PER_CLUB)
            self.assertEqual(squad.position_counts(), SHAPE_COUNTS)

    def test_mixed_ovr_pool_equalizes_without_changing_ratings(self):
        grouped = _mixed_pool()
        original = {
            player.id: player.overall
            for group in grouped.values()
            for player in group
        }
        plan = build_starting_pool(grouped, seed=26, max_attempts=80)
        self.assertTrue(plan.exact, plan.notes)
        selected = plan.selected
        self.assertEqual(len(selected), 364)
        self.assertEqual(len({player.fc27_id for player in selected}), 364)
        self.assertGreaterEqual(min(player.overall for player in selected), 64)
        self.assertLessEqual(max(player.overall for player in selected), 70)
        totals = [squad.total_ovr for squad in plan.squads]
        self.assertEqual(len(set(totals)), 1)
        for player in selected:
            self.assertEqual(player.overall, original[player.id])
        report = format_plan_report(plan)
        self.assertIn("Total selected = 364", report)
        self.assertIn("Duplicates = 0", report)
        self.assertIn("Exact equal totals: True", report)

    def test_short_pool_does_not_invent_players(self):
        grouped = _grouped_pool()
        grouped["LW"] = grouped["LW"][:10]
        plan = build_starting_pool(grouped, seed=1, max_attempts=5)
        self.assertFalse(plan.exact)
        self.assertEqual(plan.squads, [])
        self.assertTrue(any("SHORT" in format_plan_report(plan) or "short" in note.lower() for note in plan.notes))
