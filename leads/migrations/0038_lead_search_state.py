from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("leads", "0037_lead_whatsapp_batches"),
    ]

    operations = [
        migrations.AddField(
            model_name="searchqueryrecord",
            name="search_state",
            field=models.CharField(
                blank=True,
                default="",
                help_text="State / region used for the hunt.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="search_state",
            field=models.CharField(
                blank=True,
                help_text="State / region from the Serper hunt that captured this lead.",
                max_length=255,
                null=True,
            ),
        ),
    ]
