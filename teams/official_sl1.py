from decimal import Decimal

from leagues.services import ensure_super_league_1
from teams.models import Team


OFFICIAL_SL1_CLUBS = (
    ("Real Madrid", "RMA"),
    ("Barcelona", "BAR"),
    ("Atletico Madrid", "ATM"),
    ("Manchester United", "MUN"),
    ("Chelsea", "CHE"),
    ("Manchester City", "MCI"),
    ("Arsenal", "ARS"),
    ("Liverpool", "LIV"),
    ("Tottenham", "TOT"),
    ("Paris Saint-Germain", "PSG"),
    ("Lyon", "OL"),
    ("Marseille", "OM"),
    ("Bayer Leverkusen", "B04"),
    ("Bayern Munich", "FCB"),
)

OFFICIAL_SL1_SHORT_NAMES = tuple(short for _name, short in OFFICIAL_SL1_CLUBS)
STARTING_TOKENS = Decimal("50.00")


def ensure_official_sl1_clubs():
    """
    Create the 14 official Premier League clubs if they are missing.

    Existing clubs are matched by short name, then full name.
    Tokens, managers, squads and history are not overwritten.
    """

    league = ensure_super_league_1()
    created = []
    reused = []

    for name, short_name in OFFICIAL_SL1_CLUBS:
        team = (
            Team.objects.filter(short_name__iexact=short_name).order_by("id").first()
            or Team.objects.filter(name__iexact=name).order_by("id").first()
        )
        if team is None:
            team = Team.objects.create(
                name=name,
                short_name=short_name,
                league=league,
                tokens=STARTING_TOKENS,
                manager=None,
            )
            created.append(team)
            continue

        fields = []
        if team.name != name:
            team.name = name
            fields.append("name")
        if team.short_name != short_name:
            team.short_name = short_name
            fields.append("short_name")
        if team.league_id != league.id:
            team.league = league
            fields.append("league")
        if fields:
            team.save(update_fields=fields)
        reused.append(team)

    return league, created, reused
