from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("managers", "0004_manager_tokens_auctions_scouting"),
        ("mgl", "0010_managernotification"),
    ]

    operations = [
        migrations.AddField(
            model_name="matchsubmission",
            name="opponent_response",
            field=models.CharField(
                blank=True,
                choices=[
                    ("PENDING", "Pending"),
                    ("APPROVED", "Approved"),
                    ("REJECTED", "Rejected"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="matchsubmission",
            name="opponent_responded_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="matchsubmission",
            name="opponent_responded_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="opponent_match_responses",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="playerlisting",
            name="reserved_buyer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="transfer_offers",
                to="managers.managerapplication",
            ),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="actioned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="details",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="fixture",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="manager_notifications",
                to="mgl.fixture",
            ),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="listing",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="manager_notifications",
                to="mgl.playerlisting",
            ),
        ),
        migrations.AddField(
            model_name="managernotification",
            name="response_status",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "None"),
                    ("PENDING", "Pending"),
                    ("ACCEPTED", "Accepted"),
                    ("REJECTED", "Rejected"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
