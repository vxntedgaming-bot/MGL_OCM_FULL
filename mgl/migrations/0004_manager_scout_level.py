from django.db import migrations, models
import django.db.models.deletion


def copy_manager_scout_level(apps, schema_editor):
    ScoutProfile = apps.get_model("mgl", "ScoutProfile")
    for profile in ScoutProfile.objects.all():
        old = max(
            profile.bronze_level or 0,
            profile.silver_level or 0,
            profile.gold_level or 0,
        )
        if old <= 0:
            new_level = 1
        elif old == 1:
            new_level = 2
        else:
            new_level = 3
        profile.scout_level = new_level
        profile.save(update_fields=["scout_level"])


def reverse_manager_scout_level(apps, schema_editor):
    ScoutProfile = apps.get_model("mgl", "ScoutProfile")
    for profile in ScoutProfile.objects.all():
        level = profile.scout_level or 1
        old = 0 if level <= 1 else 1 if level == 2 else 2
        profile.bronze_level = old
        profile.silver_level = old
        profile.gold_level = old
        profile.save(update_fields=["bronze_level", "silver_level", "gold_level"])


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0003_manager_tokens_auctions_scouting"),
        ("teams", "0004_official_sl1_clubs"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoutprofile",
            name="scout_level",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.RunPython(copy_manager_scout_level, reverse_manager_scout_level),
        migrations.RemoveField(
            model_name="scoutprofile",
            name="bronze_level",
        ),
        migrations.RemoveField(
            model_name="scoutprofile",
            name="silver_level",
        ),
        migrations.RemoveField(
            model_name="scoutprofile",
            name="gold_level",
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="recruited",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="club",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scout_recruits",
                to="teams.team",
            ),
        ),
        migrations.AlterField(
            model_name="scoutassignment",
            name="level",
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
