"""Official 42-club UFL structure.

Premier League keeps the existing 14 clubs. Championship and League One are
filled with real football clubs when missing. Existing club IDs, managers,
squads and tokens are never overwritten. Extra clubs are not deleted.
"""

from decimal import Decimal

from leagues.services import ensure_premier_league
from teams.models import Team
from teams.official_sl1 import OFFICIAL_SL1_CLUBS, OFFICIAL_SL1_SHORT_NAMES, ensure_official_sl1_clubs

STARTING_TOKENS = Decimal("50.00")

OFFICIAL_CH_CLUBS = (
    ("Leeds United", "LEE"),
    ("Leicester City", "LEI"),
    ("Southampton", "SOU"),
    ("Ipswich Town", "IPS"),
    ("Norwich City", "NOR"),
    ("West Bromwich Albion", "WBA"),
    ("Middlesbrough", "MID"),
    ("Coventry City", "COV"),
    ("Sunderland", "SUN"),
    ("Sheffield United", "SHU"),
    ("Watford", "WAT"),
    ("Millwall", "MIL"),
    ("Hull City", "HUL"),
    ("Stoke City", "STK"),
)

OFFICIAL_L1_CLUBS = (
    ("Birmingham City", "BCG"),
    ("Wrexham", "WRX"),
    ("Bolton Wanderers", "BOL"),
    ("Charlton Athletic", "CHA"),
    ("Huddersfield Town", "HUD"),
    ("Reading", "RDG"),
    ("Barnsley", "BRS"),
    ("Blackpool", "BLP"),
    ("Peterborough United", "POS"),
    ("Stockport County", "STP"),
    ("Lincoln City", "LIN"),
    ("Wycombe Wanderers", "WYC"),
    ("Leyton Orient", "LEY"),
    ("Exeter City", "EXE"),
)

OFFICIAL_CH_SHORT_NAMES = tuple(short for _name, short in OFFICIAL_CH_CLUBS)
OFFICIAL_L1_SHORT_NAMES = tuple(short for _name, short in OFFICIAL_L1_CLUBS)


def _ensure_club_list(league, clubs):
    created = []
    reused = []
    for name, short_name in clubs:
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
    return created, reused


def ensure_official_ufl_clubs():
    """Create missing official clubs. Never deletes clubs or applies squads."""
    from leagues.models import League

    premier, sl1_created, sl1_reused = ensure_official_sl1_clubs()
    championship = League.objects.filter(short_name__iexact="CH").first()
    league_one = League.objects.filter(short_name__iexact="L1").first()
    ensure_premier_league()
    championship = League.objects.filter(short_name__iexact="CH").first()
    league_one = League.objects.filter(short_name__iexact="L1").first()
    ch_created, ch_reused = _ensure_club_list(championship, OFFICIAL_CH_CLUBS)
    l1_created, l1_reused = _ensure_club_list(league_one, OFFICIAL_L1_CLUBS)
    return {
        "premier": premier,
        "created": sl1_created + ch_created + l1_created,
        "reused": sl1_reused + ch_reused + l1_reused,
        "counts": {
            "PL": Team.objects.filter(short_name__in=OFFICIAL_SL1_SHORT_NAMES).count(),
            "CH": Team.objects.filter(short_name__in=OFFICIAL_CH_SHORT_NAMES).count(),
            "L1": Team.objects.filter(short_name__in=OFFICIAL_L1_SHORT_NAMES).count(),
        },
    }
