# Generated for multi-batch lead assignment.

import django.db.models.deletion
from django.db import migrations, models


def copy_fk_to_m2m(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    for lead in Lead.objects.exclude(whatsapp_batch__isnull=True).iterator():
        lead.whatsapp_batches.add(lead.whatsapp_batch_id)


def copy_m2m_to_fk(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    for lead in Lead.objects.exclude(whatsapp_batches__isnull=True).iterator():
        first = lead.whatsapp_batches.order_by("scheduled_at", "id").first()
        if first is not None:
            lead.whatsapp_batch_id = first.pk
            lead.save(update_fields=["whatsapp_batch"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0036_remove_whatsappbatchschedule_lead_count_and_more"),
    ]

    operations = [
        # Drop the FK's reverse accessor ("leads") first so the new M2M can
        # claim it without a reverse-accessor clash in the intermediate state.
        migrations.AlterField(
            model_name="lead",
            name="whatsapp_batch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="leads.whatsappbatchschedule",
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="whatsapp_batches",
            field=models.ManyToManyField(
                blank=True,
                help_text="Scheduled batches this lead is part of (assigned from the Queue).",
                related_name="leads",
                to="leads.whatsappbatchschedule",
            ),
        ),
        migrations.RunPython(copy_fk_to_m2m, copy_m2m_to_fk),
        migrations.RemoveField(
            model_name="lead",
            name="whatsapp_batch",
        ),
    ]
