"""Controlled UFL Season 1 club bootstrap.

Preview is always safe. Apply retires current UFL-division test clubs and
creates the locked 16 / 14 / 8 starter structure. It never assigns starting
squads, never changes manager tokens, and never rewrites FC26 identities.

Do not call apply against production until the Owner explicitly approves.
"""

from __future__ import annotations

import random
from decimal import Decimal

from django.db import transaction

from leagues.services import (
    CHAMPIONSHIP_SHORT,
    LEAGUE_ONE_SHORT,
    PREMIER_SHORT,
    active_divisions,
    ensure_premier_league,
)


UFL_DIVISION_COUNTS = {
    PREMIER_SHORT: 16,
    CHAMPIONSHIP_SHORT: 14,
    LEAGUE_ONE_SHORT: 8,
}
UFL_STARTER_CLUB_TOTAL = sum(UFL_DIVISION_COUNTS.values())
CONFIRM_PHRASE = "SEASON 1 BOOTSTRAP"
APPLY_BLOCKED_REASON = (
    "Season 1 apply is implemented but blocked until the Owner explicitly "
    "authorises the production bootstrap in a later instruction."
)

_TOWNS = (
    "Ashford", "Bramley", "Calder", "Dunwich", "Eastmere", "Fenwick",
    "Glenford", "Hartley", "Ironbridge", "Kingswell", "Lakeside", "Mossley",
    "Northfield", "Oakridge", "Prestwich", "Queensferry", "Redcliff", "Stonehaven",
    "Thornbury", "Aldermere", "Blackwater", "Crowhurst", "Dalston", "Edenford",
    "Fairhaven", "Goldmere", "Highstead", "Ivybridge", "Juniper", "Kirkwell",
    "Longridge", "Mapleford", "Newhaven", "Otterbourne", "Ridgeway", "Shoreham",
    "Tanglewood", "Whitfield",
)
_SUFFIXES = ("FC", "United", "City", "Athletic")


def _short_code(name, used):
    letters = "".join(ch for ch in name.upper() if ch.isalpha())
    base = (letters[:3] + "XXX")[:3]
    code = base
    index = 0
    while code in used:
        index += 1
        code = f"{base[:2]}{index}"[:3]
    used.add(code)
    return code


def proposed_clubs(seed=None):
    rng = random.Random(int(seed) if seed is not None else 20260901)
    towns = list(_TOWNS)
    rng.shuffle(towns)
    suffixes = list(_SUFFIXES)
    used = set()
    planned = []
    cursor = 0
    for short, count in UFL_DIVISION_COUNTS.items():
        for _ in range(count):
            town = towns[cursor]
            cursor += 1
            suffix = suffixes[rng.randrange(len(suffixes))]
            name = f"{town} {suffix}"
            planned.append(
                {
                    "league": short,
                    "name": name,
                    "short_name": _short_code(town, used),
                }
            )
    return planned


def _ufl_division_teams():
    from teams.models import Team

    return list(
        Team.objects.filter(
            league__short_name__in=list(UFL_DIVISION_COUNTS.keys())
        ).select_related("league", "manager").order_by("league_id", "name", "id")
    )


