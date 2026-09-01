"""FC26 scouting: one manager-wide HQ level, reserved unreleased players, pack reveal."""

from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from players.models import Player
from teams.models import Team
from auctions.models import PlayerAuction

from .market import club_for_user, debit_manager_tokens
from .models import (
    NewsPost,
    PlayerListing,
    ScoutAssignment,
    ScoutProfile,
    ScoutReport,
    ScoutSquadException,
    ScoutWatchlist,
)
from .player_state import is_ufl_free_agent, market_status, unassigned_players
from .regions import (
    REGION_MENU,
    SCOUT_POSITIONS,
    nations_for_region,
    region_keys,
    region_label,
)
from .permissions import is_owner_or_admin
from .services import assign_player, create_news


BRONZE = ScoutAssignment.BRONZE
SILVER = ScoutAssignment.SILVER
GOLD = ScoutAssignment.GOLD
ELITE = ScoutAssignment.ELITE

TIER_RANGES = {
    BRONZE: (45, 60),
    SILVER: (60, 72),
    GOLD: (73, 81),
    ELITE: (82, 91),
}
BASE_HOURS = {
    BRONZE: Decimal("8"),
    SILVER: Decimal("16"),
    GOLD: Decimal("32"),
    ELITE: Decimal("48"),
}
# Official UFL scout levels. L1 is granted at hire (listed cost 10 TKN).
# L2/L3 use the published flat reductions. L4 does not add another flat
# cut — it halves Gold and Elite only. Bronze/Silver keep the L3 reduction.
LEVEL_HOUR_REDUCTION = {
    1: Decimal("2"),
    2: Decimal("4"),
    3: Decimal("8"),
    4: Decimal("0"),
}
MIN_HOURS = Decimal("1")
UPGRADE_COSTS = {
    2: Decimal("18.00"),
    3: Decimal("25.00"),
    4: Decimal("25.00"),
}
LEVEL_COSTS = {
    1: Decimal("10.00"),
    2: Decimal("18.00"),
    3: Decimal("25.00"),
    4: Decimal("25.00"),
}
STARTING_LEVEL = 1
MAX_LEVEL = 4
SQUAD_LIMIT = 30
SQUAD_FULL_MESSAGE = "Your squad is full — maximum 30 players."


def _squad_limit():
    from mgl.ufl_settings import max_squad_size

    return max_squad_size()


