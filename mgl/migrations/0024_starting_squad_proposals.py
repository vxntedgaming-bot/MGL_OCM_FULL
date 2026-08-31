from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0023_disable_manager_scout_recruit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StartingSquadProposal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("seed", models.BigIntegerField()),
                ("include_free_agents", models.BooleanField(default=False)),
                ("club_count", models.PositiveIntegerField(default=0)),
                ("players_required", models.PositiveIntegerField(default=0)),
                ("players_available", models.PositiveIntegerField(default=0)),
                ("rating_min", models.PositiveSmallIntegerField(default=64)),
                ("rating_max", models.PositiveSmallIntegerField(default=69)),
                ("squad_size", models.PositiveSmallIntegerField(default=25)),
                ("average_league_ovr", models.DecimalField(decimal_places=3, default=0, max_digits=6)),
                ("largest_avg_diff", models.DecimalField(decimal_places=3, default=0, max_digits=6)),
                ("max_allowed_avg_diff", models.DecimalField(decimal_places=3, default=1.5, max_digits=6)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("DRAFT", "Draft"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                            ("SUPERSEDED", "Superseded"),
                        ],
                        default="DRAFT",
                        max_length=12,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("validation", models.JSONField(blank=True, default=dict)),
                ("notes", models.JSONField(blank=True, default=list)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="starting_squad_approvals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="starting_squad_proposals",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "rejected_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="starting_squad_rejections",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="StartingSquadLock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season", models.PositiveIntegerField(unique=True)),
                ("approved_at", models.DateTimeField()),
                ("club_count", models.PositiveIntegerField(default=0)),
                ("players_assigned", models.PositiveIntegerField(default=0)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="starting_squad_locks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "proposal",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="season_lock",
                        to="mgl.startingsquadproposal",
                    ),
                ),
            ],
            options={"ordering": ["-season"]},
        ),
    ]
