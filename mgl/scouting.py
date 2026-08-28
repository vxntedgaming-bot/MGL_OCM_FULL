"""FC26 scouting: real players, server-side cooldowns, personal reports."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from players.models import Player

from .market import debit_manager_tokens
from .models import ScoutAssignment, ScoutProfile, ScoutReport


BRONZE = ScoutAssignment.BRONZE
SILVER = ScoutAssignment.SILVER
GOLD = ScoutAssignment.GOLD

TIER_RANGES = {
    BRONZE: (45, 56),
    SILVER: (60, 74),
    GOLD: (70, 81),
}
TIER_BASE_HOURS = {
    BRONZE: Decimal("5"),
    SILVER: Decimal("10"),
    GOLD: Decimal("24"),
}
UPGRADE_COSTS = {1: Decimal("8.00"), 2: Decimal("15.00"), 3: Decimal("20.00")}
MAX_LEVEL = 3
LEVEL_FIELDS = {
    BRONZE: "bronze_level",
    SILVER: "silver_level",
    GOLD: "gold_level",
}


def scout_nationalities():
    return list(
        Player.objects.exclude(nationality="")
        .order_by("nationality")
        .values_list("nationality", flat=True)
        .distinct()
    )


def scout_positions():
    return [choice[0] for choice in Player.POSITION_CHOICES]


def get_or_create_scout_profile(manager):
    profile, _ = ScoutProfile.objects.get_or_create(manager=manager)
    return profile


def level_for(profile, tier):
    return int(getattr(profile, LEVEL_FIELDS[tier]) or 0)


def cooldown_hours(tier, level):
    base = TIER_BASE_HOURS[tier]
    level = int(level or 0)
    if level >= 3:
        hours = base / 2
    elif level >= 2:
        hours = base - 4
    elif level >= 1:
        hours = base - 2
    else:
        hours = base
    if hours < 0:
        hours = Decimal("0")
    return hours


def remaining_wait(assignment, now=None):
    now = now or timezone.now()
    if assignment.status != ScoutAssignment.PENDING:
        return timedelta(0)
    if assignment.ready_at <= now:
        return timedelta(0)
    return assignment.ready_at - now


@transaction.atomic
def upgrade_scout(manager, tier):
    if tier not in LEVEL_FIELDS:
        raise ValueError("Unknown scout tier.")
    profile = get_or_create_scout_profile(manager)
    profile = ScoutProfile.objects.select_for_update().get(pk=profile.pk)
    current = level_for(profile, tier)
    if current >= MAX_LEVEL:
        raise ValueError("This scout is already at maximum level.")
    nxt = current + 1
    cost = UPGRADE_COSTS[nxt]
    debit_manager_tokens(manager, cost, f"{tier.title()} scout level {nxt}")
    setattr(profile, LEVEL_FIELDS[tier], nxt)
    profile.save(update_fields=[LEVEL_FIELDS[tier]])
    return profile, nxt, cost


@transaction.atomic
def complete_ready_assignments(manager, now=None):
    now = now or timezone.now()
    due = ScoutAssignment.objects.select_for_update().filter(
        manager=manager,
        status=ScoutAssignment.PENDING,
        ready_at__lte=now,
        player__isnull=False,
    )
    created = []
    for assignment in due:
        report = ScoutReport.objects.create(
            manager=manager,
            player=assignment.player,
            assignment=assignment,
            tier=assignment.tier,
            level=assignment.level,
            region=assignment.region,
            position=assignment.position,
        )
        assignment.status = ScoutAssignment.COMPLETE
        assignment.completed_at = now
        assignment.save(update_fields=["status", "completed_at"])
        created.append(report)
    return created


def _pick_player(tier, region, position):
    low, high = TIER_RANGES[tier]
    queryset = Player.objects.filter(overall__gte=low, overall__lte=high)
    if region:
        queryset = queryset.filter(nationality=region)
    if position:
        queryset = queryset.filter(position=position)
    player = queryset.order_by("?").first()
    if player is None:
        raise ValueError("No FC26 player matches that scout range, region and position.")
    return player


@transaction.atomic
def dispatch_scout(manager, tier, region="", position=""):
    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    region = (region or "").strip()
    position = (position or "").strip().upper()
    if region and region not in set(scout_nationalities()):
        raise ValueError("Choose a nationality from the FC26 player pool.")
    if position and position not in scout_positions():
        raise ValueError("Choose a valid player position.")

    get_or_create_scout_profile(manager)
    now = timezone.now()
    complete_ready_assignments(manager, now=now)

    busy = ScoutAssignment.objects.filter(
        manager=manager,
        tier=tier,
        status=ScoutAssignment.PENDING,
        ready_at__gt=now,
    ).exists()
    if busy:
        raise ValueError("That scout is still on cooldown.")

    profile = get_or_create_scout_profile(manager)
    level = level_for(profile, tier)
    player = _pick_player(tier, region, position)
    wait = cooldown_hours(tier, level)
    assignment = ScoutAssignment.objects.create(
        manager=manager,
        tier=tier,
        level=level,
        region=region,
        position=position,
        player=player,
        ready_at=now + timedelta(hours=float(wait)),
        status=ScoutAssignment.PENDING,
    )
    return assignment
