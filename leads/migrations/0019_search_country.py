from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leads", "0018_lead_is_very_important"),
    ]

    operations = [
        migrations.AddField(
            model_name="searchqueryrecord",
            name="search_country",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Optional country used to disambiguate the Serper hunt.",
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name="lead",
            name="search_country",
            field=models.CharField(
                blank=True,
                help_text="Country used for the Serper hunt that captured this lead (optional).",
                max_length=255,
                null=True,
            ),
        ),
    ]
