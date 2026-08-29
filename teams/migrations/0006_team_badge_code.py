from django.db import migrations, models


OFFICIAL_CODES = (
    "RMA",
    "BAR",
    "ATM",
    "MUN",
    "CHE",
    "MCI",
    "ARS",
    "LIV",
    "TOT",
    "PSG",
    "OL",
    "OM",
    "B04",
    "FCB",
)


def snapshot_official_badge_codes(apps, schema_editor):
    """Pin official crests to the existing club that currently holds that code."""
    Team = apps.get_model("teams", "Team")
    used = set()
    for team in Team.objects.order_by("id"):
        code = (team.short_name or "").strip().upper()
        if code not in OFFICIAL_CODES or code in used:
            continue
        team.badge_code = code
        team.save(update_fields=["badge_code"])
        used.add(code)


def clear_badge_codes(apps, schema_editor):
    Team = apps.get_model("teams", "Team")
    Team.objects.exclude(badge_code="").update(badge_code="")


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0005_team_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="badge_code",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Frozen official crest key. Display fallback only. "
                    "Site Management never changes this when name or short_name is edited."
                ),
                max_length=20,
            ),
        ),
        migrations.RunPython(snapshot_official_badge_codes, clear_badge_codes),
    ]
