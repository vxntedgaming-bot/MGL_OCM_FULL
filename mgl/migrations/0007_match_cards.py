import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0006_press_and_job_application_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="teammatchstats",
            name="yellow_cards",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[django.core.validators.MaxValueValidator(11)],
            ),
        ),
        migrations.AddField(
            model_name="teammatchstats",
            name="red_cards",
            field=models.PositiveSmallIntegerField(
                default=0,
                validators=[django.core.validators.MaxValueValidator(11)],
            ),
        ),
        migrations.AlterField(
            model_name="gksave",
            name="saves",
            field=models.PositiveSmallIntegerField(
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(20),
                ]
            ),
        ),
    ]
