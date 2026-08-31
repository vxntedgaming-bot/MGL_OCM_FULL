"""FC26 scouting: one manager-wide HQ level, reserved unreleased players, pack reveal."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from players.models import Player
from auctions.models import PlayerAuction

from .market import club_for_user, debit_manager_tokens
from .models import NewsPost, PlayerListing, ScoutAssignment, ScoutProfile, ScoutReport
from .player_state import unassigned_players
from .regions import (
    REGION_MENU,
    SCOUT_POSITIONS,
    nations_for_region,
    region_keys,
    region_label,
)
from .services import assign_player, create_news


BRONZE = ScoutAssignment.BRONZE
SILVER = ScoutAssignment.SILVER
GOLD = ScoutAssignment.GOLD
ELITE = ScoutAssignment.ELITE

TIER_RANGES = {
    BRONZE: (45, 56),
    SILVER: (60, 74),
    GOLD: (70, 81),
    ELITE: (82, 92),
}
BASE_HOURS = {
    BRONZE: Decimal("8"),
    SILVER: Decimal("10"),
    GOLD: Decimal("12"),
    ELITE: Decimal("16"),
}
HOURS_REDUCTION_PER_LEVEL = Decimal("1.5")
MIN_HOURS = Decimal("0.5")
UPGRADE_COSTS = {
    2: Decimal("10.00"),
    3: Decimal("15.00"),
    4: Decimal("20.00"),
    5: Decimal("25.00"),
}
STARTING_LEVEL = 1
MAX_LEVEL = 5
SQUAD_LIMIT = 30
SQUAD_FULL_MESSAGE = "Your squad is full — maximum 30 players."
TIER_LABELS = {
    BRONZE: ("Bronze", "🥉"),
    SILVER: ("Silver", "🥈"),
    GOLD: ("Gold", "🥇"),
    ELITE: ("Elite", "◆"),
}
ACTIVE_STATUSES = (
    ScoutAssignment.PENDING,
    ScoutAssignment.READY,
    ScoutAssignment.OPENED,
)
REGION_NATIONS_KEYS = set(region_keys())


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
    if tier not in BASE_HOURS:
        raise ValueError("Unknown scout tier.")
    level = int(level or STARTING_LEVEL)
    if level < STARTING_LEVEL:
        level = STARTING_LEVEL
    if level > MAX_LEVEL:
        level = MAX_LEVEL
    hours = BASE_HOURS[tier] - (HOURS_REDUCTION_PER_LEVEL * (level - 1))
    if hours < MIN_HOURS:
        hours = MIN_HOURS
    return hours


def hours_saved(level):
    level = int(level or STARTING_LEVEL)
    if level < STARTING_LEVEL:
        level = STARTING_LEVEL
    return HOURS_REDUCTION_PER_LEVEL * (level - 1)


def hours_saved_label(level):
    saved = hours_saved(level)
    if not saved:
        return ""
    if saved == saved.to_integral_value():
        value = int(saved)
        unit = "hour" if value == 1 else "hours"
        return f"{value} {unit}"
    text = format(saved, "f").rstrip("0").rstrip(".")
    return f"{text} hours"


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
        "hours_saved": hours_saved(nxt),
    }


def remaining_wait(assignment, now=None):
    now = now or timezone.now()
    if assignment is None or assignment.status != ScoutAssignment.PENDING:
        return timedelta(0)
    if assignment.ready_at <= now:
        return timedelta(0)
    return assignment.ready_at - now


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
    reserved = ScoutAssignment.objects.filter(
        status__in=ACTIVE_STATUSES,
        player_id__isnull=False,
    ).values_list("player_id", flat=True)
    return Q(id__in=live_auctions) | Q(id__in=live_listings) | Q(id__in=reserved)


def eligible_players(tier, region="", position=""):
    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    low, high = TIER_RANGES[tier]
    queryset = unassigned_players().filter(
        overall__gte=low,
        overall__lte=high,
    ).exclude(_unavailable_player_ids())
    nations = nations_for_region(region)
    if nations is not None:
        queryset = queryset.filter(nationality__in=nations)
    elif region and region not in ("", "anywhere") and region not in REGION_NATIONS_KEYS:
        queryset = queryset.filter(nationality=region)
    if position:
        queryset = queryset.filter(position=position)
    return queryset


def _claim_unreleased_player(tier, region, position):
    """Lock and reserve an unreleased player so two scouts cannot claim the same one."""
    candidate_ids = list(
        eligible_players(tier, region, position).order_by("?").values_list("id", flat=True)[:25]
    )
    if not candidate_ids:
        raise ValueError("No available FC26 player matches that scout range, region and position.")
    for player_id in candidate_ids:
        locked = Player.objects.select_for_update().get(pk=player_id)
        if locked.mgl_team_id is not None or locked.is_free_agent:
            continue
        if ScoutAssignment.objects.filter(
            player_id=locked.pk,
            status__in=ACTIVE_STATUSES,
        ).exists():
            continue
        return locked
    raise ValueError("No available FC26 player matches that scout range, region and position.")


def _club_for_manager(manager):
    return club_for_user(getattr(manager, "user", None))


def _assert_roster_space(team):
    if team is None:
        raise ValueError("You must manage a club before sending a scout.")
    from mgl.player_state import roster_occupancy

    roster_limit = getattr(team, "roster_limit", None) or SQUAD_LIMIT
    current = roster_occupancy(team)
    if current >= min(roster_limit, SQUAD_LIMIT):
        raise SquadFullError(SQUAD_FULL_MESSAGE)


def _owned_assignment(manager, assignment):
    if assignment is None:
        raise ValueError("That scouting mission was not found.")
    if assignment.manager_id != manager.id:
        raise ValueError("That scouting mission does not belong to you.")
    return assignment


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


def _notify_pack_ready(assignment):
    from mgl.notifications import notify_user

    user = getattr(assignment.manager, "user", None)
    if user is None:
        return
    place = region_label(assignment.region)
    notify_user(
        user,
        source_key=f"scout-ready-{assignment.id}",
        notification_type="SCOUTING",
        title="SCOUT REPORT READY",
        message=(
            f"Your {assignment.get_tier_display()} Scout has returned from {place}. "
            "Your scouting pack is ready to open."
        ),
        action_url=f"{reverse('scouting')}?pack={assignment.id}",
        action_label="OPEN PACK",
        team=_club_for_manager(assignment.manager),
    )


@transaction.atomic
def complete_ready_assignments(manager, now=None):
    """Mark due missions READY and notify. Does not reveal or assign the player."""
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
    ready = []
    notices = []
    for assignment in due:
        if assignment.player_id is None:
            try:
                assignment.player = _claim_unreleased_player(
                    assignment.tier, assignment.region, assignment.position
                )
            except ValueError as exc:
                assignment.status = ScoutAssignment.COMPLETE
                assignment.completed_at = now
                assignment.save(update_fields=["status", "completed_at"])
                notices.append(str(exc))
                continue
        assignment.status = ScoutAssignment.READY
        assignment.save(update_fields=["player", "status"])
        _notify_pack_ready(assignment)
        ready.append(assignment)
        notices.append(
            f"Your {assignment.get_tier_display()} scout report is ready. Open the scouting pack to reveal the player."
        )
    return ready, notices


@transaction.atomic
def dispatch_scout(manager, tier, region="", position=""):
    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    region = validate_region(region)
    position = validate_position(position)
    team = _club_for_manager(manager)
    _assert_roster_space(team)

    profile = get_or_create_scout_profile(manager)
    now = timezone.now()
    complete_ready_assignments(manager, now=now)

    busy = ScoutAssignment.objects.filter(
        manager=manager,
        tier=tier,
        status__in=ACTIVE_STATUSES,
    ).exists()
    if busy:
        raise ValueError("That scout is still on assignment.")

    player = _claim_unreleased_player(tier, region, position)
    _assert_roster_space(_club_for_manager(manager))
    level = profile.scout_level or STARTING_LEVEL
    wait = cooldown_hours(tier, level)
    try:
        with transaction.atomic():
            assignment = ScoutAssignment.objects.create(
                manager=manager,
                club=team,
                tier=tier,
                level=level,
                region=region,
                position=position,
                player=player,
                ready_at=now + timedelta(hours=float(wait)),
                status=ScoutAssignment.PENDING,
            )
    except IntegrityError as exc:
        raise ValueError(
            "No available FC26 player matches that scout range, region and position."
        ) from exc
    return assignment


@transaction.atomic
def open_scout_pack(manager, assignment):
    assignment = ScoutAssignment.objects.select_for_update().get(pk=_owned_assignment(manager, assignment).pk)
    if assignment.status != ScoutAssignment.READY:
        raise ValueError("That scouting pack is not ready to open.")
    if assignment.player_id is None:
        raise ValueError("That scouting pack has no player to reveal.")
    assignment.status = ScoutAssignment.OPENED
    assignment.save(update_fields=["status"])
    return assignment


@transaction.atomic
def send_scout_to_team(manager, assignment):
    assignment = ScoutAssignment.objects.select_for_update().get(pk=_owned_assignment(manager, assignment).pk)
    if assignment.status != ScoutAssignment.OPENED:
        raise ValueError("Open the scouting pack before sending the player to your club.")
    team = _club_for_manager(manager)
    _assert_roster_space(team)
    player = Player.objects.select_for_update().get(pk=assignment.player_id)
    try:
        assign_player(player, team, source="SCOUT", reference=f"scout:{assignment.id}")
    except ValueError as exc:
        message = str(exc)
        if "roster limit" in message.lower() or "30-player" in message:
            raise SquadFullError(SQUAD_FULL_MESSAGE) from exc
        raise
    now = timezone.now()
    assignment.status = ScoutAssignment.COMPLETE
    assignment.completed_at = now
    assignment.save(update_fields=["status", "completed_at"])
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
    create_news(
        NewsPost.SCOUTING,
        f"{player.name} recruited",
        f"{team.name} recruited {player.name} through the MGL scouting network.",
        team=team,
    )
    return report


@transaction.atomic
def release_scout_player(manager, assignment):
    assignment = ScoutAssignment.objects.select_for_update().get(pk=_owned_assignment(manager, assignment).pk)
    if assignment.status != ScoutAssignment.OPENED:
        raise ValueError("Open the scouting pack before releasing the player.")
    player = assignment.player
    now = timezone.now()
    assignment.status = ScoutAssignment.COMPLETE
    assignment.completed_at = now
    assignment.save(update_fields=["status", "completed_at"])
    report = ScoutReport.objects.create(
        manager=manager,
        player=player,
        assignment=assignment,
        tier=assignment.tier,
        level=assignment.level,
        region=assignment.region,
        position=assignment.position,
        recruited=False,
        club=None,
    )
    return report
