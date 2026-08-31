from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0017_historical_season_snapshots"),
    ]

    operations = [
        migrations.AddField(
            model_name="pressconference",
            name="available_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="rewardtransaction",
            name="reference",
            field=models.CharField(blank=True, db_index=True, default="", max_length=120),
        ),
        migrations.AddConstraint(
            model_name="rewardtransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("reference", ""), _negated=True),
                fields=("manager", "category", "reference"),
                name="unique_reward_reference",
            ),
        ),
        migrations.CreateModel(
            name="WeeklyAwardBatch",
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
                ("week_start", models.DateField(unique=True)),
                ("notes", models.TextField(blank=True)),
                ("completed", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