def preview_season1_bootstrap(seed=None):
    """Read-only report of what apply would change. Safe to run anywhere."""
    from auctions.models import PlayerAuction
    from mgl.models import (
        ClubApplication,
        Fixture,
        ManagerClubSpell,
        PlayerListing,
        PlayerReleaseRequest,
        StartingSquadLock,
        StartingSquadProposal,
    )
    from mgl.ufl_starting import season_lock
    from managers.models import ManagerApplication
    from players.models import Player
    from teams.models import Team

    ensure_premier_league()
    planned = proposed_clubs(seed)
    retiring = _ufl_division_teams()
    retiring_ids = [team.id for team in retiring]
    assigned = list(
        Player.objects.filter(mgl_team_id__in=retiring_ids).only(
            "id", "name", "fc27_id", "overall", "position", "mgl_team_id"
        )
    )
    managers_detached = [
        {
            "user_id": team.manager_id,
            "username": team.manager.username,
            "club": team.name,
        }
        for team in retiring
        if team.manager_id
    ]
    leftover = list(
        Team.objects.exclude(league__short_name__in=list(UFL_DIVISION_COUNTS.keys())).order_by("name")
    )
    lock = season_lock()
    token_snapshot = list(
        ManagerApplication.objects.order_by("id").values_list("id", "tokens")
    )
    return {
        "ok": True,
        "seed": int(seed) if seed is not None else 20260901,
        "apply_blocked": True,
        "apply_blocked_reason": APPLY_BLOCKED_REASON,
        "clubs_to_retire": [
            {
                "id": team.id,
                "name": team.name,
                "short_name": team.short_name,
                "league": team.league.short_name if team.league_id else "",
                "manager_id": team.manager_id,
                "squad_size": team.players.count(),
                "is_ufl_starter": bool(team.is_ufl_starter),
            }
            for team in retiring
        ],
        "clubs_left_in_place": [
            {
                "id": team.id,
                "name": team.name,
                "short_name": team.short_name,
                "league": team.league.short_name if team.league_id else "",
            }
            for team in leftover
        ],
        "players_to_unassign": len(assigned),
        "player_identities_preserved": True,
        "managers_detached": managers_detached,
        "manager_tokens_unchanged": True,
        "token_ledger_untouched": True,
        "user_accounts_untouched": True,
        "fixtures_that_cascade": Fixture.objects.filter(
            home_team_id__in=retiring_ids
        ).count()
        + Fixture.objects.filter(away_team_id__in=retiring_ids).exclude(
            home_team_id__in=retiring_ids
        ).count(),
        "listings_that_cascade": PlayerListing.objects.filter(team_id__in=retiring_ids).count(),
        "applications_that_cascade": ClubApplication.objects.filter(team_id__in=retiring_ids).count(),
        "spells_that_cascade": ManagerClubSpell.objects.filter(team_id__in=retiring_ids).count(),
        "release_requests_that_cascade": PlayerReleaseRequest.objects.filter(
            team_id__in=retiring_ids
        ).count(),
        "live_auctions_on_retiring_players": PlayerAuction.objects.filter(
            player__mgl_team_id__in=retiring_ids,
            status=PlayerAuction.LIVE,
        ).count(),
        "current_season_lock": (
            {
                "season": lock.season,
                "proposal_id": lock.proposal_id,
                "players_assigned": lock.players_assigned,
            }
            if lock
            else None
        ),
        "unrelated_season_locks_preserved": StartingSquadLock.objects.exclude(
            season=lock.season if lock else -1
        ).count(),
        "draft_proposals_superseded": StartingSquadProposal.objects.filter(
            status=StartingSquadProposal.DRAFT
        ).count(),
        "planned_clubs": planned,
        "planned_counts": {
            short: sum(1 for row in planned if row["league"] == short)
            for short in UFL_DIVISION_COUNTS
        },
        "planned_total": len(planned),
        "manager_token_count": len(token_snapshot),
        "notes": [
            "FC26 player master rows are not deleted.",
            "Manager token balances are not changed.",
            "User accounts and authentication are not changed.",
            "Managers are detached from retired clubs and are not assigned to the new clubs.",
            "Starting squads are not generated or assigned by this process.",
            "The 42-club ENSURE CLUBS helper is not used.",
            "mgl_reset is not used.",
            APPLY_BLOCKED_REASON,
        ],
    }


def format_preview(report):
    lines = [
        "UFL SEASON 1 BOOTSTRAP PREVIEW — NO WRITES",
        f"Seed: {report['seed']}",
        f"Clubs to retire: {len(report['clubs_to_retire'])}",
        f"Players that would be unassigned (identities kept): {report['players_to_unassign']}",
        f"Managers detached (not reassigned): {len(report['managers_detached'])}",
        f"Fixtures that would cascade-delete: {report['fixtures_that_cascade']}",
        f"Listings that would cascade-delete: {report['listings_that_cascade']}",
        f"Club applications that would cascade-delete: {report['applications_that_cascade']}",
        f"Manager spells that would cascade-delete: {report['spells_that_cascade']}",
        f"Planned clubs: {report['planned_total']} "
        f"(PL {report['planned_counts'][PREMIER_SHORT]} / "
        f"CH {report['planned_counts'][CHAMPIONSHIP_SHORT]} / "
        f"L1 {report['planned_counts'][LEAGUE_ONE_SHORT]})",
        f"Clubs left outside UFL divisions: {len(report['clubs_left_in_place'])}",
        f"Current-season lock: {report['current_season_lock'] or 'none'}",
        f"Unrelated season locks preserved: {report['unrelated_season_locks_preserved']}",
        APPLY_BLOCKED_REASON,
    ]
    for club in report["clubs_to_retire"]:
        lines.append(
            f"  RETIRE {club['short_name']} {club['name']} "
            f"({club['league']}, squad {club['squad_size']})"
        )
    for club in report["planned_clubs"]:
        lines.append(f"  CREATE {club['short_name']} {club['name']} ({club['league']})")
    return "\n".join(lines)


