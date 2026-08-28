from django.db import migrations


def promote_premier_league(apps, schema_editor):
    League = apps.get_model("leagues", "League")

    premier = (
        League.objects.filter(short_name__iexact="PL").order_by("id").first()
        or League.objects.filter(name__iexact="Premier League").order_by("id").first()
        or League.objects.filter(short_name__iexact="SL1").order_by("id").first()
        or League.objects.filter(name__iexact="Super League 1").order_by("id").first()
    )
    if premier is None:
        premier = League.objects.create(
            name="Premier League",
            short_name="PL",
            season="1",
            is_active=True,
        )
    else:
        premier.name = "Premier League"
        premier.short_name = "PL"
        premier.is_active = True
        premier.save(update_fields=["name", "short_name", "is_active"])

    for name, short_name in (("Championship", "CH"), ("League One", "L1")):
        row = (
            League.objects.filter(short_name__iexact=short_name).order_by("id").first()
            or League.objects.filter(name__iexact=name).order_by("id").first()
        )
        if row is None:
            League.objects.create(name=name, short_name=short_name, season="1", is_active=True)
        else:
            row.name = name
            row.short_name = short_name
            row.is_active = True
            row.save(update_fields=["name", "short_name", "is_active"])

    keep = {"PL", "CH", "L1"}
    League.objects.exclude(short_name__in=keep).update(is_active=False)


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("leagues", "0002_consolidate_super_league_1"),
        ("teams", "0004_official_sl1_clubs"),
    ]

    operations = [
        migrations.RunPython(promote_premier_league, noop),
    ]
