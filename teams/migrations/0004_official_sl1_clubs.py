from decimal import Decimal

from django.db import migrations


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


def create_official_sl1_clubs(apps, schema_editor):
    League = apps.get_model("leagues", "League")
    Team = apps.get_model("teams", "Team")

    league = (
        League.objects.filter(short_name__iexact="SL1").order_by("id").first()
        or League.objects.filter(name__iexact="Super League 1").order_by("id").first()
    )
    if league is None:
        league = League.objects.create(
            name="Super League 1",
            short_name="SL1",
            season="1",
            is_active=True,
        )

    for name, short_name in OFFICIAL_SL1_CLUBS:
        team = (
            Team.objects.filter(short_name__iexact=short_name).order_by("id").first()
            or Team.objects.filter(name__iexact=name).order_by("id").first()
        )
        if team is None:
            Team.objects.create(
                name=name,
                short_name=short_name,
                league=league,
                tokens=Decimal("50.00"),
                manager=None,
            )
            continue
        fields = []
        if team.name != name:
            team.name = name
            fields.append("name")
        if team.short_name != short_name:
            team.short_name = short_name
            fields.append("short_name")
        if team.league_id != league.id:
            team.league_id = league.id
            fields.append("league")
        if fields:
            team.save(update_fields=fields)


def noop(apps, schema_editor):
    """Keep official clubs if this migration is reversed."""
    return


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0003_ocm_market"),
        ("leagues", "0002_consolidate_super_league_1"),
    ]

    operations = [
        migrations.RunPython(create_official_sl1_clubs, noop),
    ]
