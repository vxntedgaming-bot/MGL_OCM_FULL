from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("players", "0008_player_fc26_attributes"),
        ("mgl", "0011_notification_actions"),
    ]

    operations = [
        migrations.AddField(
            model_name="playerlisting",
            name="offered_player",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="listings_as_swap_offer",
                to="players.player",
            ),
        ),
    ]
