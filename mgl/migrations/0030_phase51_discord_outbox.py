from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0029_phase4_job_release"),
    ]

    operations = [
        migrations.AddField(
            model_name="discordevent",
            name="idempotency_key",
            field=models.CharField(blank=True, max_length=200, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="discordevent",
            name="next_attempt_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddIndex(
            model_name="discordevent",
            index=models.Index(
                fields=["status", "next_attempt_at"],
                name="mgl_disco_status_next_idx",
            ),
        ),
    ]
