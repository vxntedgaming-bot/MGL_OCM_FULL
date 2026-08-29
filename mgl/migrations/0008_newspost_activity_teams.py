from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0004_official_sl1_clubs"),
        ("mgl", "0007_match_cards"),
    ]

    operations = [
        migrations.AddField(
            model_name="newspost",
            name="primary_team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="news_as_primary",
                to="teams.team",
            ),
        ),
        migrations.AddField(
            model_name="newspost",
            name="secondary_team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="news_as_secondary",
                to="teams.team",
            ),
        ),
    ]
