"""Build a 14 × 26 balanced starting auction pool without writing Player rows.

Players are selected from the unused FC26 pool (no club, no live auction)
at OVR 64–70 with an exact position shape. Clubs receive identical total OVR.
This module never assigns players or creates auctions.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from teams.official_sl1 import OFFICIAL_SL1_CLUBS

SQUAD_SHAPE = (
    ("GK", 2),
    ("CB", 4),
    ("RB", 2),
    ("LB", 2),
    ("CDM", 2),
    ("CM", 2),
    ("CAM", 2),
    ("RM", 2),
    ("LM", 2),
    ("ST", 2),
    ("LW", 2),
    ("RW", 2),
)
SHAPE_COUNTS = dict(SQUAD_SHAPE)
POSITIONS = tuple(pos for pos, _count in SQUAD_SHAPE)
CLUB_COUNT = 14
PLAYERS_PER_CLUB = 26
MIN_OVR = 64
MAX_OVR = 70
NEEDED_BY_POSITION = {pos: count * CLUB_COUNT for pos, count in SQUAD_SHAPE}


@dataclass(frozen=True)
class PoolPlayer:
    id: int
    fc27_id: str
    name: str
    position: str
    overall: int


@dataclass
class ProposedSquad:
    club_name: str
    short_name: str
    players: list[PoolPlayer] = field(default_factory=list)

    @property
    def total_ovr(self):
        return sum(player.overall for player in self.players)

    @property
    def average_ovr(self):
        if not self.players:
            return 0.0
        return self.total_ovr / len(self.players)

    def position_counts(self):
        counts = {pos: 0 for pos in POSITIONS}
        for player in self.players:
            counts[player.position] = counts.get(player.position, 0) + 1
        return counts


@dataclass
class StartingPoolPlan:
    squads: list[ProposedSquad]
    seed: int
    attempts: int
    exact: bool
    closest_spread: int
    pool_available: dict
    notes: list[str] = field(default_factory=list)

    @property
    def selected(self):
        return [player for squad in self.squads for player in squad.players]


def pool_player_from_model(player):
    return PoolPlayer(
        id=player.id,
        fc27_id=str(player.fc27_id or ""),
        name=player.name,
        position=player.position,
        overall=int(player.overall),
    )


def eligible_queryset():
    """Unused 64–70 pool. Excludes real Free Agents (no-bid / club-release)."""
    from auctions.models import PlayerAuction
    from mgl.models import PlayerOwnershipHistory
    from mgl.player_state import live_auction_player_ids
    from players.models import Player

    qs = (
        Player.objects.filter(
            mgl_team__isnull=True,
            overall__gte=MIN_OVR,
            overall__lte=MAX_OVR,
            position__in=POSITIONS,
        ).exclude(id__in=live_auction_player_ids())
    )
    no_bid_ids = PlayerAuction.objects.filter(
        listing_kind=PlayerAuction.FREE_AGENT,
        status=PlayerAuction.ENDED,
        winning_bid=0,
    ).values_list("player_id", flat=True)
    released_ids = PlayerOwnershipHistory.objects.filter(
        player__mgl_team__isnull=True,
        player__is_free_agent=True,
    ).values_list("player_id", flat=True)
    return qs.exclude(id__in=no_bid_ids).exclude(id__in=released_ids)


def load_eligible_players(queryset=None):
    queryset = queryset if queryset is not None else eligible_queryset()
    grouped = {pos: [] for pos in POSITIONS}
    for player in queryset.only("id", "fc27_id", "name", "position", "overall"):
        if player.position in grouped:
            grouped[player.position].append(pool_player_from_model(player))
    return grouped


def availability_report(grouped):
    report = {}
    for pos, needed in NEEDED_BY_POSITION.items():
        have = len(grouped.get(pos, []))
        report[pos] = {"have": have, "need": needed, "ok": have >= needed}
    return report


def _total(players):
    return sum(player.overall for player in players)


def _make_sum_divisible(selected, unused, modulus=CLUB_COUNT):
    remainder = _total([player for group in selected.values() for player in group]) % modulus
    if remainder == 0:
        return True
    need = (-remainder) % modulus
    for pos in POSITIONS:
        chosen = selected[pos]
        extras = unused[pos]
        for index, current in enumerate(chosen):
            for extra_index, candidate in enumerate(extras):
                delta = (candidate.overall - current.overall) % modulus
                if delta == need:
                    chosen[index] = candidate
                    extras[extra_index] = current
                    return True
    return False


def _snake_deal(selected):
    teams = [[] for _ in range(CLUB_COUNT)]
    for pos, each in SQUAD_SHAPE:
        group = sorted(selected[pos], key=lambda player: (-player.overall, player.id))
        order = list(range(CLUB_COUNT))
        cursor = 0
        for player in group:
            teams[order[cursor]].append(player)
            cursor += 1
            if cursor == CLUB_COUNT:
                order.reverse()
                cursor = 0
    return teams


def _totals(teams):
    return [_total(team) for team in teams]


def _swap(team_a, team_b, player_a, player_b):
    team_a[team_a.index(player_a)] = player_b
    team_b[team_b.index(player_b)] = player_a


def _equalize(teams, target, rounds=25000):
    for _ in range(rounds):
        totals = _totals(teams)
        if all(value == target for value in totals):
            return True
        high = max(range(CLUB_COUNT), key=lambda index: (totals[index], index))
        low = min(range(CLUB_COUNT), key=lambda index: (totals[index], -index))
        gap = totals[high] - totals[low]
        if gap == 0:
            return True
        improved = False
        best = None
        best_score = abs(totals[high] - target) + abs(totals[low] - target)
        for pos, _each in SQUAD_SHAPE:
            high_pos = [player for player in teams[high] if player.position == pos]
            low_pos = [player for player in teams[low] if player.position == pos]
            for left in high_pos:
                for right in low_pos:
                    delta = left.overall - right.overall
                    if delta <= 0:
                        continue
                    new_high = totals[high] - delta
                    new_low = totals[low] + delta
                    score = abs(new_high - target) + abs(new_low - target)
                    if score < best_score:
                        best_score = score
                        best = (left, right, delta)
        if best is not None:
            left, right, _delta = best
            _swap(teams[high], teams[low], left, right)
            improved = True
        if not improved:
            # Try any pair of clubs that are off target.
            moved = False
            for i in range(CLUB_COUNT):
                if totals[i] <= target:
                    continue
                for j in range(CLUB_COUNT):
                    if totals[j] >= target:
                        continue
                    for pos, _each in SQUAD_SHAPE:
                        i_pos = [player for player in teams[i] if player.position == pos]
                        j_pos = [player for player in teams[j] if player.position == pos]
                        for left in i_pos:
                            for right in j_pos:
                                delta = left.overall - right.overall
                                if delta <= 0:
                                    continue
                                if totals[i] - delta >= target - 2 and totals[j] + delta <= target + 2:
                                    _swap(teams[i], teams[j], left, right)
                                    moved = True
                                    break
                            if moved:
                                break
                        if moved:
                            break
                    if moved:
                        break
                if moved:
                    break
            if not moved:
                return all(value == target for value in _totals(teams))
    return all(value == target for value in _totals(teams))


def _replace_from_unused(teams, unused, target):
    totals = _totals(teams)
    if all(value == target for value in totals):
        return True
    for index, total in enumerate(totals):
        need = target - total
        if need == 0:
            continue
        for pos, _each in SQUAD_SHAPE:
            for player in list(teams[index]):
                if player.position != pos:
                    continue
                for extra_index, candidate in enumerate(unused[pos]):
                    if candidate.overall - player.overall == need:
                        teams[index][teams[index].index(player)] = candidate
                        unused[pos][extra_index] = player
                        totals[index] = target
                        break
                if totals[index] == target:
                    break
    return all(value == target for value in _totals(teams))


def _attempt(grouped, rng):
    selected = {}
    unused = {}
    for pos, needed in NEEDED_BY_POSITION.items():
        pool = list(grouped[pos])
        rng.shuffle(pool)
        selected[pos] = pool[:needed]
        unused[pos] = pool[needed:]
    if not _make_sum_divisible(selected, unused):
        return None
    all_selected = [player for group in selected.values() for player in group]
    grand = _total(all_selected)
    if grand % CLUB_COUNT:
        return None
    target = grand // CLUB_COUNT
    teams = _snake_deal(selected)
    _equalize(teams, target)
    if not all(value == target for value in _totals(teams)):
        _replace_from_unused(teams, unused, target)
        _equalize(teams, target)
    return teams, target


def build_starting_pool(grouped=None, seed=None, max_attempts=80):
    grouped = grouped if grouped is not None else load_eligible_players()
    available = availability_report(grouped)
    notes = []
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    if any(not row["ok"] for row in available.values()):
        short = {pos: row for pos, row in available.items() if not row["ok"]}
        notes.append(f"Pool is short of required positions: {short}")
        return StartingPoolPlan(
            squads=[],
            seed=seed,
            attempts=0,
            exact=False,
            closest_spread=-1,
            pool_available=available,
            notes=notes,
        )

    rng = random.Random(seed)
    closest = None
    closest_spread = None
    for attempt in range(1, max_attempts + 1):
        result = _attempt(grouped, rng)
        if result is None:
            continue
        teams, target = result
        totals = _totals(teams)
        if all(value == target for value in totals):
            squads = [
                ProposedSquad(
                    club_name=name,
                    short_name=short,
                    players=sorted(
                        teams[index],
                        key=lambda player: (
                            POSITIONS.index(player.position),
                            -player.overall,
                            player.name,
                        ),
                    ),
                )
                for index, (name, short) in enumerate(OFFICIAL_SL1_CLUBS)
            ]
            plan = StartingPoolPlan(
                squads=squads,
                seed=seed,
                attempts=attempt,
                exact=True,
                closest_spread=0,
                pool_available=available,
                notes=notes,
            )
            plan.notes.extend(_validate_plan(plan))
            return plan
        spread = max(totals) - min(totals)
        if closest_spread is None or spread < closest_spread:
            closest_spread = spread
            closest = (teams, target, attempt)

    notes.append(
        "Exact equal totals were not found in the attempt budget. "
        "No production data was written."
    )
    squads = []
    if closest is not None:
        teams, _target, attempt = closest
        squads = [
            ProposedSquad(
                club_name=name,
                short_name=short,
                players=sorted(
                    teams[index],
                    key=lambda player: (POSITIONS.index(player.position), -player.overall, player.name),
                ),
            )
            for index, (name, short) in enumerate(OFFICIAL_SL1_CLUBS)
        ]
        notes.append(f"Closest spread after {attempt} attempt(s): {closest_spread} OVR.")
    return StartingPoolPlan(
        squads=squads,
        seed=seed,
        attempts=max_attempts,
        exact=False,
        closest_spread=closest_spread if closest_spread is not None else -1,
        pool_available=available,
        notes=notes,
    )


def _validate_plan(plan: StartingPoolPlan):
    problems = []
    selected = plan.selected
    if len(selected) != CLUB_COUNT * PLAYERS_PER_CLUB:
        problems.append(f"Selected {len(selected)}, expected {CLUB_COUNT * PLAYERS_PER_CLUB}.")
    ids = [player.id for player in selected]
    fc_ids = [player.fc27_id for player in selected]
    if len(set(ids)) != len(ids):
        problems.append("Duplicate player primary keys in the proposed pool.")
    if len(set(fc_ids)) != len(fc_ids):
        problems.append("Duplicate fc27_id values in the proposed pool.")
    ovrs = [player.overall for player in selected]
    if ovrs and (min(ovrs) < MIN_OVR or max(ovrs) > MAX_OVR):
        problems.append(f"OVR out of {MIN_OVR}–{MAX_OVR}: {min(ovrs)}–{max(ovrs)}.")
    totals = [squad.total_ovr for squad in plan.squads]
    if plan.exact and totals and len(set(totals)) != 1:
        problems.append(f"Squad totals are not identical: {totals}.")
    for squad in plan.squads:
        counts = squad.position_counts()
        if len(squad.players) != PLAYERS_PER_CLUB:
            problems.append(f"{squad.short_name} has {len(squad.players)} players.")
        for pos, needed in SHAPE_COUNTS.items():
            if counts.get(pos, 0) != needed:
                problems.append(
                    f"{squad.short_name} {pos}={counts.get(pos, 0)}, expected {needed}."
                )
    return problems


def format_plan_report(plan: StartingPoolPlan):
    lines = [
        "MGL STARTING AUCTION POOL — DRY RUN",
        "This is a proposed TARGET POOL. Players were not assigned and no auctions were created.",
        f"Seed: {plan.seed}",
        f"Attempts used: {plan.attempts}",
        f"Exact equal totals: {plan.exact}",
        "",
        "Position availability (unused 64–70 OVR pool):",
    ]
    for pos in POSITIONS:
        row = plan.pool_available[pos]
        lines.append(f"  {pos}: have {row['have']} / need {row['need']} {'OK' if row['ok'] else 'SHORT'}")
    lines.append("")
    selected = plan.selected
    if selected:
        lines.append(f"Total selected = {len(selected)}")
        lines.append(f"Unique selected ids = {len({player.id for player in selected})}")
        lines.append(f"Unique fc27_id = {len({player.fc27_id for player in selected})}")
        lines.append(
            f"Duplicates = {len(selected) - len({player.id for player in selected})}"
        )
        lines.append(f"Lowest OVR = {min(player.overall for player in selected)}")
        lines.append(f"Highest OVR = {max(player.overall for player in selected)}")
        lines.append("")
    for squad in plan.squads:
        lines.append(f"{squad.club_name} ({squad.short_name}):")
        lines.append(f"  Players: {len(squad.players)}")
        lines.append(f"  Total OVR: {squad.total_ovr}")
        lines.append(f"  Average OVR: {squad.average_ovr:.4f}")
        lines.append(f"  Shape: {squad.position_counts()}")
        for player in squad.players:
            lines.append(
                f"  {player.position:3}  {player.overall:2}  {player.name}  "
                f"fc27={player.fc27_id}  id={player.id}"
            )
        lines.append("")
    if plan.notes:
        lines.append("Notes:")
        lines.extend(f"  - {note}" for note in plan.notes)
    return "\n".join(lines)
