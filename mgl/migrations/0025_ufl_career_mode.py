from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def enable_ufl_career_defaults(apps, schema_editor):
    LeagueSettings = apps.get_model("mgl", "LeagueSettings")
    LeagueSettings.objects.update(
        allow_manager_auctions=True,
        scout_can_recruit=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("mgl", "0024_starting_squad_proposals"),
    ]

    operations = [
        migrations.AddField(
            model_name="leaguesettings",
            name="auction_listings_per_24h",
            field=models.PositiveSmallIntegerField(default=3),
        ),
        migrations.AddField(
            model_name="leaguesettings",
            name="press_per_24h",
            field=models.PositiveSmallIntegerField(default=4),
        ),
        migrations.AddField(
            model_name="leaguesettings",
            name="press_reward",
            field=models.DecimalField(decimal_places=2, default=0.5, max_digits=6),
        ),
        migrations.AlterField(
            model_name="leaguesettings",
            name="allow_manager_auctions",
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name="leaguesettings",
            name="scout_can_recruit",
            field=models.BooleanField(
                default=True,
                help_text="UFL scouting recruits into the manager squad when the scout returns.",
            ),
        ),
        migrations.AddField(
            model_name="playerlisting",
            name="message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="playerlisting",
            name="request_changes_note",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="country",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="outcome",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="country",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="scoutreport",
            name="outcome",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="category",
            field=models.CharField(db_index=True, default="Career", max_length=20),
        ),
        migrations.CreateModel(
            name="TransferNegotiationEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(choices=[("OFFER", "Offer"), ("COUNTER", "Counter"), ("ACCEPT", "Accept"), ("REJECT", "Reject"), ("WITHDRAW", "Withdraw"), ("CHANGES", "Request changes"), ("APPROVE", "Approve")], max_length=16)),
                ("token_amount", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ("message", models.TextField(blank=True)),
                ("swap_summary", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transfer_negotiation_events", to=settings.AUTH_USER_MODEL)),
                ("listing", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="negotiation_events", to="mgl.playerlisting")),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
        migrations.CreateModel(
            name="ScoutSquadException",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("ASSIGNED", "Assigned"), ("RELEASED", "Released")], default="PENDING", max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("assignment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="squad_exception", to="mgl.scoutassignment")),
                ("club", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scout_exceptions", to="teams.team")),
                ("manager", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scout_exceptions", to="managers.managerapplication")),
                ("player", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="scout_exceptions", to="players.player")),
                ("resolved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scout_exceptions_resolved", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.RunPython(enable_ufl_career_defaults, migrations.RunPython.noop),
    ]
