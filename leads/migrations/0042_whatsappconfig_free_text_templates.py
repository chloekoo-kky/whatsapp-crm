from django.db import migrations, models


def migrate_single_template_to_list(apps, schema_editor):
    WhatsAppConfig = apps.get_model("leads", "WhatsAppConfig")
    for config in WhatsAppConfig.objects.all():
        old_text = (getattr(config, "free_text_template", None) or "").strip()
        if old_text:
            config.free_text_templates = [{"label": "Template 1", "text": old_text}]
            config.save(update_fields=["free_text_templates"])


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0041_whatsappconfig_free_text_template"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="free_text_templates",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Up to 3 Active Chat reply templates ({label, text}). Supports {{ name }} and {{ area }}.",
            ),
        ),
        migrations.RunPython(migrate_single_template_to_list, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="whatsappconfig",
            name="free_text_template",
        ),
    ]
