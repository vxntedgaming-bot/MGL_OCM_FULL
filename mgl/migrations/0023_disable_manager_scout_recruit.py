from django.db import migrations, models


def disable_manager_scout_recruit(apps, schema_editor):
    LeagueSettings = apps.get_model("mgl", "LeagueSettings")
    LeagueSettings.objects.update(scout_can_recruit=False)


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0022_ufl_copy_sweep"),
    ]

    operations = [
        migrations.AlterField(
            model_name="leaguesettings",
            name="scout_can_recruit",
            field=models.BooleanField(
                default=False,
                help_text="Legacy scout-to-squad claim. Managers cannot use this. Owner/Admin only.",
            ),
        ),
        migrations.RunPython(disable_manager_scout_recruit, migrations.RunPython.noop),
    ]
