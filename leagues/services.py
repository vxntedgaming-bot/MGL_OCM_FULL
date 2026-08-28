from django.db import transaction
from django.db.models import Q

from leagues.models import League
from teams.models import Team


PREMIER_NAME = "Premier League"
PREMIER_SHORT = "PL"
CHAMPIONSHIP_NAME = "Championship"
CHAMPIONSHIP_SHORT = "CH"
LEAGUE_ONE_NAME = "League One"
LEAGUE_ONE_SHORT = "L1"

ACTIVE_DIVISIONS = (
    (PREMIER_NAME, PREMIER_SHORT),
    (CHAMPIONSHIP_NAME, CHAMPIONSHIP_SHORT),
    (LEAGUE_ONE_NAME, LEAGUE_ONE_SHORT),
)

INACTIVE_MARKERS = (
    Q(short_name__iexact="MLS")
    | Q(name__iexact="MLS")
    | Q(short_name__iexact="SL2")
    | Q(name__icontains="Super League 2")
    | Q(name__iexact="Super League")
)


def _get_or_rename_premier():
    league = (
        League.objects.filter(short_name__iexact=PREMIER_SHORT).order_by("id").first()
        or League.objects.filter(name__iexact=PREMIER_NAME).order_by("id").first()
        or League.objects.filter(short_name__iexact="SL1").order_by("id").first()
        or League.objects.filter(name__iexact="Super League 1").order_by("id").first()
    )
    if league is None:
        return League.objects.create(
            name=PREMIER_NAME,
            short_name=PREMIER_SHORT,
            season="1",
            is_active=True,
        )
    changed = []
    if league.name != PREMIER_NAME:
        league.name = PREMIER_NAME
        changed.append("name")
    if league.short_name != PREMIER_SHORT:
        league.short_name = PREMIER_SHORT
        changed.append("short_name")
    if not league.is_active:
        league.is_active = True
        changed.append("is_active")
    if changed:
        league.save(update_fields=changed)
    return league


def _ensure_division(name, short_name):
    league = (
        League.objects.filter(short_name__iexact=short_name).order_by("id").first()
        or League.objects.filter(name__iexact=name).order_by("id").first()
    )
    if league is None:
        return League.objects.create(
            name=name,
            short_name=short_name,
            season="1",
            is_active=True,
        )
    changed = []
    if league.name != name:
        league.name = name
        changed.append("name")
    if league.short_name != short_name:
        league.short_name = short_name
        changed.append("short_name")
    if not league.is_active:
        league.is_active = True
        changed.append("is_active")
    if changed:
        league.save(update_fields=changed)
    return league


@transaction.atomic
def ensure_premier_league():
    """
    Premier League is the top active division.

    Existing Super League 1 rows are renamed in place so team IDs, squads
    and fixtures stay attached. Championship and League One are created
    empty for later population. MLS and Super League 2 stay in the database
    but are marked inactive. Teams on those inactive rows are not deleted.
    """

    premier = _get_or_rename_premier()
    _ensure_division(CHAMPIONSHIP_NAME, CHAMPIONSHIP_SHORT)
    _ensure_division(LEAGUE_ONE_NAME, LEAGUE_ONE_SHORT)

    keep_ids = set(
        League.objects.filter(
            short_name__in=[PREMIER_SHORT, CHAMPIONSHIP_SHORT, LEAGUE_ONE_SHORT]
        ).values_list("id", flat=True)
    )
    League.objects.filter(INACTIVE_MARKERS).update(is_active=False)
    League.objects.exclude(pk__in=keep_ids).filter(is_active=True).update(is_active=False)
    return premier


def ensure_super_league_1():
    """Compatibility alias: Super League 1 was renamed to Premier League."""
    return ensure_premier_league()


def active_league():
    return (
        League.objects.filter(is_active=True, short_name__iexact=PREMIER_SHORT).first()
        or League.objects.filter(is_active=True, short_name__iexact="SL1").first()
        or League.objects.filter(is_active=True).order_by("id").first()
    )


def active_divisions():
    ensure_premier_league()
    order = {PREMIER_SHORT: 0, CHAMPIONSHIP_SHORT: 1, LEAGUE_ONE_SHORT: 2}
    leagues = list(
        League.objects.filter(
            is_active=True,
            short_name__in=[PREMIER_SHORT, CHAMPIONSHIP_SHORT, LEAGUE_ONE_SHORT],
        ).prefetch_related("teams__manager")
    )
    leagues.sort(key=lambda row: order.get(row.short_name, 9))
    return leagues
