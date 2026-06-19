from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0026_lead_whatsapp_idle_and_system_groups"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppScriptTemplate",
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
                    "group_name",
                    models.CharField(
                        help_text="Industry folder label (e.g. Aesthetic, Clinics, General Outreach).",
                        max_length=100,
                        unique=True,
                    ),
                ),
                (
                    "template_text",
                    models.TextField(
                        blank=True,
                        default="",
                        help_text="Message body with {{ name }} and {{ area }} placeholders.",
                    ),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "WhatsApp script template",
                "verbose_name_plural": "WhatsApp script templates",
                "db_table": "leads_whatsappscripttemplate",
                "ordering": ["group_name"],
            },
        ),
    ]