def _cancel_market_for_players(player_ids):
    from auctions.models import PlayerAuction
    from mgl.models import PlayerListing

    PlayerListing.objects.filter(
        player_id__in=player_ids,
        status__in=[
            PlayerListing.LIVE,
            PlayerListing.OFFER,
            PlayerListing.PENDING,
        ],
    ).update(status=PlayerListing.CANCELLED)
    PlayerAuction.objects.filter(player_id__in=player_ids, status=PlayerAuction.LIVE).update(
        status=PlayerAuction.CANCELLED
    )


def apply_season1_bootstrap(user, confirm=False, seed=None, allow_apply=False):
    """Apply the Season 1 club structure.

    Production apply remains blocked unless allow_apply=True. Automated tests
    pass allow_apply=True against the isolated Django test database only.
    """
    from mgl.permissions import is_owner
    from mgl.site_cms import log_site_change
    from mgl.models import PlayerOwnershipHistory, StartingSquadLock, StartingSquadProposal
    from mgl.ufl_starting import season_lock
    from managers.models import ManagerApplication
    from players.models import Player
    from teams.models import Team

    if not is_owner(user):
        raise ValueError("Only the Owner can apply the Season 1 club bootstrap.")
    if not confirm:
        raise ValueError("Season 1 apply requires explicit confirmation.")
    if not allow_apply:
        raise ValueError(APPLY_BLOCKED_REASON)

    report = preview_season1_bootstrap(seed=seed)
    token_before = {
        row["id"]: str(row["tokens"])
        for row in ManagerApplication.objects.values("id", "tokens")
    }
    identity_before = list(
        Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name")
    )
    planned = report["planned_clubs"]
    if len(planned) != UFL_STARTER_CLUB_TOTAL:
        raise ValueError("Season 1 plan does not contain exactly 38 clubs.")

    divisions = {league.short_name: league for league in active_divisions()}
    created = []
    with transaction.atomic():
        retiring = _ufl_division_teams()
        retiring_ids = [team.id for team in retiring]
        assigned = list(Player.objects.select_for_update().filter(mgl_team_id__in=retiring_ids))
        player_ids = [player.id for player in assigned]
        _cancel_market_for_players(player_ids)
        for player in assigned:
            PlayerOwnershipHistory.objects.create(
                player=player,
                team=player.mgl_team,
                manager=player.mgl_team.manager if player.mgl_team_id else None,
                source="SEASON1_RETIRE",
                reference="ufl-season1-bootstrap",
            )
            player.mgl_team = None
            player.is_free_agent = False
            player.save(update_fields=["mgl_team", "is_free_agent"])
        Team.objects.filter(pk__in=retiring_ids).update(manager=None)
        Team.objects.filter(pk__in=retiring_ids).delete()

        lock = season_lock()
        if lock:
            StartingSquadLock.objects.filter(pk=lock.pk).delete()
        StartingSquadProposal.objects.filter(status=StartingSquadProposal.DRAFT).update(
            status=StartingSquadProposal.SUPERSEDED
        )

        for row in planned:
            league = divisions[row["league"]]
            created.append(
                Team.objects.create(
                    name=row["name"],
                    short_name=row["short_name"],
                    league=league,
                    manager=None,
                    roster_limit=30,
                    is_ufl_starter=True,
                    tokens=Decimal("50.00"),
                )
            )

        for manager_id, tokens in token_before.items():
            live = ManagerApplication.objects.get(pk=manager_id)
            if str(live.tokens) != tokens:
                raise ValueError("Manager tokens changed during Season 1 bootstrap.")
        identity_after = list(
            Player.objects.order_by("id").values_list("id", "fc27_id", "overall", "name")
        )
        if identity_after != identity_before:
            raise ValueError("Player identity data changed during Season 1 bootstrap.")
        if Team.objects.filter(is_ufl_starter=True).count() != UFL_STARTER_CLUB_TOTAL:
            raise ValueError("Season 1 apply did not create exactly 38 starter clubs.")

        log_site_change(
            user,
            action="season1.bootstrap",
            object_type="Team",
            object_id="season1",
            object_label="UFL Season 1 clubs",
            summary=(
                f"Retired {len(retiring_ids)} UFL-division clubs and created "
                f"{len(created)} starter clubs. Starting squads were not assigned."
            ),
        )

    return {
        "ok": True,
        "retired": len(retiring_ids),
        "created": len(created),
        "unassigned": len(player_ids),
        "clubs": [
            {"id": team.id, "name": team.name, "short_name": team.short_name, "league": team.league.short_name}
            for team in created
        ],
    }
