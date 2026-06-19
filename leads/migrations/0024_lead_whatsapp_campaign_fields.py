from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0023_chainbrandstatus"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="whatsapp_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending Queue"),
                    ("processing", "Processing"),
                    ("sent", "First Message Sent"),
                    ("failed", "Failed"),
                ],
                db_index=True,
                default="pending",
                help_text="Outbound first-touchpoint automator queue state.",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="whatsapp_sent_at",
            field=models.DateTimeField(
                blank=True,
                help_text="When the first automated WhatsApp message was dispatched.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="whatsapp_instance_id",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Evolution API instance name used for the outbound send.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="whatsapp_last_error",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Last Evolution API / network error for automated WhatsApp dispatch.",
            ),
        ),
    ]
