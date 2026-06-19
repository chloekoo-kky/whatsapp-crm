import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0024_lead_whatsapp_campaign_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "allowed_days",
                    models.JSONField(
                        default=list,
                        help_text="ISO weekdays when sending is allowed (Monday=1 … Sunday=7).",
                    ),
                ),
                ("window1_start", models.TimeField(default=datetime.time(8, 0))),
                ("window1_end", models.TimeField(default=datetime.time(13, 0))),
                ("window2_start", models.TimeField(default=datetime.time(15, 0))),
                ("window2_end", models.TimeField(default=datetime.time(20, 0))),
                (
                    "is_paused",
                    models.BooleanField(
                        default=False,
                        help_text="Master kill-switch for the campaign daemon.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "WhatsApp campaign config",
                "verbose_name_plural": "WhatsApp campaign config",
                "db_table": "leads_whatsappconfig",
            },
        ),
    ]
