from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0014_newspost_details"),
    ]

    operations = [
        migrations.AlterField(
            model_name="scoutassignment",
            name="tier",
            field=models.CharField(
                choices=[
                    ("BRONZE", "Bronze"),
                    ("SILVER", "Silver"),
                    ("GOLD", "Gold"),
                    ("ELITE", "Elite"),
                ],
                max_length=10,
            ),
        ),
    ]