def scout_attributes_for_level(level):
    level = max(STARTING_LEVEL, min(MAX_LEVEL, int(level or STARTING_LEVEL)))
    return {
        "judging_ability": min(5, 1 + level),
        "judging_potential": min(5, level),
        "position_knowledge": min(5, 2 + (level // 2)),
        "discovery_rate": min(5, level),
        "report_accuracy": min(5, 1 + level),
        "scouting_speed": min(5, level),
    }


def apply_scout_attributes(profile):
    values = scout_attributes_for_level(profile.scout_level)
    for key, value in values.items():
        setattr(profile, key, value)
    return values
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
        defaults={"scout_level": STARTING_LEVEL, **scout_attributes_for_level(STARTING_LEVEL)},
    )
    if not created and not profile.scout_level:
        profile.scout_level = STARTING_LEVEL
    if not created and not profile.judging_ability:
        apply_scout_attributes(profile)
        profile.save(
            update_fields=[
                "scout_level",
                "judging_ability",
                "judging_potential",
                "position_knowledge",
                "discovery_rate",
                "report_accuracy",
                "scouting_speed",
            ]
        )
    elif created:
        apply_scout_attributes(profile)
        profile.save()
    return profile


def manager_scout_level(manager):
    return get_or_create_scout_profile(manager).scout_level or STARTING_LEVEL


def scout_level_config(level):
    from mgl.models import ScoutLevelConfig

    ensure_default_scout_levels()
    level = int(level or STARTING_LEVEL)
    return ScoutLevelConfig.objects.filter(level=level).first()


def upgrade_cost_for(level):
    row = scout_level_config(level)
    if row is not None:
        return Decimal(str(row.upgrade_cost))
    return UPGRADE_COSTS.get(int(level), Decimal("0"))


def extra_reduction_percent(level):
    row = scout_level_config(level)
    if row is None:
        return Decimal("0")
    return Decimal(str(row.time_reduction_percent or 0))


def cooldown_hours(tier, level):
    if tier not in BASE_HOURS:
        raise ValueError("Unknown scout tier.")
    level = int(level or STARTING_LEVEL)
    if level < STARTING_LEVEL:
        level = STARTING_LEVEL
    if level > MAX_LEVEL:
        level = MAX_LEVEL
    if level >= 4 and tier in {GOLD, ELITE}:
        hours = BASE_HOURS[tier] / 2
    else:
        reduction = LEVEL_HOUR_REDUCTION.get(level, Decimal("0"))
        if level >= 4:
            reduction = LEVEL_HOUR_REDUCTION.get(3, Decimal("8"))
        hours = BASE_HOURS[tier] - reduction
    percent = extra_reduction_percent(level)
    if percent:
        hours = hours * (Decimal("1") - (percent / Decimal("100")))
    if hours < MIN_HOURS:
        hours = MIN_HOURS
    return hours


def hours_saved(level):
    level = int(level or STARTING_LEVEL)
    if level < STARTING_LEVEL:
        level = STARTING_LEVEL
    if level > MAX_LEVEL:
        level = MAX_LEVEL
    return LEVEL_HOUR_REDUCTION.get(level, Decimal("0"))


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


def ensure_default_scout_levels():
    from mgl.models import ScoutLevelConfig

    if ScoutLevelConfig.objects.exists():
        return list(ScoutLevelConfig.objects.order_by("level"))
    created = []
    defaults = (
        (1, Decimal("0.00"), Decimal("0.00")),
        (2, Decimal("18.00"), Decimal("0.00")),
        (3, Decimal("25.00"), Decimal("0.00")),
        (4, Decimal("25.00"), Decimal("0.00")),
    )
    for level, cost, percent in defaults:
        created.append(
            ScoutLevelConfig.objects.create(
                level=level,
                upgrade_cost=cost,
                time_reduction_percent=percent,
                result_count=4,
                select_count=1,
            )
        )
    return created


def next_upgrade(level):
    level = int(level or STARTING_LEVEL)
    if level >= MAX_LEVEL:
        return None
    nxt = level + 1
    cost = upgrade_cost_for(nxt)
    return {
        "level": nxt,
        "cost": cost,
        "cost_label": str(int(cost)) if cost == cost.to_integral_value() else str(cost),
        "times": scout_times(nxt),
        "hours_saved": hours_saved(nxt),
    }


def save_scout_level_config(
    *,
    actor,
    level,
    upgrade_cost=None,
    time_reduction_percent=None,
    result_count=None,
    select_count=None,
):
    from mgl.models import ScoutLevelConfig
    from mgl.tokens import validate_token_amount

    if not is_owner_or_admin(actor):
        raise ValueError("Only the Owner or Admin can configure scout levels.")
    level = int(level)
    if level < STARTING_LEVEL or level > MAX_LEVEL:
        raise ValueError("Scout level must be between 1 and 4.")
    ensure_default_scout_levels()
    row, _created = ScoutLevelConfig.objects.get_or_create(
        level=level,
        defaults={
            "upgrade_cost": UPGRADE_COSTS.get(level, Decimal("0")),
            "time_reduction_percent": Decimal("0"),
            "result_count": 4,
            "select_count": 1,
        },
    )
    if upgrade_cost is not None and upgrade_cost != "":
        row.upgrade_cost = validate_token_amount(upgrade_cost)
    if time_reduction_percent is not None and time_reduction_percent != "":
        percent = Decimal(str(time_reduction_percent))
        if percent < 0 or percent >= 100:
            raise ValueError("Time reduction must be between 0 and 99.99 percent.")
        row.time_reduction_percent = percent
    if result_count is not None and result_count != "":
        result_count = int(result_count)
        if result_count < 1:
            raise ValueError("A scout must return at least one player.")
        row.result_count = result_count
    if select_count is not None and select_count != "":
        select_count = int(select_count)
        if select_count < 1 or select_count > row.result_count:
            raise ValueError("The manager must select at least one scouted player.")
        row.select_count = select_count
    row.save()
    return row


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


def scout_countries():
    return list(
        Player.objects.exclude(nationality="")
        .order_by("nationality")
        .values_list("nationality", flat=True)
        .distinct()[:400]
    )


def validate_country(country):
    country = (country or "").strip()
    if not country or country.lower() == "anywhere":
        return ""
    return country


def _reserved_result_ids():
    from mgl.recruitment import reserved_player_ids

    return reserved_player_ids()


def _unavailable_player_ids():
    live_auctions = PlayerAuction.objects.filter(
        status__in=[PlayerAuction.PENDING, PlayerAuction.LIVE]
    ).values_list("player_id", flat=True)
    live_listings = PlayerListing.objects.filter(
        status__in=[PlayerListing.PENDING, PlayerListing.LIVE]
    ).values_list("player_id", flat=True)
    reserved = _reserved_result_ids()
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
    """Pick one unassigned player for this mission so two live reports do not reveal the same row.

    This is a discovery lock only. It does not transfer ownership, grant signing
    rights, or keep the player exclusive after the report is filed.
    """
    candidate_ids = list(
        eligible_players(tier, region, position).order_by("?").values_list("id", flat=True)[:25]
    )
    if not candidate_ids:
        raise ValueError("No available FC26 player matches that scout range, region and position.")
    for player_id in candidate_ids:
        locked = Player.objects.select_for_update().get(pk=player_id)
        if locked.mgl_team_id is not None or is_ufl_free_agent(locked):
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

    from mgl.ufl_settings import effective_roster_limit

    roster_limit = effective_roster_limit(team)
    current = roster_occupancy(team)
    if current >= roster_limit:
        raise SquadFullError(f"Your squad is full — maximum {roster_limit} players.")


def _owned_assignment(manager, assignment):
    if assignment is None:
        raise ValueError("That scouting mission was not found.")
    if assignment.manager_id != manager.id:
        raise ValueError("That scouting mission does not belong to you.")
    return assignment


@transaction.atomic
def upgrade_scout(manager):
    from mgl.services import debit_manager
    from mgl.tokens import validate_token_amount

    profile = get_or_create_scout_profile(manager)
    profile = ScoutProfile.objects.select_for_update().get(pk=profile.pk)
    current = profile.scout_level or STARTING_LEVEL
    if current >= MAX_LEVEL:
        raise ValueError("Your scouting network is already at maximum level.")
    nxt = current + 1
    cost = validate_token_amount(upgrade_cost_for(nxt))
    try:
        debit_manager(
            manager,
            cost,
            f"Scouting network level {nxt}",
            category="SCOUTING",
            reference=f"scout:upgrade:{manager.id}:{nxt}",
        )
    except ValueError as exc:
        if "enough tokens" in str(exc).lower():
            raise ValueError(
                f"You do not have enough tokens. Level {nxt} costs {cost} tokens."
            ) from exc
        raise
    profile.scout_level = nxt
    apply_scout_attributes(profile)
    profile.save(
        update_fields=[
            "scout_level",
            "judging_ability",
            "judging_potential",
            "position_knowledge",
            "discovery_rate",
            "report_accuracy",
            "scouting_speed",
        ]
    )
    now = timezone.now()
    for assignment in ScoutAssignment.objects.select_for_update().filter(
        manager=manager, status=ScoutAssignment.PENDING
    ):
        wait = cooldown_hours(assignment.tier, nxt)
        assignment.level = nxt
        assignment.duration_hours = wait
        assignment.ready_at = assignment.started_at + timedelta(hours=float(wait))
        assignment.save(update_fields=["level", "duration_hours", "ready_at"])
        if assignment.ready_at <= now:
            _reveal_scout_results(assignment, now)
    return profile, nxt, cost


def _notify_scout_result(assignment, title, message, label="VIEW SCOUTING"):
    from mgl.notifications import notify_user

    user = getattr(assignment.manager, "user", None)
    if user is None:
        return
    notify_user(
        user,
        source_key=f"scout-result-{assignment.id}",
        notification_type="SCOUTING",
        title=title,
        message=message,
        action_url=reverse("scouting"),
        action_label=label,
        team=_club_for_manager(assignment.manager),
        player=assignment.player,
    )


def _write_scout_report(assignment, recruited, outcome):
    return ScoutReport.objects.create(
        manager=assignment.manager,
        player=assignment.player,
        assignment=assignment,
        tier=assignment.tier,
        level=assignment.level,
        region=assignment.region,
        country=assignment.country,
        position=assignment.position,
        outcome=outcome,
        recruited=recruited,
        club=assignment.club if recruited else None,
        confidence=assignment.confidence,
        recommendation="Signed" if recruited else "Pending league office",
        estimated_potential_low=assignment.estimated_potential_low,
        estimated_potential_high=assignment.estimated_potential_high,
    )


def _finish_assignment(assignment, now, outcome):
    assignment.status = ScoutAssignment.COMPLETE
    assignment.completed_at = now
    assignment.outcome = outcome
    assignment.save(update_fields=["status", "completed_at", "outcome", "player"])


def _pick_scout_results(assignment, count):
    region = assignment.country or assignment.region
    pool = list(
        eligible_players(assignment.tier, region, assignment.position).values_list("id", flat=True)
    )
    if not pool:
        return []
    shuffled = random_sample(pool, min(len(pool), max(count * 4, count)))
    if len(pool) <= count:
        shuffled = list(pool)
    claimed = []
    reserved = _reserved_result_ids()
    for player_id in shuffled:
        if player_id in reserved:
            continue
        player = Player.objects.select_for_update().get(pk=player_id)
        if player.mgl_team_id or is_ufl_free_agent(player) or player.id in reserved:
            continue
        claimed.append(player.id)
        reserved.add(player.id)
        if len(claimed) >= count:
            break
    return claimed


def random_sample(pool, count):
    import random

    return random.sample(list(pool), count)


def _reveal_scout_results(assignment, now):
    from mgl.player_state import roster_occupancy
    from mgl.ufl_settings import effective_roster_limit, scout_result_count

    team = assignment.club or _club_for_manager(assignment.manager)
    if team is None:
        _finish_assignment(assignment, now, ScoutAssignment.OUTCOME_NO_PLAYER)
        return assignment, "Your club is no longer valid, so the scout could not deliver a player."
    count = scout_result_count()
    row = scout_level_config(assignment.level)
    if row is not None:
        count = int(row.result_count or count)
    player_ids = _pick_scout_results(assignment, count)
    if not player_ids:
        _finish_assignment(assignment, now, ScoutAssignment.OUTCOME_NO_PLAYER)
        return assignment, "No available FC26 player matches that scout range, region and position."
    assignment.player_ids = [int(pk) for pk in player_ids]
    assignment.player_id = assignment.player_ids[0]
    assignment.status = ScoutAssignment.READY
    assignment.reveal_stage = "COMPLETE"
    assignment.club = team
    assignment.save(update_fields=["player_ids", "player", "status", "reveal_stage", "club"])
    limit = effective_roster_limit(team)
    if roster_occupancy(team) >= limit:
        assignment.outcome = ScoutAssignment.OUTCOME_SQUAD_FULL
        assignment.status = ScoutAssignment.COMPLETE
        assignment.completed_at = now
        assignment.save(update_fields=["outcome", "status", "completed_at"])
        ScoutSquadException.objects.update_or_create(
            assignment=assignment,
            defaults={
                "manager": assignment.manager,
                "club": team,
                "player": assignment.player,
                "status": ScoutSquadException.PENDING,
            },
        )
        _write_scout_report(assignment, False, ScoutAssignment.OUTCOME_SQUAD_FULL)
        _notify_scout_result(
            assignment,
            "SCOUT RETURNED — SQUAD FULL",
            "Scout results are waiting but your squad is already full. The league office must resolve this.",
        )
        return assignment, (
            "Players were discovered but your squad is full. "
            "The league office must resolve this before a player can join."
        )
    _notify_scout_result(
        assignment,
        "SCOUT RESULTS READY",
        f"Your scout returned {len(assignment.player_ids)} unsigned players. Choose one.",
    )
    return assignment, f"Your scout returned {len(assignment.player_ids)} players. Choose one."


@transaction.atomic
def choose_scout_player(manager, assignment_id, player_id):
    from mgl.player_state import roster_occupancy
    from mgl.ufl_settings import effective_roster_limit, scout_can_recruit
    from mgl.audit import log_ocm_action

    if not scout_can_recruit():
        raise ValueError("Scouting is set to discovery only. The league office has disabled recruitment.")
    assignment = (
        ScoutAssignment.objects.select_for_update()
        .select_related("manager", "club")
        .filter(pk=assignment_id, manager=manager)
        .first()
    )
    assignment = _owned_assignment(manager, assignment)
    if assignment.status != ScoutAssignment.READY:
        raise ValueError("Those scout results are not ready to choose from.")
    try:
        player_id = int(player_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Choose one of the scouted players.") from exc
    if player_id not in [int(pk) for pk in (assignment.player_ids or [])]:
        raise ValueError("That player was not in this scout result.")
    team = assignment.club or _club_for_manager(manager)
    if team is None:
        raise ValueError("You must manage a club to recruit a scouted player.")
    team = Team.objects.select_for_update().get(pk=team.pk)
    limit = effective_roster_limit(team)
    if roster_occupancy(team) >= limit:
        raise SquadFullError(f"Your squad is full — maximum {limit} players.")
    player = Player.objects.select_for_update().filter(pk=player_id).first()
    if player is None or player.mgl_team_id or is_ufl_free_agent(player):
        raise ValueError("That player is no longer unsigned.")
    assign_player(player, team, source="SCOUT", reference=f"scout:{assignment.id}")
    assignment.player = player
    assignment.club = team
    _finish_assignment(assignment, timezone.now(), ScoutAssignment.OUTCOME_RECRUITED)
    _write_scout_report(assignment, True, ScoutAssignment.OUTCOME_RECRUITED)
    create_news(
        NewsPost.SCOUTING,
        f"{player.name} joins {team.name}",
        f"{team.name} signed {player.name} after a {assignment.get_tier_display()} scouting mission.",
        team=team,
    )
    from mgl.notifications import notify_user

    user = getattr(manager, "user", None)
    if user is not None:
        notify_user(
            user,
            source_key=f"scout-chosen-{assignment.id}",
            notification_type="SCOUTING",
            title="SCOUT RECRUITED A PLAYER",
            message=f"{player.name} has joined {team.name}.",
            action_url=reverse("scouting"),
            action_label="VIEW SQUAD",
            team=team,
            player=player,
        )
    log_ocm_action(
        getattr(manager, "user", None),
        action="scout.recruited",
        object_type="ScoutAssignment",
        object_id=assignment.pk,
        object_label=player.name,
        new_value=team.name,
        summary=f"{player.name} recruited to {team.name} via {assignment.tier} scout.",
    )
    return assignment


def players_for_assignment(assignment):
    if assignment is None:
        return []
    ids = [int(pk) for pk in (assignment.player_ids or [])]
    found = {
        player.id: player
        for player in Player.objects.filter(pk__in=ids).select_related("mgl_team")
    }
    return [found[pk] for pk in ids if pk in found]


@transaction.atomic
def complete_ready_assignments(manager, now=None):
    """When the timer ends, reserve unsigned results. The manager then chooses one."""
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
        completed, notice = _reveal_scout_results(assignment, now)
        ready.append(completed)
        notices.append(notice)
    return ready, notices


def complete_due_scouts(now=None):
    now = now or timezone.now()
    manager_ids = list(
        ScoutAssignment.objects.filter(
            status=ScoutAssignment.PENDING,
            ready_at__lte=now,
        )
        .values_list("manager_id", flat=True)
        .distinct()
    )
    from managers.models import ManagerApplication

    results = []
    for manager in ManagerApplication.objects.filter(pk__in=manager_ids):
        results.extend(complete_ready_assignments(manager, now=now)[0])
    return results


def _apply_progress_estimates(assignment, stage="HIDDEN"):
    player = assignment.player
    level = int(assignment.level or STARTING_LEVEL)
    spread = max(1, 6 - level)
    actual = int(getattr(player, "overall", 0) or 0) if player else 66
    potential = min(99, actual + max(1, 4 - (level // 2)))
    if stage == "HIDDEN":
        assignment.estimated_ovr_low = max(45, actual - spread)
        assignment.estimated_ovr_high = min(99, actual + spread)
        assignment.estimated_potential_low = None
        assignment.estimated_potential_high = None
        assignment.confidence = max(20, 40 + level * 6)
    elif stage == "PARTIAL":
        assignment.estimated_ovr_low = actual
        assignment.estimated_ovr_high = actual
        assignment.estimated_potential_low = max(actual, potential - 2)
        assignment.estimated_potential_high = potential + 1
        assignment.confidence = max(40, 55 + level * 7)
    else:
        assignment.estimated_ovr_low = actual
        assignment.estimated_ovr_high = actual
        assignment.estimated_potential_low = potential
        assignment.estimated_potential_high = potential
        assignment.confidence = min(99, 70 + level * 6)


def scout_availability_label(player):
    status = market_status(player)
    if status == "UNASSIGNED":
        return "Player unavailable for direct purchase. Watch for Auction."
    if status in {"FREE AGENT", "FREE_AGENT"}:
        return "Player available for a future Admin auction."
    if status == "TRANSFER LISTED":
        return "Make Offer"
    if status == "AUCTION":
        return "View Auction"
    if status in {"ASSIGNED", "CLUB PLAYER", "IN NEGOTIATION"}:
        return "Contact Club / Make Transfer Offer"
    return status


@transaction.atomic
def add_to_watchlist(manager, player, report=None, notes=""):
    row, _created = ScoutWatchlist.objects.get_or_create(
        manager=manager,
        player=player,
        defaults={"report": report, "notes": notes},
    )
    if report and row.report_id != getattr(report, "pk", None):
        row.report = report
        row.save(update_fields=["report"])
    return row


def watchlist_for(manager):
    return (
        ScoutWatchlist.objects.filter(manager=manager)
        .select_related("player", "player__mgl_team", "report")
        .order_by("-created_at")
    )


@transaction.atomic
def dispatch_scout(manager, tier, region="", position="", duration_hours=None, country=""):
    from mgl.ufl_settings import scout_mission_cost, scout_requires_tokens

    if tier not in TIER_RANGES:
        raise ValueError("Unknown scout tier.")
    country = validate_country(country)
    region = validate_region(region) if not country else ""
    position = validate_position(position)
    team = _club_for_manager(manager)
    if team is None:
        raise ValueError("You must manage a club before sending a scout.")
    search = country or region
    if not eligible_players(tier, search, position).exists():
        raise ValueError("No available FC26 player matches that scout range, country and position.")

    profile = get_or_create_scout_profile(manager)
    profile = ScoutProfile.objects.select_for_update().get(pk=profile.pk)
    now = timezone.now()
    complete_ready_assignments(manager, now=now)

    busy = (
        ScoutAssignment.objects.select_for_update()
        .filter(manager=manager, status__in=ACTIVE_STATUSES)
        .exists()
    )
    if busy:
        raise ValueError(
            "You already have an active scout. Finish that assignment before sending another."
        )

    level = profile.scout_level or STARTING_LEVEL
    wait = cooldown_hours(tier, level)
    if duration_hours:
        try:
            wait = Decimal(str(duration_hours))
        except Exception:
            wait = cooldown_hours(tier, level)
    cost = scout_mission_cost(int(wait)) if scout_requires_tokens() else Decimal("0")
    if cost and scout_requires_tokens():
        try:
            debit_manager_tokens(manager, cost, f"Scouting mission {tier} {int(wait)}h")
        except ValueError as exc:
            if "enough tokens" in str(exc).lower():
                raise ValueError(
                    f"You do not have enough tokens. This mission costs {cost} tokens."
                ) from exc
            raise
    try:
        with transaction.atomic():
            assignment = ScoutAssignment.objects.create(
                manager=manager,
                club=team,
                tier=tier,
                level=level,
                region=region,
                country=country,
                position=position,
                player=None,
                ready_at=now + timedelta(hours=float(wait)),
                status=ScoutAssignment.PENDING,
                duration_hours=wait,
                token_cost=cost,
                reveal_stage="HIDDEN",
            )
            _apply_progress_estimates(assignment, stage="HIDDEN")
            assignment.save(
                update_fields=[
                    "estimated_ovr_low",
                    "estimated_ovr_high",
                    "estimated_potential_low",
                    "estimated_potential_high",
                    "confidence",
                    "reveal_stage",
                ]
            )
    except IntegrityError as exc:
        if ScoutAssignment.objects.filter(
            manager=manager, status__in=ACTIVE_STATUSES
        ).exists():
            raise ValueError(
                "You already have an active scout. Finish that assignment before sending another."
            ) from exc
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
    assignment.reveal_stage = "COMPLETE"
    _apply_progress_estimates(assignment, stage="COMPLETE")
    assignment.save(
        update_fields=[
            "status",
            "reveal_stage",
            "estimated_ovr_low",
            "estimated_ovr_high",
            "estimated_potential_low",
            "estimated_potential_high",
            "confidence",
        ]
    )
    return assignment


def _assert_admin_scout_assign(user):
    if not is_owner_or_admin(user):
        raise ValueError("Only the league office can resolve a scouting exception.")


@transaction.atomic
def send_scout_to_team(manager, assignment, actor=None):
    """Owner/Admin correction for a squad-full exception or leftover pack."""
    actor = actor or getattr(manager, "user", None)
    _assert_admin_scout_assign(actor)
    assignment = ScoutAssignment.objects.select_for_update().get(pk=_owned_assignment(manager, assignment).pk)
    if assignment.status not in {ScoutAssignment.OPENED, ScoutAssignment.COMPLETE, ScoutAssignment.SQUAD_FULL}:
        if assignment.outcome != ScoutAssignment.OUTCOME_SQUAD_FULL:
            raise ValueError("That scouting result is not waiting for a league-office assignment.")
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
        confidence=assignment.confidence,
        recommendation="Strong prospect" if (assignment.confidence or 0) >= 80 else "Worth following",
        estimated_potential_low=assignment.estimated_potential_low,
        estimated_potential_high=assignment.estimated_potential_high,
    )
    create_news(
        NewsPost.SCOUTING,
        f"{player.name} assigned by league office",
        f"{team.name} received {player.name} after an Owner/Admin scouting correction.",
        team=team,
    )
    from mgl.audit import log_ocm_action

    log_ocm_action(
        getattr(manager, "user", None),
        action="scout.admin_assign",
        object_type="ScoutAssignment",
        object_id=assignment.pk,
        object_label=player.name,
        new_value=team.name,
        summary=f"{player.name} assigned to {team.name} by Owner/Admin via {assignment.tier} scout.",
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
        confidence=assignment.confidence,
        recommendation="Worth following" if (assignment.confidence or 0) >= 60 else "Monitor",
        estimated_potential_low=assignment.estimated_potential_low,
        estimated_potential_high=assignment.estimated_potential_high,
    )
    from mgl.audit import log_ocm_action

    log_ocm_action(
        getattr(manager, "user", None),
        action="scout.report",
        object_type="ScoutAssignment",
        object_id=assignment.pk,
        object_label=getattr(player, "name", ""),
        new_value="DISCOVERED",
        summary=(
            f"{getattr(player, 'name', 'Player')} scout report filed. "
            "Ownership unchanged."
        ),
    )
    return report


@transaction.atomic
def file_scout_report(manager, assignment, watchlist=False):
    """Legacy discovery report for leftover pack missions."""
    report = release_scout_player(manager, assignment)
    if watchlist and report.player_id:
        add_to_watchlist(manager, report.player, report=report)
    return report


@transaction.atomic
def resolve_scout_exception(exception, actor, assign=True, note=""):
    exception = ScoutSquadException.objects.select_for_update().get(pk=exception.pk)
    if not is_owner_or_admin(actor):
        raise ValueError("Only the league office can resolve a scouting exception.")
    if exception.status != ScoutSquadException.PENDING:
        return exception
    player = Player.objects.select_for_update().get(pk=exception.player_id)
    now = timezone.now()
    if assign:
        send_scout_to_team(exception.manager, exception.assignment, actor=actor)
        exception.status = ScoutSquadException.ASSIGNED
    else:
        if player.mgl_team_id is None:
            player.is_free_agent = False
            player.save(update_fields=["is_free_agent"])
        exception.status = ScoutSquadException.RELEASED
    exception.resolved_at = now
    exception.resolved_by = actor
    exception.note = note or ""
    exception.save(update_fields=["status", "resolved_at", "resolved_by", "note"])
    return exception
