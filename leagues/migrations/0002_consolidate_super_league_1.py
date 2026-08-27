from django.db import migrations


def consolidate_super_league_1(apps, schema_editor):
    League = apps.get_model("leagues", "League")
    Team = apps.get_model("teams", "Team")
    Fixture = apps.get_model("mgl", "Fixture")

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
    else:
        league.name = "Super League 1"
        league.short_name = "SL1"
        league.is_active = True
        league.save(update_fields=["name", "short_name", "is_active"])

    League.objects.exclude(pk=league.pk).update(is_active=False)
    Team.objects.exclude(league_id=league.id).update(league=league)
    Fixture.objects.exclude(league_id=league.id).update(league=league)


def noop(apps, schema_editor):
    """Keep Super League 2 rows; do not delete leagues on reverse."""
    return


class Migration(migrations.Migration):

    dependencies = [
        ("leagues", "0001_initial"),
        ("teams", "0003_ocm_market"),
        ("mgl", "0002_ocm_market"),
    ]

    operations = [
        migrations.RunPython(consolidate_super_league_1, noop),
    ]
