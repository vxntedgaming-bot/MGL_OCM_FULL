from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("teams", "0004_official_sl1_clubs"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="description",
            field=models.TextField(
                blank=True,
                help_text="Optional public club description. Display only; does not affect squads or fixtures.",
            ),
        ),
    ]
