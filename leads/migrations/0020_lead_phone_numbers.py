from django.db import migrations, models


def backfill_phone_numbers(apps, schema_editor):
    Lead = apps.get_model("leads", "Lead")
    for lead in Lead.objects.all().iterator():
        pn = (getattr(lead, "phone_number", None) or "").strip()
        existing = getattr(lead, "phone_numbers", None)
        if pn and not (isinstance(existing, list) and len(existing) > 0):
            lead.phone_numbers = [pn[:64]]
            lead.save(update_fields=["phone_numbers"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0019_search_country"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="phone_numbers",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Ordered E.164-style numbers (+60…); first is primary. Max 8.",
            ),
        ),
        migrations.RunPython(backfill_phone_numbers, migrations.RunPython.noop),
    ]
