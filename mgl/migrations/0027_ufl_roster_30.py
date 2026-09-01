from django.db import migrations, models


def align_league_settings(apps, schema_editor):
    LeagueSettings = apps.get_model("mgl", "LeagueSettings")
    LeagueSettings.objects.filter(max_squad_size__lt=30).update(max_squad_size=30)
    LeagueSettings.objects.filter(starting_squad_size__lt=30).update(starting_squad_size=30)


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0026_recruitment_opening"),
    ]

    operations = [
        migrations.AlterField(
            model_name="leaguesettings",
            name="max_squad_size",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AlterField(
            model_name="leaguesettings",
            name="starting_squad_size",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.AlterField(
            model_name="startingsquadproposal",
            name="squad_size",
            field=models.PositiveSmallIntegerField(default=30),
        ),
        migrations.RunPython(align_league_settings, migrations.RunPython.noop),
    ]
