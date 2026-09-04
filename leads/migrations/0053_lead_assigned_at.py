# Assigned-at timestamp for when a lead's owner last changed.

from django.db import migrations, models
from django.db.models import F


def backfill_assigned_at(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    Lead.objects.filter(assigned_to__isnull=False, assigned_at__isnull=True).update(
        assigned_at=F("created_at")
    )


def noop_reverse(apps, schema_editor):
    return None


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0052_ready_system_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="assigned_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When assigned_to was last set. Cleared when the lead is unassigned.",
                null=True,
            ),
        ),
        migrations.RunPython(backfill_assigned_at, noop_reverse),
    ]
