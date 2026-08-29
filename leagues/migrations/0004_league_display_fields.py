from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leagues", "0003_premier_league_structure"),
    ]

    operations = [
        migrations.AddField(
            model_name="league",
            name="display_name",
            field=models.CharField(
                blank=True,
                help_text="Public label. Canonical name/short_name stay unchanged so league structure is not rewritten.",
                max_length=100,
            ),
        ),
        migrations.AddField(
            model_name="league",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="league",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="leagues/"),
        ),
        migrations.AddField(
            model_name="league",
            name="display_order",
            field=models.PositiveSmallIntegerField(default=0),
        ),
    ]
