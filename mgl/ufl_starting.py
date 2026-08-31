"""UFL starting-squad generator.

Generation writes a proposal snapshot only. It never assigns players, never
changes FC26 ratings or IDs, and never calls apply_starting_squads.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from mgl.player_state import (
    LIVE_LISTING_STATUSES,
    live_auction_player_ids,
    market_status,
    roster_occupancy,
)
from mgl.ufl_settings import (
    UFL_MAX_OVR,
    UFL_MIN_OVR,
    UFL_SQUAD_SHAPE,
    effective_roster_limit,
)

SQUAD_SHAPE = tuple(UFL_SQUAD_SHAPE)
SHAPE_COUNTS = dict(SQUAD_SHAPE)
POSITIONS = tuple(pos for pos, _count in SQUAD_SHAPE)
PLAYERS_PER_CLUB = sum(count for _pos, count in SQUAD_SHAPE)
MIN_OVR = UFL_MIN_OVR
MAX_OVR = UFL_MAX_OVR
DEFAULT_MAX_AVG_DIFF = Decimal("1.500")
MAX_ATTEMPTS = 80


@dataclass(frozen=True)
class ProposedPlayer:
    id: int
    fc27_id: str
    name: str
    position: str
    overall: int

    def as_dict(self):
        return {
            "id": self.id,
            "fc27_id": self.fc27_id,
            "name": self.name,
            "position": self.position,
            "overall": self.overall,
        }


@dataclass
class ProposedClubSquad:
    team_id: int
    club_name: str
    short_name: str
    players: list = field(default_factory=list)

    @property
    def total_ovr(self):
        return sum(player.overall for player in self.players)

    @property
    def average_ovr(self):
        if not self.players:
            return 0.0
        return self.total_ovr / len(self.players)

    @property
    def highest_ovr(self):
        return max((player.overall for player in self.players), default=0)

    @property
    def lowest_ovr(self):
        return min((player.overall for player in self.players), default=0)

    def position_counts(self):
        counts = {pos: 0 for pos in POSITIONS}
        for player in self.players:
            counts[player.position] = counts.get(player.position, 0) + 1
        return counts

    def by_position(self):
        grouped = {pos: [] for pos in POSITIONS}
        for player in self.players:
            grouped.setdefault(player.position, []).append(player)
        for pos in grouped:
            grouped[pos].sort(key=lambda item: (-item.overall, item.name, item.id))
        return grouped


def _blocked_listing_ids():
    from mgl.models import PlayerListing

    return PlayerListing.objects.filter(status__in=LIVE_LISTING_STATUSES).values_list(
        "player_id", flat=True
    )


def target_clubs():
    from teams.models import Team

    return list(Team.objects.select_related("league", "manager").order_by("league_id", "name", "id"))


def eligible_queryset(include_free_agents=False):
    from players.models import Player

    qs = Player.objects.filter(
        overall__gte=MIN_OVR,
        overall__lte=MAX_OVR,
        position__in=POSITIONS,
        mgl_team__isnull=True,
    ).exclude(id__in=live_auction_player_ids()).exclude(id__in=_blocked_listing_ids())
    if include_free_agents:
        return qs
    return qs.filter(is_free_agent=False)


def _from_model(player):
    return ProposedPlayer(
        id=player.id,
        fc27_id=str(player.fc27_id or ""),
        name=player.name,
        position=player.position,
        overall=int(player.overall or 0),
    )


def load_eligible_players(include_free_agents=False, queryset=None):
    queryset = queryset if queryset is not None else eligible_queryset(include_free_agents)
    grouped = {pos: [] for pos in POSITIONS}
    for player in queryset.only("id", "fc27_id", "name", "position", "overall"):
        if player.position in grouped:
            grouped[player.position].append(_from_model(player))
    return grouped


def availability_report(grouped, club_count):
    report = {}
    for pos, each in SQUAD_SHAPE:
        need = each * club_count
        have = len(grouped.get(pos, []))
        report[pos] = {"have": have, "need": need, "ok": have >= need}
    return report


def _total(players):
    return sum(player.overall for player in players)


def _snake_deal(selected, club_count):
    teams = [[] for _ in range(club_count)]
    for pos, _each in SQUAD_SHAPE:
        group = sorted(selected[pos], key=lambda player: (-player.overall, player.id))
        order = list(range(club_count))
        cursor = 0
        for player in group:
            teams[order[cursor]].append(player)
            cursor += 1
            if cursor == club_count:
                order.reverse()
                cursor = 0
    return teams


def _equalize(teams, rounds=20000):
    club_count = len(teams)
    if club_count < 2:
        return
    for _ in range(rounds):
        totals = [_total(team) for team in teams]
        high = max(range(club_count), key=lambda index: (totals[index], index))
        low = min(range(club_count), key=lambda index: (totals[index], -index))
        if totals[high] - totals[low] <= 1:
            return
        best = None
        best_gap = totals[high] - totals[low]
        for pos, _each in SQUAD_SHAPE:
            high_pos = [player for player in teams[high] if player.position == pos]
            low_pos = [player for player in teams[low] if player.position == pos]
            for left in high_pos:
                for right in low_pos:
                    delta = left.overall - right.overall
                    if delta <= 0:
                        continue
                    new_gap = abs((totals[high] - delta) - (totals[low] + delta))
                    if new_gap < best_gap:
                        best_gap = new_gap
                        best = (left, right)
        if best is None:
            return
        left, right = best
        teams[high][teams[high].index(left)] = right
        teams[low][teams[low].index(right)] = left


def _attempt(grouped, rng, club_count):
    selected = {}
    for pos, each in SQUAD_SHAPE:
        needed = each * club_count
        pool = list(grouped[pos])
        rng.shuffle(pool)
        if len(pool) < needed:
            return None
        selected[pos] = pool[:needed]
    teams = _snake_deal(selected, club_count)
    _equalize(teams)
    return teams


def _sort_squad(players):
    return sorted(
        players,
        key=lambda player: (POSITIONS.index(player.position), -player.overall, player.name, player.id),
    )


def generate_allocation(
    clubs=None,
    seed=None,
    include_free_agents=False,
    max_attempts=MAX_ATTEMPTS,
    grouped=None,
):
    clubs = list(clubs if clubs is not None else target_clubs())
    club_count = len(clubs)
    grouped = grouped if grouped is not None else load_eligible_players(include_free_agents)
    available = availability_report(grouped, club_count)
    notes = []
    if seed is None:
        seed = random.SystemRandom().randrange(1, 2**31)
    seed = int(seed)
    players_available = sum(len(grouped.get(pos, [])) for pos in POSITIONS)
    required = PLAYERS_PER_CLUB * club_count

    if club_count == 0:
        notes.append("No UFL clubs exist.")
        return {
            "seed": seed,
            "clubs": [],
            "available": available,
            "players_available": players_available,
            "players_required": required,
            "notes": notes,
            "exact": False,
            "attempts": 0,
        }

    if any(not row["ok"] for row in available.values()):
        short = {pos: row for pos, row in available.items() if not row["ok"]}
        notes.append(f"Eligible pool is short of required positions: {short}")
        return {
            "seed": seed,
            "clubs": [],
            "available": available,
            "players_available": players_available,
            "players_required": required,
            "notes": notes,
            "exact": False,
            "attempts": 0,
        }

    rng = random.Random(seed)
    closest = None
    closest_spread = None
    for attempt in range(1, max_attempts + 1):
        teams = _attempt(grouped, rng, club_count)
        if teams is None:
            continue
        totals = [_total(team) for team in teams]
        spread = max(totals) - min(totals)
        if closest_spread is None or spread < closest_spread:
            closest_spread = spread
            closest = (teams, attempt, spread)
        if spread == 0:
            break

    if closest is None:
        notes.append("No valid allocation could be built from the eligible pool.")
        return {
            "seed": seed,
            "clubs": [],
            "available": available,
            "players_available": players_available,
            "players_required": required,
            "notes": notes,
            "exact": False,
            "attempts": max_attempts,
        }

    teams, attempts, spread = closest
    if spread:
        notes.append(f"Closest total-OVR spread after {attempts} attempt(s): {spread}.")
    squads = []
    for index, club in enumerate(clubs):
        squads.append(
            ProposedClubSquad(
                team_id=club.id,
                club_name=club.name,
                short_name=club.short_name,
                players=_sort_squad(teams[index]),
            )
        )
    return {
        "seed": seed,
        "clubs": squads,
        "available": available,
        "players_available": players_available,
        "players_required": required,
        "notes": notes,
        "exact": spread == 0,
        "attempts": attempts,
        "largest_total_diff": spread,
    }


def _check(key, label, ok, detail=""):
    return {"key": key, "label": label, "ok": bool(ok), "detail": detail}


def validate_allocation(squads, include_free_agents=False, max_avg_diff=DEFAULT_MAX_AVG_DIFF):
    from players.models import Player
    from teams.models import Team

    problems = []
    checks = []
    selected = [player for squad in squads for player in squad.players]
    club_count = len(squads)
    required = PLAYERS_PER_CLUB * club_count

    size_ok = all(len(squad.players) == PLAYERS_PER_CLUB for squad in squads) and len(selected) == required
    checks.append(_check("squad_size", "Every club has 25 players", size_ok, f"{len(selected)} selected / {required} required"))
    if not size_ok:
        problems.append("One or more clubs do not have exactly 25 players.")

    shape_ok = True
    for squad in squads:
        counts = squad.position_counts()
        for pos, needed in SHAPE_COUNTS.items():
            if counts.get(pos, 0) != needed:
                shape_ok = False
                problems.append(f"{squad.short_name} {pos}={counts.get(pos, 0)}, expected {needed}.")
    checks.append(_check("shape", "Every club has the required positional structure", shape_ok))

    ovrs = [player.overall for player in selected]
    ovr_ok = bool(ovrs) and min(ovrs) >= MIN_OVR and max(ovrs) <= MAX_OVR
    checks.append(
        _check(
            "ovr",
            f"Every player is between {MIN_OVR}–{MAX_OVR} OVR",
            ovr_ok,
            f"{min(ovrs) if ovrs else 0}–{max(ovrs) if ovrs else 0}",
        )
    )
    if ovrs and not ovr_ok:
        problems.append(f"OVR out of {MIN_OVR}–{MAX_OVR}.")

    ids = [player.id for player in selected]
    fc_ids = [player.fc27_id for player in selected]
    unique_ok = len(set(ids)) == len(ids) and len(set(fc_ids)) == len(fc_ids)
    checks.append(_check("unique", "No player appears twice", unique_ok))
    if not unique_ok:
        problems.append("Duplicate players in the proposal.")

    averages = [squad.average_ovr for squad in squads if squad.players]
    largest_diff = max(averages) - min(averages) if averages else 0
    balance_ok = Decimal(str(round(largest_diff, 3))) <= Decimal(str(max_avg_diff))
    checks.append(
        _check(
            "balance",
            f"Squad balance within {max_avg_diff} average OVR",
            balance_ok,
            f"Largest average difference: {largest_diff:.3f}",
        )
    )
    if not balance_ok:
        problems.append(f"Largest average OVR difference is {largest_diff:.3f}, allowed {max_avg_diff}.")

    live = {player.id: player for player in Player.objects.filter(pk__in=ids).select_related("mgl_team")}
    eligible_ok = True
    owned_ok = True
    transfer_ok = True
    auction_ok = True
    exists_ok = True
    for item in selected:
        player = live.get(item.id)
        if player is None:
            exists_ok = False
            eligible_ok = False
            problems.append(f"Player {item.name} (id={item.id}) no longer exists.")
            continue
        if str(player.fc27_id or "") != item.fc27_id:
            eligible_ok = False
            problems.append(f"{item.name} FC26 ID changed.")
        if int(player.overall or 0) != item.overall or player.position != item.position:
            eligible_ok = False
            problems.append(f"{item.name} FC26 rating or position no longer matches the proposal.")
        if player.mgl_team_id:
            owned_ok = False
            eligible_ok = False
            problems.append(f"{player.name} already belongs to {player.mgl_team.short_name}.")
        if player.is_free_agent and not include_free_agents:
            eligible_ok = False
            problems.append(f"{player.name} is a Free Agent and was not included in this proposal.")
        status = market_status(player)
        if status == "AUCTION":
            auction_ok = False
            eligible_ok = False
            problems.append(f"{player.name} is in an active auction.")
        if status in {"TRANSFER LISTED", "IN NEGOTIATION"}:
            transfer_ok = False
            eligible_ok = False
            problems.append(f"{player.name} is in an active transfer.")
    checks.append(_check("exists", "Every selected player still exists", exists_ok))
    checks.append(_check("eligible", "Every selected player is eligible", eligible_ok))
    checks.append(_check("unowned", "No selected player belongs to another UFL club", owned_ok))
    checks.append(_check("transfers", "No active transfer is affected", transfer_ok))
    checks.append(_check("auctions", "No active auction is affected", auction_ok))

    roster_ok = True
    club_ids = [squad.team_id for squad in squads]
    clubs = {club.id: club for club in Team.objects.filter(pk__in=club_ids)}
    for squad in squads:
        club = clubs.get(squad.team_id)
        if club is None:
            roster_ok = False
            problems.append(f"Club {squad.short_name} no longer exists.")
            continue
        occupied = roster_occupancy(club)
        limit = effective_roster_limit(club)
        if occupied + PLAYERS_PER_CLUB > limit:
            roster_ok = False
            problems.append(
                f"{club.name} already has {occupied} players and cannot accept {PLAYERS_PER_CLUB} more."
            )
    checks.append(_check("roster", "No squad-limit conflict exists", roster_ok))

    return {
        "ok": not problems and all(item["ok"] for item in checks),
        "checks": checks,
        "problems": problems,
        "largest_avg_diff": round(largest_diff, 3) if averages else 0,
        "average_league_ovr": round(sum(averages) / len(averages), 3) if averages else 0,
    }


def serialize_squads(squads):
    rows = []
    for squad in squads:
        rows.append(
            {
                "team_id": squad.team_id,
                "club_name": squad.club_name,
                "short_name": squad.short_name,
                "total_ovr": squad.total_ovr,
                "average_ovr": round(squad.average_ovr, 3),
                "highest_ovr": squad.highest_ovr,
                "lowest_ovr": squad.lowest_ovr,
                "position_counts": squad.position_counts(),
                "players": [player.as_dict() for player in squad.players],
            }
        )
    return rows


def squads_from_payload(payload):
    squads = []
    for row in payload.get("clubs") or []:
        squads.append(
            ProposedClubSquad(
                team_id=row["team_id"],
                club_name=row["club_name"],
                short_name=row["short_name"],
                players=[ProposedPlayer(**item) for item in row.get("players") or []],
            )
        )
    return squads


def create_proposal(user, seed=None, include_free_agents=False, max_avg_diff=DEFAULT_MAX_AVG_DIFF):
    from mgl.models import StartingSquadProposal

    result = generate_allocation(seed=seed, include_free_agents=include_free_agents)
    squads = result["clubs"]
    validation = validate_allocation(squads, include_free_agents=include_free_agents, max_avg_diff=max_avg_diff)
    averages = [squad.average_ovr for squad in squads if squad.players]
    with transaction.atomic():
        StartingSquadProposal.objects.filter(status=StartingSquadProposal.DRAFT).update(
            status=StartingSquadProposal.SUPERSEDED
        )
        proposal = StartingSquadProposal.objects.create(
            created_by=user if getattr(user, "is_authenticated", False) else None,
            seed=result["seed"],
            include_free_agents=include_free_agents,
            club_count=len(squads) or len(target_clubs()),
            players_required=result["players_required"],
            players_available=result["players_available"],
            rating_min=MIN_OVR,
            rating_max=MAX_OVR,
            squad_size=PLAYERS_PER_CLUB,
            average_league_ovr=Decimal(str(validation["average_league_ovr"])),
            largest_avg_diff=Decimal(str(validation["largest_avg_diff"])),
            max_allowed_avg_diff=Decimal(str(max_avg_diff)),
            status=StartingSquadProposal.DRAFT,
            payload={
                "clubs": serialize_squads(squads),
                "available": result["available"],
                "attempts": result["attempts"],
                "exact": result["exact"],
                "largest_total_diff": result.get("largest_total_diff", 0),
            },
            validation=validation,
            notes=result["notes"],
        )
    return proposal


def reject_proposal(proposal, user):
    from mgl.models import StartingSquadProposal

    if proposal.status != StartingSquadProposal.DRAFT:
        raise ValueError("Only a draft proposal can be rejected.")
    proposal.status = StartingSquadProposal.REJECTED
    proposal.rejected_by = user
    proposal.rejected_at = timezone.now()
    proposal.save(update_fields=["status", "rejected_by", "rejected_at"])
    return proposal


def _season_number():
    from mgl.season_history import current_season_number, ensure_active_season

    ensure_active_season()
    return current_season_number()


def approve_proposal(proposal, user, confirm=False):
    from mgl.audit import log_ocm_action
    from mgl.events import emit_official_event
    from mgl.models import NewsPost, StartingSquadLock, StartingSquadProposal
    from mgl.permissions import is_owner
    from mgl.services import assign_player
    from players.models import Player
    from teams.models import Team

    if not is_owner(user):
        raise ValueError("Only the Owner can approve starting squads.")
    if not confirm:
        raise ValueError("Approval requires explicit confirmation.")
    if proposal.status != StartingSquadProposal.DRAFT:
        raise ValueError("Only a draft proposal can be approved.")

    lock = StartingSquadLock.objects.filter(season=_season_number()).first()
    if lock:
        raise ValueError(
            f"Starting squads for season {lock.season} are already locked "
            f"(proposal {lock.proposal_id}). Start a new season before allocating again."
        )

    latest_draft = StartingSquadProposal.objects.filter(status=StartingSquadProposal.DRAFT).order_by("-id").first()
    if latest_draft and latest_draft.pk != proposal.pk:
        raise ValueError("This proposal is stale. A newer draft exists. Regenerate or open the latest proposal.")

    squads = squads_from_payload(proposal.payload)
    selected_ids = [player.id for squad in squads for player in squad.players]
    token_snapshot = {}
    assigned_rows = []

    try:
        with transaction.atomic():
            locked_proposal = StartingSquadProposal.objects.select_for_update().get(pk=proposal.pk)
            if locked_proposal.status != StartingSquadProposal.DRAFT:
                raise ValueError("This proposal is no longer a draft.")
            if StartingSquadLock.objects.select_for_update().filter(season=_season_number()).exists():
                raise ValueError("Starting squads for this season are already locked.")

            live_players = {
                player.id: player
                for player in Player.objects.select_for_update().filter(pk__in=selected_ids)
            }
            live_clubs = {
                club.id: club
                for club in Team.objects.select_for_update().filter(pk__in=[squad.team_id for squad in squads])
            }
            for club in live_clubs.values():
                if club.manager_id:
                    from managers.models import ManagerApplication

                    manager = ManagerApplication.objects.filter(user_id=club.manager_id).first()
                    if manager:
                        token_snapshot[manager.id] = str(manager.tokens)

            fresh = validate_allocation(
                squads,
                include_free_agents=locked_proposal.include_free_agents,
                max_avg_diff=locked_proposal.max_allowed_avg_diff,
            )
            if not fresh["ok"]:
                locked_proposal.validation = fresh
                locked_proposal.save(update_fields=["validation"])
                raise ValueError(
                    "This proposal is stale and must be regenerated. "
                    + "; ".join(fresh["problems"][:6])
                )

            for squad in squads:
                club = live_clubs[squad.team_id]
                for item in squad.players:
                    player = live_players[item.id]
                    previous = {
                        "player_id": player.id,
                        "fc27_id": str(player.fc27_id or ""),
                        "overall": player.overall,
                        "name": player.name,
                        "team_id": player.mgl_team_id,
                        "is_free_agent": player.is_free_agent,
                        "state": market_status(player),
                    }
                    assign_player(
                        player,
                        club,
                        source="UFL_STARTING",
                        reference=f"ufl-start:{locked_proposal.pk}:{club.short_name}",
                    )
                    player.refresh_from_db()
                    if player.overall != item.overall or str(player.fc27_id or "") != item.fc27_id:
                        raise ValueError("FC26 player identity changed during allocation.")
                    assigned_rows.append(
                        {
                            "previous": previous,
                            "new": {
                                "player_id": player.id,
                                "fc27_id": str(player.fc27_id or ""),
                                "overall": player.overall,
                                "team_id": club.id,
                                "team": club.name,
                                "state": "ASSIGNED",
                            },
                        }
                    )

            for manager_id, tokens in token_snapshot.items():
                from managers.models import ManagerApplication

                manager = ManagerApplication.objects.get(pk=manager_id)
                if str(manager.tokens) != tokens:
                    raise ValueError("Manager tokens changed during starting allocation.")

            now = timezone.now()
            locked_proposal.status = StartingSquadProposal.APPROVED
            locked_proposal.approved_by = user
            locked_proposal.approved_at = now
            locked_proposal.validation = fresh
            locked_proposal.save(
                update_fields=["status", "approved_by", "approved_at", "validation"]
            )
            StartingSquadLock.objects.create(
                season=_season_number(),
                proposal=locked_proposal,
                approved_by=user,
                approved_at=now,
                club_count=len(squads),
                players_assigned=len(selected_ids),
            )
            log_ocm_action(
                user,
                action="starting_squads.approve",
                object_type="StartingSquadProposal",
                object_id=str(locked_proposal.pk),
                object_label=f"Proposal {locked_proposal.pk}",
                old_value="DRAFT",
                new_value="APPROVED",
                summary=json.dumps(
                    {
                        "proposal_id": locked_proposal.pk,
                        "owner": getattr(user, "username", ""),
                        "timestamp": now.isoformat(),
                        "clubs": [squad.short_name for squad in squads],
                        "players_assigned": len(selected_ids),
                        "average_league_ovr": str(locked_proposal.average_league_ovr),
                        "largest_avg_diff": str(locked_proposal.largest_avg_diff),
                        "assignments": assigned_rows,
                    },
                    default=str,
                ),
            )
            proposal_id = locked_proposal.pk
    except ValueError:
        raise

    emit_official_event(
        NewsPost.MANAGER,
        "UFL STARTING SQUADS ALLOCATED",
        "Ultimate Fantasy League has officially completed its starting squad allocation.",
        details={"proposal_id": proposal_id, "clubs": len(squads), "players": len(selected_ids)},
    )
    return StartingSquadProposal.objects.get(pk=proposal_id)


def season_lock():
    from mgl.models import StartingSquadLock

    return StartingSquadLock.objects.select_related("proposal", "approved_by").filter(
        season=_season_number()
    ).first()
