from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0006_team_badge_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="is_ufl_starter",
            field=models.BooleanField(
                default=False,
                help_text="True for official UFL Season 1 starter clubs (16 Premier League / 14 Championship / 8 League One).",
            ),
        ),
    ]
