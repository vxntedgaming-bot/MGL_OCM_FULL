from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_league_settings_and_branding(apps, schema_editor):
    LeagueSettings = apps.get_model("mgl", "LeagueSettings")
    if not LeagueSettings.objects.exists():
        LeagueSettings.objects.create()
    SiteContent = apps.get_model("mgl", "SiteContent")
    replacements = {
        "settings.site_name": ("Meta Gaming League", "Ultimate Fantasy League"),
        "settings.site_tagline": ("Online Career Mode", "Your Club. Your Decisions. Your Legacy."),
        "home.hero_subtitle": (
            "Build your club. Manage your squad. Compete against real managers in Meta Gaming League Online Career Mode.",
            "Build your squad. Negotiate transfers. Compete against real managers. Build your career.",
        ),
        "home.join_text": (
            "Join MGL and take control of your club.",
            "Join UFL and take control of your club.",
        ),
    }
    for key, (old, new) in replacements.items():
        row = SiteContent.objects.filter(key=key).first()
        if row and (not row.value or row.value == old):
            row.value = new
            row.save(update_fields=["value"])


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0020_token_ledger_one_scout"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="scoutprofile",
            name="judging_ability",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="scoutprofile",
            name="judging_potential",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="scoutprofile",
            name="position_knowledge",
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.AddField(
            model_name="scoutprofile",
            name="discovery_rate",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="scoutprofile",
            name="report_accuracy",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="scoutprofile",
            name="scouting_speed",
            field=models.PositiveSmallIntegerField(default=2),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="duration_hours",
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="token_cost",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=8),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="reveal_stage",
            field=models.CharField(default="HIDDEN", max_length=12),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="estimated_ovr_low",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="estimated_ovr_high",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="estimated_potential_low",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="estimated_potential_high",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="confidence",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="confidence",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="recommendation",
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="estimated_potential_low",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="estimated_potential_high",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="LeagueSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("starting_tokens", models.DecimalField(decimal_places=2, default=20, max_digits=8)),
                ("max_squad_size", models.PositiveSmallIntegerField(default=28)),
                ("starting_squad_size", models.PositiveSmallIntegerField(default=25)),
                ("max_active_listings", models.PositiveSmallIntegerField(default=5)),
                ("listings_per_24h", models.PositiveSmallIntegerField(default=3)),
                ("allow_manager_auctions", models.BooleanField(default=False)),
                (
                    "scout_can_recruit",
                    models.BooleanField(
                        default=True,
                        help_text="Legacy scout-to-squad claim. UFL Career Mode should turn this off.",
                    ),
                ),
                ("scout_requires_tokens", models.BooleanField(default=False)),
                ("max_scouts_per_club", models.PositiveSmallIntegerField(default=1)),
                ("auction_durations", models.CharField(default="30,60,90,120", max_length=80)),
                ("scout_durations", models.CharField(default="1,3,6,12,24,48,72", max_length=80)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="league_settings_edits",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"verbose_name": "League settings"},
        ),
        migrations.CreateModel(
            name="DiscordEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("event_type", models.CharField(db_index=True, max_length=40)),
                ("channel_key", models.CharField(default="NEWS", max_length=40)),
                ("payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[("PENDING", "Pending"), ("SENT", "Sent"), ("FAILED", "Failed")],
                        db_index=True,
                        default="PENDING",
                        max_length=12,
                    ),
                ),
                ("attempt_count", models.PositiveSmallIntegerField(default=0)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("error", models.TextField(blank=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "news_post",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="discord_events",
                        to="mgl.newspost",
                    ),
                ),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.AddIndex(
            model_name="discordevent",
            index=models.Index(fields=["status", "created_at"], name="mgl_disco_status_created_idx"),
        ),
        migrations.CreateModel(
            name="PlayerReleaseRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("APPROVED", "Approved"),
                            ("REJECTED", "Rejected"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "manager",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="release_requests",
                        to="managers.managerapplication",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="release_requests",
                        to="players.player",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="player_releases_reviewed",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "team",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="release_requests",
                        to="teams.team",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="playerreleaserequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "PENDING")),
                fields=("player",),
                name="unique_pending_player_release",
            ),
        ),
        migrations.CreateModel(
            name="ScoutWatchlist",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notes", models.CharField(blank=True, max_length=240)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "manager",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="scout_watchlist",
                        to="managers.managerapplication",
                    ),
                ),
                (
                    "player",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="watchlisted_by",
                        to="players.player",
                    ),
                ),
                (
                    "report",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="watchlist_rows",
                        to="mgl.scoutreport",
                    ),
                ),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="scoutwatchlist",
            constraint=models.UniqueConstraint(
                fields=("manager", "player"),
                name="unique_scout_watchlist_player",
            ),
        ),
        migrations.RunPython(seed_league_settings_and_branding, migrations.RunPython.noop),
    ]
