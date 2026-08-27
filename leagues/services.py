from django.db import transaction

from leagues.models import League
from teams.models import Team


SL1_NAME = "Super League 1"
SL1_SHORT = "SL1"


@transaction.atomic
def ensure_super_league_1():
    """
    Keep one active competition: Super League 1.

    Existing clubs, squads, tokens and history are preserved.
    Other league rows (including Super League 2) stay in the database
    but are marked inactive so they can be turned on later.
    """

    league = (
        League.objects.filter(short_name__iexact=SL1_SHORT).order_by("id").first()
        or League.objects.filter(name__iexact=SL1_NAME).order_by("id").first()
    )
    if league is None:
        league = League.objects.create(
            name=SL1_NAME,
            short_name=SL1_SHORT,
            season="1",
            is_active=True,
        )
    else:
        changed = []
        if league.name != SL1_NAME:
            league.name = SL1_NAME
            changed.append("name")
        if league.short_name != SL1_SHORT:
            league.short_name = SL1_SHORT
            changed.append("short_name")
        if not league.is_active:
            league.is_active = True
            changed.append("is_active")
        if changed:
            league.save(update_fields=changed)

    League.objects.exclude(pk=league.pk).filter(is_active=True).update(is_active=False)
    Team.objects.exclude(league_id=league.id).update(league=league)

    from mgl.models import Fixture

    Fixture.objects.exclude(league_id=league.id).update(league=league)
    return league


def active_league():
    return (
        League.objects.filter(is_active=True, short_name__iexact=SL1_SHORT).first()
        or League.objects.filter(is_active=True).order_by("id").first()
    )
