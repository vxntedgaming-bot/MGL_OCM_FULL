import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def collapse_duplicate_active_scouts(apps, schema_editor):
    ScoutAssignment = apps.get_model("mgl", "ScoutAssignment")
    extras = []
    seen = {}
    for row in ScoutAssignment.objects.filter(
        status__in=["PENDING", "READY", "OPENED"]
    ).order_by("started_at", "id"):
        if row.manager_id in seen:
            extras.append(row.pk)
        else:
            seen[row.manager_id] = row.pk
    if extras:
        ScoutAssignment.objects.filter(pk__in=extras).update(
            status="COMPLETE",
            completed_at=timezone.now(),
        )


class Migration(migrations.Migration):

    dependencies = [
        ("mgl", "0019_ocm_integrity_awards_audit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="rewardtransaction",
            name="balance_before",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=8, null=True
            ),
        ),
        migrations.AddField(
            model_name="rewardtransaction",
            name="balance_after",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=8, null=True
            ),
        ),
        migrations.AddField(
            model_name="rewardtransaction",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="token_adjustments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="rewardtransaction",
            name="reverses",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reversed_by_rows",
                to="mgl.rewardtransaction",
            ),
        ),
        migrations.AddField(
            model_name="rewardtransaction",
            name="reversed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RemoveConstraint(
            model_name="rewardtransaction",
            name="unique_reward_reference",
        ),
        migrations.AddConstraint(
            model_name="rewardtransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("reference", ""), _negated=True)
                & models.Q(("reversed_at__isnull", True)),
                fields=("manager", "category", "reference"),
                name="unique_reward_reference",
            ),
        ),
        migrations.RunPython(
            collapse_duplicate_active_scouts, migrations.RunPython.noop
        ),
        migrations.RemoveConstraint(
            model_name="scoutassignment",
            name="unique_active_scout_tier_per_manager",
        ),
        migrations.AddConstraint(
            model_name="scoutassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["PENDING", "READY", "OPENED"])),
                fields=("manager",),
                name="unique_active_scout_per_manager",
            ),
        ),
    ]
