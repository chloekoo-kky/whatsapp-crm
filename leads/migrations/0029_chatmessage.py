from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0028_whatsappconfig_outbound_template"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "body",
                    models.TextField(
                        help_text="Rendered message text shown in the chat drawer."
                    ),
                ),
                (
                    "is_outbound",
                    models.BooleanField(
                        default=False,
                        help_text="True for CRM/Meta template sends; false for client replies.",
                    ),
                ),
                (
                    "template_name",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Meta template name when this row is an outbound template send.",
                        max_length=64,
                    ),
                ),
                (
                    "meta_message_id",
                    models.CharField(
                        blank=True,
                        db_index=True,
                        default="",
                        help_text="WhatsApp message id from Meta webhooks (dedupe inbound).",
                        max_length=128,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "lead",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chat_messages",
                        to="leads.lead",
                    ),
                ),
            ],
            options={
                "verbose_name": "Chat message",
                "verbose_name_plural": "Chat messages",
                "db_table": "leads_chatmessage",
                "ordering": ["created_at", "id"],
            },
        ),
    ]
