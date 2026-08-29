import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("teams", "0006_team_badge_code"),
        ("players", "0008_player_fc26_attributes"),
        ("mgl", "0009_site_content_and_changelog"),
    ]

    operations = [
        migrations.CreateModel(
            name="ManagerNotification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("source_key", models.CharField(max_length=120)),
                ("notification_type", models.CharField(max_length=40)),
                ("title", models.CharField(max_length=160)),
                ("message", models.TextField()),
                ("actor", models.CharField(blank=True, max_length=160)),
                ("action_url", models.CharField(blank=True, max_length=400)),
                ("action_label", models.CharField(blank=True, max_length=40)),
                ("is_action", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                (
                    "player",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="manager_notifications",
                        to="players.player",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="manager_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="manager_notifications",
                        to="teams.team",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="managernotification",
            constraint=models.UniqueConstraint(
                fields=("recipient", "source_key"),
                name="unique_manager_notification_key",
            ),
        ),
        migrations.AddIndex(
            model_name="managernotification",
            index=models.Index(
                fields=["recipient", "read_at"],
                name="mgl_manager_recipie_419c8c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="managernotification",
            index=models.Index(
                fields=["recipient", "created_at"],
                name="mgl_manager_recipie_d6cbf7_idx",
            ),
        ),
    ]
