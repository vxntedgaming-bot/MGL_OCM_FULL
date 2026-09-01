from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def seed_catalogue(apps, schema_editor):
    RecruitmentPack = apps.get_model("mgl", "RecruitmentPack")
    ScoutLevelConfig = apps.get_model("mgl", "ScoutLevelConfig")
    packs = (
        ("GK", "3x GK PACK", ["GK"], 0),
        ("CB", "3x CB PACK", ["CB"], 1),
        ("FB", "3x RB/LB PACK", ["RB", "LB"], 2),
        ("DM", "3x CDM/CM PACK", ["CDM", "CM"], 3),
        ("WM", "3x RM/LM PACK", ["RM", "LM"], 4),
        ("CAM", "3x CAM PACK", ["CAM"], 5),
        ("WING", "3x LW/RW PACK", ["LW", "RW"], 6),
        ("ST", "3x ST PACK", ["ST", "CF"], 7),
    )
    for code, name, positions, order in packs:
        RecruitmentPack.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "pack_type": "POSITION",
                "active": True,
                "token_cost": Decimal("1.00"),
                "result_count": 3,
                "select_count": 1,
                "min_ovr": None,
                "max_ovr": 74,
                "positions": positions,
                "opening_limit": None,
                "sort_order": order,
            },
        )
    levels = (
        (1, Decimal("0.00"), Decimal("0.00")),
        (2, Decimal("18.00"), Decimal("0.00")),
        (3, Decimal("25.00"), Decimal("0.00")),
        (4, Decimal("25.00"), Decimal("0.00")),
    )
    for level, cost, percent in levels:
        ScoutLevelConfig.objects.get_or_create(
            level=level,
            defaults={
                "upgrade_cost": cost,
                "time_reduction_percent": percent,
                "result_count": 4,
                "select_count": 1,
            },
        )


def unseed_catalogue(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("mgl", "0027_ufl_roster_30"),
        ("players", "0009_player_dob_playstyles"),
        ("teams", "0007_team_is_ufl_starter"),
        ("managers", "0004_manager_tokens_auctions_scouting"),
    ]

    operations = [
        migrations.CreateModel(
            name="RecruitmentPack",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=80)),
                ("pack_type", models.CharField(blank=True, default="POSITION", max_length=20)),
                ("active", models.BooleanField(default=True)),
                ("token_cost", models.DecimalField(decimal_places=2, default=1, max_digits=8)),
                ("result_count", models.PositiveSmallIntegerField(default=3)),
                ("select_count", models.PositiveSmallIntegerField(default=1)),
                ("min_ovr", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("max_ovr", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("positions", models.JSONField(blank=True, default=list)),
                (
                    "opening_limit",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Max openings per manager for this pack. Blank = unlimited.",
                        null=True,
                    ),
                ),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"ordering": ["sort_order", "name", "id"]},
        ),
        migrations.CreateModel(
            name="ScoutLevelConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("level", models.PositiveSmallIntegerField(unique=True)),
                ("upgrade_cost", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                ("time_reduction_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("result_count", models.PositiveSmallIntegerField(default=4)),
                ("select_count", models.PositiveSmallIntegerField(default=1)),
            ],
            options={"ordering": ["level"]},
        ),
        migrations.AddField(
            model_name="leaguesettings",
            name="scout_result_count",
            field=models.PositiveSmallIntegerField(default=4),
        ),
        migrations.AddField(
            model_name="leaguesettings",
            name="scout_select_count",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="recruitmentopening",
            name="pack",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="openings",
                to="mgl.recruitmentpack",
            ),
        ),
        migrations.AlterField(
            model_name="recruitmentopening",
            name="pack_code",
            field=models.CharField(max_length=20),
        ),
        migrations.AddField(
            model_name="scoutassignment",
            name="player_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(seed_catalogue, unseed_catalogue),
    ]
