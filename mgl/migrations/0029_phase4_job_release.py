from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0028_recruitment_economy"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="clubapplication",
            constraint=models.UniqueConstraint(
                fields=("manager",),
                condition=models.Q(status="PENDING"),
                name="unique_pending_club_application",
            ),
        ),
    ]
