from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("players", "0008_player_fc26_attributes"),
        ("mgl", "0012_listing_offered_player"),
    ]

    operations = [
        migrations.AddField(
            model_name="playerlisting",
            name="offered_players",
            field=models.ManyToManyField(
                blank=True,
                related_name="listings_offered_in",
                to="players.player",
            ),
        ),
    ]
