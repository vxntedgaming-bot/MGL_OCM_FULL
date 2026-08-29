"""FC26 scouting: one manager-wide level, grouped regions, roster recruitment."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from players.models import Player
from auctions.models import PlayerAuction

from .market import club_for_user, debit_manager_tokens
from .models import NewsPost, PlayerListing, ScoutAssignment, ScoutProfile, ScoutReport
from .services import create_news
from .regions import (
    REGION_MENU,
    SCOUT_POSITIONS,
    nations_for_region,
    region_keys,
)
from .services import assign_player


BRONZE = ScoutAssignment.BRONZE
SILVER = ScoutAssignment.SILVER
GOLD = ScoutAssignment.GOLD

TIER_RANGES = {
    BRONZE: (45, 56),
    SILVER: (60, 74),
    GOLD: (70, 81),
}
SCOUT_HOURS = {
    1: {BRONZE: Decimal("8"), SILVER: Decimal("10"), GOLD: Decimal("12")},
    2: {BRONZE: Decimal("4"), SILVER: Decimal("5"), GOLD: Decimal("6")},
    3: {BRONZE: Decimal("1"), SILVER: Decimal("2.5"), GOLD: Decimal("3")},
}
UPGRADE_COSTS = {2: Decimal("18.00"), 3: Decimal("25.00")}
STARTING_LEVEL = 1
MAX_LEVEL = 3
SQUAD_LIMIT = 30
SQUAD_FULL_MESSAGE = "Your squad is full — maximum 30 players."
TIER_LABELS = {
    BRONZE: ("Bronze", "🥉"),
    SILVER: ("Silver", "🥈"),
    GOLD: ("Gold", "🥇"),
}


class SquadFullError(ValueError):
    pass


def scout_positions():
    return list(SCOUT_POSITIONS)


def scout_region_menu():
    return REGION_MENU


def get_or_create_scout_profile(manager):
    profile, created = ScoutProfile.objects.get_or_create(
        manager=manager,
        defaults={"scout_level": STARTING_LEVEL},
    )
    if not created and not profile.scout_level:
        profile.scout_level = STARTING_LEVEL
        profile.save(update_fields=["scout_level"])
    return profile


def manager_scout_level(manager):
    return get_or_create_scout_profile(manager).scout_level or STARTING_LEVEL


def cooldown_hours(tier, level):
    level = int(level or STARTING_LEVEL)
    if level not in SCOUT_HOURS:
        level = STARTING_LEVEL
    if tier not in SCOUT_HOURS[level]:
        raise ValueError("Unknown scout tier.")
    return SCOUT_HOURS[level][tier]


def format_hours(hours):
    hours = Decimal(str(hours))
    if hours == hours.to_integral_value():
        value = int(hours)
        unit = "Hour" if value == 1 else "Hours"
        return f"{value} {unit}"
    text = format(hours, "f").rstrip("0").rstrip(".")
    return f"{text} Hours"


def scout_times(level):
    rows = []
    for tier, (name, medal) in TIER_LABELS.items():
        hours = cooldown_hours(tier, level)
        rows.append(
            {
                "tier": tier,
                "name": name,
                "medal": medal,
                "hours": hours,
                "label": format_hours(hours),
            }
        )
    return rows


def next_upgrade(level):
    level = int(level or STARTING_LEVEL)
    if level >= MAX_LEVEL:
        return None
    nxt = level + 1
    cost = UPGRADE_COSTS[nxt]
    return {
        "level": nxt,
        "cost": cost,
        "cost_label": str(int(cost)) if cost == cost.to_integral_value() else str(cost),
        "times": scout_times(nxt),
    }


def remaining_wait(assignment, now=None):
    now = now or timezone.now()
    if assignment is None or assignment.status != ScoutAssignment.PENDING:
        return timedelta(0)
    if assignment.ready_at <= now:
        return timedelta(0)
    return assignment.ready_at - now


def _normalize_region(region):
    region = (region or "").strip()
    if not region or region == "anywhere":
        return ""
    if region in REGION_NATIONS_KEYS:
        return region
    return region


REGION_NATIONS_KEYS = set(region_keys())


def validate_region(region):
    region = (region or "").strip()
    if not region or region == "anywhere":
        return ""
    if region in REGION_NATIONS_KEYS:
        return region
    raise ValueError("Choose a scouting region from the list.")


def validate_position(position):
    position = (position or "").strip().upper()
    if not position:
        return ""
    if position in SCOUT_POSITIONS:
        return position
    raise ValueError("Choose a valid player position.")


def _unavailable_player_ids():
    live_auctions = PlayerAuction.objects.filter(
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE]
    ).values_list("player_id", flat=True)
    live_listings = PlayerListing.objects.filter(
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE]
    ).values_list("player_id", flat=True)
    return Q(id__in=live_auctions) | Q(id__in=live_listings)


def eligible_players(tier, region="", position=""):
    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    low, high = TIER_RANGES[tier]
    queryset = Player.objects.filter(
        overall__gte=low,
        overall__lte=high,
        is_free_agent=False,
        mgl_team__isnull=True,
    ).exclude(_unavailable_player_ids())
    nations = nations_for_region(region)
    if nations is not None:
        queryset = queryset.filter(nationality__in=nations)
    elif region and region not in ("", "anywhere") and region not in REGION_NATIONS_KEYS:
        queryset = queryset.filter(nationality=region)
    if position:
        queryset = queryset.filter(position=position)
    return queryset


def _pick_player(tier, region, position):
    player = eligible_players(tier, region, position).order_by("?").first()
    if player is None:
        raise ValueError("No available FC26 player matches that scout range, region and position.")
    return player


def _club_for_manager(manager):
    return club_for_user(getattr(manager, "user", None))


def _assert_roster_space(team):
    if team is None:
        raise ValueError("You must manage a club before sending a scout.")
    roster_limit = getattr(team, "roster_limit", None) or SQUAD_LIMIT
    current = Player.objects.filter(mgl_team=team).count()
    if current >= min(roster_limit, SQUAD_LIMIT):
        raise SquadFullError(SQUAD_FULL_MESSAGE)


@transaction.atomic
def upgrade_scout(manager):
    profile = get_or_create_scout_profile(manager)
    profile = ScoutProfile.objects.select_for_update().get(pk=profile.pk)
    current = profile.scout_level or STARTING_LEVEL
    if current >= MAX_LEVEL:
        raise ValueError("Your scouting network is already at maximum level.")
    nxt = current + 1
    cost = UPGRADE_COSTS[nxt]
    try:
        debit_manager_tokens(manager, cost, f"Scouting network level {nxt}")
    except ValueError as exc:
        if "enough tokens" in str(exc).lower():
            raise ValueError(
                f"You do not have enough tokens. Level {nxt} costs {cost} tokens."
            ) from exc
        raise
    profile.scout_level = nxt
    profile.save(update_fields=["scout_level"])
    return profile, nxt, cost


@transaction.atomic
def complete_ready_assignments(manager, now=None):
    now = now or timezone.now()
    due = list(
        ScoutAssignment.objects.select_for_update()
        .filter(
            manager=manager,
            status=ScoutAssignment.PENDING,
            ready_at__lte=now,
        )
        .order_by("ready_at")
    )
    created = []
    notices = []
    team = _club_for_manager(manager)
    for assignment in due:
        try:
            _assert_roster_space(team)
        except SquadFullError as exc:
            notices.append(str(exc))
            break
        except ValueError as exc:
            notices.append(str(exc))
            break
        player = None
        if assignment.player_id:
            still_open = eligible_players(
                assignment.tier, assignment.region, assignment.position
            ).filter(pk=assignment.player_id)
            if still_open.exists():
                player = assignment.player
        if player is None:
            try:
                player = _pick_player(
                    assignment.tier, assignment.region, assignment.position
                )
            except ValueError as exc:
                assignment.status = ScoutAssignment.COMPLETE
                assignment.completed_at = now
                assignment.save(update_fields=["status", "completed_at"])
                notices.append(str(exc))
                continue
        player = Player.objects.select_for_update().get(pk=player.pk)
        try:
            assign_player(
                player,
                team,
                source="SCOUT",
                reference=f"scout:{assignment.id}",
            )
        except ValueError as exc:
            message = str(exc)
            if "roster limit" in message.lower() or "30-player" in message:
                notices.append(SQUAD_FULL_MESSAGE)
                break
            notices.append(message)
            continue
        assignment.player = player
        assignment.status = ScoutAssignment.COMPLETE
        assignment.completed_at = now
        assignment.save(update_fields=["player", "status", "completed_at"])
        report = ScoutReport.objects.create(
            manager=manager,
            player=player,
            assignment=assignment,
            tier=assignment.tier,
            level=assignment.level,
            region=assignment.region,
            position=assignment.position,
            recruited=True,
            club=team,
        )
        created.append(report)
        notices.append(f"{player.name} recruited to {team.name}.")
        create_news(
            NewsPost.SCOUTING,
            f"{player.name} recruited",
            f"{team.name} recruited {player.name} through the MGL scouting network.",
            team=team,
        )
    return created, notices


@transaction.atomic
def dispatch_scout(manager, tier, region="", position=""):
    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    region = validate_region(region)
    position = validate_position(position)
    team = _club_for_manager(manager)
    _assert_roster_space(team)
    if not eligible_players(tier, region, position).exists():
        raise ValueError("No available FC26 player matches that scout range, region and position.")

    profile = get_or_create_scout_profile(manager)
    now = timezone.now()
    complete_ready_assignments(manager, now=now)
    _assert_roster_space(_club_for_manager(manager))

    busy = ScoutAssignment.objects.filter(
        manager=manager,
        tier=tier,
        status=ScoutAssignment.PENDING,
        ready_at__gt=now,
    ).exists()
    if busy:
        raise ValueError("That scout is still on cooldown.")
    ready_pending = ScoutAssignment.objects.filter(
        manager=manager,
        tier=tier,
        status=ScoutAssignment.PENDING,
        ready_at__lte=now,
    ).exists()
    if ready_pending:
        raise SquadFullError(SQUAD_FULL_MESSAGE)

    level = profile.scout_level or STARTING_LEVEL
    wait = cooldown_hours(tier, level)
    assignment = ScoutAssignment.objects.create(
        manager=manager,
        tier=tier,
        level=level,
        region=region,
        position=position,
        player=None,
        ready_at=now + timedelta(hours=float(wait)),
        status=ScoutAssignment.PENDING,
    )
    return assignment
