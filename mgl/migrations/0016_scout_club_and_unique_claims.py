import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0015_scout_elite_tier"),
        ("teams", "0006_team_badge_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoutassignment",
            name="club",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="scout_assignments",
                to="teams.team",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoutassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("status__in", ["PENDING", "READY", "OPENED"]),
                    ("player__isnull", False),
                ),
                fields=("player",),
                name="unique_active_scout_player",
            ),
        ),
        migrations.AddConstraint(
            model_name="scoutassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["PENDING", "READY", "OPENED"])),
                fields=("manager", "tier"),
                name="unique_active_scout_tier_per_manager",
            ),
        ),
    ]
