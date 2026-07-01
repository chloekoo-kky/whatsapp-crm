from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0038_lead_search_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="whatsappconfig",
            name="force_send_template_name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Meta template used by the Send now (⚡) button on group folder cards.",
                max_length=64,
            ),
        ),
    ]
