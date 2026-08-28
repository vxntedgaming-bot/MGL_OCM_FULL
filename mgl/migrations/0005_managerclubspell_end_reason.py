from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0004_manager_scout_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="managerclubspell",
            name="end_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("RESIGNED", "Resigned"),
                    ("REMOVED", "Removed"),
                    ("REASSIGNED", "Reassigned"),
                ],
                max_length=20,
            ),
        ),
    ]
