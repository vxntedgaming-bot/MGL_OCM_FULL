"""Approved 14×26 starting squads and application helpers.

The allocation is the verified dry-run (seed 20260828). This module never
changes FC26 ratings, IDs, faces, club treasuries, or manager balances.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from django.db import transaction
from django.db.models import Sum

from mgl.player_state import live_auctions, market_counts, player_is_in_live_auction
from mgl.services import assign_player
from players.models import Player
from teams.models import Team
from teams.official_sl1 import OFFICIAL_SL1_SHORT_NAMES


ALLOCATION_PATH = Path(__file__).resolve().parent / "data" / "approved_starting_squads.json"
TARGET_TOTAL_OVR = 1741
TARGET_AVERAGE_OVR = 66.9615
PLAYERS_PER_CLUB = 26
CLUB_COUNT = 14
EXPECTED_ASSIGNED = CLUB_COUNT * PLAYERS_PER_CLUB
EXPECTED_TOTAL_PLAYERS = 18405
EXPECTED_UNASSIGNED_AFTER = EXPECTED_TOTAL_PLAYERS - EXPECTED_ASSIGNED
SHAPE = {
    "GK": 2,
    "CB": 4,
    "RB": 2,
    "LB": 2,
    "CDM": 2,
    "CM": 2,
    "CAM": 2,
    "RM": 2,
    "LM": 2,
    "ST": 2,
    "LW": 2,
    "RW": 2,
}


def load_allocation(path=None):
    path = Path(path) if path else ALLOCATION_PATH
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def selected_players(allocation=None):
    allocation = allocation if allocation is not None else load_allocation()
    return [player for squad in allocation["squads"] for player in squad["players"]]


def allocation_integrity_errors(allocation=None):
    allocation = allocation if allocation is not None else load_allocation()
    problems = []
    selected = selected_players(allocation)
    if len(allocation.get("squads") or []) != CLUB_COUNT:
        problems.append(f"Allocation has {len(allocation.get('squads') or [])} clubs, expected {CLUB_COUNT}.")
    if len(selected) != EXPECTED_ASSIGNED:
        problems.append(f"Allocation has {len(selected)} players, expected {EXPECTED_ASSIGNED}.")
    fc_ids = [str(player["fc27_id"]) for player in selected]
    if len(set(fc_ids)) != len(fc_ids):
        problems.append("Allocation contains duplicate fc27_id values.")
    shorts = [squad["short_name"] for squad in allocation["squads"]]
    if tuple(shorts) != OFFICIAL_SL1_SHORT_NAMES:
        problems.append(f"Club order/short names do not match official clubs: {shorts}")
    for squad in allocation["squads"]:
        players = squad["players"]
        if len(players) != PLAYERS_PER_CLUB:
            problems.append(f"{squad['short_name']} has {len(players)} players.")
        total = sum(int(player["overall"]) for player in players)
        if total != TARGET_TOTAL_OVR:
            problems.append(f"{squad['short_name']} allocation total OVR {total}, expected {TARGET_TOTAL_OVR}.")
        avg = round(total / PLAYERS_PER_CLUB, 4) if players else 0
        if avg != TARGET_AVERAGE_OVR:
            problems.append(f"{squad['short_name']} allocation average {avg}, expected {TARGET_AVERAGE_OVR}.")
        counts = Counter(player["position"] for player in players)
        if dict(counts) != SHAPE:
            problems.append(f"{squad['short_name']} shape {dict(counts)}, expected {SHAPE}.")
        ovrs = [int(player["overall"]) for player in players]
        if ovrs and (min(ovrs) < 64 or max(ovrs) > 70):
            problems.append(f"{squad['short_name']} OVR out of 64–70.")
    return problems


def _club_map():
    clubs = list(Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES))
    return {club.short_name: club for club in clubs}


def validate_against_database(allocation=None):
    allocation = allocation if allocation is not None else load_allocation()
    problems = list(allocation_integrity_errors(allocation))
    clubs = _club_map()
    missing_clubs = [short for short in OFFICIAL_SL1_SHORT_NAMES if short not in clubs]
    if missing_clubs:
        problems.append(f"Missing official clubs: {missing_clubs}")
        return {"ok": False, "problems": problems, "rows": [], "counts": market_counts()}

    selected = selected_players(allocation)
    fc_ids = [str(player["fc27_id"]) for player in selected]
    db_players = {
        str(player.fc27_id): player
        for player in Player.objects.filter(fc27_id__in=fc_ids).select_related("mgl_team")
    }
    rows = []
    already_assigned = []
    for squad in allocation["squads"]:
        club = clubs[squad["short_name"]]
        for item in squad["players"]:
            fc27_id = str(item["fc27_id"])
            player = db_players.get(fc27_id)
            row = {
                "club": squad["short_name"],
                "club_name": squad["club_name"],
                "fc27_id": fc27_id,
                "expected_name": item["name"],
                "expected_position": item["position"],
                "expected_overall": int(item["overall"]),
            }
            if player is None:
                problems.append(f"Missing player fc27_id={fc27_id} ({item['name']}).")
                row["status"] = "MISSING"
                rows.append(row)
                continue
            row["player_id"] = player.id
            row["db_name"] = player.name
            row["db_position"] = player.position
            row["db_overall"] = player.overall
            if player.overall != int(item["overall"]):
                problems.append(
                    f"{fc27_id} OVR is {player.overall}, allocation expects {item['overall']}. Ratings must not be changed."
                )
            if player.position != item["position"]:
                problems.append(
                    f"{fc27_id} position is {player.position}, allocation expects {item['position']}."
                )
            blocked = False
            if player.mgl_team_id:
                already_assigned.append(fc27_id)
                blocked = True
                problems.append(
                    f"{fc27_id} already belongs to {player.mgl_team.short_name}."
                )
            if player.is_free_agent:
                blocked = True
                problems.append(f"{fc27_id} is a Free Agent; starting squads must come from UNASSIGNED.")
            if player_is_in_live_auction(player):
                blocked = True
                problems.append(f"{fc27_id} is in a live auction and cannot be assigned.")
            row["status"] = "BLOCKED" if blocked else "OK"
            rows.append(row)

    for short in OFFICIAL_SL1_SHORT_NAMES:
        club = clubs.get(short)
        if club is not None and club.players.exists():
            problems.append(f"{short} already has players. Starting assignment requires empty official squads.")

    if live_auctions().exists():
        problems.append("Live auctions exist. Starting assignment requires 0 active auctions.")

    counts = market_counts()
    player_total = Player.objects.count()
    unique_fc27 = (
        Player.objects.exclude(fc27_id="")
        .exclude(fc27_id__isnull=True)
        .values("fc27_id")
        .distinct()
        .count()
    )
    assigned_now = Player.objects.filter(mgl_team__isnull=False).count()
    report = {
        "ok": not problems,
        "problems": problems,
        "rows": rows,
        "counts": counts,
        "player_total": player_total,
        "unique_fc27": unique_fc27,
        "ovr_sum": Player.objects.aggregate(total=Sum("overall"))["total"] or 0,
        "assigned_now": assigned_now,
        "club_treasuries": {
            short: str(clubs[short].tokens) for short in OFFICIAL_SL1_SHORT_NAMES if short in clubs
        },
        "club_rosters": {
            short: clubs[short].players.count() for short in OFFICIAL_SL1_SHORT_NAMES if short in clubs
        },
        "matches_league_start_counts": (
            player_total == EXPECTED_TOTAL_PLAYERS
            and unique_fc27 == EXPECTED_TOTAL_PLAYERS
            and assigned_now == 0
            and counts.get("free_agents") == 0
            and counts.get("auctions") == 0
        ),
    }
    return report


def projected_club_totals(allocation=None):
    allocation = allocation if allocation is not None else load_allocation()
    return {
        squad["short_name"]: sum(int(player["overall"]) for player in squad["players"])
        for squad in allocation["squads"]
    }


@transaction.atomic
def apply_starting_squads(allocation=None, dry_run=True):
    allocation = allocation if allocation is not None else load_allocation()
    report = validate_against_database(allocation)
    if not report["ok"]:
        return report
    if dry_run:
        report["applied"] = False
        report["message"] = "DRY RUN — no players were assigned and no auctions were created."
        return report

    clubs = _club_map()
    selected = selected_players(allocation)
    fc_ids = [str(player["fc27_id"]) for player in selected]
    locked = {
        str(player.fc27_id): player
        for player in Player.objects.select_for_update().filter(fc27_id__in=fc_ids)
    }
    treasuries_before = {short: club.tokens for short, club in clubs.items()}
    ovrs_before = {fc27_id: player.overall for fc27_id, player in locked.items()}

    for squad in allocation["squads"]:
        club = clubs[squad["short_name"]]
        for item in squad["players"]:
            player = locked[str(item["fc27_id"])]
            assign_player(
                player,
                club,
                source="INITIAL_SQUAD",
                reference=f"MGL_STARTING_{club.short_name}",
            )

    for short, club in clubs.items():
        club.refresh_from_db()
        if club.tokens != treasuries_before[short]:
            raise ValueError(f"{short} treasury changed during assignment.")
    for fc27_id, overall in ovrs_before.items():
        player = Player.objects.get(fc27_id=fc27_id)
        if player.overall != overall:
            raise ValueError(f"{fc27_id} overall changed during assignment.")

    after = validate_applied_squads()
    report["applied"] = after["ok"]
    report["after"] = after
    report["counts"] = market_counts()
    report["message"] = (
        "Assigned 364 starting club players from the approved allocation."
        if after["ok"]
        else "Assignment wrote rows but post-checks failed."
    )
    if not after["ok"]:
        raise ValueError("; ".join(after["problems"]))
    return report


def validate_applied_squads():
    problems = []
    clubs = _club_map()
    assigned_ids = []
    for short in OFFICIAL_SL1_SHORT_NAMES:
        club = clubs.get(short)
        if club is None:
            problems.append(f"Missing club {short}.")
            continue
        players = list(club.players.all())
        if len(players) != PLAYERS_PER_CLUB:
            problems.append(f"{short} has {len(players)} players, expected {PLAYERS_PER_CLUB}.")
        total = sum(player.overall for player in players)
        if total != TARGET_TOTAL_OVR:
            problems.append(f"{short} total OVR {total}, expected {TARGET_TOTAL_OVR}.")
        avg = round(total / PLAYERS_PER_CLUB, 4) if players else 0
        if avg != TARGET_AVERAGE_OVR:
            problems.append(f"{short} average OVR {avg}, expected {TARGET_AVERAGE_OVR}.")
        counts = Counter(player.position for player in players)
        if dict(counts) != SHAPE:
            problems.append(f"{short} shape {dict(counts)}, expected {SHAPE}.")
        ovrs = [player.overall for player in players]
        if ovrs and (min(ovrs) < 64 or max(ovrs) > 70):
            problems.append(f"{short} has a player outside 64–70 OVR.")
        assigned_ids.extend(player.fc27_id for player in players)
        if str(club.tokens) != "50.00":
            problems.append(f"{short} treasury is {club.tokens}, expected 50.00.")
    if len(assigned_ids) != len(set(assigned_ids)):
        problems.append("A player belongs to more than one club.")
    counts = market_counts()
    if counts.get("free_agents"):
        problems.append(f"Free Agents = {counts['free_agents']}, expected 0 after starting assignment.")
    if counts.get("auctions"):
        problems.append(f"Active auctions = {counts['auctions']}, expected 0 after starting assignment.")
    if counts.get("club_players") != EXPECTED_ASSIGNED:
        problems.append(f"Club players = {counts.get('club_players')}, expected {EXPECTED_ASSIGNED}.")
    return {"ok": not problems, "problems": problems, "counts": counts}


def format_validation_report(report):
    lines = [
        "MGL STARTING SQUADS — VALIDATION",
        f"OK: {report.get('ok')}",
        f"Players: {report.get('player_total')}",
        f"Unique fc27_id: {report.get('unique_fc27')}",
        f"OVR sum: {report.get('ovr_sum')}",
        f"Currently assigned: {report.get('assigned_now')}",
        f"Market: {report.get('counts')}",
        (
            "League-start totals (18,405 / 0 assigned / 0 FA / 0 auctions): "
            f"{report.get('matches_league_start_counts')}"
        ),
    ]
    treasuries = report.get("club_treasuries") or {}
    if treasuries:
        lines.append("Club treasuries: " + ", ".join(f"{k}={v}" for k, v in treasuries.items()))
    rosters = report.get("club_rosters") or {}
    if rosters:
        lines.append("Club rosters: " + ", ".join(f"{k}={v}" for k, v in rosters.items()))
    if report.get("message"):
        lines.append(report["message"])
    if report.get("problems"):
        lines.append("Problems:")
        lines.extend(f"  - {item}" for item in report["problems"])
    after = report.get("after")
    if after:
        lines.append(f"Post-apply OK: {after.get('ok')}")
        lines.append(f"Post-apply market: {after.get('counts')}")
        if after.get("problems"):
            lines.extend(f"  - {item}" for item in after["problems"])
    return "\n".join(lines)
