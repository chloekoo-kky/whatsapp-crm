from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0030_alter_lead_whatsapp_instance_id_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="send_cooldown_enabled",
            field=models.BooleanField(
                default=True,
                help_text="When on, the campaign daemon waits between successful queue sends.",
            ),
        ),
        migrations.AddField(
            model_name="whatsappconfig",
            name="send_cooldown_seconds",
            field=models.PositiveSmallIntegerField(
                default=10,
                help_text="Seconds to wait after each successful queue send (1–3600).",
            ),
        ),
    ]
