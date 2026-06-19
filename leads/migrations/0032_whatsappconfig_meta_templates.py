from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0031_whatsappconfig_send_cooldown"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="meta_message_templates",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Last synced Meta message_templates catalog (approved outbound).",
            ),
        ),
        migrations.AddField(
            model_name="whatsappconfig",
            name="meta_templates_synced_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When meta_message_templates was last refreshed from Meta Graph API.",
                null=True,
            ),
        ),
    ]
