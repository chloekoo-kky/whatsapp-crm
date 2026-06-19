from django.db import migrations, models


def bootstrap_pipeline_groups(apps, schema_editor):
    LeadGroup = apps.get_model("leads", "LeadGroup")
    Lead = apps.get_model("leads", "Lead")

    legacy_junk = LeadGroup.objects.filter(name="Junk").first()
    if legacy_junk:
        legacy_junk.name = "🚫 Trash"
        legacy_junk.sort_order = 2
        legacy_junk.save(update_fields=["name", "sort_order"])
        trash = legacy_junk
    else:
        trash, _ = LeadGroup.objects.get_or_create(
            name="🚫 Trash",
            defaults={"sort_order": 2},
        )

    uncategorized, _ = LeadGroup.objects.get_or_create(
        name="Uncategorized",
        defaults={"sort_order": 0},
    )
    queue, _ = LeadGroup.objects.get_or_create(
        name="queue",
        defaults={"sort_order": 1},
    )

    LeadGroup.objects.filter(pk=uncategorized.pk).update(sort_order=0)
    LeadGroup.objects.filter(pk=queue.pk).update(sort_order=1)
    LeadGroup.objects.filter(pk=trash.pk).update(sort_order=2)

    Lead.objects.filter(group__isnull=True).update(group_id=uncategorized.pk)

    Lead.objects.filter(whatsapp_status="pending").exclude(group_id=queue.pk).update(
        whatsapp_status="idle",
        whatsapp_last_error="",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0025_whatsappconfig"),
    ]

    operations = [
        migrations.AlterField(
            model_name="lead",
            name="whatsapp_status",
            field=models.CharField(
                choices=[
                    ("idle", "Idle"),
                    ("pending", "Pending Queue"),
                    ("processing", "Processing"),
                    ("sent", "First Message Sent"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="idle",
                help_text="Outbound first-touchpoint automator queue state.",
                max_length=16,
            ),
        ),
        migrations.RunPython(bootstrap_pipeline_groups, migrations.RunPython.noop),
    ]
