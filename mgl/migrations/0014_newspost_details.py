from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0013_listing_offered_players"),
    ]

    operations = [
        migrations.AddField(
            model_name="newspost",
            name="details",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
