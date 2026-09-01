"""Owner-configurable UFL rules. Frontend must never hard-code these values."""

from decimal import Decimal, InvalidOperation
from django.core.exceptions import ObjectDoesNotExist
from django.db.utils import OperationalError, ProgrammingError

from accounts.models import User
from mgl.permissions import approved_manager


DEFAULT_STARTING_TOKENS = Decimal("20")
UFL_ROSTER_LIMIT = 30
DEFAULT_MAX_SQUAD = UFL_ROSTER_LIMIT
DEFAULT_STARTING_SQUAD = UFL_ROSTER_LIMIT
DEFAULT_MAX_LISTINGS = 5
DEFAULT_LISTINGS_PER_24H = 3
DEFAULT_AUCTION_DURATIONS = (30, 60, 90, 120)
DEFAULT_AUCTION_LISTINGS_PER_24H = 3
DEFAULT_PRESS_REWARD = Decimal("0.50")
DEFAULT_PRESS_PER_24H = 4
DEFAULT_SCOUT_DURATIONS = (1, 3, 6, 12, 24, 48, 72)
DEFAULT_SCOUT_COSTS = {
    1: Decimal("1"),
    3: Decimal("2"),
    6: Decimal("3"),
    12: Decimal("4"),
    24: Decimal("5"),
    48: Decimal("8"),
    72: Decimal("10"),
}

# Legacy live generator (do not apply on production from this module).
LEGACY_SQUAD_SHAPE = (
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

# Official locked UFL 30-player starting squad (DEC-030).
UFL_SQUAD_SHAPE = (
    ("GK", 2),
    ("CB", 4),
    ("RB", 2),
    ("LB", 2),
    ("RWB", 2),
    ("LWB", 2),
    ("CDM", 2),
    ("CM", 2),
    ("CAM", 2),
    ("LM", 2),
    ("RM", 2),
    ("LW", 2),
    ("RW", 2),
    ("ST", 2),
)

OFFICIAL_STARTING_SQUAD_SIZE = sum(count for _position, count in UFL_SQUAD_SHAPE)


def official_starting_structure():
    """Ordered official starting slots: [{"code": "GK", "required": 2}, ...]."""
    return [{"code": code, "required": count} for code, count in UFL_SQUAD_SHAPE]


UFL_MIN_OVR = 64
UFL_MAX_OVR = 69


class SettingsProxy:
    starting_tokens = DEFAULT_STARTING_TOKENS
    max_squad_size = DEFAULT_MAX_SQUAD
    starting_squad_size = DEFAULT_STARTING_SQUAD
    max_active_listings = DEFAULT_MAX_LISTINGS
    listings_per_24h = DEFAULT_LISTINGS_PER_24H
    allow_manager_auctions = True
    scout_can_recruit = True
    scout_requires_tokens = False
    max_scouts_per_club = 1
    auction_durations = "30,60,90,120"
    scout_durations = "1,3,6,12,24,48,72"
    auction_listings_per_24h = DEFAULT_AUCTION_LISTINGS_PER_24H
    press_reward = DEFAULT_PRESS_REWARD
    press_per_24h = DEFAULT_PRESS_PER_24H


def _parse_int_list(raw, fallback):
    if not raw:
        return tuple(fallback)
    values = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            continue
    return tuple(values) or tuple(fallback)


def get_league_settings():
    try:
        from mgl.models import LeagueSettings

        row = LeagueSettings.objects.order_by("id").first()
        if row is None:
            row = LeagueSettings.objects.create()
        return row
    except (OperationalError, ProgrammingError, ObjectDoesNotExist):
        return SettingsProxy()


def starting_tokens():
    try:
        return Decimal(get_league_settings().starting_tokens)
    except (InvalidOperation, TypeError, AttributeError):
        return DEFAULT_STARTING_TOKENS


def max_squad_size():
    configured = int(getattr(get_league_settings(), "max_squad_size", DEFAULT_MAX_SQUAD) or DEFAULT_MAX_SQUAD)
    # Legacy LeagueSettings rows stored 28. Never silently cap below the locked UFL roster.
    return max(configured, UFL_ROSTER_LIMIT)


def max_active_listings():
    return int(
        getattr(get_league_settings(), "max_active_listings", DEFAULT_MAX_LISTINGS)
        or DEFAULT_MAX_LISTINGS
    )


def listings_per_24h():
    return int(
        getattr(get_league_settings(), "listings_per_24h", DEFAULT_LISTINGS_PER_24H)
        or DEFAULT_LISTINGS_PER_24H
    )


def allow_manager_auctions():
    return bool(getattr(get_league_settings(), "allow_manager_auctions", True))


def scout_can_recruit():
    return True


def auction_listings_per_24h():
    return int(
        getattr(get_league_settings(), "auction_listings_per_24h", DEFAULT_AUCTION_LISTINGS_PER_24H)
        or DEFAULT_AUCTION_LISTINGS_PER_24H
    )


def press_reward():
    try:
        return Decimal(getattr(get_league_settings(), "press_reward", DEFAULT_PRESS_REWARD))
    except (InvalidOperation, TypeError, AttributeError):
        return DEFAULT_PRESS_REWARD


def press_per_24h():
    return int(
        getattr(get_league_settings(), "press_per_24h", DEFAULT_PRESS_PER_24H)
        or DEFAULT_PRESS_PER_24H
    )


def scout_requires_tokens():
    return bool(getattr(get_league_settings(), "scout_requires_tokens", False))


def auction_duration_choices():
    values = _parse_int_list(
        getattr(get_league_settings(), "auction_durations", ""),
        DEFAULT_AUCTION_DURATIONS,
    )
    return tuple((minutes, f"{minutes} minutes") for minutes in values)


def scout_duration_hours():
    return _parse_int_list(
        getattr(get_league_settings(), "scout_durations", ""),
        DEFAULT_SCOUT_DURATIONS,
    )


def scout_mission_cost(hours):
    hours = int(hours)
    return DEFAULT_SCOUT_COSTS.get(hours, Decimal(str(max(1, hours // 6))))


def effective_roster_limit(team):
    stored = int(getattr(team, "roster_limit", 0) or 0)
    configured = max_squad_size()
    return max(stored, configured, UFL_ROSTER_LIMIT)


def ufl_access_role(user):
    """Map live accounts onto the UFL PUBLIC / MEMBER / MANAGER / ADMIN / OWNER grid."""
    if user is None or not getattr(user, "is_authenticated", False):
        return "PUBLIC"
    role = getattr(user, "role", None)
    if role == User.OWNER:
        return "OWNER"
    if role == User.ADMIN:
        return "ADMIN"
    if approved_manager(user) is not None and getattr(user, "managed_team", None):
        return "MANAGER"
    return "MEMBER"


def is_member(user):
    return ufl_access_role(user) == "MEMBER"


def is_appointed_manager(user):
    return ufl_access_role(user) == "MANAGER"
